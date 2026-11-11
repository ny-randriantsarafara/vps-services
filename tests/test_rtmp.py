import socket
import struct
import sys
import threading
import time
import unittest

from helpers import FILES

sys.path.insert(0, str(FILES))

from vps_platform.rtmp import (  # noqa: E402
    RTMP_VERSION,
    client_handshake,
    loopback_rtmp_handshake,
)


def _s0_s1_s2():
    s0 = bytes([RTMP_VERSION])
    s1 = struct.pack(">I", 0) + b"\x00\x00\x00\x00" + bytes(1528)
    s2 = bytes(1536)
    return s0 + s1 + s2


class FakeRtmpServer:
    def __init__(self, answer):
        self.answer = answer
        self.thread = None
        self.sock = None

    def __enter__(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.sock = listener
        port = listener.getsockname()[1]

        def serve():
            connection, _ = listener.accept()
            try:
                connection.settimeout(5)
                payload = connection.recv(4096)
                if len(payload) >= 1537 and self.answer is not None:
                    connection.sendall(self.answer)
            finally:
                connection.close()

        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        self.port = port
        return self

    def __exit__(self, *args):
        if self.sock:
            self.sock.close()
        if self.thread:
            self.thread.join(timeout=2)


class RtmpProbeTests(unittest.TestCase):
    def test_correct_s0_succeeds(self):
        with FakeRtmpServer(_s0_s1_s2()) as server:
            self.assertTrue(loopback_rtmp_handshake(f"127.0.0.1:{server.port}", timeout=2))

    def test_wrong_first_byte_fails(self):
        with FakeRtmpServer(bytes([0x09])) as server:
            self.assertFalse(loopback_rtmp_handshake(f"127.0.0.1:{server.port}", timeout=2))

    def test_silence_until_timeout_fails(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def stall():
            connection, _ = listener.accept()
            time.sleep(3)
            connection.close()

        thread = threading.Thread(target=stall, daemon=True)
        thread.start()
        try:
            self.assertFalse(loopback_rtmp_handshake(f"127.0.0.1:{port}", timeout=0.3))
        finally:
            listener.close()
            thread.join(timeout=5)

    def test_oversized_answer_still_checks_s0(self):
        with FakeRtmpServer(_s0_s1_s2() + b"x" * 8192) as server:
            self.assertTrue(loopback_rtmp_handshake(f"127.0.0.1:{server.port}", timeout=2))

    def test_client_handshake_shape(self):
        payload = client_handshake()
        self.assertEqual(len(payload), 1537)
        self.assertEqual(payload[0], RTMP_VERSION)


if __name__ == "__main__":
    unittest.main()
