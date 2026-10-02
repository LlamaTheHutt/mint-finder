#!/usr/bin/python3

import gettext
import os
import signal
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("XApp", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango, XApp

import search
import shortcut

try:
    gi.require_version("GdkX11", "3.0")
    from gi.repository import GdkX11
except (ValueError, ImportError):
    GdkX11 = None

gettext.install("mint-finder", "/usr/share/linuxmint/locale")

ICON_SIZE = 32
ROW_ESTIMATE = 48
MIN_VISIBLE_RESULTS = 6


def share_dir():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_share = os.path.abspath(os.path.join(script_dir, "..", "..", "..", "share"))
    ui_file = os.path.join(local_share, "linuxmint", "mint-finder", "mint-finder.ui")
    if os.path.exists(ui_file):
        return local_share
    return "/usr/share"


def ui_file():
    return os.path.join(share_dir(), "linuxmint", "mint-finder", "mint-finder.ui")


def icon_file():
    return os.path.join(share_dir(), "icons", "hicolor", "scalable", "apps", "mint-finder.svg")


def load_settings():
    source = Gio.SettingsSchemaSource.get_default()
    if source is None:
        return None
    schema = source.lookup("com.linuxmint.finder", True)
    if schema is None:
        return None
    return Gio.Settings.new("com.linuxmint.finder")


def accelerator_label(accel):
    key, mods = Gtk.accelerator_parse(accel)
    if key == 0:
        return accel
    return Gtk.accelerator_get_label(key, mods)


def session_type():
    return os.environ.get("XDG_SESSION_TYPE")


def grab_keyboard(widget):
    window = widget.get_window()
    if window is None:
        return None, None
    if session_type() == "x11":
        device = Gtk.get_current_event_device()
        if device is None:
            return None, None
        if device.get_source() == Gdk.InputSource.KEYBOARD:
            keyboard = device
        else:
            keyboard = device.get_associated_device()
        if keyboard is None:
            return None, None
        status = keyboard.grab(
            window,
            Gdk.GrabOwnership.WINDOW,
            False,
            Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.KEY_RELEASE_MASK,
            None,
            Gdk.CURRENT_TIME
        )
        if status != Gdk.GrabStatus.SUCCESS:
            return None, None
        return keyboard, None
    display = widget.get_display()
    seat = display.get_default_seat()
    status = seat.grab(
        window,
        Gdk.SeatCapabilities.KEYBOARD,
        False,
        None,
        None,
        None
    )
    if status != Gdk.GrabStatus.SUCCESS:
        return None, None
    return None, seat


def ungrab_keyboard(keyboard, seat):
    if keyboard is not None:
        keyboard.ungrab(Gdk.CURRENT_TIME)
    if seat is not None:
        seat.ungrab()


def launch_result(result):
    if result.kind == "application":
        info = Gio.DesktopAppInfo.new_from_filename(result.target)
        if info is None:
            return False
        return info.launch([], None)
    if not os.path.exists(result.target):
        return False
    uri = GLib.filename_to_uri(result.target, None)
    return Gio.AppInfo.launch_default_for_uri(uri, None)


def show_message(parent, text):
    dialog = Gtk.MessageDialog(
        parent,
        Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        Gtk.MessageType.ERROR,
        Gtk.ButtonsType.CLOSE,
        text
    )
    dialog.run()
    dialog.destroy()


def fallback_icon_name(kind):
    if kind == "directory":
        return "xsi-folder-symbolic"
    if kind == "bookmark":
        return "xsi-user-bookmarks-symbolic"
    if kind == "file":
        return "xsi-text-x-generic-symbolic"
    return "xsi-executable-symbolic"


def image_from_pixbuf(pixbuf, scale):
    surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, scale, None)
    image = Gtk.Image.new_from_surface(surface)
    image.set_pixel_size(ICON_SIZE)
    return image


def image_from_file(path, scale):
    pixels = ICON_SIZE * scale
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, pixels, pixels)
    except GLib.Error:
        return None
    if pixbuf is None:
        return None
    return image_from_pixbuf(pixbuf, scale)


def icon_is_symbolic(icon_name, info):
    if icon_name.endswith("-symbolic"):
        return True
    if info is not None and info.is_symbolic():
        return True
    return False


def load_named_pixbuf(icon_name, scale, context):
    theme = Gtk.IconTheme.get_default()
    if not theme.has_icon(icon_name):
        return None
    try:
        info = theme.lookup_icon_for_scale(
            icon_name,
            ICON_SIZE,
            scale,
            Gtk.IconLookupFlags.FORCE_SIZE
        )
    except GLib.Error:
        return None
    if info is None:
        return None
    if context is not None and icon_is_symbolic(icon_name, info):
        try:
            loaded = info.load_symbolic_for_context(context)
            pixbuf = loaded[0]
        except GLib.Error:
            pixbuf = None
        if pixbuf is not None:
            return pixbuf
    try:
        return info.load_icon()
    except GLib.Error:
        return None


def image_from_icon_name(icon_name, scale, context):
    pixbuf = load_named_pixbuf(icon_name, scale, context)
    if pixbuf is None:
        return None
    return image_from_pixbuf(pixbuf, scale)


def result_image(result, scale, context=None):
    if scale < 1:
        scale = 1
    icon_name = result.icon_name
    image = None
    if icon_name.startswith("/"):
        image = image_from_file(icon_name, scale)
    else:
        image = image_from_icon_name(icon_name, scale, context)
    if image is not None:
        return image
    image = image_from_icon_name(fallback_icon_name(result.kind), scale, context)
    if image is not None:
        return image
    image = Gtk.Image.new_from_icon_name(fallback_icon_name(result.kind), Gtk.IconSize.DND)
    image.set_pixel_size(ICON_SIZE)
    return image


def section_title(kind):
    if kind == "bookmark":
        return _("Bookmarks")
    if kind == "application":
        return _("Programs")
    if kind == "directory":
        return _("Folders")
    return _("Files")


