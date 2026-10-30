import platform
import time
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import ListItem, ListView, Static

from ..config import APP_VERSION, STYLE_PATH
from ..helpers import is_front, log_event_text, newtext, palette
from ..state import LOGS, SERVICES
from ..store import store
from ..theme import PALETTE
from .hosts import HostClass


LOGO_GLYPHS = {
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "L": ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"],
    "A": [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "B": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██████╔╝", "╚═════╝ "],
}

LOGO_LINES = ["".join(LOGO_GLYPHS[c][row] for c in "NETLAB") for row in range(6)]

HOME_ENTRIES = [
    ("◉", "Hosts", "hosts", "h"),
    ("◈", "Services", "services", "s"),
    ("≡", "Logs", "logs", "l"),
    ("+", "New host", "new_host", "a"),
    ("◇", "Settings", "settings", "t"),
    ("✕", "Quit", "quit", "q"),
]

HOME_TIPS = [
    "Press [m] on any screen to open the main menu",
    "Press [/] to search hosts, services and logs",
    "Select a service and press [v] to reveal its password",
    "Press [i] on a host or service to change its check interval",
    "Press [r] on a host to run a check right now",
    "Turn the CRT effect on or off in Settings",
]

HOME_MIN_HEIGHT_ACTIVITY = 32
HOME_MIN_HEIGHT_TIP = 27


class HomeItem(ListItem):

    def __init__(self, icon: str, label: str, route: str, key: str):
        super().__init__(id=f"home-{route}")
        self.icon, self.label, self.route, self.key = icon, label, route, key

    def compose(self) -> ComposeResult:
        yield Static("❱", classes="home-cursor")
        yield Static(self.icon, classes="home-icon")
        yield Static(self.label, classes="home-label")
        yield Static(self.key, classes="home-key")


class StartupScreen(Screen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("m", "app.main_menu", "Main Menu"),
        *[(key, f"open('{route}')", label) for _, label, route, key in HOME_ENTRIES],
    ]

    def __init__(self):
        super().__init__()
        self.cursor_on = True
        self.opened = time.monotonic()

    def compose(self) -> ComposeResult:
        with Vertical(id="home"):
            yield Static("", id="home-logo")
            yield Static("", id="home-tag")
            yield ListView(*[HomeItem(*entry) for entry in HOME_ENTRIES], id="home-menu")
            yield Static("", id="home-summary")
            yield Static("", id="home-activity")
            yield Static("", id="home-tip")
            yield Static("", id="home-footer")

    def on_mount(self) -> None:
        self.query_one("#home-menu", ListView).focus()
        self._draw_logo()
        self._tick()
        self.set_interval(1, self._tick)
        self.set_interval(0.5, self._blink)

    def on_resize(self, event) -> None:
        height = self.size.height
        self.query_one("#home-activity").display = height >= HOME_MIN_HEIGHT_ACTIVITY
        self.query_one("#home-tip").display = height >= HOME_MIN_HEIGHT_TIP

    def _draw_logo(self) -> None:
        fill, shadow = PALETTE["fill"], PALETTE["shadow"]
        logo = Text(no_wrap=True, overflow="crop")
        for index, line in enumerate(LOGO_LINES):
            for char in line:
                if char == "█":
                    logo.append(char, style=f"bold {fill}")
                elif char == " ":
                    logo.append(char)
                else:
                    logo.append(char, style=shadow)
            if index < len(LOGO_LINES) - 1:
                logo.append("\n")
        self.query_one("#home-logo", Static).update(logo)

    def _blink(self) -> None:
        if not is_front(self):
            return
        self.cursor_on = not self.cursor_on
        self._draw_tag()

    def _draw_tag(self) -> None:
        pal = palette(self.app)
        tag = Text(no_wrap=True)
        tag.append("server monitoring terminal", style="dim")
        tag.append("  v" + APP_VERSION, style=pal["accent"])
        tag.append(" █" if self.cursor_on else "  ", style=pal["accent"])
        self.query_one("#home-tag", Static).update(tag)

    def _tick(self) -> None:
        if not is_front(self):
            return
        pal = palette(self.app)
        self._draw_tag()
        hosts = store.all()
        states = [h[1] for h in hosts]
        services = sum(len(s[2]) for s in SERVICES)
        summary = Text(no_wrap=True, justify="center")
        summary.append(f"● {states.count('online')} online", style=pal["ok"])
        summary.append("   ")
        summary.append(f"◐ {states.count('warning')} warning", style=pal["warn"])
        summary.append("   ")
        summary.append(f"○ {states.count('offline')} offline", style="dim")
        summary.append("   ·   ", style="dim")
        summary.append(f"{len(hosts)} hosts  {services} services", style="dim")
        self.query_one("#home-summary", Static).update(summary)

        activity = [Text("RECENT ACTIVITY", style=f"bold {pal['accent']}", no_wrap=True)]
        colors = {"error": pal["bad"], "warning": pal["warn"]}
        for entry in LOGS[:3]:
            line = newtext()
            line.append(f"{entry[0]}  ", style="dim")
            line.append(f"{entry[1]:<8}", style=pal["accent"])
            line.append(log_event_text(entry), style=colors.get(entry[4]))
            activity.append(line)
        self.query_one("#home-activity", Static).update(newtext("\n").join(activity))

        tip = HOME_TIPS[int((time.monotonic() - self.opened) // 8) % len(HOME_TIPS)]
        self.query_one("#home-tip", Static).update(Text("✦ " + tip, no_wrap=True, overflow="ellipsis"))

        now = datetime.now()
        footer = Text(no_wrap=True, overflow="ellipsis", justify="center")
        footer.append(platform.system())
        footer.append("   ·   ")
        footer.append(now.strftime("%a %d %b  %H:%M:%S"), style=pal["accent"])
        self.query_one("#home-footer", Static).update(footer)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, HomeItem):
            self.action_open(event.item.route)

    def action_open(self, route: str) -> None:
        if route == "quit":
            self.app.exit()
            return
        if route == "new_host":
            screen = HostClass()
            self.app.push_screen(screen)
            screen.call_after_refresh(screen.action_add_host)
            return
        screen_class = self.app.routes.get(route)
        if screen_class is not None:
            self.app.push_screen(screen_class())
