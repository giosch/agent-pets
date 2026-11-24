"""HID preference, GATT fallback, and safe native-handle cancellation."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from agent_pets_habitat import device_display


class TransportChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_prefers_hid_without_opening_gatt(self):
        display = SimpleNamespace(close=lambda: None)
        with TemporaryDirectory() as temp, \
             patch.object(device_display.HidDisplay, "open", return_value=display), \
             patch.object(device_display, "stream", new=AsyncMock(side_effect=asyncio.CancelledError)), \
             patch.object(device_display, "find_gatt", new=AsyncMock()) as find:
            with self.assertRaises(asyncio.CancelledError):
                await device_display.run_loop(Path(temp))
            find.assert_not_awaited()

    async def test_hid_open_failure_falls_back_to_gatt(self):
        device = SimpleNamespace(address="AA:BB", name="Agent Pets")
        display = SimpleNamespace(kind="GATT", name="Agent Pets")
        @asynccontextmanager
        async def connect(_):
            yield display
        with TemporaryDirectory() as temp, \
             patch.object(device_display.HidDisplay, "open", side_effect=OSError("HID denied")), \
             patch.object(device_display, "find_gatt", new=AsyncMock(return_value=device)), \
             patch.object(device_display, "gatt_connection", new=connect), \
             patch.object(device_display, "stream", new=AsyncMock(side_effect=asyncio.CancelledError)) as stream:
            with self.assertRaises(asyncio.CancelledError):
                await device_display.run_loop(Path(temp))
            self.assertIs(stream.await_args.args[0], display)

    async def test_forced_gatt_does_not_enumerate_hid(self):
        with TemporaryDirectory() as temp, \
             patch.object(device_display.HidDisplay, "open") as hid, \
             patch.object(device_display, "find_gatt", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await device_display.run_loop(Path(temp), transport="gatt")
            hid.assert_not_called()

    async def test_cancellation_waits_for_native_io_before_closing(self):
        import threading
        started, release = threading.Event(), threading.Event()
        def operation():
            started.set()
            release.wait(2)
            return 1
        task = asyncio.create_task(device_display.hid_call(operation))
        await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task


class BackendStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_backend_sends_status_without_fake_snapshot(self):
        import json
        messages = []
        display = SimpleNamespace(kind="GATT",connected=True)
        async def send(record, sequence):
            messages.append(json.loads(record))
            raise asyncio.CancelledError
        display.send = send
        with TemporaryDirectory() as temp, patch.object(device_display.threading,"Thread"):
            with self.assertRaises(asyncio.CancelledError):
                await device_display.stream(display,Path(temp),None,lambda:1,"gatt",None)
        self.assertEqual(messages,[{"version":1,"type":"bridge_status","backend":False}])

    async def test_backend_loss_is_reported_while_pc_channel_stays_open(self):
        import json
        queue = None
        records = []
        class Reader:
            def __init__(self,target,args,daemon):
                nonlocal queue
                queue = args[2]
            def start(self):
                queue.put_nowait({"version":1,"type":"snapshot","sequence":1,"sessions":[]})
        display = SimpleNamespace(kind="GATT",connected=True,device=SimpleNamespace(address="test",name="test"),name="test")
        async def send(record, sequence):
            records.append(json.loads(record))
            if len(records)==2:
                queue.put_nowait({"type":"offline"})
            if len(records)==3:
                raise asyncio.CancelledError
        display.send = send
        with TemporaryDirectory() as temp, patch.object(device_display.threading,"Thread",Reader):
            with self.assertRaises(asyncio.CancelledError):
                await device_display.stream(display,Path(temp),None,lambda:1,"gatt",None)
        self.assertTrue(records[0]["backend"])
        self.assertEqual(records[1]["type"],"snapshot")
        self.assertEqual(records[2],{"version":1,"type":"bridge_status","backend":False})
        self.assertTrue(display.connected)
