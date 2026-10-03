#!/usr/bin/env python3
"""Validate an Agent Anatomy report, pull its code excerpts from the repositories, and render it.

Usage: build.py [--draft] <report.json> <output.html>

The report never contains code. Each excerpt names a file and a line range;
this script reads those lines from the cached repository at the pinned commit
and embeds them, so the page cannot misquote the source.

Every factual statement carries a [^id] marker tied to a citation: one claim
and the lines that support it. The build checks each citation against the
repository, and refuses to publish unless review.json (written by review.py
from an independent reviewer's verdicts) marks every claim as supported.
--draft skips the review requirement and stamps the page as unreviewed.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")
TEMPLATE = os.path.join(ASSETS, "template.html")
CARD_TEMPLATE = os.path.join(ASSETS, "card-template.html")
CARD_SIZE = (1200, 630)
VERDICTS = {"implements", "partial", "delegates", "absent"}
KINDS = {"product", "framework", "unknown"}
MAX_EXCERPT_LINES = 45
MAX_EXCERPTS_PER_REPO = 5
MAX_CITATION_LINES = 30
MAX_IMPL_LINES = 200
DIAGRAM_KINDS = ("flowchart", "graph", "sequenceDiagram", "stateDiagram")
BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
)

sys.path.insert(0, HERE)
from fetch import cache_path  # noqa: E402
from review import (MARKER, citation_hash, impl_dir, impl_lines, mirror_hash,  # noqa: E402
                    prose_fields, prose_hash)


def git(path, *args):
    return subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, errors="replace")


def repo_dir(entry):
    return entry.get("local_path") or cache_path(entry["repo"])


def read_lines(root, commit, path):
    """File content at the pinned commit, as a list of lines, or None."""
    r = git(root, "show", f"{commit}:{path}")
    if r.returncode:
        return None
    return r.stdout.split("\n")


def check(report, report_path="report.json"):
    errors, warnings = [], []

    def need(obj, key, kind, where):
        v = obj.get(key) if isinstance(obj, dict) else None
        if not isinstance(v, kind) or (isinstance(v, (str, list)) and not v):
            errors.append(f"{where}.{key}: required {kind.__name__}")
            return None
        return v

    meta = need(report, "meta", dict, "report") or {}
    for k in ("question", "title", "analysed_at"):
        need(meta, k, str, "meta")
    if len(meta.get("title") or "") > 40:
        errors.append("meta.title: at most 40 characters (it is the headline on the share card)")
    hook = meta.get("hook")
    if hook is not None and (not isinstance(hook, str) or len(hook) > 120):
        errors.append("meta.hook: optional string of at most 120 characters")
    site = meta.get("site_url")
    if site is not None and not (isinstance(site, str) and site.startswith("https://")):
        errors.append("meta.site_url: optional, must start with https://")
    elif not site:
        warnings.append("meta.site_url not set: link previews need the page's public URL to find the card image")
    need(report, "answer", str, "report")

    repos = need(report, "repos", list, "report") or []
    by_id = {}
    for i, r in enumerate(repos):
        w = f"repos[{i}]"
        rid = need(r, "id", str, w)
        need(r, "commit", str, w)
        need(r, "summary", str, w)
        if not r.get("repo") and not r.get("local_path"):
            errors.append(f"{w}: needs 'repo' (owner/name) or 'local_path'")
        if r.get("verdict") not in VERDICTS:
            errors.append(f"{w}.verdict: one of {sorted(VERDICTS)}")
        if r.get("kind") not in KINDS:
            errors.append(f"{w}.kind: one of {sorted(KINDS)}")
        if rid:
            by_id[rid] = r
        if rid and r.get("commit") and (r.get("repo") or r.get("local_path")):
            root = repo_dir(r)
            if not os.path.isdir(root):
                errors.append(f"{w}: repository not found at {root}; run fetch.py first")
            elif git(root, "cat-file", "-e", f"{r['commit']}^{{commit}}").returncode:
                errors.append(f"{w}.commit: {r['commit'][:12]} is not in the cached repository; "
                              "use the commit printed by fetch.py")
    if len(repos) < 1:
        errors.append("repos: at least one")

    comp = need(report, "comparison", dict, "report") or {}
    dims = need(comp, "dimensions", list, "comparison") or []
    rows = need(comp, "rows", list, "comparison") or []
    for i, row in enumerate(rows):
        if row.get("repo") not in by_id:
            errors.append(f"comparison.rows[{i}].repo: unknown repo id")
        if len(row.get("cells") or []) != len(dims):
            errors.append(f"comparison.rows[{i}].cells: needs {len(dims)} cells, one per dimension")
    if {r.get("repo") for r in rows} != set(by_id):
        errors.append("comparison.rows: one row per repo")

    dives = need(report, "deep_dives", list, "report") or []
    seen = set()
    for i, d in enumerate(dives):
        w = f"deep_dives[{i}]"
        rid = d.get("repo")
        if rid not in by_id:
            errors.append(f"{w}.repo: unknown repo id")
            continue
        seen.add(rid)
        entry = by_id[rid]
        need(d, "headline", str, w)
        need(d, "how_it_works", list, w)
        diagram = d.get("diagram")
        if diagram:
            code = (diagram.get("mermaid") or "").strip()
            first = code.split(None, 1)[0] if code else ""
            if not first.startswith(DIAGRAM_KINDS):
                errors.append(f"{w}.diagram.mermaid: must start with one of {DIAGRAM_KINDS}")
            if code.count('"') % 2:
                errors.append(f"{w}.diagram.mermaid: unbalanced double quotes")
            if "classDef" in code:
                warnings.append(f"{w}.diagram.mermaid: classDef is supplied by the template; remove it")
        root = repo_dir(entry)
        for j, part in enumerate(d.get("key_parts") or []):
            pw = f"{w}.key_parts[{j}]"
            need(part, "name", str, pw)
            need(part, "role", str, pw)
            path = need(part, "path", str, pw)
            if path and os.path.isdir(root) and read_lines(root, entry["commit"], path) is None:
                errors.append(f"{pw}.path: '{path}' does not exist at the pinned commit")
        excerpts = d.get("excerpts") or []
        if entry.get("verdict") in ("implements", "partial") and not excerpts:
            errors.append(f"{w}: a repo with verdict '{entry['verdict']}' needs at least one code excerpt")
        if len(excerpts) > MAX_EXCERPTS_PER_REPO:
            errors.append(f"{w}.excerpts: at most {MAX_EXCERPTS_PER_REPO}")
        for j, ex in enumerate(excerpts):
            ew = f"{w}.excerpts[{j}]"
            path = need(ex, "path", str, ew)
            need(ex, "title", str, ew)
            start, end = ex.get("start"), ex.get("end")
            if not (isinstance(start, int) and isinstance(end, int) and 1 <= start <= end):
                errors.append(f"{ew}: 'start' and 'end' must be line numbers with start <= end")
                continue
            if end - start + 1 > MAX_EXCERPT_LINES:
                errors.append(f"{ew}: {end - start + 1} lines; keep excerpts to {MAX_EXCERPT_LINES} lines or fewer")
                continue
            if "code" in ex:
                errors.append(f"{ew}: do not put code in the report; give the line range only")
            if not path or not os.path.isdir(root):
                continue
            lines = read_lines(root, entry["commit"], path)
            if lines is None:
                errors.append(f"{ew}.path: '{path}' does not exist at the pinned commit")
                continue
            if end > len(lines):
                errors.append(f"{ew}: file has {len(lines)} lines, range ends at {end}")
                continue
            text = "\n".join(lines[start - 1:end])
            expect = ex.get("expect")
            if not expect:
                errors.append(f"{ew}.expect: required - a short string that must appear in the range, "
                              "such as the function or constant name")
            elif expect not in text:
                errors.append(f"{ew}.expect: '{expect}' is not within lines {start}-{end} of {path}; "
                              "the range is wrong or the file changed")
            ex["_code"] = text
    missing = set(by_id) - seen
    if missing:
        errors.append(f"deep_dives: missing a section for {sorted(missing)}")

    # ---- Citations: every factual statement points at lines that support it ----
    cits = report.get("citations")
    if not isinstance(cits, dict) or not cits:
        errors.append("citations: required - an object of id -> {repo, path, start, end, expect, claim}")
        cits = {}
    for cid, c in cits.items():
        w = f"citations.{cid}"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", cid):
            errors.append(f"{w}: ids use letters, digits, - and _ only")
        claim = need(c, "claim", str, w)
        if claim and len(claim) > 260:
            errors.append(f"{w}.claim: keep the claim to one sentence (260 characters)")
        entry = by_id.get(c.get("repo"))
        if not entry:
            errors.append(f"{w}.repo: unknown repo id")
            continue
        path, start, end = c.get("path"), c.get("start"), c.get("end")
        if not (isinstance(path, str) and isinstance(start, int) and isinstance(end, int) and 1 <= start <= end):
            errors.append(f"{w}: needs 'path' and line numbers 'start' <= 'end'")
            continue
        if end - start + 1 > MAX_CITATION_LINES:
            errors.append(f"{w}: cites {end - start + 1} lines; cite the {MAX_CITATION_LINES} or fewer that carry the claim")
        root = repo_dir(entry)
        if not os.path.isdir(root):
            continue
        lines = read_lines(root, entry["commit"], path)
        if lines is None:
            errors.append(f"{w}.path: '{path}' does not exist at the pinned commit")
        elif end > len(lines):
            errors.append(f"{w}: file has {len(lines)} lines, range ends at {end}")
        else:
            expect = c.get("expect")
            if not expect:
                errors.append(f"{w}.expect: required - a short string that must appear in the cited lines")
            elif expect not in "\n".join(lines[start - 1:end]):
                errors.append(f"{w}.expect: '{expect}' is not within lines {start}-{end} of {path}")

    used = set()
    for where, text in prose_fields(report):
        for m in MARKER.findall(text):
            used.add(m)
            if m not in cits:
                errors.append(f"{where}: marker [^{m}] has no citation")

    def must_cite(where, text):
        if text and not MARKER.search(text):
            errors.append(f"{where}: states facts without a [^id] citation")

    absent = {r.get("id") for r in repos if r.get("verdict") == "absent"}
    for i, r in enumerate(repos):
        if r.get("id") not in absent:
            must_cite(f"repos[{i}].summary", r.get("summary"))
    for i, row in enumerate(rows):
        if row.get("repo") in absent:
            continue
        for j, cell in enumerate(row.get("cells") or []):
            if cell.strip().lower() not in ("not applicable", "none", "none found", "n/a"):
                must_cite(f"comparison.rows[{i}].cells[{j}]", cell)
    for i, d in enumerate(dives):
        if d.get("repo") in absent:
            continue
        for key in ("how_it_works", "gotchas"):
            for j, text in enumerate(d.get(key) or []):
                must_cite(f"deep_dives[{i}].{key}[{j}]", text)

    # ---- Reference implementation: runnable, tested, and mapped to the original ----
    impl = report.get("implementation")
    needs_impl = any(r.get("verdict") in ("implements", "partial") for r in repos)
    if not impl and needs_impl:
        errors.append("implementation: required when a repository implements the technique")
    if impl:
        w = "implementation"
        for k in ("title", "intro"):
            need(impl, k, str, w)
        root = impl_dir(report, report_path)
        files = need(impl, "files", list, w) or []
        for name in files:
            path = os.path.join(root, str(name))
            if not os.path.isfile(path):
                errors.append(f"{w}.files: {name} not found in {root}")
            elif not os.path.basename(name).startswith("test_"):
                with open(path, encoding="utf-8") as f:
                    count = len(f.read().split("\n"))
                if count > MAX_IMPL_LINES:
                    errors.append(f"{w}.files: {name} is {count} lines; keep it to {MAX_IMPL_LINES} or fewer")
        if not any(os.path.basename(str(n)).startswith("test_") for n in files):
            errors.append(f"{w}.files: include a test file named test_*.py")
        if not (impl.get("simplifications") or []):
            errors.append(f"{w}.simplifications: list what the implementation leaves out or changes")
        mirrors = need(impl, "mirrors", list, w) or []
        seen_ids = set()
        for i, m in enumerate(mirrors):
            mw = f"{w}.mirrors[{i}]"
            mid = need(m, "id", str, mw)
            if mid in seen_ids:
                errors.append(f"{mw}.id: duplicate")
            seen_ids.add(mid)
            need(m, "what", str, mw)
            if m.get("citation") not in cits:
                errors.append(f"{mw}.citation: must name an existing citation")
            lines = impl_lines(report, report_path, m)
            if lines is None:
                errors.append(f"{mw}: 'file', 'start' and 'end' must point at lines of an implementation file")
            elif not m.get("expect") or m["expect"] not in "\n".join(lines):
                errors.append(f"{mw}.expect: required, and must appear in {m.get('file')}:{m.get('start')}-{m.get('end')}")
        if len(mirrors) < 3:
            errors.append(f"{w}.mirrors: map at least 3 behaviours to citations of the original")
        for m in mirrors:
            used.add(m.get("citation"))

    items = need(report, "build_your_own", list, "report") or []
    if not 3 <= len(items) <= 7:
        errors.append("build_your_own: 3 to 7 items")
    diffs = report.get("differences") or []
    if len(repos) > 1 and not 2 <= len(diffs) <= 6:
        errors.append("differences: 2 to 6 items when more than one repository is compared")
    if len(repos) == 1 and diffs:
        errors.append("differences: leave out for a single-repository report")
    for cid in cits:
        if cid not in used:
            warnings.append(f"citations.{cid}: never referenced in the text or the implementation")
    return errors, warnings


def run_tests(report, report_path):
    """Run the reference implementation's tests. Returns (error or None, number of tests)."""
    impl = report.get("implementation")
    if not impl:
        return None, 0
    root = impl_dir(report, report_path)
    try:
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", root, "-p", "test_*.py"],
                           capture_output=True, text=True, timeout=120, cwd=root)
    except subprocess.TimeoutExpired:
        return "implementation tests timed out after 120 seconds", 0
    out = r.stderr + r.stdout
    m = re.search(r"Ran (\d+) tests?", out)
    ran = int(m.group(1)) if m else 0
    if r.returncode != 0:
        return "implementation tests failed:\n" + out.strip()[-1500:], ran
    if ran < 5:
        return f"implementation has {ran} tests; write at least 5", ran
    return None, ran


