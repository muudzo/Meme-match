"""Writable SDK caches and useful logs for a Finder-launched, windowless app."""
import os
from pathlib import Path
import sys
import tempfile

if "MPLCONFIGDIR" not in os.environ:
    cache_base = Path(os.environ.get("PURRPOSE_CACHE_DIR", "")) if os.environ.get("PURRPOSE_CACHE_DIR") else Path.home() / "Library" / "Caches" / "Purrpose"
    try:
        cache_base.mkdir(parents=True, exist_ok=True)
    except OSError:
        cache_base = Path(tempfile.gettempdir()) / "purrpose-cache"
        cache_base.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache_base / "matplotlib")

if sys.stdout is None or sys.stderr is None:
    try:
        log_dir = Path(os.environ.get("PURRPOSE_LOG_DIR", "")) if os.environ.get("PURRPOSE_LOG_DIR") else Path.home() / "Library" / "Logs" / "Purrpose"
        log_dir.mkdir(parents=True, exist_ok=True)
        stream = (log_dir / "runtime.log").open("a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
