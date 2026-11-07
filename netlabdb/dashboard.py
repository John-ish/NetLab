import getpass
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from rich.color import Color
from rich.text import Text

from .config import APP_VERSION, LAYOUT_PATH, ensure_private_dir
from .fonts import fit
from .helpers import fmt_duration
from .presets import PRESETS
from .settings import settings
from .state import HOSTS, SERVICES
from .theme import ACCENT_NAMES, PALETTE, THEME_SPECS, THEME_STATE, blend_hex


DEFAULT_TITLE = "NETLAB"
DEFAULT_WIDTH = 72
SESSION_START = time.monotonic()

DEFAULT_MENU = [
    {"icon": "◉", "label": "Hosts", "key": "h", "action": "hosts"},
    {"icon": "◈", "label": "Services", "key": "s", "action": "services"},
    {"icon": "≡", "label": "Logs", "key": "l", "action": "logs"},
    {"icon": "+", "label": "New host", "key": "a", "action": "new_host"},
    {"icon": "◇", "label": "Settings", "key": "t", "action": "settings"},
    {"icon": "✕", "label": "Quit", "key": "q", "action": "quit"},
]

DEFAULT_TIPS = [
    "Press [m] on any screen to open the main menu",
    "Press [/] to search hosts, services and logs",
    "Select a service and press [v] to reveal its password",
    "Press [i] on a host or service to change its check interval",
    "Press [r] on a host to run a check right now",
    "Turn the CRT effect on or off in Settings",
    "Change this logo, tagline and footer in Settings",
    "Press [l] in Settings to design the whole dashboard in a layout file",
]

DATE_FORMATS = {
    "datetime": "%a %d %b  %H:%M:%S",
    "time": "%H:%M:%S",
    "date": "%a %d %b %Y",
    "iso": "%Y-%m-%d %H:%M:%S",
    "twelve": "%a %d %b  %I:%M:%S %p",
}

FOOTER_PRESETS = {
    "system": "{system}", "host": "{hostname}", "user": "{user}", "python": "Python {python}",
    "datetime": "{datetime}", "time": "{time}", "date": "{date}", "iso": "{iso}",
    "twelve": "{twelve}", "session": "up {session}", "off": "",
}

PRIORITY = {
    "logo": 0, "menu": 0, "columns": 0, "tagline": 1, "summary": 2, "footer": 3, "text": 3, "art": 3,
    "hosts": 3, "alerts": 3, "stats": 3, "activity": 4, "spacer": 4, "tip": 5,
}
SINGLE = {"logo", "tagline", "menu", "summary", "activity", "tip", "footer"}
LISTS = ("activity", "hosts", "alerts")
ALIGNS = ("left", "center", "right")
BORDERS = ("round", "solid", "double", "heavy", "dashed", "ascii")
PLACEHOLDER = re.compile(r"\{(\w+|now:[^}]*)\}")
WIDTH_VALUE = re.compile(r"^\d+(%|fr)?$")

