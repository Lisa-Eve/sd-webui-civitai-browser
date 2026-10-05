"""Shared state and logging for CivitAI Browser+.

The `print` and `debug_print` names are part of the public surface: every module
imports them from here. Console behaviour is unchanged, everything additionally
lands in a rotating log file so a running Forge install can be diagnosed after
the fact.
"""

import os
import platform
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler

VERSION = "0.2.0"

from modules.shared import opts

# Read lazily: opts is populated after the extension module is imported, so the
# earlier module-level read frequently saw the default and never enabled debug.
_debug_enabled = None


def debug_enabled():
    global _debug_enabled
    if _debug_enabled is None:
        _debug_enabled = bool(getattr(opts, "civitai_debug_prints", False))
    return _debug_enabled


def refresh_options():
    """Re-read opts after WebUI finished loading its settings."""
    global _debug_enabled
    _debug_enabled = bool(getattr(opts, "civitai_debug_prints", False))


_log_handler = None
_log_path = None


def _log_file_path():
    return os.path.join(os.getcwd(), "config_states", "civitai_browser.log")


def _ensure_log_handler():
    """Attach a rotating file handler once; never raise into the caller."""
    global _log_handler, _log_path
    if _log_handler is not None:
        return _log_handler
    try:
        path = _log_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(_LogFormatter())
        _log_handler = handler
        _log_path = path
        return handler
    except Exception:
        # Logging must never be the reason the extension fails to load.
        _log_handler = False
        return False


def _write_file(level, message):
    handler = _ensure_log_handler()
    if handler:
        try:
            handler.emit(_LogRecord(level, message))
        except Exception:
            pass


class _LogRecord:
    """Minimal record so the formatter is shared by file and console output."""

    def __init__(self, level, message):
        self.levelno = {"INFO": 20, "DEBUG": 10, "ERROR": 40}.get(level, 20)
        self.levelname = level
        self.created = time.time()
        self.getMessage = lambda: message


class _LogFormatter:
    def format(self, record):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        return f"{stamp} {record.levelname:<5} {record.getMessage()}"


def log_path():
    """Absolute path of the active log file, or None if file logging is off."""
    _ensure_log_handler()
    return _log_path if _log_handler else None


_print = print


def print(print_message):
    """Console output, unchanged, plus the log file."""
    try:
        text = str(print_message)
    except Exception:
        text = repr(print_message)
    _write_file("INFO", text)
    _print(f"\033[96mCivitAI Browser+\033[0m: {text}")


def debug_print(print_message):
    """Debug detail. Always written to the log file, console only when enabled."""
    try:
        text = str(print_message)
    except Exception:
        text = repr(print_message)
    _write_file("DEBUG", text)
    if debug_enabled():
        _print(f"\033[96m[DEBUG] CivitAI Browser+\033[0m: {text}")


def log_exception(context, error=None):
    """Record an exception with its traceback without raising it again."""
    if error is None:
        detail = traceback.format_exc()
    else:
        detail = "".join(traceback.format_exception(
            type(error), error, error.__traceback__))
    _write_file("ERROR", f"{context}: {detail.rstrip()}")
    _print(f"\033[91mCivitAI Browser+ ERROR\033[0m: {context}: {error}")


# Settings that are safe to show. Anything that looks like a credential is
# reported as present/absent only, never by value.
_REPORTABLE_OPTS = (
    "civitai_debug_prints", "show_log", "use_aria2", "aria2_flags", "unpack_zip",
    "auto_save_all_img", "split_aria2", "disable_dns", "use_LORA",
    "local_path_in_html", "use_local_html", "civitai_hide_installed",
    "civitai_tile_count", "civitai_new_to_old", "civitai_nsfw", "civitai_tile_view",
    "civitai_token_level", "civitai_alt_view", "civitai_alt_sort",
)


