import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sylo.receiver.config import ReceiverConfig
from sylo.receiver.device_writer import DeviceRegistry
from sylo.receiver.envelope import RawMessage
from sylo.receiver.stats import StatsRegistry


def make_config(tmp_path: Path, **overrides) -> ReceiverConfig:
    defaults = dict(
        data_dir=tmp_path,
        flush_max_messages=5,
        flush_idle_seconds=0.05,
        fsync_interval_seconds=0.1,
        queue_soft_limit=3,
        queue_hard_limit=5,
    )
    defaults.update(overrides)
    return ReceiverConfig(**defaults)


def raw_message(text: bytes, ip: str = "10.0.0.1") -> RawMessage:
    return RawMessage(
        raw=text,
        receipt_time=datetime.now(timezone.utc),
        source_ip=ip,
        source_port=514,
        transport="udp",
    )


@pytest.mark.asyncio
async def test_flush_on_idle_writes_file(tmp_path):
    config = make_config(tmp_path)
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_running_loop()
    registry = DeviceRegistry(config, executor, StatsRegistry(), loop)

    writer = registry.get_or_create("10.0.0.1")
    writer.enqueue(raw_message(b"<34>Oct 11 22:14:15 host su: hello"))

    await asyncio.sleep(0.3)
    await registry.stop_all()
    executor.shutdown(wait=True)

    files = list((tmp_path / "10.0.0.1").glob("*.log"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "hello" in content
    assert content.count("\n") == 1


@pytest.mark.asyncio
async def test_flush_on_count_threshold(tmp_path):
    config = make_config(tmp_path, flush_idle_seconds=10)  # idle timer won't fire in this test
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_running_loop()
    registry = DeviceRegistry(config, executor, StatsRegistry(), loop)

    writer = registry.get_or_create("10.0.0.2")
    for i in range(5):
        writer.enqueue(raw_message(f"<34>Oct 11 22:14:15 host su: msg{i}".encode()))

    await asyncio.sleep(0.2)
    await registry.stop_all()
    executor.shutdown(wait=True)

    files = list((tmp_path / "10.0.0.2").glob("*.log"))
    assert len(files) == 1
    assert files[0].read_text().count("\n") == 5


@pytest.mark.asyncio
async def test_hard_cap_drops_without_blocking(tmp_path):
    config = make_config(tmp_path, flush_idle_seconds=10, queue_hard_limit=3, queue_soft_limit=1)
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_running_loop()
    stats_registry = StatsRegistry()
    registry = DeviceRegistry(config, executor, stats_registry, loop)

    writer = registry.get_or_create("10.0.0.3")
    # Fill well past the hard cap; enqueue must never raise/block.
    for i in range(20):
        writer.enqueue(raw_message(f"msg{i}".encode()))

    stats = stats_registry.for_device("10.0.0.3")
    assert stats.dropped > 0
    assert stats.lag_warnings > 0

    await registry.stop_all()
    executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_per_device_isolation_uses_separate_files(tmp_path):
    config = make_config(tmp_path)
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_running_loop()
    registry = DeviceRegistry(config, executor, StatsRegistry(), loop)

    registry.get_or_create("10.0.0.1").enqueue(raw_message(b"from device 1"))
    registry.get_or_create("10.0.0.2").enqueue(raw_message(b"from device 2"))

    await asyncio.sleep(0.3)
    await registry.stop_all()
    executor.shutdown(wait=True)

    assert "from device 1" in (tmp_path / "10.0.0.1").glob("*.log").__next__().read_text()
    assert "from device 2" in (tmp_path / "10.0.0.2").glob("*.log").__next__().read_text()


@pytest.mark.asyncio
async def test_ipv6_device_key_sanitized_for_filesystem(tmp_path):
    config = make_config(tmp_path)
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_running_loop()
    registry = DeviceRegistry(config, executor, StatsRegistry(), loop)

    registry.get_or_create("::1").enqueue(raw_message(b"ipv6 message", ip="::1"))
    await asyncio.sleep(0.3)
    await registry.stop_all()
    executor.shutdown(wait=True)

    assert (tmp_path / "__1").exists()
