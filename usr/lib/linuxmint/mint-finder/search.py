#!/usr/bin/python3

import os
import shutil
import subprocess

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio

APP_LIMIT = 64
DIRECTORY_LIMIT = 300
FILE_LIMIT = 300
BOOKMARK_LIMIT = 64
LOCATE_LIMIT = 800
MAX_VISITS = 40000
MAX_DIR_VISITS = 20000
MAX_DEPTH = 30
MIN_FILE_QUERY = 2
BOOKMARK_SCORE = 1000
NAME_MATCH_BONUS = 200
EXACT_NAME_BONUS = 400
WALK_BATCH_SIZE = 24
PER_DIRECTORY_RESULTS = 4
LOCATE_SCAN_LIMIT = 20000
LOCATE_PER_DIRECTORY = 24

SKIP_DIRECTORIES = [
    ".cache",
    "cache",
    "node_modules",
    ".git",
    "__pycache__",
    ".npm",
    ".venv",
    "venv",
    "site-packages",
    "pkgs",
    "Trash",
    ".Trash",
    ".thumbnails",
    "build",
    "intermediates",
    ".backups",
    "dosdevices",
    ".tox",
    "dist",
    ".next",
    "coverage",
    "squashfs-root",
    ".gradle",
    ".m2",
    ".cargo",
    ".rustup",
    "CachedData",
    "Cache",
    "Caches",
    ".cpan",
    "lost+found",
    ".pub-cache",
    "flutter_web_sdk",
    "android_sdk",
    "miniforge3",
    "anaconda3",
    "miniconda3",
    ".pyenv",
    "idlelib"
]

# Path segments that are still searchable but should rank far below real hits.
DEMOTE_DIRECTORIES = [
    "logs",
    "log",
    "debug",
    "obj",
    "deps",
    "third_party",
    "third-party",
    "vendor",
    "engine",
    "out"
]

NOISE_PREFIXES = [
    "/proc/",
    "/sys/",
    "/dev/",
    "/run/"
]


class Result:
    def __init__(self, kind, title, subtitle, icon_name, target, score):
        self.kind = kind
        self.title = title
        self.subtitle = subtitle
        self.icon_name = icon_name
        self.target = target
        self.score = score


class PathSearch:
    def __init__(self):
        self.directories = []
        self.files = []
        self.note = ""


def query_words(query):
    words = []
    if not query:
        return words
    for word in query.split():
        cleaned = word.strip().casefold()
        if cleaned:
            words.append(cleaned)
    return words


def text_matches(words, text):
    if not words:
        return False
    if not text:
        return False
    folded = text.casefold()
    for word in words:
        if word not in folded:
            return False
    return True


def name_matches_word(words, name):
    if not words:
        return False
    if not name:
        return False
    folded = name.casefold()
    for word in words:
        if word in folded:
            return True
    return False


def entry_match_kind(words, name, full_path):
    # Nemo: every keyword in the file or folder name, else one word in the
    # name and every keyword somewhere in the full path.
    if text_matches(words, name):
        return "name"
    if name_matches_word(words, name) and text_matches(words, full_path):
        return "path"
    return ""


def exact_hidden_basename(words, name):
    if not name.startswith("."):
        return False
    if len(words) != 1:
        return False
    word = words[0]
    stripped = name.lstrip(".")
    if stripped.casefold() == word:
        return True
    if name.casefold() == "." + word:
        return True
    return False


def score_text(query, text):
    if not query or not text:
        return 0
    query_folded = query.strip().casefold()
    text_folded = text.casefold()
    if not query_folded or not text_folded:
        return 0
    if text_folded == query_folded:
        return 100
    if text_folded.startswith(query_folded):
        return 80
    if query_folded in text_folded:
        return 50
    return 0


def result_sort_key(result):
    return (-result.score, result.title.casefold(), result.target)


def sort_results(results, counts, by_frequency):
    ranked = []
    for result in results:
        count = 0
        if by_frequency and result.target in counts:
            count = counts[result.target]
        if by_frequency:
            ranked.append((-count, -result.score, result.title.casefold(), result.target, result))
        else:
            ranked.append((-result.score, result.title.casefold(), result.target, result))
    ranked.sort()
    ordered = []
    for item in ranked:
        ordered.append(item[-1])
    return ordered


