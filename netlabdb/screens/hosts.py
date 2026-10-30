from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Input, ListItem, ListView, Static

from ..config import STYLE_PATH
from ..constants import HOST_ACTION_EVENTS, NAV_HINTS
from ..errors import DatabaseError
from ..helpers import put
from ..store import store
from ..widgets import KeyBar
from .dialogs import DeleteHostScreen
from .host_detail import HostDetailScreen
from .host_forms import AddHostScreen, EditHostScreen


class HostRow(ListItem):

    def __init__(self, host_name, status, up, total, updated, latency=None):
        super().__init__()
        self.host_name = host_name
        self.host_status = status
        self.up, self.total, self.updated, self.latency = up, total, updated, latency
        self.snapshot = (status, up, total, updated, latency)

    def _latency_class(self) -> str:
        if self.latency is None:
            return "lat-none"
        if self.latency < 50:
            return "lat-good"
        if self.latency < 150:
            return "lat-ok"
        return "lat-bad"

    def _cell(self, text: str, classes: str) -> Static:
        cell = Static(text, classes=classes)
        cell.shown_content = text
        return cell

    def compose(self) -> ComposeResult:
        text = "—" if self.latency is None else f"{self.latency} ms"
        self.status_class = f"col-status {self.host_status}"
        self.latency_class = f"col-latency {self._latency_class()}"
        self.w_status = self._cell(f"●  {self.host_status.upper()}", self.status_class)
        self.w_services = self._cell(f"{self.up} / {self.total}", "col-services")
        self.w_latency = self._cell(text, self.latency_class)
        self.w_updated = self._cell(self.updated, "col-updated")
        yield Static("❱", classes="col-cursor")
        yield Static(self.host_name, classes="col-name")
        yield self.w_status
        yield self.w_services
        yield self.w_latency
        yield self.w_updated

    def show(self, status: str, up: int, total: int, updated: str, latency: int | None) -> None:
        snapshot = (status, up, total, updated, latency)
        if snapshot == self.snapshot:
            return
        self.snapshot = snapshot
        self.host_status = status
        self.up, self.total, self.updated, self.latency = up, total, updated, latency
        put(self.w_status, f"●  {status.upper()}")
        status_class = f"col-status {status}"
        if status_class != self.status_class:
            self.status_class = status_class
            self.w_status.set_classes(status_class)
        put(self.w_services, f"{up} / {total}")
        put(self.w_latency, "—" if latency is None else f"{latency} ms")
        latency_class = f"col-latency {self._latency_class()}"
        if latency_class != self.latency_class:
            self.latency_class = latency_class
            self.w_latency.set_classes(latency_class)
        put(self.w_updated, updated)


