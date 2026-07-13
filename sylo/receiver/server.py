from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .config import ReceiverConfig
from .device_writer import DeviceRegistry
from .envelope import RawMessage
from ..indexer.config import IndexerConfig
from ..indexer.core import Indexer
from ..stats import QueueStats, StatsRegistry

logger = logging.getLogger("sylo.receiver.server")


class SyslogUDPProtocol(asyncio.DatagramProtocol):
    """datagram_received runs on the event loop -- device-id extraction (the
    source IP, handed to us free by asyncio) plus a non-blocking enqueue,
    nothing else (plan line 17)."""

    def __init__(self, registry: DeviceRegistry) -> None:
        self._registry = registry

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        source_ip, source_port = addr[0], addr[1]
        raw_message = RawMessage(
            raw=data,
            receipt_time=datetime.now(timezone.utc),
            source_ip=source_ip,
            source_port=source_port,
            transport="udp",
        )
        self._registry.get_or_create(source_ip).enqueue(raw_message)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UDP socket error: %s", exc)


async def _handle_tcp_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    registry: DeviceRegistry,
    max_line_bytes: int,
) -> None:
    peer = writer.get_extra_info("peername")
    source_ip, source_port = (peer[0], peer[1]) if peer else ("unknown", 0)
    device_writer = registry.get_or_create(source_ip)
    try:
        while True:
            try:
                line = await reader.readuntil(b"\n")
            except asyncio.IncompleteReadError as exc:
                line = exc.partial
                if not line:
                    break
            except asyncio.LimitOverrunError:
                # Line exceeded the stream's internal buffer limit; drain and
                # drop it rather than let a bad client stall/OOM us.
                line = await reader.read(max_line_bytes)
                logger.warning("device %s sent oversized TCP line, dropping", source_ip)
                if not line:
                    break
                continue
            if not line:
                break
            device_writer.enqueue(
                RawMessage(
                    raw=line.rstrip(b"\r\n"),
                    receipt_time=datetime.now(timezone.utc),
                    source_ip=source_ip,
                    source_port=source_port,
                    transport="tcp",
                )
            )
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


class SyslogServer:
    def __init__(self, config: ReceiverConfig, indexer_config: IndexerConfig | None = None) -> None:
        self._config = config
        self._indexer_config = indexer_config or IndexerConfig.from_env()
        self._executor = ThreadPoolExecutor(
            max_workers=config.executor_workers, thread_name_prefix="sylo-writer"
        )
        self.stats = StatsRegistry()
        self.indexer_stats = QueueStats()
        self._indexer: Indexer | None = None
        self._registry: DeviceRegistry | None = None
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._tcp_server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._indexer = Indexer(self._indexer_config, self.indexer_stats, loop)
        self._indexer.start()
        self._registry = DeviceRegistry(self._config, self._executor, self.stats, loop, self._indexer)

        self._udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: SyslogUDPProtocol(self._registry),
            local_addr=(self._config.bind_host, self._config.udp_port),
        )
        logger.info("UDP listening on %s:%d", self._config.bind_host, self._config.udp_port)

        self._tcp_server = await asyncio.start_server(
            lambda r, w: _handle_tcp_connection(r, w, self._registry, self._config.tcp_max_line_bytes),
            host=self._config.bind_host,
            port=self._config.tcp_port,
            limit=self._config.tcp_max_line_bytes,
        )
        logger.info("TCP listening on %s:%d", self._config.bind_host, self._config.tcp_port)

    async def stop(self) -> None:
        if self._udp_transport is not None:
            self._udp_transport.close()
        if self._tcp_server is not None:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
        if self._registry is not None:
            await self._registry.stop_all()
        # Stop the indexer only after device writers have drained -- they
        # forward parsed envelopes to it synchronously during their own
        # drain, so by now everything they'll ever send has been enqueued.
        if self._indexer is not None:
            await self._indexer.stop()
        self._executor.shutdown(wait=True)
