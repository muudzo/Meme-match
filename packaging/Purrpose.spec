# -*- mode: python ; coding: utf-8 -*-
"""Standalone macOS accessory app; build through scripts/build_desktop.py."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).resolve().parent
mp_datas, mp_binaries, mp_imports = collect_all("mediapipe")

analysis = Analysis(
    [str(root / "desktop.py")],
    pathex=[str(root)],
    binaries=mp_binaries,
    datas=mp_datas + [
        (str(root / "models" / "face_landmarker.task"), "models"),
        (str(root / "models" / "gesture_recognizer.task"), "models"),
        (str(root / "packaging" / "Purrpose.icns"), "packaging"),
        (str(root / "LICENSE"), "licenses"),
    ],
    hiddenimports=mp_imports + [
        "cv2", "numpy", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
        "mediapipe.tasks.python.vision.face_landmarker",
        "mediapipe.tasks.python.core.base_options",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / "packaging" / "runtime_hook.py")],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [],
    exclude_binaries=True,
    name="Purrpose",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    exe, analysis.binaries, analysis.datas,
    strip=False, upx=False, name="Purrpose",
)
app = BUNDLE(
    collection,
    name="Purrpose.app",
    icon=str(root / "packaging" / "Purrpose.icns"),
    bundle_identifier="com.purrpose.desktop",
    info_plist={
        "CFBundleName": "Purrpose",
        "CFBundleDisplayName": "Purrpose",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "2",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSCameraUsageDescription": (
            "When you activate your desktop cat, Purrpose uses the camera locally "
            "to mirror visible facial reactions and offer gentle check-ins. "
            "No camera images are saved or uploaded."
        ),
        "NSHumanReadableCopyright": "Purrpose contributors. Source licensed under MIT.",
    },
)