LAYOUT_HELP = [
    "Edit this file while NETLAB is running and the dashboard updates live.",
    "preset: the name of a built-in layout (" + ", ".join(PRESETS) + "). It is used when 'sections' is left out. Delete 'preset' and write your own 'sections' to customize.",
    "sections run top to bottom. types: logo, tagline, menu, summary, activity, hosts, alerts, stats, tip, footer, text, art, spacer, columns.",
    "logo, tagline, menu, summary, activity, tip and footer can appear once. the others can repeat.",
    "columns: {\"type\": \"columns\", \"gap\": 4, \"valign\": \"middle\", \"columns\": [{\"width\": \"1fr\", \"sections\": [...]}, {\"width\": \"1fr\", \"sections\": [...]}]}. width is cells, a percentage or fr units. columns cannot be nested.",
    "every section accepts: align (left, center, right), margin (blank rows above), width, padding, border (round, solid, double, heavy, dashed, ascii), border_color, title (the border title), priority (higher hides first when the terminal is short) and min_height (hide below this many terminal rows).",
    "logo: text, font (block, compact, plain or fig:NAME with pyfiglet), color, fill_color. Or art (list of lines) / art_file (a file in ~/.netlabdb) for your own ASCII art. art sections take lines the same way.",
    "tagline: text, version, cursor. summary: optional text. tip: tips (list), seconds, icon. activity, hosts and alerts: lines, title. hosts also takes sort (status, name, latency). stats shows fleet meters.",
    "menu: items with icon, label, key and action (hosts, services, logs, settings, new_host, quit). keys: false hides the key column. label_align: left or center.",
    "footer: left, right (system, host, user, python, datetime, time, date, iso, twelve, session, custom, off or any text), left_text, right_text, separator.",
    "text: text (use \\n for new lines), color, bold. spacer: height.",
    "placeholders usable in any text: {user} {hostname} {system} {python} {version} {time} {date} {datetime} {iso} {session} {hosts} {online} {warning} {offline} {services} {services_up} {services_down} {services_warning} {avg_latency} and {now:%H:%M} for any strftime format.",
    "colors: accent, ok, warn, bad, muted, red, green, yellow, blue, magenta, cyan or a #hex value.",
]


class Layout:

    def __init__(self, sections: list, width: int, error: str | None = None, source: str = "settings"):
        self.sections = sections
        self.width = width
        self.error = error
        self.source = source
        self.signature = json.dumps([sections, width], sort_keys=True, default=str)

    def walk(self):
        for section in self.sections:
            if section["type"] == "columns":
                for column in section["columns"]:
                    yield from column["sections"]
            else:
                yield section

    def first(self, kind: str) -> dict | None:
        return next((s for s in self.walk() if s["type"] == kind), None)


def _int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _flag(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _text(value, default: str = "", limit: int = 400) -> str:
    return default if value is None else str(value)[:limit]


def _width(value):
    if isinstance(value, bool) or value in (None, ""):
        return ""
    text = str(value).strip()
    if not WIDTH_VALUE.match(text):
        return ""
    return int(text) if text.isdigit() else text


def _art(raw: dict, errors: list) -> list[str] | None:
    lines = raw.get("art")
    if isinstance(lines, str):
        lines = lines.split("\n")
    if lines is None and raw.get("art_file"):
        path = Path(str(raw["art_file"])).expanduser()
        if not path.is_absolute():
            path = LAYOUT_PATH.parent / path
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"art file {path.name}: {getattr(error, 'strerror', None) or error}")
            return None
    if not isinstance(lines, list):
        return None
    lines = [str(line).expandtabs(4).rstrip() for line in lines][:60]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines or None


def _items(value) -> list[dict]:
    items = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict) or not raw.get("label"):
            continue
        label = _text(raw.get("label"), limit=30)
        items.append({
            "icon": _text(raw.get("icon"), "•", 2),
            "label": label,
            "key": _text(raw.get("key"), "", 20).strip().lower(),
            "action": _text(raw.get("action"), label.lower().replace(" ", "_"), 30).strip(),
        })
    return items