def check_review(report, report_path):
    """Return (errors, summary) for the independent review recorded beside the report."""
    report_path_for_impl = report_path
    path = os.path.join(os.path.dirname(os.path.abspath(report_path)), "review.json")
    if not os.path.exists(path):
        return ["no review.json: run the reviewer pass (review.py packet, then review.py record), "
                "or pass --draft to build an unreviewed page"], None
    with open(path, encoding="utf-8") as f:
        review = json.load(f)
    errors = []
    by_id = {r["id"]: r for r in report["repos"]}
    results = {r.get("id"): r for r in review.get("results", [])}
    for cid, c in (report.get("citations") or {}).items():
        res = results.get(cid)
        commit = by_id.get(c.get("repo"), {}).get("commit")
        if not res:
            errors.append(f"review: citation {cid} was not reviewed")
        elif res.get("hash") != citation_hash(c, commit):
            errors.append(f"review: citation {cid} changed after it was reviewed; review it again")
        elif res.get("verdict") != "supported":
            errors.append(f"review: citation {cid} is '{res.get('verdict')}': {res.get('note', '')[:200]}")
    for m in (report.get("implementation") or {}).get("mirrors") or []:
        mid = f"impl:{m.get('id')}"
        res = results.get(mid)
        if not res:
            errors.append(f"review: implementation item {mid} was not reviewed")
        elif res.get("hash") != mirror_hash(report, report_path_for_impl, m):
            errors.append(f"review: implementation item {mid} changed after it was reviewed; review it again")
        elif res.get("verdict") != "supported":
            errors.append(f"review: implementation item {mid} is '{res.get('verdict')}': {res.get('note', '')[:200]}")
    if review.get("prose_hash") != prose_hash(report):
        errors.append("review: the text changed after the review; the reviewer must re-check it for uncited statements")
    for u in review.get("uncited", []):
        errors.append(f"review: uncited statement at {u.get('where')}: {str(u.get('text', ''))[:140]}")
    summary = {"reviewer": review.get("reviewer", ""), "reviewed_at": review.get("reviewed_at", ""),
               "claims": len(report.get("citations") or {})}
    return errors, summary


