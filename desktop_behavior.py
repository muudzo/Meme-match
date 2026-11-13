"""Deterministic reactions and gentle check-ins for the desktop cat.

Camera expressions are visible movements, not evidence of a person's thoughts
or emotions. This module turns recent observations into animation cues and
optional, tentative prompts. It neither diagnoses distraction nor opens a camera.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
import time


EXPRESSION_POSES = {
    "neutral": "idle",
    "smile": "happy",
    "grin": "happy",
    "eyebrows_raised": "curious",
    "frown": "concerned",
    "mouth_open": "surprised",
    "kiss": "happy",
    "wink": "wink",
    "eyes_closed": "sleeping",
}

MESSAGES = {
    "gentle_checkin": "A little check-in: what are you working on?",
    "eyes_rest": "Take a breath. Want a moment to reset?",
    "sustained_frown": "A little check-in: how are you feeling right now?",
}


class CatBehavior:
    """Map fresh camera snapshots to a cat pose and occasional gentle prompts.

    ``sampled_at`` is the monotonic time at which the camera processed a frame.
    It is required: missing, future, or more-than-three-second-old observations
    cannot establish presence or prompt evidence. Re-reading one snapshot does
    not extend its evidence. ``nudge`` is a one-update event; ``message`` and
    ``reason`` remain available for at most 15 seconds or until acknowledged.

    Check-ins require a continuous stretch of observed presence. Leaving view,
    a camera stop, stale evidence, or a sampling gap resets that stretch. A
    sustained expression prompts once per episode, so holding the same face
    does not produce a repeating alarm.
    """

    stale_seconds = 3.0
    prompt_seconds = 15.0
    reaction_seconds = 2.0

    def __init__(self, checkin_minutes=10, cooldown_seconds=120):
        self.checkin_minutes = self._minutes(checkin_minutes)
        self.cooldown_seconds = self._number(cooldown_seconds, "Cooldown")
        if self.cooldown_seconds < 120:
            raise ValueError("Cooldown must be at least 120 seconds.")
        self.active = False
        self._clock_at = None
        self._evidence_floor = None
        self._last_sample_at = None
        self._present_since = None
        self._expression = None
        self._expression_since = None
        self._latched_cue = None
        self._last_prompt_at = None
        self._message = None
        self._reason = None
        self._prompt_until = None
        self._reaction_until = None
        self._pose = "idle"
        self._observed = False

    @staticmethod
    def _number(value, label):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{label} must be a finite number.")
        return float(value)

    @classmethod
    def _minutes(cls, value):
        value = cls._number(value, "Check-in interval")
        if not 1 <= value <= 60:
            raise ValueError("Check-in interval must be between 1 and 60 minutes.")
        return value

    def _now(self, now):
        now = self._number(time.monotonic() if now is None else now, "Time")
        if self._clock_at is not None and now < self._clock_at:
            raise ValueError("Times must be monotonic.")
        self._clock_at = now
        return now

    def _clear_prompt(self):
        self._message = None
        self._reason = None
        self._prompt_until = None
        self._reaction_until = None

    def _clear_evidence(self):
        self._last_sample_at = None
        self._present_since = None
        self._expression = None
        self._expression_since = None
        self._latched_cue = None
        self._observed = False
        self._pose = "idle"

    def _result(self, now, *, nudge=False):
        stretching = (self._observed and self._reaction_until is not None
                      and now < self._reaction_until)
        return {
            "pose": "stretch" if stretching else self._pose,
            "message": self._message,
            "reason": self._reason,
            "nudge": nudge,
            "active": self.active,
            "observed": self._observed,
            "prompt_visible": self._message is not None,
            "expression": self._expression,
        }

    def set_active(self, active, now=None):
        """Explicit activation or pause starts a fresh observation episode."""
        if not isinstance(active, bool):
            raise ValueError("Active must be true or false.")
        now = self._now(now)
        self.active = active
        self._clear_evidence()
        self._clear_prompt()
        self._last_prompt_at = None
        self._evidence_floor = now
        return self._result(now)

    def configure(self, checkin_minutes=None, *, now=None):
        """Change the interval and restart the periodic reminder clock."""
        minutes = self.checkin_minutes if checkin_minutes is None else self._minutes(checkin_minutes)
        now = self._now(now)
        self.checkin_minutes = minutes
        self._present_since = None
        self._evidence_floor = now
        self._clear_prompt()
        return self._result(now)

    def acknowledge(self, now=None):
        """A click dismisses the prompt and gives the person a quiet interval."""
        now = self._now(now)
        self._clear_prompt()
        self._last_prompt_at = now
        self._present_since = None
        self._evidence_floor = now
        self._expression_since = None
        if self._expression in {"eyes_closed", "frown"}:
            self._latched_cue = self._expression
        return self._result(now)

    def update(self, snapshot, now=None):
        now = self._now(now)
        if self._prompt_until is not None and now >= self._prompt_until:
            self._clear_prompt()
        snapshot = snapshot if isinstance(snapshot, Mapping) else {}
        sample = snapshot.get("sampled_at")
        fresh = (not isinstance(sample, bool) and isinstance(sample, (int, float))
                 and math.isfinite(sample) and 0 <= now - sample <= self.stale_seconds)
        if (not self.active or snapshot.get("status") != "running"
                or snapshot.get("face_present") is not True or not fresh):
            self._clear_evidence()
            self._clear_prompt()
            self._evidence_floor = now
            return self._result(now)

        # Ignore frames arriving out of order. Repeated reads are safe, but a
        # timestamp cannot move backwards and still extend the current episode.
        if self._last_sample_at is not None and sample < self._last_sample_at:
            self._clear_evidence()
            self._clear_prompt()
            self._evidence_floor = now
            return self._result(now)
        if self._last_sample_at is not None and sample - self._last_sample_at > self.stale_seconds:
            self._clear_evidence()
            self._clear_prompt()
            self._evidence_floor = sample

        self._last_sample_at = float(sample)
        self._observed = True
        expression = snapshot.get("expression")
        expression = expression if isinstance(expression, str) and expression in EXPRESSION_POSES else None
        self._pose = EXPRESSION_POSES.get(expression, "idle")
        baseline = max(float(sample), self._evidence_floor if self._evidence_floor is not None else float(sample))
        if self._present_since is None:
            self._present_since = baseline
        if expression != self._expression or self._expression_since is None:
            if expression != self._expression:
                self._latched_cue = None
            self._expression_since = baseline
        self._expression = expression

        cooling_down = (self._last_prompt_at is not None
                        and now - self._last_prompt_at < self.cooldown_seconds)
        if self._message is not None or cooling_down:
            return self._result(now)

        held = max(0, sample - self._expression_since)
        reason = None
        if expression == "eyes_closed" and self._latched_cue != expression and held >= 3:
            reason = "eyes_rest"
        elif expression == "frown" and self._latched_cue != expression and held >= 8:
            reason = "sustained_frown"
        elif sample - self._present_since >= self.checkin_minutes * 60:
            reason = "gentle_checkin"

        if reason is not None:
            self._message = MESSAGES[reason]
            self._reason = reason
            self._last_prompt_at = now
            self._prompt_until = now + self.prompt_seconds
            self._reaction_until = now + self.reaction_seconds
            self._present_since = max(now, sample)
            if reason in {"eyes_rest", "sustained_frown"}:
                self._latched_cue = expression
            return self._result(now, nudge=True)
        return self._result(now)
