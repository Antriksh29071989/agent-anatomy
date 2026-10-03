"""Loop detection for an agent loop: a small reference implementation.

It follows two production designs, described with source citations in the
report this file belongs to:

  * Gemini CLI: hash every tool call, look for a repeating cycle, warn the
    model on the first detection and stop on the second.
  * OpenHands: compare call-and-result pairs, nudge when the same call keeps
    erroring, and mark the run stuck when a pattern matches.

Written from scratch for teaching. It is not code from either project.
"""
import hashlib
import json
from dataclasses import dataclass, field

TOOL_CALL_LOOP_THRESHOLD = 5   # a cycle must repeat this many times
MAX_CYCLE_LENGTH = 5           # cycles of 1 to 5 calls are checked
SAME_RESULT_THRESHOLD = 4      # identical call-and-result pairs in a row
ERROR_THRESHOLD = 3            # same call erroring: nudge at 3, stuck above 3


@dataclass
class Verdict:
    action: str            # "continue", "warn" (send `message` to the model) or "stop"
    message: str = ""


def call_key(name, args):
    """An exact fingerprint of one tool call: its name and its JSON arguments."""
    return hashlib.sha256(f"{name}:{json.dumps(args)}".encode()).hexdigest()


@dataclass
class LoopDetector:
    calls: list = field(default_factory=list)   # call fingerprints, oldest first
    steps: list = field(default_factory=list)   # (fingerprint, result, is_error), oldest first
    detections: int = 0

    def reset(self):
        """Call when the user sends a new prompt: old history no longer counts."""
        self.calls, self.steps, self.detections = [], [], 0

    def has_cycle(self):
        """True if the last calls are one cycle of length 1..5 repeated 5 times."""
        n = len(self.calls)
        for k in range(1, MAX_CYCLE_LENGTH + 1):
            need = k * TOOL_CALL_LOOP_THRESHOLD
            if n >= need:
                cycle = self.calls[-k:]
                if all(self.calls[n - need + i] == cycle[i % k] for i in range(need)):
                    return True
        return False

    def same_result_repeated(self):
        """True if the last 4 steps are the same call returning the same result."""
        last = self.steps[-SAME_RESULT_THRESHOLD:]
        return len(last) == SAME_RESULT_THRESHOLD and all(
            step == last[0] for step in last   # same call, same result, same kind of outcome
        )

    def error_streak(self):
        """How many times in a row the latest call has ended in an error."""
        streak = 0
        for key, _result, is_error in reversed(self.steps):
            if key != self.steps[-1][0] or not is_error:
                break
            streak += 1
        return streak

    def record(self, name, args, result, is_error=False):
        """Record one finished tool call and say what the agent loop should do."""
        key = call_key(name, args)
        keep = MAX_CYCLE_LENGTH * TOOL_CALL_LOOP_THRESHOLD
        self.calls = (self.calls + [key])[-keep:]
        self.steps.append((key, result, is_error))

        streak = self.error_streak()
        if streak == ERROR_THRESHOLD:
            return Verdict("warn", (
                f"You've called `{name}` with the same arguments {streak} times in a row "
                f"and it failed each time: {result}. Correct the arguments or try a "
                "different approach."))
        if streak > ERROR_THRESHOLD or self.same_result_repeated():
            return Verdict("stop", "Stuck: the same call keeps producing the same outcome.")

        if self.has_cycle():
            self.detections += 1
            if self.detections > 1:
                return Verdict("stop", "Loop detected again after a warning.")
            return Verdict("warn", (
                f"System: Potential loop detected. Repeated tool call: {name} with "
                f"arguments {json.dumps(args)}. Take a step back and confirm you're "
                "making forward progress."))
        return Verdict("continue")