def config_dir():
    config_home = os.environ.get("XDG_CONFIG_HOME", "")
    if not config_home:
        config_home = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(config_home, "mint-finder")


def legacy_data_dir():
    data_home = os.environ.get("XDG_DATA_HOME", "")
    if not data_home:
        data_home = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(data_home, "mint-finder")


def config_file(name):
    folder = config_dir()
    path = os.path.join(folder, name)
    if os.path.exists(path):
        return path
    legacy = os.path.join(legacy_data_dir(), name)
    if os.path.exists(legacy):
        if not os.path.isdir(folder):
            os.makedirs(folder)
        shutil.copy2(legacy, path)
    return path


def frequency_file():
    return config_file("frequency")


def load_frequencies(path):
    counts = {}
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError:
        return counts
    for line in handle:
        cleaned = line.strip()
        if not cleaned:
            continue
        parts = cleaned.split("\t", 1)
        if len(parts) != 2:
            continue
        if not parts[0].isdigit():
            continue
        counts[parts[1]] = int(parts[0])
    handle.close()
    return counts


def save_frequencies(path, counts):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    lines = []
    for target in counts:
        lines.append(str(counts[target]) + "\t" + target)
    lines.sort()
    text = "\n".join(lines)
    if text:
        text = text + "\n"
    handle = open(path, "w", encoding="utf-8")
    handle.write(text)
    handle.close()


class LaunchFrequency:
    def __init__(self, path):
        self.path = path
        self.counts = load_frequencies(path)

    def record(self, target):
        count = 0
        if target in self.counts:
            count = self.counts[target]
        self.counts[target] = count + 1
        save_frequencies(self.path, self.counts)


def bookmark_file():
    return config_file("bookmarks")


def load_bookmarks(path):
    bookmarks = []
    seen = {}
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError:
        return bookmarks
    for line in handle:
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen[cleaned] = True
        bookmarks.append(cleaned)
    handle.close()
    return bookmarks


def save_bookmarks(path, bookmarks):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    text = "\n".join(bookmarks)
    if text:
        text = text + "\n"
    handle = open(path, "w", encoding="utf-8")
    handle.write(text)
    handle.close()


class Bookmarks:
    def __init__(self, path):
        self.path = path
        self.items = load_bookmarks(path)

    def contains(self, target):
        return target in self.items

    def add(self, target):
        if not target:
            return False
        if target in self.items:
            return False
        self.items.append(target)
        save_bookmarks(self.path, self.items)
        return True

    def remove(self, target):
        if target not in self.items:
            return False
        kept = []
        for item in self.items:
            if item != target:
                kept.append(item)
        self.items = kept
        save_bookmarks(self.path, self.items)
        return True


def take(results, limit):
    chosen = []
    for result in results:
        if len(chosen) >= limit:
            break
        chosen.append(result)
    return chosen


def application_directories():
    directories = []
    data_home = os.environ.get("XDG_DATA_HOME", "")
    if not data_home:
        data_home = os.path.join(os.path.expanduser("~"), ".local", "share")
    directories.append(os.path.join(data_home, "applications"))
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    for item in data_dirs.split(":"):
        if item:
            directories.append(os.path.join(item, "applications"))
    return directories


def desktop_files_in(directory):
    paths = []
    try:
        names = os.listdir(directory)
    except OSError:
        return paths
    for name in names:
        if name.endswith(".desktop"):
            paths.append(os.path.join(directory, name))
    paths.sort()
    return paths


def desktop_names():
    names = []
    current = os.environ.get("XDG_CURRENT_DESKTOP", "")
    for part in current.split(":"):
        if part:
            names.append(part)
    return names


def desktop_list(value):
    items = []
    if not value:
        return items
    for part in value.split(";"):
        if part:
            items.append(part)
    return items


def names_overlap(field, current_names):
    for name in desktop_list(field):
        for current in current_names:
            if name == current:
                return True
    return False


def desktop_is_shown(info):
    current_names = desktop_names()
    only = info.get_string("OnlyShowIn")
    if only and not names_overlap(only, current_names):
        return False
    hidden_on = info.get_string("NotShowIn")
    if hidden_on and names_overlap(hidden_on, current_names):
        return False
    return True


def command_exists(command):
    if not command:
        return False
    if os.path.isabs(command) and os.path.exists(command):
        return True
    if shutil.which(command):
        return True
    return False


