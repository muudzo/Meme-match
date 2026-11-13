"""Offscreen native-widget regressions; no webcam or display is opened."""
import importlib.util
import os
from pathlib import Path
import tempfile
import time
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

# This must precede every Qt import, including importing the desktop entry point.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from desktop import DesktopController


class Clock:
    def __init__(self):
        self.value = time.monotonic()

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeCamera:
    def __init__(self, clock):
        self.clock = clock
        self.start_calls = 0
        self.stop_calls = []
        self.state = {"status": "off", "expression": None, "face_present": False,
                      "sampled_at": None, "message": "Camera is paused."}

    def snapshot(self):
        return dict(self.state)

    def start(self):
        self.start_calls += 1
        self.state["status"] = "running"
        self.observe("neutral")
        return self.snapshot()

    def stop(self, wait=True):
        self.stop_calls.append(wait)
        self.state.update(status="off", expression=None, face_present=False, sampled_at=None)
        return self.snapshot()

    def observe(self, expression, *, present=True):
        self.state.update(expression=expression if present else None,
                          face_present=present, sampled_at=self.clock())


@unittest.skipUnless(HAS_QT, "Optional PySide6 native-widget dependencies are not installed")
class DesktopWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.clock_patch = patch("desktop.time.monotonic", self.clock)
        self.clock_patch.start()
        self.camera = FakeCamera(self.clock)
        self.wall = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        self.controller = DesktopController(self.app, Path(self.temporary.name),
                                            camera=self.camera, tray=False, wall_clock=lambda: self.wall)
        # Tests advance the logical clock and controller explicitly. Native
        # animation and polling timers must not introduce incidental events.
        self.controller.timer.stop()
        self.controller.widget.animation.stop()
        self.app.processEvents()

    def tearDown(self):
        self.controller.cleanup()
        try:
            self.app.aboutToQuit.disconnect(self.controller.cleanup)
        except RuntimeError:
            pass
        self.controller.widget.hide()
        self.controller.menu.deleteLater()
        self.controller.widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.clock_patch.stop()
        self.temporary.cleanup()

    def click_cat(self):
        QTest.mouseClick(self.controller.widget, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(120, 180))
        self.app.processEvents()

    def test_widget_is_a_transparent_frameless_floating_tool(self):
        widget = self.controller.widget
        self.assertEqual(widget.windowType(), Qt.WindowType.Tool)
        self.assertTrue(widget.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(widget.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow))

    def test_constructing_widget_never_starts_the_camera(self):
        self.assertEqual(self.camera.start_calls, 0)
        self.assertFalse(self.controller.active)
        self.assertFalse(self.controller.widget.active)
        self.assertEqual(self.camera.snapshot()["status"], "off")

    def test_click_activates_background_tracking_without_a_browser(self):
        self.click_cat()
        self.assertEqual(self.camera.start_calls, 1)
        self.assertTrue(self.controller.active)
        self.assertTrue(self.controller.widget.active)
        self.assertEqual(self.controller.activation_action.text(), "Pause camera")

    def test_pause_stops_camera_without_blocking_the_ui(self):
        self.controller.activate()
        self.controller.pause()
        self.assertEqual(self.camera.stop_calls, [False])
        self.assertFalse(self.controller.active)
        self.assertFalse(self.controller.widget.active)
        self.assertEqual(self.controller.activation_action.text(), "Activate camera")

    def test_clicking_an_active_cat_acknowledges_without_pausing(self):
        self.click_cat()
        self.click_cat()
        self.assertEqual(self.camera.start_calls, 1)
        self.assertEqual(self.camera.stop_calls, [])
        self.assertTrue(self.controller.active)
        self.assertEqual(self.controller.widget.pose, "happy")
        counts = self.controller.journal.today(self.controller.store.state()["timezone"])
        self.assertEqual(counts.get("acknowledged"), 1)

    def test_fresh_smile_drives_the_rendered_cat_pose(self):
        self.controller.activate()
        self.camera.observe("smile")
        self.controller.tick()
        self.assertEqual(self.controller.widget.pose, "happy")
        self.assertTrue(self.controller.behavior.update(self.camera.snapshot(), now=self.clock())["observed"])

    def test_frame_published_during_poll_is_not_rejected_as_future(self):
        self.controller.activate()
        original_snapshot = self.camera.snapshot

        def freshly_published_snapshot():
            self.clock.advance(.001)
            self.camera.observe("smile")
            return original_snapshot()

        with patch.object(self.camera, "snapshot", side_effect=freshly_published_snapshot):
            self.controller.tick()
        self.assertEqual(self.controller.widget.pose, "happy")
        self.assertNotIn("no face", self.controller.widget.label)

    def test_stale_tracking_clears_the_rendered_expression(self):
        self.controller.activate()
        self.camera.observe("smile")
        self.controller.tick()
        self.clock.advance(4)
        self.controller.tick()
        self.assertEqual(self.controller.widget.pose, "idle")
        self.assertIn("no face", self.controller.widget.label)
        self.assertTrue(self.controller.active)

    def test_face_leaving_view_clears_the_rendered_expression(self):
        self.controller.activate()
        self.camera.observe("smile")
        self.controller.tick()
        self.camera.observe(None, present=False)
        self.controller.tick()
        self.assertEqual(self.controller.widget.pose, "idle")
        self.assertIn("no face", self.controller.widget.label)

    def test_hand_gesture_moves_body_while_face_keeps_smiling(self):
        self.controller.activate()
        self.camera.observe("smile")
        self.camera.state.update(gesture="open_palm", hands_present=True)
        self.controller.tick()
        self.assertEqual(self.controller.widget.pose, "wave")
        self.assertEqual(self.controller.widget.face_pose, "happy")
        self.assertIn("Open palm", self.controller.widget.label)

    def test_break_reminder_survives_face_detection_gaps_and_starts_rest(self):
        self.controller.reminders.break_minutes = 5
        self.controller.activate()
        self.camera.observe(None, present=False)
        for _ in range(5):
            self.clock.advance(60)
            self.controller.tick()
        self.assertTrue(self.controller.has_scheduled_reminder)
        self.assertIn("break", self.controller.widget.message)
        self.click_cat()
        self.assertFalse(self.controller.active)
        self.assertFalse(self.controller.has_scheduled_reminder)
        self.assertIn("Resting", self.controller.widget.label)
        self.assertEqual(self.camera.stop_calls, [False])

    def test_daily_reminder_works_paused_and_dismissal_never_starts_camera(self):
        self.wall = datetime(2026, 11, 13, 15, 20, tzinfo=timezone.utc)
        self.controller.tick()
        self.assertIn("roll a joint", self.controller.widget.message)
        self.assertTrue(self.controller.has_scheduled_reminder)
        self.click_cat()
        self.assertEqual(self.camera.start_calls, 0)
        self.assertFalse(self.controller.has_scheduled_reminder)
        self.assertEqual(self.controller.settings.value("last_daily_key"), "2026-11-13@16:20")

    def test_camera_error_does_not_move_behavior_clock_backwards(self):
        self.controller.activate()
        self.clock.advance(1)
        self.camera.state.update(status="error", message="Camera is not available")
        self.controller.tick()
        self.assertFalse(self.controller.active)
        self.assertEqual(self.controller.widget.pose, "sleeping")

    def test_finishing_a_break_needs_explicit_click_to_restart_camera(self):
        self.controller.reminders.rest_minutes = 1
        self.controller.activate()
        self.controller.start_break()
        calls = self.camera.start_calls
        self.clock.advance(60)
        self.controller.tick()
        self.assertEqual(self.camera.start_calls, calls)
        self.assertIn("break is over", self.controller.widget.message)
        self.click_cat()
        self.assertEqual(self.camera.start_calls, calls + 1)
        self.assertTrue(self.controller.active)

    def test_drag_moves_and_persists_position_without_activating(self):
        widget = self.controller.widget
        widget.move(200, 200)
        original = widget.pos()
        QTest.mousePress(widget, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(100, 180))
        QTest.mouseMove(widget, QPoint(160, 210))
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, QPoint(160, 210))
        self.app.processEvents()
        self.assertNotEqual(widget.pos(), original)
        self.assertEqual(self.camera.start_calls, 0)
        self.assertFalse(self.controller.active)
        self.assertEqual(int(self.controller.settings.value("x")), widget.x())
        self.assertEqual(int(self.controller.settings.value("y")), widget.y())

    def test_cat_render_preserves_transparent_desktop_corners(self):
        image = self.controller.widget.grab().toImage()
        self.assertTrue(image.hasAlphaChannel())
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(image.pixelColor(120, 180).alpha(), 0)


if __name__ == "__main__":
    unittest.main()
