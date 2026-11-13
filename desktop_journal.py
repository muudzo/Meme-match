"""Small local log of widget interactions; it never labels a user's thoughts."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


class DesktopJournal:
    def __init__(self, path):
        self._db = sqlite3.connect(str(Path(path)))
        self._db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, at TEXT NOT NULL)")

    def record(self, kind):
        if kind not in {"activated", "paused", "prompt", "acknowledged", "self_reported_reset",
                        "break_reminder", "daily_reminder", "break_started"}:
            raise ValueError("Unknown desktop event")
        with self._db:
            self._db.execute("INSERT INTO events(kind, at) VALUES (?, ?)", (kind, datetime.now(timezone.utc).isoformat()))

    def today(self, timezone_name):
        zone = ZoneInfo(timezone_name)
        today = datetime.now(zone).date()
        counts = {}
        for kind, at in self._db.execute("SELECT kind, at FROM events"):
            if datetime.fromisoformat(at).astimezone(zone).date() == today:
                counts[kind] = counts.get(kind, 0) + 1
        return counts

    def close(self):
        self._db.close()