def icon_name_from_gicon(icon):
    if isinstance(icon, Gio.ThemedIcon):
        names = icon.get_names()
        if names:
            return names[0]
    if isinstance(icon, Gio.FileIcon):
        file_obj = icon.get_file()
        if file_obj is not None:
            path = file_obj.get_path()
            if path:
                return path
    return "xsi-executable-symbolic"


def keyword_list(info):
    keywords = info.get_keywords()
    if keywords is None:
        return []
    return list(keywords)


def application_score(query, name, generic, comment, keywords, executable):
    words = query_words(query)
    haystack = name
    haystack = haystack + " " + generic
    haystack = haystack + " " + comment
    haystack = haystack + " " + executable
    for keyword in keywords:
        haystack = haystack + " " + keyword
    if not text_matches(words, haystack):
        return 0
    score = score_text(query, name)
    generic_score = score_text(query, generic)
    if generic_score > score:
        score = generic_score
    keyword_score = 0
    for keyword in keywords:
        one = score_text(query, keyword)
        if one > keyword_score:
            keyword_score = one
    if keyword_score > score:
        score = keyword_score - 10
    exec_name = os.path.basename(executable)
    exec_score = score_text(query, exec_name)
    if exec_score > score:
        score = exec_score - 5
    if score < 1:
        score = 30
    return score


def application_subtitle(comment, generic, executable):
    if comment:
        return comment
    if generic:
        return generic
    if executable:
        return executable
    return ""


def load_application(path, query):
    try:
        info = Gio.DesktopAppInfo.new_from_filename(path)
    except TypeError:
        return None, False
    if info is None:
        return None, False
    if info.get_nodisplay() or info.get_is_hidden():
        return None, True
    if not desktop_is_shown(info):
        return None, True
    try_exec = info.get_string("TryExec")
    if try_exec and not command_exists(try_exec):
        return None, True
    name = info.get_display_name()
    if not name:
        name = info.get_name()
    if not name:
        name = os.path.basename(path)
    generic = info.get_string("GenericName")
    if not generic:
        generic = ""
    comment = info.get_string("Comment")
    if not comment:
        comment = ""
    executable = info.get_executable()
    if not executable:
        executable = ""
    keywords = keyword_list(info)
    score = application_score(query, name, generic, comment, keywords, executable)
    if score < 1:
        return None, True
    result = Result(
        "application",
        name,
        application_subtitle(comment, generic, executable),
        icon_name_from_gicon(info.get_icon()),
        path,
        score
    )
    return result, True


def search_applications(query, directories):
    stripped = ""
    if query:
        stripped = query.strip()
    if not stripped:
        return []
    if directories is None:
        directories = application_directories()
    seen = {}
    results = []
    for directory in directories:
        for path in desktop_files_in(directory):
            desktop_id = os.path.basename(path)
            if desktop_id in seen:
                continue
            result, handled = load_application(path, stripped)
            if handled:
                seen[desktop_id] = True
            if result is not None:
                results.append(result)
    results.sort(key=result_sort_key)
    return take(results, APP_LIMIT)


def locate_command():
    for name in ("plocate", "locate"):
        path = shutil.which(name)
        if path:
            return path
    return None


def locate_query(query):
    characters = []
    for character in query:
        if character in "*?[]":
            continue
        characters.append(character)
    return "".join(characters).strip()


def split_lines(text):
    paths = []
    if not text:
        return paths
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            paths.append(cleaned)
    return paths


def locate_patterns(query):
    patterns = []
    for word in query_words(query):
        safe = locate_query(word)
        if len(safe) >= MIN_FILE_QUERY:
            patterns.append(safe)
    if patterns:
        return patterns
    safe = locate_query(query)
    if len(safe) >= MIN_FILE_QUERY:
        return [safe]
    return []


