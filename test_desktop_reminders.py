from datetime import datetime, timedelta, timezone
import unittest

from desktop_reminders import DesktopReminders


NOON = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


class ReminderTests(unittest.TestCase):
    def scheduler(self, **values):
        reminder = DesktopReminders(**values)
        reminder.set_working(True, now=0)
        return reminder

    def advance(self, reminder, start, end):
        result = None
        for now in range(start, end + 1):
            result = reminder.update(now, NOON)
        return result

    def test_break_due_after_work_time_without_any_camera_evidence(self):
        reminder = self.scheduler(break_minutes=5)
        self.assertFalse(self.advance(reminder, 0, 299)["events"])
        result = reminder.update(300, NOON)
        self.assertEqual(result["events"][0]["kind"], "break")
        self.assertTrue(result["break_due"])
        self.assertFalse(reminder.update(301, NOON)["events"])

    def test_paused_time_is_not_work(self):
        reminder = self.scheduler(break_minutes=5)
        self.advance(reminder, 0, 150)
        reminder.set_working(False, 150)
        self.advance(reminder, 151, 500)
        reminder.set_working(True, 500)
        self.assertFalse(self.advance(reminder, 501, 649)["events"])
        self.assertEqual(reminder.update(650, NOON)["events"][0]["kind"], "break")

    def test_computer_sleep_does_not_count_as_work(self):
        reminder = self.scheduler(break_minutes=5)
        self.assertFalse(reminder.update(3600, NOON)["events"])
        self.assertEqual(reminder.update(3601, NOON)["working_seconds"], 1)

    def test_break_countdown_finishes_without_restarting_camera_or_work(self):
        reminder = self.scheduler(rest_minutes=1)
        reminder.start_break(0)
        self.assertEqual(reminder.update(30, NOON)["rest_remaining"], 30)
        result = reminder.update(60, NOON)
        self.assertEqual(result["events"][0]["kind"], "rest_finished")
        self.assertEqual(result["working_seconds"], 0)
        self.assertFalse(reminder.update(61, NOON)["events"])

    def test_snoozing_defers_the_next_break_by_five_work_minutes(self):
        reminder = self.scheduler(break_minutes=25)
        self.advance(reminder, 0, 1500)
        reminder.snooze(1500)
        self.assertFalse(self.advance(reminder, 1501, 1799)["events"])
        self.assertEqual(reminder.update(1800, NOON)["events"][0]["kind"], "break")

    def test_1620_uses_amsterdam_local_time_even_with_camera_paused(self):
        reminder = DesktopReminders()
        before = datetime(2026, 11, 13, 15, 19, tzinfo=timezone.utc)
        self.assertFalse(reminder.update(0, before)["events"])
        result = reminder.update(60, before + timedelta(minutes=1))
        self.assertEqual(result["events"][0]["kind"], "daily")
        self.assertIn("roll a joint", result["events"][0]["message"])
        self.assertFalse(reminder.update(61, before + timedelta(minutes=1))["events"])

    def test_daily_reminder_is_not_duplicated_after_restart(self):
        wall = datetime(2026, 11, 13, 15, 20, tzinfo=timezone.utc)
        first = DesktopReminders()
        key = first.update(0, wall)["last_daily_key"]
        restarted = DesktopReminders(last_daily_key=key)
        self.assertFalse(restarted.update(0, wall)["events"])

    def test_daily_reminder_repeats_next_day_and_respects_dst(self):
        reminder = DesktopReminders()
        winter = datetime(2026, 11, 13, 15, 20, tzinfo=timezone.utc)
        self.assertTrue(reminder.update(0, winter)["events"])
        self.assertTrue(reminder.update(1, winter + timedelta(days=1))["events"])
        summer = DesktopReminders()
        self.assertTrue(summer.update(0, datetime(2026, 7, 13, 14, 20, tzinfo=timezone.utc))["events"])

    def test_disabled_or_late_daily_reminder_stays_quiet(self):
        wall = datetime(2026, 11, 13, 15, 20, tzinfo=timezone.utc)
        self.assertFalse(DesktopReminders(daily_enabled=False).update(0, wall)["events"])
        self.assertFalse(DesktopReminders().update(0, wall + timedelta(hours=3))["events"])

    def test_configurable_time_and_message(self):
        reminder = DesktopReminders(daily_time="09:30", daily_text="Tea time")
        result = reminder.update(0, datetime(2026, 11, 13, 8, 30, tzinfo=timezone.utc))
        self.assertEqual(result["events"][0]["message"], "Tea time")

    def test_invalid_values_are_rejected(self):
        for values in ({"break_minutes": 0}, {"rest_minutes": 0}, {"daily_time": "25:20"}, {"daily_text": ""}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                DesktopReminders(**values)
