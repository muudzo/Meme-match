"""Local, durable records for Purrpose's focus timer and daily reflections.

The timer measures time a timer ran, not attention or productivity. Camera
expressions and self-reported moods are deliberately separate data streams.
Only timestamps and expression labels are stored; this module never sees images.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
MOODS = ("great", "good", "okay", "low", "stressed")
DEFAULT_SETTINGS = {
    "focus_minutes": 25,
    "break_minutes": 5,
    "daily_goal_minutes": 120,
    "report_hour": 18,
    "timezone": "Europe/Amsterdam",
    "cat_name": "Miso",
}
MAX_OBSERVATION_GAP = 2.5


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _seconds(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds())


def _duration(value: float) -> str:
    minutes = int(value // 60)
    if minutes >= 60:
        hours, rest = divmod(minutes, 60)
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    return f"{minutes} min" if minutes else f"{int(value)} sec"


class CompanionStore:
    """A thread-safe SQLite store, with an injectable UTC clock for testing.

    ``focus_sessions`` counts completed or finished focus sessions contributing
    positive timer time to the requested local date. ``focus_seconds`` includes
    a currently running or paused session, and excludes cancelled sessions.

    Call ``state()`` or ``heartbeat()`` while the app is open to checkpoint the
    timer. Reopening a store pauses an interrupted timer at its last checkpoint;
    time while the app was stopped is never added to the diary.
    """

    def __init__(self, db_path=None, *, clock=None, timezone_name="Europe/Amsterdam"):
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._closed = False
        self._last_observation = None
        db_path = Path(db_path or ".purrpose/purrpose.sqlite3")
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS task_completions (
                id INTEGER PRIMARY KEY,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                title TEXT NOT NULL, completed_at TEXT NOT NULL, undone_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                task_title TEXT, planned_seconds REAL NOT NULL,
                status TEXT NOT NULL, started_at TEXT NOT NULL,
                ended_at TEXT, last_checkpoint_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_session
                ON sessions ((1)) WHERE status IN ('running', 'paused');
            CREATE TABLE IF NOT EXISTS session_segments (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(id),
                started_at TEXT NOT NULL, ended_at TEXT
            );
            CREATE INDEX IF NOT EXISTS segment_session ON session_segments(session_id);
            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY, mood TEXT NOT NULL,
                energy INTEGER NOT NULL, note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, expression TEXT,
                face_present INTEGER NOT NULL,
                started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
                samples INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS reports (
                day TEXT NOT NULL, timezone TEXT NOT NULL,
                generated_at TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (day, timezone)
            );
            """
        )
        with self._lock, self._db:
            if not self._db.execute("SELECT 1 FROM settings WHERE id = 1").fetchone():
                initial = dict(DEFAULT_SETTINGS, timezone=timezone_name)
                self._validate_settings(initial)
                self._db.execute("INSERT INTO settings VALUES (1, ?)", (json.dumps(initial),))
            # Preserve completion history independently of a task's later deletion.
            # The SELECT also migrates records created before this event table.
            self._db.execute(
                "INSERT INTO task_completions (task_id, title, completed_at) "
                "SELECT id, title, completed_at FROM tasks WHERE completed = 1 AND completed_at IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM task_completions WHERE task_id = tasks.id AND undone_at IS NULL)"
            )
            self._recover_interrupted_sessions()

    def _now(self):
        value = self._clock()
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, UTC)
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("The clock must return a timezone-aware datetime or a Unix timestamp.")
        return value.astimezone(UTC)

    def _settings(self):
        return dict(DEFAULT_SETTINGS, **json.loads(self._db.execute(
            "SELECT payload FROM settings WHERE id = 1"
        ).fetchone()[0]))

    def current_day(self):
        with self._lock:
            return self._now().astimezone(ZoneInfo(self._settings()["timezone"])).date().isoformat()

    def _bounds(self, day, now, settings):
        tz = ZoneInfo(settings["timezone"])
        if day is None:
            value = now.astimezone(tz).date()
        else:
            try:
                value = date.fromisoformat(day)
            except (ValueError, TypeError):
                raise ValueError("Date must use YYYY-MM-DD.") from None
            if value.isoformat() != day:
                raise ValueError("Date must use YYYY-MM-DD.")
        start = datetime.combine(value, time.min, tzinfo=tz).astimezone(UTC)
        end = datetime.combine(value + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
        return value.isoformat(), start, end

    @staticmethod
    def _id(value):
        if isinstance(value, bool):
            raise ValueError("A valid record ID is required.")
        try:
            parsed = int(value)
        except (ValueError, TypeError):
            raise ValueError("A valid record ID is required.") from None
        if parsed < 1 or str(parsed) != str(value):
            raise ValueError("A valid record ID is required.")
        return parsed

    @staticmethod
    def _text(value, label, maximum, *, empty=False):
        if not isinstance(value, str):
            raise ValueError(f"{label} must be text.")
        value = value.strip()
        if (not value and not empty) or len(value) > maximum:
            raise ValueError(f"{label} must contain {'0' if empty else '1'}–{maximum} characters.")
        return value

    @staticmethod
    def _int(value, label, minimum, maximum):
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{label} must be an integer from {minimum} to {maximum}.")
        return value

    @classmethod
    def _validate_settings(cls, settings):
        for key, minimum, maximum in (
            ("focus_minutes", 1, 180), ("break_minutes", 1, 60),
            ("daily_goal_minutes", 5, 720), ("report_hour", 0, 23),
        ):
            cls._int(settings[key], key.replace("_", " ").capitalize(), minimum, maximum)
        cls._text(settings["cat_name"], "Cat name", 32)
        try:
            ZoneInfo(settings["timezone"])
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("Choose a valid IANA timezone, such as Europe/Amsterdam.") from None

    def update_settings(self, values):
        if not isinstance(values, dict) or set(values) - set(DEFAULT_SETTINGS):
            raise ValueError("Settings contain an unsupported field.")
        with self._lock, self._db:
            settings = dict(self._settings(), **values)
            self._validate_settings(settings)
            settings["cat_name"] = settings["cat_name"].strip()
            self._db.execute("UPDATE settings SET payload = ? WHERE id = 1", (json.dumps(settings),))
            return settings

    @staticmethod
    def _task(row):
        if row is None:
            return None
        value = dict(row)
        value["completed"] = bool(value["completed"])
        return value

    def add_task(self, title):
        title = self._text(title, "Task title", 200)
        with self._lock, self._db:
            row_id = self._db.execute(
                "INSERT INTO tasks (title, created_at) VALUES (?, ?)", (title, _iso(self._now()))
            ).lastrowid
            return self._task(self._db.execute("SELECT * FROM tasks WHERE id = ?", (row_id,)).fetchone())

    def update_task(self, task_id, completed):
        task_id = self._id(task_id)
        if not isinstance(completed, bool):
            raise ValueError("Completed must be true or false.")
        with self._lock, self._db:
            row = self._db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise ValueError("That task no longer exists.")
            completed_at = row["completed_at"] if completed and row["completed"] else (
                _iso(self._now()) if completed else None
            )
            if completed and not row["completed"]:
                self._db.execute(
                    "INSERT INTO task_completions (task_id, title, completed_at) VALUES (?, ?, ?)",
                    (task_id, row["title"], completed_at)
                )
            elif not completed and row["completed"]:
                self._db.execute(
                    "UPDATE task_completions SET undone_at = ? WHERE task_id = ? AND undone_at IS NULL",
                    (_iso(self._now()), task_id)
                )
            self._db.execute("UPDATE tasks SET completed = ?, completed_at = ? WHERE id = ?",
                             (int(completed), completed_at, task_id))
            return self._task(self._db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def delete_task(self, task_id):
        with self._lock, self._db:
            result = self._db.execute("DELETE FROM tasks WHERE id = ?", (self._id(task_id),))
            if not result.rowcount:
                raise ValueError("That task no longer exists.")
            return {"deleted": True}

    def _segments(self, session_id):
        return self._db.execute(
            "SELECT * FROM session_segments WHERE session_id = ? ORDER BY started_at, id", (session_id,)
        ).fetchall()

    def _elapsed(self, row, now, bounds=None):
        total = 0.0
        for segment in self._segments(row["id"]):
            start = _dt(segment["started_at"])
            end = _dt(segment["ended_at"]) if segment["ended_at"] else now
            if bounds:
                start, end = max(start, bounds[0]), min(end, bounds[1])
            total += _seconds(start, end)
        return min(total, row["planned_seconds"])

    def _recover_interrupted_sessions(self):
        for row in self._db.execute("SELECT * FROM sessions WHERE status = 'running'").fetchall():
            checkpoint = row["last_checkpoint_at"]
            self._db.execute(
                "UPDATE session_segments SET ended_at = MAX(started_at, ?) "
                "WHERE session_id = ? AND ended_at IS NULL", (checkpoint, row["id"])
            )
            elapsed = self._elapsed(row, _dt(checkpoint))
            completed = elapsed >= row["planned_seconds"]
            self._db.execute("UPDATE sessions SET status = ?, ended_at = ? WHERE id = ?",
                             ("completed" if completed else "paused", checkpoint if completed else None, row["id"]))

    def _tick(self, now):
        row = self._db.execute("SELECT * FROM sessions WHERE status = 'running'").fetchone()
        if row is None:
            return
        segment = self._db.execute(
            "SELECT * FROM session_segments WHERE session_id = ? AND ended_at IS NULL", (row["id"],)
        ).fetchone()
        if segment is None:
            self._db.execute("UPDATE sessions SET status = 'paused' WHERE id = ?", (row["id"],))
            return
        start = _dt(segment["started_at"])
        earlier = sum(_seconds(_dt(s["started_at"]), _dt(s["ended_at"]))
                      for s in self._segments(row["id"]) if s["ended_at"])
        deadline = start + timedelta(seconds=max(0, row["planned_seconds"] - earlier))
        if now >= deadline:
            self._db.execute("UPDATE session_segments SET ended_at = ? WHERE id = ?", (_iso(deadline), segment["id"]))
            self._db.execute("UPDATE sessions SET status = 'completed', ended_at = ?, last_checkpoint_at = ? WHERE id = ?",
                             (_iso(deadline), _iso(deadline), row["id"]))
        else:
            checkpoint = max(now, _dt(row["last_checkpoint_at"]), start)
            self._db.execute("UPDATE sessions SET last_checkpoint_at = ? WHERE id = ?", (_iso(checkpoint), row["id"]))

    def _session(self, row, now, bounds=None):
        if row is None:
            return None
        elapsed = self._elapsed(row, now)
        payload = {key: row[key] for key in (
            "id", "kind", "task_id", "task_title", "planned_seconds", "status", "started_at", "ended_at"
        )}
        payload.update(elapsed_seconds=round(elapsed, 3), remaining_seconds=round(max(0, row["planned_seconds"] - elapsed), 3))
        if bounds:
            payload["day_seconds"] = round(self._elapsed(row, now, bounds), 3)
        return payload

    def heartbeat(self):
        with self._lock, self._db:
            now = self._now()
            self._tick(now)
            return self._session(self._db.execute(
                "SELECT * FROM sessions WHERE status IN ('running', 'paused')"
            ).fetchone(), now)

    def start_session(self, task_id=None, duration_minutes=25, kind="focus"):
        self._int(duration_minutes, "Session minutes", 1, 180 if kind == "focus" else 60)
        if kind not in ("focus", "break"):
            raise ValueError("Session kind must be focus or break.")
        with self._lock, self._db:
            now = self._now()
            self._tick(now)
            if self._db.execute("SELECT 1 FROM sessions WHERE status IN ('running', 'paused')").fetchone():
                raise ValueError("Finish or cancel your current session before starting another.")
            task = None
            if task_id is not None:
                task_id = self._id(task_id)
                task = self._db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if task is None:
                    raise ValueError("That task no longer exists.")
                if task["completed"]:
                    raise ValueError("Choose an unfinished task for this session.")
            stamp = _iso(now)
            session_id = self._db.execute(
                "INSERT INTO sessions (kind, task_id, task_title, planned_seconds, status, started_at, last_checkpoint_at) "
                "VALUES (?, ?, ?, ?, 'running', ?, ?)",
                (kind, task_id, task["title"] if task else None, duration_minutes * 60, stamp, stamp)
            ).lastrowid
            self._db.execute("INSERT INTO session_segments (session_id, started_at) VALUES (?, ?)", (session_id, stamp))
            return self._session(self._db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone(), now)

    def session_action(self, action, expected_session_id=None):
        if action not in ("pause", "resume", "finish", "cancel"):
            raise ValueError("Session action must be pause, resume, finish or cancel.")
        if expected_session_id is not None:
            expected_session_id = self._id(expected_session_id)
        with self._lock, self._db:
            now = self._now()
            self._tick(now)
            row = self._db.execute("SELECT * FROM sessions WHERE status IN ('running', 'paused')").fetchone()
            if row is None:
                if action == "finish":
                    finished = self._db.execute(
                        "SELECT * FROM sessions WHERE status IN ('completed', 'finished') ORDER BY ended_at DESC, id DESC LIMIT 1"
                    ).fetchone()
                    if finished is not None:
                        if expected_session_id is not None and finished["id"] != expected_session_id:
                            raise ValueError("This session has changed. Refresh your workspace and try again.")
                        return self._session(finished, now)
                raise ValueError("There is no active session.")
            if expected_session_id is not None and row["id"] != expected_session_id:
                raise ValueError("This session has changed. Refresh your workspace and try again.")
            if action == "pause" and row["status"] != "running":
                raise ValueError("This session is already paused.")
            if action == "resume" and row["status"] != "paused":
                raise ValueError("This session is already running.")
            if action == "resume":
                self._db.execute("INSERT INTO session_segments (session_id, started_at) VALUES (?, ?)", (row["id"], _iso(now)))
                status, ended_at = "running", None
            else:
                self._db.execute(
                    "UPDATE session_segments SET ended_at = MAX(started_at, ?) WHERE session_id = ? AND ended_at IS NULL",
                    (_iso(now), row["id"])
                )
                status = {"pause": "paused", "finish": "finished", "cancel": "cancelled"}[action]
                ended_at = None if action == "pause" else _iso(now)
            self._db.execute("UPDATE sessions SET status = ?, ended_at = ?, last_checkpoint_at = ? WHERE id = ?",
                             (status, ended_at, _iso(now), row["id"]))
            return self._session(self._db.execute("SELECT * FROM sessions WHERE id = ?", (row["id"],)).fetchone(), now)

    def add_checkin(self, mood, energy, note=""):
        if mood not in MOODS:
            raise ValueError("Mood must be great, good, okay, low or stressed.")
        self._int(energy, "Energy", 1, 5)
        note = self._text(note, "Note", 1000, empty=True)
        with self._lock, self._db:
            row_id = self._db.execute("INSERT INTO checkins (mood, energy, note, created_at) VALUES (?, ?, ?, ?)",
                                      (mood, energy, note, _iso(self._now()))).lastrowid
            return dict(self._db.execute("SELECT * FROM checkins WHERE id = ?", (row_id,)).fetchone())

    def record_expression(self, expression, face_present=True):
        if not isinstance(face_present, bool):
            raise ValueError("Face presence must be true or false.")
        if expression is not None and (not isinstance(expression, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", expression)):
            raise ValueError("Expression must be a short lowercase label or null.")
        if not face_present:
            expression = None
        with self._lock, self._db:
            now = self._now()
            previous = self._last_observation
            continuous = previous is not None and 0 <= _seconds(previous["at"], now) <= MAX_OBSERVATION_GAP and now >= previous["at"]
            if continuous:
                self._db.execute("UPDATE observations SET ended_at = ? WHERE id = ?", (_iso(now), previous["id"]))
            same = continuous and expression == previous["expression"] and face_present == previous["face_present"]
            if same:
                row_id = previous["id"]
                self._db.execute("UPDATE observations SET samples = samples + 1 WHERE id = ?", (row_id,))
            else:
                row_id = self._db.execute(
                    "INSERT INTO observations (expression, face_present, started_at, ended_at) VALUES (?, ?, ?, ?)",
                    (expression, int(face_present), _iso(now), _iso(now))
                ).lastrowid
            self._last_observation = {"id": row_id, "at": now, "expression": expression, "face_present": face_present}
            return {"expression": expression, "face_present": face_present, "observed_at": _iso(now)}

    def _day_data(self, day, now, settings):
        name, start, end = self._bounds(day, now, settings)
        bounds = (start, end)
        sessions = []
        for row in self._db.execute("SELECT * FROM sessions ORDER BY started_at, id").fetchall():
            payload = self._session(row, now, bounds)
            if payload["day_seconds"] > 0 or start <= _dt(row["started_at"]) < end:
                sessions.append(payload)
        checkins = [dict(r) for r in self._db.execute(
            "SELECT * FROM checkins WHERE created_at >= ? AND created_at < ? ORDER BY created_at, id", (_iso(start), _iso(end))
        ).fetchall()]
        completed_tasks = self._db.execute(
            "SELECT COUNT(*) FROM task_completions WHERE undone_at IS NULL AND completed_at >= ? AND completed_at < ?",
            (_iso(start), _iso(end))
        ).fetchone()[0]
        included = [s for s in sessions if s["status"] != "cancelled"]
        stats = {
            "focus_seconds": round(sum(s["day_seconds"] for s in included if s["kind"] == "focus"), 3),
            "focus_sessions": sum(s["kind"] == "focus" and s["day_seconds"] > 0 and s["status"] in ("completed", "finished") for s in included),
            "completed_tasks": completed_tasks,
            "break_seconds": round(sum(s["day_seconds"] for s in included if s["kind"] == "break"), 3),
        }
        observed, present, away = 0.0, 0.0, 0.0
        expression_seconds = {}
        for row in self._db.execute(
            "SELECT * FROM observations WHERE started_at < ? AND ended_at >= ?", (_iso(end), _iso(start))
        ).fetchall():
            seconds = _seconds(max(start, _dt(row["started_at"])), min(end, _dt(row["ended_at"])))
            observed += seconds
            if row["face_present"]:
                present += seconds
                if row["expression"]:
                    expression_seconds[row["expression"]] = expression_seconds.get(row["expression"], 0) + seconds
            else:
                away += seconds
        available = _seconds(start, min(now, end))
        coverage = {
            "observed_seconds": round(observed, 3), "face_present_seconds": round(present, 3),
            "away_seconds": round(away, 3), "unobserved_seconds": round(max(0, available - observed), 3),
            "day_seconds": round(available, 3),
            "note": "Camera labels describe visible expressions. Mood comes from your check-ins; gaps are unobserved.",
        }
        expressions = [{"expression": label, "seconds": round(seconds, 3)}
                       for label, seconds in sorted(expression_seconds.items(), key=lambda pair: (-pair[1], pair[0])) if seconds > 0]
        return name, stats, checkins, sessions, expressions, coverage

    def state(self, day=None):
        with self._lock, self._db:
            now, settings = self._now(), self._settings()
            self._tick(now)
            name, stats, checkins, _, _, _ = self._day_data(day, now, settings)
            local = now.astimezone(ZoneInfo(settings["timezone"]))
            if name < local.date().isoformat() or (name == local.date().isoformat() and local.hour >= settings["report_hour"]):
                self._save_report(self._make_report(name, now, settings))
            report_ready = self._db.execute("SELECT 1 FROM reports WHERE day = ? AND timezone = ?", (name, settings["timezone"])).fetchone() is not None
            return {
                "date": name, "timezone": settings["timezone"],
                "tasks": [self._task(r) for r in self._db.execute("SELECT * FROM tasks ORDER BY completed, created_at, id").fetchall()],
                "session": self._session(self._db.execute("SELECT * FROM sessions WHERE status IN ('running', 'paused')").fetchone(), now),
                "checkins": checkins, "stats": stats, "settings": settings, "report_ready": report_ready,
            }

    def _make_report(self, day, now, settings):
        name, stats, checkins, sessions, expressions, coverage = self._day_data(day, now, settings)
        _, day_start, _ = self._bounds(name, now, settings)
        parts, insights = [], []
        if stats["focus_seconds"]:
            parts.append(f"You recorded {_duration(stats['focus_seconds'])} of focus timer time.")
        if stats["focus_sessions"]:
            count = stats["focus_sessions"]
            parts.append(f"You finished {count} focus {'session' if count == 1 else 'sessions'}.")
        if stats["completed_tasks"]:
            count = stats["completed_tasks"]
            parts.append(f"You completed {count} {'task' if count == 1 else 'tasks'}.")
        if stats["break_seconds"]:
            parts.append(f"Your recorded breaks added up to {_duration(stats['break_seconds'])}.")
        if checkins:
            last = checkins[-1]
            parts.append(f"Your latest check-in was {last['mood']}, with energy {last['energy']}/5.")
            if len(checkins) > 1 and checkins[0]["energy"] != last["energy"]:
                insights.append(f"Your reported energy changed from {checkins[0]['energy']}/5 to {last['energy']}/5 across {len(checkins)} check-ins.")
            if last["mood"] in ("low", "stressed") or last["energy"] <= 2:
                insights.append("Your latest check-in suggests making your next block shorter or taking a break.")
        else:
            insights.append("Add a mood check-in to give your reflection personal context.")
        if stats["focus_seconds"] >= settings["daily_goal_minutes"] * 60:
            insights.append(f"You reached your {settings['daily_goal_minutes']}-minute focus timer goal.")
        elif stats["focus_seconds"] == 0:
            insights.append("Choose one task and start a manageable focus block.")
        if stats["focus_sessions"] >= 2 and stats["break_seconds"] == 0:
            insights.append("Your timer log contains no breaks. Consider recording one between focus blocks.")
        if coverage["observed_seconds"] == 0:
            insights.append("No camera observation time was recorded. Your check-ins and timer records still stand on their own.")
        if not parts:
            parts.append("No focus timer time, completed tasks or mood check-ins were recorded for this day.")
        timeline = [{"type": "checkin", "id": c["id"], "at": c["created_at"],
                     "title": f"Feeling {c['mood']}", "detail": c["note"], "mood": c["mood"], "energy": c["energy"]}
                    for c in checkins]
        timeline.extend({"type": s["kind"], "id": s["id"],
                         "at": _iso(max(_dt(s["started_at"]), day_start)),
                         "original_started_at": s["started_at"],
                         "continued_from_previous_day": _dt(s["started_at"]) < day_start,
                         "title": s["task_title"] or ("Focus session" if s["kind"] == "focus" else "Break"),
                         "detail": s["status"], "seconds": s["day_seconds"], "status": s["status"]}
                        for s in sessions if s["status"] != "cancelled")
        timeline.sort(key=lambda entry: (entry["at"], entry["type"], entry["id"]))
        return {"date": name, "timezone": settings["timezone"], "stats": stats, "checkins": checkins,
                "sessions": sessions, "expressions": expressions, "summary": " ".join(parts),
                "insights": insights, "timeline": timeline, "coverage": coverage, "generated_at": _iso(now)}

    def _save_report(self, report):
        self._db.execute("INSERT OR REPLACE INTO reports (day, timezone, generated_at, payload) VALUES (?, ?, ?, ?)",
                         (report["date"], report["timezone"], report["generated_at"], json.dumps(report, ensure_ascii=False)))
        return report

    def report(self, day=None):
        with self._lock, self._db:
            now = self._now()
            self._tick(now)
            return self._save_report(self._make_report(day, now, self._settings()))

    def export_markdown(self, day=None):
        report = self.report(day)
        stats = report["stats"]
        lines = [f"# Purrpose daily reflection — {report['date']}", "", report["summary"], "",
                 f"Timezone: {report['timezone']}", "", "## Recorded activity", "",
                 f"- Focus timer: {_duration(stats['focus_seconds'])}",
                 f"- Finished focus sessions: {stats['focus_sessions']}",
                 f"- Completed tasks: {stats['completed_tasks']}",
                 f"- Break timer: {_duration(stats['break_seconds'])}", "", "## Mood check-ins", ""]
        tz = ZoneInfo(report["timezone"])
        for checkin in report["checkins"]:
            stamp = _dt(checkin["created_at"]).astimezone(tz).strftime("%H:%M")
            note = checkin["note"].replace("\n", " ")
            lines.append(f"- {stamp}: {checkin['mood']}; energy {checkin['energy']}/5" + (f" — {note}" if note else ""))
        if not report["checkins"]:
            lines.append("No self-reported mood check-ins.")
        lines += ["", "## Reflection", ""] + [f"- {item}" for item in report["insights"]]
        lines += ["", "## Camera observations", "", report["coverage"]["note"], "",
                  f"- Face visible: {_duration(report['coverage']['face_present_seconds'])}",
                  f"- Camera observed without a face: {_duration(report['coverage']['away_seconds'])}",
                  f"- Unobserved time in this day so far: {_duration(report['coverage']['unobserved_seconds'])}"]
        for expression in report["expressions"]:
            lines.append(f"- {expression['expression'].replace('_', ' ')}: {_duration(expression['seconds'])} observed")
        lines += ["", "Timer records describe recorded sessions, not proof of attention. Facial expressions are not mood measurements.", ""]
        return "\n".join(lines)

    def close(self):
        with self._lock:
            if self._closed:
                return
            with self._db:
                now = self._now()
                self._tick(now)
                active = self._db.execute("SELECT id FROM sessions WHERE status = 'running'").fetchone()
                if active:
                    self._db.execute("UPDATE session_segments SET ended_at = MAX(started_at, ?) WHERE session_id = ? AND ended_at IS NULL",
                                     (_iso(now), active["id"]))
                    self._db.execute("UPDATE sessions SET status = 'paused', last_checkpoint_at = ? WHERE id = ?", (_iso(now), active["id"]))
            self._db.close()
            self._closed = True
