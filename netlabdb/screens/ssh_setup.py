from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from ..config import STYLE_PATH
from ..constants import SPINNER_FRAMES, SSH_DEFAULT_PORT, SSH_MISSING, SSH_USER_RE
from ..helpers import nav_hint_text, newtext, palette, put
from ..ssh import (
    INSTALL_SCRIPT, SshError, authorized_line, ensure_keypair, forget_host, key_fingerprint,
    known_keys, remote_missing_tools, save_host_keys, scan_host_keys, ssh_install_hint,
    ssh_missing_tools, ssh_reason, ssh_run,
)


SSH_STEPS = [
    "Check local SSH tools",
    "Verify host key",
    "Create dedicated SSH key",
    "Authorize key on the server",
    "Test connection",
]


class SshSetupScreen(ModalScreen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, address: str, user: str | None = None, port: int | None = None):
        super().__init__()
        self.address = address
        self.initial_user = user or ""
        self.initial_port = str(port) if port else ""
        self.phase = "form"
        self.steps = ["pending"] * len(SSH_STEPS)
        self.note = ""
        self.scanned = []
        self.pub = ""
        self.target = None
        self.result = None
        self.manual = False
        self.spin_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="ssh-panel"):
            yield Static(Text(f"Set up key-based SSH for {self.address} so live metrics are collected securely. "
                              "Use a dedicated non-root account where possible."), id="ssh-intro")
            yield Static("SSH user", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(value=self.initial_user, placeholder="ubuntu", id="ssh-user", max_length=32)
                yield Static("", classes="field-mark")
            yield Static("SSH port", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(value=self.initial_port, placeholder="22", id="ssh-port")
                yield Static("", classes="field-mark")
            yield Static("", id="ssh-steps")
            yield Static("Server password (used once to install the key, never stored)",
                         id="ssh-pass-label", classes="field-label")
            with Horizontal(classes="field-row", id="ssh-pass-row"):
                yield Input(password=True, placeholder="Password", id="ssh-pass", max_length=128)
                yield Static("", classes="field-mark")
            yield Static("", id="ssh-note")
            with Horizontal(id="ssh-buttons"):
                yield Button("Start", id="btn-ssh-main")
                yield Button("Show command", id="btn-ssh-alt")
                yield Button("Cancel", id="btn-ssh-cancel")

    def on_mount(self) -> None:
        panel = self.query_one("#ssh-panel")
        panel.border_title = "GUIDED SSH SETUP"
        panel.border_subtitle = nav_hint_text([("[Tab]", "Next"), ("[Enter]", "Continue"), ("[Esc]", "Cancel")])
        self.set_interval(0.1, self._spin)
        self._sync()
        self.query_one("#ssh-user", Input).focus()

    def _spin(self) -> None:
        if "running" in self.steps:
            self.spin_index = (self.spin_index + 1) % len(SPINNER_FRAMES)
            self._draw()

    def _draw(self) -> None:
        pal = palette(self.app)
        icons = {
            "pending": ("○", "dim"), "running": (SPINNER_FRAMES[self.spin_index], pal["warn"]),
            "ok": ("✓", pal["ok"]), "bad": ("×", pal["bad"]), "wait": ("◐", pal["warn"]),
        }
        lines = []
        for label, state in zip(SSH_STEPS, self.steps):
            icon, style = icons[state]
            line = newtext()
            line.append(f" {icon} ", style=style)
            line.append(label, style="dim" if state == "pending" else None)
            lines.append(line)
        put(self.query_one("#ssh-steps", Static), newtext("\n").join(lines))
        color = {"error": pal["bad"], "done": pal["ok"], "changed": pal["bad"]}.get(self.phase)
        put(self.query_one("#ssh-note", Static), Text(self.note, style=color or ""))

    def _sync(self) -> None:
        phase = self.phase
        editable = phase in ("form", "error")
        for field in ("#ssh-user", "#ssh-port"):
            self.query_one(field, Input).disabled = not editable
        installing = phase == "install"
        self.query_one("#ssh-pass-label").display = installing
        self.query_one("#ssh-pass-row").display = installing
        main = self.query_one("#btn-ssh-main", Button)
        alt = self.query_one("#btn-ssh-alt", Button)
        labels = {"form": "Start", "busy": "Working…", "trust": "Trust & continue", "changed": "Replace key",
                  "install": "Install key", "manual": "Verify", "error": "Retry", "done": "Done"}
        main.label = labels[phase]
        main.disabled = phase == "busy"
        alt.display = phase in ("install", "manual")
        alt.label = "Copy command" if phase == "manual" else "Show command"
        self._draw()
        if phase == "install":
            self.query_one("#ssh-pass", Input).focus()
        elif phase in ("trust", "changed", "manual", "done"):
            main.focus()

    def _go(self, work) -> None:
        self.phase = "busy"
        self._sync()
        self.run_worker(work, exclusive=True)

    def _fail(self, step: int, message: str) -> None:
        self.steps[step] = "bad"
        self.note = message
        self.phase = "error"
        self._sync()

    def _fingerprints(self, heading: str) -> str:
        lines = [heading, ""]
        for kind, blob, _ in self.scanned:
            lines.append(f"  {kind.replace('ssh-', '').replace('ecdsa-sha2-', 'ecdsa-').upper():<14}{key_fingerprint(blob)}")
        lines += ["", "To double-check, run on the server:  ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"]
        return "\n".join(lines)

    def _start(self) -> None:
        user = self.query_one("#ssh-user", Input).value.strip()
        port_text = self.query_one("#ssh-port", Input).value.strip()
        if not SSH_USER_RE.match(user):
            self.note, self.phase = "Enter a valid SSH user name", "error"
            self._sync()
            return
        if port_text and not (port_text.isascii() and port_text.isdigit() and len(port_text) <= 5):
            self.note, self.phase = "Port must be a number between 1 and 65535", "error"
            self._sync()
            return
        port = int(port_text) if port_text else SSH_DEFAULT_PORT
        if not 1 <= port <= 65535:
            self.note, self.phase = "Port must be between 1 and 65535", "error"
            self._sync()
            return
        self.target = (user, port)
        self.manual = False
        self._go(self._scan())

    async def _scan(self) -> None:
        user, port = self.target
        self.steps = ["running"] + ["pending"] * (len(SSH_STEPS) - 1)
        self.note = ""
        self._draw()
        missing = ssh_missing_tools()
        if missing:
            self._fail(0, f"Missing: {', '.join(missing)}. {ssh_install_hint()}.")
            return
        self.steps[0], self.steps[1] = "ok", "running"
        self._draw()
        try:
            self.scanned = await scan_host_keys(self.address, port)
        except SshError as error:
            self._fail(1, error.message)
            return
        known = known_keys(self.address, port)
        if not known:
            self.steps[1] = "wait"
            self.note = self._fingerprints("This server's host key is not trusted yet. Make sure these are its fingerprints:")
            self.phase = "trust"
            self._sync()
            return
        changed = any(kind in known and known[kind] != blob for kind, blob, _ in self.scanned)
        if not changed and any(known.get(kind) == blob for kind, blob, _ in self.scanned):
            self.steps[1] = "ok"
            await self._keys_stage()
            return
        self.steps[1] = "bad"
        self.note = self._fingerprints("WARNING: the host key differs from the one you trusted before. The server may "
                                       "have been reinstalled, or someone may be intercepting the connection. New fingerprints:")
        self.phase = "changed"
        self._sync()

    async def _trust(self, replace: bool) -> None:
        _, port = self.target
        try:
            if replace:
                forget_host(self.address, port)
            save_host_keys([line for _, _, line in self.scanned])
        except OSError as error:
            self._fail(1, f"Could not save the host key: {error.strerror or error}")
            return
        self.steps[1] = "ok"
        await self._keys_stage()

    async def _keys_stage(self) -> None:
        self.steps[2] = "running"
        self._draw()
        try:
            self.pub = await ensure_keypair()
        except SshError as error:
            self._fail(2, error.message)
            return
        self.steps[2] = "ok"
        await self._connect()

    async def _key_login(self) -> bool:
        user, port = self.target
        try:
            code, out, err = await ssh_run(self.address, user, port, "uname -s")
        except OSError:
            raise SshError(SSH_MISSING, True)
        if code == 0:
            if out.strip().lower() == "linux":
                return True
            raise SshError(f"Unsupported system: {out.strip() or 'unknown'}. Only Linux servers can be monitored", True)
        reason = ssh_reason(err, code)
        if reason.kind == "auth":
            return False
        raise reason

    async def _connect(self) -> None:
        user, port = self.target
        self.steps[3], self.steps[4] = "running", "pending"
        self._draw()
        try:
            authorized = await self._key_login()
        except SshError as error:
            self._fail(3, error.message)
            return
        if not authorized:
            self.steps[3] = "wait"
            if self.manual:
                self.phase = "manual"
                self.note = "The server still does not accept the key. Run the command below on the server, then press Verify.\n\n" + self._command()
            else:
                self.phase = "install"
                self.note = ("The server does not accept the NETLAB key yet. Enter the server password to install it "
                             "automatically, or press Show command to do it yourself.")
            self._sync()
            return
        self.steps[3], self.steps[4] = "ok", "running"
        self._draw()
        try:
            missing = await remote_missing_tools(self.address, user, port)
        except (OSError, SshError):
            missing = []
        self.steps[4] = "ok"
        self.result = {"user": user, "port": None if port == SSH_DEFAULT_PORT else port}
        self.note = f"SSH is ready for {user}@{self.address}. Live metrics will start as soon as you press Done."
        if missing:
            self.note += f"\nOptional tools missing on the server: {', '.join(missing)}"
        self.phase = "done"
        self._sync()

    def _command(self) -> str:
        line = authorized_line(self.pub)
        return ("mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                f"echo '{line}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys")

    def _install(self) -> None:
        field = self.query_one("#ssh-pass", Input)
        password = field.value
        if not password:
            self.note = "Enter the server password first"
            self._draw()
            return
        field.value = ""
        self._go(self._do_install(password))

    async def _do_install(self, password: str) -> None:
        user, port = self.target
        self.steps[3] = "running"
        self._draw()
        script = INSTALL_SCRIPT.format(blob=self.pub.split()[1], line=authorized_line(self.pub))
        try:
            code, _, err = await ssh_run(self.address, user, port, "sh -s", 30, script, password)
        except OSError:
            self._fail(3, SSH_MISSING)
            return
        finally:
            password = ""
        if code != 0:
            reason = ssh_reason(err, code)
            self.steps[3] = "wait"
            self.phase = "install"
            self.note = ("Password login failed or is disabled on this server. Use Show command instead."
                         if reason.kind == "auth" else reason.message)
            self._sync()
            return
        await self._connect()

    def _show_manual(self) -> None:
        self.manual = True
        self.phase = "manual"
        self.note = "Run this on the server as the SSH user, then press Verify:\n\n" + self._command()
        self._sync()

    def action_main(self) -> None:
        phase = self.phase
        if phase in ("form", "error"):
            self._start()
        elif phase == "trust":
            self._go(self._trust(False))
        elif phase == "changed":
            self._go(self._trust(True))
        elif phase == "install":
            self._install()
        elif phase == "manual":
            self._go(self._connect())
        elif phase == "done":
            self.dismiss(self.result)

    def action_alt(self) -> None:
        if self.phase == "install":
            self._show_manual()
        elif self.phase == "manual":
            self.app.copy_to_clipboard(self._command())
            self.notify("Command copied")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ssh-pass":
            self._install()
        elif self.phase in ("form", "error"):
            self._start()

    @on(Button.Pressed, "#btn-ssh-main")
    def press_main(self) -> None:
        self.action_main()

    @on(Button.Pressed, "#btn-ssh-alt")
    def press_alt(self) -> None:
        self.action_alt()

    @on(Button.Pressed, "#btn-ssh-cancel")
    def press_cancel(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)