#!/usr/bin/env python3
"""Fetch the pinned official Sparkle distribution and verify it before unpacking."""
from pathlib import Path
import hashlib
import io
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.10.1"
SHA256 = "1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27"
DESTINATION = ROOT / "build" / "sparkle"


def main():
    url = f"https://github.com/sparkle-project/Sparkle/releases/download/{VERSION}/Sparkle-{VERSION}.tar.xz"
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError("Sparkle download checksum mismatch; refusing to unpack it.")
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
        archive.extractall(DESTINATION, filter="data")
    print(f"Verified Sparkle {VERSION}: {DESTINATION}")


if __name__ == "__main__":
    main()
