from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Static

from ..config import LAYOUT_PATH, STYLE_PATH
from ..dashboard import ensure_layout_file, open_in_editor
from ..helpers import nav_hint_text, palette
from ..presets import PRESETS
from ..settings import (
    DASHBOARD_KEYS, ON_OFF, SETTING_DEFAULTS, SETTING_DEFINITIONS, SETTING_PARENTS, TEXT_LIMITS,
    inactive, settings,
)
from ..widgets import KeyBar, SvcScroll
from .confirm_action import ActionConfirmScreen
from .startup import DashboardPreview
from .text_edit import TextEditScreen


SETTINGS_NAV_HINTS = [
    ("[↑/↓]", "Navigate"),
    ("[m]", "Menu"),
]

SETTINGS_ACTION_EVENTS = [
    ("[←/→]", "Change"),
    ("[p]", "Preview"),
    ("[d]", "Dashboard"),
    ("[l]", "Layout file"),
    ("[r]", "Reset"),
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

    def __init__(self, key: str, label: str, options: list | None, description: str, value: str,
                 branch: str = ""):
        super().__init__()
        self.key = key
        self.label = label
        self.options = options
        self.description = description
        self.branch = branch
        self.text = value if options is None else ""
        self.index = 0 if options is None else next((i for i, (_, v) in enumerate(options) if v == value), 0)

    @property
    def value(self) -> str:
        return self.text if self.options is None else self.options[self.index][1]

    def _label(self, pal: dict) -> Text:
        text = Text(no_wrap=True, overflow="ellipsis")
        if self.branch:
            text.append(self.branch, style=f"dim {pal['accent']}")
        text.append(self.label)
        return text

    def compose(self) -> ComposeResult:
        yield Static("❱", classes="set-cursor")
        yield Static(self._label(palette(self.app)), classes="set-label")
        yield Static("", classes="set-value")

    def on_mount(self) -> None:
        self._draw()

    def _draw(self) -> None:
        pal = palette(self.app)
        muted = self.has_class("-disabled")
        text = Text(no_wrap=True, overflow="ellipsis")
        if self.options is None:
            text.append("✎ ", style="dim")
            if self.text:
                text.append(self.text, style="dim" if muted else f"bold {pal['accent']}")
            else:
                text.append("(empty)", style="dim")
        else:
            label, value = self.options[self.index]
            if self.options == ON_OFF:
                on = value == "on" and not muted
                text.append("● " if value == "on" else "○ ", style=pal["ok"] if on else "dim")
                text.append(label.upper(), style=f"bold {pal['ok']}" if on else "dim")
            else:
                text.append("‹ ", style="dim")
                text.append(label, style="dim" if muted else f"bold {pal['accent']}")
                text.append(" ›", style="dim")
        target = self.query(".set-value")
        if target:
            target.first(Static).update(text)
        if self.branch:
            name = self.query(".set-label")
            if name:
                name.first(Static).update(self._label(pal))

    def set_value(self, value: str) -> None:
        if self.options is None:
            self.text = value
        else:
            self.index = next((i for i, (_, v) in enumerate(self.options) if v == value), 0)
        self._draw()

    def _edit(self) -> None:
        self.app.push_screen(
            TextEditScreen(self.label, self.text, TEXT_LIMITS[self.key], SETTING_DEFAULTS[self.key]),
            callback=self._edited,
        )

    def _edited(self, result: str | None) -> None:
        if result is None or result == self.text:
            return
        self.text = result
        self._draw()
        self.post_message(self.Changed(self.key, result))

    def action_shift(self, step: int) -> None:
        if self.options is None:
            if step > 0:
                self._edit()
            return
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
        ("d", "preview_dashboard", "Dashboard"),
        ("l", "layout_file", "Layout file"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-panel"):
            with SvcScroll(id="settings-scroll"):
                section = None
                definitions = SETTING_DEFINITIONS
                for index, (key, group, label, options, description) in enumerate(definitions):
                    if group != section:
                        section = group
                        yield Static(group.upper(), classes="set-section")
                    parent = SETTING_PARENTS.get(key)
                    branch = ""
                    if parent:
                        following = definitions[index + 1][0] if index + 1 < len(definitions) else None
                        branch = "├─ " if SETTING_PARENTS.get(following) == parent else "└─ "
                    yield SettingRow(key, label, options, description, settings.get(key), branch)
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
        for row in self.query(SettingRow):
            row.set_class(inactive(row.key, settings.get), "-disabled")
            row._draw()

    def on_descendant_focus(self, event) -> None:
        row = event.widget
        if isinstance(row, SettingRow):
            text = row.description
            if row.has_class("-disabled") and row.key in DASHBOARD_KEYS and settings.get("layout_mode") != "settings":
                text += " Not used while a preset or the layout file is active. Set Layout source to Settings to use it."
            self.query_one("#set-help", Static).update(Text(text))

    def on_setting_row_changed(self, event: SettingRow.Changed) -> None:
        settings.set(event.key, event.value)
        if event.key not in DASHBOARD_KEYS:
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

    def action_preview_dashboard(self) -> None:
        self.app.push_screen(DashboardPreview())

    def action_layout_file(self) -> None:
        mode = settings.get("layout_mode")
        preset = PRESETS.get(mode[7:]) if mode.startswith("preset:") else None
        exists = LAYOUT_PATH.exists()
        if preset is not None:
            state = f"The {preset['label']} preset will be saved to it so you can edit on top of it."
            if exists:
                state += f" Your current file is backed up as {LAYOUT_PATH.name}.bak."
        elif exists:
            state = "The existing file will be opened as it is."
        else:
            state = "It will be created from your current dashboard."
        body = (f"Open ~/.netlabdb/{LAYOUT_PATH.name} in your default text editor?\n\n{state}\n"
                "The layout source will switch to Layout file.")
        self.app.push_screen(
            ActionConfirmScreen("OPEN LAYOUT FILE", body, "Open file", "Cancel"),
            callback=lambda confirmed: self.layout_confirmed(confirmed, preset is not None),
        )

    def layout_confirmed(self, confirmed: bool | None, replace: bool) -> None:
        if not confirmed:
            return
        try:
            path = ensure_layout_file(replace)
        except OSError as error:
            self.notify(f"Could not write the layout file: {error.strerror or error}", severity="error")
            return
        settings.set("layout_mode", "file")
        for row in self.query(SettingRow):
            if row.key == "layout_mode":
                row.set_value("file")
        self._sync()
        opened = open_in_editor(path)
        hint = "" if opened else ". Open it in any editor; changes apply live"
        self.notify(f"Layout file: {path}{hint}", timeout=10)

    def action_reset(self) -> None:
        self.app.push_screen(
            ActionConfirmScreen("RESET SETTINGS",
                                "Restore every setting to its default?\nYour dashboard.json file is not changed.",
                                "Reset", "Cancel"),
            callback=self.reset_confirmed,
        )

    def reset_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        settings.reset()
        for row in self.query(SettingRow):
            row.set_value(settings.get(row.key))
        self._sync()
        self.app.apply_settings()
        self.notify("Settings restored to defaults")