def embed(report, report_path, tests_run):
    """Attach code, permalinks and repo links to the report for the page."""
    impl = report.get("implementation")
    if impl:
        root = impl_dir(report, report_path)
        loaded = []
        for name in impl["files"]:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                loaded.append({"name": name, "code": f.read().rstrip("\n"),
                               "href": f"{impl.get('dir', 'impl')}/{name}"})
        impl["files"] = loaded
        impl["tests_run"] = tests_run
        for m in impl["mirrors"]:
            m.pop("expect", None)
    by_id = {r["id"]: r for r in report["repos"]}
    for r in report["repos"]:
        r["url"] = f"https://github.com/{r['repo']}" if r.get("repo") else None
        r.pop("local_path", None)
    for d in report["deep_dives"]:
        entry = by_id[d["repo"]]
        base = f"https://github.com/{entry['repo']}/blob/{entry['commit']}/" if entry.get("repo") else None
        for part in d.get("key_parts") or []:
            part["url"] = base + part["path"] if base else None
        for ex in d.get("excerpts") or []:
            ex["code"] = ex.pop("_code")
            ex["url"] = f"{base}{ex['path']}#L{ex['start']}-L{ex['end']}" if base else None
    for c in (report.get("citations") or {}).values():
        entry = by_id[c["repo"]]
        c["url"] = (f"https://github.com/{entry['repo']}/blob/{entry['commit']}/{c['path']}#L{c['start']}-L{c['end']}"
                    if entry.get("repo") else None)
        c.pop("expect", None)


