"""Test-only helpers for running the upstream launcher on an owned socket."""
import socket


def bind_test_listener():
    """Reserve an ephemeral loopback listener until the test closes it."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        return listener
    except BaseException:
        listener.close()
        raise


def write_uvicorn_shim(directory):
    """Create a subprocess-only shim; the installed upstream remains unchanged."""
    path = directory / 'sitecustomize.py'
    path.write_text('''\
import os

# Python normally only logs sitecustomize errors and continues startup. Exit
# instead, so a broken shim can never fall through to the real fixed port.
try:
    import socket
    import uvicorn
    int(os.environ["OWL_TEST_LISTEN_FD"])
except BaseException:
    os._exit(121)

# The test still runs the real upstream __main__ and verifies its defaults.
def run_on_test_socket(app, *args, **kwargs):
    if kwargs.get("host") != "127.0.0.1" or kwargs.get("port") != 7187:
        raise RuntimeError("upstream default bind changed")
    listener = socket.socket(fileno=int(os.environ["OWL_TEST_LISTEN_FD"]))
    try:
        config = uvicorn.Config(app, *args, **kwargs)
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()

uvicorn.run = run_on_test_socket
''')
    return path
