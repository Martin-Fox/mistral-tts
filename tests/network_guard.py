"""Block external IP/DNS in tests and Python children; keep loopback/Unix IPC."""
from ipaddress import ip_address
import socket


def install():
    if getattr(socket, '_booksmith_network_blocked', False):
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def local_ipc(sock, address):
        if sock.family == getattr(socket, 'AF_UNIX', None):
            return True
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            try:
                return ip_address(address[0]).is_loopback
            except (ValueError, TypeError, IndexError):
                return False
        return False

    def connect(sock, address):
        if local_ipc(sock, address):
            return original_connect(sock, address)
        raise AssertionError('Network disabled in tests; use a fake API transport')

    def connect_ex(sock, address):
        if local_ipc(sock, address):
            return original_connect_ex(sock, address)
        raise AssertionError('Network disabled in tests; use a fake API transport')

    def forbidden(*args, **kwargs):
        raise AssertionError('Network/DNS disabled in tests; use a fake API transport')

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = forbidden
    socket.getaddrinfo = forbidden
    socket._booksmith_network_blocked = True


install()
