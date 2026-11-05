#!/usr/bin/env python3
"""Offline pose accuracy harness (AI strategy Phase 3, slice E2; strategy section 7).

Answers one question before any video feature is built: do MediaPipe joint
angles separate a coach's "pass" from "fail" on the Level 1-2 grip and lunge
criteria? It reads a folder of side-on clips and a coach's label CSV, runs
MediaPipe pose locally, and prints per-criterion separation plus the
"can't tell" rate.

Privacy:
  * Runs entirely on this laptop. Nothing is sent to any model, server or
    network; tests/test_pose_accuracy_harness.py fails if this module imports
    a network client.
  * Face landmarks (MediaPipe indices 0-10) are dropped as each frame's result
    is converted, before the frame is kept in memory, aggregated or printed.
  * Nothing is written to disk; output is the printed table only.
  * The clips folder must live outside the repository (enforced). Real clips
    are only run after owner gates 3a (reviewed consent recorded per child)
    and 3b (twenty such clips exist).

Install (laptop only, never in CI requirements):
  pip install mediapipe opencv-python

Usage:
  python scripts/dev/pose_accuracy_harness.py --clips ~/pose-clips --labels ~/pose-clips/labels.csv

Labels CSV, one row per clip per criterion (header required):
  clip,criterion,label
  kid01_lunge,lunge_front_knee,pass
  kid01_lunge,lunge_back_leg,fail

`clip` is the video file name without its extension. `criterion` is a key of
CRITERIA below. `label` is pass or fail; a blank label means the coach did not
judge it and the row is skipped.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi"}

# MediaPipe Pose landmark indices (33 total). 0-10 are the face.
FACE_LANDMARKS = range(0, 11)
NUM_LANDMARKS = 33
L_SHOULDER, R_SHOULDER = 11, 12
L_ELBOW, R_ELBOW = 13, 14
L_WRIST, R_WRIST = 15, 16
L_INDEX, R_INDEX = 19, 20
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28

# shortcut: assumes a right-handed player lunging on the racket (right) leg;
# add a per-clip handedness column when a left-handed child is in the set.
CRITERIA: dict[str, dict[str, object]] = {
    # key: (a, vertex, c) angle at the vertex in degrees, a per-clip reducer,
    # and what the coach is judging. "at_lunge_depth" reads the angle on the
    # frame where the front knee is most bent, so standing frames before or
    # after the lunge do not stand in for it.
    "grip_wrist_cock": {
        "joints": (R_ELBOW, R_WRIST, R_INDEX),
        "reduce": "median",
        "meaning": "Grip: wrist cocked back at ready (elbow-wrist-index angle).",
    },
    "grip_ready_elbow": {
        "joints": (R_SHOULDER, R_ELBOW, R_WRIST),
        "reduce": "median",
        "meaning": "Grip: racket arm bent and up at ready (shoulder-elbow-wrist angle).",
    },
    "lunge_front_knee": {
        "joints": (R_HIP, R_KNEE, R_ANKLE),
        "reduce": "min",
        "meaning": "Lunge: front knee near 90 degrees at the deepest point (hip-knee-ankle).",
    },
    "lunge_back_leg": {
        "joints": (L_HIP, L_KNEE, L_ANKLE),
        "reduce": "at_lunge_depth",
        "meaning": "Lunge: back leg extended at the deepest lunge frame (back hip-knee-ankle).",
    },
    "lunge_trunk_upright": {
        "joints": (R_SHOULDER, R_HIP, R_KNEE),
        "reduce": "median",
        "meaning": "Lunge: trunk upright over the front leg (shoulder-hip-knee).",
    },
}

DEFAULT_MIN_VISIBILITY = 0.5
DEFAULT_MIN_VALID_FRACTION = 0.5

# A landmark is (x, y, z, visibility); None means missing or dropped.
Landmark = tuple[float, float, float, float]
Frame = list[Landmark | None]


# ---------------------------------------------------------------- pure functions


def drop_face(landmarks: Iterable[object], width: float = 1.0, height: float = 1.0) -> Frame:
    """Convert MediaPipe landmarks (objects with x, y, z, visibility) to a frame.

    MediaPipe normalises x by image width and y by image height, so a
    non-square clip would skew every angle; pass the frame size to get pixel
    coordinates (z is on the x scale). Face landmarks become None without
    their coordinates ever being read, so no face point is copied out of the
    MediaPipe result.
    """
    return [
        None if i in FACE_LANDMARKS else (lm.x * width, lm.y * height, lm.z * width, lm.visibility)  # type: ignore[attr-defined]
        for i, lm in enumerate(landmarks)
    ]


def joint_angle(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> float:
    """Angle ABC in degrees, in the image (x, y) plane: the side-on view."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 == 0 or n2 == 0:
        raise ValueError("degenerate angle: two joints coincide")
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def frame_angle(
    frame: Sequence[Landmark | None], joints: Sequence[int], min_visibility: float
) -> float | None:
    """Criterion angle for one frame, or None when the frame can't tell."""
    points = [frame[j] if j < len(frame) else None for j in joints]
    if any(p is None or p[3] < min_visibility for p in points):
        return None
    try:
        return joint_angle(*points)  # type: ignore[arg-type]
    except ValueError:
        return None