def normalize(raw, position: int, seen: set, errors: list, nested: bool = False) -> dict | None:
    if not isinstance(raw, dict):
        errors.append("every section must be an object")
        return None
    kind = str(raw.get("type", "")).strip().lower()
    if kind not in PRIORITY:
        errors.append(f"unknown section type '{kind}'")
        return None
    if kind == "columns" and nested:
        errors.append("columns cannot be nested")
        return None
    if kind in SINGLE and kind in seen:
        errors.append(f"'{kind}' can only appear once")
        return None
    border = str(raw.get("border", "")).strip().lower()
    section = {
        "type": kind,
        "align": raw.get("align") if raw.get("align") in ALIGNS else ("left" if kind in LISTS + ("hosts", "alerts", "stats") else "center"),
        "margin": _int(raw.get("margin"), 0 if position == 0 else 1, 0, 20),
        "priority": _int(raw.get("priority"), PRIORITY[kind], 0, 99),
        "min_height": _int(raw.get("min_height"), 0, 0, 500),
        "border": border if border in BORDERS else "",
        "border_color": _text(raw.get("border_color"), "accent", 20),
        "width": _width(raw.get("width")),
        "padding": _int(raw.get("padding"), -1, -1, 20) if raw.get("padding") is not None else "",
    }
    if section["padding"] == -1:
        section["padding"] = ""
    if kind == "logo":
        section.update(
            text=_text(raw.get("text"), DEFAULT_TITLE, 60), font=_text(raw.get("font"), "block", 40),
            color=_text(raw.get("color"), "default", 20), fill_color=_text(raw.get("fill_color"), "", 20),
            lines=_art(raw, errors), title=_text(raw.get("title"), "", 60),
        )
    elif kind == "art":
        art = _art(raw, errors)
        if art is None:
            errors.append("an art section needs 'art' (a list of lines) or 'art_file'")
            return None
        section.update(lines=art, color=_text(raw.get("color"), "default", 20),
                       fill_color=_text(raw.get("fill_color"), "", 20), title=_text(raw.get("title"), "", 60))
    elif kind == "tagline":
        section.update(text=_text(raw.get("text"), "", 120), version=_flag(raw.get("version"), False),
                       cursor=_flag(raw.get("cursor"), False))
    elif kind == "menu":
        section.update(
            items=_items(raw.get("items")) or [dict(item) for item in DEFAULT_MENU],
            keys=_flag(raw.get("keys"), True),
            label_align="center" if raw.get("label_align") == "center" else "left",
        )
    elif kind == "summary":
        section.update(text=_text(raw.get("text"), "", 200), title=_text(raw.get("title"), "", 60))
    elif kind == "activity":
        section.update(lines=_int(raw.get("lines"), 3, 1, 15), title=_text(raw.get("title"), "RECENT ACTIVITY", 60))
    elif kind == "hosts":
        sort = raw.get("sort") if raw.get("sort") in ("status", "name", "latency") else "status"
        section.update(lines=_int(raw.get("lines"), 5, 1, 20), title=_text(raw.get("title"), "HOSTS", 60), sort=sort)
    elif kind == "alerts":
        section.update(lines=_int(raw.get("lines"), 5, 1, 20), title=_text(raw.get("title"), "ATTENTION", 60))
    elif kind == "stats":
        section["title"] = _text(raw.get("title"), "FLEET", 60)
    elif kind == "tip":
        tips = raw.get("tips")
        if not isinstance(tips, list) and raw.get("text"):
            tips = str(raw["text"]).split("|")
        tips = [str(tip).strip() for tip in tips or [] if str(tip).strip()]
        section.update(tips=tips or list(DEFAULT_TIPS), seconds=_int(raw.get("seconds"), 8, 1, 3600),
                       icon=_text(raw.get("icon"), "✦ ", 4))
    elif kind == "footer":
        section.update(
            left=_text(raw.get("left"), "system", 120), right=_text(raw.get("right"), "datetime", 120),
            left_text=_text(raw.get("left_text"), "", 120), right_text=_text(raw.get("right_text"), "", 120),
            separator=_text(raw.get("separator"), "   ·   ", 20),
        )
    elif kind == "text":
        section.update(text=_text(raw.get("text"), "", 400).replace("\\n", "\n"),
                       color=_text(raw.get("color"), "", 20), bold=_flag(raw.get("bold"), False),
                       title=_text(raw.get("title"), "", 60))
    elif kind == "spacer":
        section.update(height=_int(raw.get("height"), 1, 1, 20), margin=0)
    elif kind == "columns":
        raws = raw.get("columns")
        if not isinstance(raws, list) or not raws:
            errors.append("a columns section needs a 'columns' list")
            return None
        columns = []
        for column in raws[:4]:
            if not isinstance(column, dict) or not isinstance(column.get("sections"), list):
                errors.append("every column needs a 'sections' list")
                continue
            children = []
            for child in column["sections"]:
                built = normalize(child, len(children), seen, errors, True)
                if built is not None:
                    children.append(built)
            if children:
                columns.append({"width": _width(column.get("width")) or "1fr", "sections": children})
        if not columns:
            errors.append("the columns section has no valid sections")
            return None
        valign = raw.get("valign") if raw.get("valign") in ("top", "middle", "bottom") else "top"
        section.update(columns=columns, gap=_int(raw.get("gap"), 2, 0, 20), valign=valign)
    seen.add(kind)
    return section


