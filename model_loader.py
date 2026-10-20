"""加载本地 YOLO 权重，兼容训练环境保存在权重中的跨平台路径。"""

import io
import pickle
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace

import torch
from ultralytics import YOLO


class _PortablePathUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module == "pathlib":
            if name == "PosixPath":
                return PurePosixPath
            if name == "WindowsPath":
                return PureWindowsPath
        return super().find_class(module, name)


def _portable_load(file, **kwargs):
    return _PortablePathUnpickler(file, **kwargs).load()


def _portable_loads(data, **kwargs):
    return _portable_load(io.BytesIO(data), **kwargs)


_PORTABLE_PICKLE = SimpleNamespace(
    __name__="portable_path_pickle",
    Unpickler=_PortablePathUnpickler,
    load=_portable_load,
    loads=_portable_loads,
)


def load_yolo_model(model_path):
    """优先正常加载；仅遇到路径平台不兼容时转换临时副本，保留原权重。"""
    model_path = Path(model_path)
    try:
        return YOLO(str(model_path))
    except NotImplementedError as exc:
        if "PosixPath" not in str(exc) and "WindowsPath" not in str(exc):
            raise

    # 与 Ultralytics 一样加载完整的本地模型；不修改 pathlib 的全局类。
    checkpoint = torch.load(
        str(model_path),
        map_location="cpu",
        pickle_module=_PORTABLE_PICKLE,
        weights_only=False,
    )
    with tempfile.TemporaryDirectory(prefix="vision_model_") as temp_dir:
        portable_path = Path(temp_dir) / model_path.name
        torch.save(checkpoint, str(portable_path))
        model = YOLO(str(portable_path))

    # 模型已加载到内存，之后的推理不依赖临时文件。
    original_path = str(model_path)
    model.ckpt_path = original_path
    model.model_name = original_path
    model.model.pt_path = original_path
    model.overrides["model"] = original_path
    return model
