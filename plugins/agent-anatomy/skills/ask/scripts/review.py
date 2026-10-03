#!/usr/bin/env python3
"""Prepare a report's claims for independent review, and record the reviewer's verdicts.

Usage:
  review.py packet <report.json>                 Print every cited claim next to the code it cites.
  review.py record <report.json> <verdicts.json> Stamp the verdicts and write review.json beside the report.

A citation ties one factual claim to a line range at a pinned commit. The
reviewer reads the packet (and the repositories) and writes verdicts.json:

  {
    "reviewer": "who or what reviewed",
    "results": [ { "id": "c1", "verdict": "supported", "note": "" } ],
    "uncited": [ { "where": "deep_dives[0].how_it_works[2]", "text": "...", "note": "why it needs a citation" } ]
  }

verdict is one of: supported, partial, unsupported, unclear.
`record` binds each verdict to a hash of the claim it judged, so editing a
claim or its line range afterwards invalidates that verdict.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fetch import cache_path  # noqa: E402

MARKER = re.compile(r"\[\^([A-Za-z0-9_-]+)\]")
VERDICTS = {"supported", "partial", "unsupported", "unclear"}
CONTEXT = 8


def repo_dir(entry):
    return entry.get("local_path") or cache_path(entry["repo"])


def read_lines(root, commit, path):
    r = subprocess.run(["git", "-C", root, "show", f"{commit}:{path}"],
                       capture_output=True, text=True, errors="replace")
    return None if r.returncode else r.stdout.split("\n")


def citation_hash(cit, commit):
    blob = json.dumps([cit.get("claim"), cit.get("repo"), commit, cit.get("path"),
                       cit.get("start"), cit.get("end")], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def prose_fields(report):
    """Every piece of explanatory text, as (location, text), in a fixed order."""
    out = [("answer", report.get("answer", ""))]
    for i, r in enumerate(report.get("repos", [])):
        out.append((f"repos[{i}].summary", r.get("summary", "")))
    comp = report.get("comparison", {})
    for i, row in enumerate(comp.get("rows", [])):
        for j, cell in enumerate(row.get("cells", [])):
            out.append((f"comparison.rows[{i}].cells[{j}]", cell))
    for i, d in enumerate(report.get("deep_dives", [])):
        out.append((f"deep_dives[{i}].headline", d.get("headline", "")))
        for key in ("how_it_works", "gotchas", "searched"):
            for j, text in enumerate(d.get(key) or []):
                out.append((f"deep_dives[{i}].{key}[{j}]", text))
        for j, part in enumerate(d.get("key_parts") or []):
            out.append((f"deep_dives[{i}].key_parts[{j}].role", part.get("role", "")))
        for j, ex in enumerate(d.get("excerpts") or []):
            out.append((f"deep_dives[{i}].excerpts[{j}].note", ex.get("note", "")))
        if d.get("diagram"):
            out.append((f"deep_dives[{i}].diagram.caption", d["diagram"].get("caption", "")))
    for i, x in enumerate(report.get("differences") or []):
        out.append((f"differences[{i}]", f"{x.get('title', '')}. {x.get('detail', '')}"))
    for i, x in enumerate(report.get("build_your_own") or []):
        out.append((f"build_your_own[{i}]", x))
    return [(where, text) for where, text in out if text]


def prose_hash(report):
    blob = json.dumps(prose_fields(report), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def commits(report):
    return {r["id"]: r for r in report.get("repos", [])}


def packet(report):
    by_id = commits(report)
    cits = report.get("citations") or {}
    print("# REVIEW PACKET")
    print(f"Question: {report['meta']['question']}")
    print(f"{len(cits)} cited claims. Repositories on disk:")
    for rid, r in by_id.items():
        print(f"  {rid}: {repo_dir(r)}  (commit {r['commit'][:12]})")
    print("\n# CLAIMS\n")
    for cid, cit in cits.items():
        entry = by_id.get(cit.get("repo"))
        print(f"## {cid}")
        print(f"CLAIM: {cit.get('claim')}")
        print(f"CITES: {cit.get('repo')} {cit.get('path')}:{cit.get('start')}-{cit.get('end')}")
        lines = read_lines(repo_dir(entry), entry["commit"], cit["path"]) if entry else None
        if lines is None:
            print("CODE: <file not found at the pinned commit>\n")
            continue
        lo = max(1, cit["start"] - CONTEXT)
        hi = min(len(lines), cit["end"] + CONTEXT)
        print("CODE (lines marked > are the cited range; others are context):")
        for n in range(lo, hi + 1):
            mark = ">" if cit["start"] <= n <= cit["end"] else " "
            print(f"{mark}{n:>6}  {lines[n - 1]}")
        print()
    print("# PROSE (check for factual statements that carry no [^id] marker)\n")
    for where, text in prose_fields(report):
        print(f"- {where}: {text}")


def record(report, report_path, verdicts):
    by_id = commits(report)
    cits = report.get("citations") or {}
    results, problems = [], []
    seen = set()
    for item in verdicts.get("results", []):
        cid = item.get("id")
        if cid not in cits:
            problems.append(f"verdict for unknown citation '{cid}'")
            continue
        if item.get("verdict") not in VERDICTS:
            problems.append(f"{cid}: verdict must be one of {sorted(VERDICTS)}")
            continue
        seen.add(cid)
        entry = by_id.get(cits[cid].get("repo"), {})
        results.append({"id": cid, "verdict": item["verdict"], "note": item.get("note", ""),
                        "hash": citation_hash(cits[cid], entry.get("commit"))})
    missing = [c for c in cits if c not in seen]
    if missing:
        problems.append(f"no verdict for: {', '.join(missing)}")
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        sys.exit(1)
    review = {
        "reviewer": verdicts.get("reviewer", "unspecified"),
        "reviewed_at": verdicts.get("reviewed_at", ""),
        "prose_hash": prose_hash(report),
        "results": results,
        "uncited": verdicts.get("uncited", []),
    }
    out = os.path.join(os.path.dirname(os.path.abspath(report_path)), "review.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(review, f, indent=1, ensure_ascii=False)
    tally = {}
    for r in results:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print(f"wrote {out}: {tally}, {len(review['uncited'])} uncited statements flagged")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("packet", "record"):
        sys.exit(__doc__)
    with open(sys.argv[2], encoding="utf-8") as f:
        report = json.load(f)
    if sys.argv[1] == "packet":
        packet(report)
    else:
        if len(sys.argv) != 4:
            sys.exit(__doc__)
        with open(sys.argv[3], encoding="utf-8") as f:
            verdicts = json.load(f)
        record(report, sys.argv[2], verdicts)


if __name__ == "__main__":
    main()