def plain(text):
    return MARKER.sub("", str(text or "")).replace("`", "").replace("  ", " ").strip()


def find_browser():
    for candidate in BROWSERS:
        path = candidate if os.path.isabs(candidate) else shutil.which(candidate)
        if path and os.path.exists(path):
            return path
    return None


def write_card(report, out_dir):
    meta = report["meta"]
    title = plain(meta["title"])
    size = 112 if len(title) <= 14 else 92 if len(title) <= 20 else 74 if len(title) <= 28 else 60
    label = {"implements": "built in", "partial": "partly", "delegates": "left to you", "absent": "none found"}
    stats = "".join(
        f'<div class="stat"><b>{html.escape(r["id"])}</b>'
        f'<span class="mono">{html.escape(label[r["verdict"]])}</span></div>'
        for r in report["repos"][:4]
    )
    with open(CARD_TEMPLATE, encoding="utf-8") as f:
        card = f.read()
    for key, value in {
        "__CARD_NAME_SIZE__": str(size),
        "__CARD_NAME__": html.escape(title),
        "__CARD_HOOK__": html.escape(plain(meta.get("hook") or meta["question"])),
        "__CARD_STATS__": stats,
    }.items():
        card = card.replace(key, value)
    card_html = os.path.join(out_dir, "card.html")
    card_png = os.path.join(out_dir, "card.png")
    with open(card_html, "w", encoding="utf-8") as f:
        f.write(card)
    browser = find_browser()
    if not browser:
        print("warning: no Chrome-family browser found; card.html written but card.png was not rendered",
              file=sys.stderr)
        return None
    if os.path.exists(card_png):
        os.remove(card_png)
    profile = tempfile.mkdtemp(prefix="anatomy-card-")
    proc = subprocess.Popen(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
         "--force-device-scale-factor=1", f"--user-data-dir={profile}",
         f"--window-size={CARD_SIZE[0]},{CARD_SIZE[1]}", f"--screenshot={card_png}",
         "file://" + os.path.abspath(card_html)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Headless Chrome does not always exit after a screenshot, so wait for the file, not the process.
    deadline = time.time() + 40
    while time.time() < deadline and not (os.path.exists(card_png) and os.path.getsize(card_png) > 0):
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    time.sleep(0.5)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    shutil.rmtree(profile, ignore_errors=True)
    if os.path.exists(card_png) and os.path.getsize(card_png) > 0:
        return card_png
    print("warning: the browser did not produce card.png", file=sys.stderr)
    return None


def head_tags(report, has_card):
    """Static link-preview tags. Crawlers do not run scripts, so these cannot come from the page's JS."""
    meta = report["meta"]
    title = f"{plain(meta['title'])} - Agent Anatomy"
    desc = plain(meta.get("hook") or meta["question"])[:200]
    site = (meta.get("site_url") or "").rstrip("/")
    tags = [
        ("name", "description", desc),
        ("property", "og:type", "article"),
        ("property", "og:title", title),
        ("property", "og:description", desc),
        ("name", "twitter:title", title),
        ("name", "twitter:description", desc),
    ]
    if site:
        tags.append(("property", "og:url", site + "/"))
    if has_card:
        image = f"{site}/card.png" if site else "card.png"
        tags += [
            ("property", "og:image", image),
            ("property", "og:image:width", str(CARD_SIZE[0])),
            ("property", "og:image:height", str(CARD_SIZE[1])),
            ("property", "og:image:alt", f"{title}: {desc}"),
            ("name", "twitter:card", "summary_large_image"),
            ("name", "twitter:image", image),
        ]
    return "\n".join(
        f'<meta {kind}="{key}" content="{html.escape(value, quote=True)}">' for kind, key, value in tags
    )


def main():
    args = [a for a in sys.argv[1:] if a != "--draft"]
    draft = "--draft" in sys.argv[1:]
    if len(args) != 2:
        sys.exit(__doc__)
    src, out = args
    with open(src, encoding="utf-8") as f:
        report = json.load(f)
    errors, warnings = check(report, src)
    tests_run = 0
    if not errors:
        test_error, tests_run = run_tests(report, src)
        if test_error:
            errors.append(test_error)
    review = None
    if not errors and not draft:
        review_errors, review = check_review(report, src)
        errors += review_errors
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    embed(report, src, tests_run)
    report["review"] = review  # None on a draft build

    out_dir = os.path.dirname(os.path.abspath(out))
    os.makedirs(out_dir, exist_ok=True)
    card = write_card(report, out_dir)
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read()
    payload = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    title = re.sub(r"[<>&]", "", plain(report["meta"]["title"]))
    page = (page.replace("__AA_TITLE__", title)
                .replace("__AA_HEAD__", head_tags(report, card is not None))
                .replace("__AA_DATA__", payload))
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    n = sum(len(d.get("excerpts") or []) for d in report["deep_dives"])
    state = "DRAFT, not reviewed" if draft else f"{len(report.get('citations') or {})} claims reviewed"
    print(f"wrote {out} ({len(page) // 1024} KB, {len(report['repos'])} repos, {n} verified excerpts, {state})")
    if card:
        print(f"wrote {card} ({CARD_SIZE[0]}x{CARD_SIZE[1]} share card)")


if __name__ == "__main__":
    main()
