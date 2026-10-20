"""使用真实 MainWindow/事件循环和本地 TCP，验证 12 次循环及界面响应。"""
import io
import json
import socket
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace


def run_gui_self_test(report_path):
    import tkinter as tk
    from PIL import Image
    from main_window import MainWindow
    from config import ROI_SOURCE_SIZE

    report = {"ok": False, "inference": "stub; tests GUI/TCP, not recognition accuracy"}
    root = None
    app = None
    connections = []
    outcome = []
    errors = []
    done = threading.Event()
    camera = socket.socket()
    camera.bind(("127.0.0.1", 0))
    camera.listen(1)
    camera.settimeout(15)
    connections.append(camera)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        plc_port = probe.getsockname()[1]
    payload_buffer = io.BytesIO()
    Image.new("RGB", ROI_SOURCE_SIZE, "white").save(payload_buffer, format="PNG")
    payload = payload_buffer.getvalue()

    def recv_exact(connection, size):
        data = bytearray()
        while len(data) < size:
            chunk = connection.recv(size - len(data))
            if not chunk:
                raise EOFError("test socket closed early")
            data.extend(chunk)
        return bytes(data)

    def camera_loop():
        try:
            connection, _ = camera.accept()
            connections.append(connection)
            connection.settimeout(15)
            for _ in range(12):
                expected = b"Camera:Start=True"
                assert recv_exact(connection, len(expected)) == expected
                connection.sendall(len(payload).to_bytes(4, "big") + payload)
        except Exception:
            errors.append(traceback.format_exc())

    def controller_loop():
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    controller = socket.create_connection(("127.0.0.1", plc_port), timeout=1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.05)
            connections.append(controller)
            controller.settimeout(15)
            expected_ranges = [range(1, 4), range(4, 7), range(7, 10), range(10, 13)] * 3
            for expected in expected_ranges:
                controller.sendall(b"Camera:Trigger=True")
                reply = controller.recv(128).decode("utf-8")
                result = int(reply.removeprefix("Camera:Result="))
                assert result in expected, (reply, list(expected))
                outcome.append(result)
            assert len(set(outcome)) == 12, outcome
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            done.set()

    try:
        root = tk.Tk()
        root.withdraw()
        root.report_callback_exception = lambda *args: errors.append(
            "".join(traceback.format_exception(*args)))
        app = MainWindow(root)
        app.virtual_port.set(camera.getsockname()[1])
        app.plc_host.set("127.0.0.1")
        app.plc_port.set(plc_port)
        app.image_processor.roi_save_dir = Path(report_path).resolve().parent / "gui_test_roi"
        # 主窗口实际加载真实模型；仅连续循环阶段替换推理，以验证四类的控制流。
        model_names = dict(app.image_processor.model.names)
        sequence = iter(["hole", "stain", "scratch", "damage"] * 3)
        class StubModel:
            names = model_names
            def __call__(self, image, **kwargs):
                name = next(sequence)
                class_id = next(key for key, value in self.names.items() if value == name)
                return [SimpleNamespace(probs=SimpleNamespace(
                    top1=class_id, top1conf=SimpleNamespace(item=lambda: 1.0)))]
        app.image_processor.model = StubModel()
        threading.Thread(target=camera_loop, daemon=True).start()
        threading.Thread(target=controller_loop, daemon=True).start()
        started = time.monotonic()
        ticks = []
        stopping = []
        def tick():
            ticks.append(time.monotonic())
            if done.is_set() and not stopping:
                stopping.append(True)
                app.stop_server()
            if (stopping and not app.service_busy) or time.monotonic() - started > 30:
                root.quit()
            else:
                root.after(25, tick)
        root.after(25, tick)
        root.mainloop()
        assert done.is_set(), "GUI/TCP loop exceeded 30 seconds"
        assert not errors, errors
        assert len(outcome) == 12, outcome
        assert not app.service_busy and not app.tcp_communication.server_running
        assert app.image_processor.photo_image is not None
        gaps = [right - left for left, right in zip(ticks, ticks[1:])]
        max_gap = max(gaps, default=0)
        assert max_gap < 2, f"GUI event loop stalled for {max_gap:.2f}s"
        report.update(ok=True, results=outcome, gui_ticks=len(ticks),
                      service_stopped=True,
                      max_gui_gap_seconds=round(max_gap, 3), model_loaded=model_names,
                      elapsed_seconds=round(time.monotonic() - started, 3))
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        for connection in connections:
            try:
                connection.close()
            except OSError:
                pass
        if app is not None:
            app.tcp_communication.stop_server()
            app.ui_dispatcher.close()
        if root is not None:
            root.destroy()
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
