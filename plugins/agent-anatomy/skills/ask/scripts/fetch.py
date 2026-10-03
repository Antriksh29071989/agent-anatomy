#!/usr/bin/env python3
"""Fetch agent repositories into a local cache and report where they are.

Usage: fetch.py [--refresh] <target> [<target> ...]

A target is a registry id (see references/repos.json), an owner/name pair, a
git URL, or a path to a local repository. Remote repositories are cloned at
depth 1 into the cache and reused on later runs; --refresh updates them.

Prints a JSON list: id, repo, path, commit, commit_date, kind, language, license.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "..", "references", "repos.json")


def cache_root():
    base = os.environ.get("AGENT_ANATOMY_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "agent-anatomy")
    return os.path.join(base, "repos")


def cache_path(repo):
    return os.path.join(cache_root(), repo.replace("/", "__"))


def registry():
    with open(REGISTRY, encoding="utf-8") as f:
        return {r["id"]: r for r in json.load(f)["repos"]}


def git(path, *args):
    return subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, errors="replace")


def detect_license(path):
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING"):
        p = os.path.join(path, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                head = f.read(600)
            for spdx, marker in (("Apache-2.0", "Apache License"), ("MIT", "MIT License"),
                                 ("BSD", "BSD "), ("GPL", "GNU GENERAL PUBLIC"), ("MPL-2.0", "Mozilla Public")):
                if marker.lower() in head.lower():
                    return spdx
            return "see " + name
    return "not found"


def resolve(target, reg):
    """Return (id, repo or None, local path or None, registry entry or {})."""
    if os.path.isdir(target):
        path = os.path.abspath(target)
        return os.path.basename(path.rstrip("/")), None, path, {}
    if target in reg:
        entry = reg[target]
        return target, entry["repo"], None, entry
    m = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", target) or re.match(r"^([\w.-]+)/([\w.-]+)$", target)
    if not m:
        sys.exit(f"cannot understand target: {target}")
    repo = f"{m.group(1)}/{m.group(2)}"
    for entry in reg.values():
        if entry["repo"].lower() == repo.lower():
            return entry["id"], entry["repo"], None, entry
    return m.group(2).lower(), repo, None, {}


def fetch(repo, refresh):
    path = cache_path(repo)
    url = f"https://github.com/{repo}.git"
    if not os.path.isdir(os.path.join(path, ".git")):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        r = subprocess.run(["git", "clone", "--quiet", "--depth", "1", url, path], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"clone failed for {repo}: {r.stderr.strip()[:300]}")
    elif refresh:
        r = git(path, "fetch", "--quiet", "--depth", "1", "origin", "HEAD")
        if r.returncode:
            sys.exit(f"fetch failed for {repo}: {r.stderr.strip()[:300]}")
        git(path, "checkout", "--quiet", "--detach", "FETCH_HEAD")
    return path


def main():
    args = [a for a in sys.argv[1:] if a != "--refresh"]
    refresh = "--refresh" in sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    reg = registry()
    out = []
    for target in args:
        rid, repo, local, entry = resolve(target, reg)
        path = local or fetch(repo, refresh)
        head = git(path, "log", "-1", "--format=%H %ad", "--date=short").stdout.split()
        if len(head) != 2:
            sys.exit(f"not a git repository: {path}")
        out.append({
            "id": rid,
            "repo": repo,
            "path": path,
            "commit": head[0],
            "commit_date": head[1],
            "kind": entry.get("kind", "unknown"),
            "language": entry.get("language", ""),
            "license": entry.get("license") or detect_license(path),
            "what": entry.get("what", ""),
        })
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