@dataclass
class ClipMeasure:
    value: float | None  # None: the clip can't tell
    frames: int
    unusable_frames: int


def measure_clip(
    frames: Sequence[Sequence[Landmark | None]],
    criterion: str,
    min_visibility: float = DEFAULT_MIN_VISIBILITY,
    min_valid_fraction: float = DEFAULT_MIN_VALID_FRACTION,
) -> ClipMeasure:
    spec = CRITERIA[criterion]
    angles = [frame_angle(f, spec["joints"], min_visibility) for f in frames]  # type: ignore[arg-type]
    valid = [a for a in angles if a is not None]
    unusable = len(angles) - len(valid)
    if not valid or len(valid) < min_valid_fraction * len(angles):
        return ClipMeasure(None, len(angles), unusable)
    if spec["reduce"] == "at_lunge_depth":
        front_joints = CRITERIA["lunge_front_knee"]["joints"]
        paired = [
            (front, angle)
            for f, angle in zip(frames, angles, strict=True)
            if angle is not None
            and (front := frame_angle(f, front_joints, min_visibility)) is not None  # type: ignore[arg-type]
        ]
        if not paired:
            return ClipMeasure(None, len(angles), unusable)
        return ClipMeasure(min(paired)[1], len(angles), unusable)
    reducer = {"median": statistics.median, "min": min, "max": max}[spec["reduce"]]  # type: ignore[index]
    return ClipMeasure(reducer(valid), len(angles), unusable)


def read_labels(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, bool]]:
    """{clip: {criterion: passed}} from CSV rows; rejects unknown criteria/labels."""
    labels: dict[str, dict[str, bool]] = {}
    for line, row in enumerate(rows, start=2):
        clip = (row.get("clip") or "").strip()
        criterion = (row.get("criterion") or "").strip()
        label = (row.get("label") or "").strip().lower()
        if not label:
            continue
        if not clip:
            raise ValueError(f"labels line {line}: missing clip")
        if criterion not in CRITERIA:
            raise ValueError(f"labels line {line}: unknown criterion {criterion!r}")
        if label not in {"pass", "fail"}:
            raise ValueError(f"labels line {line}: label must be pass or fail, got {label!r}")
        labels.setdefault(clip, {})[criterion] = label == "pass"
    return labels


@dataclass
class Join:
    matched: dict[str, dict[str, bool]]
    clips_without_labels: list[str]
    labels_without_clips: list[str]


def join_clips_and_labels(clip_names: Iterable[str], labels: dict[str, dict[str, bool]]) -> Join:
    clips = set(clip_names)
    return Join(
        matched={c: labels[c] for c in sorted(clips & labels.keys())},
        clips_without_labels=sorted(clips - labels.keys()),
        labels_without_clips=sorted(labels.keys() - clips),
    )


def auc(passes: Sequence[float], fails: Sequence[float]) -> float:
    """Direction-free AUC: 1.0 is perfect separation, 0.5 is none."""
    wins = sum(1.0 if p > f else 0.5 if p == f else 0.0 for p in passes for f in fails)
    raw = wins / (len(passes) * len(fails))
    return max(raw, 1.0 - raw)


def cohens_d(passes: Sequence[float], fails: Sequence[float]) -> float | None:
    """Gap between group means in pooled standard deviations (absolute)."""
    if len(passes) < 2 or len(fails) < 2:
        return None
    pooled = math.sqrt(
        (
            (len(passes) - 1) * statistics.variance(passes)
            + (len(fails) - 1) * statistics.variance(fails)
        )
        / (len(passes) + len(fails) - 2)
    )
    gap = abs(statistics.fmean(passes) - statistics.fmean(fails))
    return math.inf if pooled == 0 and gap else (gap / pooled if pooled else 0.0)


@dataclass
class CriterionReport:
    criterion: str
    pass_values: list[float]
    fail_values: list[float]
    labelled_clips: int
    cant_tell_clips: int
    frames: int
    unusable_frames: int

    @property
    def auc(self) -> float | None:
        return (
            auc(self.pass_values, self.fail_values)
            if self.pass_values and self.fail_values
            else None
        )

    @property
    def cohens_d(self) -> float | None:
        return cohens_d(self.pass_values, self.fail_values)


