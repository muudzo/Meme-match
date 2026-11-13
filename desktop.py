"""Purrpose: a real, transparent desktop cat. No browser or server is started."""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import sys
import time
from collections import deque


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Override the local application data directory.")
    parser.add_argument("--screenshot", type=Path, help="Render a transparent preview without opening a camera.")
    parser.add_argument("--demo", choices=("idle", "sleeping", "happy", "curious", "concerned", "stretch", "surprised", "wink", "wave", "cheer", "heart", "paw"), default="sleeping")
    parser.add_argument("--self-test", action="store_true", help="Verify the native widget and packaged model without webcam access.")
    parser.add_argument("--updater-self-test", action="store_true", help="Verify the packaged native updater without activating the camera (macOS Cocoa session).")
    return parser.parse_args(argv)


# Qt is only required by the native entry point, not the recognition/report core.
try:
    from PySide6.QtCore import QLockFile, QPoint, QPointF, QRectF, QSettings, QStandardPaths, QTime, Qt, QTimer
    from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRegion
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
        QFileDialog, QFormLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
        QSpinBox, QSystemTrayIcon, QTextBrowser, QTimeEdit, QVBoxLayout, QWidget)
except ImportError:
    if __name__ == "__main__":
        raise SystemExit("Install the native app dependencies with .venv/bin/python -m pip install -r requirements-desktop.txt, then run ./run_purrpose.sh.")
    raise

from companion_camera import CompanionCamera
from companion_store import CompanionStore
from desktop_behavior import CatBehavior
from desktop_journal import DesktopJournal
from desktop_reminders import DesktopReminders

GESTURE_LABELS = {"thumbs_up": "Thumbs up · nice one!", "thumbs_down": "Thumbs down · I see you",
                  "peace": "Peace · wink!", "open_palm": "Open palm · hello!", "fist": "Fist bump!",
                  "pointing": "Pointing · what's up?", "love_you": "Love you too!"}
EXPRESSION_LABELS = {"smile": "Smile · smiling with you", "grin": "Grin · looking good!",
                     "wink": "Wink · right back at you", "eyebrows_raised": "Raised eyebrows · curious!",
                     "mouth_open": "Open mouth · wow!", "kiss": "Puckered lips · a little love",
                     "frown": "Frown · here with you", "eyes_closed": "Eyes closed · resting"}


def path(points):
    result = QPainterPath()
    result.moveTo(*points[0])
    for point in points[1:]:
        if len(point) == 2:
            result.lineTo(*point)
        else:
            result.cubicTo(*point)
    result.closeSubpath()
    return result


