from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from ..config import STYLE_PATH
from ..constants import HOST_ICON, SERVICE_INTERVALS, SPINNER_FRAMES, SUDO_ATTEMPTS
from ..helpers import interval_label, nav_hint_text
from ..store import store
from ..sudo import verify_sudo_password


class ConfirmScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("d", "answer(True)", "Discard"),
        ("n", "answer(False)", "Keep editing"),
        ("escape", "answer(False)", "Keep editing"),
        ("left", "pick('#btn-yes')", "Discard"),
        ("right", "pick('#btn-no')", "Keep editing"),
    ]

    def __init__(self, heading: str, body_text: str, yes_text: str, no_text: str):
        super().__init__()
        self.heading = heading
        self.body_text = body_text
        self.yes_text = yes_text
        self.no_text = no_text

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-panel"):
            yield Static(Text(self.body_text), id="confirm-body")
            with Horizontal(id="confirm-buttons"):
                yield Button(self.yes_text, id="btn-yes")
                yield Button(self.no_text, id="btn-no")

    def on_mount(self) -> None:
        panel = self.query_one("#confirm-panel")
        panel.border_title = self.heading
        panel.border_subtitle = nav_hint_text(
            [("[D]", self.yes_text), ("[N]", self.no_text)]
        )
        self.query_one("#btn-no", Button).focus()

    def action_answer(self, result: bool) -> None:
        self.dismiss(result)

    def action_pick(self, selector: str) -> None:
        self.query_one(selector, Button).focus()

    @on(Button.Pressed, "#btn-yes")
    def press_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-no")
    def press_no(self) -> None:
        self.dismiss(False)


class IntervalScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "apply", "Apply"),
        ("left", "move_button(-1)", "Previous button"),
        ("right", "move_button(1)", "Next button"),
    ]

    def __init__(self, target: str, current: int):
        super().__init__()
        self.target = target
        self.current = current

    def compose(self) -> ComposeResult:
        options = list(SERVICE_INTERVALS)
        if all(value != self.current for _, value in options):
            options = sorted(options + [(interval_label(self.current), self.current)], key=lambda o: o[1])
        with Vertical(id="interval-panel"):
            yield Static(Text(f"Check {self.target} every:"), id="interval-body")
            yield Select(options, value=self.current, allow_blank=False, id="sel-every")
            with Horizontal(id="interval-buttons"):
                yield Button("Apply", id="btn-apply")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        panel = self.query_one("#interval-panel")
        panel.border_title = "MONITORING INTERVAL"
        panel.border_subtitle = nav_hint_text([
            ("[Enter]", "Open list"),
            ("[Ctrl+S]", "Apply"),
            ("[Esc]", "Cancel"),
        ])
        self.query_one("#sel-every", Select).focus()

    def action_move_button(self, step: int) -> None:
        buttons = list(self.query("#interval-buttons Button"))
        if self.focused not in buttons:
            return
        index = buttons.index(self.focused) + step
        buttons[max(0, min(len(buttons) - 1, index))].focus()

    @on(Button.Pressed, "#btn-apply")
    def press_apply(self) -> None:
        self.action_apply()

    @on(Button.Pressed, "#btn-cancel")
    def press_cancel(self) -> None:
        self.action_cancel()

    def action_apply(self) -> None:
        self.dismiss(int(self.query_one("#sel-every", Select).value))

    def action_cancel(self) -> None:
        self.dismiss(None)


class DeleteHostScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("left", "pick('#btn-delete')", "Delete"),
        ("right", "pick('#btn-cancel')", "Cancel"),
    ]

    def __init__(self, host_name: str):
        super().__init__()
        self.host_name = host_name

    def compose(self) -> ComposeResult:
        host = next((h for h in store.all() if h[0] == self.host_name), None)
        status = host[1] if host else "offline"
        address = store.details(self.host_name)["address"] or "No address saved"
        count = store.service_count(self.host_name)
        services = "No services" if count == 0 else f"{count} service" + ("" if count == 1 else "s")
        with Vertical(id="delete-panel"):
            yield Static("Are you sure you want to remove:", classes="del-label")
            with Horizontal(id="del-host-row"):
                yield Static(Text(self.host_name), id="del-name")
                yield Static(f"{HOST_ICON[status]} {status.upper()}", id="del-status", classes=status)
            yield Static(Text(address), id="del-address")
            yield Static("This will permanently remove:", classes="del-label")
            yield Static(Text(f"  {services}"), classes="del-item")
            yield Static("  Monitoring history", classes="del-item")
            yield Static("  Host-related logs", classes="del-item")
            yield Static("This action cannot be undone.", classes="del-label", id="del-warning")
            with Horizontal(id="delete-buttons"):
                yield Button("Delete Host", id="btn-delete")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        panel = self.query_one("#delete-panel")
        panel.border_title = "DELETE HOST"
        panel.border_subtitle = nav_hint_text([("[Enter]", "Select"), ("[Esc]", "Cancel")])
        self.query_one("#btn-cancel", Button).focus()

    def action_pick(self, selector: str) -> None:
        self.query_one(selector, Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-delete")
    def press_delete(self) -> None:
        self.dismiss(self.host_name)

    @on(Button.Pressed, "#btn-cancel")
    def press_cancel(self) -> None:
        self.dismiss(None)


class DeleteServiceScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("left", "pick('#btn-delete')", "Delete"),
        ("right", "pick('#btn-cancel')", "Cancel"),
    ]

    def __init__(self, original: tuple):
        super().__init__()
        self.original = original

    def compose(self) -> ComposeResult:
        host, name, port = self.original
        protocol = store.service_details(host, name, port)["protocol"]
        with Vertical(id="delete-panel"):
            yield Static(Text(host), id="dels-host")
            yield Static("│", classes="dels-branch")
            with Horizontal(classes="dels-line"):
                yield Static("└── ", classes="dels-branch")
                yield Static(Text(name), id="dels-name")
            with Horizontal(classes="dels-line"):
                yield Static("     └── ", classes="dels-branch")
                yield Static(Text(f"{protocol} :{port}"), id="dels-port")
            yield Static("Remove this service from monitoring?", classes="del-label")
            yield Static("Monitoring history for this service will also be removed.", classes="del-note")
            with Horizontal(id="delete-buttons"):
                yield Button("Delete Service", id="btn-delete")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        panel = self.query_one("#delete-panel")
        panel.border_title = "DELETE SERVICE"
        panel.border_subtitle = nav_hint_text([("[Enter]", "Select"), ("[Esc]", "Cancel")])
        self.query_one("#btn-cancel", Button).focus()

    def action_pick(self, selector: str) -> None:
        self.query_one(selector, Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-delete")
    def press_delete(self) -> None:
        self.dismiss(self.original)

    @on(Button.Pressed, "#btn-cancel")
    def press_cancel(self) -> None:
        self.dismiss(None)


class SudoScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, service: str):
        super().__init__()
        self.service = service
        self.failures = 0
        self.busy = False
        self.spin_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="sudo-panel"):
            yield Static(Text(f"Enter your sudo password to reveal the password for {self.service}."), id="sudo-body")
            yield Input(password=True, placeholder="sudo password", id="sudo-input", max_length=128)
            yield Static("", id="sudo-status")
            with Horizontal(id="sudo-buttons"):
                yield Button("Unlock", id="btn-unlock")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        panel = self.query_one("#sudo-panel")
        panel.border_title = "UNLOCK PASSWORD"
        panel.border_subtitle = nav_hint_text([("[Enter]", "Unlock"), ("[Esc]", "Cancel")])
        self.query_one("#sudo-input", Input).focus()
        self.set_interval(0.1, self._spin)

    def _spin(self) -> None:
        if not self.busy:
            return
        self.spin_index = (self.spin_index + 1) % len(SPINNER_FRAMES)
        self._status(f"{SPINNER_FRAMES[self.spin_index]} Verifying…", "busy")

    def _status(self, message: str, kind: str = "bad") -> None:
        status = self.query_one("#sudo-status", Static)
        status.update(Text(message))
        status.set_class(kind == "busy", "-busy")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.submit()

    @on(Button.Pressed, "#btn-unlock")
    def press_unlock(self) -> None:
        self.submit()

    @on(Button.Pressed, "#btn-cancel")
    def press_cancel(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def submit(self) -> None:
        if self.busy:
            return
        field = self.query_one("#sudo-input", Input)
        password = field.value
        field.value = ""
        self.busy = True
        self.spin_index = 0
        self._status(f"{SPINNER_FRAMES[0]} Verifying…", "busy")
        self.run_worker(self._verify(password), exclusive=True)

    async def _verify(self, password: str) -> None:
        try:
            granted, error = await verify_sudo_password(password)
        except Exception:
            granted, error = False, "Could not verify the password"
        self.busy = False
        if granted:
            self.dismiss(True)
            return
        self.failures += 1
        if self.failures >= SUDO_ATTEMPTS:
            self.dismiss(False)
            return
        self._status(f"× {error} ({SUDO_ATTEMPTS - self.failures} attempts left)")
        self.query_one("#sudo-input", Input).focus()


class AccessScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
        ("left", "move_button(-1)", "Previous button"),
        ("right", "move_button(1)", "Next button"),
    ]

    def __init__(self, original: tuple):
        super().__init__()
        self.original = original
        self.saved = store.service_access(*original)

    def compose(self) -> ComposeResult:
        with Vertical(id="access-panel"):
            yield Static(Text(f"Credentials for {self.original[1]} on {self.original[0]}"), id="access-body")
            yield Static("Username (optional)", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(value=self.saved["username"] or "", placeholder="Enter username", id="in-user", max_length=100)
                yield Static("", classes="field-mark")
            yield Static("Password", classes="field-label")
            placeholder = "Leave blank to keep the current password" if self.saved["password"] else "Enter password"
            with Horizontal(classes="field-row"):
                yield Input(password=True, placeholder=placeholder, id="in-pass", max_length=200)
                yield Static("", classes="field-mark")
            yield Static("Password display", classes="field-label")
            yield Select(
                [("Hidden · sudo password to reveal", "hidden"), ("Always visible", "visible")],
                value="visible" if self.saved["visible"] else "hidden", allow_blank=False, id="sel-visible",
            )
            yield Static("Stored as plain text in the database.", classes="del-note")
            with Horizontal(id="access-buttons"):
                yield Button("Save", id="btn-save")
                yield Button("Remove", id="btn-remove")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        panel = self.query_one("#access-panel")
        panel.border_title = "ACCESS"
        panel.border_subtitle = nav_hint_text([("[Tab/Enter]", "Next field"), ("[Ctrl+S]", "Save"), ("[Esc]", "Cancel")])
        self.query_one("#btn-remove", Button).disabled = not (self.saved["username"] or self.saved["password"])
        self.query_one("#in-user", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.focus_next()

    def action_move_button(self, step: int) -> None:
        buttons = [b for b in self.query("#access-buttons Button") if not b.disabled]
        if self.focused not in buttons:
            return
        index = buttons.index(self.focused) + step
        buttons[max(0, min(len(buttons) - 1, index))].focus()

    @on(Button.Pressed, "#btn-save")
    def press_save(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#btn-remove")
    def press_remove(self) -> None:
        self.dismiss({"username": None, "password": None, "visible": False})

    @on(Button.Pressed, "#btn-cancel")
    def press_cancel(self) -> None:
        self.action_cancel()

    def action_save(self) -> None:
        username = self.query_one("#in-user", Input).value.strip() or None
        typed = self.query_one("#in-pass", Input).value
        password = typed or self.saved["password"]
        if username is None and password is None:
            self.dismiss(None)
            return
        self.dismiss({
            "username": username,
            "password": password,
            "visible": self.query_one("#sel-visible", Select).value == "visible",
        })

    def action_cancel(self) -> None:
        self.dismiss(None)