class HostClass(Screen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("m", "app.main_menu", "Main Menu"),
        ("/", "focus_search", "Search"),
        ("a", "add_host", "Add"),
        ("e", "edit_host", "Edit"),
        ("d", "delete_host", "Delete"),
    ]

    def compose(self):
        with Vertical(id="hosts-panel"):
            with Horizontal(id="search-bar"):
                yield Static("⌕", id="search-icon")
                yield Input(placeholder="Search hosts...", id="search")
                yield Static("✕", id="search-clear")
            with Horizontal(id="header"):
                yield Static("", classes="col-cursor")
                yield Static("HOST NAME", classes="col-name")
                yield Static("STATUS", classes="col-status")
                yield Static("SERVICES", classes="col-services")
                yield Static("LATENCY", classes="col-latency")
                yield Static("LAST SEEN", classes="col-updated")
            yield ListView(*self._rows(""), id="host-list")
            yield Static("", id="host-empty")
            with Horizontal(id="footer-bar"):
                yield KeyBar(HOST_ACTION_EVENTS)
                with Horizontal(id="footer-stats"):
                    yield Static("", id="stat-total")
                    yield Static("|", id="stat-sep")
                    yield Static("", id="stat-online", classes="online")
                    yield Static("", id="stat-offline", classes="offline")
                    yield Static("", id="stat-warning", classes="warning")

    def on_mount(self) -> None:
        panel = self.query_one("#hosts-panel")
        panel.border_title = "HOSTS"
        panel.border_subtitle = self._nav_hints()
        self.query_one("#host-list", ListView).focus()
        self._update_stats(self._matching(""))
        self._show_empty("", bool(self._matching("")))

    def _nav_hints(self) -> Text:
        t = Text()
        t.append(" ")
        for i, (key, label) in enumerate(NAV_HINTS):
            if i:
                t.append("   ")
            t.append(key,)
            t.append(f" {label}")
        t.append(" ")
        return t

    def _matching(self, query: str) -> list[tuple]:
        q = query.strip().lower()
        return [h for h in store.all() if q in h[0].lower()]

    def _update_stats(self, hosts: list[tuple]) -> None:
        count = lambda s: sum(1 for h in hosts if h[1] == s)
        put(self.query_one("#stat-total", Static), f"{len(hosts)} hosts")
        put(self.query_one("#stat-online", Static), f"{count('online')} online")
        put(self.query_one("#stat-offline", Static), f"{count('offline')} offline")
        put(self.query_one("#stat-warning", Static), f"{count('warning')} warning")

    def live_update(self) -> None:
        lookup = {h[0]: h for h in store.all()}
        for row in self.query(HostRow):
            host = lookup.get(row.host_name)
            if host is not None:
                row.show(*host[1:])
        self._update_stats(self._matching(self.query_one("#search", Input).value))

    def _rows(self, query: str) -> list[HostRow]:
        q = query.strip().lower()
        return [HostRow(*h) for h in store.all() if q in h[0].lower()]

    async def _refresh_hosts(self, query: str) -> None:
        lv = self.query_one("#host-list", ListView)
        hosts = self._matching(query)
        rows = self._rows(query)
        await lv.clear()
        await lv.extend(rows)
        lv.index = 0 if rows else None
        self._update_stats(hosts)
        self._show_empty(query, bool(rows))

    def _show_empty(self, query: str, has_rows: bool) -> None:
        self.query_one("#host-list", ListView).display = has_rows
        empty = self.query_one("#host-empty", Static)
        empty.display = not has_rows
        if not has_rows:
            text = f"No hosts match “{query.strip()}”" if query.strip() else "No hosts yet"
            empty.update(Text(text))

    async def on_input_changed(self, event: Input.Changed) -> None:
        await self._refresh_hosts(event.value)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, HostRow):
            self.app.push_screen(HostDetailScreen(event.item.host_name), callback=self.detail_closed)

    async def detail_closed(self, name: str | None) -> None:
        query = self.query_one("#search", Input).value
        await self._refresh_hosts(query)
        lv = self.query_one("#host-list", ListView)
        names = [h[0] for h in self._matching(query)]
        if name in names:
            lv.index = names.index(name)
        lv.focus()

    def action_add_host(self) -> None:
        self.app.push_screen(AddHostScreen(), callback=self.host_added)

    def action_delete_host(self) -> None:
        row = self.query_one("#host-list", ListView).highlighted_child
        if not isinstance(row, HostRow):
            return
        self.app.push_screen(DeleteHostScreen(row.host_name), callback=self.host_deleted)

    async def host_deleted(self, name: str | None) -> None:
        if name is None:
            return
        lv = self.query_one("#host-list", ListView)
        previous = lv.index or 0
        try:
            store.remove(name)
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        query = self.query_one("#search", Input).value
        await self._refresh_hosts(query)
        remaining = len(self._matching(query))
        if remaining:
            lv.index = min(previous, remaining - 1)
        lv.focus()
        self.notify(f"Removed {name}")

    def action_edit_host(self) -> None:
        row = self.query_one("#host-list", ListView).highlighted_child
        if not isinstance(row, HostRow):
            return
        self.app.push_screen(EditHostScreen(row.host_name), callback=self.host_edited)

    async def host_edited(self, result: dict | None) -> None:
        if result is None:
            return
        try:
            store.update(
                result["original"],
                result["name"],
                result["address"],
                result["description"],
                latency=result["latency"],
                reachable=result["reachable"],
                ssh_user=result["ssh_user"],
                ssh_port=result["ssh_port"],
            )
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        query = self.query_one("#search", Input).value
        await self._refresh_hosts(query)
        lv = self.query_one("#host-list", ListView)
        names = [h[0] for h in self._matching(query)]
        if result["name"] in names:
            lv.index = names.index(result["name"])
            row = lv.highlighted_child
            if row is not None:
                row.add_class("-new")
                self.set_timer(2, lambda: row.remove_class("-new"))
        lv.focus()
        self.notify(f"Saved {result['name']}")

    async def host_added(self, result: dict | None) -> None:
        if result is None:
            return
        try:
            store.add(
                result["name"],
                result["address"],
                result["description"],
                latency=result["latency"],
                reachable=result["reachable"],
                ssh_user=result["ssh_user"],
                ssh_port=result["ssh_port"],
            )
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        search = self.query_one("#search", Input)
        with search.prevent(Input.Changed):
            search.value = ""
        await self._refresh_hosts("")
        lv = self.query_one("#host-list", ListView)
        names = [h[0] for h in store.all()]
        lv.index = names.index(result["name"])
        row = lv.highlighted_child
        lv.focus()
        if row is not None:
            row.add_class("-new")
            self.set_timer(2, lambda: row.remove_class("-new"))
        self.notify(f"Added {result['name']}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#host-list", ListView).focus()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    @on(Click, "#search-clear")
    def clear_search(self) -> None:
        self.query_one("#search", Input).value = ""
        self.query_one("#search", Input).focus()
