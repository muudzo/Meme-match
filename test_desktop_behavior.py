import unittest

from desktop_behavior import CatBehavior


def frame(at, expression="neutral", *, present=True, status="running"):
    return {"status": status, "expression": expression,
            "face_present": present, "sampled_at": at}


class CatBehaviorTests(unittest.TestCase):
    def behavior(self, **kwargs):
        cat = CatBehavior(**kwargs)
        cat.set_active(True, now=0)
        return cat

    def feed(self, cat, start, end, expression="neutral"):
        state = None
        for stamp in range(start, end + 1):
            state = cat.update(frame(stamp, expression), now=stamp)
        return state

    def test_fresh_expressions_drive_only_visible_reactions(self):
        cat = self.behavior()
        expected = {"smile": "happy", "grin": "happy", "eyebrows_raised": "curious",
                    "frown": "concerned", "mouth_open": "surprised", "kiss": "happy",
                    "wink": "wink", "eyes_closed": "sleeping", "neutral": "idle"}
        for stamp, (expression, pose) in enumerate(expected.items()):
            result = cat.update(frame(stamp, expression), now=stamp)
            self.assertEqual(result["pose"], pose)
            self.assertFalse(result["nudge"])

    def test_paused_cat_does_not_mirror_or_prompt(self):
        cat = CatBehavior(checkin_minutes=1)
        result = self.feed(cat, 0, 200, "eyes_closed")
        self.assertEqual(result["pose"], "idle")
        self.assertFalse(result["active"])
        self.assertFalse(result["observed"])
        self.assertIsNone(result["message"])

    def test_closed_eyes_need_three_seconds_then_emit_one_event(self):
        cat = self.behavior()
        self.assertFalse(self.feed(cat, 0, 2, "eyes_closed")["nudge"])
        result = cat.update(frame(3, "eyes_closed"), now=3)
        self.assertTrue(result["nudge"])
        self.assertEqual(result["reason"], "eyes_rest")
        self.assertEqual(result["pose"], "stretch")
        self.assertFalse(cat.update(frame(4, "eyes_closed"), now=4)["nudge"])
        self.assertTrue(cat.update(frame(5, "eyes_closed"), now=5)["prompt_visible"])

    def test_brief_blinks_do_not_prompt(self):
        cat = self.behavior()
        self.feed(cat, 0, 2, "eyes_closed")
        result = cat.update(frame(3, "neutral"), now=3)
        self.assertFalse(result["nudge"])
        self.assertIsNone(result["message"])

    def test_frown_needs_eight_seconds(self):
        cat = self.behavior()
        self.assertFalse(self.feed(cat, 0, 7, "frown")["nudge"])
        result = cat.update(frame(8, "frown"), now=8)
        self.assertTrue(result["nudge"])
        self.assertEqual(result["reason"], "sustained_frown")

    def test_periodic_prompt_requires_continuous_observed_presence(self):
        cat = self.behavior(checkin_minutes=1)
        self.assertFalse(self.feed(cat, 0, 59)["nudge"])
        result = cat.update(frame(60), now=60)
        self.assertTrue(result["nudge"])
        self.assertEqual(result["reason"], "gentle_checkin")
        self.assertIn("what are you working on", result["message"])

    def test_away_time_restarts_periodic_evidence_and_clears_prompts(self):
        cat = self.behavior(checkin_minutes=1)
        self.feed(cat, 0, 59)
        result = cat.update(frame(60, present=False), now=60)
        self.assertFalse(result["observed"])
        self.assertFalse(result["nudge"])
        self.assertIsNone(result["message"])
        self.assertFalse(self.feed(cat, 61, 120)["nudge"])
        self.assertTrue(cat.update(frame(121), now=121)["nudge"])

    def test_missing_stale_future_and_nonfinite_timestamps_are_unobserved(self):
        for sample in (None, -4, 1, float("nan"), float("inf"), True):
            with self.subTest(sample=sample):
                cat = self.behavior()
                snapshot = frame(0, "eyes_closed")
                snapshot["sampled_at"] = sample
                result = cat.update(snapshot, now=0)
                self.assertFalse(result["observed"])
                self.assertFalse(result["nudge"])

    def test_repeated_snapshot_does_not_accumulate_duration(self):
        cat = self.behavior()
        snapshot = frame(0, "eyes_closed")
        for stamp in (0, 1, 2, 3):
            self.assertFalse(cat.update(snapshot, now=stamp)["nudge"])
        result = cat.update(snapshot, now=4)
        self.assertFalse(result["observed"])
        self.assertIsNone(result["message"])

    def test_long_sampling_gap_does_not_count_as_sustained_expression(self):
        cat = self.behavior()
        self.feed(cat, 0, 2, "eyes_closed")
        result = cat.update(frame(30, "eyes_closed"), now=30)
        self.assertFalse(result["nudge"])
        self.assertTrue(cat.update(frame(33, "eyes_closed"), now=33)["nudge"])

    def test_same_held_cue_does_not_prompt_again_after_cooldown(self):
        cat = self.behavior()
        self.feed(cat, 0, 3, "eyes_closed")
        events = []
        for stamp in range(4, 200):
            if cat.update(frame(stamp, "eyes_closed"), now=stamp)["nudge"]:
                events.append(stamp)
        self.assertEqual(events, [])

    def test_changed_cue_respects_cooldown_then_can_prompt_again(self):
        cat = self.behavior()
        self.feed(cat, 0, 3, "eyes_closed")
        self.feed(cat, 4, 20)
        self.assertFalse(self.feed(cat, 21, 122, "frown")["nudge"])
        self.assertTrue(cat.update(frame(123, "frown"), now=123)["nudge"])

    def test_prompt_expires_after_fifteen_seconds(self):
        cat = self.behavior()
        self.feed(cat, 0, 3, "eyes_closed")
        result = self.feed(cat, 4, 18, "eyes_closed")
        self.assertFalse(result["prompt_visible"])
        self.assertIsNone(result["message"])
        self.assertIsNone(result["reason"])

    def test_acknowledgement_dismisses_and_restarts_reminder(self):
        cat = self.behavior(checkin_minutes=1)
        self.feed(cat, 0, 60)
        acknowledged = cat.acknowledge(now=61)
        self.assertFalse(acknowledged["prompt_visible"])
        self.assertFalse(self.feed(cat, 61, 180)["nudge"])
        self.assertTrue(cat.update(frame(181), now=181)["nudge"])

    def test_pause_and_reactivation_discard_old_evidence(self):
        cat = self.behavior()
        self.feed(cat, 0, 3, "eyes_closed")
        result = cat.set_active(False, now=4)
        self.assertIsNone(result["message"])
        self.assertFalse(result["observed"])
        cat.set_active(True, now=5)
        self.assertFalse(self.feed(cat, 5, 7, "eyes_closed")["nudge"])
        self.assertTrue(cat.update(frame(8, "eyes_closed"), now=8)["nudge"])

    def test_camera_stop_clears_reaction_immediately(self):
        cat = self.behavior()
        self.feed(cat, 0, 3, "eyes_closed")
        result = cat.update(frame(4, status="off"), now=4)
        self.assertEqual(result["pose"], "idle")
        self.assertFalse(result["prompt_visible"])

    def test_hand_gesture_reacts_even_when_face_is_out_of_view(self):
        cat = self.behavior()
        snapshot = {**frame(1, present=False), "gesture": "open_palm", "hands_present": True}
        result = cat.update(snapshot, now=1)
        self.assertEqual(result["pose"], "wave")
        self.assertEqual(result["gesture"], "open_palm")
        self.assertFalse(result["observed"])
        self.assertFalse(result["nudge"])

    def test_hand_body_reaction_keeps_the_facial_expression(self):
        cat = self.behavior()
        snapshot = {**frame(1, "smile"), "gesture": "open_palm", "hands_present": True}
        result = cat.update(snapshot, now=1)
        self.assertEqual(result["pose"], "wave")
        self.assertEqual(result["face_pose"], "happy")

    def test_hand_leaving_view_clears_its_pose(self):
        cat = self.behavior()
        cat.update({**frame(1), "gesture": "thumbs_up", "hands_present": True}, now=1)
        result = cat.update(frame(2), now=2)
        self.assertEqual(result["pose"], "idle")
        self.assertIsNone(result["gesture"])

    def test_stale_hand_frame_cannot_keep_waving(self):
        cat = self.behavior()
        snapshot = {**frame(1), "gesture": "open_palm", "hands_present": True}
        self.assertEqual(cat.update(snapshot, now=1)["pose"], "wave")
        self.assertEqual(cat.update(snapshot, now=5)["pose"], "idle")

    def test_out_of_order_frame_is_discarded(self):
        cat = self.behavior()
        cat.update(frame(2, "eyes_closed"), now=2)
        result = cat.update(frame(1, "eyes_closed"), now=3)
        self.assertFalse(result["observed"])
        self.assertFalse(result["nudge"])

    def test_configuration_and_monotonicity_validation(self):
        for value in (0, 61, True, float("inf")):
            with self.subTest(interval=value), self.assertRaises(ValueError):
                CatBehavior(checkin_minutes=value)
        with self.assertRaises(ValueError):
            CatBehavior(cooldown_seconds=119)
        cat = self.behavior()
        cat.update(frame(2), now=2)
        with self.assertRaises(ValueError):
            cat.update(frame(1), now=1)
        with self.assertRaises(ValueError):
            cat.set_active(1, now=3)


if __name__ == "__main__":
    unittest.main()