def read_locate(binary, query, limit):
    # plocate AND-matches every pattern against the full path. That is the
    # normal Linux "find this file by name" path (updatedb + locate).
    if isinstance(query, (list, tuple)):
        patterns = []
        for item in query:
            safe = locate_query(item)
            if len(safe) >= MIN_FILE_QUERY:
                patterns.append(safe)
    else:
        patterns = locate_patterns(query)
    if not patterns:
        return []
    try:
        completed = subprocess.run(
            [binary, "-i", "-e", "-N", "-l", str(limit), "--"] + patterns,
            capture_output=True,
            text=True,
            timeout=3,
            check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    error_text = ""
    if completed.stderr:
        error_text = completed.stderr.strip()
    if completed.returncode == 0:
        return split_lines(completed.stdout)
    if completed.returncode == 1 and not error_text:
        return split_lines(completed.stdout)
    return None


def path_is_excluded(path, include_hidden, query=None):
    if is_noise_path(path):
        return True
    if include_hidden:
        return False
    parts = []
    for part in path.split(os.sep):
        if part:
            parts.append(part)
    if not parts:
        return False
    for part in parts[:-1]:
        if part.startswith("."):
            return True
    name = parts[-1]
    if not name.startswith("."):
        return False
    # Exact dotfile lookup: "bashrc" finds ~/.bashrc without enabling all
    # hidden files. Substring matches like "secret" -> .secret.txt stay hidden.
    if query and exact_hidden_basename(query_words(query), name):
        return False
    return True


def is_noise_path(path):
    for prefix in NOISE_PREFIXES:
        if path.startswith(prefix):
            return True
    for part in path.split(os.sep):
        if part in SKIP_DIRECTORIES:
            return True
    return False


def walk_depth(root, current):
    if current == root:
        return 0
    return current[len(root):].count(os.sep)


def walk_one_root(query, root, include_hidden, max_visits, max_depth, directories_only,
                  max_dir_visits, on_batch, batch_size, matches, batch, blocked=None):
    words = query_words(query)
    visits = 0
    dir_visits = 0
    file_share = max_visits
    dir_share = max_dir_visits
    file_counts = {}
    dir_counts = {}

    def flush_batch():
        if not on_batch:
            return
        if not batch:
            return
        on_batch(list(batch))
        del batch[:]

    def add_match(full_path):
        matches.append(full_path)
        batch.append(full_path)
        if len(batch) >= batch_size:
            flush_batch()

    if blocked is None:
        blocked = []
    if not root or not os.path.isdir(root):
        return matches
    if path_is_blocked(root, blocked):
        return matches
    for current, dirs, files in os.walk(root, followlinks=False):
        if max_depth >= 0 and walk_depth(root, current) >= max_depth:
            del dirs[:]
        kept = []
        for name in dirs:
            if name in SKIP_DIRECTORIES:
                continue
            full_path = os.path.join(current, name)
            if path_is_blocked(full_path, blocked):
                continue
            if name.startswith(".") and not include_hidden:
                # Exact hidden folder lookup without descending into it.
                if exact_hidden_basename(words, name) and entry_match_kind(words, name, full_path):
                    dir_visits = dir_visits + 1
                    add_match(full_path)
                continue
            kept.append(name)
        dirs[:] = kept
        # Split the visit budget across the folders directly inside this
        # search root. Otherwise the first folder uses the whole budget.
        key = ""
        if current != root and current.startswith(root + os.sep):
            key = current[len(root) + 1:].split(os.sep)[0]
        if current == root and len(kept) > 1:
            file_share = max_visits // len(kept)
            if file_share < 1:
                file_share = 1
            dir_share = max_dir_visits // len(kept)
            if dir_share < 1:
                dir_share = 1
        if key:
            if file_counts.get(key, 0) >= file_share or dir_counts.get(key, 0) >= dir_share:
                del dirs[:]
                continue
        stop_root = False
        stop_child = False
        for name in kept:
            dir_visits = dir_visits + 1
            if dir_visits > max_dir_visits:
                stop_root = True
                break
            if key:
                dir_counts[key] = dir_counts.get(key, 0) + 1
                if dir_counts[key] > dir_share:
                    stop_child = True
                    break
            full_path = os.path.join(current, name)
            if not entry_match_kind(words, name, full_path):
                continue
            add_match(full_path)
        if stop_root:
            del dirs[:]
            flush_batch()
            return matches
        if stop_child:
            del dirs[:]
        if directories_only:
            continue
        for name in files:
            if key and file_counts.get(key, 0) >= file_share:
                del dirs[:]
                break
            visits = visits + 1
            if visits > max_visits:
                del dirs[:]
                flush_batch()
                return matches
            if key:
                file_counts[key] = file_counts.get(key, 0) + 1
            full_path = os.path.join(current, name)
            if name.startswith(".") and not include_hidden:
                if not exact_hidden_basename(words, name):
                    continue
            if not entry_match_kind(words, name, full_path):
                continue
            add_match(full_path)
    flush_batch()
    return matches


def walk_paths(query, roots, include_hidden, max_visits, max_depth, directories_only=False,
               max_dir_visits=None, on_batch=None, batch_size=None, blocked=None):
    matches = []
    batch = []
    if max_dir_visits is None:
        max_dir_visits = MAX_DIR_VISITS
    if batch_size is None:
        batch_size = WALK_BATCH_SIZE
    if blocked is None:
        blocked = []
    # Each search folder gets its own visit budget so an earlier root
    # cannot starve later ones.
    for root in roots:
        walk_one_root(
            query,
            root,
            include_hidden,
            max_visits,
            max_depth,
            directories_only,
            max_dir_visits,
            on_batch,
            batch_size,
            matches,
            batch,
            blocked
        )
    return matches


def display_path(path, home):
    if home and path == home:
        return "~"
    prefix = home + os.sep
    if home and path.startswith(prefix):
        return "~" + path[len(home):]
    return path


def word_score(word, name):
    folded = name.casefold()
    if word == folded:
        return 100
    if folded.startswith(word):
        return 80
    if word in folded:
        return 50
    return 0


def path_score(query, path, home, anchors=None):
    words = query_words(query)
    name = os.path.basename(path)
    kind = entry_match_kind(words, name, path)
    if not kind:
        return 0
    score = 0
    folded_name = name.casefold()
    for word in words:
        score = score + word_score(word, name)
    if kind == "name":
        score = score + NAME_MATCH_BONUS
        if len(words) == 1 and folded_name == words[0]:
            score = score + EXACT_NAME_BONUS
        elif folded_name == " ".join(words):
            score = score + EXACT_NAME_BONUS
    # Prefer short paths. Deep SDK / build trees should not crowd out real hits.
    depth = path.count(os.sep)
    if depth > 4:
        score = score - ((depth - 4) * 3)
    places = anchors
    if not places:
        places = []
        if home:
            places.append(home)
    bonus = 0
    for anchor in places:
        extra = 0
        if anchor and path == anchor:
            extra = 60
        elif anchor and path.startswith(anchor + os.sep):
            rel_depth = path[len(anchor) + 1:].count(os.sep)
            if rel_depth == 0:
                extra = 80
            elif rel_depth == 1:
                extra = 40
            elif rel_depth == 2:
                extra = 15
        if extra > bonus:
            bonus = extra
    score = score + bonus
    for part in path.split(os.sep):
        if part in DEMOTE_DIRECTORIES:
            score = score - 40
    # A real match should never disappear because of depth penalties.
    if score < 1:
        score = 1
    return score


def kind_for_path(path):
    if os.path.isdir(path):
        return "directory"
    if os.path.isfile(path):
        return "file"
    if os.path.exists(path):
        return "file"
    return None


def result_for_path(query, path, home, include_hidden, kind=None, anchors=None):
    if not path:
        return None
    if path_is_excluded(path, include_hidden, query):
        return None
    if kind is None:
        kind = kind_for_path(path)
    if kind is None:
        return None
    score = path_score(query, path, home, anchors)
    if score < 1:
        return None
    icon_name = "xsi-text-x-generic-symbolic"
    if kind == "directory":
        icon_name = "xsi-folder-symbolic"
    return Result(
        kind,
        os.path.basename(path),
        display_path(path, home),
        icon_name,
        path,
        score
    )


def path_matches_query(query, path):
    words = query_words(query)
    name = os.path.basename(path)
    if entry_match_kind(words, name, path):
        return True
    return False


def filter_located_paths(query, paths):
    matches = []
    seen = {}
    for path in paths:
        if not path or path in seen:
            continue
        seen[path] = True
        if not path_matches_query(query, path):
            continue
        matches.append(path)
    return matches


def rank_paths(query, paths, home, include_hidden, directories_only=False, excluded=None, anchors=None):
    directories = []
    files = []
    seen = {}
    blocked = blocked_roots(excluded)
    for path in paths:
        if not path or path in seen:
            continue
        seen[path] = True
        if path_is_blocked(path, blocked):
            continue
        if not path_matches_query(query, path):
            continue
        if path_is_excluded(path, include_hidden, query):
            continue
        kind = kind_for_path(path)
        if kind is None:
            continue
        if directories_only and kind != "directory":
            continue
        result = result_for_path(query, path, home, include_hidden, kind, anchors)
        if result is None:
            continue
        if result.kind == "directory":
            directories.append(result)
        else:
            files.append(result)
    directories.sort(key=result_sort_key)
    files.sort(key=result_sort_key)
    return directories, files


def spread_results(results, per_directory):
    primary = []
    extra = []
    counts = {}
    if per_directory < 1:
        per_directory = 1
    for result in results:
        parent = os.path.dirname(result.target)
        used = counts.get(parent, 0)
        if used < per_directory:
            counts[parent] = used + 1
            primary.append(result)
        else:
            extra.append(result)
    for result in extra:
        primary.append(result)
    return primary


def take_spread(results, limit, per_directory):
    return take(spread_results(results, per_directory), limit)


def keep_path_sample(paths, limit, per_directory):
    primary = []
    extra = []
    counts = {}
    if per_directory < 1:
        per_directory = 1
    for path in paths:
        parent = os.path.dirname(path)
        used = counts.get(parent, 0)
        if used < per_directory:
            counts[parent] = used + 1
            primary.append(path)
            if len(primary) >= limit:
                return primary
        else:
            extra.append(path)
    for path in extra:
        primary.append(path)
        if len(primary) >= limit:
            break
    return primary


def locate_one(binary, query, patterns, root, limit):
    locate_args = list(patterns)
    if root:
        safe_root = locate_query(root)
        if safe_root and safe_root not in locate_args:
            locate_args.append(safe_root)
    scan_limit = LOCATE_SCAN_LIMIT
    if scan_limit < limit:
        scan_limit = limit
    paths = read_locate(binary, locate_args, scan_limit)
    if paths is None:
        return None
    cleaned = []
    seen = {}
    for path in paths:
        if not path or path in seen:
            continue
        seen[path] = True
        if is_noise_path(path):
            continue
        cleaned.append(path)
    matched = filter_located_paths(query, cleaned)
    return keep_path_sample(matched, limit, LOCATE_PER_DIRECTORY)


def locate_words(binary, query, limit, roots=None):
    patterns = locate_patterns(query)
    if not patterns:
        return []
    if not roots:
        return locate_one(binary, query, patterns, None, limit)
    merged = []
    seen = {}
    found_any = False
    per_root = limit // len(roots)
    if per_root < 40:
        per_root = 40
    if per_root > limit:
        per_root = limit
    for root in roots:
        found = locate_one(binary, query, patterns, root, per_root)
        if found is None:
            continue
        found_any = True
        for path in found:
            if path in seen:
                continue
            seen[path] = True
            merged.append(path)
    if not found_any:
        return None
    return merged


def prune_nested_roots(roots):
    ordered = sorted(roots)
    kept = []
    for root in ordered:
        nested = False
        for parent in kept:
            if root == parent:
                nested = True
                break
            if root.startswith(parent + os.sep):
                nested = True
                break
        if nested:
            continue
        kept.append(root)
    return kept


def resolve_search_roots(locations, home):
    roots = []
    seen = {}
    items = locations
    if items is None:
        if home and os.path.isdir(home):
            return [os.path.abspath(home)]
        return roots
    for item in items:
        if not item:
            continue
        path = os.path.expanduser(item)
        path = os.path.abspath(path)
        if path in seen:
            continue
        if not os.path.isdir(path):
            continue
        seen[path] = True
        roots.append(path)
    return prune_nested_roots(roots)


def path_in_roots(path, roots):
    if not path or not roots:
        return False
    for root in roots:
        if path == root:
            return True
        if path.startswith(root + os.sep):
            return True
    return False


def blocked_roots(locations):
    roots = []
    seen = {}
    if not locations:
        return roots
    for item in locations:
        if not item:
            continue
        path = os.path.abspath(os.path.expanduser(item))
        if path in seen:
            continue
        seen[path] = True
        roots.append(path)
    return prune_nested_roots(roots)


def path_is_blocked(path, blocked):
    if not path or not blocked:
        return False
    full = os.path.abspath(path)
    for root in blocked:
        if full == root:
            return True
        if full.startswith(root + os.sep):
            return True
    return False


def bookmark_results(query, bookmarks, home, include_hidden, directories_only=False, excluded=None):
    results = []
    stripped = ""
    if query:
        stripped = query.strip()
    if not stripped:
        return results
    words = query_words(stripped)
    blocked = blocked_roots(excluded)
    for path in bookmarks:
        if not path:
            continue
        if not os.path.exists(path):
            continue
        if path_is_blocked(path, blocked):
            continue
        kind = kind_for_path(path)
        if kind is None:
            continue
        if directories_only and kind != "directory":
            continue
        if path_is_excluded(path, include_hidden, stripped):
            continue
        name = os.path.basename(path)
        if not entry_match_kind(words, name, path):
            continue
        score = path_score(stripped, path, home)
        if score < 1:
            continue
        icon_name = "xsi-text-x-generic-symbolic"
        if kind == "directory":
            icon_name = "xsi-folder-symbolic"
        results.append(Result(
            "bookmark",
            name,
            display_path(path, home),
            icon_name,
            path,
            BOOKMARK_SCORE + score
        ))
        if len(results) >= BOOKMARK_LIMIT:
            break
    results.sort(key=result_sort_key)
    return results


def emit_path_batches(paths, on_batch, batch_size=None):
    if not on_batch or not paths:
        return
    if batch_size is None:
        batch_size = WALK_BATCH_SIZE
    batch = []
    for path in paths:
        batch.append(path)
        if len(batch) >= batch_size:
            on_batch(list(batch))
            del batch[:]
    if batch:
        on_batch(list(batch))


def keep_located_paths(paths, walk_roots, directories_only, blocked=None):
    kept = []
    if blocked is None:
        blocked = []
    for path in paths:
        if not path_in_roots(path, walk_roots):
            continue
        if path_is_blocked(path, blocked):
            continue
        if directories_only and not os.path.isdir(path):
            continue
        kept.append(path)
    return kept


def collect_paths(query, home, include_hidden, locate_bin=False, walk_roots=None,
                  directories_only=False, search_locations=None, on_batch=None,
                  excluded_locations=None):
    outcome = PathSearch()
    stripped = ""
    if query:
        stripped = query.strip()
    if len(stripped) < MIN_FILE_QUERY:
        outcome.note = "short"
        return outcome
    if walk_roots is None:
        walk_roots = resolve_search_roots(search_locations, home)
    else:
        walk_roots = prune_nested_roots(walk_roots)
    if not walk_roots:
        return outcome
    blocked = blocked_roots(excluded_locations)
    paths = []
    note = "walk"
    locate_hits = 0
    # Prefer the locate index first so hits appear before the folder walk finishes.
    if locate_bin:
        located = locate_words(locate_bin, stripped, LOCATE_LIMIT, walk_roots)
        if located is None:
            note = "walk"
        else:
            note = ""
            kept = keep_located_paths(located, walk_roots, directories_only, blocked)
            locate_hits = len(kept)
            emit_path_batches(kept, on_batch)
            paths.extend(kept)
    # Live walk fills gaps the index has not seen yet. When locate already
    # returned hits, keep the walk shallow so it cannot drown them in noise.
    walk_visits = MAX_VISITS
    walk_depth = MAX_DEPTH
    walk_dir_visits = MAX_DIR_VISITS
    if locate_bin and note == "" and locate_hits > 0:
        walk_visits = 8000
        walk_depth = 8
        walk_dir_visits = 4000
    walked = walk_paths(
        stripped,
        walk_roots,
        include_hidden,
        walk_visits,
        walk_depth,
        directories_only,
        max_dir_visits=walk_dir_visits,
        on_batch=on_batch,
        blocked=blocked
    )
    paths.extend(walked)
    directories, files = rank_paths(
        stripped,
        paths,
        home,
        include_hidden,
        directories_only,
        excluded_locations,
        walk_roots
    )
    outcome.directories = take_spread(directories, DIRECTORY_LIMIT, PER_DIRECTORY_RESULTS)
    if directories_only:
        outcome.files = []
    else:
        outcome.files = take_spread(files, FILE_LIMIT, PER_DIRECTORY_RESULTS)
    outcome.note = note
    return outcome
