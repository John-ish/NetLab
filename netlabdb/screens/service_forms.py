from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from ..config import STYLE_PATH
from ..constants import CUSTOM_SERVICE, SERVICE_INTERVALS, SERVICE_PROTOCOLS
from ..helpers import nav_hint_text
from ..store import store
from .dialogs import ConfirmScreen


class AddServiceScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Add service"),
        ("left", "move_button(-1)", "Previous button"),
        ("right", "move_button(1)", "Next button"),
    ]

    form_title = "ADD SERVICE"
    head_label = "+ New Service"
    submit_label = "Add Service"
    submit_hint = "Add"
    initial_focus = "#sel-service"

    def __init__(self, default_host: str | None = None, original: tuple | None = None):
        super().__init__()
        self.hosts = [h[0] for h in store.all()]
        self.catalog = {name: (port, protocol) for name, port, protocol in store.service_catalog()}
        self.original = original
        if original:
            host, name, port = original
            saved = store.service_details(host, name, port)
            self.default_host = host if host in self.hosts else self.hosts[0]
            self.initial = {
                "type": name if name in self.catalog else CUSTOM_SERVICE,
                "name": name,
                "port": str(port),
                "protocol": saved["protocol"],
                "interval": saved["interval"],
                "description": saved["description"],
            }
        else:
            self.default_host = default_host if default_host in self.hosts else self.hosts[0]
            self.initial = {
                "type": None,
                "name": "",
                "port": "",
                "protocol": "TCP",
                "interval": 5,
                "description": "",
            }
        self.last_type = self.initial["type"]
        self.attempted = False

    def _group(self, label: str, control, last: bool = False, error_id: str | None = None):
        gutter = "  └─\n  " if last else "  ├─\n  │\n  │"
        with Horizontal(classes="tree-group"):
            yield Static(Text(gutter), classes="tree-gutter")
            with Vertical(classes="tree-body"):
                with Horizontal(classes="tree-label-row"):
                    yield Static(label, classes="tree-label")
                    yield Static("", id=error_id, classes="tree-error")
                yield control

    def compose(self) -> ComposeResult:
        service_options = [(name, name) for name in sorted(self.catalog, key=str.lower)]
        service_options.append(("Custom", CUSTOM_SERVICE))
        type_options = {"value": self.initial["type"]} if self.initial["type"] else {}
        with Vertical(id="add-service-panel"):
            yield Static("Host", classes="tree-label")
            yield Select([(h, h) for h in self.hosts], value=self.default_host,
                         allow_blank=False, id="sel-host")
            yield Static("│", classes="tree-top")
            with Horizontal(classes="tree-head"):
                yield Static("└─┬─", classes="tree-branch")
                yield Static(self.head_label, classes="tree-title")
            yield from self._group(
                "Service type",
                Select(service_options, prompt="Select a service type", allow_blank=True,
                       id="sel-service", **type_options),
                error_id="err-service",
            )
            yield from self._group(
                "Service name",
                Input(value=self.initial["name"], placeholder="Enter service name",
                      id="in-name", max_length=13),
                error_id="err-name",
            )
            yield from self._group(
                "Port",
                Input(value=self.initial["port"], placeholder="Enter port number",
                      id="in-port", max_length=5, restrict=r"[0-9]*"),
                error_id="err-port",
            )
            yield from self._group(
                "Protocol",
                Select([(p, p) for p in SERVICE_PROTOCOLS], value=self.initial["protocol"],
                       allow_blank=False, id="sel-protocol"),
            )
            yield from self._group(
                "Monitoring interval",
                Select(SERVICE_INTERVALS, value=self.initial["interval"],
                       allow_blank=False, id="sel-interval"),
            )
            yield from self._group(
                "Description",
                Input(value=self.initial["description"], placeholder="Add a description",
                      id="in-desc", max_length=120),
                last=True,
            )
            with Horizontal(id="service-buttons"):
                yield Button(self.submit_label, id="btn-add")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        panel = self.query_one("#add-service-panel")
        panel.border_title = self.form_title
        panel.border_subtitle = nav_hint_text([
            ("[Tab/Enter]", "Next field"),
            ("[Ctrl+S]", self.submit_hint),
            ("[Esc]", "Cancel"),
        ])
        self.query_one(self.initial_focus).focus()
        self._refresh_form()

    def _choice(self) -> str | None:
        value = self.query_one("#sel-service", Select).value
        return value if isinstance(value, str) else None

    def _text(self, field_id: str) -> str:
        return self.query_one(field_id, Input).value.strip()

    def _selected(self, field_id: str):
        return self.query_one(field_id, Select).value

    def _checks(self) -> dict:
        checks = {
            "service": ("ok", "") if self._choice() else ("empty", "Select a service type"),
            "name": ("ok", "") if self._text("#in-name") else ("empty", "Name is required"),
        }
        port_text = self._text("#in-port")
        if not port_text:
            checks["port"] = ("empty", "Port is required")
        elif not 1 <= int(port_text) <= 65535:
            checks["port"] = ("error", "Port must be between 1 and 65535")
        else:
            owner = store.port_owner(
                self._selected("#sel-host"),
                int(port_text),
                self._selected("#sel-protocol"),
                ignore=self.original,
            )
            checks["port"] = ("error", f"Port {port_text} is used by {owner}") if owner else ("ok", "")
        return checks

    def _refresh_form(self) -> None:
        checks = self._checks()
        for key, field_id in (("service", None), ("name", "#in-name"), ("port", "#in-port")):
            state, message = checks[key]
            show = state == "error" or (state == "empty" and self.attempted)
            self.query_one(f"#err-{key}", Static).update(Text(message) if show else "")
            if field_id:
                self.query_one(field_id, Input).set_class(show, "-invalid")
        self.query_one("#btn-add", Button).disabled = any(state != "ok" for state, _ in checks.values())

    def _type_changed(self) -> None:
        choice = self._choice()
        if choice == self.last_type:
            return
        self.last_type = choice
        name = self.query_one("#in-name", Input)
        port = self.query_one("#in-port", Input)
        protocol = self.query_one("#sel-protocol", Select)
        if choice == CUSTOM_SERVICE:
            name.value = ""
            port.value = ""
            protocol.value = "TCP"
            self.query_one("#sel-interval", Select).value = 5
            self.query_one("#in-desc", Input).value = ""
            name.focus()
        elif choice in self.catalog:
            default_port, default_protocol = self.catalog[choice]
            name.value = choice
            port.value = str(default_port)
            protocol.value = default_protocol

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "sel-service":
            self._type_changed()
        self._refresh_form()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_form()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "in-desc":
            self.action_save()
        else:
            self.focus_next()

    @on(Button.Pressed, "#btn-add")
    def press_add(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#btn-cancel")
    def press_cancel(self) -> None:
        self.action_cancel()

    def action_move_button(self, step: int) -> None:
        buttons = [b for b in self.query("#service-buttons Button") if not b.disabled]
        if self.focused not in buttons:
            return
        index = buttons.index(self.focused) + step
        buttons[max(0, min(len(buttons) - 1, index))].focus()

    def action_save(self) -> None:
        self.attempted = True
        self._refresh_form()
        checks = self._checks()
        targets = {"service": "#sel-service", "name": "#in-name", "port": "#in-port"}
        for key, field_id in targets.items():
            if checks[key][0] != "ok":
                self.query_one(field_id).focus()
                return
        self.dismiss({
            "original": self.original,
            "host": self._selected("#sel-host"),
            "name": self._text("#in-name"),
            "port": int(self._text("#in-port")),
            "protocol": self._selected("#sel-protocol"),
            "interval": self._selected("#sel-interval"),
            "description": self._text("#in-desc"),
        })

    def action_cancel(self) -> None:
        current = (
            self._choice(),
            self._text("#in-name"),
            self._text("#in-port"),
            self._selected("#sel-protocol"),
            self._selected("#sel-interval"),
            self._text("#in-desc"),
            self._selected("#sel-host"),
        )
        initial = (
            self.initial["type"],
            self.initial["name"],
            self.initial["port"],
            self.initial["protocol"],
            self.initial["interval"],
            self.initial["description"],
            self.default_host,
        )
        if current == initial:
            self.dismiss(None)
            return
        self.app.push_screen(
            ConfirmScreen("DISCARD SERVICE?", "You have unsaved changes.", "Discard", "Keep editing"),
            callback=self.discard_answer,
        )

    def discard_answer(self, discard: bool | None) -> None:
        if discard:
            self.dismiss(None)


class EditServiceScreen(AddServiceScreen):

    form_title = "EDIT SERVICE"
    head_label = "~ Edit Service"
    submit_label = "Save Changes"
    submit_hint = "Save"
    initial_focus = "#in-name"

    def __init__(self, original: tuple):
        super().__init__(original=original)
