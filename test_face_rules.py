import math
from types import SimpleNamespace
import unittest

from face_rules import classify_expression


def face():
    lm = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(468)]
    values = {10:(.5,.15),152:(.5,.85),234:(.25,.5),454:(.75,.5),
              61:(.4,.65),291:(.6,.65),13:(.5,.6475),14:(.5,.6525),
              33:(.33,.4),133:(.43,.4),159:(.38,.385),145:(.38,.415),
              263:(.67,.4),362:(.57,.4),386:(.62,.385),374:(.62,.415),
              105:(.38,.35),334:(.62,.35),168:(.5,.4)}
    for i,(x,y) in values.items():
        lm[i].x,lm[i].y=x,y
    return lm


class FaceRulesTests(unittest.TestCase):
    def test_neutral_geometry_is_unclassified(self):
        self.assertIsNone(classify_expression(face()))

    def test_wink_is_not_hidden_by_grinning(self):
        lm=face()
        lm[61].x,lm[291].x=.35,.65
        lm[13].y,lm[14].y=.63,.67
        lm[159].y=lm[145].y=.4
        self.assertEqual(classify_expression(lm),'wink')

    def test_eye_closure_is_not_hidden_by_open_mouth(self):
        lm=face()
        lm[61].x,lm[291].x=.45,.55
        lm[13].y,lm[14].y=.6,.7
        lm[159].y=lm[145].y=.4
        lm[386].y=lm[374].y=.4
        self.assertEqual(classify_expression(lm),'eyes_closed')

    def test_frown_is_stable_under_head_roll(self):
        lm=face()
        lm[61].y=lm[291].y=.67
        self.assertEqual(classify_expression(lm),'sad')
        a=math.radians(80)
        for point in lm:
            x,y=point.x-.5,point.y-.5
            point.x=.5+x*math.cos(a)-y*math.sin(a)
            point.y=.5+x*math.sin(a)+y*math.cos(a)
        self.assertEqual(classify_expression(lm),'sad')

    def test_invalid_faces_are_not_closed_eyes(self):
        collapsed=[SimpleNamespace(x=0,y=0,z=0) for _ in range(468)]
        for lm in (None,[],collapsed):
            with self.subTest(lm=type(lm).__name__):
                self.assertIsNone(classify_expression(lm))
        lm=face()
        lm[13].x=float('nan')
        self.assertIsNone(classify_expression(lm))
