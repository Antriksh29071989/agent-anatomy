# Report file

`report.json` holds the explanation. `scripts/build.py` validates it, reads every code excerpt from the cached repository at the pinned commit, and renders the page.

## Text rules

- Plain text only; HTML is shown literally.
- Backticks render as inline code. Use them for identifiers, file names and literal values.
- No code in the report. Excerpts are line ranges; the build inserts the code.

## Structure

```json
{
  "meta": {
    "question": "The question as a full sentence. It is the page headline.",
    "title": "Short topic name, at most 40 characters",
    "slug": "short-topic-name",
    "analysed_at": "YYYY-MM-DD",
    "hook": "The most striking contrast, as one line of at most 120 characters.",
    "site_url": "https://<user>.github.io/<repo>/reports/short-topic-name/"
  },
  "answer": "The direct answer in two to four sentences, naming each repository's approach.",
  "repos": [
    {
      "id": "gemini-cli",
      "repo": "google-gemini/gemini-cli",
      "commit": "full sha printed by fetch.py",
      "commit_date": "YYYY-MM-DD",
      "kind": "product",
      "language": "TypeScript",
      "license": "Apache-2.0",
      "what": "One-line description of the project",
      "verdict": "implements",
      "summary": "One or two sentences: what this repository does about the question."
    }
  ],
  "comparison": {
    "dimensions": ["Approach", "What triggers it", "Thresholds", "Response"],
    "rows": [
      { "repo": "gemini-cli", "cells": ["...", "...", "...", "..."] }
    ]
  },
  "deep_dives": [
    {
      "repo": "gemini-cli",
      "headline": "The mechanism in a few words",
      "how_it_works": [
        "Paragraph one: what triggers it and what it reads.",
        "Paragraph two: how it decides.",
        "Paragraph three: what it does and what the caller does next."
      ],
      "diagram": {
        "caption": "One sentence saying what to notice.",
        "mermaid": "flowchart TB\n  a[\"Step one\"]:::external --> b[\"Step two\"]:::system\n"
      },
      "key_parts": [
        { "name": "ClassOrFunction", "path": "path/in/repo.ts", "role": "What it does" }
      ],
      "excerpts": [
        {
          "path": "path/in/repo.ts",
          "start": 29,
          "end": 66,
          "expect": "SOME_CONSTANT_NAME",
          "title": "What this excerpt shows",
          "note": "Optional: one sentence on what to notice."
        }
      ],
      "gotchas": [ "A limitation or surprise a builder should know." ],
      "searched": [ "For delegates/absent verdicts: what you searched for and where." ]
    }
  ],
  "differences": [
    { "title": "Short claim", "detail": "The difference and, where the code shows it, the reason." }
  ],
  "build_your_own": [ "An ordered, practical point for someone writing their own agent." ],
  "method": {
    "scope": "What was read in each repository.",
    "limits": [ "What was not examined, and how sure each 'not found' is." ]
  }
}
```

For a local repository that is not on GitHub, give `"local_path": "/abs/path"` in place of `"repo"`; the page then shows file paths without links.

## Rules the build enforces

| Field | Rule |
|---|---|
| `meta.question`, `meta.title`, `meta.analysed_at`, `answer` | Required; `title` at most 40 characters |
| `meta.hook` | Optional; at most 120 characters |
| `meta.site_url` | Optional; must start with `https://` |
| `repos[].verdict` | `implements`, `partial`, `delegates` or `absent` |
| `repos[].kind` | `product`, `framework` or `unknown` |
| `repos[].commit` | Must exist in the cached repository |
| `comparison.rows` | Exactly one row per repository; as many cells as dimensions |
| `deep_dives` | One per repository |
| `key_parts[].path` | Must exist at the pinned commit |
| `excerpts` | At most 5 per repository; required (at least one) when the verdict is `implements` or `partial` |
| `excerpts[].start`, `end` | Line numbers, at most 45 lines, within the file |
| `excerpts[].expect` | Required; must appear in the range |
| `excerpts[].code` | Not allowed |
| `differences` | 2 to 6 |
| `build_your_own` | 3 to 7 |

## Diagrams

Mermaid source in a JSON string (`\n` for newlines, `\"` for quotes). Accepted: `flowchart`, `sequenceDiagram`, `stateDiagram`.

Use `flowchart TB` for a mechanism with decisions. The template supplies colours; attach one class to each node and do not write `classDef` or `style` lines:

| Class | Use for |
|---|---|
| `external` | Inputs and things outside the mechanism |
| `system` | The main class or function |
| `component` | Steps and checks inside it |
| `queue` | Intermediate states and signals |
| `store` | Outcomes and terminal states |

Rules that prevent render failures:

- Every label in double quotes; no double quotes inside a label.
- At most two lines per node: `"Name<br/>detail"`. `<br/>` is the only markup allowed.
- Node ids are plain identifiers; never `end`, `graph`, `subgraph`, `class` or `style`.
- Decisions: `id{"Question?"}:::component`.
- Label edges that are conditional: `a -->|"first time"| b`. Use `-.->` for optional paths.
- No `(`, `)`, `{`, `}`, `#` or `;` inside edge labels.
- Keep it under about 12 nodes.
