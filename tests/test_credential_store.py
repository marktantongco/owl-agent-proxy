#!/usr/bin/env python3
"""Probes for proxy credential application.

`credential-store-rotates` claims a 407 rotates to another credential instead of
banning the proxy. Two defects made that path unreachable in practice, both
found by exercising the store rather than reading it:

1. **Key mismatch.** `CredentialStore.add(host, ...)` keys by the string the
   caller passes, and config comes through as `proxy_credentials` mapping
   whatever the operator wrote. `apply()` looks up `urlparse(proxy_url).hostname`
   — the bare host, without a port. So `{"10.0.0.1:8080": [...]}`, the form the
   URL actually uses, never matches. No credential is applied, the proxy is used
   unauthenticated, and `used_credential` stays None — which is the condition the
   407 branch tests before rotating. The rotation is dead.

2. **No percent-encoding.** `apply()` interpolates the username and password
   straight into the netloc. A password containing `/`, `?` or `#` changes the
   URL's structure; `@` changes which part is the host. Measured: a password of
   `pa/ss` produced `http://user1:pa/ss@10.0.0.1:8080`, whose port no longer
   parses at all.

Run: python tests/test_credential_store.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location(
    "proxy_defense_under_test", REPO / "proxy_defense.py"
)
pd = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
# Dataclasses resolve their annotations via sys.modules[cls.__module__], so the
# module must be registered before exec_module or they raise AttributeError.
import sys
sys.modules[_SPEC.name] = pd
_SPEC.loader.exec_module(pd)


def store_with(host: str, *creds: tuple[str, str]):
    store = pd.CredentialStore()
    for username, password in creds:
        store.add(host, username, password)
    return store


# ── 1. key resolution ─────────────────────────────────────────────────────
def test_credential_resolves_for_a_host_port_key() -> None:
    """The key format a proxy URL actually uses must work.

    `apply` returns ``(effective_url, (host_key, username))`` -- the tuple is the
    identity needed to call ``mark_failed`` later, not the password.
    """
    store = store_with("10.0.0.1:8080", ("user1", "pass1"))
    url, cred = store.apply("http://10.0.0.1:8080")
    assert cred == ("10.0.0.1:8080", "user1"), f"credential not applied; url={url}"
    assert "user1:pass1@" in url, url


def test_credential_resolves_for_a_bare_host_key() -> None:
    store = store_with("10.0.0.1", ("user1", "pass1"))
    url, cred = store.apply("http://10.0.0.1:8080")
    assert cred == ("10.0.0.1", "user1"), "bare-host key stopped working"
    assert "user1:pass1@" in url, url


def test_no_credential_for_an_unknown_host() -> None:
    store = store_with("10.0.0.1", ("user1", "pass1"))
    _, cred = store.apply("http://192.0.2.9:8080")
    assert cred is None


def test_an_existing_credential_in_the_url_is_left_alone() -> None:
    store = store_with("10.0.0.1", ("user1", "pass1"))
    url = "http://already:there@10.0.0.1:8080"  # cred-ok: fixture, no real secret
    out, cred = store.apply(url)
    assert (out, cred) == (url, None)


# ── 2. rotation, which depends on (1) ─────────────────────────────────────
def test_mark_failed_rotates_to_the_next_credential() -> None:
    store = store_with("10.0.0.1:8080", ("u1", "p1"), ("u2", "p2"))
    _, first = store.apply("http://10.0.0.1:8080")
    assert first is not None, "no credential to rotate from"
    store.mark_failed("10.0.0.1:8080", first[1])
    _, second = store.apply("http://10.0.0.1:8080")
    assert second is not None and second != first, f"did not rotate: {first} -> {second}"


# ── 3. encoding ───────────────────────────────────────────────────────────
def test_password_with_url_metacharacters_does_not_corrupt_the_url() -> None:
    for password in ("pa/ss", "pa@ss", "pa?ss", "pa#ss", "pa:ss"):
        store = store_with("10.0.0.1", ("user1", password))
        url, cred = store.apply("http://10.0.0.1:8080")
        assert cred is not None, f"{password!r}: no credential applied"
        parsed = urlparse(url)
        assert parsed.hostname == "10.0.0.1", f"{password!r}: host became {parsed.hostname!r}"
        assert parsed.port == 8080, f"{password!r}: port became {parsed.port!r}"


def test_username_with_url_metacharacters_does_not_corrupt_the_url() -> None:
    for username in ("us/er", "us@er", "us:er"):
        store = store_with("10.0.0.1", (username, "pass1"))
        url, cred = store.apply("http://10.0.0.1:8080")
        assert cred is not None, f"{username!r}: no credential applied"
        parsed = urlparse(url)
        assert parsed.hostname == "10.0.0.1", f"{username!r}: host became {parsed.hostname!r}"
        assert parsed.port == 8080, f"{username!r}: port became {parsed.port!r}"


def test_encoding_round_trips_to_the_original_secret() -> None:
    """Encoding is only correct if the server would recover the same password."""
    from urllib.parse import unquote
    store = store_with("10.0.0.1", ("user1", "p@ss:w/rd"))
    url, _ = store.apply("http://10.0.0.1:8080")
    parsed = urlparse(url)
    assert unquote(parsed.password or "") == "p@ss:w/rd", parsed.password
    assert unquote(parsed.username or "") == "user1", parsed.username


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS: {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL: {name}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"FAIL: {name}: raised {type(exc).__name__}: {exc}")
    print()
    if failures:
        print(f"FAILED: {failures} of {len(tests)} probe(s)")
        return 1
    print(f"PASSED: {len(tests)} probe(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
