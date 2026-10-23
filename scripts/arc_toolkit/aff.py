from __future__ import annotations

import math
import re
import bisect
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TAP_RE = re.compile(r"(?m)^\s*\(\s*(\d+)\s*,\s*([1-4])\s*\);\s*$")
HOLD_RE = re.compile(r"\bhold\(\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*([1-4])\s*\);")
ARC_RE = re.compile(r"\barc\(([^)]*)\)(?:\[([^\]]*)\])?;")
ARCTAP_RE = re.compile(
    r"arctap\(\s*(-?\d+)(?:\s*,\s*(-?(?:\d+(?:\.\d*)?|\.\d+)))?\s*\)"
)
TIMING_RE = re.compile(r"\btiming\(\s*(-?\d+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\);")
CAMERA_RE = re.compile(r"\bcamera\(([^)]*)\);")
SCENECONTROL_RE = re.compile(r"\bscenecontrol\(([^)]*)\);")
AUDIO_OFFSET_RE = re.compile(r"(?m)^AudioOffset:\s*(-?\d+)")
DENSITY_RE = re.compile(r"(?m)^TimingPointDensityFactor:\s*([\d.]+)")
TIMINGGROUP_RE = re.compile(r"\btiminggroup\(([^)]*)\)")
TIMINGGROUP_OPEN_RE = re.compile(r"\btiminggroup\(([^)]*)\)\s*\{")


def _timing_group_scopes(text: str) -> list[tuple[int, int, int, str]]:
    """Locate non-nested AFF timinggroup bodies for event ownership.

    AFF timinggroups are not nested. Invalid/unbalanced input is left to the
    validator; the parser fails closed by ending an unclosed scope at EOF.
    """
    scopes: list[tuple[int, int, int, str]] = []
    for group_id, match in enumerate(TIMINGGROUP_OPEN_RE.finditer(text), 1):
        depth = 1
        index = match.end()
        while index < len(text) and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        scopes.append((match.end(), index - 1 if depth == 0 else len(text), group_id, match.group(1).strip()))
    return scopes


def _timing_group_at(scopes: list[tuple[int, int, int, str]], position: int) -> int:
    for start, end, group_id, _ in scopes:
        if start <= position < end:
            return group_id
    return 0


def _ease_arc_axis(kind: str, progress: float) -> float:
    progress = min(1.0, max(0.0, progress))
    if kind == "i":
        return math.sin(progress * math.pi / 2.0)
    if kind == "o":
        return 1.0 - math.cos(progress * math.pi / 2.0)
    if kind == "b":
        return progress * progress * (3.0 - 2.0 * progress)
    return progress


def _arc_position_candidate(arc: "AffEvent", timing_ms: int) -> tuple[float, float, float]:
    """Mirror ArcCreate ArcFormula/positionAt for hand-side classification.

    Confidence is intentionally lower when a curve crosses the centre line;
    the side-to-hand mapping remains a heuristic even when geometry is exact.
    """
    duration = max(arc.end_ms - arc.start_ms, 1)
    progress = (timing_ms - arc.start_ms) / duration
    curve = str(arc.data.get("curve", "s")).lower()
    axis_kinds = {
        "s": ("s", "s"),
        "b": ("b", "b"),
        "si": ("i", "s"),
        "so": ("o", "s"),
        "sisi": ("i", "i"),
        "siso": ("i", "o"),
        "sosi": ("o", "i"),
        "soso": ("o", "o"),
    }
    x_kind, y_kind = axis_kinds.get(curve, ("s", "s"))
    x_progress = _ease_arc_axis(x_kind, progress)
    y_progress = _ease_arc_axis(y_kind, progress)
    x = float(arc.data["x1"]) + (float(arc.data["x2"]) - float(arc.data["x1"])) * x_progress
    y = float(arc.data["y1"]) + (float(arc.data["y2"]) - float(arc.data["y1"])) * y_progress
    same_side = max(float(arc.data["x1"]), float(arc.data["x2"])) <= 0.4 or min(
        float(arc.data["x1"]), float(arc.data["x2"])
    ) >= 0.6
    confidence = 0.9 if same_side else 0.55 + min(abs(x - 0.5), 0.5) * 0.5
    return x, y, min(confidence, 0.8 if curve not in {"s", "b", "si", "so", "sisi", "siso", "sosi", "soso"} else 1.0)


def _arctap_hand_candidate(x: float, confidence: float) -> tuple[str, float]:
    if x <= 0.4:
        return "left", confidence
    if x >= 0.6:
        return "right", confidence
    return "ambiguous", min(confidence, 0.5)


