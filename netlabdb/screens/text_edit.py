from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from ..config import STYLE_PATH
from ..helpers import nav_hint_text


class TextEditScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
        ("left", "move_button(-1)", "Previous button"),
        ("right", "move_button(1)", "Next button"),
    ]

    def __init__(self, label: str, value: str, limit: int, default: str):
        super().__init__()
        self.label = label
        self.value = value
        self.limit = limit
        self.default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="text-panel"):
            yield Static(Text(f"Set {self.label.lower()} (up to {self.limit} characters)"), id="text-body")
            with Horizontal(classes="field-row"):
                yield Input(value=self.value, placeholder="Leave empty to hide", id="text-input",
                            max_length=self.limit)
                yield Static("", classes="field-mark")
            with Horizontal(id="text-buttons"):
                yield Button("Save", id="btn-text-save")
                yield Button("Default", id="btn-text-default")
                yield Button("Cancel", id="btn-text-cancel")

    def on_mount(self) -> None:
        panel = self.query_one("#text-panel")
        panel.border_title = self.label.upper()
        panel.border_subtitle = nav_hint_text([("[Enter]", "Save"), ("[Esc]", "Cancel")])
        field = self.query_one("#text-input", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def action_move_button(self, step: int) -> None:
        buttons = list(self.query("#text-buttons Button"))
        if self.focused not in buttons:
            return
        index = buttons.index(self.focused) + step
        buttons[max(0, min(len(buttons) - 1, index))].focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    @on(Button.Pressed, "#btn-text-save")
    def press_save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#btn-text-default")
    def press_default(self) -> None:
        field = self.query_one("#text-input", Input)
        field.value = self.default
        field.cursor_position = len(field.value)
        field.focus()

    @on(Button.Pressed, "#btn-text-cancel")
    def press_cancel(self) -> None:
        self.action_cancel()

    def action_save(self) -> None:
        self.dismiss(self.query_one("#text-input", Input).value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)