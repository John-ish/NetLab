from textual.widgets import Button

from ..helpers import nav_hint_text
from .dialogs import ConfirmScreen


class ActionConfirmScreen(ConfirmScreen):

    BINDINGS = [
        ("y", "answer(True)", "Confirm"),
        ("n", "answer(False)", "Cancel"),
        ("escape", "answer(False)", "Cancel"),
        ("left", "pick('#btn-yes')", "Confirm"),
        ("right", "pick('#btn-no')", "Cancel"),
        ("d", "noop", ""),
    ]

    def on_mount(self) -> None:
        panel = self.query_one("#confirm-panel")
        panel.border_title = self.heading
        panel.border_subtitle = nav_hint_text([("[Y]", self.yes_text), ("[N]", self.no_text)])
        self.query_one("#btn-no", Button).focus()

    def action_noop(self) -> None:
        pass