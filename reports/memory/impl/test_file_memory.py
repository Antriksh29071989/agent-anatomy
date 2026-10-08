"""Tests for file_memory.py. Run: python3 -m unittest -v"""
import os
import tempfile
import unittest

from file_memory import JIT_PREFIX, MemoryStore, append_jit_context, find_upward


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = os.path.realpath(self.tmp.name)
        self.home, self.repo = os.path.join(t, "home"), os.path.join(t, "repo")
        self.private = os.path.join(self.home, ".gemini", "tmp", "repo-hash", "memory")
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, **kw):
        return MemoryStore(self.home, self.private, [self.repo], **kw)


class TierOne(Base):
    def test_global_memory_goes_in_the_system_instruction(self):
        write(os.path.join(self.home, ".gemini", "GEMINI.md"), "I prefer pytest.")
        s = self.store()
        self.assertIn("<global_context>", s.system_instruction_memory())
        self.assertIn("I prefer pytest.", s.system_instruction_memory())
        self.assertEqual(s.session_memory(), "")

    def test_private_project_memory_index_is_tier_one_too(self):
        write(os.path.join(self.private, "MEMORY.md"), "Local db runs on 5433.")
        self.assertIn("<user_project_memory>", self.store().system_instruction_memory())

    def test_memory_md_is_preferred_over_the_legacy_private_file(self):
        write(os.path.join(self.private, "MEMORY.md"), "new index")
        write(os.path.join(self.private, "GEMINI.md"), "old private file")
        text = self.store().system_instruction_memory()
        self.assertIn("new index", text)
        self.assertNotIn("old private file", text)

    def test_legacy_private_file_is_used_when_there_is_no_index(self):
        write(os.path.join(self.private, "GEMINI.md"), "old private file")
        self.assertIn("old private file", self.store().system_instruction_memory())


    def test_an_empty_private_memory_file_adds_nothing(self):
        write(os.path.join(self.private, "MEMORY.md"), "   \n")
        self.assertEqual(self.store().system_instruction_memory(), "")


class TierTwo(Base):
    def test_project_file_goes_in_the_first_user_message_not_the_system_instruction(self):
        write(os.path.join(self.repo, "GEMINI.md"), "We use tabs.")
        s = self.store()
        self.assertIn("<project_context>", s.session_memory())
        self.assertIn("We use tabs.", s.session_memory())
        self.assertNotIn("We use tabs.", s.system_instruction_memory())

    def test_an_untrusted_folder_loads_no_project_memory(self):
        write(os.path.join(self.repo, "GEMINI.md"), "We use tabs.")
        self.assertEqual(self.store(trusted=False).session_memory(), "")

    def test_upward_search_is_outermost_first_and_stops_at_the_project_root(self):
        write(os.path.join(os.path.dirname(self.repo), "GEMINI.md"), "above the repo")
        write(os.path.join(self.repo, "GEMINI.md"), "root")
        write(os.path.join(self.repo, "pkg", "GEMINI.md"), "pkg")
        found = find_upward(os.path.join(self.repo, "pkg"), self.repo)
        self.assertEqual([os.path.relpath(p, self.repo) for p in found], ["GEMINI.md", os.path.join("pkg", "GEMINI.md")])


    def test_a_blank_project_file_adds_no_session_memory(self):
        write(os.path.join(self.repo, "GEMINI.md"), "\n\n")
        self.assertEqual(self.store().session_memory(), "")


class TierThree(Base):
    def test_a_subdirectory_file_is_discovered_when_a_tool_touches_that_folder(self):
        write(os.path.join(self.repo, "src", "auth", "GEMINI.md"), "Auth rules.")
        s = self.store()
        self.assertNotIn("Auth rules.", s.session_memory())
        context = s.discover_context(os.path.join(self.repo, "src", "auth", "login.ts"))
        self.assertIn("Auth rules.", context)
        self.assertIn(JIT_PREFIX, append_jit_context("file contents", context))

    def test_each_file_is_delivered_only_once(self):
        write(os.path.join(self.repo, "src", "GEMINI.md"), "Src rules.")
        s = self.store()
        self.assertIn("Src rules.", s.discover_context(os.path.join(self.repo, "src", "a.ts")))
        self.assertEqual(s.discover_context(os.path.join(self.repo, "src", "b.ts")), "")

    def test_files_already_loaded_at_start_are_not_repeated(self):
        write(os.path.join(self.repo, "GEMINI.md"), "root rules")
        self.assertEqual(self.store().discover_context(os.path.join(self.repo, "main.ts")), "")

    def test_a_file_that_does_not_exist_yet_uses_its_parent_folder(self):
        write(os.path.join(self.repo, "docs", "GEMINI.md"), "Docs rules.")
        self.assertIn("Docs rules.", self.store().discover_context(os.path.join(self.repo, "docs", "new.md")))

    def test_nothing_is_discovered_outside_the_workspace_or_when_untrusted(self):
        write(os.path.join(self.repo, "src", "GEMINI.md"), "Src rules.")
        self.assertEqual(self.store().discover_context("/etc/hosts"), "")
        self.assertEqual(self.store(trusted=False).discover_context(os.path.join(self.repo, "src", "a.ts")), "")

    def test_an_empty_subdirectory_file_adds_nothing_to_the_tool_output(self):
        write(os.path.join(self.repo, "src", "GEMINI.md"), "")
        context = self.store().discover_context(os.path.join(self.repo, "src", "a.ts"))
        self.assertEqual(append_jit_context("out", context), "out")

    def test_no_context_leaves_the_tool_output_unchanged(self):
        self.assertEqual(append_jit_context("out", ""), "out")


class Writing(Base):
    def test_a_saved_memory_is_an_edited_file_and_shows_up_after_refresh(self):
        s = self.store()
        self.assertEqual(s.system_instruction_memory(), "")
        write(s.memory_paths()["private_project"], "Remember: deploy with make ship.")
        s.refresh()
        self.assertIn("make ship", s.system_instruction_memory())


if __name__ == "__main__":
    unittest.main()