class FinderSettings:
    def __init__(self):
        self.settings = load_settings()
        self.shortcut = "<Super>space"
        self.search_hidden = False
        self.order_by_frequency = True
        self.search_directories_only = False
        self.search_locations = []
        self.excluded_locations = []
        if self.settings is not None:
            self.shortcut = self.settings.get_string("shortcut")
            self.search_hidden = self.settings.get_boolean("search-hidden")
            try:
                self.order_by_frequency = self.settings.get_boolean("order-by-frequency")
            except GLib.Error:
                self.order_by_frequency = True
            try:
                self.search_directories_only = self.settings.get_boolean("search-directories-only")
            except GLib.Error:
                self.search_directories_only = False
            try:
                user_value = self.settings.get_user_value("search-locations")
            except GLib.Error:
                user_value = None
            if user_value is None:
                home = os.path.expanduser("~")
                if os.path.isdir(home):
                    self.set_search_locations([home])
                else:
                    self.search_locations = []
            else:
                try:
                    self.search_locations = list(self.settings.get_strv("search-locations"))
                except GLib.Error:
                    self.search_locations = []
            try:
                self.excluded_locations = list(self.settings.get_strv("excluded-locations"))
            except GLib.Error:
                self.excluded_locations = []
        if not self.search_locations and self.settings is None:
            home = os.path.expanduser("~")
            if os.path.isdir(home):
                self.search_locations = [home]

    def set_shortcut(self, shortcut):
        self.shortcut = shortcut
        if self.settings is not None:
            self.settings.set_string("shortcut", shortcut)

    def set_search_hidden(self, enabled):
        self.search_hidden = enabled
        if self.settings is not None:
            self.settings.set_boolean("search-hidden", enabled)

    def set_order_by_frequency(self, enabled):
        self.order_by_frequency = enabled
        if self.settings is None:
            return
        try:
            self.settings.set_boolean("order-by-frequency", enabled)
        except GLib.Error:
            return

    def set_search_directories_only(self, enabled):
        self.search_directories_only = enabled
        if self.settings is None:
            return
        try:
            self.settings.set_boolean("search-directories-only", enabled)
        except GLib.Error:
            return

    def set_search_locations(self, locations):
        cleaned = []
        seen = {}
        for item in locations:
            if not item:
                continue
            path = os.path.abspath(os.path.expanduser(item))
            if path in seen:
                continue
            seen[path] = True
            cleaned.append(path)
        self.search_locations = cleaned
        if self.settings is None:
            return
        try:
            self.settings.set_strv("search-locations", cleaned)
        except GLib.Error:
            return

    def set_excluded_locations(self, locations):
        cleaned = []
        seen = {}
        for item in locations:
            if not item:
                continue
            path = os.path.abspath(os.path.expanduser(item))
            if path in seen:
                continue
            seen[path] = True
            cleaned.append(path)
        self.excluded_locations = cleaned
        if self.settings is None:
            return
        try:
            self.settings.set_strv("excluded-locations", cleaned)
        except GLib.Error:
            return

    def restore_defaults(self):
        self.shortcut = "<Super>space"
        self.search_hidden = False
        self.order_by_frequency = True
        self.search_directories_only = False
        self.excluded_locations = []
        home = os.path.expanduser("~")
        if os.path.isdir(home):
            self.search_locations = [home]
        else:
            self.search_locations = []
        if self.settings is None:
            return
        keys = [
            "shortcut",
            "search-hidden",
            "order-by-frequency",
            "search-directories-only",
            "search-locations",
            "excluded-locations"
        ]
        for key in keys:
            try:
                self.settings.reset(key)
            except GLib.Error:
                pass
        self.set_shortcut(self.shortcut)
        self.set_search_hidden(self.search_hidden)
        self.set_order_by_frequency(self.order_by_frequency)
        self.set_search_directories_only(self.search_directories_only)
        self.set_search_locations(self.search_locations)
        self.set_excluded_locations(self.excluded_locations)


