"""Security regression: device reports remain application data, never PC input."""
from pathlib import Path
import re
import unittest

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware" / "AgentPets_ES3C35P"


def report_layout(descriptor):
    page = usage = report_id = count = bits = 0
    layout = {}
    applications = []
    index = 0
    while index < len(descriptor):
        prefix = descriptor[index]
        index += 1
        if prefix == 0xFE:
            raise AssertionError("Unexpected long HID item; review its input capabilities")
        size = (0, 1, 2, 4)[prefix & 3]
        data = descriptor[index:index + size]
        assert len(data) == size
        index += size
        value = int.from_bytes(data, "little")
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        if kind == 1:
            if tag == 0:
                page = value
                assert page == 0xFF00, "Standard HID usage page would enable OS input/control semantics"
            elif tag == 7: bits = value
            elif tag == 8: report_id = value
            elif tag == 9: count = value
            elif tag in (10, 11):
                raise AssertionError("Review HID global stack changes for input capabilities")
        elif kind == 2 and tag == 0:
            if size == 4:
                assert value >> 16 == 0xFF00
            usage = value & 0xFFFF
        elif kind == 0:
            if tag == 10 and value == 1:
                applications.append((page, usage))
            if tag in (8, 9, 11):
                assert page == 0xFF00
                layout[({8:"input",9:"output",11:"feature"}[tag], report_id)] = bits * count // 8
    return applications, layout


class HidDescriptorTests(unittest.TestCase):
    def test_firmware_has_only_vendor_data_reports(self):
        source = (FIRMWARE / "bluetooth_link.cpp").read_text(encoding="utf-8")
        body = re.search(r"static uint8_t reportMap\[\] = \{(.*?)\};", source, re.S).group(1)
        descriptor = bytes(int(x,16) for x in re.findall(r"0x([0-9A-Fa-f]+)",body))
        apps, layout = report_layout(descriptor)
        self.assertEqual(apps, [(0xFF00,1)])
        self.assertEqual(layout, {("input",1):8,("output",1):63,("feature",2):63,("feature",3):63})
        self.assertNotRegex(source,r"getBoot(?:Input|Output)\s*\(")

    def test_guard_rejects_keyboard_mouse_and_consumer_pages(self):
        for page in (1,7,12):
            with self.assertRaises(AssertionError):
                report_layout(bytes([0x05,page,0x09,1,0xA1,1,0xC0]))

    def test_usb_build_uses_serial_jtag_not_hid(self):
        settings = (FIRMWARE / "sketch.yaml").read_text(encoding="utf-8")
        self.assertIn("USBMode=hwcdc",settings)
        self.assertIn("CDCOnBoot=cdc",settings)
        for source in [*FIRMWARE.glob("*.cpp"), *FIRMWARE.glob("*.ino")]:
            self.assertNotRegex(source.read_text(encoding="utf-8"),r"#include\s*[<\"](?:USBHID|BLEKeyboard)")
