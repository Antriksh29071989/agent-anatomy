"""File-based agent memory in three tiers: a small reference implementation.

It follows the design of Gemini CLI's memory, described with source citations
in the report this file belongs to. Memory is plain markdown files. Nothing is
embedded or searched: files are loaded whole, and what differs is *where* each
one enters the conversation.

  Tier 1  global + private project memory   -> the system instruction
  Tier 2  extension + project context files -> the first user message
  Tier 3  subdirectory context files        -> appended to a tool's result,
                                               the first time that folder is touched

Written from scratch for teaching. It is not code from that project.
"""
import os

CONTEXT_FILENAME = "GEMINI.md"          # instruction files, at any directory level
MEMORY_INDEX_FILENAME = "MEMORY.md"     # the private per-project memory index
GLOBAL_DIR = ".gemini"                  # under the user's home directory
JIT_PREFIX = "\n\n--- Newly Discovered Project Context ---\n"
JIT_SUFFIX = "\n--- End Project Context ---"


def find_project_root(start, markers=(".git",)):
    """The nearest ancestor of `start` that contains a boundary marker, or None."""
    current = os.path.abspath(start)
    while True:
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def find_upward(start_dir, stop_dir):
    """Context files from `start_dir` up to `stop_dir`, outermost first."""
    found, current, stop = [], os.path.abspath(start_dir), os.path.abspath(stop_dir)
    while True:
        candidate = os.path.join(current, CONTEXT_FILENAME)
        if os.path.isfile(candidate):
            found.insert(0, candidate)
        parent = os.path.dirname(current)
        if current == stop or parent == current:
            return found
        current = parent


def read_all(paths):
    """Concatenate files, each between lines naming where it came from. Empty files are dropped."""
    out = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            out.append(f"--- Context from: {path} ---\n{text}\n--- End of Context from: {path} ---")
    return "\n\n".join(out)


class MemoryStore:
    def __init__(self, home, project_memory_dir, workspace_roots, trusted=True, extension_files=()):
        self.home, self.project_memory_dir = home, project_memory_dir
        self.roots, self.trusted, self.extension_files = list(workspace_roots), trusted, list(extension_files)
        self.loaded = set()             # real paths already in the conversation
        self.global_memory = self.user_project_memory = self.project_memory = self.extension_memory = ""
        self.refresh()

    def memory_paths(self):
        """Where each kind of memory lives. A write is an ordinary edit of one of these files."""
        return {"global": os.path.join(self.home, GLOBAL_DIR, CONTEXT_FILENAME),
                "private_project": os.path.join(self.project_memory_dir, MEMORY_INDEX_FILENAME),
                "project": [os.path.join(r, CONTEXT_FILENAME) for r in self.roots]}

    def refresh(self):
        """Re-read every tier from disk. Call at start-up and after memory files change."""
        self.loaded.clear()
        paths = self.memory_paths()
        global_paths = [p for p in [paths["global"]] if os.path.isfile(p)]
        private = [p for p in [paths["private_project"]] if os.path.isfile(p)]
        if not private:                 # fall back to the older private file name
            legacy = os.path.join(self.project_memory_dir, CONTEXT_FILENAME)
            private = [legacy] if os.path.isfile(legacy) else []
        project = []
        if self.trusted:                # project files are only read in a trusted folder
            for root in self.roots:
                ceiling = find_project_root(root) or os.path.abspath(root)
                project += [p for p in find_upward(root, ceiling) if p not in project]
            project.sort()
        extension = [p for p in self.extension_files if os.path.isfile(p)]
        self.global_memory, self.user_project_memory = read_all(global_paths), read_all(private)
        self.project_memory, self.extension_memory = read_all(project), read_all(extension)
        self.loaded.update(os.path.realpath(p) for p in global_paths + private + project + extension)

    def system_instruction_memory(self):
        """Tier 1: goes in the system instruction."""
        parts = []
        if self.global_memory.strip():
            parts.append(f"<global_context>\n{self.global_memory.strip()}\n</global_context>")
        if self.user_project_memory.strip():
            parts.append(f"<user_project_memory>\n{self.user_project_memory.strip()}\n</user_project_memory>")
        return "\n".join(parts)

    def session_memory(self):
        """Tier 2: goes in the first user message."""
        sections = []
        if self.extension_memory.strip():
            sections.append(f"<extension_context>\n{self.extension_memory.strip()}\n</extension_context>")
        if self.project_memory.strip():
            sections.append(f"<project_context>\n{self.project_memory.strip()}\n</project_context>")
        return f"\n<loaded_context>\n{chr(10).join(sections)}\n</loaded_context>" if sections else ""

    def discover_context(self, accessed_path):
        """Tier 3: context files between a path a tool just touched and the project ceiling."""
        if not self.trusted:
            return ""
        target = os.path.abspath(accessed_path)
        roots = [os.path.abspath(r) for r in self.roots
                 if target == os.path.abspath(r) or target.startswith(os.path.abspath(r) + os.sep)]
        if not roots:
            return ""                   # outside every workspace root
        best_root = max(roots, key=len)                     # the deepest root containing the path
        ceiling = find_project_root(best_root) or best_root
        start = target if os.path.isdir(target) else os.path.dirname(target)
        new = [p for p in find_upward(start, ceiling) if os.path.realpath(p) not in self.loaded]
        self.loaded.update(os.path.realpath(p) for p in new)   # each file is delivered once
        return read_all(new)


def append_jit_context(tool_output, context):
    """Attach newly discovered context to a tool's result; leave it alone if there is none."""
    return f"{tool_output}{JIT_PREFIX}{context}{JIT_SUFFIX}" if context else tool_output
