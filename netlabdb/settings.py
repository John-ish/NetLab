import json
from pathlib import Path

from .config import SETTINGS_PATH, ensure_private_dir
from .fonts import FONT_OPTIONS
from .presets import PRESETS
from .theme import ACCENT_NAMES, ACCENT_OPTIONS, THEME_OPTIONS


ON_OFF = [("On", "on"), ("Off", "off")]

INTENSITY_LEVELS = [("Off", "off"), ("Subtle", "subtle"), ("Medium", "medium"), ("Strong", "strong")]

LOGO_COLOR_OPTIONS = [("Match accent", "default")] + [(name.capitalize(), name) for name in ACCENT_NAMES]

LAYOUT_OPTIONS = [("Settings", "settings"), ("Layout file", "file")] + [
    (f"Preset: {preset['label']}", f"preset:{key}") for key, preset in PRESETS.items()
]

ACTIVITY_LINES = [(str(n), str(n)) for n in range(1, 6)]

TIP_SECONDS = [("5 seconds", "5"), ("8 seconds", "8"), ("15 seconds", "15"), ("30 seconds", "30")]

FOOTER_LEFT = [
    ("System", "system"), ("Hostname", "host"), ("User", "user"), ("Python version", "python"),
    ("Custom text", "custom"), ("Hidden", "off"),
]

FOOTER_RIGHT = [
    ("Date and time", "datetime"), ("Time", "time"), ("Date", "date"), ("ISO date and time", "iso"),
    ("12-hour clock", "twelve"), ("Session uptime", "session"), ("Custom text", "custom"), ("Hidden", "off"),
]

SETTING_DEFINITIONS = [
    ("theme", "Appearance", "Color scheme", THEME_OPTIONS,
     "'Terminal colors' follows your terminal's own palette. It has no CRT effect, and pop-ups show the screen behind them undimmed."),
    ("accent", "Appearance", "Accent color", ACCENT_OPTIONS,
     "Highlight color used for borders, cursors and keys. 'Scheme default' uses the scheme's signature color."),
    ("transparent", "Appearance", "Transparent background", ON_OFF,
     "Toggles the terminal's background transparency. Pop-ups show the screen behind them undimmed. *Does not combine with the CRT effect well, as in only text is affected, never the background."),
    ("crt_effect", "Appearance", "CRT effect", ON_OFF,
     "Adds a subtle scanline animation to the whole interface. Unavailable with 'Terminal colors' color scheme; only affects text when 'Transparent background' is on."),
    ("crt_intensity", "Appearance", "Scanline intensity", INTENSITY_LEVELS,
     "How dark the alternating scanlines are. 'Off' removes them."),
    ("crt_flicker", "Appearance", "Screen flicker", INTENSITY_LEVELS,
     "Random patches of the screen flicker briefly, like interference on an old TV."),
    ("crt_glow", "Appearance", "Screen glow", INTENSITY_LEVELS,
     "Brightens text and lifts the black level slightly to mimic the glow of an old TV."),
    ("crt_roll", "Appearance", "Rolling bar", ON_OFF,
     "A faint bright bar that slowly sweeps down the screen."),
    ("layout_mode", "Dashboard", "Layout source", LAYOUT_OPTIONS,
     "'Settings' builds the dashboard from the options below. A 'Preset' uses a ready-made layout. 'Layout file' uses ~/.netlabdb/dashboard.json, where you control every section; pressing [l] creates it from the active layout. Edits apply live."),
    ("logo_text", "Dashboard", "Logo text", None,
     "The big title on the dashboard and in the startup animations. Leave it empty to hide the logo. 'Block' and 'Compact' draw letters, digits and - _ . ! ? : only; use 'Plain' or a Figlet font for anything else. Press [Enter] to edit."),
    ("logo_font", "Dashboard", "Logo font", FONT_OPTIONS,
     "'Block' and 'Compact' are built in. Install pyfiglet (pip install pyfiglet) to unlock more fonts. If the title is too wide for the terminal a smaller font is used automatically."),
    ("logo_color", "Dashboard", "Logo color", LOGO_COLOR_OPTIONS,
     "Color of the logo's outline and shadow. 'Match accent' follows the accent color."),
    ("tagline", "Dashboard", "Tagline", None,
     "The line under the logo. Leave it empty to hide it. Press [Enter] to edit."),
    ("show_version", "Dashboard", "Show version", ON_OFF,
     "Shows the version number after the tagline."),
    ("show_cursor", "Dashboard", "Blinking cursor", ON_OFF,
     "Shows a blinking block cursor after the tagline."),
    ("show_summary", "Dashboard", "Status summary", ON_OFF,
     "The online, warning and offline counters under the menu."),
    ("show_activity", "Dashboard", "Recent activity", ON_OFF,
     "The latest log events at the bottom of the dashboard. Only shown when the terminal is tall enough."),
    ("activity_lines", "Dashboard", "Activity lines", ACTIVITY_LINES,
     "How many recent events the dashboard lists."),
    ("tip_mode", "Hints & footer", "Hint line", [("Rotating tips", "rotate"), ("Custom text", "custom"), ("Hidden", "off")],
     "The hint under the activity list. Rotating tips cycles through the built-in tips. Custom text shows your own."),
    ("tip_text", "Hints & footer", "Custom hints", None,
     "Your own hint. Separate several hints with | and they rotate. Press [Enter] to edit."),
    ("tip_seconds", "Hints & footer", "Hint rotation", TIP_SECONDS,
     "How long each hint stays before the next one appears."),
    ("footer_left", "Hints & footer", "Footer left", FOOTER_LEFT,
     "What the left side of the dashboard footer shows."),
    ("footer_left_text", "Hints & footer", "Footer left text", None,
     "Shown when Footer left is set to Custom text. Press [Enter] to edit."),
    ("footer_right", "Hints & footer", "Footer right", FOOTER_RIGHT,
     "What the right side of the dashboard footer shows. It updates every second."),
    ("footer_right_text", "Hints & footer", "Footer right text", None,
     "Shown when Footer right is set to Custom text. Press [Enter] to edit."),
    ("startup_animation", "Startup", "Startup animation", ON_OFF,
     "Plays an animation of your choice on startup."),
    ("startup_style", "Startup", "Startup style",
     [("CRT power-on", "crt"), ("Glitch reveal", "glitch"), ("Network scan", "scan"),
      ("Neon sweep", "sweep"), ("Fade in", "fade"), ("Random", "random")],
     "Which animation plays at launch. 'Glitch reveal', 'Neon sweep' and 'Fade in' use your dashboard's logo and tagline. Press [p] to preview it."),
    ("default_screen", "Startup", "Default screen",
     [("Dashboard", "startup"), ("Hosts", "hosts"), ("Services", "services"), ("Logs", "logs")],
     "The screen shown right after launch."),
]

