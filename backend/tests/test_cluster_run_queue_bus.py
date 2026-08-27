"""Payload routing for queue wake-ups."""

import unittest

from app.services.cluster.run_queue_bus import QueueWakeBus, is_for_me


class PayloadRoutingTests(unittest.TestCase):
    def test_a_payload_naming_this_instance_wakes_it(self) -> None:
        self.assertTrue(is_for_me("worker-a", instance_id="worker-a"))

    def test_a_payload_for_another_instance_is_ignored(self) -> None:
        self.assertFalse(is_for_me("worker-b", instance_id="worker-a"))

    def test_whitespace_is_tolerated(self) -> None:
        self.assertTrue(is_for_me("  worker-a  ", instance_id="worker-a"))

    def test_an_empty_payload_is_ignored(self) -> None:
        self.assertFalse(is_for_me("", instance_id="worker-a"))


class WakeBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_matching_payload_sets_the_wake_flag(self) -> None:
        bus = QueueWakeBus(instance_id="worker-a")
        self.assertTrue(bus.handle_payload("worker-a"))

    async def test_a_foreign_payload_does_not_set_the_wake_flag(self) -> None:
        bus = QueueWakeBus(instance_id="worker-a")
        self.assertFalse(bus.handle_payload("worker-b"))

    async def test_wait_returns_immediately_once_notified(self) -> None:
        """A notify that arrives before the wait must not be lost."""
        bus = QueueWakeBus(instance_id="worker-a")
        bus.handle_payload("worker-a")
        await bus.wait_for_work()

    async def test_wait_clears_the_flag_so_the_next_wait_blocks(self) -> None:
        bus = QueueWakeBus(instance_id="worker-a")
        bus.handle_payload("worker-a")
        await bus.wait_for_work()
        self.assertFalse(bus.has_pending_wake())
