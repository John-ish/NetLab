from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Static

from ..config import STYLE_PATH
from ..helpers import nav_hint_text, palette
from ..settings import CRT_DEPENDENT, ON_OFF, SETTING_DEFINITIONS, settings
from ..widgets import KeyBar, SvcScroll


SETTINGS_NAV_HINTS = [
    ("[↑/↓]", "Navigate"),
    ("[m]", "Menu"),
]

SETTINGS_ACTION_EVENTS = [
    ("[←/→]", "Change"),
    ("[Enter]", "Next"),
    ("[p]", "Preview"),
    ("[r]", "Reset"),
    ("[m]", "Menu"),
]


class SettingRow(Horizontal, can_focus=True):

    BINDINGS = [
        ("left", "shift(-1)", "Previous"),
        ("right", "shift(1)", "Next"),
        ("enter", "shift(1)", "Next"),
        ("space", "shift(1)", "Next"),
    ]

    class Changed(Message):
        def __init__(self, key: str, value: str) -> None:
            super().__init__()
            self.key = key
            self.value = value

    def __init__(self, key: str, label: str, options: list, description: str, value: str):
        super().__init__()
        self.key = key
        self.label = label
        self.options = options
        self.description = description
        self.index = next((i for i, (_, v) in enumerate(options) if v == value), 0)

    @property
    def value(self) -> str:
        return self.options[self.index][1]

    def compose(self) -> ComposeResult:
        yield Static("❱", classes="set-cursor")
        yield Static(self.label, classes="set-label")
        yield Static("", classes="set-value")

    def on_mount(self) -> None:
        self._draw()

    def _draw(self) -> None:
        pal = palette(self.app)
        label, value = self.options[self.index]
        text = Text(no_wrap=True)
        if self.options == ON_OFF:
            text.append("● " if value == "on" else "○ ", style=pal["ok"] if value == "on" else "dim")
            text.append(label.upper(), style=f"bold {pal['ok']}" if value == "on" else "dim")
        else:
            text.append("‹ ", style="dim")
            text.append(label, style=f"bold {pal['accent']}")
            text.append(" ›", style="dim")
        self.query_one(".set-value", Static).update(text)

    def set_value(self, value: str) -> None:
        self.index = next((i for i, (_, v) in enumerate(self.options) if v == value), 0)
        self._draw()

    def action_shift(self, step: int) -> None:
        self.index = (self.index + step) % len(self.options)
        self._draw()
        self.post_message(self.Changed(self.key, self.value))

    def on_click(self, event: Click) -> None:
        self.focus()
        self.action_shift(1)


class SettingsScreen(Screen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("m", "app.main_menu", "Main Menu"),
        ("up", "move(-1)", "Up"),
        ("down", "move(1)", "Down"),
        ("r", "reset", "Reset"),
        ("p", "preview", "Preview"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-panel"):
            with SvcScroll(id="settings-scroll"):
                section = None
                for key, group, label, options, description in SETTING_DEFINITIONS:
                    if group != section:
                        section = group
                        yield Static(group.upper(), classes="set-section")
                    yield SettingRow(key, label, options, description, settings.get(key))
            yield Static("", id="set-help")
            with Horizontal(id="footer-bar"):
                yield KeyBar(SETTINGS_ACTION_EVENTS)
                with Horizontal(id="footer-stats"):
                    yield Static(f"{len(SETTING_DEFINITIONS)} settings", id="stat-total")
                    yield Static("|", id="stat-sep")
                    yield Static("✓ Auto-saved", id="stat-online", classes="online")

    def on_mount(self) -> None:
        panel = self.query_one("#settings-panel")
        panel.border_title = "SETTINGS"
        panel.border_subtitle = nav_hint_text(SETTINGS_NAV_HINTS)
        self._sync()
        rows = list(self.query(SettingRow))
        if rows:
            rows[0].focus()

    def _sync(self) -> None:
        terminal = settings.get("theme") == "terminal"
        crt_off = settings.get("crt_effect") != "on" or terminal
        for row in self.query(SettingRow):
            row.set_class((crt_off and row.key in CRT_DEPENDENT) or (terminal and row.key in ("crt_effect", "transparent")),
                          "-disabled")

    def on_descendant_focus(self, event) -> None:
        if isinstance(event.widget, SettingRow):
            self.query_one("#set-help", Static).update(Text(event.widget.description))

    def on_setting_row_changed(self, event: SettingRow.Changed) -> None:
        settings.set(event.key, event.value)
        self.app.apply_settings()
        self._sync()
        for row in self.query(SettingRow):
            row._draw()

    def action_move(self, step: int) -> None:
        rows = list(self.query(SettingRow))
        if not rows:
            return
        current = self.focused
        index = rows.index(current) + step if current in rows else 0
        rows[max(0, min(len(rows) - 1, index))].focus()

    def action_preview(self) -> None:
        self.app.push_screen(self.app.boot_screen())

    def action_reset(self) -> None:
        settings.reset()
        for row in self.query(SettingRow):
            row.set_value(settings.get(row.key))
        self._sync()
        self.app.apply_settings()
        self.notify("Settings restored to defaults")
