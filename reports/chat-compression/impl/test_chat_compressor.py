"""Tests for chat_compressor.py. Run: python3 -m unittest -v"""
import unittest

from chat_compressor import (ACK, Chat, compress, estimate_tokens, find_split_point,
                             truncate_history_to_budget, truncate_output)


def user(text):
    return {"role": "user", "parts": [{"text": text}]}


def model(text):
    return {"role": "model", "parts": [{"text": text}]}


def tool_call(name):
    return {"role": "model", "parts": [{"function_call": {"name": name}}]}


def tool_result(name, output):
    return {"role": "user", "parts": [{"function_response": {"name": name, "output": output}}]}


def conversation(turns, size=400):
    out = []
    for i in range(turns):
        out += [user(f"question {i} " + "x" * size), model(f"answer {i} " + "y" * size)]
    return out


class FakeModel:
    """Stands in for the summariser and records what it was asked."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages, instruction):
        self.calls.append((messages, instruction))
        return self.replies.pop(0)


class Trigger(unittest.TestCase):
    def test_below_threshold_does_nothing_and_calls_no_model(self):
        fake = FakeModel([])
        result, status = compress(conversation(4), 1_000_000, fake)
        self.assertEqual((result, status), (None, "NOOP"))
        self.assertEqual(fake.calls, [])

    def test_exactly_half_the_limit_compresses_and_just_under_does_not(self):
        history = conversation(10)
        tokens = estimate_tokens(history)
        fake = FakeModel(["<state_snapshot>s</state_snapshot>", "<state_snapshot>better</state_snapshot>"])
        self.assertEqual(compress(history, tokens * 2 + 2, fake)[1], "NOOP")
        self.assertEqual(compress(history, tokens * 2, fake)[1], "COMPRESSED")

    def test_force_skips_the_threshold(self):
        fake = FakeModel(["<state_snapshot>s</state_snapshot>", ""])
        _, status = compress(conversation(10), 10_000_000, fake, force=True)
        self.assertEqual(status, "COMPRESSED")


class SplitPoint(unittest.TestCase):
    def test_keeps_roughly_the_newest_thirty_percent(self):
        history = conversation(10)
        split = find_split_point(history, 0.7)
        self.assertEqual(history[split]["role"], "user")
        self.assertIn(split, (14, 16))

    def test_never_splits_between_a_tool_call_and_its_result(self):
        history = [user("go"), tool_call("ls"), tool_result("ls", "a" * 5000), model("done")]
        split = find_split_point(history, 0.7)
        self.assertIn(split, (0, len(history)))   # never index 2, the tool result

    def test_does_not_compress_everything_while_a_tool_call_is_pending(self):
        history = [user("go"), tool_call("ls")]
        self.assertEqual(find_split_point(history, 0.7), 0)


class ToolOutputBudget(unittest.TestCase):
    def test_short_output_is_left_alone(self):
        self.assertEqual(truncate_output("abc", 10), "abc")

    def test_long_output_keeps_first_20_and_last_80_percent(self):
        text = "H" * 50 + "M" * 900 + "T" * 50
        short = truncate_output(text, 100)
        self.assertTrue(short.startswith("H" * 20))
        self.assertTrue(short.endswith("M" * 30 + "T" * 50))
        self.assertIn("900 characters omitted", short)

    def test_newest_outputs_survive_and_older_ones_are_shortened(self):
        big = "z" * 150_000                      # about 37,500 tokens each
        history = [tool_result("old", big), tool_result("new", big)]
        out = truncate_history_to_budget(history, max_chars=1000)
        self.assertEqual(out[1]["parts"][0]["function_response"]["output"], big)
        self.assertLess(len(out[0]["parts"][0]["function_response"]["output"]), 1200)


class Snapshot(unittest.TestCase):
    def test_two_model_calls_and_the_second_answer_wins(self):
        fake = FakeModel(["first", "second"])
        result, _ = compress(conversation(10), 1000, fake, last_prompt_tokens=900)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("Critically evaluate", fake.calls[1][1])
        self.assertEqual(result[0]["parts"][0]["text"], "second")
        self.assertEqual(result[1]["parts"][0]["text"], ACK)

    def test_the_check_is_told_to_repeat_the_snapshot_when_nothing_is_missing(self):
        fake = FakeModel(["first", "second"])
        compress(conversation(10), 1000, fake, last_prompt_tokens=900)
        self.assertIn("repeat the exact same <state_snapshot>", fake.calls[1][1])

    def test_first_summary_is_used_when_the_check_returns_nothing(self):
        fake = FakeModel(["first", ""])
        result, _ = compress(conversation(10), 1000, fake, last_prompt_tokens=900)
        self.assertEqual(result[0]["parts"][0]["text"], "first")

    def test_an_earlier_snapshot_is_integrated(self):
        history = [user("<state_snapshot>old</state_snapshot>"), model("ok")] + conversation(10)
        fake = FakeModel(["s", "s2"])
        compress(history, 1000, fake, last_prompt_tokens=900)
        self.assertIn("previous <state_snapshot> exists", fake.calls[0][1])

    def test_empty_summary_changes_nothing(self):
        fake = FakeModel(["", ""])
        result, status = compress(conversation(10), 1000, fake, last_prompt_tokens=900)
        self.assertEqual((result, status), (None, "COMPRESSION_FAILED_EMPTY_SUMMARY"))


class SizeGuard(unittest.TestCase):
    def test_a_larger_result_is_rejected(self):
        fake = FakeModel(["s" * 100_000, ""])
        result, status = compress(conversation(10), 1000, fake, last_prompt_tokens=900)
        self.assertEqual((result, status), (None, "COMPRESSION_FAILED_INFLATED_TOKEN_COUNT"))

    def test_after_a_failure_automatic_attempts_do_not_call_the_model(self):
        fake = FakeModel(["s" * 100_000, ""])
        chat = Chat(token_limit=100, summarise=fake)
        chat.history = conversation(10)
        self.assertEqual(chat.try_compress(), "COMPRESSION_FAILED_INFLATED_TOKEN_COUNT")
        self.assertTrue(chat.failed)
        self.assertEqual(chat.try_compress(), "NOOP")          # nothing to truncate, no model call
        self.assertEqual(len(fake.calls), 2)

    def test_a_stale_token_count_does_not_trigger_a_second_compression(self):
        fake = FakeModel(["short", ""])
        chat = Chat(token_limit=4000, summarise=fake)
        chat.history = conversation(10)
        chat.last_prompt_tokens = 3900          # reported by the model API before compressing
        self.assertEqual(chat.try_compress(), "COMPRESSED")
        self.assertEqual(chat.last_prompt_tokens, 0)
        self.assertEqual(chat.try_compress(), "NOOP")
        self.assertEqual(len(fake.calls), 2)

    def test_a_forced_failure_does_not_set_the_flag(self):
        fake = FakeModel(["s" * 100_000, ""])
        chat = Chat(token_limit=10_000_000, summarise=fake)
        chat.history = conversation(10)
        chat.try_compress(force=True)
        self.assertFalse(chat.failed)

    def test_a_forced_attempt_still_summarises_after_a_failure(self):
        fake = FakeModel(["s" * 100_000, "", "short", ""])
        chat = Chat(token_limit=100, summarise=fake)
        chat.history = conversation(10)
        chat.try_compress()
        self.assertEqual(chat.try_compress(force=True), "COMPRESSED")
        self.assertFalse(chat.failed)


if __name__ == "__main__":
    unittest.main()
