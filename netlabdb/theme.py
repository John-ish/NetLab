from textual.color import Color as TColor
from textual.theme import Theme


ACCENT_NAMES = ("red", "green", "yellow", "blue", "magenta", "cyan")

THEME_SPECS = {
    "netlab": dict(label="Netlab", dark=True, bg="#121212", fg="#e0e0e0", muted="#9a9a9a", accent="red",
                   red="#ba3c5b", green="#4ebf71", yellow="#ffa62b", blue="#3b9be0", magenta="#c678dd",
                   cyan="#56b6c2", bad="#ff5555"),
    "catppuccin-mocha": dict(label="Catppuccin Mocha", dark=True, bg="#1e1e2e", fg="#cdd6f4", muted="#9399b2",
                             accent="magenta", red="#f38ba8", green="#a6e3a1", yellow="#f9e2af", blue="#89b4fa",
                             magenta="#cba6f7", cyan="#94e2d5"),
    "catppuccin-macchiato": dict(label="Catppuccin Macchiato", dark=True, bg="#24273a", fg="#cad3f5", muted="#939ab7",
                                 accent="magenta", red="#ed8796", green="#a6da95", yellow="#eed49f", blue="#8aadf4",
                                 magenta="#c6a0f6", cyan="#8bd5ca"),
    "catppuccin-frappe": dict(label="Catppuccin Frappé", dark=True, bg="#303446", fg="#c6d0f5", muted="#949cbb",
                              accent="magenta", red="#e78284", green="#a6d189", yellow="#e5c890", blue="#8caaee",
                              magenta="#ca9ee6", cyan="#81c8be"),
    "catppuccin-latte": dict(label="Catppuccin Latte", dark=False, bg="#eff1f5", fg="#4c4f69", muted="#7c7f93",
                             accent="magenta", red="#d20f39", green="#40a02b", yellow="#df8e1d", blue="#1e66f5",
                             magenta="#8839ef", cyan="#179299"),
    "dracula": dict(label="Dracula", dark=True, bg="#282a36", fg="#f8f8f2", muted="#8b95c9", accent="magenta",
                    red="#ff5555", green="#50fa7b", yellow="#f1fa8c", blue="#bd93f9", magenta="#ff79c6",
                    cyan="#8be9fd"),
    "nord": dict(label="Nord", dark=True, bg="#2e3440", fg="#d8dee9", muted="#8d99ae", accent="cyan",
                 red="#bf616a", green="#a3be8c", yellow="#ebcb8b", blue="#81a1c1", magenta="#b48ead",
                 cyan="#88c0d0"),
    "gruvbox": dict(label="Gruvbox Dark", dark=True, bg="#282828", fg="#ebdbb2", muted="#a89984", accent="yellow",
                    red="#fb4934", green="#b8bb26", yellow="#fabd2f", blue="#83a598", magenta="#d3869b",
                    cyan="#8ec07c"),
    "tokyo-night": dict(label="Tokyo Night", dark=True, bg="#1a1b26", fg="#c0caf5", muted="#7982a9", accent="blue",
                        red="#f7768e", green="#9ece6a", yellow="#e0af68", blue="#7aa2f7", magenta="#bb9af7",
                        cyan="#7dcfff"),
    "solarized-dark": dict(label="Solarized Dark", dark=True, bg="#002b36", fg="#93a1a1", muted="#657b83",
                           accent="blue", red="#dc322f", green="#859900", yellow="#b58900", blue="#268bd2",
                           magenta="#d33682", cyan="#2aa198"),
    "rose-pine": dict(label="Rosé Pine", dark=True, bg="#191724", fg="#e0def4", muted="#908caa", accent="magenta",
                      red="#eb6f92", green="#7fb69e", yellow="#f6c177", blue="#31748f", magenta="#c4a7e7",
                      cyan="#9ccfd8"),
    "one-dark": dict(label="One Dark", dark=True, bg="#282c34", fg="#abb2bf", muted="#7f848e", accent="blue",
                     red="#e06c75", green="#98c379", yellow="#e5c07b", blue="#61afef", magenta="#c678dd",
                     cyan="#56b6c2"),
    "monokai": dict(label="Monokai", dark=True, bg="#272822", fg="#f8f8f2", muted="#908f84", accent="red",
                    red="#f92672", green="#a6e22e", yellow="#e6db74", blue="#66d9ef", magenta="#ae81ff",
                    cyan="#a1efe4"),
}

THEME_OPTIONS = [("Terminal colors", "terminal")] + [(spec["label"], key) for key, spec in THEME_SPECS.items()]
ACCENT_OPTIONS = [("Scheme default", "default")] + [(name.capitalize(), name) for name in ACCENT_NAMES]
THEME_STATE = {"terminal": False, "ansi": False}
PALETTE = {"ok": "#4ebf71", "warn": "#ffa62b", "bad": "#ff5555", "accent": "#ba3c5b",
           "fill": "#e6e9ef", "shadow": "#ba3c5b", "bg": TColor(18, 18, 18)}
