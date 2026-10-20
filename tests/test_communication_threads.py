import threading
import unittest
from types import SimpleNamespace
from logger import Logger
from ui_dispatcher import UIDispatcher
from tcp_communication import TCPCommunication


class MainThreadWidget:
    def __init__(self):
        self.owner = threading.get_ident()
        self.calls = []
        self.scheduled = []

    def record(self, method, *args):
        if threading.get_ident() != self.owner:
            raise RuntimeError("GUI was touched by a worker")
        self.calls.append((method, args))

    def after(self, delay, callback):
        self.record("after")
        self.scheduled.append(callback)
        return len(self.scheduled)

    def after_cancel(self, timer): self.record("cancel")
    def insert(self, *args): self.record("insert", *args)
    def see(self, *args): self.record("see", *args)
    def delete(self, *args): self.record("delete", *args)
    def report_callback_exception(self, *args): raise AssertionError(args)


class CommunicationThreadTests(unittest.TestCase):
    def test_background_logs_and_display_do_not_call_tk(self):
        widget = MainThreadWidget()
        dispatch = UIDispatcher(widget)
        logger = Logger(widget, dispatch)
        comm = TCPCommunication(logger, SimpleNamespace(display_image=lambda data:
                                  widget.record("display", data)), dispatch)
        errors = []
        def worker():
            try:
                logger.log("worker message")
                comm._display_image(b"example")
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual([name for name, args in widget.calls], ["after"])
        dispatch._drain()
        names = [name for name, args in widget.calls]
        self.assertIn("insert", names)
        self.assertIn("display", names)
        dispatch.close()

    def test_decoder_preserves_every_possible_next_command_prefix(self):
        comm = TCPCommunication(None, None)
        command = b"Camera:Trigger=True"
        for split in range(1, len(command)):
            with self.subTest(split=split):
                count, pending = comm._extract_trigger_commands(
                    bytearray(command + command[:split]))
                self.assertEqual(count, 1)
                count, pending = comm._extract_trigger_commands(pending + command[split:])
                self.assertEqual(count, 1)
                self.assertEqual(pending, bytearray())

    def test_decoder_handles_bytewise_commands_whitespace_and_noise(self):
        comm = TCPCommunication(None, None)
        pending = bytearray()
        count = 0
        for value in b"noiseCamera:Trigger=True\r\n CAMERA:TRIGGER=TRUE\n":
            pending.append(value)
            found, pending = comm._extract_trigger_commands(pending)
            count += found
        self.assertEqual(count, 2)
        self.assertEqual(pending, bytearray())


if __name__ == "__main__":
    unittest.main()
