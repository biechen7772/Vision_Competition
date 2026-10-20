"""后台线程仅入队；所有 Tk 操作由主线程定时执行。"""

import queue
import sys
import time


class UIDispatcher:
    def __init__(self, root):
        self.root = root
        self.pending = queue.Queue()
        self.closed = False
        self.timer = root.after(25, self._drain)

    def __call__(self, callback, *args):
        if not self.closed:
            self.pending.put((callback, args))

    def _drain(self):
        if self.closed:
            return
        deadline = time.monotonic() + 0.01
        for _ in range(100):
            try:
                callback, args = self.pending.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args)
            except Exception:
                self.root.report_callback_exception(*sys.exc_info())
            if time.monotonic() >= deadline:
                break
        self.timer = self.root.after(25, self._drain)

    def close(self):
        self.closed = True
        self.root.after_cancel(self.timer)
        while not self.pending.empty():
            try:
                self.pending.get_nowait()
            except queue.Empty:
                break
