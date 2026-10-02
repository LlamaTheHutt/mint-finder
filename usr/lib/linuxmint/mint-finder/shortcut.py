#!/usr/bin/python3

import os
import pwd
import subprocess
import sys

try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except (ImportError, ValueError):
    Gio = None
    GLib = None

PARENT_SCHEMA = "org.cinnamon.desktop.keybindings"
WM_SCHEMA = "org.cinnamon.desktop.keybindings.wm"
IBUS_SCHEMA = "org.freedesktop.ibus.general.hotkey"
COMMAND = "mint-finder"
NAME = "Finder"
DEFAULT_SHORTCUT = "<Super>space"
INPUT_SOURCE_KEEP = ["XF86Keyboard"]
INPUT_SOURCE_DEFAULT = ["<Super>space", "XF86Keyboard"]
KEYBOARD_SETTINGS = "/usr/share/cinnamon/cinnamon-settings/bin"
RUNUSER = "/usr/sbin/runuser"
SESSION_USER_ENV = "MINT_FINDER_SESSION_USER"


def settings_user_from(euid, sudo_user, sudo_uid, pkexec_uid):
    if euid != 0:
        return ""
    if sudo_user and sudo_user != "root":
        return sudo_user
    for value in (sudo_uid, pkexec_uid):
        if value and str(value).isdigit() and str(value) != "0":
            try:
                return pwd.getpwuid(int(value)).pw_name
            except KeyError:
                continue
    return desktop_user()


def desktop_user():
    runtime_root = "/run/user"
    if not os.path.isdir(runtime_root):
        return ""
    names = os.listdir(runtime_root)
    names.sort()
    for name in names:
        if not name.isdigit() or name == "0":
            continue
        bus = os.path.join(runtime_root, name, "bus")
        if not os.path.exists(bus):
            continue
        try:
            return pwd.getpwuid(int(name)).pw_name
        except KeyError:
            continue
    return ""


def session_environment(user):
    info = pwd.getpwnam(user)
    runtime = "/run/user/%d" % info.pw_uid
    env = {}
    names = [
        "PATH",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "DISPLAY",
        "XAUTHORITY",
        "XDG_CURRENT_DESKTOP",
        "XDG_DATA_DIRS",
        "TERM",
    ]
    for name in names:
        value = os.environ.get(name, "")
        if value:
            env[name] = value
    env["HOME"] = info.pw_dir
    env["USER"] = user
    env["LOGNAME"] = user
    env["XDG_RUNTIME_DIR"] = runtime
    env[SESSION_USER_ENV] = user
    bus = os.path.join(runtime, "bus")
    if os.path.exists(bus):
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + bus
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"
    if "XDG_CURRENT_DESKTOP" not in env:
        env["XDG_CURRENT_DESKTOP"] = "X-Cinnamon"
    if "XDG_DATA_DIRS" not in env:
        env["XDG_DATA_DIRS"] = "/usr/local/share:/usr/share"
    return env


def claim_session():
    if os.geteuid() != 0:
        return True
    if os.environ.get(SESSION_USER_ENV, ""):
        return False
    user = settings_user_from(
        os.geteuid(),
        os.environ.get("SUDO_USER", ""),
        os.environ.get("SUDO_UID", ""),
        os.environ.get("PKEXEC_UID", ""),
    )
    if not user or not os.path.exists(RUNUSER):
        return False
    env = session_environment(user)
    command = [RUNUSER, "-u", user, "--preserve-environment", "--", sys.executable, os.path.abspath(__file__)]
    for arg in sys.argv[1:]:
        command.append(arg)
    status = subprocess.call(command, env=env)
    raise SystemExit(status)


def command_is_finder(value):
    if not value:
        return False
    return value.strip("'\"") == COMMAND


def cinnamon_session():
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if "Cinnamon" in desktop:
        return True
    if "X-Cinnamon" in desktop:
        return True
    return False


def copy_list(items):
    copied = []
    if not items:
        return copied
    for item in items:
        copied.append(item)
    return copied


