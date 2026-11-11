"""RTMP handshake probes for RTMPS routes. Standard library only."""

import os
import socket
import ssl
import struct
import time

RTMP_VERSION = 0x03
C0C1_LENGTH = 1537
S0_LENGTH = 1
PROBE_TIMEOUT_SECONDS = 10
HANDSHAKE_READ_LIMIT = 4096


def client_handshake():
    c0 = bytes([RTMP_VERSION])
    c1 = struct.pack(">I", 0) + b"\x00\x00\x00\x00" + os.urandom(1528)
    return c0 + c1


def loopback_rtmp_handshake(upstream, timeout=PROBE_TIMEOUT_SECONDS):
    host, _, port_text = upstream.rpartition(":")
    if not host or not port_text.isdigit():
        return False
    port = int(port_text)
    if not 1 <= port <= 65535:
        return False
    try:
        connection = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return False
    try:
        connection.settimeout(timeout)
        connection.sendall(client_handshake())
        return reads_rtmp_s0(connection, timeout)
    except OSError:
        return False
    finally:
        connection.close()


def public_rtmps_handshake(hostname, timeout=PROBE_TIMEOUT_SECONDS):
    context = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, 443), timeout=timeout) as plain:
            with context.wrap_socket(plain, server_hostname=hostname) as tls_socket:
                tls_socket.settimeout(timeout)
                tls_socket.sendall(client_handshake())
                return reads_rtmp_s0(tls_socket, timeout)
    except (OSError, ssl.SSLError):
        return False


def reads_rtmp_s0(connection, timeout):
    deadline = time.monotonic() + timeout
    collected = bytearray()
    while len(collected) < S0_LENGTH and time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        connection.settimeout(remaining)
        try:
            chunk = connection.recv(min(HANDSHAKE_READ_LIMIT, S0_LENGTH - len(collected)))
        except OSError:
            return False
        if not chunk:
            return False
        collected.extend(chunk)
        if len(collected) >= S0_LENGTH:
            break
    return len(collected) == S0_LENGTH and collected[0] == RTMP_VERSION