class FinderWindow:
    def __init__(self, app):
        self.app = app
        self.generation = 0
        self.search_timeout = 0
        self.current_apps = []
        self.pending_bookmarks = []
        self.pending_apps = []
        self.pending_directories = []
        self.pending_files = []
        self.raw_directories = []
        self.raw_files = []
        self.display_limit = MIN_VISIBLE_RESULTS
        self.loading_more = False
        self.capturing = False
        self.capture_keyboard = None
        self.capture_seat = None
        self.updating_prefs = False
        self.allow_hide = False
        self.was_active = False
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain("mint-finder")
        self.builder.add_from_file(ui_file())
        self.window = self.builder.get_object("main_window")
        self.entry = self.builder.get_object("search_entry")
        self.stack = self.builder.get_object("results_stack")
        self.spinner = self.builder.get_object("working_spinner")
        self.results_list = self.builder.get_object("results_list")
        self.results_scroll = self.builder.get_object("results_scroll")
        self.error_label = self.builder.get_object("error_label")
        self.status_label = self.builder.get_object("status_label")
        self.preferences = self.builder.get_object("preferences_dialog")
        self.shortcut_button = self.builder.get_object("shortcut_button")
        self.hidden_check = self.builder.get_object("hidden_check")
        self.frequency_check = self.builder.get_object("frequency_check")
        self.directories_check = self.builder.get_object("directories_check")
        self.locations_list = self.builder.get_object("locations_list")
        self.locations_hint = self.builder.get_object("locations_hint")
        self.locations_add = self.builder.get_object("locations_add")
        self.locations_remove = self.builder.get_object("locations_remove")
        self.bookmarks_list = self.builder.get_object("bookmarks_list")
        self.bookmarks_add = self.builder.get_object("bookmarks_add")
        self.bookmarks_remove = self.builder.get_object("bookmarks_remove")
        self.move_to_blacklist = self.builder.get_object("move_to_blacklist")
        self.excluded_list = self.builder.get_object("excluded_list")
        self.excluded_add = self.builder.get_object("excluded_add")
        self.excluded_remove = self.builder.get_object("excluded_remove")
        self.move_to_bookmarks = self.builder.get_object("move_to_bookmarks")
        self.restore_defaults_button = self.builder.get_object("restore_defaults")
        self.preferences_hint = self.builder.get_object("preferences_hint")
        self.preferences_close = self.builder.get_object("preferences_close")
        self.window.set_application(app)
        self.window.get_style_context().add_class("mint-finder")
        icon = icon_file()
        if os.path.exists(icon):
            self.window.set_icon_from_file(icon)
            self.preferences.set_icon_from_file(icon)
        else:
            self.window.set_icon_name("mint-finder")
            self.preferences.set_icon_name("mint-finder")
        self.entry.connect("changed", self.on_entry_changed)
        self.entry.connect("activate", self.on_entry_activate)
        self.entry.connect("key-press-event", self.on_entry_key)
        self.results_list.connect("row-activated", self.on_row_activated)
        self.results_scroll.get_vadjustment().connect("value-changed", self.on_results_scrolled)
        self.window.connect("delete-event", self.on_delete)
        self.window.connect("focus-out-event", self.on_focus_out)
        self.builder.get_object("preferences_button").connect("clicked", self.on_preferences_clicked)
        self.shortcut_button.connect("clicked", self.on_shortcut_clicked)
        self.shortcut_button.connect("key-press-event", self.on_shortcut_key)
        self.shortcut_button.connect("focus-out-event", self.on_shortcut_focus_out)
        self.preferences.connect("key-press-event", self.on_shortcut_key)
        self.preferences.connect("delete-event", self.on_preferences_delete)
        self.preferences_close.connect("clicked", self.on_preferences_close)
        self.hidden_check.connect("toggled", self.on_hidden_toggled)
        self.frequency_check.connect("toggled", self.on_frequency_toggled)
        self.directories_check.connect("toggled", self.on_directories_toggled)
        self.locations_list.connect("row-selected", self.on_location_selected)
        self.locations_add.connect("clicked", self.on_locations_add)
        self.locations_remove.connect("clicked", self.on_locations_remove)
        self.bookmarks_list.connect("row-selected", self.on_bookmark_selected)
        self.bookmarks_add.connect("clicked", self.on_bookmarks_add)
        self.bookmarks_remove.connect("clicked", self.on_bookmarks_remove)
        self.move_to_blacklist.connect("clicked", self.on_move_to_blacklist)
        self.excluded_list.connect("row-selected", self.on_excluded_selected)
        self.excluded_add.connect("clicked", self.on_excluded_add)
        self.excluded_remove.connect("clicked", self.on_excluded_remove)
        self.move_to_bookmarks.connect("clicked", self.on_move_to_bookmarks)
        self.restore_defaults_button.connect("clicked", self.on_restore_defaults)
        self.preferences.connect("response", self.on_preferences_response)
        self.preferences.set_default(self.preferences_close)
        self.refresh_placeholder()
        self.show_page("empty")
        self.update_status("")

    def present_search(self):
        self.allow_hide = False
        self.generation = self.generation + 1
        self.entry.set_text("")
        self.show_page("empty")
        self.clear_results()
        self.was_active = False
        self.window.set_keep_above(True)
        self.window.show_all()
        self.center_window()
        self.present_window()
        self.entry.grab_focus()
        self.update_status("")
        GLib.timeout_add(400, self.enable_hide)

    def present_window(self):
        gdk_window = self.window.get_window()
        timestamp = 0
        if GdkX11 is not None and gdk_window is not None:
            timestamp = GdkX11.x11_get_server_time(gdk_window)
        if timestamp:
            self.window.present_with_time(timestamp)
            return
        self.window.present()

    def enable_hide(self):
        self.allow_hide = True
        self.was_active = True
        return False

    def hide_search(self):
        self.allow_hide = False
        self.generation = self.generation + 1
        if self.search_timeout:
            GLib.source_remove(self.search_timeout)
            self.search_timeout = 0
        self.window.hide()
        self.app.quit()

    def is_open(self):
        return self.window.get_visible() and self.window.is_active()

    def center_window(self):
        display = self.window.get_display()
        if display is None:
            display = Gdk.Display.get_default()
        monitor = None
        if display is not None:
            seat = display.get_default_seat()
            if seat is not None:
                pointer = seat.get_pointer()
                if pointer is not None:
                    position = pointer.get_position()
                    monitor = display.get_monitor_at_point(position.x, position.y)
            if monitor is None:
                monitor = display.get_primary_monitor()
            if monitor is None and display.get_n_monitors() > 0:
                monitor = display.get_monitor(0)
        if monitor is not None:
            geometry = monitor.get_geometry()
        else:
            geometry = Gdk.Rectangle()
            geometry.x = 0
            geometry.y = 0
            geometry.width = 1280
            geometry.height = 800
        width, height = self.window.get_size()
        if width < 100:
            width = 680
        if height < 100:
            height = 480
        x = geometry.x + (geometry.width - width) / 2
        y = geometry.y + max(48, (geometry.height - height) / 6)
        self.window.move(int(x), int(y))

    def on_delete(self, widget, event):
        self.hide_search()
        return True

    def on_focus_out(self, widget, event):
        if not self.allow_hide:
            return False
        if self.preferences.get_visible():
            return False
        GLib.timeout_add(120, self.hide_if_inactive)
        return False

    def hide_if_inactive(self):
        if not self.allow_hide:
            return False
        if self.preferences.get_visible():
            return False
        if self.window.is_active():
            return False
        self.hide_search()
        return False

    def on_entry_changed(self, entry):
        if self.search_timeout:
            GLib.source_remove(self.search_timeout)
        self.search_timeout = GLib.timeout_add(120, self.on_search_timeout)

    def on_search_timeout(self):
        self.search_timeout = 0
        self.start_search()
        return False

    def start_search(self):
        self.generation = self.generation + 1
        generation = self.generation
        query = self.entry.get_text().strip()
        self.raw_directories = []
        self.raw_files = []
        if not query:
            self.current_apps = []
            self.pending_bookmarks = []
            self.pending_apps = []
            self.pending_directories = []
            self.pending_files = []
            self.clear_results()
            self.show_page("empty")
            self.update_status("")
            return
        try:
            apps = search.search_applications(query, None)
        except OSError as error:
            self.error_label.set_text(str(error))
            self.show_page("error")
            return
        self.current_apps = apps
        home = os.path.expanduser("~")
        include_hidden = self.app.settings.search_hidden
        directories_only = self.app.settings.search_directories_only
        bookmarks = search.bookmark_results(
            query,
            self.app.bookmarks.items,
            home,
            include_hidden,
            directories_only,
            self.app.settings.excluded_locations
        )
        if apps or bookmarks:
            self.fill_results(bookmarks, apps, [], [])
            self.show_page("results")
        else:
            self.show_page("working")
        if len(query) < search.MIN_FILE_QUERY:
            if not apps and not bookmarks:
                self.show_page("none")
            self.update_status("short")
            return
        self.update_status("searching")
        locations = list(self.app.settings.search_locations)
        excluded = list(self.app.settings.excluded_locations)
        thread = threading.Thread(
            target=self.file_search_thread,
            args=(query, generation, home, include_hidden, directories_only, locations, excluded)
        )
        thread.daemon = True
        thread.start()

    def file_search_thread(self, query, generation, home, include_hidden, directories_only, locations, excluded):
        outcome = search.PathSearch()

        def on_batch(paths):
            GLib.idle_add(
                self.apply_path_batch,
                generation,
                query,
                home,
                include_hidden,
                directories_only,
                paths
            )

        try:
            outcome = search.collect_paths(
                query,
                home,
                include_hidden,
                locate_bin=search.locate_command(),
                directories_only=directories_only,
                search_locations=locations,
                on_batch=on_batch,
                excluded_locations=excluded
            )
        except Exception:
            outcome.note = "walk"
        GLib.idle_add(self.apply_paths, generation, outcome)

    def apply_path_batch(self, generation, query, home, include_hidden, directories_only, paths):
        if generation != self.generation:
            return False
        directories, files = search.rank_paths(
            query,
            paths,
            home,
            include_hidden,
            directories_only,
            self.app.settings.excluded_locations,
            self.app.settings.search_locations
        )
        if not directories and not files:
            return False
        seen_dirs = {}
        for item in self.raw_directories:
            seen_dirs[item.target] = True
        for item in directories:
            if item.target in seen_dirs:
                continue
            self.raw_directories.append(item)
            seen_dirs[item.target] = True
        seen_files = {}
        for item in self.raw_files:
            seen_files[item.target] = True
        for item in files:
            if item.target in seen_files:
                continue
            self.raw_files.append(item)
            seen_files[item.target] = True
        bookmarks = search.bookmark_results(
            query,
            self.app.bookmarks.items,
            home,
            include_hidden,
            directories_only,
            self.app.settings.excluded_locations
        )
        self.fill_results(bookmarks, self.current_apps, self.raw_directories, self.raw_files)
        self.show_page("results")
        return False

    def apply_paths(self, generation, outcome):
        if generation != self.generation:
            return False
        query = self.entry.get_text().strip()
        home = os.path.expanduser("~")
        include_hidden = self.app.settings.search_hidden
        directories_only = self.app.settings.search_directories_only
        bookmarks = search.bookmark_results(
            query,
            self.app.bookmarks.items,
            home,
            include_hidden,
            directories_only,
            self.app.settings.excluded_locations
        )
        apps = self.current_apps
        self.fill_results(bookmarks, apps, outcome.directories, outcome.files)
        if not bookmarks and not apps and not outcome.directories and not outcome.files:
            self.show_page("none")
        else:
            self.show_page("results")
        self.update_status(outcome.note)
        return False

    def show_page(self, name):
        self.stack.set_visible_child_name(name)
        if name == "working":
            self.spinner.start()
        else:
            self.spinner.stop()

    def clear_results(self):
        for child in self.results_list.get_children():
            self.results_list.remove(child)

    def ordered_results(self, results):
        counts = {}
        if self.app.settings.order_by_frequency:
            counts = self.app.frequency.counts
        return search.sort_results(results, counts, self.app.settings.order_by_frequency)

    def without_bookmarked(self, results, bookmarks):
        seen = {}
        for item in bookmarks:
            seen[item.target] = True
        kept = []
        for result in results:
            if result.target in seen:
                continue
            kept.append(result)
        return kept

    def visible_budget(self):
        height = self.results_scroll.get_allocated_height()
        if height < 80:
            height = self.window.get_allocated_height() - 120
        if height < 80:
            height = 280
        count = int(height / ROW_ESTIMATE)
        if count < MIN_VISIBLE_RESULTS:
            count = MIN_VISIBLE_RESULTS
        return count

    def total_pending(self):
        total = 0
        total = total + len(self.pending_bookmarks)
        total = total + len(self.pending_apps)
        total = total + len(self.pending_directories)
        total = total + len(self.pending_files)
        return total

    def fill_results(self, bookmarks, apps, directories, files):
        self.raw_directories = list(directories)
        self.raw_files = list(files)
        ordered_bookmarks = self.ordered_results(bookmarks)
        ordered_apps = self.ordered_results(apps)
        ordered_directories = search.spread_results(
            self.without_bookmarked(
                self.ordered_results(directories),
                ordered_bookmarks
            ),
            search.PER_DIRECTORY_RESULTS
        )
        ordered_files = search.spread_results(
            self.without_bookmarked(
                self.ordered_results(files),
                ordered_bookmarks
            ),
            search.PER_DIRECTORY_RESULTS
        )
        self.pending_bookmarks = ordered_bookmarks
        self.pending_apps = ordered_apps
        self.pending_directories = ordered_directories
        self.pending_files = ordered_files
        self.display_limit = self.visible_budget()
        self.render_visible_results(select_first=True, preserve_scroll=False)

    def render_visible_results(self, select_first=False, preserve_scroll=False):
        adjustment = self.results_scroll.get_vadjustment()
        old_value = adjustment.get_value()
        self.clear_results()
        remaining = self.display_limit
        sections = [
            ("bookmark", self.pending_bookmarks),
            ("application", self.pending_apps),
            ("directory", self.pending_directories),
            ("file", self.pending_files)
        ]
        for kind, results in sections:
            if remaining < 1:
                break
            if not results:
                continue
            chunk = []
            index = 0
            while index < len(results) and len(chunk) < remaining:
                chunk.append(results[index])
                index = index + 1
            self.add_section(kind, chunk)
            remaining = remaining - len(chunk)
        if select_first:
            self.select_first()
        if preserve_scroll:
            GLib.idle_add(self.restore_scroll, old_value)

    def restore_scroll(self, value):
        adjustment = self.results_scroll.get_vadjustment()
        upper = adjustment.get_upper()
        page = adjustment.get_page_size()
        maximum = upper - page
        if maximum < 0:
            maximum = 0
        if value > maximum:
            value = maximum
        adjustment.set_value(value)
        return False

    def on_results_scrolled(self, adjustment):
        if self.loading_more:
            return
        if self.stack.get_visible_child_name() != "results":
            return
        total = self.total_pending()
        if self.display_limit >= total:
            return
        upper = adjustment.get_upper()
        page = adjustment.get_page_size()
        value = adjustment.get_value()
        if upper <= page:
            return
        if value + page < upper - 40:
            return
        self.loading_more = True
        self.display_limit = self.display_limit + self.visible_budget()
        self.render_visible_results(select_first=False, preserve_scroll=True)
        self.loading_more = False

    def add_section(self, kind, results):
        if not results:
            return
        label = Gtk.Label(label=section_title(kind), xalign=0)
        label.set_margin_top(8)
        label.set_margin_bottom(2)
        label.set_margin_start(8)
        label.get_style_context().add_class("dim-label")
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row.add(label)
        row.show_all()
        self.results_list.add(row)
        for result in results:
            self.add_result_row(result)

    def add_result_row(self, result):
        row = Gtk.ListBoxRow()
        row.result = result
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        scale = self.window.get_scale_factor()
        image = result_image(result, scale, self.window.get_style_context())
        image.set_pixel_size(ICON_SIZE)
        box.pack_start(image, False, False, 0)
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=result.title, xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle = Gtk.Label(label=result.subtitle, xalign=0)
        subtitle.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        subtitle.get_style_context().add_class("dim-label")
        text_box.pack_start(title, False, False, 0)
        text_box.pack_start(subtitle, False, False, 0)
        box.pack_start(text_box, True, True, 0)
        if result.kind != "application":
            bookmark_button = self.bookmark_button(result)
            box.pack_end(bookmark_button, False, False, 0)
            skip_button = self.skip_button(result)
            if skip_button is not None:
                box.pack_end(skip_button, False, False, 0)
        row.add(box)
        row.show_all()
        self.results_list.add(row)

    def bookmark_button(self, result):
        bookmarked = self.app.bookmarks.contains(result.target)
        if bookmarked:
            icon_name = "xsi-starred-symbolic"
            tooltip = _("Remove bookmark")
        else:
            icon_name = "xsi-non-starred-symbolic"
            tooltip = _("Add bookmark")
        button = Gtk.Button.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.get_style_context().add_class("image-button")
        button.get_style_context().add_class("flat")
        button.set_focus_on_click(False)
        button.set_valign(Gtk.Align.CENTER)
        button.set_tooltip_text(tooltip)
        button.result = result
        button.connect("button-press-event", self.on_bookmark_press)
        return button

    def skip_folder_for(self, result):
        path = result.target
        if not path:
            return None
        if os.path.isdir(path):
            folder = os.path.abspath(path)
        else:
            folder = os.path.dirname(os.path.abspath(path))
        if not folder or folder == os.sep:
            return None
        return folder

    def skip_button(self, result):
        folder = self.skip_folder_for(result)
        if folder is None:
            return None
        button = Gtk.Button.new_from_icon_name("xsi-process-stop-symbolic", Gtk.IconSize.BUTTON)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.get_style_context().add_class("image-button")
        button.get_style_context().add_class("flat")
        button.set_focus_on_click(False)
        button.set_valign(Gtk.Align.CENTER)
        if os.path.isdir(result.target):
            button.set_tooltip_text(_("Blacklist this folder"))
        else:
            button.set_tooltip_text(_("Blacklist the folder this file is in"))
        button.skip_path = folder
        button.connect("button-press-event", self.on_skip_press)
        return button

    def on_skip_press(self, button, event):
        if event.button != 1:
            return False
        path = button.skip_path
        if not path:
            return True
        locations = list(self.app.settings.excluded_locations)
        if path not in locations:
            locations.append(path)
        self.app.settings.set_excluded_locations(locations)
        if self.preferences.get_visible():
            self.refresh_excluded_list()
        if self.entry.get_text().strip():
            self.start_search()
        return True

    def on_bookmark_press(self, button, event):
        if event.button != 1:
            return False
        result = button.result
        if self.app.bookmarks.contains(result.target):
            self.app.bookmarks.remove(result.target)
        else:
            self.app.bookmarks.add(result.target)
        query = self.entry.get_text().strip()
        if query:
            home = os.path.expanduser("~")
            bookmarks = search.bookmark_results(
                query,
                self.app.bookmarks.items,
                home,
                self.app.settings.search_hidden,
                self.app.settings.search_directories_only,
                self.app.settings.excluded_locations
            )
            self.fill_results(
                bookmarks,
                self.current_apps,
                self.raw_directories,
                self.raw_files
            )
        if self.preferences.get_visible():
            self.refresh_bookmarks_list()
        return True

    def result_rows(self):
        rows = []
        index = 0
        row = self.results_list.get_row_at_index(index)
        while row is not None:
            if row.get_selectable():
                rows.append(row)
            index = index + 1
            row = self.results_list.get_row_at_index(index)
        return rows

    def select_first(self):
        rows = self.result_rows()
        if rows:
            self.results_list.select_row(rows[0])

    def move_selection(self, direction):
        rows = self.result_rows()
        if not rows:
            return
        selected = self.results_list.get_selected_row()
        current = 0
        index = 0
        for row in rows:
            if row == selected:
                current = index
            index = index + 1
        next_index = current + direction
        if next_index < 0:
            next_index = 0
        if next_index >= len(rows):
            next_index = len(rows) - 1
        chosen = rows[next_index]
        self.results_list.select_row(chosen)
        self.scroll_to_row(chosen)

    def scroll_to_row(self, row):
        allocation = row.get_allocation()
        if allocation.height < 1:
            return
        adjustment = self.results_scroll.get_vadjustment()
        y = allocation.y
        page = adjustment.get_page_size()
        value = adjustment.get_value()
        if y < value:
            adjustment.set_value(y)
        elif y + allocation.height > value + page:
            adjustment.set_value(y + allocation.height - page)

    def on_entry_key(self, entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide_search()
            return True
        if event.keyval == Gdk.KEY_Down:
            self.move_selection(1)
            return True
        if event.keyval == Gdk.KEY_Up:
            self.move_selection(-1)
            return True
        return False

    def on_entry_activate(self, entry):
        self.open_selected()

    def on_row_activated(self, listbox, row):
        if not row.get_selectable():
            return
        self.open_row(row)

    def open_selected(self):
        row = self.results_list.get_selected_row()
        if row is None or not row.get_selectable():
            rows = self.result_rows()
            if not rows:
                return
            row = rows[0]
        self.open_row(row)

    def open_row(self, row):
        result = row.result
        opened = False
        try:
            opened = launch_result(result)
        except GLib.Error:
            opened = False
        if not opened:
            show_message(self.window, _("Could not open %s") % result.title)
            return
        self.app.frequency.record(result.target)
        self.hide_search()

    def shortcut_status(self):
        if self.app.shortcut_bound:
            label = accelerator_label(self.app.settings.shortcut)
            return _("Shortcut: %s") % label
        return _("Bind the mint-finder command in Keyboard settings")

    def update_status(self, note):
        if note == "walk":
            if self.app.settings.search_locations:
                self.status_label.set_text(_("Showing results from your search folders"))
            else:
                self.status_label.set_text(_("Add a search folder in Preferences"))
            return
        if note == "short":
            if self.app.settings.search_directories_only:
                self.status_label.set_text(_("Type one more letter to search folders"))
            else:
                self.status_label.set_text(_("Type one more letter to search files and folders"))
            return
        if note == "searching":
            if self.app.settings.search_directories_only:
                self.status_label.set_text(_("Searching folders..."))
            else:
                self.status_label.set_text(_("Searching files and folders..."))
            return
        self.status_label.set_text(self.shortcut_status())

    def refresh_placeholder(self):
        empty_label = self.builder.get_object("empty_label")
        none_label = self.builder.get_object("none_label")
        if self.app.settings.search_directories_only:
            text = _("Search programs and folders")
            none_text = _("No matching programs or folders")
        else:
            text = _("Search programs, files, and folders")
            none_text = _("No matching programs, files, or folders")
        self.entry.set_placeholder_text(text)
        empty_label.set_text(text)
        none_label.set_text(none_text)

    def on_preferences_clicked(self, button):
        self.open_preferences()

    def open_preferences(self):
        self.stop_shortcut_capture()
        self.updating_prefs = True
        self.hidden_check.set_active(self.app.settings.search_hidden)
        self.frequency_check.set_active(self.app.settings.order_by_frequency)
        self.directories_check.set_active(self.app.settings.search_directories_only)
        self.updating_prefs = False
        self.refresh_locations_list()
        self.refresh_bookmarks_list()
        self.refresh_excluded_list()
        self.refresh_shortcut_button()
        self.refresh_hint()
        self.preferences.show_all()
        self.preferences.present()

    def clear_locations_list(self):
        for child in self.locations_list.get_children():
            self.locations_list.remove(child)

    def refresh_locations_list(self, select_path=None):
        self.clear_locations_list()
        home = os.path.expanduser("~")
        locations = self.app.settings.search_locations
        if not locations:
            label = Gtk.Label(label=_("No folders selected"), xalign=0)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            label.get_style_context().add_class("dim-label")
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            row.path = None
            row.add(label)
            row.show_all()
            self.locations_list.add(row)
            self.update_locations_remove()
            return
        chosen = None
        first = None
        for path in locations:
            label = Gtk.Label(label=search.display_path(path, home), xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            row = Gtk.ListBoxRow()
            row.path = path
            row.add(label)
            row.show_all()
            self.locations_list.add(row)
            if first is None:
                first = row
            if path == select_path:
                chosen = row
        if chosen is None:
            chosen = first
        if chosen is not None:
            self.locations_list.select_row(chosen)
        self.update_locations_remove()

    def on_location_selected(self, box, row):
        self.update_locations_remove()

    def update_locations_remove(self):
        row = self.locations_list.get_selected_row()
        if row is None or row.path is None:
            self.locations_remove.set_sensitive(False)
            return
        self.locations_remove.set_sensitive(True)

    def on_locations_add(self, button):
        dialog = Gtk.FileChooserDialog(
            title=_("Add search folder"),
            parent=self.preferences,
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Add"), Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        folder = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            return
        if not folder:
            return
        locations = list(self.app.settings.search_locations)
        path = os.path.abspath(folder)
        if path not in locations:
            locations.append(path)
        self.app.settings.set_search_locations(locations)
        self.refresh_locations_list(path)
        if self.entry.get_text().strip():
            self.start_search()

    def on_locations_remove(self, button):
        row = self.locations_list.get_selected_row()
        if row is None or row.path is None:
            return
        locations = []
        for item in self.app.settings.search_locations:
            if item != row.path:
                locations.append(item)
        self.app.settings.set_search_locations(locations)
        self.refresh_locations_list()
        if self.entry.get_text().strip():
            self.start_search()

    def clear_bookmarks_list(self):
        for child in self.bookmarks_list.get_children():
            self.bookmarks_list.remove(child)

    def refresh_bookmarks_list(self, select_path=None):
        self.clear_bookmarks_list()
        home = os.path.expanduser("~")
        items = self.app.bookmarks.items
        if not items:
            label = Gtk.Label(label=_("No bookmarks"), xalign=0)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            label.get_style_context().add_class("dim-label")
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            row.path = None
            row.add(label)
            row.show_all()
            self.bookmarks_list.add(row)
            self.update_move_to_blacklist()
            return
        chosen = None
        first = None
        for path in items:
            label = Gtk.Label(label=search.display_path(path, home), xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            row = Gtk.ListBoxRow()
            row.path = path
            row.add(label)
            row.show_all()
            self.bookmarks_list.add(row)
            if first is None:
                first = row
            if path == select_path:
                chosen = row
        if chosen is None:
            chosen = first
        if chosen is not None:
            self.bookmarks_list.select_row(chosen)
        self.update_move_to_blacklist()

    def on_bookmark_selected(self, box, row):
        self.update_move_to_blacklist()

    def update_move_to_blacklist(self):
        row = self.bookmarks_list.get_selected_row()
        if row is None or row.path is None:
            self.bookmarks_remove.set_sensitive(False)
            self.move_to_blacklist.set_sensitive(False)
            return
        self.bookmarks_remove.set_sensitive(True)
        self.move_to_blacklist.set_sensitive(True)

    def blacklist_folder_for_path(self, path):
        if not path:
            return None
        if os.path.isdir(path):
            folder = os.path.abspath(path)
        else:
            folder = os.path.dirname(os.path.abspath(path))
        if not folder or folder == os.sep:
            return None
        return folder

    def on_bookmarks_add(self, button):
        dialog = Gtk.FileChooserDialog(
            title=_("Add bookmark"),
            parent=self.preferences,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Add"), Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        chosen = dialog.get_filename()
        if not chosen:
            chosen = dialog.get_current_folder()
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            return
        if not chosen:
            return
        path = os.path.abspath(chosen)
        self.app.bookmarks.add(path)
        self.refresh_bookmarks_list(path)
        if self.entry.get_text().strip():
            self.start_search()

    def on_bookmarks_remove(self, button):
        row = self.bookmarks_list.get_selected_row()
        if row is None or row.path is None:
            return
        self.app.bookmarks.remove(row.path)
        self.refresh_bookmarks_list()
        if self.entry.get_text().strip():
            self.start_search()

    def on_move_to_blacklist(self, button):
        row = self.bookmarks_list.get_selected_row()
        if row is None or row.path is None:
            return
        folder = self.blacklist_folder_for_path(row.path)
        if folder is None:
            return
        self.app.bookmarks.remove(row.path)
        locations = list(self.app.settings.excluded_locations)
        if folder not in locations:
            locations.append(folder)
        self.app.settings.set_excluded_locations(locations)
        self.refresh_bookmarks_list()
        self.refresh_excluded_list(folder)
        if self.entry.get_text().strip():
            self.start_search()

    def on_move_to_bookmarks(self, button):
        row = self.excluded_list.get_selected_row()
        if row is None or row.path is None:
            return
        path = row.path
        self.app.bookmarks.add(path)
        locations = []
        for item in self.app.settings.excluded_locations:
            if item != path:
                locations.append(item)
        self.app.settings.set_excluded_locations(locations)
        self.refresh_bookmarks_list(path)
        self.refresh_excluded_list()
        if self.entry.get_text().strip():
            self.start_search()

    def clear_excluded_list(self):
        for child in self.excluded_list.get_children():
            self.excluded_list.remove(child)

    def refresh_excluded_list(self, select_path=None):
        self.clear_excluded_list()
        home = os.path.expanduser("~")
        locations = self.app.settings.excluded_locations
        if not locations:
            label = Gtk.Label(label=_("No blacklisted folders"), xalign=0)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            label.get_style_context().add_class("dim-label")
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            row.path = None
            row.add(label)
            row.show_all()
            self.excluded_list.add(row)
            self.update_excluded_remove()
            return
        chosen = None
        first = None
        for path in locations:
            label = Gtk.Label(label=search.display_path(path, home), xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            row = Gtk.ListBoxRow()
            row.path = path
            row.add(label)
            row.show_all()
            self.excluded_list.add(row)
            if first is None:
                first = row
            if path == select_path:
                chosen = row
        if chosen is None:
            chosen = first
        if chosen is not None:
            self.excluded_list.select_row(chosen)
        self.update_excluded_remove()

    def on_excluded_selected(self, box, row):
        self.update_excluded_remove()

    def update_excluded_remove(self):
        row = self.excluded_list.get_selected_row()
        if row is None or row.path is None:
            self.excluded_remove.set_sensitive(False)
            self.move_to_bookmarks.set_sensitive(False)
            return
        self.excluded_remove.set_sensitive(True)
        self.move_to_bookmarks.set_sensitive(True)

    def on_excluded_add(self, button):
        dialog = Gtk.FileChooserDialog(
            title=_("Blacklist folder"),
            parent=self.preferences,
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Add"), Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        folder = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            return
        if not folder:
            return
        locations = list(self.app.settings.excluded_locations)
        path = os.path.abspath(folder)
        if path not in locations:
            locations.append(path)
        self.app.settings.set_excluded_locations(locations)
        self.refresh_excluded_list(path)
        if self.entry.get_text().strip():
            self.start_search()

    def on_excluded_remove(self, button):
        row = self.excluded_list.get_selected_row()
        if row is None or row.path is None:
            return
        locations = []
        for item in self.app.settings.excluded_locations:
            if item != row.path:
                locations.append(item)
        self.app.settings.set_excluded_locations(locations)
        self.refresh_excluded_list()
        if self.entry.get_text().strip():
            self.start_search()

    def on_restore_defaults(self, button):
        self.app.settings.restore_defaults()
        self.app.bind_shortcut()
        self.updating_prefs = True
        self.hidden_check.set_active(self.app.settings.search_hidden)
        self.frequency_check.set_active(self.app.settings.order_by_frequency)
        self.directories_check.set_active(self.app.settings.search_directories_only)
        self.updating_prefs = False
        self.refresh_locations_list()
        self.refresh_bookmarks_list()
        self.refresh_excluded_list()
        self.refresh_shortcut_button()
        self.refresh_hint()
        self.refresh_placeholder()
        self.update_status("")
        if self.entry.get_text().strip():
            self.start_search()

    def on_preferences_close(self, button):
        self.close_preferences()

    def on_preferences_delete(self, widget, event):
        self.close_preferences()
        return True

    def on_preferences_response(self, dialog, response):
        if not dialog.get_visible():
            return
        self.close_preferences()

    def close_preferences(self):
        self.stop_shortcut_capture()
        self.refresh_shortcut_button()
        self.preferences.hide()

    def stop_shortcut_capture(self):
        self.capturing = False
        ungrab_keyboard(self.capture_keyboard, self.capture_seat)
        self.capture_keyboard = None
        self.capture_seat = None

    def on_shortcut_clicked(self, button):
        if self.capturing:
            self.stop_shortcut_capture()
            self.refresh_shortcut_button()
            return
        self.shortcut_button.grab_focus()
        keyboard, seat = grab_keyboard(self.shortcut_button)
        self.capture_keyboard = keyboard
        self.capture_seat = seat
        self.capturing = True
        self.shortcut_button.set_label(_("Press a shortcut"))

    def on_shortcut_focus_out(self, widget, event):
        if not self.capturing:
            return False
        self.stop_shortcut_capture()
        self.refresh_shortcut_button()
        return False

    def on_shortcut_key(self, widget, event):
        if not self.capturing:
            if event.keyval == Gdk.KEY_Escape:
                self.close_preferences()
                return True
            return False
        if event.keyval == Gdk.KEY_Escape:
            self.stop_shortcut_capture()
            self.refresh_shortcut_button()
            return True
        if event.is_modifier:
            return True
        mask = event.state & Gtk.accelerator_get_default_mod_mask()
        if not Gtk.accelerator_valid(event.keyval, mask):
            return True
        accel = Gtk.accelerator_name(event.keyval, mask)
        self.app.settings.set_shortcut(accel)
        self.app.bind_shortcut()
        self.stop_shortcut_capture()
        self.refresh_shortcut_button()
        self.refresh_hint()
        self.update_status("")
        return True

    def refresh_shortcut_button(self):
        if self.capturing:
            self.shortcut_button.set_label(_("Press a shortcut"))
            return
        self.shortcut_button.set_label(accelerator_label(self.app.settings.shortcut))

    def refresh_hint(self):
        if self.app.shortcut_bound:
            self.preferences_hint.set_text(_("Cinnamon opens Finder with this shortcut."))
            return
        self.preferences_hint.set_text(_("Bind the mint-finder command in Keyboard settings."))

    def on_hidden_toggled(self, check):
        if self.updating_prefs:
            return
        self.app.settings.set_search_hidden(check.get_active())
        if self.entry.get_text().strip():
            self.start_search()

    def on_frequency_toggled(self, check):
        if self.updating_prefs:
            return
        self.app.settings.set_order_by_frequency(check.get_active())
        if self.entry.get_text().strip():
            self.start_search()

    def on_directories_toggled(self, check):
        if self.updating_prefs:
            return
        self.app.settings.set_search_directories_only(check.get_active())
        self.refresh_placeholder()
        if self.entry.get_text().strip():
            self.start_search()


class FinderApplication(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(
            self,
            application_id="com.linuxmint.finder",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )
        self.add_main_option(
            "preferences",
            ord("p"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Open preferences",
            None
        )
        self.settings = FinderSettings()
        self.frequency = search.LaunchFrequency(search.frequency_file())
        self.bookmarks = search.Bookmarks(search.bookmark_file())
        self.finder = None
        self.shortcut_bound = False

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.bind_shortcut()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.on_sigint)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.on_sigint)

    def on_sigint(self):
        self.quit()
        return False

    def ensure_window(self):
        if self.finder is None:
            self.finder = FinderWindow(self)

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        self.ensure_window()
        if options.contains("preferences"):
            if not self.finder.window.get_visible():
                self.finder.present_search()
            self.finder.open_preferences()
            return 0
        if self.finder.is_open():
            self.finder.hide_search()
            return 0
        self.finder.present_search()
        return 0

    def do_activate(self):
        self.ensure_window()
        self.finder.present_search()

    def bind_shortcut(self):
        binding = self.settings.shortcut
        self.shortcut_bound = False
        if shortcut.cinnamon_session():
            self.shortcut_bound = shortcut.ensure_cinnamon_shortcut(binding)
        if self.finder is not None:
            self.finder.update_status("")
            if self.finder.preferences.get_visible():
                self.finder.refresh_hint()


def main(argv):
    GLib.set_prgname("mint-finder")
    app = FinderApplication()
    return app.run(argv)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
