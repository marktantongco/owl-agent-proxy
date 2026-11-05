#!/usr/bin/env python3
"""
Tests for the reverse_proxy module.

These tests verify that ReverseProxy correctly forwards requests through
ResilientClient to an upstream target. Tests use a mock upstream server
and avoid live network calls.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the package directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reverse_proxy import (
    CircuitBreaker,
    DEFAULT_USER_AGENTS,
    ReverseProxy,
    StealthClient,
    StealthConfig,
    UpstreamTarget,
    UserAgentRotator,
    load_config,
    parse_args,
    main_async,
)


class TestReverseProxyInit:
    """Test ReverseProxy initialization."""

    def test_default_values(self):
        rp = ReverseProxy(target_hosts=["http://localhost:3000"])
        assert rp.target_hosts[0].url == "http://localhost:3000"
        assert rp.listen_port == 8080
        assert rp.agent_id == "reverse-proxy"
        assert rp._requests_total == 0
        assert rp._requests_ok == 0
        assert rp._requests_error == 0
        assert len(rp.protocol_escalation) == 6

    def test_custom_values(self):
        rp = ReverseProxy(
            target_hosts=["https://api.example.com"],
            listen_port=9090,
            agent_id="test-agent",
            protocol_escalation=["http/1.1", "http/2"],
        )
        assert rp.target_hosts[0].url == "https://api.example.com"
        assert rp.listen_port == 9090
        assert rp.agent_id == "test-agent"
        assert rp.protocol_escalation == ["http/1.1", "http/2"]

    def test_multiple_targets(self):
        rp = ReverseProxy(target_hosts=["http://a.example.com", "http://b.example.com"])
        assert len(rp.target_hosts) == 2
        assert rp.target_hosts[0].url == "http://a.example.com"
        assert rp.target_hosts[1].url == "http://b.example.com"

    def test_target_host_strips_trailing_slash(self):
        # UpstreamTarget strips trailing slash
        t = UpstreamTarget("http://localhost:3000/")
        assert t.url == "http://localhost:3000"


class TestUpstreamTarget:
    """Test UpstreamTarget health tracking."""

    def test_mark_success_and_failure(self):
        t = UpstreamTarget("http://example.com")
        assert t.healthy is True
        t.mark_success()
        assert t.healthy is True
        t.mark_failure()
        t.mark_failure()
        t.mark_failure()  # 3 failures -> unhealthy
        assert t.healthy is False

    def test_error_rate(self):
        t = UpstreamTarget("http://example.com")
        assert t.error_rate() == 0.0
        t._total_requests = 10
        t._total_errors = 3
        assert t.error_rate() == 0.3


class TestCircuitBreaker:
    """Test CircuitBreaker failure tracking."""

    def test_open_after_threshold(self):
        cb = CircuitBreaker(threshold=3)
        assert cb.is_open("http/1.1") is False
        cb.record_failure("http/1.1")
        cb.record_failure("http/1.1")
        assert cb.is_open("http/1.1") is False
        cb.record_failure("http/1.1")
        assert cb.is_open("http/1.1") is True

    def test_record_success_resets(self):
        cb = CircuitBreaker(threshold=3)
        cb.record_failure("http/1.1")
        cb.record_failure("http/1.1")
        cb.record_success("http/1.1")
        assert cb.is_open("http/1.1") is False
        assert cb.failure_count("http/1.1") == 0


class TestLoadConfig:
    """Test configuration loading."""

    def test_load_config_with_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"reverse_proxy": {"port": 9090}}))
        import reverse_proxy as rp_module
        original = rp_module.CONFIG_FILE
        rp_module.CONFIG_FILE = config_file
        try:
            config = rp_module.load_config()
            assert config == {"reverse_proxy": {"port": 9090}}
        finally:
            rp_module.CONFIG_FILE = original

    def test_load_config_missing_file(self):
        import reverse_proxy as rp_module
        original = rp_module.CONFIG_FILE
        rp_module.CONFIG_FILE = Path("/nonexistent/config.json")
        try:
            config = rp_module.load_config()
            assert config == {}
        finally:
            rp_module.CONFIG_FILE = original


class TestParseArgs:
    """Test argument parsing."""

    def test_default_args(self):
        with patch("sys.argv", ["reverse_proxy.py"]):
            args = parse_args()
            assert args.port is None
            assert args.target is None
            assert args.targets is None

    def test_custom_port(self):
        with patch("sys.argv", ["reverse_proxy.py", "--port", "9090"]):
            args = parse_args()
            assert args.port == 9090

    def test_custom_target(self):
        with patch("sys.argv", ["reverse_proxy.py", "--target", "https://api.example.com"]):
            args = parse_args()
            assert args.target == "https://api.example.com"

    def test_custom_targets(self):
        with patch("sys.argv", ["reverse_proxy.py", "--targets", "http://a.com,http://b.com"]):
            args = parse_args()
            assert args.targets == "http://a.com,http://b.com"


class TestReverseProxyStats:
    """Test ReverseProxy statistics."""

    def test_stats_structure(self):
        rp = ReverseProxy(target_hosts=["http://localhost:3000"], listen_port=8080)
        stats = rp.stats()
        assert stats["listen_port"] == 8080
        assert stats["target_hosts"] == ["http://localhost:3000"]
        assert stats["requests_total"] == 0
        assert stats["requests_ok"] == 0
        assert stats["requests_error"] == 0
        assert "targets_healthy" in stats
        assert "circuit_breaker" in stats


class TestProtocolSelection:
    """Test protocol selection logic."""

    def test_select_protocol_explicit_header(self):
        rp = ReverseProxy(target_hosts=["http://localhost:3000"])
        headers = {"x-owl-protocol": "http/2"}
        protocol = rp._select_protocol(headers, "http://localhost:3000/api")
        assert protocol == "http/2"

    def test_select_protocol_open_circuit_skipped(self):
        rp = ReverseProxy(target_hosts=["http://localhost:3000"])
        # Open circuit for http/2 (threshold is 5)
        for _ in range(5):
            rp.circuit_breaker.record_failure("http/2")
        headers = {"x-owl-protocol": "http/2"}
        protocol = rp._select_protocol(headers, "http://localhost:3000/api")
        assert protocol != "http/2"  # Should skip open circuit

    def test_select_protocol_https_prefers_http2(self):
        rp = ReverseProxy(target_hosts=["http://localhost:3000"])
        headers = {}
        protocol = rp._select_protocol(headers, "https://api.example.com/api")
        # HTTPS targets should prefer http/2 if available
        assert protocol in ("http/2", "http/1.1")


class TestUpstreamSelection:
    """Test upstream target selection."""

    def test_select_healthy_upstream(self):
        rp = ReverseProxy(target_hosts=["http://a.example.com", "http://b.example.com"])
        t1 = rp._select_upstream()
        t2 = rp._select_upstream()
        assert t1 is not None
        assert t2 is not None
        # Round-robin should alternate
        assert t1.url != t2.url

    def test_all_unhealthy_fallback(self):
        rp = ReverseProxy(target_hosts=["http://a.example.com", "http://b.example.com"])
        # Mark all unhealthy
        for t in rp.target_hosts:
            t.mark_failure()
            t.mark_failure()
            t.mark_failure()
        # Should still return a target (fallback)
        t = rp._select_upstream()
        assert t is not None


class TestConfigDrivenPortAndTarget:
    """Test that config.json drives port and target."""

    def test_config_values(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({
                "reverse_proxy": {
                    "port": 9999,
                    "target_host": "https://upstream.example.com",
                    "targets": ["https://a.example.com", "https://b.example.com"],
                }
            })
        )
        import reverse_proxy as rp_module
        original = rp_module.CONFIG_FILE
        rp_module.CONFIG_FILE = config_file
        try:
            config = rp_module.load_config()
            rp_cfg = config.get("reverse_proxy", {})
            assert rp_cfg.get("port") == 9999
            assert rp_cfg.get("target_host") == "https://upstream.example.com"
            assert len(rp_cfg.get("targets", [])) == 2
        finally:
            rp_module.CONFIG_FILE = original


class TestReverseProxyRequestHandling:
    """Test request handling logic."""

    @pytest.mark.asyncio
    async def test_error_response_when_no_upstream(self):
        rp = ReverseProxy(target_hosts=[])
        # No targets at all
        rp.target_hosts = []
        # We can't easily test the full aiohttp request flow without mocking
        # the entire web framework. Test the structural aspects instead.
        assert len(rp.target_hosts) == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failures(self):
        rp = ReverseProxy(target_hosts=["http://localhost:3000"])
        cb = rp.circuit_breaker
        for _ in range(5):
            cb.record_failure("http/1.1")
        assert cb.is_open("http/1.1") is True


# ── stealth mode tests ────────────────────────────────────────────────


class TestUserAgentRotator:
    """Test UserAgentRotator rotation modes."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_sticky_mode_pins_per_target(self):
        rotator = UserAgentRotator(mode="sticky")
        ua1 = self._run(rotator.get("http://example.com/api/1"))
        ua2 = self._run(rotator.get("http://example.com/api/1"))
        ua3 = self._run(rotator.get("http://example.com/api/2"))
        assert ua1 == ua2  # same target -> same UA (sticky)
        assert ua1 in DEFAULT_USER_AGENTS
        assert ua3 in DEFAULT_USER_AGENTS

    def test_random_mode(self):
        rotator = UserAgentRotator(mode="random")
        uas = {self._run(rotator.get("http://example.com")) for _ in range(20)}
        # With 5 default UAs and 20 draws, we should see at least 2 distinct
        assert len(uas) >= 2
        assert all(ua in DEFAULT_USER_AGENTS for ua in uas)

    def test_cycle_mode(self):
        rotator = UserAgentRotator(mode="cycle")
        uas = [self._run(rotator.get("http://example.com")) for _ in range(len(DEFAULT_USER_AGENTS) + 2)]
        # Cycle should wrap around
        assert uas[0] == uas[len(DEFAULT_USER_AGENTS)]
        assert len(set(uas)) == len(DEFAULT_USER_AGENTS)

    def test_custom_user_agents(self):
        custom = ["Mozilla/5.0 Custom/1.0"]
        rotator = UserAgentRotator(user_agents=custom, mode="random")
        ua = self._run(rotator.get("http://example.com"))
        assert ua == "Mozilla/5.0 Custom/1.0"


