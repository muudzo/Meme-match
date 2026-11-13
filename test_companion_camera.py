import math
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from companion_camera import CompanionCamera, expression_from_blendshapes


def shapes(**scores):
    return [SimpleNamespace(category_name=name, score=value) for name, value in scores.items()]


class ExpressionMappingTests(unittest.TestCase):
    def test_deliberate_closed_eyes_take_priority_over_smile(self):
        self.assertEqual(expression_from_blendshapes(shapes(eyeBlinkLeft=.9, eyeBlinkRight=.9,
                         mouthSmileLeft=.9, mouthSmileRight=.9)), "eyes_closed")

    def test_asymmetric_smile_is_not_assumed_to_be_happy(self):
        self.assertEqual(expression_from_blendshapes(shapes(mouthSmileLeft=.8, mouthSmileRight=0)), "neutral")

    def test_nonfinite_scores_are_ignored(self):
        self.assertIsNone(expression_from_blendshapes(shapes(jawOpen=math.nan)))

    def test_no_coefficients_uses_geometry_fallback(self):
        self.assertIsNone(expression_from_blendshapes([]))

    def test_visible_expression_vocabulary(self):
        cases = [(dict(eyeBlinkLeft=.9, eyeBlinkRight=.1), "wink"),
                 (dict(mouthSmileLeft=.6, mouthSmileRight=.6), "smile"),
                 (dict(mouthFrownLeft=.6, mouthFrownRight=.6), "frown"),
                 (dict(jawOpen=.6), "mouth_open")]
        for values, expected in cases:
            with self.subTest(expression=expected):
                self.assertEqual(expression_from_blendshapes(shapes(**values)), expected)

    def test_missing_dependencies_fail_without_starting_a_thread(self):
        camera = CompanionCamera(SimpleNamespace())
        with patch("companion_camera.importlib.util.find_spec", return_value=None):
            self.assertEqual(camera.start()["status"], "error")
        self.assertIsNone(camera._thread)
        self.assertFalse(camera.snapshot()["face_present"])


class ControlledCamera(CompanionCamera):
    """A native-resource stand-in; never imports camera SDKs or opens hardware."""
    def __init__(self, model_path):
        super().__init__(model_path=model_path)
        self.entered = {number: threading.Event() for number in (1, 2)}
        self.closing = {number: threading.Event() for number in (1, 2)}
        self.release = {number: threading.Event() for number in (1, 2)}
        self.live_resources = 0
        self.peak_resources = 0

    def _capture(self, stop, generation):
        with self._lock:
            self.live_resources += 1
            self.peak_resources = max(self.peak_resources, self.live_resources)
        self._publish(generation, stop, status="running", expression="smile",
                      face_present=True, sampled_at=100.0)
        self.entered[generation].set()
        stop.wait(5)
        self.closing[generation].set()
        self.release[generation].wait(5)
        with self._lock:
            self.live_resources -= 1


class CameraLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.model = Path(self.temporary.name) / "test.task"
        self.model.write_bytes(b"test resource")
        self.dependencies = patch("companion_camera.importlib.util.find_spec", return_value=object())
        self.dependencies.start()
        self.cameras = []

    def tearDown(self):
        for camera in self.cameras:
            camera.stop(wait=False)
            for gate in getattr(camera, "release", {}).values():
                gate.set()
            camera.stop()
        self.dependencies.stop()
        self.temporary.cleanup()

    def camera(self):
        camera = ControlledCamera(self.model)
        self.cameras.append(camera)
        return camera

    def wait_status(self, camera, status):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if camera.snapshot()["status"] == status:
                return
            threading.Event().wait(.005)
        self.assertEqual(camera.snapshot()["status"], status)

    def test_constructing_camera_does_not_activate_or_probe_hardware(self):
        with patch("companion_camera.threading.Thread", side_effect=AssertionError("No automatic worker")):
            camera = CompanionCamera()
        self.assertIsNone(camera.store)
        self.assertEqual(camera.snapshot()["status"], "off")
        self.assertIsNone(camera.snapshot()["sampled_at"])

    def test_pause_clears_expression_immediately_but_off_waits_for_release(self):
        camera = self.camera()
        camera.start()
        self.assertTrue(camera.entered[1].wait(1))
        self.assertEqual(camera.snapshot()["sampled_at"], 100.0)
        snapshot = camera.stop(wait=False)
        self.assertTrue(camera.closing[1].wait(1))
        self.assertEqual(snapshot["status"], "stopping")
        self.assertIsNone(snapshot["sampled_at"])
        self.assertIsNone(snapshot["expression"])
        self.assertFalse(snapshot["face_present"])
        self.assertEqual(camera.live_resources, 1)
        self.assertFalse(camera._publish(1, camera._stop, expression="smile", sampled_at=101.0))
        camera.release[1].set()
        self.wait_status(camera, "off")
        self.assertEqual(camera.live_resources, 0)

    def test_rapid_reactivation_queues_until_previous_capture_is_released(self):
        camera = self.camera()
        camera.start()
        self.assertTrue(camera.entered[1].wait(1))
        camera.stop(wait=False)
        self.assertEqual(camera.start()["status"], "stopping")
        self.assertEqual(camera._generation, 1)
        camera.release[1].set()
        self.assertTrue(camera.entered[2].wait(1))
        self.assertEqual(camera.snapshot()["status"], "running")
        self.assertEqual(camera._generation, 2)
        self.assertEqual(camera.peak_resources, 1)
        # Late publications from generation one cannot overwrite the new state.
        self.assertFalse(camera._publish(1, threading.Event(), expression="frown", sampled_at=999.0))
        self.assertEqual(camera.snapshot()["expression"], "smile")

    def test_second_pause_cancels_a_queued_reactivation(self):
        camera = self.camera()
        camera.start()
        self.assertTrue(camera.entered[1].wait(1))
        camera.stop(wait=False)
        camera.start()
        camera.stop(wait=False)
        camera.release[1].set()
        self.wait_status(camera, "off")
        self.assertEqual(camera._generation, 1)
        self.assertFalse(camera.entered[2].is_set())

    def test_missing_model_leaves_no_stale_sample_or_worker(self):
        camera = CompanionCamera(model_path=Path(self.temporary.name) / "missing.task")
        camera._set(expression="smile", face_present=True, sampled_at=100)
        self.assertEqual(camera.start()["status"], "error")
        self.assertIsNone(camera._thread)
        self.assertIsNone(camera.snapshot()["sampled_at"])
        self.assertIsNone(camera.snapshot()["expression"])

    def test_worker_error_clears_last_sample(self):
        camera = CompanionCamera(model_path=self.model)
        self.cameras.append(camera)
        def fail(stop, generation):
            camera._publish(generation, stop, status="running", expression="smile",
                            face_present=True, sampled_at=100)
            raise RuntimeError("The test capture failed")
        camera._capture = fail
        camera.start()
        self.wait_status(camera, "error")
        snapshot = camera.snapshot()
        self.assertEqual(snapshot["message"], "The test capture failed")
        self.assertIsNone(snapshot["sampled_at"])
        self.assertIsNone(snapshot["expression"])
        self.assertFalse(snapshot["face_present"])


if __name__ == "__main__":
    unittest.main()
