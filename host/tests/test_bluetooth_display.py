"""BLE framing, MTU and acknowledgement regressions without an adapter."""
import asyncio
import json
import struct
from types import SimpleNamespace
import unittest

from agent_pets_habitat.bluetooth_display import RX_UUID, packet, send_snapshot, select_paired_device, connection_status


class FakeClient:
    def __init__(self, mtu, replies, result=0):
        self.mtu_size = mtu
        self.replies = replies
        self.result = result
        self.parts = []

    async def write_gatt_char(self, uuid, data, response):
        assert uuid == RX_UUID and response
        assert len(data) <= min(244, self.mtu_size - 3)
        self.parts.append(data)
        if data.endswith(b"\n"):
            sequence = json.loads(b"".join(self.parts))["tx"]
            # Ignore unrelated, malformed and old acknowledgements.
            self.replies.put_nowait(b"bad")
            self.replies.put_nowait(struct.pack("<BI", 0, sequence - 1))
            self.replies.put_nowait(struct.pack("<BI", self.result, sequence))


class BluetoothTests(unittest.IsolatedAsyncioTestCase):
    def test_bridge_status_is_versioned_and_requires_boolean(self):
        for value in (False,True):
            self.assertEqual(json.loads(connection_status(value)), {"version":1,"type":"bridge_status","backend":value})
        with self.assertRaises(ValueError):
            connection_status("false")

    def test_unpaired_saved_device_is_never_selected(self):
        self.assertIsNone(select_paired_device([], preferred="AA:01"))
        self.assertIsNone(select_paired_device([], address="AA:01"))

    def test_new_os_pairing_replaces_removed_saved_device(self):
        board = SimpleNamespace(address="AA:02", name="Agent Pets ABCD")
        headset = SimpleNamespace(address="AA:03", name="Headset")
        self.assertIs(select_paired_device([headset, board], preferred="AA:01"), board)

    def test_multiple_paired_boards_require_a_selection(self):
        first = SimpleNamespace(address="AA:01", name="Agent Pets ABCD")
        second = SimpleNamespace(address="AA:02", name="Agent Pets EFGH")
        with self.assertRaisesRegex(ValueError, "Multiple paired"):
            select_paired_device([first, second])
        self.assertIs(select_paired_device([first, second], preferred="aa:02"), second)
        self.assertIs(select_paired_device([first, second], address="aa:01"), first)

    def test_windows_rename_preserves_saved_selection(self):
        board = SimpleNamespace(address="AA:01", name="Desk habitat")
        self.assertIs(select_paired_device([board], preferred="aa:01"), board)

    async def test_fragmentation_reassembles_at_minimum_and_preferred_mtu(self):
        record = json.dumps({"version": 1, "type": "snapshot", "sessions": [{"id": "a" * 700}]}).encode()
        for mtu in (23, 247, 517):
            replies = asyncio.Queue()
            client = FakeClient(mtu, replies)
            await send_snapshot(client, record, 41, replies)
            self.assertEqual(b"".join(client.parts), packet(record, 41))
            self.assertGreater(len(client.parts), 1)

    async def test_rejection_does_not_acknowledge_scene(self):
        replies = asyncio.Queue()
        with self.assertRaisesRegex(ValueError, "rejected"):
            await send_snapshot(FakeClient(23, replies, 1), b'{"sessions":[]}', 3, replies)

    async def test_interrupted_transfer_propagates_for_reconnect(self):
        replies = asyncio.Queue()
        client = FakeClient(23, replies)
        async def fail(*args, **kwargs):
            raise OSError("link lost")
        client.write_gatt_char = fail
        with self.assertRaises(OSError):
            await send_snapshot(client, b'{"sessions":[]}', 9, replies)

    def test_added_sequence_cannot_overflow_firmware_record(self):
        with self.assertRaises(ValueError):
            packet(json.dumps({"id": "x" * 4080}), 4294967295)


if __name__ == "__main__":
    unittest.main()