def without_shortcut(bindings, shortcut):
    kept = []
    for item in bindings:
        if item != shortcut:
            kept.append(item)
    return kept


def input_source_after_removal(current):
    if current is None:
        return None
    if copy_list(current) == INPUT_SOURCE_KEEP:
        return INPUT_SOURCE_DEFAULT
    return None


def ibus_triggers_after_removal(current):
    if current is None:
        return None
    if copy_list(current) == []:
        return [DEFAULT_SHORTCUT]
    return None


def load_settings(schema_id, path=None):
    if Gio is None:
        return None
    try:
        if path is None:
            return Gio.Settings.new(schema_id)
        return Gio.Settings.new_with_path(schema_id, path)
    except GLib.Error:
        return None


def free_default_binding(binding):
    if binding != DEFAULT_SHORTCUT:
        return
    settings = load_settings(WM_SCHEMA)
    if settings is None:
        return
    current = copy_list(settings.get_strv("switch-input-source"))
    if len(current) == 0 or DEFAULT_SHORTCUT in current:
        settings.set_strv("switch-input-source", INPUT_SOURCE_KEEP)


def release_ibus_trigger(binding):
    if binding != DEFAULT_SHORTCUT:
        return
    settings = load_settings(IBUS_SCHEMA)
    if settings is None:
        return
    current = copy_list(settings.get_strv("triggers"))
    if binding not in current:
        return
    settings.set_strv("triggers", without_shortcut(current, binding))


def keyboard_table():
    import builtins
    saved = getattr(builtins, "_", None)
    if KEYBOARD_SETTINGS not in sys.path:
        sys.path.insert(0, KEYBOARD_SETTINGS)
    import KeybindingTable
    if saved is not None:
        builtins._ = saved
    return KeybindingTable.get_default()


def custom_shortcuts(table):
    found = []
    for category in table.custom_store:
        for keybinding in category.keybindings:
            found.append(keybinding)
    return found


def finder_shortcut(table):
    for keybinding in custom_shortcuts(table):
        if command_is_finder(keybinding.action):
            return keybinding
    return None


def ensure_cinnamon_shortcut(binding):
    if not binding:
        binding = DEFAULT_SHORTCUT
    free_default_binding(binding)
    release_ibus_trigger(binding)
    try:
        table = keyboard_table()
    except Exception:
        return False
    target = finder_shortcut(table)
    if target is None:
        table.add_custom_keybinding(NAME, COMMAND)
        target = finder_shortcut(table)
    if target is None:
        return False
    if target.label != NAME or target.action != COMMAND:
        target.setDetails(NAME, COMMAND)
    target.setBinding(0, binding)
    if Gio is not None:
        Gio.Settings.sync()
    return True


def remove_cinnamon_shortcut():
    try:
        table = keyboard_table()
    except Exception:
        return False
    targets = []
    for keybinding in custom_shortcuts(table):
        if command_is_finder(keybinding.action):
            targets.append(keybinding)
    for keybinding in targets:
        table.remove_custom_keybinding(keybinding)
    wm = load_settings(WM_SCHEMA)
    if wm is not None:
        restored = input_source_after_removal(wm.get_strv("switch-input-source"))
        if restored is not None:
            wm.set_strv("switch-input-source", restored)
    ibus = load_settings(IBUS_SCHEMA)
    if ibus is not None:
        restored_triggers = ibus_triggers_after_removal(ibus.get_strv("triggers"))
        if restored_triggers is not None:
            ibus.set_strv("triggers", restored_triggers)
    if Gio is not None:
        Gio.Settings.sync()
    return True


if __name__ == "__main__":
    if not claim_session():
        sys.stderr.write("mint-finder: cannot set the keyboard shortcut for the logged-in user\n")
        raise SystemExit(1)
    if len(sys.argv) > 1 and sys.argv[1] == "--remove":
        ok = remove_cinnamon_shortcut()
    else:
        ok = ensure_cinnamon_shortcut(DEFAULT_SHORTCUT)
    if ok:
        raise SystemExit(0)
    raise SystemExit(1)
