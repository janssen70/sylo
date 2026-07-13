import asyncio
import socket

import pytest

from sylo.receiver.config import ReceiverConfig
from sylo.receiver.server import SyslogServer


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_udp_end_to_end(tmp_path):
    port = free_port()
    config = ReceiverConfig(
        bind_host="127.0.0.1",
        udp_port=port,
        tcp_port=free_port(),
        data_dir=tmp_path,
        flush_idle_seconds=0.05,
        fsync_interval_seconds=0.1,
    )
    server = SyslogServer(config)
    await server.start()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b"<34>Oct 11 22:14:15 mymachine su: hello over udp", ("127.0.0.1", port))
        sock.close()
        await asyncio.sleep(0.3)
    finally:
        await server.stop()

    files = list((tmp_path / "127.0.0.1").glob("*.log"))
    assert len(files) == 1
    assert "hello over udp" in files[0].read_text()


@pytest.mark.asyncio
async def test_tcp_end_to_end(tmp_path):
    udp_port = free_port()
    tcp_port = free_port()
    config = ReceiverConfig(
        bind_host="127.0.0.1",
        udp_port=udp_port,
        tcp_port=tcp_port,
        data_dir=tmp_path,
        flush_idle_seconds=0.05,
        fsync_interval_seconds=0.1,
    )
    server = SyslogServer(config)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", tcp_port)
        writer.write(b"<34>Oct 11 22:14:15 mymachine su: hello over tcp\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.3)
    finally:
        await server.stop()

    files = list((tmp_path / "127.0.0.1").glob("*.log"))
    assert len(files) == 1
    assert "hello over tcp" in files[0].read_text()
