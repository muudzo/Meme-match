from types import SimpleNamespace
import unittest

from recognition_state import StableSignal, metric_landmarks


class StableSignalTests(unittest.TestCase):
    def test_one_frame_cannot_confirm(self):
        signal=StableSignal()
        self.assertIsNone(signal.update('smile',now=0))
        self.assertIsNone(signal.update('smile',now=.1))
        self.assertEqual(signal.update('smile',now=.31),'smile')

    def test_confirmation_is_not_blocked_by_high_frame_rate(self):
        signal=StableSignal()
        for frame in range(31):
            value=signal.update('smile',now=frame/60)
        self.assertEqual(value,'smile')

    def test_short_blink_does_not_replace_confirmed_expression(self):
        signal=StableSignal()
        for t in (0,.15,.31):
            signal.update('smile',now=t)
        self.assertEqual(signal.update('eyes_closed',now=.4),'smile')
        self.assertEqual(signal.update('smile',now=.5),'smile')

    def test_repeated_no_match_clears_prior_pose(self):
        signal=StableSignal()
        for t in (0,.15,.31):
            signal.update('smile',now=t)
        for t in (.5,.7,.9,1.1,1.3,1.5):
            value=signal.update(None,now=t)
        self.assertIsNone(value)

    def test_lost_sampling_clears_stale_evidence(self):
        signal=StableSignal()
        for t in (0,.15,.31):
            signal.update('smile',now=t)
        self.assertIsNone(signal.update('smile',now=3))

    def test_clock_must_be_monotonic(self):
        signal=StableSignal()
        signal.update('smile',now=5)
        with self.assertRaises(ValueError):
            signal.update('smile',now=4)

    def test_immediate_reset_clears_pose_and_evidence(self):
        signal=StableSignal()
        for t in (0,.15,.31):
            signal.update('smile',now=t)
        signal.reset()
        self.assertIsNone(signal.value)
        self.assertIsNone(signal.update('smile',now=1))


class MetricLandmarksTests(unittest.TestCase):
    def test_horizontal_and_vertical_distances_have_common_units(self):
        points=[SimpleNamespace(x=.25,y=.5,z=.1),SimpleNamespace(x=.5,y=.5,z=0)]
        corrected=metric_landmarks(points,1920,1080)
        self.assertAlmostEqual(corrected[1].x-corrected[0].x,480/1080)
        self.assertAlmostEqual(corrected[0].z,192/1080)
        self.assertEqual(points[0].x,.25)

    def test_invalid_frame_dimensions_are_rejected(self):
        for width,height in ((0,480),(640,0),(-1,2),(float('nan'),1)):
            with self.subTest(dimensions=(width,height)):
                with self.assertRaises(ValueError):
                    metric_landmarks([],width,height)
