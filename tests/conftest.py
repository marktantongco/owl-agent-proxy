#!/usr/bin/env python3
"""
🦉 OWL-AGENT — test hygiene.

These tests must behave identically on a laptop with no egress and on a CI
runner with full internet. An earlier revision relied on the network being
*unreachable* (the honeypot detector fails open when no baseline can be
established), which passed locally and failed on GitHub Actions — exactly the
kind of environment-dependent test that erodes trust in a suite.

So: outbound connections to anything other than loopback are blocked by
default. A test that genuinely needs the internet must opt in with
``@pytest.mark.allow_network``.
"""
import socket

import pytest

_LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "allow_network: test needs real outbound network access"
    )


def _is_loopback(address) -> bool:
    if not isinstance(address, tuple) or not address:
        # AF_UNIX / already-connected sockets are not outbound network access
        return True
    host = address[0]
    if not isinstance(host, str):
        return True
    return host in _LOOPBACK or host.startswith("127.") or host.startswith("::1")


@pytest.fixture(autouse=True)
def block_outbound_network(request, monkeypatch):
    """Fail loudly instead of silently depending on the runner's connectivity."""
    if request.node.get_closest_marker("allow_network"):
        return

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guard(original):
        def wrapper(self, address, *args, **kwargs):
            if not _is_loopback(address):
                raise OSError(
                    f"test attempted outbound network access to {address!r}; "
                    "monkeypatch the dependency or mark the test allow_network"
                )
            return original(self, address, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(socket.socket, "connect", guard(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(real_connect_ex))