def diagnostics_report(tail_lines=60):
    """Text report for bug reports: version, paths, settings, state, recent log.

    Contains no credentials. Opts are read from an explicit allowlist, and the
    presence of the API key is reported as a boolean only.
    """
    import scripts.civitai_global as gl

    lines = ["=== CivitAI Browser+ diagnostics ===", ""]
    lines.append(f"version: {VERSION}")
    lines.append(f"python:   {sys.version.split()[0]} ({platform.python_implementation()})")
    lines.append(f"platform: {platform.system()} {platform.release()} {platform.machine()}")
    lines.append(f"cwd:      {os.getcwd()}")
    lines.append(f"debug prints enabled: {debug_enabled()}")
    lines.append("")

    lines.append("--- settings (allowlisted, no values) ---")
    for name in _REPORTABLE_OPTS:
        if hasattr(opts, name):
            value = getattr(opts, name)
            if isinstance(value, str) and value:
                value = f"<set, {len(value)} chars>"
            lines.append(f"  {name} = {value}")
    try:
        import scripts.civitai_api as api
        has_key = bool(getattr(api, "civitai_api_key", None)) or bool(
            getattr(opts, "civitai_api_key", None))
        lines.append(f"  civitai api key present: {has_key}")
    except Exception:
        lines.append("  civitai api key present: unknown (api module not importable)")
    lines.append("")

    lines.append("--- state ---")
    for name, getter in (("download_queue", lambda: gl.download_queue),
                         ("isDownloading", lambda: gl.isDownloading),
                         ("cancel_status", lambda: gl.cancel_status),
                         ("download_fail", lambda: gl.download_fail),
                         ("recent_model", lambda: gl.recent_model),
                         ("last_version", lambda: gl.last_version),
                         ("update_items", lambda: gl.update_items)):
        try:
            value = getter()
            if isinstance(value, list):
                value = f"{len(value)} entries"
            lines.append(f"  {name} = {value}")
        except Exception as error:
            lines.append(f"  {name} = <unavailable: {error}>")
    lines.append("")

    lines.append("--- aria2 ---")
    try:
        import subprocess
        probe = subprocess.run(["aria2c", "--version"], capture_output=True,
                               text=True, timeout=5)
        lines.append("  " + (probe.stdout.splitlines() or ["<no version output>"])[0])
    except Exception:
        lines.append("  aria2c not on PATH or not runnable")
    lines.append("")

    path = log_path()
    lines.append(f"--- last {tail_lines} log lines ({path or 'no log file'}) ---")
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                tail = handle.readlines()[-tail_lines:]
            lines.extend(line.rstrip("\n") for line in tail)
        except Exception as error:
            lines.append(f"  <could not read log: {error}>")
    else:
        lines.append("  <no log data>")
    return "\n".join(lines)


def init():
    import warnings
    from urllib3.exceptions import InsecureRequestWarning
    warnings.simplefilter('ignore', InsecureRequestWarning)

    config_folder = os.path.join(os.getcwd(), "config_states")
    if not os.path.exists(config_folder):
        os.mkdir(config_folder)

    global download_queue, last_version, cancel_status, recent_model, last_url, json_data, json_info, main_folder, previous_inputs, download_fail, sortNewest, isDownloading, old_download, scan_files, from_update_tab, url_list, subfolder_json, update_preferred_versions, update_items

    cancel_status = False
    recent_model = None
    json_data = None
    json_info = None
    main_folder = None
    previous_inputs = None
    last_version = None
    url_list = {}
    download_queue = []

    subfolder_json = os.path.join(config_folder, "civitai_subfolders.json")
    if not os.path.exists(subfolder_json):
        with open(subfolder_json, 'w', encoding="utf-8") as json_file:
            json.dump({}, json_file)

    from_update_tab = False
    scan_files = False
    download_fail = False
    sortNewest = False
    isDownloading = False
    old_download = False
    update_preferred_versions = {}
    update_items = []

    _ensure_log_handler()
    print(f"v{VERSION} initialised, log file: {log_path()}")
