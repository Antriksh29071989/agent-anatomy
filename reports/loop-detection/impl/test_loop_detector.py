"""Tests for loop_detector.py. Run: python3 -m unittest -v"""
import unittest

from loop_detector import LoopDetector, call_key


def feed(detector, calls):
    """Record (name, args, result[, is_error]) calls and return the verdict actions."""
    return [detector.record(*c).action for c in calls]


class ToolCallCycles(unittest.TestCase):
    def test_distinct_calls_never_trigger(self):
        d = LoopDetector()
        actions = feed(d, [("read", {"path": f"f{i}"}, f"content {i}") for i in range(30)])
        self.assertEqual(set(actions), {"continue"})

    def test_fifth_identical_call_warns(self):
        d = LoopDetector()
        # Results differ, so only the call-cycle rule can fire.
        actions = feed(d, [("ls", {"dir": "."}, f"out {i}") for i in range(5)])
        self.assertEqual(actions, ["continue"] * 4 + ["warn"])

    def test_second_detection_stops(self):
        d = LoopDetector()
        actions = feed(d, [("ls", {"dir": "."}, f"out {i}") for i in range(6)])
        self.assertEqual(actions[-2:], ["warn", "stop"])

    def test_alternating_pair_is_a_cycle_of_length_two(self):
        d = LoopDetector()
        calls = [("a", {}, f"r{i}") if i % 2 == 0 else ("b", {}, f"r{i}") for i in range(10)]
        actions = feed(d, calls)
        self.assertEqual(actions[:9], ["continue"] * 9)
        self.assertEqual(actions[9], "warn")

    def test_one_changed_argument_is_a_different_call(self):
        self.assertNotEqual(call_key("grep", {"q": "foo"}), call_key("grep", {"q": "foo "}))
        d = LoopDetector()
        actions = feed(d, [("grep", {"q": f"foo{i}"}, "none") for i in range(3)])
        self.assertEqual(set(actions), {"continue"})

    def test_new_prompt_resets_everything(self):
        d = LoopDetector()
        feed(d, [("ls", {}, f"out {i}") for i in range(5)])
        d.reset()
        self.assertEqual(d.record("ls", {}, "out").action, "continue")
        self.assertEqual(d.detections, 0)


class RepeatedOutcomes(unittest.TestCase):
    def test_four_identical_call_and_result_pairs_stop(self):
        d = LoopDetector()
        actions = feed(d, [("status", {}, "pending")] * 4)
        self.assertEqual(actions, ["continue"] * 3 + ["stop"])

    def test_same_call_with_changing_result_is_not_stuck_at_four(self):
        d = LoopDetector()
        actions = feed(d, [("status", {}, f"{i * 25}%") for i in range(4)])
        self.assertEqual(set(actions), {"continue"})

    def test_an_error_and_a_success_with_the_same_text_are_different_outcomes(self):
        d = LoopDetector()
        actions = feed(d, [("t", {}, "x"), ("t", {}, "x"), ("t", {}, "x", True), ("t", {}, "x", True)])
        self.assertEqual(set(actions), {"continue"})

    def test_third_error_nudges_and_fourth_stops(self):
        d = LoopDetector()
        actions = feed(d, [("write", {"p": "/x"}, f"denied {i}", True) for i in range(4)])
        self.assertEqual(actions, ["continue", "continue", "warn", "stop"])

    def test_nudge_names_the_tool_and_the_error(self):
        d = LoopDetector()
        for _ in range(2):
            d.record("write", {"p": "/x"}, "permission denied", True)
        verdict = d.record("write", {"p": "/x"}, "permission denied", True)
        self.assertIn("`write`", verdict.message)
        self.assertIn("permission denied", verdict.message)

    def test_a_success_breaks_the_error_streak(self):
        d = LoopDetector()
        d.record("write", {"p": "/x"}, "denied", True)
        d.record("write", {"p": "/x"}, "denied", True)
        d.record("write", {"p": "/x"}, "ok", False)
        self.assertEqual(d.error_streak(), 0)


if __name__ == "__main__":
    unittest.main()
