"""HID report framing, discovery and acknowledged transfer regressions."""
import json
import struct
import unittest
from unittest.mock import patch

from agent_pets_habitat.hid_display import (HidDisplay, fragments, decode_capabilities,
    decode_ack, candidates, load_hid, CAPABILITY_REPORT, TRANSFER_REPORT)


class FakeHid:
    def __init__(self):
        self.buffer = bytearray()
        self.sequence = 0
        self.result = 0
        self.fail_write = False

    def send_feature_report(self, report):
        if self.fail_write:
            return 0
        assert report[0] == TRANSFER_REPORT and len(report) == 64
        magic, flags, sequence, offset, size = struct.unpack_from("<BBIHB", report, 1)
        assert magic == 0xC1
        if flags & 1:
            self.buffer.clear()
        assert offset == len(self.buffer)
        self.buffer.extend(report[10:10 + size])
        if flags & 2:
            assert json.loads(self.buffer)["tx"] == sequence
            self.sequence = sequence
        return len(report)

    def read(self, size, timeout_ms):
        # Deliberately stale notification; status polling must recover it.
        return [1, 0xC1, 0, 0, 0, 0, 0, 1, 0]

    def get_feature_report(self, report_id, length):
        assert report_id == CAPABILITY_REPORT
        return b"\x02APH1\x01\x3f\x00\x10" + bytes([self.result]) + struct.pack("<I", self.sequence) + b"\x01\x00\x00"


class HidDisplayTests(unittest.TestCase):
    def test_linux_uses_bluetooth_capable_hidraw_backend(self):
        with patch("agent_pets_habitat.hid_display.sys.platform", "linux"), \
             patch("agent_pets_habitat.hid_display.importlib.import_module") as load:
            load_hid()
            load.assert_called_once_with("hidraw")

    def test_fragments_are_bounded_ordered_and_loss_detectable(self):
        for size in (0, 1, 53, 54, 55, 4000):
            record = json.dumps({"id": "x" * size}).encode()
            parts = list(fragments(record, 77))
            data = bytearray()
            for index, part in enumerate(parts):
                self.assertEqual(len(part), 63)
                magic, flags, tx, offset, length = struct.unpack_from("<BBIHB", part)
                self.assertEqual((magic, tx, offset), (0xC1, 77, len(data)))
                self.assertEqual(bool(flags & 1), index == 0)
                self.assertEqual(bool(flags & 2), index == len(parts) - 1)
                self.assertLessEqual(length, 54)
                data.extend(part[9:9 + length])
            self.assertEqual(json.loads(data), {"id": "x" * size, "tx": 77})

    def test_numbered_report_prefix_is_normalized(self):
        capability = b"APH1\x01\x3f\x00\x10\x00" + struct.pack("<I", 42) + b"\x01\x00\x00"
        for prefix in (b"", b"\x02"):
            self.assertEqual(decode_capabilities(prefix + capability), (0, 42))
            self.assertEqual(decode_capabilities(prefix + capability + bytes(47)), (0, 42))
        ack = b"\xc1\x00" + struct.pack("<I", 42) + b"\x01\x00"
        for prefix in (b"", b"\x01"):
            self.assertEqual(decode_ack(prefix + ack), (0, 42))
        with self.assertRaises(ValueError):
            decode_capabilities(capability.replace(b"APH1", b"BAD1"))
        self.assertIsNone(decode_ack(b"bad"))

    def test_feature_status_ack_recovers_lost_input_notification(self):
        device = FakeHid()
        display = HidDisplay(device, {"product_string": "Agent Pets"})
        display.send(b'{"sessions":[]}', 89)
        self.assertEqual(device.sequence, 89)

    def test_rejected_snapshot_and_partial_write_fail_transport(self):
        for rejected in (False, True):
            device = FakeHid()
            device.fail_write = not rejected
            device.result = 1 if rejected else 0
            display = HidDisplay(device, {})
            with self.assertRaises((OSError, ValueError)):
                display.send(b'{"sessions":[]}', 5)
            self.assertFalse(display.connected)

    def test_discovery_filters_other_collections_and_serial(self):
        entries = [{"usage_page": 1, "usage": 6},
                   {"usage_page": 0xFF00, "usage": 1, "serial_number": "one"},
                   {"usage_page": 0, "usage": 0, "serial_number": "two"}]
        class Enumeration:
            def enumerate(self, vid, pid):
                return entries
        self.assertEqual(candidates(Enumeration(), "one"), [entries[1]])
        self.assertEqual(candidates(Enumeration()), entries[1:])
