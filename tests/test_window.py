#!/usr/bin/python3

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "usr", "lib", "linuxmint", "mint-finder"))

import search


class WindowTests(unittest.TestCase):
    def test_builder_loads_search_window(self):
        if not os.environ.get("DISPLAY"):
            self.skipTest("needs a display")
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("XApp", "1.0")
        from gi.repository import Gtk, XApp
        Gtk.init([])
        ui_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "usr",
            "share",
            "linuxmint",
            "mint-finder",
            "mint-finder.ui"
        )
        builder = Gtk.Builder()
        builder.add_from_file(os.path.abspath(ui_path))
        window = builder.get_object("main_window")
        entry = builder.get_object("search_entry")
        stack = builder.get_object("results_stack")
        preferences = builder.get_object("preferences_dialog")
        self.assertIsNotNone(window)
        self.assertIsNotNone(entry)
        self.assertIsNotNone(stack)
        self.assertIsNotNone(preferences)
        self.assertIsNotNone(builder.get_object("headerbar"))
        self.assertIsInstance(entry, Gtk.SearchEntry)
        self.assertIsNotNone(builder.get_object("preferences_button"))
        self.assertIsNotNone(builder.get_object("results_list"))
        self.assertIsNotNone(builder.get_object("shortcut_button"))
        self.assertIsNotNone(builder.get_object("preferences_close"))
        self.assertIsNotNone(builder.get_object("frequency_check"))
        self.assertIsNotNone(builder.get_object("directories_check"))
        self.assertIsNotNone(builder.get_object("locations_list"))
        self.assertIsNotNone(builder.get_object("locations_add"))
        self.assertIsNotNone(builder.get_object("locations_remove"))
        self.assertIsNotNone(builder.get_object("excluded_list"))
        self.assertIsNotNone(builder.get_object("excluded_add"))
        self.assertIsNotNone(builder.get_object("excluded_remove"))
        self.assertFalse(builder.get_object("excluded_remove").get_sensitive())
        self.assertEqual(builder.get_object("move_to_bookmarks").get_label(), "Move to Bookmarks")
        self.assertEqual(builder.get_object("move_to_blacklist").get_label(), "Move to Blacklist")
        self.assertFalse(builder.get_object("move_to_bookmarks").get_sensitive())
        self.assertFalse(builder.get_object("move_to_blacklist").get_sensitive())
        self.assertIsNotNone(builder.get_object("bookmarks_list"))
        self.assertIsNotNone(builder.get_object("bookmarks_add"))
        self.assertFalse(builder.get_object("bookmarks_remove").get_sensitive())
        page_stack = builder.get_object("preferences_stack")
        self.assertIsNotNone(page_stack)
        self.assertIsNotNone(builder.get_object("preferences_sidebar"))
        self.assertEqual(page_stack.get_visible_child_name(), "general")
        titles = []
        for child in page_stack.get_children():
            titles.append(page_stack.child_get_property(child, "title"))
        self.assertEqual(titles, ["General", "Bookmarks", "Blacklist"])
        self.assertIsNotNone(builder.get_object("restore_defaults"))
        preferences_button = builder.get_object("preferences_button")
        self.assertEqual(preferences_button.get_relief(), Gtk.ReliefStyle.NONE)
        self.assertEqual(preferences_button.get_tooltip_text(), "Preferences")
        shortcut_button = builder.get_object("shortcut_button")
        self.assertEqual(shortcut_button.get_tooltip_text(), "Click, then press a shortcut")
        self.assertFalse(builder.get_object("locations_remove").get_sensitive())
        frequency = builder.get_object("frequency_check")
        directories = builder.get_object("directories_check")
        self.assertEqual(frequency.get_label(), "Show frequently opened results first")
        self.assertEqual(directories.get_label(), "Search programs and folders only")
        self.assertEqual(preferences.get_transient_for(), window)
        restore = builder.get_object("restore_defaults")
        close = builder.get_object("preferences_close")
        self.assertIs(close.get_parent(), restore.get_parent())
        self.assertTrue(restore.get_parent().child_get_property(restore, "secondary"))
        self.assertIsNotNone(stack.get_child_by_name("empty"))
        self.assertIsNotNone(stack.get_child_by_name("working"))
        self.assertIsNotNone(stack.get_child_by_name("results"))
        self.assertIsNotNone(stack.get_child_by_name("none"))
        self.assertIsNotNone(stack.get_child_by_name("error"))

    def test_program_icons_share_one_size(self):
        if not os.environ.get("DISPLAY"):
            self.skipTest("needs a display")
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, Gtk
        Gtk.init([])
        module = load_finder_module()
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "program.png")
            pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 128, 128)
            pixbuf.fill(0xff5533ff)
            pixbuf.savev(path, "png", [], [])
            large = search.Result("application", "Large", "", path, path, 1)
            themed = search.Result("application", "Zen", "", "app.zen_browser.zen", "zen.desktop", 1)
            for scale in (1, 2):
                large_image = shown_image(module.result_image(large, scale))
                themed_image = shown_image(module.result_image(themed, scale))
                large_width, large_height = image_size(large_image)
                themed_width, themed_height = image_size(themed_image)
                self.assertEqual(large_width, module.ICON_SIZE)
                self.assertEqual(large_height, module.ICON_SIZE)
                self.assertEqual(themed_width, module.ICON_SIZE)
                self.assertEqual(themed_height, module.ICON_SIZE)
                large_image.get_parent().destroy()
                themed_image.get_parent().destroy()
        finally:
            shutil.rmtree(folder)


def load_finder_module():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "usr",
        "lib",
        "linuxmint",
        "mint-finder",
        "mint-finder.py"
    )
    spec = importlib.util.spec_from_file_location("mint_finder_app", os.path.abspath(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shown_image(image):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    window = Gtk.Window()
    window.add(image)
    window.show_all()
    return image


def image_size(image):
    width = image.get_preferred_width()[1]
    height = image.get_preferred_height()[1]
    return width, height


if __name__ == "__main__":
    unittest.main()