ANSI_VARIABLES = {
    "ansi-background": "ansi_black", "ansi-foreground": "ansi_white", "border-blurred": "ansi_black",
    "block-cursor-foreground": "ansi_black", "block-cursor-background": "ansi_white",
    "input-cursor-background": "ansi_black", "input-cursor-foreground": "ansi_bright_white",
    "input-cursor-text-style": "none", "input-selection-background": "ansi_bright_blue",
    "input-selection-foreground": "ansi_black", "screen-selection-background": "ansi_bright_blue",
    "screen-selection-foreground": "ansi_black",
}
THEME_FALLBACKS = {
    **ANSI_VARIABLES,
    "row": "#2b181c", "row-hover": "#3e2128", "row-text": "#e0e0e0", "on-accent": "#121212",
    "placeholder": "#9a9a9a",
    "bad": "#ff5555", "tint": "#2b181c", "tint-hover": "#3e2128", "tint-faint": "#1c1415",
    "bad-tint": "#3a1a1a", "bad-tint-strong": "#4d2020", "live-dim": "#1d4a2a", "shade": "rgba(18,18,18,0.55)",
}


def rich_color(value: str) -> str:
    return value[5:] if value.startswith("ansi_") else value


def blend_hex(base: str, over: str, amount: float) -> str:
    return TColor.parse(base).blend(TColor.parse(over), amount).hex


def make_theme(**fields) -> Theme:
    try:
        return Theme(**fields)
    except TypeError:
        fields.pop("ansi", None)
        return Theme(**fields)


def build_theme_state(key: str, accent_choice: str, transparent: bool) -> dict:
    spec = THEME_SPECS.get(key)
    if spec is None:
        slot = "red" if accent_choice == "default" else accent_choice
        accent = f"ansi_{slot}"
        subtle = "ansi_bright_black"
        variables = {
            **ANSI_VARIABLES,
            "background": "ansi_default", "text": "ansi_default", "text-muted": subtle, "error-darken-1": subtle,
            "bad": "ansi_red", "tint": subtle, "tint-hover": subtle, "tint-faint": "ansi_default",
            "bad-tint": subtle, "bad-tint-strong": subtle, "live-dim": subtle, "shade": "transparent",
            "row": "ansi_default", "row-hover": "ansi_default", "row-text": accent,
            "on-accent": "ansi_black" if slot in ("yellow", "green", "cyan") else "ansi_bright_white",
            "placeholder": "ansi_white",
        }
        theme = make_theme(
            name=f"nl-terminal-{slot}", primary="ansi_blue", secondary="ansi_magenta", accent="ansi_cyan",
            warning="ansi_yellow", error=accent, success="ansi_green", foreground="ansi_default",
            background="ansi_default", surface="ansi_default", panel="ansi_default", boost="ansi_default",
            dark=True, variables=variables, ansi=True,
        )
        palette = {"ok": "green", "warn": "yellow", "bad": "red", "accent": rich_color(accent), "fill": "default",
                   "shadow": rich_color(accent), "bg": TColor(18, 18, 18)}
        return {"theme": theme, "palette": palette, "ansi": True, "terminal": True}
    slot = spec["accent"] if accent_choice == "default" else accent_choice
    accent, bg, fg, bad = spec[slot], spec["bg"], spec["fg"], spec.get("bad", spec["red"])
    base = TColor.parse(bg)
    variables = {
        "error-darken-1": blend_hex(accent, bg, 0.55), "bad": bad, "text": fg, "text-muted": spec["muted"],
        "tint": blend_hex(bg, accent, 0.15), "tint-hover": blend_hex(bg, accent, 0.30),
        "tint-faint": blend_hex(bg, accent, 0.08), "bad-tint": blend_hex(bg, bad, 0.20),
        "bad-tint-strong": blend_hex(bg, bad, 0.35), "live-dim": blend_hex(bg, spec["green"], 0.35),
        "shade": f"rgba({base.r},{base.g},{base.b},0.55)",
        "row": blend_hex(bg, accent, 0.15), "row-hover": blend_hex(bg, accent, 0.30), "row-text": fg,
        "on-accent": bg, "placeholder": spec["muted"],
    }
    if transparent:
        variables["background"] = "ansi_default"
        variables["shade"] = "transparent"
    theme = make_theme(
        name=f"nl-{key}-{slot}-{'clear' if transparent else 'solid'}", primary=spec["blue"],
        secondary=spec["magenta"], accent=spec["cyan"], warning=spec["yellow"], error=accent,
        success=spec["green"], foreground=fg, background=bg, surface=blend_hex(bg, fg, 0.04),
        panel=blend_hex(bg, fg, 0.08), dark=spec["dark"], variables=variables, ansi=transparent,
    )
    palette = {"ok": spec["green"], "warn": spec["yellow"], "bad": bad, "accent": accent, "fill": fg,
               "shadow": blend_hex(accent, "#ffffff", 0.15), "bg": base}
    return {"theme": theme, "palette": palette, "ansi": transparent, "terminal": False}
