#!/usr/bin/python3

import os
import pwd
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "usr", "lib", "linuxmint", "mint-finder"))

import shortcut


class ShortcutTests(unittest.TestCase):
    def test_command_is_finder(self):
        self.assertTrue(shortcut.command_is_finder("mint-finder"))
        self.assertTrue(shortcut.command_is_finder("'mint-finder'"))
        self.assertFalse(shortcut.command_is_finder("nemo"))
        self.assertFalse(shortcut.command_is_finder(""))

    def test_without_shortcut(self):
        self.assertEqual(
            shortcut.without_shortcut(["<Super>space", "Control+space"], "<Super>space"),
            ["Control+space"]
        )
        self.assertEqual(shortcut.without_shortcut(["<Super>space"], "<Super>space"), [])

    def test_input_source_after_removal(self):
        self.assertEqual(
            shortcut.input_source_after_removal(shortcut.INPUT_SOURCE_KEEP),
            shortcut.INPUT_SOURCE_DEFAULT
        )
        self.assertIsNone(shortcut.input_source_after_removal(["<Super>e"]))
        self.assertIsNone(shortcut.input_source_after_removal(None))

    def test_ibus_triggers_after_removal(self):
        self.assertEqual(shortcut.ibus_triggers_after_removal([]), ["<Super>space"])
        self.assertIsNone(shortcut.ibus_triggers_after_removal(["Control+space"]))
        self.assertIsNone(shortcut.ibus_triggers_after_removal(None))

    def test_settings_user_from(self):
        self.assertEqual(shortcut.settings_user_from(1000, "someone", "", ""), "")
        self.assertEqual(shortcut.settings_user_from(0, "someone", "", ""), "someone")
        self.assertEqual(shortcut.settings_user_from(0, "root", "", ""), shortcut.desktop_user())
        info = None
        for entry in pwd.getpwall():
            if entry.pw_uid >= 1000 and entry.pw_uid < 60000:
                info = entry
                break
        if info is not None:
            self.assertEqual(shortcut.settings_user_from(0, "", str(info.pw_uid), ""), info.pw_name)
            self.assertEqual(shortcut.settings_user_from(0, "root", "", str(info.pw_uid)), info.pw_name)

    def test_session_environment_uses_user_home(self):
        info = None
        for entry in pwd.getpwall():
            if entry.pw_uid >= 1000 and entry.pw_uid < 60000:
                info = entry
                break
        if info is None:
            return
        saved = os.environ.get("GSETTINGS_SCHEMA_DIR")
        os.environ["GSETTINGS_SCHEMA_DIR"] = "/tmp/does-not-exist"
        try:
            env = shortcut.session_environment(info.pw_name)
        finally:
            if saved is None:
                os.environ.pop("GSETTINGS_SCHEMA_DIR", None)
            else:
                os.environ["GSETTINGS_SCHEMA_DIR"] = saved
        self.assertEqual(env["HOME"], info.pw_dir)
        self.assertEqual(env["USER"], info.pw_name)
        self.assertEqual(env["XDG_RUNTIME_DIR"], "/run/user/%d" % info.pw_uid)
        self.assertNotIn("GSETTINGS_SCHEMA_DIR", env)
        bus = "/run/user/%d/bus" % info.pw_uid
        if os.path.exists(bus):
            self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=" + bus)


if __name__ == "__main__":
    unittest.main()