def _normalize_all(raws: list) -> tuple[list, list]:
    sections, seen, errors = [], set(), []
    for raw in raws:
        section = normalize(raw, len(sections), seen, errors)
        if section is not None:
            sections.append(section)
    return sections, errors


def settings_layout() -> Layout:
    get = settings.get
    raws = []
    title = get("logo_text").strip()
    if title:
        raws.append({"type": "logo", "text": title, "font": get("logo_font"), "color": get("logo_color")})
    tagline, version, cursor = get("tagline"), get("show_version") == "on", get("show_cursor") == "on"
    if tagline or version or cursor:
        raws.append({"type": "tagline", "text": tagline, "version": version, "cursor": cursor})
    raws.append({"type": "menu", "items": [dict(item) for item in DEFAULT_MENU]})
    if get("show_summary") == "on":
        raws.append({"type": "summary"})
    if get("show_activity") == "on":
        raws.append({"type": "activity", "lines": int(get("activity_lines"))})
    mode = get("tip_mode")
    if mode == "rotate":
        raws.append({"type": "tip", "tips": list(DEFAULT_TIPS), "seconds": int(get("tip_seconds"))})
    elif mode == "custom" and get("tip_text").strip():
        raws.append({"type": "tip", "text": get("tip_text"), "seconds": int(get("tip_seconds"))})
    if get("footer_left") != "off" or get("footer_right") != "off":
        raws.append({"type": "footer", "left": get("footer_left"), "right": get("footer_right"),
                     "left_text": get("footer_left_text"), "right_text": get("footer_right_text")})
    sections, _ = _normalize_all(raws)
    return Layout(sections, DEFAULT_WIDTH)


def preset_layout(key: str) -> Layout:
    preset = PRESETS.get(key) or next(iter(PRESETS.values()))
    sections, _ = _normalize_all(preset["sections"])
    return Layout(sections, preset["width"], None, "preset")


def base_layout() -> Layout:
    mode = settings.get("layout_mode")
    return preset_layout(mode[7:]) if mode.startswith("preset:") else settings_layout()


def file_layout() -> Layout:
    fallback = settings_layout()
    name = LAYOUT_PATH.name
    if not LAYOUT_PATH.exists():
        try:
            ensure_layout_file()
        except OSError as error:
            return Layout(fallback.sections, fallback.width, f"{name}: {error.strerror or error}")
    try:
        data = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return Layout(fallback.sections, fallback.width, f"{name}: {error}")
    if not isinstance(data, dict):
        return Layout(fallback.sections, fallback.width, f"{name}: the file must contain a JSON object")
    preset = PRESETS.get(str(data.get("preset", "")).strip().lower())
    raws, width = data.get("sections"), DEFAULT_WIDTH
    if raws is None and preset is not None:
        raws, width = preset["sections"], preset["width"]
    if not isinstance(raws, list):
        return Layout(fallback.sections, fallback.width, f"{name}: needs a 'sections' list or a valid 'preset'")
    sections, errors = _normalize_all(raws)
    if not sections:
        return Layout(fallback.sections, fallback.width, f"{name}: no valid sections found")
    error = None
    if errors:
        error = f"{name}: {errors[0]}" + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else "")
    return Layout(sections, _int(data.get("width"), width, 20, 300), error, "file")


