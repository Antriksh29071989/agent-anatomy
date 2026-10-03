"""Chat history compression for an agent: a small reference implementation.

It follows the design of Gemini CLI's chat compression, described with source
citations in the report this file belongs to: check a threshold, trim old tool
outputs, split at a safe boundary, have a model write a state snapshot and then
critique it, and reject a result that came out larger.

Written from scratch for teaching. It is not code from that project.

A history is a list of messages: {"role": "user" | "model", "parts": [...]},
where a part is {"text": str}, {"function_call": {...}} or
{"function_response": {"name": str, "output": str}}.
"""
import json

DEFAULT_COMPRESSION_TOKEN_THRESHOLD = 0.5      # compress at this fraction of the token limit
COMPRESSION_PRESERVE_THRESHOLD = 0.3           # keep this fraction of recent history verbatim
FUNCTION_RESPONSE_TOKEN_BUDGET = 50_000        # tool output kept in full, newest first
ACK = "Got it. Thanks for the additional context!"


def estimate_tokens(history):
    """A rough count: about four characters per token."""
    return sum(len(json.dumps(m["parts"])) for m in history) // 4


def truncate_output(text, max_chars):
    """Leave short output alone; otherwise keep the first 20% and last 80% of the limit."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = int(max_chars * 0.2)
    tail = max_chars - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n\n... [{omitted} characters omitted] ...\n\n{text[-tail:]}"


def truncate_history_to_budget(history, max_chars):
    """Walk newest to oldest; once tool output exceeds the budget, shorten older ones."""
    used, out = 0, []
    for message in reversed(history):
        parts = []
        for part in reversed(message["parts"]):
            response = part.get("function_response")
            if response:
                tokens = len(response["output"]) // 4
                if used + tokens > FUNCTION_RESPONSE_TOKEN_BUDGET:
                    short = truncate_output(response["output"], max_chars)
                    part = {"function_response": {**response, "output": short}}
                    tokens = len(short) // 4
                used += tokens
            parts.insert(0, part)
        out.insert(0, {**message, "parts": parts})
    return out


def find_split_point(history, fraction):
    """Index of the oldest message to keep. Splits only where a tool call is not cut from its result."""
    sizes = [len(json.dumps(m)) for m in history]
    target = sum(sizes) * fraction
    last_split, seen = 0, 0
    for i, message in enumerate(history):
        is_plain_user = message["role"] == "user" and not any(
            "function_response" in p for p in message["parts"])
        if is_plain_user:
            if seen >= target:
                return i
            last_split = i
        seen += sizes[i]
    last = history[-1]
    if last["role"] == "model" and not any("function_call" in p for p in last["parts"]):
        return len(history)          # safe to compress everything
    return last_split


def compress(history, token_limit, summarise, *, last_prompt_tokens=0, force=False,
             failed_before=False, threshold=DEFAULT_COMPRESSION_TOKEN_THRESHOLD,
             max_chars=40_000):
    """Return (new_history or None, status). `summarise(messages, instruction)` calls a model."""
    if not history:
        return None, "NOOP"
    original = last_prompt_tokens if last_prompt_tokens > 0 else estimate_tokens(history)
    if not force and original < threshold * token_limit:
        return None, "NOOP"

    truncated = truncate_history_to_budget(history, max_chars)
    if failed_before and not force:          # summarising failed earlier: truncate only
        if estimate_tokens(truncated) < original:
            return truncated, "CONTENT_TRUNCATED"
        return None, "NOOP"

    split = find_split_point(truncated, 1 - COMPRESSION_PRESERVE_THRESHOLD)
    to_compress, to_keep = truncated[:split], truncated[split:]
    if not to_compress:
        return None, "NOOP"

    has_snapshot = any("<state_snapshot>" in p.get("text", "")
                       for m in to_compress for p in m["parts"])
    instruction = ("A previous <state_snapshot> exists in the history. Integrate everything "
                   "still relevant from it into the new one."
                   if has_snapshot else "Generate a new <state_snapshot> from this history.")
    instruction += "\n\nFirst, reason in your scratchpad. Then, generate the updated <state_snapshot>."
    summary = summarise(to_compress, instruction) or ""
    checked = summarise(
        to_compress + [{"role": "model", "parts": [{"text": summary}]}],
        "Critically evaluate the <state_snapshot> you just generated. If anything is missing "
        "or could be more precise, generate a final, improved <state_snapshot>. Otherwise, "
        "repeat the exact same <state_snapshot> again.")
    final = ((checked or "").strip() or summary).strip()
    if not final:
        return None, "COMPRESSION_FAILED_EMPTY_SUMMARY"

    new_history = [{"role": "user", "parts": [{"text": final}]},
                   {"role": "model", "parts": [{"text": ACK}]}] + to_keep
    if estimate_tokens(new_history) > original:
        return None, "COMPRESSION_FAILED_INFLATED_TOKEN_COUNT"
    return new_history, "COMPRESSED"


class Chat:
    """The caller's side: applies the result and remembers a failed attempt."""

    def __init__(self, token_limit, summarise):
        self.history, self.token_limit, self.summarise = [], token_limit, summarise
        self.failed = False
        self.last_prompt_tokens = 0     # set this from your model API's usage report

    def try_compress(self, force=False):
        new_history, status = compress(self.history, self.token_limit, self.summarise,
                                       last_prompt_tokens=self.last_prompt_tokens,
                                       force=force, failed_before=self.failed)
        if status == "COMPRESSION_FAILED_INFLATED_TOKEN_COUNT":
            self.failed = self.failed or not force
        elif status == "COMPRESSED":
            self.history, self.failed = new_history, False   # a new chat clears the flag
        elif status == "CONTENT_TRUNCATED":
            self.history = new_history                        # the flag stays set
        if new_history is not None:
            self.last_prompt_tokens = 0     # the old count no longer describes the history
        return status
