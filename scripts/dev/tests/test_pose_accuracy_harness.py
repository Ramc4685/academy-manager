"""Tests for the E2 pose harness against drawn skeletons only (no clips, no images)."""

from __future__ import annotations

import ast
import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

DEV_SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEV_SCRIPTS))

import pose_accuracy_harness as h  # noqa: E402


def skeleton(angle_deg: float, joints: tuple[int, int, int], visibility: float = 0.9) -> list:
    """A 33-landmark frame whose `joints` form `angle_deg` at the middle joint."""
    frame: list = [(0.5, 0.5, 0.0, 0.9)] * h.NUM_LANDMARKS
    a, b, c = joints
    rad = math.radians(angle_deg)
    frame[b] = (0.5, 0.5, 0.0, visibility)
    frame[a] = (0.6, 0.5, 0.0, visibility)
    frame[c] = (0.5 + 0.1 * math.cos(rad), 0.5 + 0.1 * math.sin(rad), 0.0, visibility)
    return frame


KNEE = h.CRITERIA["lunge_front_knee"]["joints"]


class AngleTests(unittest.TestCase):
    def test_known_angles(self) -> None:
        for expected in (30.0, 90.0, 135.0, 180.0):
            self.assertAlmostEqual(
                h.frame_angle(skeleton(expected, KNEE), KNEE, 0.5), expected, places=6
            )

    def test_right_angle_from_points(self) -> None:
        self.assertAlmostEqual(h.joint_angle((1, 0), (0, 0), (0, 1)), 90.0)

    def test_clip_reducer(self) -> None:
        frames = [skeleton(a, KNEE) for a in (150, 95, 120)]
        self.assertAlmostEqual(h.measure_clip(frames, "lunge_front_knee").value, 95.0)


class FaceDropTests(unittest.TestCase):
    def test_face_landmarks_removed_and_body_kept(self) -> None:
        raw = [SimpleNamespace(x=i / 33, y=0.1, z=0.0, visibility=0.9) for i in range(33)]
        dropped = h.drop_face(raw)
        self.assertEqual(len(dropped), h.NUM_LANDMARKS)
        self.assertTrue(all(lm is None for lm in dropped[:11]))
        self.assertEqual(dropped[11:], [(lm.x, lm.y, lm.z, lm.visibility) for lm in raw[11:]])

    def test_non_square_frame_is_scaled_to_pixels_before_angles(self) -> None:
        # A true 90 degree knee in a 1920x1080 clip, given in normalised coords.
        px = {h.R_HIP: (760, 340), h.R_KNEE: (960, 540), h.R_ANKLE: (1160, 340)}
        raw = [SimpleNamespace(x=0.5, y=0.5, z=0.0, visibility=0.9) for _ in range(33)]
        for j, (x, y) in px.items():
            raw[j] = SimpleNamespace(x=x / 1920, y=y / 1080, z=0.0, visibility=0.9)
        frame = h.drop_face(raw, width=1920, height=1080)
        self.assertAlmostEqual(h.frame_angle(frame, KNEE, 0.5), 90.0, places=6)
        skewed = h.drop_face(raw)
        self.assertNotAlmostEqual(h.frame_angle(skewed, KNEE, 0.5), 90.0, places=1)

    def test_no_criterion_uses_a_face_landmark(self) -> None:
        for spec in h.CRITERIA.values():
            self.assertFalse(set(spec["joints"]) & set(h.FACE_LANDMARKS))


class CantTellTests(unittest.TestCase):
    def test_missing_and_low_visibility_frames_count(self) -> None:
        missing = skeleton(90, KNEE)
        missing[KNEE[1]] = None
        frames = [
            skeleton(90, KNEE),
            skeleton(90, KNEE, visibility=0.2),
            missing,
            skeleton(100, KNEE),
        ]
        m = h.measure_clip(frames, "lunge_front_knee")
        self.assertEqual((m.frames, m.unusable_frames), (4, 2))
        self.assertAlmostEqual(m.value, 90.0)

    def test_clip_is_cant_tell_below_valid_fraction(self) -> None:
        frames = [skeleton(90, KNEE)] + [skeleton(90, KNEE, visibility=0.1)] * 3
        self.assertIsNone(h.measure_clip(frames, "lunge_front_knee").value)
        self.assertIsNone(h.measure_clip([], "lunge_front_knee").value)

    def test_report_counts_cant_tell_clips(self) -> None:
        good = h.ClipMeasure(90.0, 10, 1)
        blind = h.ClipMeasure(None, 10, 10)
        measures = {"a": {"lunge_front_knee": good}, "b": {"lunge_front_knee": blind}}
        matched = {"a": {"lunge_front_knee": True}, "b": {"lunge_front_knee": False}}
        r = next(r for r in h.build_reports(measures, matched) if r.criterion == "lunge_front_knee")
        self.assertEqual(
            (r.labelled_clips, r.cant_tell_clips, r.unusable_frames, r.frames), (2, 1, 11, 20)
        )