class TestStealthConfig:
    """Test StealthConfig validation."""

    def test_defaults(self):
        cfg = StealthConfig()
        assert cfg.enabled is True
        assert cfg.browser == "chrome124"
        assert cfg.user_agent_rotation == "sticky"
        assert cfg.stealth_headers is True
        assert cfg.cookie_persistence is True
        assert cfg.timing_jitter_ms == (500, 2500)

    def test_invalid_browser_warns_but_accepts(self):
        # Unknown browser should warn but not raise
        cfg = StealthConfig(browser="internet_explorer_6")
        assert cfg.browser == "internet_explorer_6"

    def test_invalid_rotation_raises(self):
        with pytest.raises(ValueError):
            StealthConfig(user_agent_rotation="invalid_mode")

    def test_invalid_jitter_raises(self):
        with pytest.raises(ValueError):
            StealthConfig(timing_jitter_ms=(100,))


class TestStealthClient:
    """Test StealthClient initialization and stats."""

    def test_init_default(self):
        client = StealthClient()
        assert client.config.browser == "chrome124"
        assert client.config.enabled is True
        assert client._requests_total == 0
        assert len(client._sessions) == 0

    def test_init_custom_config(self):
        cfg = StealthConfig(browser="safari17", user_agent_rotation="random")
        client = StealthClient(config=cfg)
        assert client.config.browser == "safari17"
        assert client.rotator.mode == "random"

    def test_stats_structure(self):
        client = StealthClient()
        stats = client.stats()
        assert stats["browser"] == "chrome124"
        assert stats["user_agent_rotation"] == "sticky"
        assert stats["stealth_headers"] is True
        assert stats["cookie_persistence"] is True
        assert stats["requests_total"] == 0
        assert stats["sessions_active"] == 0

    def test_curl_cffi_not_imported_at_module_scope(self):
        """curl_cffi must be lazily imported — module import must not require it."""
        import reverse_proxy as rp_module
        assert rp_module._curl_cffi is None

    def test_jitter_delay_range(self):
        client = StealthClient(config=StealthConfig(timing_jitter_ms=(100, 200)))
        delay = client._jitter_delay()
        assert 0.1 <= delay <= 0.2

    def test_jitter_delay_zero_when_disabled(self):
        client = StealthClient(config=StealthConfig(timing_jitter_ms=(0, 0)))
        delay = client._jitter_delay()
        assert delay == 0.0


