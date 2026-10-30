import json
from pathlib import Path

from .config import SETTINGS_PATH, ensure_private_dir
from .theme import ACCENT_OPTIONS, THEME_OPTIONS


ON_OFF = [("On", "on"), ("Off", "off")]

INTENSITY_LEVELS = [("Off", "off"), ("Subtle", "subtle"), ("Medium", "medium"), ("Strong", "strong")]

SETTING_DEFINITIONS = [
    ("theme", "Appearance", "Color scheme", THEME_OPTIONS,
     "Terminal colors follows your terminal's own palette and updates live when it changes. It has no CRT effect, and pop-ups show the screen behind them undimmed."),
    ("accent", "Appearance", "Accent color", ACCENT_OPTIONS,
     "Highlight color used for borders, cursors and keys. Scheme default uses the scheme's signature color."),
    ("transparent", "Appearance", "Transparent background", ON_OFF,
     "Lets your terminal's background (wallpaper, blur, opacity) show through. Does not combine with the CRT effect: only text is affected, never the background. Pop-ups show the screen behind them undimmed."),
    ("crt_effect", "Appearance", "CRT effect", ON_OFF,
     "Adds a subtle scanline overlay to the whole interface. Unavailable with Terminal colors; only affects text when Transparent background is on."),
    ("crt_intensity", "Appearance", "Scanline intensity", INTENSITY_LEVELS,
     "How dark the alternating scanlines are. Off removes them."),
    ("crt_flicker", "Appearance", "Screen flicker", INTENSITY_LEVELS,
     "Random patches of the screen flicker briefly, like interference on an old TV."),
    ("crt_glow", "Appearance", "Screen glow", INTENSITY_LEVELS,
     "Brightens text and lifts the black level slightly, like a glowing phosphor screen."),
    ("crt_roll", "Appearance", "Rolling bar", ON_OFF,
     "A faint bright bar that slowly sweeps down the screen."),
    ("startup_animation", "Startup", "Startup animation", ON_OFF,
     "Plays the CRT power-on and boot sequence when the app launches."),
    ("startup_style", "Startup", "Startup style",
     [("CRT power-on", "crt"), ("Glitch reveal", "glitch"), ("Network scan", "scan"), ("Random", "random")],
     "Which animation plays at launch. Press [p] to preview it."),
    ("default_screen", "Startup", "Default screen",
     [("Startup", "startup"), ("Hosts", "hosts"), ("Services", "services"), ("Logs", "logs")],
     "The screen shown right after launch."),
]

SETTING_DEFAULTS = {
    "theme": "terminal",
    "accent": "default",
    "transparent": "off",
    "crt_effect": "on",
    "crt_intensity": "subtle",
    "crt_flicker": "subtle",
    "crt_glow": "subtle",
    "crt_roll": "off",
    "startup_animation": "on",
    "startup_style": "crt",
    "default_screen": "startup",
}

CRT_INTENSITY = {"off": 0.0, "subtle": 0.10, "medium": 0.18, "strong": 0.28}
FLICKER_STRENGTH = {"off": 0.0, "subtle": 0.05, "medium": 0.09, "strong": 0.15}
CRT_GLOW = {"off": 0.0, "subtle": 0.3, "medium": 0.6, "strong": 1.0}
CRT_DEPENDENT = ("crt_intensity", "crt_flicker", "crt_glow", "crt_roll")


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
            if data.get(key) in [value for _, value in options]:
                self.values[key] = data[key]

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