SETTING_PARENTS = {
    "crt_intensity": "crt_effect",
    "crt_flicker": "crt_effect",
    "crt_glow": "crt_effect",
    "crt_roll": "crt_effect",
    "logo_font": "logo_text",
    "logo_color": "logo_text",
    "show_version": "tagline",
    "show_cursor": "tagline",
    "activity_lines": "show_activity",
    "tip_text": "tip_mode",
    "tip_seconds": "tip_mode",
    "footer_left_text": "footer_left",
    "footer_right_text": "footer_right",
    "startup_style": "startup_animation",
}

SETTING_DEFAULTS = {
    "theme": "terminal",
    "accent": "default",
    "transparent": "off",
    "crt_effect": "off",
    "crt_intensity": "subtle",
    "crt_flicker": "subtle",
    "crt_glow": "subtle",
    "crt_roll": "off",
    "layout_mode": "settings",
    "logo_text": "NETLAB",
    "logo_font": "block",
    "logo_color": "default",
    "tagline": "server monitoring terminal",
    "show_version": "on",
    "show_cursor": "on",
    "show_summary": "on",
    "show_activity": "on",
    "activity_lines": "3",
    "tip_mode": "rotate",
    "tip_text": "",
    "tip_seconds": "8",
    "footer_left": "system",
    "footer_left_text": "",
    "footer_right": "datetime",
    "footer_right_text": "",
    "startup_animation": "on",
    "startup_style": "glitch",
    "default_screen": "startup",
}

TEXT_LIMITS = {
    "logo_text": 20,
    "tagline": 48,
    "tip_text": 240,
    "footer_left_text": 40,
    "footer_right_text": 40,
}

CRT_INTENSITY = {"off": 0.0, "subtle": 0.10, "medium": 0.18, "strong": 0.28}
FLICKER_STRENGTH = {"off": 0.0, "subtle": 0.05, "medium": 0.09, "strong": 0.15}
CRT_GLOW = {"off": 0.0, "subtle": 0.3, "medium": 0.6, "strong": 1.0}
CRT_DEPENDENT = ("crt_intensity", "crt_flicker", "crt_glow", "crt_roll")
DASHBOARD_KEYS = frozenset(key for key, group, *_ in SETTING_DEFINITIONS if group in ("Dashboard", "Hints & footer"))


def inactive(key: str, get) -> bool:
    if key in DASHBOARD_KEYS and key != "layout_mode" and get("layout_mode") != "settings":
        return True
    if key in CRT_DEPENDENT:
        return get("crt_effect") != "on" or get("theme") == "terminal"
    if key in ("crt_effect", "transparent"):
        return get("theme") == "terminal"
    if key in ("logo_font", "logo_color"):
        return not get("logo_text").strip()
    if key == "activity_lines":
        return get("show_activity") != "on"
    if key == "tip_seconds":
        return get("tip_mode") == "off"
    if key == "tip_text":
        return get("tip_mode") != "custom"
    if key == "footer_left_text":
        return get("footer_left") != "custom"
    if key == "footer_right_text":
        return get("footer_right") != "custom"
    if key == "startup_style":
        return get("startup_animation") != "on"
    return False


class SettingsStore:

    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self.values = dict(SETTING_DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key, _, _, options, _ in SETTING_DEFINITIONS:
            value = data.get(key)
            if options is None:
                if isinstance(value, str):
                    self.values[key] = value[:TEXT_LIMITS[key]]
            elif value in [option for _, option in options]:
                self.values[key] = value

    def save(self) -> None:
        try:
            ensure_private_dir(self.path.parent)
            self.path.write_text(json.dumps(self.values, indent=2), encoding="utf-8")
        except OSError:
            pass

    def get(self, key: str) -> str:
        return self.values.get(key, SETTING_DEFAULTS[key])

    def set(self, key: str, value: str) -> None:
        self.values[key] = value
        self.save()

    def reset(self) -> None:
        self.values = dict(SETTING_DEFAULTS)
        self.save()


settings = SettingsStore()