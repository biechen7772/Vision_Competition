"""持久保存在线裁剪图，不使用 PyInstaller 的临时解压目录。"""

import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def resolve_roi_directory(directory):
    directory = Path(directory)
    if directory.is_absolute():
        return directory
    base = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    return base / directory


def save_roi_image(image, directory, bbox):
    """无损保存同一张 ROI；独占创建，重复采集和重启均不覆盖旧图。"""
    now = datetime.now()
    folder = Path(directory) / now.strftime("%Y%m%d")
    folder.mkdir(parents=True, exist_ok=True)
    coordinates = "_".join(str(value) for value in bbox)
    width, height = image.size
    filename = (
        f"{now:%H%M%S_%f}_roi_{coordinates}_{width}x{height}_{uuid4().hex}.png"
    )
    path = folder / filename
    with path.open("xb") as output:
        try:
            # 较低压缩等级减少在线保存耗时；不改变像素或尺寸。
            image.save(output, format="PNG", compress_level=1)
        except Exception:
            output.close()
            path.unlink()
            raise
    return path
