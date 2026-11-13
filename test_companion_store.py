import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from companion_store import CompanionStore


class Clock:
    def __init__(self, value="2026-11-13T09:00:00+00:00"):
        self.value = datetime.fromisoformat(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class CompanionStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "diary.sqlite3"
        self.clock = Clock()
        self.store = CompanionStore(self.path, clock=self.clock)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_pause_resume_excludes_paused_time_and_finish_counts_actual_time(self):
        task = self.store.add_task("Ship the prototype")
        self.store.start_session(task["id"], 25)
        self.clock.advance(120)
        paused = self.store.session_action("pause")
        self.assertEqual(paused["elapsed_seconds"], 120)
        self.clock.advance(600)
        self.assertEqual(self.store.state()["session"]["elapsed_seconds"], 120)
        self.store.session_action("resume")
        self.clock.advance(60)
        finished = self.store.session_action("finish")
        self.assertEqual(finished["elapsed_seconds"], 180)
        self.assertEqual(self.store.state()["stats"]["focus_seconds"], 180)
        self.assertEqual(self.store.state()["stats"]["focus_sessions"], 1)

    def test_overlapping_sessions_rejected_and_elapsed_capped(self):
        self.store.start_session(duration_minutes=1)
        with self.assertRaisesRegex(ValueError, "current session"):
            self.store.start_session(kind="break", duration_minutes=5)
        self.clock.advance(500)
        state = self.store.state()
        self.assertIsNone(state["session"])
        self.assertEqual(state["stats"]["focus_seconds"], 60)
        self.assertEqual(state["stats"]["focus_sessions"], 1)
        session = self.store.report()["sessions"][0]
        self.assertEqual(session["ended_at"], "2026-11-13T09:01:00.000000+00:00")

    def test_cancelled_timer_does_not_count_toward_focus(self):
        self.store.start_session()
        self.clock.advance(50)
        self.store.session_action("cancel")
        self.assertEqual(self.store.state()["stats"]["focus_seconds"], 0)

    def test_stale_finish_after_natural_completion_is_idempotent(self):
        started = self.store.start_session(duration_minutes=1)
        self.clock.advance(60)
        finished = self.store.session_action("finish", expected_session_id=started["id"])
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["elapsed_seconds"], 60)
        self.clock.advance(20)
        repeated = self.store.session_action("finish", expected_session_id=started["id"])
        self.assertEqual(repeated, finished)
        self.assertIsNone(self.store.state()["session"])
        self.assertEqual(self.store.state()["stats"]["focus_sessions"], 1)
        for action in ("pause", "resume", "cancel"):
            with self.assertRaisesRegex(ValueError, "no active session"):
                self.store.session_action(action)

    def test_stale_session_id_cannot_finish_a_new_session(self):
        first = self.store.start_session(duration_minutes=1)
        self.clock.advance(5)
        self.store.session_action("finish", expected_session_id=first["id"])
        second = self.store.start_session(duration_minutes=1)
        with self.assertRaisesRegex(ValueError, "session has changed"):
            self.store.session_action("finish", expected_session_id=first["id"])
        active = self.store.state()["session"]
        self.assertEqual(active["id"], second["id"])
        self.assertEqual(active["status"], "running")
        self.store.session_action("finish", expected_session_id=second["id"])

    def test_finish_without_session_history_still_rejects(self):
        with self.assertRaisesRegex(ValueError, "no active session"):
            self.store.session_action("finish")

    def test_restart_recovers_only_last_checkpoint_and_pauses(self):
        self.store.start_session()
        self.clock.advance(120)
        self.store.heartbeat()
        # Simulate a crash: close SQLite without the graceful close method.
        self.store._db.close()
        self.store._closed = True
        self.clock.advance(3600)
        self.store = CompanionStore(self.path, clock=self.clock)
        session = self.store.state()["session"]
        self.assertEqual(session["status"], "paused")
        self.assertEqual(session["elapsed_seconds"], 120)

    def test_midnight_clips_timer_into_local_dates(self):
        self.clock.value = datetime.fromisoformat("2026-11-13T22:59:30+00:00")
        self.store.start_session(duration_minutes=2)
        self.clock.advance(90)
        self.store.session_action("finish")
        self.assertEqual(self.store.report("2026-11-13")["stats"]["focus_seconds"], 30)
        second_day = self.store.report("2026-11-14")
        self.assertEqual(second_day["stats"]["focus_seconds"], 60)
        entry = second_day["timeline"][0]
        self.assertEqual(entry["at"], "2026-11-13T23:00:00.000000+00:00")
        self.assertEqual(entry["original_started_at"], "2026-11-13T22:59:30.000000+00:00")
        self.assertTrue(entry["continued_from_previous_day"])
        self.assertEqual(second_day["sessions"][0]["started_at"], entry["original_started_at"])

    def test_dst_day_uses_actual_local_day_length(self):
        self.clock.value = datetime.fromisoformat("2026-03-30T12:00:00+00:00")
        self.assertEqual(self.store.report("2026-03-29")["coverage"]["day_seconds"], 23 * 3600)
        self.assertEqual(self.store.report("2026-10-25")["coverage"]["day_seconds"], 0)
        self.clock.value = datetime.fromisoformat("2026-10-26T12:00:00+00:00")
        self.assertEqual(self.store.report("2026-10-25")["coverage"]["day_seconds"], 25 * 3600)

    def test_expressions_do_not_manufacture_mood_or_cover_gaps(self):
        self.store.record_expression("smile")
        self.clock.advance(2)
        self.store.record_expression("smile")
        self.clock.advance(60)
        self.store.record_expression("sad")
        self.clock.advance(2)
        self.store.record_expression("smile", face_present=False)
        self.clock.advance(2)
        self.store.record_expression(None, face_present=False)
        report = self.store.report()
        self.assertEqual(report["checkins"], [])
        self.assertEqual(report["coverage"]["observed_seconds"], 6)
        self.assertEqual(report["coverage"]["face_present_seconds"], 4)
        self.assertEqual(report["coverage"]["away_seconds"], 2)
        self.assertEqual({r["expression"]: r["seconds"] for r in report["expressions"]}, {"smile": 2, "sad": 2})
        self.assertNotIn("happy", report["summary"])

    def test_mood_and_energy_are_self_reported_and_persist(self):
        self.store.add_checkin("low", 2, "After a long meeting")
        self.clock.advance(600)
        self.store.add_checkin("good", 4, "After a walk")
        self.store.close()
        self.store = CompanionStore(self.path, clock=self.clock)
        report = self.store.report()
        self.assertEqual(len(report["checkins"]), 2)
        self.assertIn("good", report["summary"])
        self.assertTrue(any("2/5 to 4/5" in item for item in report["insights"]))
        self.assertEqual(report["expressions"], [])

    def test_task_completion_is_idempotent_and_preserves_session_title(self):
        task = self.store.add_task("Finish the day")
        self.store.start_session(task["id"])
        first = self.store.update_task(task["id"], True)
        self.clock.advance(10)
        again = self.store.update_task(task["id"], True)
        self.assertEqual(first["completed_at"], again["completed_at"])
        self.store.delete_task(task["id"])
        self.assertEqual(self.store.state()["session"]["task_title"], "Finish the day")
        self.assertEqual(self.store.report()["stats"]["completed_tasks"], 1)

    def test_undoing_completion_does_not_count_as_finished_task(self):
        task = self.store.add_task("A draft to revisit")
        self.store.update_task(task["id"], True)
        self.store.update_task(task["id"], False)
        self.assertEqual(self.store.state()["stats"]["completed_tasks"], 0)
        self.store.update_task(task["id"], True)
        self.assertEqual(self.store.state()["stats"]["completed_tasks"], 1)

    def test_report_is_empty_honestly_and_auto_saves_after_report_hour(self):
        report = self.store.report()
        self.assertEqual(report["stats"], {"focus_seconds": 0, "focus_sessions": 0, "completed_tasks": 0, "break_seconds": 0})
        self.assertEqual(report["timeline"], [])
        self.assertIn("No focus timer", report["summary"])
        self.store._db.execute("DELETE FROM reports")
        self.store._db.commit()
        self.assertFalse(self.store.state()["report_ready"])
        self.clock.value = datetime.fromisoformat("2026-11-13T17:00:00+00:00")
        self.assertTrue(self.store.state()["report_ready"])
        self.assertIsNotNone(self.store._db.execute("SELECT payload FROM reports").fetchone())

    def test_validation_rejects_invalid_shapes_without_partial_writes(self):
        for mood, energy in (("excited", 3), ("good", True), ("okay", 6)):
            with self.assertRaises(ValueError):
                self.store.add_checkin(mood, energy)
        for duration in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                self.store.start_session(duration_minutes=duration)
        with self.assertRaises(ValueError):
            self.store.update_settings({"timezone": "not/a/timezone"})
        with self.assertRaises(ValueError):
            self.store.report("20261113")
        self.assertEqual(self.store.state()["checkins"], [])

    def test_markdown_export_contains_sources_and_real_records(self):
        self.store.add_checkin("okay", 3, "A steady morning")
        output = self.store.export_markdown()
        self.assertIn("A steady morning", output)
        self.assertIn("Facial expressions are not mood measurements", output)
        self.assertIn("Europe/Amsterdam", output)


if __name__ == "__main__":
    unittest.main()