class SeparationTests(unittest.TestCase):
    def report(self, pass_angles: list[float], fail_angles: list[float]) -> h.CriterionReport:
        measures, matched = {}, {}
        for i, (angle, passed) in enumerate(
            [(a, True) for a in pass_angles] + [(a, False) for a in fail_angles]
        ):
            frames = [skeleton(angle, KNEE)] * 3
            measures[f"c{i}"] = {"lunge_front_knee": h.measure_clip(frames, "lunge_front_knee")}
            matched[f"c{i}"] = {"lunge_front_knee": passed}
        return next(
            r for r in h.build_reports(measures, matched) if r.criterion == "lunge_front_knee"
        )

    def test_clearly_separated_groups(self) -> None:
        r = self.report([88, 90, 92, 95], [140, 150, 155, 160])
        self.assertEqual(r.auc, 1.0)
        self.assertGreater(r.cohens_d, 3)
        self.assertIn("1.00", h.format_reports([r]))

    def test_overlapping_groups(self) -> None:
        r = self.report([100, 120, 140, 160], [105, 125, 135, 155])
        self.assertLess(r.auc, 0.65)
        self.assertLess(r.cohens_d, 0.5)


class LabelJoinTests(unittest.TestCase):
    def test_join_flags_both_sides(self) -> None:
        labels = h.read_labels(
            [
                {"clip": "kid01", "criterion": "lunge_front_knee", "label": "Pass"},
                {"clip": "kid02", "criterion": "grip_ready_elbow", "label": "fail"},
                {"clip": "kid03", "criterion": "grip_ready_elbow", "label": ""},
            ]
        )
        join = h.join_clips_and_labels(["kid01", "kid04"], labels)
        self.assertEqual(join.matched, {"kid01": {"lunge_front_knee": True}})
        self.assertEqual(join.clips_without_labels, ["kid04"])
        self.assertEqual(join.labels_without_clips, ["kid02"])

    def test_bad_rows_rejected(self) -> None:
        with self.assertRaises(ValueError):
            h.read_labels([{"clip": "k", "criterion": "smash_power", "label": "pass"}])
        with self.assertRaises(ValueError):
            h.read_labels([{"clip": "k", "criterion": "lunge_front_knee", "label": "maybe"}])

    def test_clips_folder_inside_repo_refused(self) -> None:
        with self.assertRaises(SystemExit):
            h.main(["--clips", str(DEV_SCRIPTS), "--labels", "unused.csv"])


class PrivacyTests(unittest.TestCase):
    BANNED = frozenset({
        "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp",
        "ftplib", "smtplib", "websocket", "websockets", "grpc", "anthropic", "openai",
        "google", "boto3", "firebase_admin", "pymongo",
    })  # fmt: skip

    def test_module_imports_no_network_client(self) -> None:
        tree = ast.parse(Path(h.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & self.BANNED, imported & self.BANNED)
        self.assertNotIn("mediapipe", sys.modules, "mediapipe must only load in the clip path")


if __name__ == "__main__":
    unittest.main()


class LungeDepthTests(unittest.TestCase):
    def test_back_leg_is_read_at_the_deepest_front_knee_frame(self) -> None:
        back = h.CRITERIA["lunge_back_leg"]["joints"]

        def frame(front_deg: float, back_deg: float) -> list:
            f = skeleton(front_deg, KNEE)
            b = skeleton(back_deg, back)
            for j in back:
                f[j] = b[j]
            return f

        # Standing (front 175, back 180) around a lunge (front 95, back 100):
        # a whole-clip max would report the standing 180.
        frames = [frame(175, 180), frame(95, 100), frame(175, 180)]
        self.assertAlmostEqual(h.measure_clip(frames, "lunge_back_leg").value, 100.0)
        extended = [frame(175, 180), frame(95, 170), frame(175, 180)]
        self.assertAlmostEqual(h.measure_clip(extended, "lunge_back_leg").value, 170.0)
