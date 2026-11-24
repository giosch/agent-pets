"""Custom GATT fallback and shared habitat snapshot framing."""
import asyncio
import json
import struct
import sys


SERVICE_UUID = "96a5d701-e7c7-4b8f-9df4-23dd0f624a01"
RX_UUID = "96a5d702-e7c7-4b8f-9df4-23dd0f624a01"
TX_UUID = "96a5d703-e7c7-4b8f-9df4-23dd0f624a01"


def select_paired_device(devices, address=None, preferred=None):
    """OS pairing is authoritative; a saved address is only a selection hint."""
    if address:
        return next((d for d in devices if d.address.lower() == address.lower()), None)
    candidates = [d for d in devices if (d.name or "").startswith("Agent Pets")
                  or (preferred and d.address.lower() == preferred.lower())]
    if preferred:
        match = next((d for d in candidates if d.address.lower() == preferred.lower()), None)
        if match:
            return match
    if len(candidates) > 1:
        raise ValueError("Multiple paired Agent Petss; select one with --address")
    return candidates[0] if candidates else None


async def paired_devices():
    """Enumerate bonded LE endpoints without an advertisement scan."""
    if sys.platform == "linux":
        from bleak.backends.device import BLEDevice
        from dbus_fast.aio import MessageBus
        from dbus_fast.constants import BusType, MessageType
        from dbus_fast.message import Message
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            reply = await bus.call(Message(destination="org.bluez", path="/",
                interface="org.freedesktop.DBus.ObjectManager", member="GetManagedObjects"))
            if reply.message_type == MessageType.ERROR:
                raise OSError("BlueZ paired-device enumeration failed: " + str(reply.body))
            result = []
            for path, interfaces in reply.body[0].items():
                props = {key: value.value for key, value in interfaces.get("org.bluez.Device1", {}).items()}
                if props.get("Paired") and props.get("Address"):
                    result.append(BLEDevice(props["Address"], props.get("Alias") or props.get("Name"),
                                            {"path": path, "props": props}))
            return result
        finally:
            bus.disconnect()
    if sys.platform != "win32":
        raise RuntimeError("This OS does not expose a paired-device enumeration API")
    from bleak.backends.device import BLEDevice
    from winrt.windows.devices.bluetooth import BluetoothLEDevice
    from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind
    from winrt.windows.foundation import IPropertyValue

    selector = BluetoothLEDevice.get_device_selector_from_pairing_state(True)
    devices = await DeviceInformation.find_all_async(
        selector, ["System.Devices.Aep.DeviceAddress"], DeviceInformationKind.ASSOCIATION_ENDPOINT)
    result = []
    for device in devices:
        value = device.properties.get("System.Devices.Aep.DeviceAddress")
        if device.pairing.is_paired and value is not None:
            address = value.as_(IPropertyValue).get_string()
            # Bleak 3.1's Windows backend connects directly from BLEDevice.address.
            # Supplying a string instead would make Bleak run an implicit scan.
            result.append(BLEDevice(address, device.name, None))
    return result


def connection_status(backend_online):
    if type(backend_online) is not bool:
        raise ValueError("Backend availability must be a boolean")
    return json.dumps({"version": 1, "type": "bridge_status", "backend": backend_online},
                      separators=(",", ":")).encode("ascii") + b"\n"


def packet(record, sequence):
    data = json.loads(record)
    data["tx"] = sequence
    encoded = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    if len(encoded) > 4096:
        raise ValueError("Bluetooth snapshot exceeds the device record limit")
    return encoded


async def send_snapshot(client, record, sequence, acknowledgements):
    """Bounded ATT writes, followed by an application ACK for the complete scene."""
    payload = packet(record, sequence)
    # Write-with-response is limited to MTU-3 and 512 bytes by ATT. The
    # conservative 244-byte ceiling also works with the board's preferred MTU.
    chunk_size = max(1, min(244, client.mtu_size - 3))
    for start in range(0, len(payload), chunk_size):
        await asyncio.wait_for(client.write_gatt_char(RX_UUID, payload[start:start + chunk_size], response=True), 5)
    async def wait_ack():
        while True:
            reply = await acknowledgements.get()
            if len(reply) != 5:
                continue
            result, received = struct.unpack("<BI", reply)
            if received != sequence:
                continue
            if result:
                raise ValueError("Bluetooth display rejected the snapshot")
            return
    await asyncio.wait_for(wait_ack(), 5)
