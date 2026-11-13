"""Download the two MediaPipe task bundles into models/.

Run: python fetch_models.py
"""
import argparse
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

BASE = "https://storage.googleapis.com/mediapipe-models"
MODELS = {
    "models/gesture_recognizer.task": f"{BASE}/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task",
    "models/face_landmarker.task": f"{BASE}/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--face-only", action="store_true", help="Download only the model needed by Purrpose.")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    (root / "models").mkdir(exist_ok=True)
    for path, url in MODELS.items():
        if args.face_only and "face_landmarker" not in path:
            continue
        target = root / path
        if target.is_file() and zipfile.is_zipfile(target):
            print(f"skip {path} (exists)")
            continue
        print(f"downloading {path} ...")
        # A failed download must never look like an installed model on restart.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".download-", delete=False) as output:
                temporary = Path(output.name)
                with urllib.request.urlopen(url, timeout=30) as response:
                    shutil.copyfileobj(response, output)
            if not zipfile.is_zipfile(temporary):
                raise ValueError(f"Downloaded {path} is not a valid MediaPipe task bundle.")
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    print("done")


if __name__ == "__main__":
    main()
