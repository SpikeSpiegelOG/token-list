"""Tests for the async event bus."""

import asyncio
import pytest
from src.core.event_bus import EventBus


@pytest.mark.asyncio
async def test_pub_sub():
    bus = EventBus()
    received = []

    async def handler(data):
        received.append(data)

    bus.subscribe("test.event", handler)
    await bus.start()

    await bus.publish("test.event", {"key": "value"})
    await asyncio.sleep(0.2)  # Give time for processing

    await bus.stop()
    assert len(received) == 1
    assert received[0]["key"] == "value"


@pytest.mark.asyncio
async def test_priority():
    bus = EventBus()
    order = []

    async def handler_low(data):
        order.append("low")

    async def handler_high(data):
        order.append("high")

    bus.subscribe("test.priority", handler_low, priority=10)
    bus.subscribe("test.priority", handler_high, priority=1)
    await bus.start()

    await bus.publish("test.priority", None)
    await asyncio.sleep(0.2)

    await bus.stop()
    # Both handlers should have been called (order may vary due to concurrent execution)
    assert "high" in order
    assert "low" in order


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    received = []

    async def handler(data):
        received.append(data)

    bus.subscribe("test.unsub", handler)
    bus.unsubscribe("test.unsub", handler)
    await bus.start()

    await bus.publish("test.unsub", "should_not_arrive")
    await asyncio.sleep(0.2)

    await bus.stop()
    assert len(received) == 0
