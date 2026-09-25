# -*- mode: python ; coding: utf-8 -*-
#
# VisionApp.spec - PyInstaller 配置文件
# 用于将 Tkinter 机器视觉应用打包成独立可执行文件
#

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # 核心修改：将 'best.pt' 模型文件添加到根目录 ('.')
    datas=[('best.pt', '.')],  
    
    # 隐藏导入：用于修复 PyTorch/Ultralytics 在 PyInstaller 环境中的常见依赖缺失问题
    hiddenimports=['torch', 'ultralytics'], 
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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