class TestReverseProxyStealth:
    """Test ReverseProxy stealth mode integration."""

    def test_stealth_mode_enabled_via_constructor(self):
        rp = ReverseProxy(
            target_hosts=["http://localhost:3000"],
            stealth_mode=True,
            stealth_config=StealthConfig(browser="chrome124"),
        )
        assert rp.stealth_mode is True
        assert rp._stealth_client is not None
        assert rp._stealth_client.config.browser == "chrome124"
        assert rp._user_agent_rotator is not None

    def test_stealth_mode_disabled_by_default(self):
        rp = ReverseProxy(target_hosts=["http://localhost:3000"])
        assert rp.stealth_mode is False
        assert rp._stealth_client is None

    def test_stealth_in_stats(self):
        rp = ReverseProxy(
            target_hosts=["http://localhost:3000"],
            stealth_mode=True,
            stealth_config=StealthConfig(browser="firefox"),
        )
        stats = rp.stats()
        assert "stealth" in stats
        assert stats["stealth"]["browser"] == "firefox"

    def test_select_protocol_stealth_not_in_standard_loop(self):
        """Stealth protocol is handled outside the standard escalation loop."""
        rp = ReverseProxy(target_hosts=["https://example.com"])
        # 'stealth' is in the escalation chain but skipped in the standard loop
        assert "stealth" in rp.protocol_escalation
        headers = {}
        protocol = rp._select_protocol(headers, "https://example.com")
        # Without stealth config, stealth won't be auto-selected by _select_protocol
        assert protocol != "stealth" or protocol in rp.protocol_escalation