def draw_cat(painter, pose="idle", phase=0, active=True, prompting=False, face_pose=None):
    """Draw a small tuxedo cat in a 300×280 coordinate system."""
    dark, white = QColor("#30382b"), QColor("#f7f8f3")
    eye, ear = QColor("#cedcae"), QColor("#a7b49d")
    face = face_pose if face_pose and face_pose != "idle" else {"wave": "happy", "cheer": "happy", "heart": "happy", "paw": "curious"}.get(pose, pose)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(20, 30, 20, 28))
    painter.drawEllipse(QRectF(70, 258, 167, 9))
    tail = QPainterPath(QPointF(207, 241))
    swing = math.sin(phase * (3 if pose in {"cheer", "wave"} else 1.4)) * (12 if pose in {"happy", "cheer", "heart"} else 4)
    tail.cubicTo(261, 270, 280 + swing, 230, 254 + swing, 200)
    tail.cubicTo(248 + swing, 191, 247 + swing, 179, 251 + swing, 171)
    painter.setPen(QPen(dark, 20, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawPath(tail)
    painter.setPen(QPen(white, 18, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(251 + swing, 174), QPointF(252 + swing, 187))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.save()
    painter.translate(0, math.sin(phase * (4 if pose == "cheer" else 1.6)) * (4 if pose == "cheer" else 1.8))
    painter.setBrush(dark)
    painter.drawPath(path([(109, 170), (85, 191, 76, 220, 80, 247), (85, 265, 215, 265, 219, 246), (218, 215, 207, 187, 187, 170)]))
    painter.setBrush(white)
    painter.drawEllipse(QRectF(116, 165, 59, 87))
    painter.setBrush(dark)
    painter.drawEllipse(QRectF(88, 212, 40, 46))
    painter.drawEllipse(QRectF(169, 213, 37, 45))
    painter.setBrush(white)
    painter.drawEllipse(QRectF(88, 244, 39, 16))
    painter.drawEllipse(QRectF(169, 244, 37, 16))
    painter.setPen(Qt.PenStyle.NoPen)
    # The head moves as one shape; facial features always stay aligned.
    painter.save()
    tilt = -7 if face == "curious" else 3 if face == "concerned" else 0
    painter.translate(150, 138)
    painter.rotate(tilt)
    painter.translate(-150, -138)
    droop = 11 if face in {"concerned", "sleeping"} else 0
    painter.setBrush(dark)
    painter.drawPath(path([(77, 104), (66 - droop, 30 + droop), (126, 62)]))
    painter.drawPath(path([(177, 62), (234 + droop, 30 + droop), (224, 105)]))
    painter.setBrush(ear)
    painter.drawPolygon(QPolygonF([QPointF(80, 77), QPointF(75 - droop / 2, 45 + droop), QPointF(105, 68)]))
    painter.drawPolygon(QPolygonF([QPointF(198, 68), QPointF(226 + droop / 2, 45 + droop), QPointF(219, 79)]))
    painter.setBrush(dark)
    painter.drawPath(path([(148, 53), (191, 53, 226, 75, 230, 121), (234, 169, 201, 197, 151, 197), (101, 197, 67, 171, 70, 124), (72, 78, 104, 53, 148, 53)]))
    painter.setBrush(white)
    painter.drawPath(path([(149, 80), (140, 107, 135, 121, 120, 136), (102, 154, 101, 165, 108, 179), (133, 201, 173, 202, 199, 177), (205, 162, 198, 150, 182, 136), (166, 121, 158, 106, 149, 80)]))
    closed = face == "sleeping" or (face not in {"surprised", "curious"} and phase % 7 > 6.78)
    painter.setPen(QPen(eye, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x, shut in ((113, closed), (185, closed or face == "wink")):
        if shut:
            curve = QPainterPath(QPointF(x - 9, 125))
            curve.quadTo(x, 131, x + 9, 125)
            painter.drawPath(curve)
        else:
            radius = 14 if face in {"curious", "surprised"} else 11
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(eye)
            painter.drawEllipse(QRectF(x - 9, 123 - radius, 18, radius * 2))
            painter.setBrush(QColor("#22291f"))
            painter.drawEllipse(QRectF(x - 3, 123 - radius + 2, 6, radius * 2 - 3))
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(QRectF(x - 5, 117, 4, 4))
            painter.setPen(QPen(eye, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#878b80"))
    painter.drawPath(path([(142, 148), (150, 155), (158, 148), (154, 143, 146, 143, 142, 148)]))
    painter.setPen(QPen(QColor("#48503f"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    mouth = QPainterPath(QPointF(137, 163))
    if face == "surprised":
        painter.setBrush(dark)
        painter.drawEllipse(QRectF(142, 159, 16, 20))
    elif face == "concerned":
        mouth.quadTo(150, 151, 163, 163)
        painter.drawPath(mouth)
    elif face == "happy":
        mouth.quadTo(150, 180, 163, 163)
        painter.drawPath(mouth)
    else:
        mouth.quadTo(143, 171, 150, 162)
        mouth.quadTo(157, 171, 163, 163)
        painter.drawPath(mouth)
    painter.setPen(QPen(QColor("#a3ad98"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for a, b in [((101, 153), (67, 149)), ((101, 161), (64, 166)), ((199, 153), (233, 149)), ((199, 161), (236, 166))]:
        painter.drawLine(QPointF(*a), QPointF(*b))
    painter.restore()
    # A reaching paw is a quiet visual prompt, rather than a notification modal.
    if prompting or pose in {"stretch", "wave", "cheer", "paw"}:
        paw_x = 221 + (math.sin(phase * 5) * 9 if pose == "wave" else 0)
        paw_y = (80 if pose == "cheer" else 191 if pose == "paw" else 173) - math.sin(phase * 3) * 5
        painter.setPen(QPen(dark, 27, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(190, 218), QPointF(paw_x, paw_y))
        painter.setPen(QPen(white, 21, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPoint(QPointF(paw_x + 1, paw_y - 2))
        if pose == "cheer":
            painter.setPen(QPen(dark, 27, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(112, 218), QPointF(78, paw_y))
            painter.setPen(QPen(white, 21, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPoint(QPointF(77, paw_y - 2))
    if pose == "heart":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#c46a76"))
        heart = QPainterPath(QPointF(208, 167))
        heart.cubicTo(182, 150, 190, 135, 208, 145)
        heart.cubicTo(226, 135, 234, 150, 208, 167)
        painter.drawPath(heart)
    painter.restore()


class CatWidget(QWidget):
    def __init__(self, controller=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("Purrpose — desktop cat")
        self.setAccessibleName("Purrpose desktop cat. Click to activate; right-click for controls.")
        self.setToolTip("Drag to move. Click to activate or check in. Right-click for controls.")
        self.setMouseTracking(True)
        self.pose = "sleeping"
        self.face_pose = None
        self.active = False
        self.prompting = False
        self.message = None
        self.label = "Click to activate"
        self.scale = 1.0
        self._press = None
        self._origin = None
        self._dragging = False
        self._phase_start = time.monotonic()
        self.resize(240, 318)
        self.animation = QTimer(self)
        self.animation.timeout.connect(self.update)
        self.animation.start(40)
        self._update_mask()

    def set_size(self, percent):
        self.scale = percent / 100
        self.resize(round(240 * self.scale), round(318 * self.scale))
        self._update_mask()

    def _update_mask(self):
        def region(rect, ellipse=False):
            scaled = QRectF(rect.x() * self.scale, rect.y() * self.scale, rect.width() * self.scale, rect.height() * self.scale).toRect()
            return QRegion(scaled, QRegion.RegionType.Ellipse) if ellipse else QRegion(scaled)
        mask = region(QRectF(43, 103, 142, 160), True)
        mask |= region(QRectF(48, 86, 140, 80))
        mask |= region(QRectF(157, 182, 58, 87), True)
        mask |= region(QRectF(26, 278, 188, 28))
        if self.message:
            mask |= region(QRectF(5, 3, 230, 67))
        self.setMask(mask)

    def show_state(self, *, pose, active, message=None, prompting=False, label=None, face_pose=None):
        changed_message = self.message != message
        self.pose, self.active, self.message, self.prompting = pose, active, message, prompting
        self.face_pose = face_pose
        self.label = label or ("Active · click to check in" if active else "Click to activate")
        if changed_message:
            self._update_mask()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.scale, self.scale)
        if self.message:
            painter.setPen(QPen(QColor("#dce2d8"), 1))
            painter.setBrush(QColor(250, 252, 247, 248))
            painter.drawRoundedRect(QRectF(6, 4, 228, 62), 14, 14)
            painter.setPen(QColor("#30382b"))
            painter.setFont(QFont("Arial", 11))
            painter.drawText(QRectF(18, 10, 204, 49), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
        painter.save()
        painter.translate(9, 70)
        painter.scale(.74, .74)
        draw_cat(painter, self.pose, time.monotonic() - self._phase_start, self.active, self.prompting, self.face_pose)
        painter.restore()
        painter.setPen(QPen(QColor(220, 226, 216, 230), 1))
        painter.setBrush(QColor(248, 250, 246, 242))
        painter.drawRoundedRect(QRectF(26, 278, 188, 28), 14, 14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1b6e66") if self.active else QColor("#8b9286"))
        painter.drawEllipse(QRectF(38, 289, 6, 6))
        painter.setFont(QFont("Arial", 10))
        painter.setPen(QColor("#40483a"))
        painter.drawText(QRectF(50, 279, 156, 26), Qt.AlignmentFlag.AlignCenter, self.label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._origin = self.pos()
            self._dragging = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._press is not None:
            delta = event.globalPosition().toPoint() - self._press
            if delta.manhattanLength() > QApplication.startDragDistance():
                self._dragging = True
            if self._dragging:
                self.move(self._origin + delta)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            clicked = not self._dragging
            self._press = None
            self.unsetCursor()
            if self.controller:
                if clicked:
                    self.controller.acknowledge() if self.active or self.controller.has_scheduled_reminder else self.controller.activate()
                else:
                    self.controller.save_position()
            event.accept()

    def contextMenuEvent(self, event):
        if self.controller:
            self.controller.menu.exec(event.globalPos())

    def closeEvent(self, event):
        if self.controller:
            self.controller.quit()
        event.accept()

    def join_desktop_spaces(self):
        """Keep this native NSPanel visible on other Spaces and above full-screen apps."""
        if sys.platform != "darwin" or QApplication.platformName() != "cocoa":
            return
        # Qt's macOS winId is its NSView. Use the public AppKit methods through
        # libobjc so no optional PyObjC install is needed for a floating pet.
        objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        def selector(name):
            return objc.sel_registerName(name.encode())
        get_ptr = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
        get_uint = ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
        set_uint = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)(("objc_msgSend", objc))
        set_bool = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)(("objc_msgSend", objc))
        window = get_ptr(int(self.winId()), selector("window"))
        if window:
            behavior = get_uint(window, selector("collectionBehavior"))
            # Joining all Spaces is exclusive with MoveToActiveSpace, and an
            # auxiliary panel must not also claim FullScreenPrimary.
            behavior &= ~((1 << 1) | (1 << 7))
            set_uint(window, selector("setCollectionBehavior:"), behavior | (1 << 0) | (1 << 8))
            set_bool(window, selector("setHidesOnDeactivate:"), False)


class DesktopController:
    def __init__(self, app, data_dir, *, camera=None, tray=True, wall_clock=None):
        self.app = app
        self._wall_clock = wall_clock
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(self.data_dir / "widget.ini"), QSettings.Format.IniFormat)
        self.store = CompanionStore(self.data_dir / "diary.sqlite3")
        self.journal = DesktopJournal(self.data_dir / "widget-events.sqlite3")
        self.camera = camera if camera is not None else CompanionCamera(self.store)
        self.behavior = CatBehavior(checkin_minutes=int(self.settings.value("checkin_minutes", 10)))
        self.reminders = DesktopReminders(
            break_minutes=int(self.settings.value("break_minutes", 25)),
            rest_minutes=int(self.settings.value("rest_minutes", 5)),
            daily_time=str(self.settings.value("daily_time", "16:20")),
            daily_text=str(self.settings.value("daily_text", "4:20 — roll a joint.")),
            daily_enabled=self.settings.value("daily_enabled", True, type=bool),
            last_daily_key=str(self.settings.value("last_daily_key", "")),
        )
        self._reminder_queue = deque()
        self._scheduled = None
        self._scheduled_until = 0
        self.active = False
        self._closed = False
        self._notice = None
        self._notice_until = 0
        self._ack_until = 0
        self._last_error = None
        self._last_save = 0
        self.widget = CatWidget(self)
        self.widget.set_size(int(self.settings.value("size_percent", 100)))
        self.menu = QMenu()
        self.activation_action = self.menu.addAction("Activate camera", self.toggle)
        self.menu.addAction("I'm here", self.acknowledge)
        self.menu.addAction("I drifted — reset", self.self_reported_reset)
        self.menu.addSeparator()
        self.break_action = self.menu.addAction(f"Take a {self.reminders.rest_minutes}-minute break", self.start_break)
        self.snooze_action = self.menu.addAction("Snooze break reminder for 5 minutes", self.snooze_break)
        self.menu.addSeparator()
        self.menu.addAction("Reminder settings…", self.preferences)
        self.menu.addAction("Today's reflection…", self.reflection)
        self.menu.addAction("Camera details…", self.camera_details)
        self.menu.addAction("Reset position", self.reset_position)
        self.update_action = self.menu.addAction("Check for updates…")
        self.update_action.setEnabled(False)
        self.menu.addSeparator()
        self.menu.addAction("Quit Purrpose", self.quit)
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(64 / 300, 64 / 280)
        draw_cat(painter, "idle")
        painter.end()
        self.icon = QIcon(pixmap)
        self.app.setWindowIcon(self.icon)
        self.tray = None
        if tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.icon, self.widget)
            self.tray.setToolTip("Purrpose · camera paused")
            self.tray.setContextMenu(self.menu)
            self.tray.show()
        self.reset_position(restore=True)
        self.widget.show()
        self.widget.join_desktop_spaces()
        self.timer = QTimer(self.widget)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.app.aboutToQuit.connect(self.cleanup)
        self.tick()

    def activate(self):
        if self._closed:
            return
        snapshot = self.camera.start()
        if snapshot["status"] == "error":
            self._last_error = snapshot.get("message")
            self.notice("Camera needs permission or setup. Right-click → Camera details.", 15)
            return
        self.active = True
        self.behavior.set_active(True)
        self.reminders.set_working(True, time.monotonic())
        self.journal.record("activated")
        self.activation_action.setText("Pause camera")
        self.notice("I'm here with you. Click me whenever you want to come back to the moment.", 8)
        self.tick()

    def pause(self):
        self.active = False
        self.behavior.set_active(False)
        self.reminders.set_working(False, time.monotonic())
        self.camera.stop(wait=False)
        self.activation_action.setText("Activate camera")
        self.journal.record("paused")
        self.notice("Taking a nap. Your camera is turning off.", 5)
        self.tick()

    def toggle(self):
        self.pause() if self.active else self.activate()

    def notice(self, message, seconds=5):
        self._notice, self._notice_until = message, time.monotonic() + seconds

    def acknowledge(self):
        if self._scheduled and self._scheduled["kind"] == "break":
            self.start_break()
            return
        if self._scheduled and self._scheduled["kind"] == "rest_finished":
            self._scheduled = None
            self.activate()
            return
        if self._scheduled:
            self._scheduled = None
            self.notice("A little moment for you.", 4)
            self.tick()
            return
        if not self.active:
            return
        self.behavior.acknowledge()
        self.journal.record("acknowledged")
        self._ack_until = time.monotonic() + 2
        self.notice("There you are. One breath, then your next small step.", 5)
        self.tick()

    @property
    def has_scheduled_reminder(self):
        return self._scheduled is not None

    def start_break(self):
        self._scheduled = None
        self._reminder_queue = deque(item for item in self._reminder_queue if item["kind"] != "break")
        self.pause()
        self.reminders.start_break(time.monotonic())
        self.journal.record("break_started")
        self.notice(f"Enjoy your {self.reminders.rest_minutes}-minute break. I'll keep time while you rest.", 8)
        self.tick()

    def snooze_break(self):
        self.reminders.snooze(time.monotonic())
        if self._scheduled and self._scheduled["kind"] == "break":
            self._scheduled = None
        self._reminder_queue = deque(item for item in self._reminder_queue if item["kind"] != "break")
        self.notice("I'll remind you again after 5 more minutes of work.", 5)
        self.tick()

    def self_reported_reset(self):
        self.journal.record("self_reported_reset")
        if self.active:
            self.acknowledge()
        else:
            self.notice("A moment to reset. Activate me whenever you'd like company.", 6)

    def tick(self):
        if self._closed:
            return
        snapshot = self.camera.snapshot()
        # Capture the consumer time after reading the snapshot. A camera frame
        # can arrive between these two operations; reading the clock first
        # incorrectly makes that fresh frame look like a future observation.
        now = time.monotonic()
        if self.active and snapshot["status"] == "error":
            self._last_error = snapshot.get("message")
            self.active = False
            self.behavior.set_active(False, now=now)
            self.reminders.set_working(False, now)
            self.activation_action.setText("Activate camera")
            self.notice("I couldn't open the camera. Right-click → Camera details.", 15)
        elif self.active and snapshot["status"] == "running":
            self._last_error = None
        state = self.behavior.update(snapshot, now=now)
        if state["nudge"]:
            self.journal.record("prompt")
            self._notice_until = 0
        message = self._notice if now < self._notice_until else state["message"]
        pose = "sleeping" if not self.active else "happy" if now < self._ack_until else state["pose"]
        reminder_state = self.reminders.update(now, wall_now=self._wall_clock() if self._wall_clock else None)
        for item in reminder_state["events"]:
            self._reminder_queue.append(item)
            if item["kind"] in {"break", "daily"}:
                self.journal.record("break_reminder" if item["kind"] == "break" else "daily_reminder")
            if item["kind"] == "daily":
                self.settings.setValue("last_daily_key", reminder_state["last_daily_key"])
                self.settings.sync()
        if self._scheduled and now >= self._scheduled_until:
            if self._scheduled["kind"] == "break":
                self.reminders.snooze(now)
            self._scheduled = None
        if not self._scheduled and self._reminder_queue:
            self._scheduled = self._reminder_queue.popleft()
            self._scheduled_until = now + 45
            if self.tray and QSystemTrayIcon.supportsMessages():
                self.tray.showMessage("Purrpose", self._scheduled["message"], QSystemTrayIcon.MessageIcon.Information, 10000)
        if self._scheduled:
            message = self._scheduled["message"]
            pose = self._scheduled["pose"]
        if reminder_state["rest_remaining"] > 0:
            remaining = math.ceil(reminder_state["rest_remaining"])
            label = f"Resting · {remaining // 60:02}:{remaining % 60:02}"
        elif self._scheduled:
            label = "Click to take a break" if self._scheduled["kind"] == "break" else "Click when you're ready" if self._scheduled["kind"] == "rest_finished" else "Your daily reminder"
        elif not self.active:
            label = "Camera closing…" if snapshot["status"] == "stopping" else "Click to activate"
        elif snapshot["status"] == "starting":
            label = "Opening camera…"
        elif snapshot["status"] == "stopping":
            label = "Restarting camera…"
        elif state.get("gesture"):
            label = GESTURE_LABELS[state["gesture"]]
        elif not state["observed"]:
            label = "Active · no face in view"
        else:
            label = EXPRESSION_LABELS.get(state["expression"], "Active · click to check in")
        self.snooze_action.setEnabled(reminder_state["break_due"])
        self.widget.show_state(pose=pose, active=self.active, message=message,
                               prompting=state["prompt_visible"] or self._scheduled is not None, label=label,
                               face_pose=state.get("face_pose") if self.active and not self._scheduled else None)
        if self.tray:
            self.tray.setToolTip("Purrpose · camera active" if self.active else "Purrpose · camera paused")
        if now - self._last_save >= 30:
            self.store.state()  # Maintains the daily reflection without a dashboard.
            self._last_save = now

    def reset_position(self, restore=False):
        screens = self.app.screens()
        if restore and self.settings.contains("x") and self.settings.contains("y"):
            position = QPoint(int(self.settings.value("x")), int(self.settings.value("y")))
            if any(screen.availableGeometry().intersects(self.widget.rect().translated(position)) for screen in screens):
                self.widget.move(position)
                return
        rect = self.app.primaryScreen().availableGeometry()
        self.widget.move(rect.right() - self.widget.width() - 35, rect.bottom() - self.widget.height() - 16)

    def save_position(self):
        self.settings.setValue("x", self.widget.x())
        self.settings.setValue("y", self.widget.y())

    def preferences(self):
        dialog = QDialog(self.widget)
        dialog.setWindowTitle("Purrpose · gentle reminders")
        layout = QFormLayout(dialog)
        copy = QLabel("Your cat mirrors facial reactions. Optional reminders invite you to notice the moment; they don't detect thoughts.")
        copy.setWordWrap(True)
        copy.setMaximumWidth(350)
        layout.addRow(copy)
        interval = QSpinBox()
        interval.setRange(1, 60)
        interval.setSuffix(" minutes")
        interval.setValue(int(self.settings.value("checkin_minutes", 10)))
        layout.addRow("Gentle check-in interval", interval)
        break_interval = QSpinBox()
        break_interval.setRange(5, 120)
        break_interval.setSuffix(" minutes of work")
        break_interval.setValue(self.reminders.break_minutes)
        layout.addRow("Remind me to take a break after", break_interval)
        rest_duration = QSpinBox()
        rest_duration.setRange(1, 30)
        rest_duration.setSuffix(" minutes")
        rest_duration.setValue(self.reminders.rest_minutes)
        layout.addRow("Break length", rest_duration)
        daily_enabled = QCheckBox("Enable daily reminder")
        daily_enabled.setChecked(self.reminders.daily_enabled)
        layout.addRow(daily_enabled)
        daily_time = QTimeEdit(QTime.fromString(self.reminders.daily_time, "HH:mm"))
        daily_time.setDisplayFormat("HH:mm")
        layout.addRow("Daily reminder time", daily_time)
        daily_text = QLineEdit(self.reminders.daily_text)
        daily_text.setMaxLength(160)
        layout.addRow("Reminder text", daily_text)
        layout.addRow(QLabel("Daily reminders use Europe/Amsterdam time while Purrpose is running."))
        size = QComboBox()
        for percent in (75, 100, 125, 150):
            size.addItem(f"{percent}%", percent)
        size.setCurrentIndex(max(0, size.findData(int(self.settings.value("size_percent", 100)))))
        layout.addRow("Cat size", size)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if not daily_text.text().strip():
                QMessageBox.information(self.widget, "Reminder text", "Please enter a message for your daily reminder.")
                return
            self.settings.setValue("checkin_minutes", interval.value())
            self.settings.setValue("size_percent", size.currentData())
            self.behavior.configure(checkin_minutes=interval.value())
            values = {"break_minutes": break_interval.value(), "rest_minutes": rest_duration.value(),
                      "daily_enabled": daily_enabled.isChecked(),
                      "daily_time": daily_time.time().toString("HH:mm"), "daily_text": daily_text.text().strip()}
            self.reminders.configure(**values)
            for key, value in values.items():
                self.settings.setValue(key, value)
            self.break_action.setText(f"Take a {self.reminders.rest_minutes}-minute break")
            self.widget.set_size(size.currentData())
            self.save_position()

    def reflection_text(self):
        report = self.store.report()
        counts = self.journal.today(report["timezone"])
        text = (f"# Your day with Purrpose — {report['date']}\n\n"
                f"Gentle prompts offered: {counts.get('prompt', 0)}\n"
                f"Times you checked in with your cat: {counts.get('acknowledged', 0)}\n"
                f"Resets you explicitly reported: {counts.get('self_reported_reset', 0)}\n\n"
                f"Break reminders: {counts.get('break_reminder', 0)}\n"
                f"Breaks you started: {counts.get('break_started', 0)}\n\n"
                "These are interactions you recorded, not a measure of attention or a count of wandering thoughts.\n\n"
                "## Facial reactions observed locally\n\n")
        for item in report["expressions"]:
            seconds = int(item["seconds"])
            text += f"- {item['expression'].replace('_', ' ')}: {seconds // 60} min {seconds % 60} sec\n"
        if not report["expressions"]:
            text += "No expression observation time recorded.\n"
        text += "\nCamera gaps stay unobserved. No photos or video are saved.\n"
        return text

    def reflection(self):
        dialog = QDialog(self.widget)
        dialog.setWindowTitle("Purrpose · today's reflection")
        dialog.resize(470, 430)
        layout = QVBoxLayout(dialog)
        text = self.reflection_text()
        view = QTextBrowser()
        view.setMarkdown(text)
        layout.addWidget(view)
        export = QPushButton("Save reflection…")
        def save():
            filename, _ = QFileDialog.getSaveFileName(dialog, "Save reflection", f"purrpose-{self.store.current_day()}.md", "Markdown (*.md)")
            if filename:
                Path(filename).write_text(text, encoding="utf-8")
        export.clicked.connect(save)
        layout.addWidget(export)
        dialog.exec()

    def camera_details(self):
        snapshot = self.camera.snapshot()
        details = self._last_error or snapshot.get("message", "Camera is paused.")
        details += f"\n\nFace: {snapshot.get('expression') or 'not recognized yet'}\nHand gesture: {snapshot.get('gesture') or 'not recognized yet'}"
        if snapshot["status"] == "running" and not snapshot.get("gestures_available"):
            details += "\nThe hand model is missing. Update the app or download both models from source."
        QMessageBox.information(self.widget, "Purrpose · camera", details + "\n\nCamera processing stays on this device. Pause or quit to release it.")

    def cleanup(self):
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.save_position()
        self.camera.stop()
        if self.tray:
            self.tray.hide()
        self.settings.sync()
        self.store.close()
        self.journal.close()

    def quit(self):
        self.cleanup()
        self.app.quit()


def self_test(app):
    widget = CatWidget()
    assert widget.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    camera = CompanionCamera()
    assert camera.snapshot()["status"] == "off"
    model = Path(__file__).resolve().parent / "models" / "face_landmarker.task"
    import cv2
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core import base_options
    options = vision.FaceLandmarkerOptions(base_options=base_options.BaseOptions(model_asset_path=str(model)), num_faces=1, output_face_blendshapes=True)
    with vision.FaceLandmarker.create_from_options(options) as landmarker:
        result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((64, 64, 3), dtype=np.uint8)))
        assert not result.face_landmarks
    hand_model = model.parent / "gesture_recognizer.task"
    hand_options = vision.GestureRecognizerOptions(base_options=base_options.BaseOptions(model_asset_path=str(hand_model)), num_hands=2)
    with vision.GestureRecognizer.create_from_options(hand_options) as recognizer:
        hand_result = recognizer.recognize(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((64, 64, 3), dtype=np.uint8)))
        assert not hand_result.hand_landmarks
    print(json.dumps({"native_widget": True, "transparent": True, "always_on_top": True,
                      "camera_off": True, "model_inference": True, "hand_model_inference": True, "opencv": cv2.__version__}), flush=True)


def main(argv=None):
    args = arguments(argv)
    if args.screenshot or args.self_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Purrpose")
    app.setOrganizationName("Purrpose")
    app.setQuitOnLastWindowClosed(False)
    if args.updater_self_test:
        from desktop_updater import DesktopUpdater
        updater = DesktopUpdater()
        updater.start()
        ready = updater.can_check
        print(json.dumps({"native_updater": ready, "camera_off": True, "error": updater.error}), flush=True)
        return 0 if ready else 1
    if args.self_test:
        self_test(app)
        return 0
    if args.screenshot:
        widget = CatWidget()
        widget.show_state(pose=args.demo, active=args.demo != "sleeping",
                          message="One breath. What are you working on?" if args.demo == "stretch" else None,
                          prompting=args.demo == "stretch")
        widget.show()
        app.processEvents()
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        if not widget.grab().save(str(args.screenshot)):
            raise RuntimeError("Could not save widget preview")
        return 0
    data_dir = args.data_dir or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    data_dir.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(data_dir / "widget.lock"))
    if not instance_lock.tryLock(0):
        print("Purrpose is already running. Use its cat or menu-bar icon.", flush=True)
        return 0
    app._purrpose_instance_lock = instance_lock
    app.aboutToQuit.connect(instance_lock.unlock)
    controller = DesktopController(app, data_dir)
    from desktop_updater import DesktopUpdater
    updater = DesktopUpdater()
    app._purrpose_updater = updater
    controller.update_action.triggered.connect(updater.check)
    controller.menu.aboutToShow.connect(lambda: controller.update_action.setEnabled(updater.can_check))
    if updater.error:
        print(f"Updater unavailable: {updater.error}", file=sys.stderr, flush=True)
    QTimer.singleShot(0, updater.start)
    # Keep the controller alive for the entire native event loop.
    app._purrpose_controller = controller
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
