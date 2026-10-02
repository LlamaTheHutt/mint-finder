#!/usr/bin/python3

import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "usr", "lib", "linuxmint", "mint-finder"))

import search


DESKTOP = """[Desktop Entry]
Type=Application
Name=%s
GenericName=%s
Comment=%s
Exec=%s
Icon=application-x-executable
Keywords=%s
"""


def write_file(path, text):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def write_desktop(path, name, generic="", comment="", executable="true", keywords="", extra=""):
    text = DESKTOP % (name, generic, comment, executable, keywords)
    if extra:
        text = text + extra + "\n"
    write_file(path, text)


class SearchTests(unittest.TestCase):
    def test_score_text_prefers_exact_then_prefix(self):
        self.assertEqual(search.score_text("notes", "notes"), 100)
        self.assertEqual(search.score_text("note", "notes"), 80)
        self.assertEqual(search.score_text("ote", "notes"), 50)
        self.assertEqual(search.score_text("zzz", "notes"), 0)

    def test_text_matches_requires_every_word(self):
        words = search.query_words("web browser")
        self.assertTrue(search.text_matches(words, "Web Browser"))
        self.assertFalse(search.text_matches(words, "Browse the web"))

    def test_locate_query_strips_globs(self):
        self.assertEqual(search.locate_query("a*b?c[d]e"), "abcde")
        self.assertEqual(search.locate_query("  report  "), "report")

    def test_empty_query_returns_no_programs(self):
        self.assertEqual(search.search_applications("   ", []), [])

    def test_applications_match_name_and_skip_hidden(self):
        root = tempfile.mkdtemp()
        try:
            user_dir = os.path.join(root, "user")
            system_dir = os.path.join(root, "system")
            write_desktop(
                os.path.join(user_dir, "firefox.desktop"),
                "Firefox",
                comment="Browse the web",
                executable="firefox"
            )
            write_desktop(os.path.join(system_dir, "firefox.desktop"), "Firefox Nightly")
            write_desktop(
                os.path.join(user_dir, "hidden.desktop"),
                "HiddenAppXYZ",
                extra="NoDisplay=true"
            )
            write_desktop(
                os.path.join(user_dir, "editor.desktop"),
                "Text Editor",
                generic="Editor",
                keywords="notes;write;"
            )
            results = search.search_applications("fire", [user_dir, system_dir])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].title, "Firefox")
            self.assertEqual(results[0].kind, "application")
            hidden = search.search_applications("HiddenAppXYZ", [user_dir, system_dir])
            self.assertEqual(hidden, [])
            notes = search.search_applications("notes", [user_dir, system_dir])
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0].title, "Text Editor")
        finally:
            shutil.rmtree(root)

    def test_prefix_program_ranks_before_contains(self):
        root = tempfile.mkdtemp()
        try:
            folder = os.path.join(root, "apps")
            write_desktop(os.path.join(folder, "campfire.desktop"), "Campfire")
            write_desktop(os.path.join(folder, "firefox.desktop"), "Firefox")
            results = search.search_applications("fire", [folder])
            self.assertEqual(results[0].title, "Firefox")
            self.assertEqual(results[1].title, "Campfire")
        finally:
            shutil.rmtree(root)

    def test_tryexec_skips_missing_program(self):
        root = tempfile.mkdtemp()
        try:
            folder = os.path.join(root, "apps")
            write_desktop(
                os.path.join(folder, "missing.desktop"),
                "MissingToolXYZ",
                extra="TryExec=missing-tool-xyz-not-installed"
            )
            results = search.search_applications("MissingToolXYZ", [folder])
            self.assertEqual(results, [])
        finally:
            shutil.rmtree(root)

    def test_walk_finds_files_and_folders(self):
        root = tempfile.mkdtemp()
        try:
            write_file(os.path.join(root, "Documents", "Notes.txt"), "hello")
            os.makedirs(os.path.join(root, "Projects"))
            write_file(os.path.join(root, ".secret.txt"), "hidden")
            write_file(os.path.join(root, "node_modules", "leftpad.txt"), "nope")
            write_file(os.path.join(root, "pkgs", "files"), "nope")
            found = search.walk_paths("notes", [root], False, 1000, 4)
            self.assertEqual(found, [os.path.join(root, "Documents", "Notes.txt")])
            folders = search.walk_paths("proj", [root], False, 1000, 4)
            self.assertEqual(folders, [os.path.join(root, "Projects")])
            hidden = search.walk_paths("secret", [root], False, 1000, 4)
            self.assertEqual(hidden, [])
            shown = search.walk_paths("secret", [root], True, 1000, 4)
            self.assertEqual(shown, [os.path.join(root, ".secret.txt")])
            skipped = search.walk_paths("leftpad", [root], False, 1000, 4)
            self.assertEqual(skipped, [])
            packages = search.walk_paths("files", [root], False, 1000, 4)
            self.assertEqual(packages, [])
        finally:
            shutil.rmtree(root)

    def test_walk_directories_only_skips_files(self):
        root = tempfile.mkdtemp()
        try:
            write_file(os.path.join(root, "Documents", "Notes.txt"), "hello")
            os.makedirs(os.path.join(root, "Notes"))
            both = search.walk_paths("notes", [root], False, 1000, 4, False)
            self.assertIn(os.path.join(root, "Documents", "Notes.txt"), both)
            self.assertIn(os.path.join(root, "Notes"), both)
            folders = search.walk_paths("notes", [root], False, 1000, 4, True)
            self.assertEqual(folders, [os.path.join(root, "Notes")])
        finally:
            shutil.rmtree(root)

    def test_directories_only_skips_file_results(self):
        root = tempfile.mkdtemp()
        try:
            home = os.path.join(root, "home")
            write_file(os.path.join(home, "Report.txt"), "a")
            os.makedirs(os.path.join(home, "Reports"))
            binary = os.path.join(root, "locate")
            write_file(binary, "#!/bin/sh\nexit 1\n")
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC)
            outcome = search.collect_paths(
                "report",
                home,
                False,
                locate_bin=binary,
                walk_roots=[home],
                directories_only=True
            )
            self.assertEqual(len(outcome.directories), 1)
            self.assertEqual(outcome.directories[0].title, "Reports")
            self.assertEqual(outcome.files, [])
        finally:
            shutil.rmtree(root)

    def test_home_path_ranks_above_system_path(self):
        root = tempfile.mkdtemp()
        try:
            home = os.path.join(root, "home")
            system = os.path.join(root, "usr")
            home_file = os.path.join(home, "Notes.txt")
            system_file = os.path.join(system, "Notes.txt")
            write_file(home_file, "a")
            write_file(system_file, "b")
            directories, files = search.rank_paths("notes", [system_file, home_file], home, False)
            self.assertEqual(directories, [])
            self.assertEqual(files[0].target, home_file)
            self.assertGreater(files[0].score, files[1].score)
            self.assertEqual(files[0].subtitle, "~/Notes.txt")
        finally:
            shutil.rmtree(root)

    def test_hidden_paths_are_left_out(self):
        root = tempfile.mkdtemp()
        try:
            visible = os.path.join(root, "Notes.txt")
            hidden = os.path.join(root, ".hidden", "Notes.txt")
            write_file(visible, "a")
            write_file(hidden, "b")
            directories, files = search.rank_paths("notes", [visible, hidden], root, False)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].target, visible)
        finally:
            shutil.rmtree(root)

    def test_read_locate_uses_full_path_search(self):
        root = tempfile.mkdtemp()
        try:
            args_file = os.path.join(root, "args")
            binary = os.path.join(root, "locate")
            script = "#!/bin/sh\nprintf '%%s\\n' \"$@\" > '%s'\nexit 1\n" % args_file
            write_file(binary, script)
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC)
            paths = search.read_locate(binary, "*report", 40)
            self.assertEqual(paths, [])
            with open(args_file, "r", encoding="utf-8") as handle:
                recorded = handle.read().splitlines()
            self.assertNotIn("-b", recorded)
            self.assertIn("-e", recorded)
            self.assertIn("-N", recorded)
            self.assertIn("report", recorded)
        finally:
            shutil.rmtree(root)

    def test_locate_failure_falls_back_to_home_walk(self):
        root = tempfile.mkdtemp()
        try:
            binary = os.path.join(root, "locate")
            write_file(binary, "#!/bin/sh\necho 'Permission denied' >&2\nexit 1\n")
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC)
            home = os.path.join(root, "home")
            write_file(os.path.join(home, "Report.txt"), "a")
            outcome = search.collect_paths("report", home, False, locate_bin=binary, walk_roots=[home])
            self.assertEqual(outcome.note, "walk")
            self.assertEqual(len(outcome.files), 1)
            self.assertEqual(outcome.files[0].title, "Report.txt")
        finally:
            shutil.rmtree(root)

    def test_locate_results_are_merged_with_the_walk(self):
        root = tempfile.mkdtemp()
        try:
            home = os.path.join(root, "home")
            other = os.path.join(root, "opt", "tools")
            write_file(os.path.join(home, "Report.txt"), "a")
            outside = os.path.join(other, "Report-extra.txt")
            write_file(outside, "b")
            binary = os.path.join(root, "locate")
            script = "#!/bin/sh\nprintf '%%s\\n' '%s'\nexit 0\n" % outside
            write_file(binary, script)
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC)
            outcome = search.collect_paths("report", home, False, locate_bin=binary, walk_roots=[home])
            self.assertEqual(outcome.note, "")
            titles = []
            for item in outcome.files:
                titles.append(item.title)
            self.assertIn("Report.txt", titles)
            self.assertNotIn("Report-extra.txt", titles)
            self.assertEqual(outcome.files[0].title, "Report.txt")
        finally:
            shutil.rmtree(root)

    def test_search_locations_limit_locate_and_walk(self):
        root = tempfile.mkdtemp()
        try:
            home = os.path.join(root, "home")
            docs = os.path.join(home, "Documents")
            other = os.path.join(root, "other")
            os.makedirs(docs)
            os.makedirs(other)
            write_file(os.path.join(docs, "Notes.txt"), "a")
            write_file(os.path.join(home, "Notes-home.txt"), "b")
            write_file(os.path.join(other, "Notes-other.txt"), "c")
            binary = os.path.join(root, "locate")
            script = "#!/bin/sh\nprintf '%%s\\n' '%s'\nprintf '%%s\\n' '%s'\nexit 0\n"
            script = script % (
                os.path.join(other, "Notes-other.txt"),
                os.path.join(docs, "Notes.txt")
            )
            write_file(binary, script)
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC)
            roots = search.resolve_search_roots([docs], home)
            self.assertEqual(roots, [docs])
            outcome = search.collect_paths(
                "notes",
                home,
                False,
                locate_bin=binary,
                search_locations=[docs]
            )
            titles = []
            for item in outcome.files:
                titles.append(item.title)
            self.assertEqual(titles, ["Notes.txt"])
            self.assertTrue(search.path_in_roots(os.path.join(docs, "Notes.txt"), roots))
            self.assertFalse(search.path_in_roots(os.path.join(other, "Notes-other.txt"), roots))
            default_roots = search.resolve_search_roots(None, home)
            self.assertEqual(default_roots, [home])
            self.assertEqual(search.resolve_search_roots([], home), [])
            nested = search.resolve_search_roots([home, docs], home)
            self.assertEqual(nested, [home])
        finally:
            shutil.rmtree(root)

    def test_dir_visit_limit_stops_deep_walks(self):
        root = tempfile.mkdtemp()
        try:
            current = root
            for index in range(6):
                current = os.path.join(current, "level%s" % index)
                os.makedirs(current)
            found = search.walk_paths("level", [root], False, 1000, 8, True, max_dir_visits=3)
            self.assertLessEqual(len(found), 3)
        finally:
            shutil.rmtree(root)

    def test_keywords_match_across_the_path(self):
        root = tempfile.mkdtemp()
        try:
            folder = os.path.join(root, "Repositories", "Cursor", "rrite")
            os.makedirs(folder)
            write_file(os.path.join(folder, "README"), "a")
            other = os.path.join(root, "Repositories", "Other", "rrite")
            os.makedirs(other)
            found = search.walk_paths("rrite cursor", [root], False, 1000, 6)
            self.assertIn(folder, found)
            self.assertNotIn(other, found)
            self.assertNotIn(os.path.join(folder, "README"), found)
            reversed_query = search.walk_paths("cursor rrite", [root], False, 1000, 6)
            self.assertIn(folder, reversed_query)
            directories, files = search.rank_paths("rrite cursor", found, root, False)
            self.assertEqual(files, [])
            self.assertEqual(len(directories), 1)
            self.assertEqual(directories[0].target, folder)
            self.assertEqual(directories[0].title, "rrite")
        finally:
            shutil.rmtree(root)

    def test_locate_passes_every_keyword(self):
        root = tempfile.mkdtemp()
        try:
            home = os.path.join(root, "home")
            os.makedirs(home)
            folder = os.path.join(root, "Repositories", "Cursor", "rrite")
            os.makedirs(folder)
            decoy = os.path.join(root, "Cursor-notes")
            write_file(decoy, "a")
            args_file = os.path.join(root, "args")
            binary = os.path.join(root, "locate")
            script = "#!/bin/sh\nprintf '%%s\\n' \"$@\" > '%s'\n"
            script = script + "printf '%%s\\n' '%s'\nexit 0\n"
            script = script % (args_file, folder)
            write_file(binary, script)
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC)
            outcome = search.collect_paths(
                "rrite cursor",
                home,
                False,
                locate_bin=binary,
                walk_roots=[root]
            )
            with open(args_file, "r", encoding="utf-8") as handle:
                recorded = handle.read().splitlines()
            self.assertIn("rrite", recorded)
            self.assertIn("cursor", recorded)
            self.assertEqual(len(outcome.directories), 1)
            self.assertEqual(outcome.directories[0].target, folder)
            self.assertEqual(outcome.files, [])
        finally:
            shutil.rmtree(root)

    def test_matching_hidden_basename_is_allowed(self):
        root = tempfile.mkdtemp()
        try:
            visible = os.path.join(root, "notes.txt")
            hidden = os.path.join(root, ".bashrc")
            partial = os.path.join(root, ".secret.txt")
            nested = os.path.join(root, ".config", "notes.txt")
            write_file(visible, "a")
            write_file(hidden, "b")
            write_file(partial, "c")
            write_file(nested, "d")
            directories, files = search.rank_paths("bashrc", [visible, hidden, partial, nested], root, False)
            self.assertEqual(directories, [])
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].target, hidden)
            directories, files = search.rank_paths("secret", [visible, hidden, partial, nested], root, False)
            self.assertEqual(files, [])
            directories, files = search.rank_paths("notes", [visible, hidden, partial, nested], root, False)
            self.assertEqual([item.target for item in files], [visible])
            hidden_dir = os.path.join(root, ".config")
            directories, files = search.rank_paths("config", [hidden_dir], root, False)
            self.assertEqual([item.target for item in directories], [hidden_dir])
            found = search.walk_paths("config", [root], False, 1000, 4, True)
            self.assertIn(hidden_dir, found)
            nested_found = search.walk_paths("notes", [root], False, 1000, 4)
            self.assertNotIn(nested, nested_found)
        finally:
            shutil.rmtree(root)

    def test_bookmarks_require_entry_match(self):
        root = tempfile.mkdtemp()
        try:
            folder = os.path.join(root, "Projects", "rrite")
            os.makedirs(folder)
            decoy = os.path.join(root, "Projects", "other")
            os.makedirs(decoy)
            results = search.bookmark_results("rrite cursor", [folder, decoy], root, False)
            self.assertEqual(results, [])
            results = search.bookmark_results("rrite projects", [folder], root, False)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].target, folder)
            self.assertEqual(results[0].kind, "bookmark")
        finally:
            shutil.rmtree(root)

    def test_frequency_orders_before_score(self):
        often = search.Result("file", "Notes", "", "text", "/home/notes", 40)
        closer = search.Result("file", "Notebook", "", "text", "/home/notebook", 80)
        counts = {"/home/notes": 5}
        ranked = search.sort_results([closer, often], counts, True)
        self.assertEqual(ranked[0].target, "/home/notes")
        plain = search.sort_results([closer, often], counts, False)
        self.assertEqual(plain[0].target, "/home/notebook")

    def test_sort_results_ties_on_same_title(self):
        first = search.Result("directory", "rrite", "", "folder", "/a/rrite", 50)
        second = search.Result("directory", "rrite", "", "folder", "/b/rrite", 50)
        ranked = search.sort_results([second, first], {}, False)
        self.assertEqual([item.target for item in ranked], ["/a/rrite", "/b/rrite"])
        ranked = search.sort_results([second, first], {}, True)
        self.assertEqual([item.target for item in ranked], ["/a/rrite", "/b/rrite"])

    def test_frequency_file_roundtrip(self):
        root = tempfile.mkdtemp()
        try:
            path = os.path.join(root, "frequency")
            store = search.LaunchFrequency(path)
            store.record("/tmp/rrite")
            store.record("/tmp/rrite")
            store.record("/tmp/other")
            loaded = search.load_frequencies(path)
            self.assertEqual(loaded["/tmp/rrite"], 2)
            self.assertEqual(loaded["/tmp/other"], 1)
        finally:
            shutil.rmtree(root)

    def test_bookmarks_roundtrip_and_match_first(self):
        root = tempfile.mkdtemp()
        try:
            path = os.path.join(root, "bookmarks")
            folder = os.path.join(root, "Projects", "rrite")
            os.makedirs(folder)
            other = os.path.join(root, "Projects", "other")
            os.makedirs(other)
            store = search.Bookmarks(path)
            self.assertTrue(store.add(folder))
            self.assertFalse(store.add(folder))
            self.assertTrue(store.contains(folder))
            loaded = search.load_bookmarks(path)
            self.assertEqual(loaded, [folder])
            results = search.bookmark_results("rrite", store.items, root, False)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].kind, "bookmark")
            self.assertEqual(results[0].target, folder)
            self.assertGreaterEqual(results[0].score, search.BOOKMARK_SCORE)
            self.assertTrue(store.remove(folder))
            self.assertFalse(store.contains(folder))
        finally:
            shutil.rmtree(root)

    def test_config_paths_use_xdg_config(self):
        root = tempfile.mkdtemp()
        old_config = os.environ.get("XDG_CONFIG_HOME")
        old_data = os.environ.get("XDG_DATA_HOME")
        try:
            os.environ["XDG_CONFIG_HOME"] = root
            if "XDG_DATA_HOME" in os.environ:
                del os.environ["XDG_DATA_HOME"]
            path = search.bookmark_file()
            self.assertEqual(path, os.path.join(root, "mint-finder", "bookmarks"))
            freq = search.frequency_file()
            self.assertEqual(freq, os.path.join(root, "mint-finder", "frequency"))
            legacy_root = tempfile.mkdtemp()
            try:
                os.environ["XDG_DATA_HOME"] = legacy_root
                legacy = os.path.join(legacy_root, "mint-finder", "bookmarks")
                write_file(legacy, "/tmp/legacy\n")
                config_root = tempfile.mkdtemp()
                try:
                    os.environ["XDG_CONFIG_HOME"] = config_root
                    migrated = search.bookmark_file()
                    self.assertEqual(migrated, os.path.join(config_root, "mint-finder", "bookmarks"))
                    self.assertTrue(os.path.exists(migrated))
                    with open(migrated, "r", encoding="utf-8") as handle:
                        self.assertEqual(handle.read(), "/tmp/legacy\n")
                finally:
                    shutil.rmtree(config_root)
            finally:
                shutil.rmtree(legacy_root)
        finally:
            if old_config is None:
                if "XDG_CONFIG_HOME" in os.environ:
                    del os.environ["XDG_CONFIG_HOME"]
            else:
                os.environ["XDG_CONFIG_HOME"] = old_config
            if old_data is None:
                if "XDG_DATA_HOME" in os.environ:
                    del os.environ["XDG_DATA_HOME"]
            else:
                os.environ["XDG_DATA_HOME"] = old_data
            shutil.rmtree(root)

    def test_name_match_ranks_above_path_match(self):
        root = tempfile.mkdtemp()
        try:
            named = os.path.join(root, "Cursor", "rrite")
            path_only = os.path.join(root, "Cursor", "project", "notes")
            os.makedirs(named)
            os.makedirs(path_only)
            write_file(os.path.join(named, "readme.txt"), "a")
            write_file(os.path.join(path_only, "rrite-notes.txt"), "b")
            directories, files = search.rank_paths(
                "rrite cursor",
                [named, os.path.join(path_only, "rrite-notes.txt")],
                root,
                False
            )
            self.assertEqual(directories[0].target, named)
            self.assertGreater(directories[0].score, files[0].score)
        finally:
            shutil.rmtree(root)

    def test_walk_batches_hits(self):
        root = tempfile.mkdtemp()
        try:
            write_file(os.path.join(root, "one.txt"), "a")
            write_file(os.path.join(root, "two.txt"), "a")
            write_file(os.path.join(root, "three.txt"), "a")
            batches = []

            def on_batch(paths):
                batches.append(list(paths))

            found = search.walk_paths(
                "t",
                [root],
                False,
                1000,
                4,
                on_batch=on_batch,
                batch_size=2
            )
            self.assertEqual(len(found), 3)
            self.assertTrue(batches)
            self.assertEqual(len(batches[0]), 2)
        finally:
            shutil.rmtree(root)

    def test_each_search_root_gets_its_own_budget(self):
        root = tempfile.mkdtemp()
        try:
            first = os.path.join(root, "first")
            second = os.path.join(root, "second")
            os.makedirs(first)
            os.makedirs(second)
            for index in range(8):
                os.makedirs(os.path.join(first, "pad%s" % index))
            target = os.path.join(second, "rrite")
            os.makedirs(target)
            found = search.walk_paths(
                "rrite",
                [first, second],
                False,
                1000,
                4,
                max_dir_visits=3
            )
            self.assertIn(target, found)
            outcome = search.collect_paths(
                "rrite",
                first,
                False,
                walk_roots=[first, second]
            )
            titles = []
            for item in outcome.directories:
                titles.append(item.title)
            self.assertIn("rrite", titles)
        finally:
            shutil.rmtree(root)

    def test_short_query_skips_files(self):
        outcome = search.collect_paths("a", "/tmp", False, locate_bin=False, walk_roots=[])
        self.assertEqual(outcome.note, "short")
        self.assertEqual(outcome.files, [])
        self.assertEqual(outcome.directories, [])

    def test_skipped_folder_stays_out_of_search(self):
        root = tempfile.mkdtemp()
        try:
            home = os.path.join(root, "home")
            skip = os.path.join(home, "Downloads")
            inner = os.path.join(skip, "Inner")
            os.makedirs(inner)
            write_file(os.path.join(home, "Notes.txt"), "a")
            write_file(os.path.join(skip, "Notes-skip.txt"), "b")
            write_file(os.path.join(inner, "Notes-inner.txt"), "c")
            blocked = search.blocked_roots([skip])
            self.assertTrue(search.path_is_blocked(skip, blocked))
            self.assertTrue(search.path_is_blocked(os.path.join(skip, "Notes-skip.txt"), blocked))
            self.assertFalse(search.path_is_blocked(os.path.join(home, "Notes.txt"), blocked))
            found = search.walk_paths("notes", [home], False, 1000, 6, blocked=blocked)
            self.assertIn(os.path.join(home, "Notes.txt"), found)
            self.assertNotIn(os.path.join(skip, "Notes-skip.txt"), found)
            self.assertNotIn(os.path.join(inner, "Notes-inner.txt"), found)
            folders = search.walk_paths("downloads", [home], False, 1000, 6, True, blocked=blocked)
            self.assertNotIn(skip, folders)
            binary = os.path.join(root, "locate")
            script = "#!/bin/sh\nprintf '%%s\\n' '%s'\nprintf '%%s\\n' '%s'\nprintf '%%s\\n' '%s'\nexit 0\n"
            script = script % (
                os.path.join(home, "Notes.txt"),
                os.path.join(skip, "Notes-skip.txt"),
                os.path.join(inner, "Notes-inner.txt")
            )
            write_file(binary, script)
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC)
            outcome = search.collect_paths(
                "notes",
                home,
                False,
                locate_bin=binary,
                search_locations=[home],
                excluded_locations=[skip]
            )
            titles = []
            for item in outcome.files:
                titles.append(item.title)
            self.assertIn("Notes.txt", titles)
            self.assertNotIn("Notes-skip.txt", titles)
            self.assertNotIn("Notes-inner.txt", titles)
            bookmarks = search.bookmark_results(
                "notes",
                [os.path.join(skip, "Notes-skip.txt"), os.path.join(home, "Notes.txt")],
                home,
                False,
                False,
                [skip]
            )
            names = []
            for item in bookmarks:
                names.append(item.title)
            self.assertEqual(names, ["Notes.txt"])
        finally:
            shutil.rmtree(root)

    def test_walk_reaches_a_later_folder(self):
        root = tempfile.mkdtemp()
        try:
            first = os.path.join(root, "a-first")
            second = os.path.join(root, "b-second")
            os.makedirs(first)
            os.makedirs(second)
            index = 0
            while index < 30:
                write_file(os.path.join(first, "notes-%s.txt" % index), "a")
                index = index + 1
            write_file(os.path.join(second, "notes-later.txt"), "b")
            found = search.walk_paths("notes", [root], False, 10, 4)
            parents = {}
            for path in found:
                parents[os.path.dirname(path)] = True
            self.assertIn(first, parents)
            self.assertIn(second, parents)
        finally:
            shutil.rmtree(root)

    def test_results_keep_a_second_folder(self):
        results = []
        index = 0
        while index < 10:
            results.append(search.Result("file", "a%s" % index, "", "icon", "/one/a%s.txt" % index, 100 - index))
            index = index + 1
        results.append(search.Result("file", "b", "", "icon", "/two/b.txt", 1))
        chosen = search.take_spread(results, 6, 4)
        targets = []
        for item in chosen:
            targets.append(item.target)
        self.assertIn("/two/b.txt", targets)
        self.assertLessEqual(len(chosen), 6)

    def test_locate_queries_each_search_folder(self):
        root = tempfile.mkdtemp()
        try:
            home = os.path.join(root, "home")
            other = os.path.join(root, "other")
            os.makedirs(home)
            os.makedirs(other)
            write_file(os.path.join(home, "Notes.txt"), "a")
            write_file(os.path.join(other, "Notes.txt"), "b")
            args_file = os.path.join(root, "args")
            binary = os.path.join(root, "locate")
            script = "#!/bin/sh\nprintf '%%s\\n' \"$@\" >> '%s'\nprintf '\\n' >> '%s'\n"
            script = script + "last=\nfor item in \"$@\"; do\n    last=\"$item\"\ndone\n"
            script = script + "case \"$last\" in\n/*) printf '%%s/Notes.txt\\n' \"$last\" ;;\nesac\nexit 0\n"
            script = script % (args_file, args_file)
            write_file(binary, script)
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IEXEC)
            outcome = search.collect_paths(
                "notes",
                home,
                False,
                locate_bin=binary,
                walk_roots=[home, other]
            )
            with open(args_file, "r", encoding="utf-8") as handle:
                recorded = handle.read()
            self.assertIn(home, recorded)
            self.assertIn(other, recorded)
            titles = []
            for item in outcome.files:
                titles.append(item.title)
            self.assertEqual(titles.count("Notes.txt"), 2)
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
