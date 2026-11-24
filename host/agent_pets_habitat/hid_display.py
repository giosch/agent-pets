"""Vendor-defined Agent Pets HID reports, shared across desktop OSes."""
import struct
import importlib
import sys
import time

from .bluetooth_display import packet

VENDOR_ID = 0x303A
PRODUCT_ID = 0xA937
USAGE_PAGE = 0xFF00
USAGE = 1
DATA_REPORT = 1
CAPABILITY_REPORT = 2
TRANSFER_REPORT = 3
REPORT_BYTES = 63
CHUNK_BYTES = 54


def load_hid():
    # Cython hidapi's Linux wheels ship separate libusb and hidraw modules.
    # Bluetooth devices require hidraw; libusb cannot enumerate them.
    module = "hidraw" if sys.platform == "linux" else "hid"
    try:
        return importlib.import_module(module)
    except ImportError as error:
        raise OSError('Install HID support with pip install "hidapi>=0.15,<0.16"'
                      + (" (Linux requires the hidraw module)" if module == "hidraw" else "")) from error


def fragments(record, sequence):
    payload = packet(record, sequence).removesuffix(b"\n")
    for offset in range(0, len(payload), CHUNK_BYTES):
        chunk = payload[offset:offset + CHUNK_BYTES]
        flags = (1 if offset == 0 else 0) | (2 if offset + len(chunk) == len(payload) else 0)
        header = struct.pack("<BBIHB", 0xC1, flags, sequence, offset, len(chunk))
        yield header + chunk + bytes(CHUNK_BYTES - len(chunk))


def decode_capabilities(report):
    data = bytes(report)
    # HIDAPI backends/bindings can retain or strip the numbered-report prefix.
    if data[:1] == bytes([CAPABILITY_REPORT]):
        data = data[1:]
    if len(data) not in (16, 63) or data[:4] != b"APH1" or data[4:8] != bytes([1, 63, 0, 16]):
        raise ValueError("Incompatible Agent Pets HID protocol")
    return data[8], struct.unpack_from("<I", data, 9)[0]


def decode_ack(report):
    data = bytes(report)
    if data[:1] == bytes([DATA_REPORT]):
        data = data[1:]
    if len(data) != 8 or data[0] != 0xC1 or data[6] != 1:
        return None
    return data[1], struct.unpack_from("<I", data, 2)[0]


def candidates(hid, serial=None):
    devices = []
    for device in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        # Linux metadata may omit usage, but no keyboard collections are defined.
        if device.get("usage_page") not in (None, 0, USAGE_PAGE) or device.get("usage") not in (None, 0, USAGE):
            continue
        if serial and device.get("serial_number") != serial:
            continue
        devices.append(device)
    return devices


class HidDisplay:
    kind = "HID"

    def __init__(self, device, info):
        self.device = device
        self.info = info
        self.name = info.get("product_string") or "Agent Pets"
        self.connected = True

    @classmethod
    def open(cls, serial=None):
        hid = load_hid()
        matches = candidates(hid, serial)
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError("Multiple HID Agent Petss; select one with --serial")
        info = matches[0]
        device = hid.device()
        try:
            device.open_path(info["path"])
            decode_capabilities(device.get_feature_report(CAPABILITY_REPORT, 64))
            return cls(device, info)
        except BaseException:
            device.close()
            raise

    def send(self, record, sequence):
        try:
            for fragment in fragments(record, sequence):
                # Feature Set_Report maps to acknowledged ATT writes on HOGP.
                # This avoids Windows hid_write's unacknowledged-output path.
                data = bytes([TRANSFER_REPORT]) + fragment
                if self.device.send_feature_report(data) != len(data):
                    raise OSError("Incomplete HID report write")
            deadline = time.monotonic() + 5
            next_status = time.monotonic() + .2
            while time.monotonic() < deadline:
                reply = decode_ack(self.device.read(9, timeout_ms=50))
                if reply is None or reply[1] != sequence:
                    if time.monotonic() < next_status:
                        continue
                    # Same application ACK is readable even if a native HID
                    # stack loses a notification or delays Input subscription.
                    reply = decode_capabilities(self.device.get_feature_report(CAPABILITY_REPORT, 64))
                    next_status = time.monotonic() + .2
                if reply[1] == sequence:
                    if reply[0]:
                        raise ValueError("HID display rejected the snapshot")
                    return
            raise TimeoutError("HID display did not acknowledge the snapshot")
        except (OSError, ValueError):
            self.connected = False
            raise

    def close(self):
        self.connected = False
        self.device.close()
