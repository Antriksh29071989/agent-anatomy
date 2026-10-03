# Topics

Questions this skill is built for, with the names each technique goes by in code. Use the search terms as a starting point: try all of them, case-insensitively, then confirm by reading.

## Menu

Show this list when the user has not asked a question yet.

| Topic | Example question |
|---|---|
| Context compression | How do they shrink the conversation when it nears the context limit, and what is kept? |
| Loop detection | How do they notice the agent is stuck repeating itself, and what happens then? |
| Memory | How is long-term memory stored, and when is it read back into the prompt? |
| Tool errors and retries | What happens when a tool call fails or returns malformed arguments? |
| Tool output handling | How are very large tool results truncated or summarised before the model sees them? |
| Prompt assembly | How is the system prompt built, and what goes into it on every turn? |
| Sub-agents | How does one agent hand work to another, and what context does the child get? |
| Approvals and sandboxing | How do they decide a tool call needs permission, and how is execution contained? |
| Stopping conditions | How does the loop know the task is finished, and what are the hard limits? |
| Model fallback and retries | What happens on rate limits, timeouts and malformed model output? |
| Prompt caching | How do they keep the prompt prefix stable so the cache is hit? |
| Evals | How do they test agent behaviour, and what does a test case look like? |
| Checkpointing and resume | How is a run saved so it can continue after a crash or restart? |
| Streaming and cancellation | How does a user interrupt a running turn, and what state is kept? |

## Search terms

**Context compression**
`compress`, `compact`, `condense`, `summar`, `trim`, `prune`, `truncate history`, `context window`, `token limit`, `overflow`, `context manager`, `sliding window`, `mask`

**Loop detection**
`loop detect`, `stuck`, `repeat`, `repetition`, `identical`, `consecutive`, `no progress`, `unproductive`, `doom loop`, `recursion limit`, `max turns`, `max iterations`, `max steps`

**Memory**
`memory`, `remember`, `recall`, `long term`, `persist`, `store`, `checkpoint`, `notes`, `scratchpad`, `knowledge`, instruction-file names (`AGENTS.md`, `GEMINI.md`, `CLAUDE.md`)

**Tool errors and retries**
`tool error`, `ToolError`, `is_error`, `invalid arguments`, `malformed`, `validation`, `retry`, `backoff`, `repair`, `schema`

**Tool output handling**
`truncate`, `max output`, `output limit`, `too large`, `head`, `tail`, `summarize output`, `mask`, `distill`, `artifact`

**Prompt assembly**
`system prompt`, `system instruction`, `build prompt`, `prompt template`, `instructions`, `preamble`, `environment context`

**Sub-agents**
`subagent`, `sub_agent`, `delegate`, `handoff`, `spawn`, `task tool`, `child`, `orchestrat`, `worker`

**Approvals and sandboxing**
`approval`, `confirm`, `permission`, `policy`, `allowlist`, `trust`, `sandbox`, `seatbelt`, `bwrap`, `landlock`, `container`, `yolo`, `auto approve`

**Stopping conditions**
`finish`, `done`, `complete task`, `stop reason`, `end turn`, `max turns`, `max iterations`, `budget`, `needs follow up`

**Model fallback and retries**
`fallback`, `retry`, `rate limit`, `429`, `overloaded`, `backoff`, `quota`, `alternate model`, `invalid stream`

**Prompt caching**
`cache_control`, `prompt cache`, `cached tokens`, `prefix`, `cache key`, `stable prefix`

**Evals**
`eval`, `benchmark`, `golden`, `behavioral`, `rubric`, `grader`, `judge`, `trajectory`, `swe-bench`, directories named `evals`, `evaluation`, `benchmarks`

**Checkpointing and resume**
`checkpoint`, `snapshot`, `resume`, `restore`, `rollout`, `session store`, `persist`, `replay`, `rewind`

**Streaming and cancellation**
`cancel`, `abort`, `interrupt`, `AbortSignal`, `CancellationToken`, `stream`, `partial`

## Where things usually live

- The agent loop is the best starting point for almost every topic: find the function that sends a request to the model and runs tools, then look at what it calls before and after.
- Thresholds are usually module-level constants or a config class near the implementation.
- Helper model calls (summarisers, judges, classifiers) usually have their own prompt string close by; the prompt tells you what the authors intended.
- Tests named after the feature state the intended behaviour and edge cases.
