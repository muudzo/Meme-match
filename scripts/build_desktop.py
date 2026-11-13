#!/usr/bin/env python3
"""Build the standalone macOS desktop cat and optionally its drag-install DMG.

Usage: .venv/bin/python scripts/build_desktop.py --dmg
Dependencies are never installed by this script. Build with the project's Python
3.12 environment after installing requirements-desktop.txt.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WORK = ROOT / "build" / "desktop"


def run(arguments, **kwargs):
    print(" ".join(str(value) for value in arguments), flush=True)
    subprocess.run([str(value) for value in arguments], check=True, **kwargs)


def create_icon():
    """Rasterize the project's cat mark into an Apple multi-resolution icon."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    # Icon rendering needs no visible windows or camera permission.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication.instance() or QGuiApplication(["Purrpose icon builder"])
    source = ROOT / "packaging" / "cat.svg"
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise RuntimeError(f"Could not load the cat mark: {source}")
    iconset = WORK / "Purrpose.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            pixels = size * scale
            image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter, QRectF(0, 0, pixels, pixels))
            painter.end()
            filename = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            if not image.save(str(iconset / filename)):
                raise RuntimeError("Could not save generated app icon.")
    target = ROOT / "packaging" / "Purrpose.icns"
    run(["/usr/bin/iconutil", "--convert", "icns", "--output", target, iconset])
    return target


def verify_bundle(app):
    """Catch missing activation permissions or model data before distribution."""
    executable = app / "Contents" / "MacOS" / "Purrpose"
    if not executable.is_file():
        raise RuntimeError(f"The application executable is missing: {executable}")
    with (app / "Contents" / "Info.plist").open("rb") as source:
        info = plistlib.load(source)
    if not info.get("NSCameraUsageDescription") or not info.get("LSUIElement"):
        raise RuntimeError("The app is missing its camera permission or desktop accessory settings.")
    # PyInstaller's macOS app relocation may place data in Resources and expose
    # it to the runtime through symlinks in Frameworks.
    model_paths = list((app / "Contents").rglob("face_landmarker.task"))
    if not any(path.is_file() for path in model_paths):
        raise RuntimeError("The packaged FaceLandmarker model is missing.")
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", app])
    return info


def release_created_image(destination):
    """Release only a retained attachment of the image this build just made.

    Some macOS DiskImages versions return from create while their helper still
    holds the created image open for writing. Verification then fails EAGAIN.
    Never inspect a volume name or guess a device: match the complete image path
    from hdiutil's structured inventory, then detach that image's whole disk.
    This helper is called only after this run successfully created destination.
    """
    result = subprocess.run(["/usr/bin/hdiutil", "info", "-plist"],
                            check=True, capture_output=True)
    inventory = plistlib.loads(result.stdout)
    expected = destination.resolve()
    for image in inventory.get("images", []):
        path = image.get("image-path")
        if not path or Path(path).resolve() != expected:
            continue
        disks = [entity.get("dev-entry", "") for entity in image.get("system-entities", [])]
        disk = next((entry for entry in disks if re.fullmatch(r"/dev/disk\d+", entry)), None)
        if disk is None:
            raise RuntimeError(f"The new installer is still attached, but its device cannot be identified safely: {expected}")
        run(["/usr/bin/hdiutil", "detach", disk])


def verify_image(destination):
    """Retry only transient image-release failures; never accept bad checksums."""
    command = ["/usr/bin/hdiutil", "verify", str(destination)]
    for attempt in range(4):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end="", flush=True)
        if result.returncode == 0:
            return
        error = result.stderr.lower()
        transient = "resource temporarily unavailable" in error or "resource busy" in error
        if not transient or attempt == 3:
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="", flush=True)
            raise subprocess.CalledProcessError(result.returncode, command,
                                                output=result.stdout, stderr=result.stderr)
        print("DiskImages is releasing the new installer; retrying verification.", flush=True)
        time.sleep(0.5 * (attempt + 1))


def create_dmg(app):
    destination = DIST / "Purrpose.dmg"
    # Only staging is deleted; never remove or overwrite an installed app.
    with tempfile.TemporaryDirectory(prefix="purrpose-dmg-", dir=WORK) as temporary:
        stage = Path(temporary)
        run(["/usr/bin/ditto", app, stage / "Purrpose.app"])
        (stage / "Applications").symlink_to("/Applications")
        (stage / "Install Purrpose.txt").write_text(
            "Drag Purrpose.app to Applications, then open Purrpose.\n\n"
            "Your cat starts paused. Click it and choose Activate to enable "
            "local camera reactions. Pause or Quit releases the camera.\n\n"
            "This is a local development build, signed ad hoc rather than "
            "notarized with an Apple Developer certificate. If macOS blocks "
            "opening it, review it in System Settings > Privacy & Security.\n",
            encoding="utf-8",
        )
        run(["/usr/bin/hdiutil", "create", "-volname", "Purrpose", "-srcfolder", stage,
             "-ov", "-format", "UDZO", destination])
    release_created_image(destination)
    verify_image(destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dmg", action="store_true", help="Also create dist/Purrpose.dmg for drag-to-Applications installation.")
    parser.add_argument("--dmg-only", action="store_true", help="Package an already-built dist/Purrpose.app without rebuilding it.")
    parser.add_argument("--clean", action="store_true", help="Ask PyInstaller to discard its analysis cache.")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        parser.error("This build produces a macOS .app; run it on macOS.")
    DIST.mkdir(exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    app = DIST / "Purrpose.app"
    if not args.dmg_only:
        missing = [name for name in ("PySide6", "PyInstaller", "mediapipe", "cv2", "numpy")
                   if importlib.util.find_spec(name) is None]
        if missing:
            parser.error("Missing build dependencies: " + ", ".join(missing) +
                         ". Run .venv/bin/python -m pip install -r requirements-desktop.txt.")
        if not (ROOT / "desktop.py").is_file():
            parser.error("desktop.py is missing from this checkout.")
        if not (ROOT / "models" / "face_landmarker.task").is_file():
            parser.error("Run .venv/bin/python fetch_models.py --face-only before building.")
        create_icon()
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", DIST,
                   "--workpath", WORK / "pyinstaller"]
        if args.clean:
            command.append("--clean")
        command.append(ROOT / "packaging" / "Purrpose.spec")
        run(command, cwd=ROOT)
    verify_bundle(app)
    print(f"\nBuilt {app}")
    if args.dmg or args.dmg_only:
        print(f"Install image: {create_dmg(app)}")
    print("The app includes Python, the camera SDK and face model; end users do not need Python.")


if __name__ == "__main__":
    main()
