"""Regression tests for the sidecar launcher's owned test listener."""
import socket

import pytest

from launcher_test_support import bind_test_listener, write_uvicorn_shim


def test_listener_is_loopback_and_owned_until_closed():
    with bind_test_listener() as listener:
        host, port = listener.getsockname()
        assert host == '127.0.0.1'
        assert 0 < port < 65536
        with socket.socket() as competitor:
            competitor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                competitor.bind((host, port))


def test_shim_is_installed_only_in_supplied_temp_dir(tmp_path):
    path = write_uvicorn_shim(tmp_path)
    assert path == tmp_path / 'sitecustomize.py'
    text = path.read_text()
    assert 'OWL_TEST_LISTEN_FD' in text
    assert 'uvicorn.Server' in text
