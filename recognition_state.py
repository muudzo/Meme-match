"""Small dependency-free helpers shared by webcam consumers.

Geometry uses a common image-height unit so horizontal and vertical distances
mean the same thing on non-square camera frames. StableSignal combines a rolling
vote with minimum evidence duration; a single frame can never confirm a pose.
"""
from collections import Counter, deque
import math
import time
from types import SimpleNamespace


def metric_landmarks(landmarks, width, height):
    """Convert MediaPipe normalized coordinates to image-height units.

    Use the returned points for geometry, and the originals for drawing. The
    z-coordinate, like x, is expressed in image-width units by MediaPipe.
    """
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise ValueError("Frame dimensions must be positive finite numbers")
    scale = width / height
    return [SimpleNamespace(x=p.x * scale, y=p.y, z=getattr(p, "z", 0.0) * scale)
            for p in landmarks]


class StableSignal:
    """Confirm hashable labels only after repeated, time-spanning evidence.

    update(value, now=None) returns the currently confirmed value. None is a real
    sample (no recognized pose), so repeated None clears a prior pose. A sampling
    gap above stale_after clears old evidence before the next sample. Consumers
    should call reset() immediately when the camera stops or tracking is lost.
    Timestamps must be monotonic seconds. The clock is injectable through now.
    """
    def __init__(self, window_size=7, min_samples=3, confirmation_seconds=0.3,
                 ratio=0.6, stale_after=1.5):
        if not isinstance(window_size, int) or not isinstance(min_samples, int):
            raise ValueError("Sample limits must be integers")
        if not 1 <= min_samples <= window_size:
            raise ValueError("Require 1 <= min_samples <= window_size")
        if not 0.5 < ratio <= 1.0:
            raise ValueError("Vote ratio must be greater than one half and at most one")
        if not math.isfinite(confirmation_seconds) or confirmation_seconds < 0:
            raise ValueError("Confirmation duration must be finite and nonnegative")
        if not math.isfinite(stale_after) or stale_after <= confirmation_seconds:
            raise ValueError("Stale duration must exceed the confirmation duration")
        self.window_size = window_size
        self.min_samples = min_samples
        self.confirmation_seconds = confirmation_seconds
        self.ratio = ratio
        self.stale_after = stale_after
        self.history = deque(maxlen=window_size)
        self.value = None
        self._last_time = None
        self._candidate = None
        self._candidate_since = None

    def reset(self, value=None):
        """Discard all evidence, optionally assigning an explicit initial value."""
        self.history.clear()
        self.value = value
        self._last_time = None
        self._candidate = None
        self._candidate_since = None
        return self.value

    def update(self, value, now=None):
        now = time.monotonic() if now is None else now
        if not math.isfinite(now):
            raise ValueError("Sample time must be finite")
        if self._last_time is not None:
            if now < self._last_time:
                raise ValueError("Sample times must be monotonic")
            if now - self._last_time > self.stale_after:
                self.reset()
        self._last_time = now
        self.history.append((now, value))
        winner, count = Counter(v for _, v in self.history).most_common(1)[0]
        if count / len(self.history) < self.ratio:
            self._candidate_since = None
            return self.value
        if self._candidate_since is None or winner != self._candidate:
            self._candidate = winner
            # Credit matching samples already in the rolling window. Otherwise
            # transitions pay the confirmation delay twice: first waiting to
            # win the vote, then restarting the duration gate from that point.
            self._candidate_since = next(t for t, v in self.history if v == winner)
        if count >= self.min_samples and now - self._candidate_since >= self.confirmation_seconds:
            self.value = winner
        return self.value