def build_reports(
    measures: dict[str, dict[str, ClipMeasure]], matched: dict[str, dict[str, bool]]
) -> list[CriterionReport]:
    """measures is {clip: {criterion: ClipMeasure}}; one report per criterion."""
    reports = []
    for criterion in CRITERIA:
        r = CriterionReport(criterion, [], [], 0, 0, 0, 0)
        for clip, crit_labels in matched.items():
            if criterion not in crit_labels:
                continue
            m = measures[clip][criterion]
            r.labelled_clips += 1
            r.frames += m.frames
            r.unusable_frames += m.unusable_frames
            if m.value is None:
                r.cant_tell_clips += 1
            elif crit_labels[criterion]:
                r.pass_values.append(m.value)
            else:
                r.fail_values.append(m.value)
        reports.append(r)
    return reports


def _group(values: Sequence[float]) -> str:
    if not values:
        return "n=0"
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return f"n={len(values)} {statistics.fmean(values):6.1f}±{sd:4.1f}"


def format_reports(reports: Sequence[CriterionReport]) -> str:
    head = f"{'criterion':<22}{'pass (deg)':<20}{'fail (deg)':<20}{'AUC':>6}{'d':>7}{'cant-tell clips':>17}{'unusable frames':>17}"
    lines = [head, "-" * len(head)]
    for r in reports:
        a = f"{r.auc:.2f}" if r.auc is not None else "-"
        d = r.cohens_d
        d_text = "-" if d is None else ("inf" if math.isinf(d) else f"{d:.2f}")
        clips = f"{r.cant_tell_clips}/{r.labelled_clips}"
        frames = f"{r.unusable_frames / r.frames:.0%}" if r.frames else "-"
        lines.append(
            f"{r.criterion:<22}{_group(r.pass_values):<20}{_group(r.fail_values):<20}{a:>6}{d_text:>7}{clips:>17}{frames:>17}"
        )
    lines.append("")
    lines.append(
        "AUC is direction-free (1.00 perfect, 0.50 none); d is the mean gap in pooled SDs."
    )
    return "\n".join(lines)


# ------------------------------------------------------------- clip reading path


def read_clip_frames(path: Path) -> Iterator[Frame]:
    """Yield face-dropped landmark frames from one clip. Needs mediapipe + opencv."""
    try:
        import cv2
        import mediapipe as mp
    except ImportError:
        sys.exit("Install the laptop-only dependencies first: pip install mediapipe opencv-python")

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"cannot open {path.name}")
    try:
        with mp.solutions.pose.Pose(static_image_mode=False, model_complexity=1) as pose:
            while True:
                ok, image = capture.read()
                if not ok:
                    break
                height, width = image.shape[:2]
                result = pose.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                del image
                if result.pose_landmarks is None:
                    yield [None] * NUM_LANDMARKS
                    continue
                yield drop_face(result.pose_landmarks.landmark, width=width, height=height)
                del result
    finally:
        capture.release()


def find_clips(folder: Path) -> dict[str, Path]:
    return {p.stem: p for p in sorted(folder.iterdir()) if p.suffix.lower() in VIDEO_SUFFIXES}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--clips", type=Path, required=True, help="folder of side-on clips, outside the repo"
    )
    parser.add_argument(
        "--labels", type=Path, required=True, help="coach CSV: clip,criterion,label"
    )
    parser.add_argument("--min-visibility", type=float, default=DEFAULT_MIN_VISIBILITY)
    parser.add_argument("--min-valid-fraction", type=float, default=DEFAULT_MIN_VALID_FRACTION)
    args = parser.parse_args(argv)

    clips_dir = args.clips.expanduser().resolve()
    if clips_dir.is_relative_to(REPO_ROOT):
        parser.error("the clips folder must be outside the repository; clips never enter the repo")
    if not clips_dir.is_dir():
        parser.error(f"not a folder: {clips_dir}")

    with args.labels.expanduser().open(newline="", encoding="utf-8") as handle:
        labels = read_labels(csv.DictReader(handle))
    clips = find_clips(clips_dir)
    join = join_clips_and_labels(clips, labels)
    for name in join.clips_without_labels:
        print(f"WARNING clip has no labels, skipped: {name}")
    for name in join.labels_without_clips:
        print(f"WARNING labels have no clip: {name}")

    measures: dict[str, dict[str, ClipMeasure]] = {}
    for name in join.matched:
        frames = list(read_clip_frames(clips[name]))
        measures[name] = {
            c: measure_clip(frames, c, args.min_visibility, args.min_valid_fraction)
            for c in CRITERIA
        }
        del frames
    print(format_reports(build_reports(measures, join.matched)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
