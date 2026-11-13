"""Opt-in, local-only webcam observations for the Purrpose companion.

The worker emits visible expressions, never a psychological mood score. Frames
stay in memory and are discarded after inference. SDK imports are lazy so the
planner, timer and journal work without camera dependencies.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import threading
import time


def expression_from_blendshapes(categories):
    """Map MediaPipe expression coefficients to a small visible vocabulary.

    See https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python
    These coefficients describe facial movement, not feelings or attention.
    """
    scores = {}
    for category in categories or []:
        score = getattr(category, "score", 0)
        if isinstance(score, (int, float)) and math.isfinite(score):
            scores[getattr(category, "category_name", "")] = score
    if not scores:
        return None
    left = scores.get("eyeBlinkLeft", 0)
    right = scores.get("eyeBlinkRight", 0)
    if min(left, right) >= 0.60:
        return "eyes_closed"
    if max(left, right) >= 0.65 and min(left, right) <= 0.25:
        return "wink"
    if scores.get("jawOpen", 0) >= 0.45:
        return "mouth_open"
    if scores.get("mouthPucker", 0) >= 0.55:
        return "kiss"
    smile = (scores.get("mouthSmileLeft", 0) + scores.get("mouthSmileRight", 0)) / 2
    if smile >= 0.45:
        return "grin" if scores.get("jawOpen", 0) >= 0.15 else "smile"
    brow = max(scores.get("browInnerUp", 0),
               (scores.get("browOuterUpLeft", 0) + scores.get("browOuterUpRight", 0)) / 2)
    if brow >= 0.50:
        return "eyebrows_raised"
    if min(scores.get("mouthFrownLeft", 0), scores.get("mouthFrownRight", 0)) >= 0.40:
        return "frown"
    return "neutral"


class CompanionCamera:
    """Own one camera worker, with opt-in activation and restart-safe teardown.

    ``sampled_at`` is a monotonic capture timestamp, never a wall-clock time.
    Consumers must treat missing or stale samples as unknown. ``stop(wait=False)``
    requests shutdown without blocking a desktop event loop; status remains
    ``stopping`` until the worker has released the native camera resources.
    """
    def __init__(self, store=None, model_path=None, device=0):
        self.store = store
        self.model_path = Path(model_path or Path(__file__).resolve().parent / "models/face_landmarker.task")
        self.device = device
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._generation = 0
        self._restart_requested = False
        self._state = {"status": "off", "expression": None, "face_present": False,
                       "sampled_at": None,
                       "message": "Camera is paused. Activate your cat to begin local expression tracking."}

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def _set(self, **values):
        with self._lock:
            self._state.update(values)

    def _publish(self, generation, stop, **values):
        # Check under the same lock as stop(): an in-flight frame must not
        # resurrect an expression after the user has paused their cat.
        with self._lock:
            if generation != self._generation or stop.is_set():
                return False
            self._state.update(values)
            return True

    def _launch_locked(self):
        try:
            dependencies = all(importlib.util.find_spec(name) for name in ("cv2", "mediapipe", "numpy"))
        except (ImportError, ValueError):
            dependencies = False
        if not dependencies:
            self._set(status="error", expression=None, face_present=False, sampled_at=None,
                      message="Camera dependencies are missing. In a source checkout, install requirements-desktop.txt with Python 3.12 and launch .venv/bin/python desktop.py.")
            return
        if not self.model_path.is_file():
            self._set(status="error", expression=None, face_present=False, sampled_at=None,
                      message="The face model is missing. In a source checkout, run .venv/bin/python fetch_models.py --face-only. For an installed app, reinstall Purrpose.")
            return
        self._stop = threading.Event()
        self._generation += 1
        self._set(status="starting", expression=None, face_present=False, sampled_at=None,
                  message="Opening your camera. macOS may ask for Purrpose camera access.")
        self._thread = threading.Thread(target=self._run, args=(self._stop, self._generation),
                                        name="purrpose-camera", daemon=True)
        self._thread.start()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                if self._stop.is_set():
                    # A rapid Pause -> Activate queues a restart. Never create
                    # another capture worker before the old one has released it.
                    self._restart_requested = True
                    self._set(status="stopping", expression=None, face_present=False, sampled_at=None,
                              message="Finishing camera shutdown, then reactivating your cat.")
                return self.snapshot()
            self._restart_requested = False
            self._launch_locked()
            return self.snapshot()

    def stop(self, wait=True):
        with self._lock:
            self._restart_requested = False
            self._stop.set()
            worker = self._thread
            alive = worker is not None and worker.is_alive()
            self._set(status="stopping" if alive else "off", expression=None,
                      face_present=False, sampled_at=None,
                      message="Waiting for the camera to close." if alive else "Camera is paused. Activate your cat whenever you need it.")
        if wait and alive and worker is not threading.current_thread():
            worker.join(timeout=3)
        # Only the worker's finally block changes stopping -> off. This avoids
        # a late stop() response clobbering a queued new generation's state.
        return self.snapshot()

    def _record(self, expression, face_present):
        if self.store is not None:
            self.store.record_expression(expression, face_present=face_present)

    def _run(self, stop, generation):
        failure = None
        try:
            self._capture(stop, generation)
        except Exception as exc:
            failure = str(exc) or type(exc).__name__
        finally:
            try:
                self._record(None, False)
            except Exception:
                pass  # A diary store may already have closed during shutdown.
            with self._lock:
                if generation == self._generation:
                    self._thread = None
                    failed = failure is not None and not stop.is_set()
                    self._set(status="error" if failed else "off", expression=None,
                              face_present=False, sampled_at=None,
                              message=failure if failed else "Camera is paused. Activate your cat whenever you need it.")
                    if self._restart_requested:
                        self._restart_requested = False
                        self._launch_locked()

    def _capture(self, stop, generation):
        # All SDK/model work stays inside the worker and after explicit start().
        if stop.is_set():
            return
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core import base_options
        from face_rules import classify_expression
        from recognition_state import StableSignal, metric_landmarks

        signal = StableSignal(confirmation_seconds=0.35, stale_after=2.0)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options.BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1, output_face_blendshapes=True,
            min_face_detection_confidence=0.6, min_face_presence_confidence=0.6,
            min_tracking_confidence=0.6,
        )
        if stop.is_set():
            return
        cap = None
        try:
            cap = cv2.VideoCapture(self.device)
            if not cap.isOpened():
                raise RuntimeError("Could not open the webcam. Allow camera access for Purrpose (or your terminal when running from source) in System Settings and close other apps using it.")
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if stop.is_set():
                return
            last_log = -math.inf
            last_timestamp = -1
            missed = 0
            with vision.FaceLandmarker.create_from_options(options) as landmarker:
                self._publish(generation, stop, status="running",
                              message="Local expression tracking is on. No images are saved.")
                while not stop.is_set():
                    captured_at = time.monotonic()
                    ok, frame = cap.read()
                    if not ok:
                        missed += 1
                        signal.reset()
                        self._publish(generation, stop, expression=None, face_present=False,
                                      sampled_at=None, message="Waiting for a fresh camera frame.")
                        if missed >= 5:
                            raise RuntimeError("The camera stopped sending frames. Pause and reactivate your cat.")
                        stop.wait(0.2)
                        continue
                    missed = 0
                    height, width = frame.shape[:2]
                    if width > 640:
                        frame = cv2.resize(frame, (640, round(height * 640 / width)))
                        height, width = frame.shape[:2]
                    rgb = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    stamp = max(last_timestamp + 1, time.monotonic_ns() // 1_000_000)
                    last_timestamp = stamp
                    result = landmarker.detect_for_video(image, stamp)
                    present = bool(result.face_landmarks)
                    expression = None
                    if present:
                        shapes = result.face_blendshapes[0] if result.face_blendshapes else []
                        raw = expression_from_blendshapes(shapes)
                        if raw is None:
                            raw = classify_expression(metric_landmarks(result.face_landmarks[0], width, height)) or "neutral"
                            raw = {"sad": "frown", "teeth": "grin"}.get(raw, raw)
                        expression = signal.update(raw, now=captured_at)
                    else:
                        signal.reset()
                    published = self._publish(generation, stop, expression=expression,
                                              face_present=present, sampled_at=captured_at,
                                              message="Local expression tracking is on. No images are saved." if present else "No face in view. Waiting quietly for you.")
                    if published and captured_at - last_log >= 1:
                        self._record(expression, present)
                        last_log = captured_at
                    stop.wait(max(0, 0.16 - (time.monotonic() - captured_at)))
        finally:
            if cap is not None:
                cap.release()
