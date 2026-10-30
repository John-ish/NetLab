from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from ..config import STYLE_PATH
from ..constants import SPINNER_FRAMES, SSH_USER_RE
from ..helpers import nav_hint_text
from ..network import address_kind, normalize_address, probe_host
from ..store import store
from .dialogs import ConfirmScreen
from .ssh_setup import SshSetupScreen


class AddHostScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Add host"),
        ("ctrl+g", "ssh_setup", "SSH setup"),
        ("left", "move_button(-1)", "Previous button"),
        ("right", "move_button(1)", "Next button"),
    ]

    form_title = "ADD HOST"
    submit_label = "Add Host"
    submit_hint = "Add host"

    def __init__(self, original: str | None = None):
        super().__init__()
        self.original = original
        saved = store.details(original) if original else {"address": "", "description": ""}
        self.initial = {
            "name": original or "",
            "address": saved["address"],
            "description": saved["description"],
            "ssh_user": saved.get("ssh_user") or "",
            "ssh_port": str(saved["ssh_port"]) if saved.get("ssh_port") else "",
        }
        self.attempted = False
        self.testing = False
        self.test_state = None
        self.spin_index = 0
        self.spin_label = ""

    def _spin(self) -> None:
        if not self.testing:
            return
        self.spin_index = (self.spin_index + 1) % len(SPINNER_FRAMES)
        self._show_test("busy", f"{SPINNER_FRAMES[self.spin_index]} {self.spin_label}")

    def compose(self) -> ComposeResult:
        with Vertical(id="add-host-panel"):
            yield Static(Text.assemble("Host name ", ("*", "bold #ff5555")), classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(value=self.initial["name"], placeholder="Enter host name", id="in-name", max_length=64)
                yield Static("", id="mark-name", classes="field-mark")
            yield Static("", id="err-name", classes="field-error")

            yield Static(Text.assemble("Address (IP or hostname) ", ("*", "bold #ff5555")), classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(value=self.initial["address"], placeholder="192.168.1.20 or nas.local", id="in-address", max_length=45)
                yield Static("", id="mark-address", classes="field-mark")
            yield Static("", id="err-address", classes="field-error")

            yield Static("Description (optional)", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(value=self.initial["description"], placeholder="Add a description", id="in-desc", max_length=120)
                yield Static("", classes="field-mark")

            yield Static("SSH user (optional, enables live metrics)", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(value=self.initial["ssh_user"], placeholder="ubuntu", id="in-ssh-user", max_length=64)
                yield Static("", id="mark-ssh-user", classes="field-mark")
            yield Static("", id="err-ssh-user", classes="field-error")

            yield Static("SSH port (optional)", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(value=self.initial["ssh_port"], placeholder="22", id="in-ssh-port",
                            max_length=5, restrict=r"[0-9]*")
                yield Static("", id="mark-ssh-port", classes="field-mark")
            yield Static("", id="err-ssh-port", classes="field-error")

            yield Static("", id="test-result")
            with Horizontal(id="add-buttons"):
                yield Button("Test connection", id="btn-test")
                yield Button("SSH setup", id="btn-test-ssh")
                yield Button(self.submit_label, id="btn-add")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        panel = self.query_one("#add-host-panel")
        panel.border_title = self.form_title
        panel.border_subtitle = nav_hint_text([
            ("[Tab/Enter]", "Next field"),
            ("[Ctrl+S]", self.submit_hint),
            ("[Esc]", "Cancel"),
        ])
        self.query_one("#in-name", Input).focus()
        self.set_interval(0.1, self._spin)
        self._refresh_form()

    def _field_text(self, field_id: str) -> str:
        return self.query_one(field_id, Input).value.strip()

    def _check_name(self, name: str) -> tuple[str, str]:
        if not name:
            return "empty", "Host name is required"
        if store.name_taken(name, ignore=self.original):
            return "error", f"“{name}” is already in use"
        return "ok", ""

    def _check_address(self, address: str) -> tuple[str, str]:
        if not address:
            return "empty", "Address is required"
        if address_kind(address) is None:
            return "error", "Enter a valid IP address or hostname"
        owner = store.address_owner(address, ignore=self.original)
        if owner:
            return "error", f"Already used by {owner}"
        return "ok", ""

    def _check_ssh_user(self, user: str) -> tuple[str, str]:
        if not user:
            return "blank", ""
        if not SSH_USER_RE.match(user):
            return "error", "Enter a valid SSH user name"
        return "ok", ""

    def _check_ssh_port(self, port: str) -> tuple[str, str]:
        if not port:
            return "blank", ""
        if not 1 <= int(port) <= 65535:
            return "error", "Port must be between 1 and 65535"
        return "ok", ""

    def _checks(self) -> dict:
        return {
            "name": self._check_name(self._field_text("#in-name")),
            "address": self._check_address(self._field_text("#in-address")),
            "ssh-user": self._check_ssh_user(self._field_text("#in-ssh-user")),
            "ssh-port": self._check_ssh_port(self._field_text("#in-ssh-port")),
        }

    def _refresh_form(self) -> None:
        checks = self._checks()
        for key in ("name", "address", "ssh-user", "ssh-port"):
            state, message = checks[key]
            show = state == "error" or (state == "empty" and self.attempted)
            self.query_one(f"#in-{key}", Input).set_class(show, "-invalid")
            mark = self.query_one(f"#mark-{key}", Static)
            mark.update("✓" if state == "ok" else "×" if show else "")
            mark.set_class(state == "ok", "-ok")
            mark.set_class(show, "-bad")
            self.query_one(f"#err-{key}", Static).update(Text(message) if show else "")
        valid = all(state in ("ok", "blank") for state, _ in checks.values())
        self.query_one("#btn-add", Button).disabled = not valid
        self.query_one("#btn-test", Button).disabled = checks["address"][0] != "ok"
        self.query_one("#btn-test-ssh", Button).disabled = (
            checks["address"][0] != "ok" or checks["ssh-port"][0] == "error"
        )

    def _show_test(self, kind: str, message: str) -> None:
        result = self.query_one("#test-result", Static)
        result.update(Text(message))
        for name in ("ok", "bad", "busy"):
            result.set_class(kind == name, f"-{name}")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in ("in-address", "in-ssh-user", "in-ssh-port"):
            self.workers.cancel_node(self)
            self.testing = False
            if event.input.id == "in-address":
                self.test_state = None
            self._show_test("", "")
        self._refresh_form()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        order = ["in-name", "in-address", "in-desc", "in-ssh-user", "in-ssh-port"]
        index = order.index(event.input.id)
        if index < len(order) - 1:
            self.query_one(f"#{order[index + 1]}", Input).focus()
        else:
            self.action_save()

    @on(Button.Pressed, "#btn-test")
    def press_test(self) -> None:
        self.action_test()

    @on(Button.Pressed, "#btn-add")
    def press_add(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#btn-cancel")
    def press_cancel(self) -> None:
        self.action_cancel()

    def action_move_button(self, step: int) -> None:
        buttons = [b for b in self.query("#add-buttons Button") if not b.disabled]
        if self.focused not in buttons:
            return
        index = buttons.index(self.focused) + step
        buttons[max(0, min(len(buttons) - 1, index))].focus()

    def action_test(self) -> None:
        address = self._field_text("#in-address")
        if self.testing or self._check_address(address)[0] != "ok":
            return
        self.testing = True
        self.test_state = None
        self.spin_label = f"Testing {address}…"
        self._show_test("busy", f"{SPINNER_FRAMES[0]} {self.spin_label}")
        self._refresh_form()
        self.run_worker(self._run_test(address), exclusive=True)

    async def _run_test(self, address: str) -> None:
        try:
            resolved, latency, error = await probe_host(address)
        except Exception:
            resolved, latency, error = None, None, "The test could not be completed"
        if self._field_text("#in-address") != address:
            return
        self.testing = False
        if error:
            self._show_test("bad", f"× {error}")
        else:
            ms = max(1, round(latency))
            self.test_state = {"address": address, "latency": ms}
            self._show_test("ok", f"✓ Reachable · {resolved} · {ms} ms")
        self._refresh_form()

    @on(Button.Pressed, "#btn-test-ssh")
    def press_test_ssh(self) -> None:
        self.action_ssh_setup()

    def action_ssh_setup(self) -> None:
        address = self._field_text("#in-address")
        checks = self._checks()
        if self.testing or checks["address"][0] != "ok" or checks["ssh-port"][0] == "error":
            return
        port_text = self._field_text("#in-ssh-port")
        self.app.push_screen(
            SshSetupScreen(normalize_address(address), self._field_text("#in-ssh-user") or None,
                           int(port_text) if port_text else None),
            callback=self.ssh_setup_done,
        )

    def ssh_setup_done(self, result: dict | None) -> None:
        if not result:
            return
        user_field = self.query_one("#in-ssh-user", Input)
        port_field = self.query_one("#in-ssh-port", Input)
        with user_field.prevent(Input.Changed), port_field.prevent(Input.Changed):
            user_field.value = result["user"]
            port_field.value = str(result["port"]) if result["port"] else ""
        self._show_test("ok", f"✓ SSH ready · {result['user']}@{self._field_text('#in-address')} · Linux")
        self._refresh_form()

    def action_save(self) -> None:
        self.attempted = True
        self._refresh_form()
        checks = self._checks()
        for key in ("name", "address", "ssh-user", "ssh-port"):
            if checks[key][0] not in ("ok", "blank"):
                self.query_one(f"#in-{key}", Input).focus()
                return
        address = self._field_text("#in-address")
        ssh_user = self._field_text("#in-ssh-user") or None
        ssh_port = int(self._field_text("#in-ssh-port")) if ssh_user and self._field_text("#in-ssh-port") else None
        tested = self.test_state if self.test_state and self.test_state["address"] == address else None
        self.dismiss({
            "original": self.original,
            "name": self._field_text("#in-name"),
            "address": address,
            "description": self._field_text("#in-desc"),
            "ssh_user": ssh_user,
            "ssh_port": ssh_port,
            "reachable": tested is not None,
            "latency": tested["latency"] if tested else None,
        })

    def action_cancel(self) -> None:
        fields = {"name": "#in-name", "address": "#in-address", "description": "#in-desc",
                  "ssh_user": "#in-ssh-user", "ssh_port": "#in-ssh-port"}
        dirty = any(
            self._field_text(selector) != self.initial[key].strip()
            for key, selector in fields.items()
        )
        if not dirty:
            self.dismiss(None)
            return
        self.app.push_screen(
            ConfirmScreen("DISCARD HOST?", "You have unsaved changes.", "Discard", "Keep editing"),
            callback=self.discard_answer,
        )

    def discard_answer(self, discard: bool | None) -> None:
        if discard:
            self.dismiss(None)


class EditHostScreen(AddHostScreen):

    form_title = "EDIT HOST"
    submit_label = "Save Changes"
    submit_hint = "Save"

    def __init__(self, original: str):
        super().__init__(original)