@dataclass
class AffEvent:
    kind: str
    start_ms: int
    end_ms: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AffChart:
    audio_offset_ms: int
    timing_point_density_factor: float
    events: list[AffEvent]
    timinggroups: list[str]
    source: str = ""

    @classmethod
    def from_text(cls, text: str, source: str = "") -> "AffChart":
        events: list[AffEvent] = []
        group_scopes = _timing_group_scopes(text)
        for match in TAP_RE.finditer(text):
            events.append(AffEvent("tap", int(match.group(1)), int(match.group(1)), {
                "lane": int(match.group(2)), "timing_group": _timing_group_at(group_scopes, match.start())
            }))
        for match in HOLD_RE.finditer(text):
            events.append(AffEvent("hold", int(match.group(1)), int(match.group(2)), {
                "lane": int(match.group(3)), "timing_group": _timing_group_at(group_scopes, match.start())
            }))
        for match in TIMING_RE.finditer(text):
            events.append(
                AffEvent(
                    "timing",
                    int(match.group(1)),
                    int(match.group(1)),
                    {"bpm": float(match.group(2)), "divisor": float(match.group(3)),
                     "timing_group": _timing_group_at(group_scopes, match.start())},
                )
            )
        for match in CAMERA_RE.finditer(text):
            fields = [part.strip() for part in match.group(1).split(",")]
            if len(fields) < 9:
                continue
            try:
                start = int(fields[0])
                duration = int(float(fields[-1]))
            except ValueError:
                continue
            events.append(
                AffEvent(
                    "camera",
                    start,
                    start + max(duration, 0),
                    {"easing": fields[-2], "fields": fields[1:-2],
                     "timing_group": _timing_group_at(group_scopes, match.start())},
                )
            )
        for match in SCENECONTROL_RE.finditer(text):
            fields = [part.strip() for part in match.group(1).split(",")]
            if len(fields) < 2:
                continue
            try:
                start = int(fields[0])
            except ValueError:
                continue
            events.append(AffEvent("scenecontrol", start, start, {
                "type": fields[1], "fields": fields[2:],
                "timing_group": _timing_group_at(group_scopes, match.start())
            }))
        for match in ARC_RE.finditer(text):
            fields = [part.strip() for part in match.group(1).split(",")]
            if len(fields) < 10:
                continue
            try:
                start, end = int(fields[0]), int(fields[1])
                arc = AffEvent(
                    "arc",
                    start,
                    end,
                    {
                        "x1": float(fields[2]),
                        "x2": float(fields[3]),
                        "curve": fields[4],
                        "y1": float(fields[5]),
                        "y2": float(fields[6]),
                        "color": int(fields[7]),
                        "effect": fields[8],
                        "trace": fields[9].lower() == "true",
                        "timing_group": _timing_group_at(group_scopes, match.start()),
                    },
                )
            except ValueError:
                continue
            events.append(arc)
            for arctap in ARCTAP_RE.finditer(match.group(2) or ""):
                arctap_timing = int(arctap.group(1))
                x, y, position_confidence = _arc_position_candidate(arc, arctap_timing)
                hand_candidate, hand_confidence = _arctap_hand_candidate(x, position_confidence)
                events.append(
                    AffEvent(
                        "arctap",
                        arctap_timing,
                        arctap_timing,
                        {
                            "parent_arc": (start, end),
                            "parent_curve": arc.data["curve"],
                            "width": float(arctap.group(2)) if arctap.group(2) is not None else 1.0,
                            "x_candidate": round(x, 5),
                            "y_candidate": round(y, 5),
                            "position_confidence": round(position_confidence, 4),
                            "hand_candidate": hand_candidate,
                            "hand_confidence": round(hand_confidence, 4),
                            "timing_group": arc.data["timing_group"],
                        },
                    )
                )
        offset = AUDIO_OFFSET_RE.search(text)
        density = DENSITY_RE.search(text)
        return cls(
            audio_offset_ms=int(offset.group(1)) if offset else 0,
            timing_point_density_factor=float(density.group(1)) if density else 1.0,
            events=sorted(events, key=lambda event: (event.start_ms, event.kind)),
            timinggroups=[scope[3] for scope in group_scopes],
            source=source,
        )

    @classmethod
    def from_path(cls, path: str | Path) -> "AffChart":
        chart_path = Path(path)
        return cls.from_text(chart_path.read_text(encoding="utf-8-sig", errors="replace"), str(chart_path.resolve()))

    def playable_events(self) -> list[AffEvent]:
        return [
            event
            for event in self.events
            if event.kind in {"tap", "hold", "arctap"}
            or (event.kind == "arc" and not event.data.get("trace", False))
        ]

    def input_arc_chains(
        self,
        time_tolerance_ms: int = 1,
        endpoint_tolerance: float = 0.0,
    ) -> list[list[AffEvent]]:
        """Join a conservative same-color subset of ArcCreate connections.

        ArcCreate connects arcs within one timing group when their time differs
        by at most 1 ms, x/y endpoints compare exactly, and trace/input status
        matches. Different colors and branches are kept separate here because
        a render connection alone does not prove one continuous hand gesture.
        A non-zero endpoint tolerance is exploratory only.
        """
        arcs = sorted(
            (
                event
                for event in self.events
                if event.kind == "arc" and not event.data.get("trace", False)
            ),
            key=lambda event: (event.start_ms, event.end_ms),
        )
        chains: list[list[AffEvent]] = []
        for arc in arcs:
            candidates: list[tuple[float, list[AffEvent]]] = []
            for chain in chains:
                previous = chain[-1]
                if previous.data.get("color") != arc.data.get("color"):
                    continue
                if previous.data.get("timing_group", 0) != arc.data.get("timing_group", 0):
                    continue
                if abs(previous.end_ms - arc.start_ms) > time_tolerance_ms:
                    continue
                endpoint_distance = math.dist(
                    (previous.data["x2"], previous.data["y2"]),
                    (arc.data["x1"], arc.data["y1"]),
                )
                if endpoint_distance <= endpoint_tolerance:
                    candidates.append((endpoint_distance, chain))
            if candidates:
                min(candidates, key=lambda item: item[0])[1].append(arc)
            else:
                chains.append([arc])
        return chains

    def playable_gesture_events(self) -> list[AffEvent]:
        """Return input starts, collapsing contiguous arc segments."""
        arc_chain_first_ids = {id(chain[0]) for chain in self.input_arc_chains()}
        return [
            event
            for event in self.playable_events()
            if event.kind != "arc" or id(event) in arc_chain_first_ids
        ]

    def summary(self, duration_s: float | None = None) -> dict[str, Any]:
        counts = Counter(event.kind for event in self.events)
        counts["arc_input"] = sum(event.kind == "arc" and not event.data.get("trace", False) for event in self.events)
        counts["arc_trace"] = sum(event.kind == "arc" and event.data.get("trace", False) for event in self.events)
        playable = self.playable_events()
        arc_chains = self.input_arc_chains()
        playable_gestures = len(self.playable_gesture_events())
        if duration_s is None:
            duration_s = max((event.end_ms for event in self.events), default=0) / 1000
        arc_movements = [
            math.dist((event.data["x1"], event.data["y1"]), (event.data["x2"], event.data["y2"]))
            for event in self.events
            if event.kind == "arc"
        ]
        lanes = Counter(event.data["lane"] for event in self.events if event.kind in {"tap", "hold"})
        lane_total = sum(lanes.values())
        lane_entropy = 0.0
        if lane_total:
            probabilities = [count / lane_total for count in lanes.values()]
            lane_entropy = -sum(p * math.log(p) for p in probabilities) / math.log(4)
        return {
            "source": self.source,
            "audio_offset_ms": self.audio_offset_ms,
            "duration_s": round(duration_s, 4),
            "counts": dict(counts),
            "playable_objects": len(playable),
            "playable_objects_per_second": round(len(playable) / max(duration_s, 1e-6), 4),
            "playable_gestures": playable_gestures,
            "playable_gestures_per_second": round(
                playable_gestures / max(duration_s, 1e-6), 4
            ),
            "input_arc_chains": len(arc_chains),
            "timinggroup_count": len(self.timinggroups),
            "noinput_group_count": sum("noinput" in group for group in self.timinggroups),
            "mean_arc_movement": round(sum(arc_movements) / max(len(arc_movements), 1), 4),
            "lane_entropy": round(lane_entropy, 4),
        }

    def section_profile(self, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        gesture_events = self.playable_gesture_events()
        for section in sections:
            start_ms = int(float(section["start_s"]) * 1000) - self.audio_offset_ms
            end_ms = int(float(section["end_s"]) * 1000) - self.audio_offset_ms
            events = [event for event in self.playable_events() if start_ms <= event.start_ms < end_ms]
            counts = Counter(event.kind if event.kind != "arc" else "arc_input" for event in events)
            gestures = [event for event in gesture_events if start_ms <= event.start_ms < end_ms]
            result.append(
                {
                    "section_index": section["index"],
                    "role_candidate": section.get("role_candidate"),
                    "role_confidence": section.get("role_confidence"),
                    "role_candidates": section.get("role_candidates", []),
                    "start_s": section["start_s"],
                    "end_s": section["end_s"],
                    "playable_objects": len(events),
                    "objects_per_second": round(len(events) / max((end_ms - start_ms) / 1000, 1e-6), 4),
                    "playable_gestures": len(gestures),
                    "gestures_per_second": round(
                        len(gestures) / max((end_ms - start_ms) / 1000, 1e-6), 4
                    ),
                    "input_arc_chain_starts": sum(
                        event.kind == "arc" for event in gestures
                    ),
                    "counts": dict(counts),
                }
            )
        return result

    def boundary_profile(
        self,
        sections: list[dict[str, Any]],
        bpm: float,
        window_beats: float = 8.0,
    ) -> list[dict[str, Any]]:
        """Summarize chart flow around tentative acoustic section boundaries.

        Boundaries remain hypotheses supplied by audio analysis. The profile
        records observable chart facts near them and does not infer intent.
        """
        playable = self.playable_events()
        arc_chains = self.input_arc_chains()
        arc_chain_first_ids = {id(chain[0]) for chain in arc_chains}
        gesture_starts = self.playable_gesture_events()
        half_window_ms = float(window_beats) * 60000.0 / max(float(bpm), 1e-6)
        result: list[dict[str, Any]] = []
        for section in sections[1:]:
            boundary_ms = int(round(float(section["start_s"]) * 1000)) - self.audio_offset_ms
            window_start = boundary_ms - half_window_ms
            window_end = boundary_ms + half_window_ms
            nearby = [event for event in playable if window_start <= event.start_ms <= window_end]
            counts = Counter(event.kind if event.kind != "arc" else "arc_input" for event in nearby)
            input_arcs = [
                event
                for event in self.events
                if event.kind == "arc"
                and not event.data.get("trace", False)
                and window_start <= event.start_ms <= window_end
            ]
            nearby_arc_chain_starts = [
                event for event in input_arcs if id(event) in arc_chain_first_ids
            ]
            arc_movements = [
                math.dist(
                    (event.data["x1"], event.data["y1"]),
                    (event.data["x2"], event.data["y2"]),
                )
                for event in input_arcs
            ]
            starts_before = [event.start_ms for event in playable if event.start_ms < boundary_ms]
            starts_after = [event.start_ms for event in playable if event.start_ms >= boundary_ms]
            gesture_starts_before = [
                event.start_ms for event in gesture_starts if event.start_ms < boundary_ms
            ]
            gesture_starts_after = [
                event.start_ms for event in gesture_starts if event.start_ms >= boundary_ms
            ]
            adjacent_gap = None
            next_delay = None
            adjacent_gesture_gap = None
            next_gesture_delay = None
            if starts_before and starts_after:
                adjacent_gap = min(starts_after) - max(starts_before)
            if starts_after:
                next_delay = min(starts_after) - boundary_ms
            if gesture_starts_before and gesture_starts_after:
                adjacent_gesture_gap = min(gesture_starts_after) - max(gesture_starts_before)
            if gesture_starts_after:
                next_gesture_delay = min(gesture_starts_after) - boundary_ms

            active_arc_chains = [
                chain
                for chain in arc_chains
                if chain[0].start_ms < boundary_ms < chain[-1].end_ms
            ]
            active_holds = [
                event
                for event in self.events
                if event.kind == "hold" and event.start_ms < boundary_ms < event.end_ms
            ]
            release_by_hand: dict[str, int] = {}
            for chain in active_arc_chains:
                hand = "left" if chain[0].data.get("color", 0) == 0 else "right"
                release_by_hand[hand] = max(release_by_hand.get(hand, boundary_ms), chain[-1].end_ms)
            for hold in active_holds:
                hand = "left" if int(hold.data.get("lane", 1)) <= 2 else "right"
                release_by_hand[hand] = max(release_by_hand.get(hand, boundary_ms), hold.end_ms)

            one_beat_ms = 60000.0 / max(float(bpm), 1e-6)
            upcoming_gestures = [
                event
                for event in gesture_starts
                if boundary_ms <= event.start_ms <= boundary_ms + one_beat_ms
            ]
            same_hand_overlap = 0
            same_hand_quick_reentry = 0
            unknown_sky_inputs = 0
            arctap_hand_candidates = Counter()
            for event in upcoming_gestures:
                hand: str | None = None
                if event.kind in {"tap", "hold"}:
                    hand = "left" if int(event.data.get("lane", 1)) <= 2 else "right"
                elif event.kind == "arc":
                    hand = "left" if event.data.get("color", 0) == 0 else "right"
                elif event.kind == "arctap":
                    candidate = str(event.data.get("hand_candidate", "ambiguous"))
                    arctap_hand_candidates[candidate] += 1
                    if candidate in {"left", "right"}:
                        hand = candidate
                    else:
                        unknown_sky_inputs += 1
                if hand is None or hand not in release_by_hand:
                    continue
                release_ms = release_by_hand[hand]
                if event.start_ms < release_ms:
                    same_hand_overlap += 1
                elif event.start_ms - release_ms <= one_beat_ms * 0.25:
                    same_hand_quick_reentry += 1
            result.append(
                {
                    "section_index": section["index"],
                    "boundary_time_s": section["start_s"],
                    "role_candidate_after": section.get("role_candidate"),
                    "role_confidence_after": section.get("role_confidence"),
                    "window_beats_each_side": float(window_beats),
                    "playable_objects": len(nearby),
                    "playable_gesture_starts": sum(
                        window_start <= event.start_ms <= window_end for event in gesture_starts
                    ),
                    "counts": dict(counts),
                    "input_arc_segments": len(input_arcs),
                    "input_arc_chain_starts": len(nearby_arc_chain_starts),
                    "input_arc_segment_continuations": len(input_arcs)
                    - len(nearby_arc_chain_starts),
                    "mean_input_arc_movement": round(
                        sum(arc_movements) / max(len(arc_movements), 1), 4
                    ),
                    "input_arcs_crossing_boundary": sum(
                        event.kind == "arc"
                        and not event.data.get("trace", False)
                        and event.start_ms < boundary_ms < event.end_ms
                        for event in self.events
                    ),
                    "input_arc_chains_crossing_boundary": len(active_arc_chains),
                    "holds_crossing_boundary": sum(
                        event.kind == "hold" and event.start_ms < boundary_ms < event.end_ms
                        for event in self.events
                    ),
                    "adjacent_start_gap_ms": adjacent_gap,
                    "next_input_delay_ms": next_delay,
                    "adjacent_gesture_start_gap_ms": adjacent_gesture_gap,
                    "next_gesture_delay_ms": next_gesture_delay,
                    "occupied_hands_candidate": sorted(release_by_hand),
                    "same_hand_overlap_candidates_within_1beat": same_hand_overlap,
                    "same_hand_quick_reentry_candidates_within_1beat": same_hand_quick_reentry,
                    "unknown_sky_inputs_within_1beat": unknown_sky_inputs,
                    "arctap_hand_candidates_within_1beat": dict(arctap_hand_candidates),
                }
            )
        return result

    def onset_alignment(
        self,
        onset_times_s: list[float],
        include_arc_continuations: bool = False,
    ) -> dict[str, Any]:
        onsets = sorted(float(value) for value in onset_times_s)
        if len(onsets) < 2:
            return {"median_distance_ms": None, "within_50ms": 0.0, "within_80ms": 0.0}
        distances: list[float] = []
        events = self.playable_events() if include_arc_continuations else self.playable_gesture_events()
        for event in events:
            audio_time = (event.start_ms + self.audio_offset_ms) / 1000
            index = bisect.bisect_left(onsets, audio_time)
            candidates = []
            if index < len(onsets):
                candidates.append(abs(audio_time - onsets[index]))
            if index > 0:
                candidates.append(abs(audio_time - onsets[index - 1]))
            if candidates:
                distances.append(min(candidates))
        if not distances:
            return {"median_distance_ms": None, "within_50ms": 0.0, "within_80ms": 0.0}
        return {
            "median_distance_ms": round(statistics.median(distances) * 1000, 3),
            "within_50ms": round(sum(value <= 0.05 for value in distances) / len(distances), 4),
            "within_80ms": round(sum(value <= 0.08 for value in distances) / len(distances), 4),
        }

    def hand_lock_audit(self, bpm: float) -> dict[str, Any]:
        """Estimate one-hand strain while the other hand holds an input arc.

        Arc color is treated as the intended-hand convention: blue/0 locks the
        left hand and red/1 locks the right. This is conservative and does not
        replace playtesting.
        """
        instant = [event for event in self.playable_events() if event.start_ms == event.end_ms]
        beat_ms = 60000.0 / max(float(bpm), 1e-6)
        issues: list[dict[str, Any]] = []
        inspected = 0
        for arc in self.events:
            if arc.kind != "arc" or arc.data.get("trace", False):
                continue
            inspected += 1
            locked_hand = "left" if arc.data.get("color", 0) == 0 else "right"
            free_lanes = {3, 4} if locked_hand == "left" else {1, 2}
            during = sorted(
                (event for event in instant if arc.start_ms <= event.start_ms < arc.end_ms),
                key=lambda event: event.start_ms,
            )
            floor = [event for event in during if event.kind == "tap"]
            sky = [event for event in during if event.kind == "arctap"]
            reasons: list[str] = []
            duration = arc.end_ms - arc.start_ms
            if duration > beat_ms * 1.25 and len(during) >= 3:
                reasons.append("long moving hand-lock with multiple opposite-hand notes")
            same_hand_sky = [
                event
                for event in sky
                if event.data.get("hand_candidate") == locked_hand
            ]
            ambiguous_sky = [
                event
                for event in sky
                if event.data.get("hand_candidate", "ambiguous") == "ambiguous"
            ]
            if same_hand_sky:
                reasons.append(
                    f"{len(same_hand_sky)} sky inputs fall on the locked hand's candidate side"
                )
            if ambiguous_sky:
                reasons.append(
                    f"{len(ambiguous_sky)} sky inputs have ambiguous hand assignment during the arc"
                )
            wrong_side = [event for event in floor if event.data.get("lane") not in free_lanes]
            if wrong_side:
                reasons.append(f"{len(wrong_side)} floor notes enter the locked hand's natural side")
            rapid_pairs: list[dict[str, int]] = []
            wide_pairs: list[dict[str, int]] = []
            for previous, current in zip(floor, floor[1:]):
                interval = current.start_ms - previous.start_ms
                jump = abs(int(current.data["lane"]) - int(previous.data["lane"]))
                if interval < max(105, beat_ms * 0.42):
                    rapid_pairs.append({"time_ms": current.start_ms, "interval_ms": interval, "lane_jump": jump})
                if interval < max(190, beat_ms * 0.72) and jump >= 2:
                    wide_pairs.append({"time_ms": current.start_ms, "interval_ms": interval, "lane_jump": jump})
            if rapid_pairs:
                reasons.append(f"{len(rapid_pairs)} one-hand pairs are faster than the comfort threshold")
            if wide_pairs:
                reasons.append(f"{len(wide_pairs)} fast one-hand lane jumps span at least two lanes")
            movement = math.dist(
                (arc.data["x1"], arc.data["y1"]),
                (arc.data["x2"], arc.data["y2"]),
            )
            if movement >= 0.9 and len(during) >= 2:
                reasons.append("large arc motion competes with opposite-hand reading")
            if reasons:
                issues.append(
                    {
                        "start_ms": arc.start_ms,
                        "end_ms": arc.end_ms,
                        "duration_ms": duration,
                        "locked_hand": locked_hand,
                        "arc_movement": round(movement, 3),
                        "floor_notes": [{"time_ms": event.start_ms, "lane": event.data["lane"]} for event in floor],
                        "sky_notes": [event.start_ms for event in sky],
                        "reasons": reasons,
                    }
                )
        return {
            "bpm": float(bpm),
            "input_arcs_inspected": inspected,
            "risky_input_arcs": len(issues),
            "issues": issues,
            "limitations": [
                "arc color is interpreted as the intended hand",
                "body posture, device size and personal technique are not modeled",
                "playtesting remains authoritative",
            ],
        }

    def playability_audit(self, bpm: float) -> dict[str, Any]:
        """Flag cramped timing, abrupt arc tension and unstable floor hand flow."""
        beat_ms = 60000.0 / max(float(bpm), 1e-6)
        # ArcCreate default world-space hitboxes converted back to AFF coordinates.
        # These are editor-player diagnostics, not claims about lowiro's implementation.
        arc_hitbox_x = 1.9 / (4.25 * 2)
        arc_hitbox_y = 2.5 / (5.5 - 1.0)
        arctap_hitbox_x = 3.02 / (4.25 * 2)
        arctap_hitbox_y = 2.5 / (5.5 - 1.0)
        rapid_arctap_window_ms = 120
        instant = sorted(
            (event for event in self.playable_events() if event.start_ms == event.end_ms),
            key=lambda event: (event.start_ms, event.kind),
        )
        unique_times = sorted({event.start_ms for event in instant})
        cramped = [
            {"previous_ms": previous, "current_ms": current, "gap_ms": current - previous}
            for previous, current in zip(unique_times, unique_times[1:])
            if 0 < current - previous < max(90, beat_ms * 0.24)
        ]

        trace_arcs = sorted(
            (
                event
                for event in self.events
                if event.kind == "arc" and event.data.get("trace", False)
            ),
            key=lambda event: (event.start_ms, event.end_ms),
        )
        continuous_trace_joints: list[dict[str, Any]] = []
        separate_trace_reentries: list[dict[str, Any]] = []
        near_misaligned_trace_joints: list[dict[str, Any]] = []
        for previous, current in zip(trace_arcs, trace_arcs[1:]):
            gap = current.start_ms - previous.end_ms
            if 0 <= gap < max(90, beat_ms * 0.24):
                endpoint_distance = math.hypot(
                    float(previous.data["x2"]) - float(current.data["x1"]),
                    float(previous.data["y2"]) - float(current.data["y1"]),
                )
                transition = {
                    "previous_end_ms": previous.end_ms,
                    "current_start_ms": current.start_ms,
                    "gap_ms": gap,
                    "endpoint_distance_aff": round(endpoint_distance, 5),
                }
                if endpoint_distance <= 0.001:
                    continuous_trace_joints.append(transition)
                elif endpoint_distance <= 0.08:
                    near_misaligned_trace_joints.append(transition)
                else:
                    separate_trace_reentries.append(transition)

        input_arcs = sorted(
            (
                event
                for event in self.events
                if event.kind == "arc" and not event.data.get("trace", False)
            ),
            key=lambda event: (event.start_ms, event.end_ms),
        )

        arctaps = sorted(
            (event for event in self.events if event.kind == "arctap"),
            key=lambda event: (event.start_ms, event.data.get("x_candidate", 0.5)),
        )
        arctap_active_arc_proximity: list[dict[str, Any]] = []
        for arctap in arctaps:
            nearby: list[tuple[float, AffEvent, float, float]] = []
            for arc in input_arcs:
                if not arc.start_ms <= arctap.start_ms <= arc.end_ms:
                    continue
                arc_x, arc_y, _ = _arc_position_candidate(arc, arctap.start_ms)
                dx = abs(float(arctap.data["x_candidate"]) - arc_x)
                dy = abs(float(arctap.data["y_candidate"]) - arc_y)
                hitbox_ratio = max(dx / arc_hitbox_x, dy / arc_hitbox_y)
                nearby.append((hitbox_ratio, arc, dx, dy))
            if nearby:
                hitbox_ratio, arc, dx, dy = min(nearby, key=lambda item: item[0])
                if hitbox_ratio <= 1:
                    arctap_active_arc_proximity.append(
                        {
                            "timing_ms": arctap.start_ms,
                            "arc_start_ms": arc.start_ms,
                            "arc_end_ms": arc.end_ms,
                            "delta_x": round(dx, 4),
                            "delta_y": round(dy, 4),
                            "arc_hitbox_ratio": round(hitbox_ratio, 3),
                        }
                    )

        simultaneous_arctap_overlap: list[dict[str, Any]] = []
        rapid_arctap_overlap: list[dict[str, Any]] = []
        for index, previous in enumerate(arctaps):
            for current in arctaps[index + 1 :]:
                interval = current.start_ms - previous.start_ms
                if interval > rapid_arctap_window_ms:
                    break
                dx = abs(float(previous.data["x_candidate"]) - float(current.data["x_candidate"]))
                dy = abs(float(previous.data["y_candidate"]) - float(current.data["y_candidate"]))
                if dx > arctap_hitbox_x or dy > arctap_hitbox_y:
                    continue
                item = {
                    "previous_ms": previous.start_ms,
                    "current_ms": current.start_ms,
                    "interval_ms": interval,
                    "delta_x": round(dx, 4),
                    "delta_y": round(dy, 4),
                }
                if interval == 0:
                    simultaneous_arctap_overlap.append(item)
                else:
                    rapid_arctap_overlap.append(item)

        tense_arcs: list[dict[str, Any]] = []
        for arc in input_arcs:
            duration = max(arc.end_ms - arc.start_ms, 1)
            movement = math.dist(
                (arc.data["x1"], arc.data["y1"]),
                (arc.data["x2"], arc.data["y2"]),
            )
            if duration < beat_ms and movement >= 0.5:
                tense_arcs.append(
                    {
                        "start_ms": arc.start_ms,
                        "end_ms": arc.end_ms,
                        "duration_ms": duration,
                        "movement": round(movement, 3),
                        "reason": "large arc displacement in less than one beat",
                    }
                )

        boundary_attachments: list[dict[str, Any]] = []
        for chain in self.input_arc_chains():
            first, last = chain[0], chain[-1]
            for event in instant:
                if event.start_ms not in {first.start_ms, last.end_ms}:
                    continue
                boundary_attachments.append(
                    {
                        "arc_start_ms": first.start_ms,
                        "arc_end_ms": last.end_ms,
                        "attached_time_ms": event.start_ms,
                        "attached_kind": event.kind,
                    }
                )

        reversals: list[dict[str, Any]] = []
        by_color = {
            color: [arc for arc in input_arcs if int(arc.data.get("color", 0)) == color]
            for color in (0, 1)
        }
        for color, arcs in by_color.items():
            for previous, current in zip(arcs, arcs[1:]):
                gap = current.start_ms - previous.end_ms
                if not 0 <= gap < beat_ms * 0.75:
                    continue
                first = (
                    previous.data["x2"] - previous.data["x1"],
                    previous.data["y2"] - previous.data["y1"],
                )
                second = (
                    current.data["x2"] - current.data["x1"],
                    current.data["y2"] - current.data["y1"],
                )
                first_length = math.hypot(*first)
                second_length = math.hypot(*second)
                if min(first_length, second_length) < 0.25:
                    continue
                cosine = (first[0] * second[0] + first[1] * second[1]) / (first_length * second_length)
                if cosine < -0.35:
                    reversals.append(
                        {
                            "color": color,
                            "previous_end_ms": previous.end_ms,
                            "current_start_ms": current.start_ms,
                            "gap_ms": gap,
                            "direction_cosine": round(cosine, 3),
                        }
                    )

        floor = [event for event in instant if event.kind == "tap"]
        same_hand_bursts: list[dict[str, int | str]] = []
        for previous, current in zip(floor, floor[1:]):
            interval = current.start_ms - previous.start_ms
            previous_lane = int(previous.data["lane"])
            current_lane = int(current.data["lane"])
            previous_hand = "left" if previous_lane <= 2 else "right"
            current_hand = "left" if current_lane <= 2 else "right"
            if 0 < interval < max(115, beat_ms * 0.34) and previous_hand == current_hand:
                same_hand_bursts.append(
                    {
                        "previous_ms": previous.start_ms,
                        "current_ms": current.start_ms,
                        "interval_ms": interval,
                        "hand": current_hand,
                        "previous_lane": previous_lane,
                        "current_lane": current_lane,
                    }
                )

        playable = self.playable_events()
        arc_chains = self.input_arc_chains()
        non_arc_playable = [event for event in playable if event.kind != "arc"]
        contact_times = sorted(
            {event.start_ms for event in non_arc_playable}
            | {event.end_ms for event in non_arc_playable if event.end_ms > event.start_ms}
            | {chain[0].start_ms for chain in arc_chains}
            | {chain[-1].end_ms for chain in arc_chains}
        )
        review_times = {event.start_ms for event in non_arc_playable} | {
            chain[0].start_ms for chain in arc_chains
        }
        chord_recovery: list[dict[str, Any]] = []
        for time in sorted(review_times):
            active = [
                event
                for event in playable
                if (event.start_ms == event.end_ms == time)
                or (event.start_ms <= time < event.end_ms)
            ]
            if len(active) < 2:
                continue
            chord_end = max((event.end_ms for event in active if event.end_ms > time), default=time)
            previous = max((value for value in contact_times if value < time), default=None)
            following = min((value for value in contact_times if value > chord_end), default=None)
            before_gap = time - previous if previous is not None else None
            after_gap = following - chord_end if following is not None else None
            if (before_gap is not None and before_gap < beat_ms * 0.5) or (
                after_gap is not None and after_gap < beat_ms * 0.5
            ):
                chord_recovery.append(
                    {
                        "time_ms": time,
                        "end_ms": chord_end,
                        "estimated_inputs": len(active),
                        "kinds": sorted(event.kind for event in active),
                        "gap_before_ms": before_gap,
                        "gap_after_ms": after_gap,
                    }
                )

        issues = {
            "cramped_input_gaps": cramped,
            "near_misaligned_trace_joints": near_misaligned_trace_joints,
            "arctap_active_arc_proximity": arctap_active_arc_proximity,
            "simultaneous_arctap_hitbox_overlap": simultaneous_arctap_overlap,
            "rapid_arctap_hitbox_overlap": rapid_arctap_overlap,
            "tense_input_arcs": tense_arcs,
            "input_arc_boundary_attachments": boundary_attachments,
            "abrupt_same_hand_arc_reversals": reversals,
            "rapid_same_hand_floor_bursts": same_hand_bursts,
            "close_chord_recovery": chord_recovery,
        }
        return {
            "bpm": float(bpm),
            "thresholds_ms": {
                "cramped_gap": round(max(90, beat_ms * 0.24), 3),
                "rapid_same_hand": round(max(115, beat_ms * 0.34), 3),
                "chord_recovery": round(beat_ms * 0.5, 3),
                "rapid_arctap_window": rapid_arctap_window_ms,
            },
            "spatial_thresholds_aff": {
                "arccreate_arc_center_dx": round(arc_hitbox_x, 4),
                "arccreate_arc_center_dy": round(arc_hitbox_y, 4),
                "arccreate_arctap_pair_dx": round(arctap_hitbox_x, 4),
                "arccreate_arctap_pair_dy": round(arctap_hitbox_y, 4),
                "trace_continuation_tolerance": 0.001,
                "trace_near_misalignment_distance": 0.08,
            },
            "summary": {
                **{key: len(value) for key, value in issues.items()},
                "continuous_trace_joints": len(continuous_trace_joints),
                "separate_trace_reentries": len(separate_trace_reentries),
            },
            "issues": issues,
            "trace_transitions": {
                "continuous_joints": continuous_trace_joints,
                "separate_reentries": separate_trace_reentries,
            },
            "review_issue_count": sum(len(value) for value in issues.values()),
            "limitations": [
                "floor lanes 1-2 and 3-4 are treated as natural left/right zones",
                "trace transition diagnostics compare adjacent endpoints; they do not model whole-curve overlap, screen-space glow or required finger travel",
                "arctap proximity uses ArcCreate's default world-space hitboxes; screen-space collision, judgement modifiers, device geometry and the official game can differ",
                "rapid arctap and active-arc proximity are review prompts because official high-difficulty charts also use them",
                "playtesting remains authoritative",
            ],
        }

    def special_effects_audit(self) -> dict[str, Any]:
        timings = [event for event in self.events if event.kind == "timing"]
        base_timing = next((event for event in timings if event.start_ms == 0), timings[0] if timings else None)
        base_bpm = float(base_timing.data["bpm"]) if base_timing else None
        timing_changes = [event for event in timings if event is not base_timing]
        cameras = [event for event in self.events if event.kind == "camera"]
        scene_controls = [event for event in self.events if event.kind == "scenecontrol"]
        overbound = [
            event
            for event in self.events
            if event.kind == "arc"
            and event.data.get("trace", False)
            and any(float(event.data[key]) < 0.0 or float(event.data[key]) > 1.0 for key in ("x1", "x2"))
        ]
        return {
            "base_bpm": base_bpm,
            "timing_changes": [
                {"time_ms": event.start_ms, "bpm": event.data["bpm"], "divisor": event.data["divisor"]}
                for event in timing_changes
            ],
            "negative_or_reverse_timings": [
                {"time_ms": event.start_ms, "bpm": event.data["bpm"]}
                for event in timings
                if float(event.data["bpm"]) < 0
            ],
            "camera_events": [
                {"time_ms": event.start_ms, "end_ms": event.end_ms, "easing": event.data["easing"]}
                for event in cameras
            ],
            "camera_reset_count": sum(event.data.get("easing") == "reset" for event in cameras),
            "scene_controls": [
                {"time_ms": event.start_ms, "type": event.data["type"]} for event in scene_controls
            ],
            "noinput_timinggroups": [group for group in self.timinggroups if "noinput" in group],
            "overbound_trace_arcs": [
                {
                    "start_ms": event.start_ms,
                    "end_ms": event.end_ms,
                    "x1": event.data["x1"],
                    "x2": event.data["x2"],
                }
                for event in overbound
            ],
            "summary": {
                "timing_change_count": len(timing_changes),
                "reverse_timing_count": sum(float(event.data["bpm"]) < 0 for event in timings),
                "camera_event_count": len(cameras),
                "scenecontrol_count": len(scene_controls),
                "noinput_timinggroup_count": sum("noinput" in group for group in self.timinggroups),
                "overbound_trace_count": len(overbound),
            },
        }


def validate_aff(path: str | Path, difficulty: str = "FTR") -> dict[str, Any]:
    chart_path = Path(path)
    text = chart_path.read_text(encoding="utf-8-sig", errors="replace")
    chart = AffChart.from_text(text, str(chart_path.resolve()))
    errors: list[str] = []
    warnings: list[str] = []
    if "AudioOffset:" not in text:
        errors.append("missing AudioOffset header")
    if "\n-" not in text.replace("\r\n", "\n"):
        errors.append("missing AFF header separator")
    if not any(event.kind == "timing" and event.start_ms == 0 for event in chart.events):
        errors.append("missing timing event at 0 ms")

    playable = chart.playable_events()
    for event in playable:
        if event.start_ms < 0 or event.end_ms < event.start_ms:
            errors.append(f"invalid {event.kind} time range at {event.start_ms} ms")
        if event.kind == "arc":
            for axis in ("y1", "y2"):
                if not math.isfinite(float(event.data[axis])):
                    errors.append(f"arc {axis} is not finite at {event.start_ms} ms")
                elif not 0 <= event.data[axis] <= 1:
                    warnings.append(
                        f"arc {axis} outside conventional 0..1 at {event.start_ms} ms; "
                        "review as intentional overbound choreography"
                    )
            for x_key, y_key in (("x1", "y1"), ("x2", "y2")):
                x, y = event.data[x_key], event.data[y_key]
                if not math.isfinite(float(x)):
                    errors.append(f"arc {x_key} is not finite at {event.start_ms} ms")
                elif not -0.5 <= x <= 1.5:
                    warnings.append(
                        f"arc {x_key} outside conventional -0.5..1.5 at {event.start_ms} ms; "
                        "review as intentional overbound choreography"
                    )
                if difficulty.upper() in {"PST", "PRS", "FTR"}:
                    left, right = -0.5 + 0.5 * y, 1.5 - 0.5 * y
                    if x < left - 1e-6 or x > right + 1e-6:
                        warnings.append(f"arc endpoint outside standard FTR trapezoid at {event.start_ms} ms")

    instants = Counter(event.start_ms for event in playable if event.start_ms == event.end_ms)
    long_events = [event for event in playable if event.end_ms > event.start_ms]
    check_times = sorted(set(instants) | {event.start_ms for event in long_events})
    max_inputs = 0
    max_input_time = 0
    three_plus_moments: list[dict[str, int]] = []
    for time in check_times:
        active = instants[time] + sum(event.start_ms <= time < event.end_ms for event in long_events)
        if active > max_inputs:
            max_inputs, max_input_time = active, time
        if active >= 3:
            three_plus_moments.append({"time_ms": time, "estimated_inputs": active})
    if three_plus_moments:
        warnings.append(
            f"estimated {max_inputs} simultaneous inputs at {max_input_time} ms; "
            "3+ inputs are valid only as intentional high-difficulty or special choreography"
        )

    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "estimated_max_simultaneous_inputs": max_inputs,
        "three_plus_input_moments": three_plus_moments[:24],
        "summary": chart.summary(),
    }
