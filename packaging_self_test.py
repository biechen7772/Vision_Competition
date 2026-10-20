"""离线检查便携包；使用合成图像和本机连接，不需要仿真平台。"""

import io
import json
import socket
import sys
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace


def run_self_test(report_path):
    report_path = Path(report_path).resolve()
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False))}
    root = None
    sockets = []
    try:
        import tkinter as tk
        from tkinter import ttk
        import torch
        import ultralytics
        from PIL import Image
        from config import MODEL_PATH, ROI_BBOX, ROI_SOURCE_SIZE, SHAPE_COLOR_MAP, RANGE_MAPPING
        from image_processor import ImageProcessor
        from tcp_communication import TCPCommunication

        logs = []
        logger = SimpleNamespace(log=logs.append)
        root = tk.Tk()
        root.withdraw()
        processor = ImageProcessor(ttk.Label(root), ttk.Label(root), logger)

        buffer = io.BytesIO()
        Image.new("RGB", ROI_SOURCE_SIZE, "white").save(buffer, format="PNG")
        image_data = buffer.getvalue()
        camera_server, camera_client = socket.socketpair()
        plc_server, plc_client = socket.socketpair()
        sockets = [camera_server, camera_client, plc_server, plc_client]
        for connection in sockets:
            connection.settimeout(30)
        camera_errors = []

        def camera_reply():
            try:
                command = bytearray()
                expected = b"Camera:Start=True"
                while len(command) < len(expected):
                    chunk = camera_server.recv(len(expected) - len(command))
                    if not chunk:
                        raise EOFError("拍照命令未完整接收")
                    command.extend(chunk)
                if bytes(command) != expected:
                    raise RuntimeError(f"拍照命令不匹配：{command!r}")
                camera_server.sendall(len(image_data).to_bytes(4, "big") + image_data)
            except Exception:
                camera_errors.append(traceback.format_exc())

        camera_thread = threading.Thread(target=camera_reply, daemon=True)
        camera_thread.start()
        communication = TCPCommunication(logger, processor)
        communication.socket_timeout = 30
        communication.virtual_socket = camera_client
        if not communication.send_trigger_to_virtual(plc_client):
            raise RuntimeError("测试结果未发送")
        camera_thread.join(timeout=5)
        if camera_thread.is_alive() or camera_errors:
            raise RuntimeError(f"测试相机应答失败：{camera_errors}")
        response = plc_server.recv(128).decode("utf-8")
        result = int(response.removeprefix("Camera:Result="))
        if not 1 <= result <= 12:
            raise RuntimeError(f"图像处理返回错误：{response}；日志：{logs}")

        prediction = processor.model.predictor.results[0]
        roi_size = (ROI_BBOX[2] - ROI_BBOX[0], ROI_BBOX[3] - ROI_BBOX[1])
        if prediction.orig_shape != roi_size[::-1]:
            raise RuntimeError(f"模型收到的图像尺寸不正确：{prediction.orig_shape}")
        predicted_class = processor.model.names[int(prediction.probs.top1)]
        if result not in RANGE_MAPPING[SHAPE_COLOR_MAP[predicted_class]]:
            raise RuntimeError("分类结果与货位映射不一致")
        if processor.photo_image is None:
            raise RuntimeError("Tk 图像显示依赖不可用")
        saved_roi = processor.last_saved_roi_path
        if processor.roi_save_enabled:
            if saved_roi is None:
                raise RuntimeError(f"ROI 图片未保存；日志：{logs}")
            with Image.open(saved_roi) as saved_image:
                if saved_image.size != roi_size or saved_image.mode != "RGB":
                    raise RuntimeError("保存的 ROI 图片尺寸或模式不正确")
                if saved_image.getpixel((0, 0)) != (255, 255, 255):
                    raise RuntimeError("保存的 ROI 像素与输入不一致")

        report.update(
            ok=True, model=MODEL_PATH, model_task=processor.model.task,
            model_classes=processor.model.names, source_size=ROI_SOURCE_SIZE,
            slot_mapping={name: RANGE_MAPPING[SHAPE_COLOR_MAP[name]]
                          for name in ("hole", "stain", "scratch", "damage")},
            roi=ROI_BBOX, roi_size=roi_size,
            model_input_size=processor.model.predictor.imgsz,
            tcp_response=response, gui_image_display=True,
            roi_image_saved=str(saved_roi) if saved_roi else None,
            torch_version=torch.__version__, ultralytics_version=ultralytics.__version__,
            test_image="synthetic; checks operation, not recognition accuracy",
            logs=logs,
        )
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        for connection in sockets:
            connection.close()
        if root is not None:
            root.destroy()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