def current_layout() -> Layout:
    return file_layout() if settings.get("layout_mode") == "file" else base_layout()


def _export(section: dict) -> dict:
    data = dict(section)
    if data["priority"] == PRIORITY[section["type"]]:
        data.pop("priority")
    if not data["min_height"]:
        data.pop("min_height")
    if section["type"] in ("logo", "art"):
        if section["type"] == "logo" or not section.get("lines"):
            data.pop("lines", None)
        if section["type"] == "art":
            data["art"] = data.pop("lines")
    if not data.get("border"):
        data.pop("border", None)
        data.pop("border_color", None)
    for key in ("width", "padding"):
        if data.get(key) == "":
            data.pop(key, None)
    if section["type"] == "columns":
        data["columns"] = [{"width": c["width"], "sections": [_export(s) for s in c["sections"]]}
                           for c in section["columns"]]
    return data


def ensure_layout_file(replace: bool = False) -> Path:
    exists = LAYOUT_PATH.exists()
    if exists and replace:
        shutil.copy2(LAYOUT_PATH, LAYOUT_PATH.with_suffix(".json.bak"))
    if replace or not exists:
        layout = base_layout()
        ensure_private_dir(LAYOUT_PATH.parent)
        LAYOUT_PATH.write_text(
            json.dumps({"_help": LAYOUT_HELP, "width": layout.width,
                        "sections": [_export(s) for s in layout.sections]}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return LAYOUT_PATH


def open_in_editor(path: Path) -> bool:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))
            return True
        command = "open" if sys.platform == "darwin" else "xdg-open"
        if shutil.which(command) is None:
            return False
        subprocess.Popen([command, str(path)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"


@lru_cache(maxsize=1)
def _username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "user"


def _values() -> dict:
    now = datetime.now()
    states = [host[1] for host in HOSTS]
    service_states = [state for _, _, services in SERVICES for _, _, state in services]
    latencies = [host[5] for host in HOSTS if host[5] is not None and host[1] != "offline"]
    values = {name: now.strftime(fmt) for name, fmt in DATE_FORMATS.items()}
    values.update(
        system=platform.system(), hostname=_hostname(), user=_username(),
        python=platform.python_version(), version=APP_VERSION,
        session=fmt_duration(time.monotonic() - SESSION_START),
        hosts=str(len(HOSTS)), online=str(states.count("online")), warning=str(states.count("warning")),
        offline=str(states.count("offline")), services=str(len(service_states)),
        services_up=str(service_states.count("up")), services_down=str(service_states.count("down")),
        services_warning=str(service_states.count("warning")),
        avg_latency=f"{sum(latencies) / len(latencies):.0f} ms" if latencies else "—",
    )
    return values


def expand(template: str) -> str:
    if "{" not in template:
        return template
    values = _values()

    def substitute(match) -> str:
        key = match.group(1)
        if key.startswith("now:"):
            try:
                return datetime.now().strftime(key[4:])
            except ValueError:
                return match.group(0)
        return values.get(key, match.group(0))

    return PLACEHOLDER.sub(substitute, template)


def footer_for(section: dict) -> tuple[str, str]:
    def side(value: str, custom: str) -> str:
        template = custom if value == "custom" else FOOTER_PRESETS.get(value, value)
        return expand(template).strip()

    return side(section["left"], section["left_text"]), side(section["right"], section["right_text"])


def tip_for(section: dict, opened: float) -> str:
    tips = section["tips"]
    index = int((time.monotonic() - opened) // section["seconds"]) % len(tips)
    return section["icon"] + expand(tips[index])


def resolve_color(name) -> str | None:
    if not name or name == "default":
        return None
    name = str(name).strip()
    named = {"accent": PALETTE["accent"], "ok": PALETTE["ok"], "warn": PALETTE["warn"],
             "bad": PALETTE["bad"], "fill": PALETTE["fill"], "shadow": PALETTE["shadow"]}
    if name in named:
        return named[name]
    if name in ACCENT_NAMES:
        spec = THEME_SPECS.get(settings.get("theme"))
        return name if THEME_STATE["terminal"] or spec is None else spec[name]
    try:
        Color.parse(name)
    except Exception:
        return None
    return name


def section_style(section: dict) -> str:
    parts = ["bold"] if section.get("bold") else []
    name = section.get("color", "")
    if name == "muted":
        parts.append("dim")
    else:
        color = resolve_color(name)
        if color:
            parts.append(color)
    return " ".join(parts)


def _shadow(name: str) -> str:
    if name in ACCENT_NAMES and not THEME_STATE["terminal"]:
        spec = THEME_SPECS.get(settings.get("theme"))
        if spec is not None:
            return blend_hex(spec[name], "#ffffff", 0.15)
    return resolve_color(name) or PALETTE["shadow"]


def _pad(lines: list[str]) -> list[str]:
    width = max(len(line) for line in lines)
    return [line.ljust(width) for line in lines]


def _balance(lines: list[str], font: str, width: int) -> list[str]:
    if not lines or font in ("plain", "compact"):
        return lines
    ink = [index for line in lines for index, char in enumerate(line) if char == "█"]
    if not ink:
        return lines
    shift = int((len(lines[0]) - 1) / 2 - (min(ink) + max(ink)) / 2 + 0.5)
    if shift < 1 or len(lines[0]) + shift > width:
        return lines
    return [" " * shift + line for line in lines]


def resolve_logo(section: dict, width: int) -> tuple[list[str], str, str, str]:
    fill = resolve_color(section.get("fill_color")) or PALETTE["fill"]
    color = section.get("color") or "default"
    art = section.get("lines")
    if art:
        lines = _pad([line[:max(1, width)] for line in art])
        if color != "default":
            tone = resolve_color(color) or PALETTE["accent"]
            return lines, "mono", tone, tone
        return lines, "art", fill, PALETTE["shadow"]
    lines, font = fit(section.get("text", ""), section.get("font", "block"), width)
    return _balance(lines, font, width), font, fill, _shadow(color)


def kind_of(char: str, font: str) -> str | None:
    if char == " ":
        return None
    if font in ("plain", "mono") or char == "█":
        return "fill"
    return "shadow"


def logo_text(lines: list[str], font: str, fill: str, shadow: str) -> Text:
    logo = Text(no_wrap=True, overflow="crop")
    for index, line in enumerate(lines):
        for char in line:
            kind = kind_of(char, font)
            if kind == "fill":
                logo.append(char, style=f"bold {fill}")
            elif kind == "shadow":
                logo.append(char, style=shadow)
            else:
                logo.append(char)
        if index < len(lines) - 1:
            logo.append("\n")
    return logo


def animation_logo(width: int) -> tuple[list[str], str, str, str]:
    section = current_layout().first("logo")
    if section is not None:
        result = resolve_logo(section, width)
        if result[0]:
            return result
    return resolve_logo({"type": "logo", "text": DEFAULT_TITLE, "font": "block", "color": "default"}, width)


def animation_tagline() -> str:
    section = current_layout().first("tagline")
    return expand(section["text"]) if section is not None else ""


def boot_title() -> str:
    section = current_layout().first("logo")
    title = "" if section is None or section.get("lines") else section["text"].strip().upper()
    return "NETLAB DB" if not title or title == DEFAULT_TITLE else title


def mix_color(color: str, background, amount: float) -> str:
    red, green, blue = Color.parse(color).get_truecolor()
    amount = max(0.0, min(1.0, amount))
    return "#{:02x}{:02x}{:02x}".format(
        round(red + (background.r - red) * amount),
        round(green + (background.g - green) * amount),
        round(blue + (background.b - blue) * amount),
    )