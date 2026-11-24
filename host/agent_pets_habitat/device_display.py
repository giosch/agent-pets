"""Prefer native HID, retaining the custom GATT service as a fallback."""
import asyncio
from contextlib import asynccontextmanager
import json
import secrets
from queue import Empty, Queue
import sys
import threading

from agent_pets_daemon.session_store import write_json_atomic
from .bluetooth_display import SERVICE_UUID, RX_UUID, TX_UUID, paired_devices, select_paired_device, send_snapshot, connection_status
from .hid_display import HidDisplay
from .serial_display import DisplayState, read_events


async def hid_call(function, *args):
    # Never close a native HID handle while a cancelled worker still uses it.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


async def find_gatt(address=None, preferred=None):
    if sys.platform in {"win32", "linux"}:
        return select_paired_device(await paired_devices(), address, preferred)
    if sys.platform == "darwin":
        from bleak import BleakScanner
        # CoreBluetooth exposes peripheral UUIDs, not an OS paired-device list.
        # macOS owns consent/bonding when an encrypted characteristic is used.
        return await BleakScanner.find_device_by_filter(
            lambda d, a: d.address.lower() == address.lower() if address else SERVICE_UUID in a.service_uuids,
            timeout=5, service_uuids=[SERVICE_UUID])
    raise RuntimeError("Display transport supports Windows, macOS and Linux")


class GattDisplay:
    kind = "GATT"

    def __init__(self, client, device):
        self.client, self.device = client, device
        self.name = device.name or device.address
        self.acks = asyncio.Queue()

    @property
    def connected(self):
        return self.client.is_connected

    async def send(self, record, sequence):
        await send_snapshot(self.client, record, sequence, self.acks)


@asynccontextmanager
async def gatt_connection(device):
    from bleak import BleakClient
    async with BleakClient(device, pair=False, timeout=45,
                           winrt={"use_cached_services": False}) as client:
        if client.services.get_service(SERVICE_UUID) is None:
            raise ValueError("Paired device does not provide the habitat GATT service")
        display = GattDisplay(client, device)
        await client.start_notify(TX_UUID, lambda _, data: display.acks.put_nowait(bytes(data)))
        await client.write_gatt_char(RX_UUID, b"\n", response=True)
        yield display


async def send_record(display, record, sequence):
    if display.kind == "HID":
        await hid_call(display.send, record, sequence)
    else:
        await display.send(record, sequence)


async def stream(display, directory, url, next_sequence, transport, serial, hid_retry=0):
    """A fresh event stream restores current state after every transport switch."""
    messages = Queue(maxsize=128)
    stop = threading.Event()
    state = DisplayState()
    threading.Thread(target=read_events, args=(directory, url, messages, stop), daemon=True).start()
    announced = False
    last_status = -1.0
    backend_announced = None
    last_check = asyncio.get_running_loop().time()
    try:
        while display.connected:
            now = asyncio.get_running_loop().time()
            if display.kind == "GATT" and now - last_check >= 5:
                if sys.platform in {"win32", "linux"}:
                    if select_paired_device(await paired_devices(), display.device.address) is None:
                        print("Device removed in OS settings; closing habitat connection", flush=True)
                        return
                if transport == "auto" and now >= hid_retry:
                    # Only leave working GATT after HID opens and passes its
                    # capability handshake. A missing/denied HID stays on GATT.
                    try:
                        probe = await hid_call(HidDisplay.open, serial)
                        if probe:
                            await hid_call(probe.close)
                            print("Native HID is ready; switching from GATT", flush=True)
                            return
                    except (OSError, ValueError):
                        pass
                last_check = now
            while True:
                try:
                    event = messages.get_nowait()
                    state.apply(event)
                    if event.get("moment"):
                        break
                except Empty:
                    break
            if backend_announced != state.online or now - last_status >= 1:
                await send_record(display, connection_status(state.online), next_sequence())
                last_status = now
                if backend_announced != state.online:
                    print("Habitat backend online" if state.online else "PC connection active; habitat backend unavailable", flush=True)
                    backend_announced = state.online
            if not state.online:
                await asyncio.sleep(.1)
                continue
            await send_record(display, state.record(), next_sequence())
            state.acknowledge()
            if not announced:
                if display.kind == "GATT":
                    write_json_atomic(directory / "bluetooth-display.json",
                                      {"address": display.device.address, "name": display.device.name})
                print(f"{display.kind} display connected: {display.name}, {len(state.sessions)} habitat sessions", flush=True)
                announced = True
            await asyncio.sleep(.25)
    finally:
        stop.set()


async def run_loop(directory, url=None, address=None, transport="auto", serial=None):
    from bleak.exc import BleakError
    settings = directory / "bluetooth-display.json"
    try:
        preferred = json.loads(settings.read_text(encoding="utf-8"))["address"]
    except (OSError, ValueError, KeyError):
        preferred = None
    print(f"Habitat display bridge ({transport}). Pair Agent Pets in your computer's Bluetooth settings.", flush=True)
    sequence = secrets.randbits(32)
    def next_sequence():
        nonlocal sequence
        sequence = sequence % 0xFFFFFFFF + 1
        return sequence
    hid_retry = 0
    waiting = False
    while True:
        display = None
        try:
            if transport != "gatt" and asyncio.get_running_loop().time() >= hid_retry:
                try:
                    display = await hid_call(HidDisplay.open, serial)
                    if display:
                        waiting = False
                        await stream(display, directory, url, next_sequence, transport, serial)
                except (OSError, ValueError, TimeoutError) as error:
                    hid_retry = asyncio.get_running_loop().time() + 30
                    print(f"HID unavailable: {str(error) or type(error).__name__}", flush=True)
                finally:
                    if display:
                        await hid_call(display.close)
                if display:
                    # On HID transfer failure, try GATT below in this iteration.
                    hid_retry = asyncio.get_running_loop().time() + 30
            if transport != "hid":
                device = await find_gatt(address, preferred)
                if device:
                    waiting = False
                    async with gatt_connection(device) as gatt:
                        print(f"Opening GATT fallback: {gatt.name}", flush=True)
                        await stream(gatt, directory, url, next_sequence, transport, serial, hid_retry)
                        preferred = device.address
                        write_json_atomic(settings, {"address": preferred, "name": device.name})
                    continue
            if not waiting:
                print("Waiting for Agent Pets. On the display choose Settings > Bluetooth > Pair PC, then add it in OS Bluetooth settings.", flush=True)
                waiting = True
            await asyncio.sleep(2)
        except (OSError, ValueError, TimeoutError, BleakError) as error:
            print(f"Display reconnecting: {str(error) or type(error).__name__}", flush=True)
            await asyncio.sleep(2)


def run(directory, url=None, address=None, transport="auto", serial=None):
    try:
        asyncio.run(run_loop(directory, url, address, transport, serial))
    except KeyboardInterrupt:
        pass
