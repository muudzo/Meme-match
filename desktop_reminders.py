"""Camera-independent break timing and a once-per-day local-time reminder."""
from datetime import datetime
import math
from zoneinfo import ZoneInfo


class DesktopReminders:
    def __init__(self, break_minutes=25, rest_minutes=5, daily_time="16:20",
                 daily_text="4:20 — roll a joint.", daily_enabled=True,
                 timezone_name="Europe/Amsterdam", last_daily_key=""):
        self._last_now = None
        self._working = False
        self._work_seconds = 0.0
        self._break_due = False
        self._rest_until = None
        self._rest_finished = False
        self.last_daily_key = last_daily_key
        self.configure(break_minutes=break_minutes, rest_minutes=rest_minutes,
                       daily_time=daily_time, daily_text=daily_text,
                       daily_enabled=daily_enabled, timezone_name=timezone_name)

    def configure(self, *, break_minutes, rest_minutes, daily_time, daily_text,
                  daily_enabled=True, timezone_name="Europe/Amsterdam"):
        if isinstance(break_minutes, bool) or not isinstance(break_minutes, int) or not 5 <= break_minutes <= 120:
            raise ValueError("Break interval must be 5–120 minutes.")
        if isinstance(rest_minutes, bool) or not isinstance(rest_minutes, int) or not 1 <= rest_minutes <= 30:
            raise ValueError("Rest duration must be 1–30 minutes.")
        try:
            hour, minute = (int(part) for part in daily_time.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59) or daily_time != f"{hour:02}:{minute:02}":
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise ValueError("Daily time must use HH:MM.") from None
        if not isinstance(daily_text, str) or not 1 <= len(daily_text.strip()) <= 160:
            raise ValueError("Reminder text must contain 1–160 characters.")
        if not isinstance(daily_enabled, bool):
            raise ValueError("Daily reminder must be enabled or disabled.")
        zone = ZoneInfo(timezone_name)
        self.break_minutes, self.rest_minutes = break_minutes, rest_minutes
        self.daily_time, self.daily_text, self.daily_enabled = daily_time, daily_text.strip(), daily_enabled
        self.zone = zone
        self._daily_minute = hour * 60 + minute

    def _advance(self, now):
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ValueError("Time must be finite.")
        if self._last_now is not None:
            delta = now - self._last_now
            if delta < 0:
                raise ValueError("Time must be monotonic.")
            # A sleeping computer is not additional work time. Normal Qt timer
            # polling continues even when other apps cover the cat.
            if self._working and self._rest_until is None and delta <= 90:
                self._work_seconds += delta
        self._last_now = now
        if self._rest_until is not None and now >= self._rest_until:
            self._rest_until = None
            self._rest_finished = True

    def set_working(self, working, now):
        self._advance(now)
        self._working = bool(working)
        if working and self._rest_until is not None:
            self._rest_until = None  # Explicit activation can finish a rest early.
            self._rest_finished = False

    def start_break(self, now):
        self._advance(now)
        self._working = False
        self._work_seconds = 0
        self._break_due = False
        self._rest_finished = False
        self._rest_until = now + self.rest_minutes * 60

    def snooze(self, now, minutes=5):
        self._advance(now)
        self._break_due = False
        self._work_seconds = max(0, self.break_minutes * 60 - minutes * 60)

    def update(self, now, wall_now=None):
        self._advance(now)
        events = []
        if self._rest_finished:
            events.append({"kind": "rest_finished", "message": "Your break is over. Click me when you're ready.", "pose": "curious"})
            self._rest_finished = False
        if self._working and not self._break_due and self._work_seconds >= self.break_minutes * 60:
            self._break_due = True
            events.append({"kind": "break", "message": f"Time for a {self.rest_minutes}-minute break.\nClick me to start resting.", "pose": "stretch"})
        wall_now = wall_now or datetime.now(self.zone)
        if wall_now.tzinfo is None:
            raise ValueError("Wall time must have a timezone.")
        local = wall_now.astimezone(self.zone)
        minute = local.hour * 60 + local.minute
        key = f"{local.date().isoformat()}@{self.daily_time}"
        # A short catch-up window covers sleep/resume without showing a stale
        # 16:20 notification when the app is first opened late at night.
        if (self.daily_enabled and self._daily_minute <= minute < self._daily_minute + 15
                and key != self.last_daily_key):
            self.last_daily_key = key
            events.append({"kind": "daily", "message": self.daily_text, "pose": "wave"})
        return {"events": events, "break_due": self._break_due,
                "rest_remaining": max(0, self._rest_until - now) if self._rest_until is not None else 0,
                "working_seconds": self._work_seconds, "last_daily_key": self.last_daily_key}
