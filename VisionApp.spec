# -*- mode: python ; coding: utf-8 -*-
#
# VisionApp.spec - PyInstaller 配置文件
# 用于将 Tkinter 机器视觉应用打包成独立可执行文件
#

import os
import runpy
from PyInstaller.utils.hooks import copy_metadata

project_dir = SPECPATH
model_path = runpy.run_path(os.path.join(project_dir, 'config.py'))['MODEL_PATH']
model_data = [(os.path.join(project_dir, model_path), '.')]
for package in ('ultralytics', 'ultralytics-thop', 'torch', 'torchvision'):
    model_data += copy_metadata(package)

a = Analysis(
    [os.path.join(project_dir, 'main.py')],
    pathex=[project_dir],
    binaries=[],
    # 将在线分类使用的权重一并打包到根目录 ('.')
    datas=model_data,
    
    # 隐藏导入：用于修复 PyTorch/Ultralytics 在 PyInstaller 环境中的常见依赖缺失问题
    hiddenimports=['torch', 'ultralytics'], 
    hookspath=[],
    hooksconfig={'matplotlib': {'backends': ['Agg', 'TkAgg']}},
    runtime_hooks=[os.path.join(project_dir, 'packaging_runtime_hook.py')],
    # 此程序只做 Tk 界面和 PyTorch 推理，不打包其他界面框架及模型导出工具。
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tensorflow', 'tensorboard',
              'IPython', 'notebook', 'jupyter', 'pytest', 'onnx', 'onnxruntime',
              'openvino', 'jax', 'triton'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VisionApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

