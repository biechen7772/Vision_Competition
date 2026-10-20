"""便携程序的离线运行设置，在第三方库导入之前执行。"""

import os
import tempfile
from pathlib import Path

app_data = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "VisionApp"
config_dir = Path(os.environ.setdefault("YOLO_CONFIG_DIR", str(app_data)))
config_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(app_data / "matplotlib"))
os.environ["YOLO_AUTOINSTALL"] = "false"
