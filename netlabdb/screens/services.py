from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Input, Static

from ..config import STYLE_PATH
from ..constants import BOX_SLOT_WIDTH, HOST_ICON, SERVICE_ACTION_EVENTS, SERVICE_ICON, SERVICE_NAV_HINTS
from ..errors import DatabaseError
from ..helpers import nav_hint_text, put
from ..state import SERVICES
from ..store import store
from ..widgets import KeyBar, SvcScroll
from .dialogs import DeleteServiceScreen
from .service_detail import ServiceDetailScreen
from .service_forms import AddServiceScreen, EditServiceScreen


class HostBox(Vertical):
    """One bordered box per host."""


class ServiceRow(Horizontal, can_focus=True):
    BINDINGS = [("enter", "select", "Details")]

    class Selected(Message):
        def __init__(self, host: str, service: str, port: int) -> None:
            super().__init__()
            self.host = host
            self.service = service
            self.port = port

    def __init__(self, host, service, port, status, is_last, is_first):
        super().__init__()
        self.host_name = host
        self.service = service
        self.port = port
        self.status = status
        self.is_last, self.is_first = is_last, is_first

    def compose(self) -> ComposeResult:
        self.icon = Static(SERVICE_ICON[self.status], classes=f"svc-status {self.status}")
        self.icon.shown_content = SERVICE_ICON[self.status]
        yield Static("❱", classes="svc-cursor")
        yield Static("└─" if self.is_last else "├─", classes="svc-branch")
        yield Static(self.service, classes="svc-name")
        yield Static(f":{self.port}", classes="svc-port")
        yield self.icon

    def show(self, status: str) -> None:
        self.status = status
        put(self.icon, SERVICE_ICON[status])
        self.icon.set_classes(f"svc-status {status}")

    def action_select(self) -> None:
        self.post_message(self.Selected(self.host_name, self.service, self.port))

    def on_click(self, event: Click) -> None:
        self.focus()
        self.action_select()


class ServicesClass(Screen):
    CSS_PATH = STYLE_PATH

    AUTO_FOCUS = ""

    BINDINGS = [
        ("up", "move(-1)", "Up"),
        ("down", "move(1)", "Down"),
        ("left", "hmove(-1)", "Prev host"),
        ("right", "hmove(1)", "Next host"),
        ("/", "focus_search", "Search"),
        ("m", "app.main_menu", "Menu"),
        ("a", "add_service", "Add"),
        ("e", "edit_service", "Edit"),
        ("d", "delete_service", "Remove"),
        ("escape", "leave_search", "Leave search"),
    ]

    def _columns(self) -> int:
        return max(1, (self.app.size.width - 5) // BOX_SLOT_WIDTH)

    async def on_resize(self, event) -> None:
        if self._columns() == getattr(self, "shown_columns", None):
            return
        try:
            search = self.query_one("#search", Input)
        except Exception:
            return
        focused = self.focused
        key = (focused.host_name, focused.service, focused.port) if isinstance(focused, ServiceRow) else None
        await self._refresh_boxes(search.value)
        if key is not None:
            for row in self.query(ServiceRow):
                if (row.host_name, row.service, row.port) == key:
                    row.focus()
                    break

    def _filter(self, query: str) -> list[tuple]:
        q = query.strip().lower()
        out = []
        for host, host_status, services in SERVICES:
            if q in host.lower():
                out.append((host, host_status, services))
                continue
            matched = [s for s in services if q in s[0].lower()]
            if matched:
                out.append((host, host_status, matched))
        return out

    def _box_rows(self, data: list[tuple], query: str = "") -> list:
        if not data:
            text = f"No services match “{query.strip()}”" if query.strip() else "No hosts yet"
            return [Static(Text(text), classes="svc-empty")]
        boxes = []
        for host, host_status, services in data:
            rows = [
                ServiceRow(host, name, port, status,
                           is_last=(i == len(services) - 1), is_first=(i == 0))
                for i, (name, port, status) in enumerate(services)
            ] or [Static("No services yet", classes="svc-none")]
            head = Horizontal(
                Static(host, classes="host-name"),
                Static(f"{HOST_ICON[host_status]} {host_status.upper()}",
                       classes=f"host-state {host_status}"),
                classes="host-head",
            )
            box = HostBox(head, *rows)
            box.host_name = host
            boxes.append(box)
        columns = self._columns()
        self.shown_columns = columns
        return [Horizontal(*boxes[i:i + columns], classes="box-row")
                for i in range(0, len(boxes), columns)]

    def compose(self) -> ComposeResult:
        with Vertical(id="services-panel"):
            with Horizontal(id="search-bar"):
                yield Static("⌕", id="search-icon")
                yield Input(placeholder="Search services...", id="search")
                yield Static("✕", id="search-clear")

            with SvcScroll(id="svc-scroll"):
                with Horizontal(id="summary"):
                    yield Static("", id="sum-running", classes="sum-running")
                    yield Static("", id="sum-warning", classes="sum-warning")
                    yield Static("", id="sum-stopped", classes="sum-stopped")
                yield from self._box_rows(self._filter(""))

            with Horizontal(id="footer-bar"):
                yield KeyBar(SERVICE_ACTION_EVENTS)
                with Horizontal(id="footer-stats"):
                    yield Static("", id="stat-total")
                    yield Static("|", id="stat-sep")
                    yield Static("", id="stat-services")

    def on_mount(self) -> None:
        panel = self.query_one("#services-panel")
        panel.border_title = "SERVICES"
        panel.border_subtitle = nav_hint_text(SERVICE_NAV_HINTS)
        self._update_stats(self._filter(""))
        self._focus_first()

    def _update_stats(self, data: list[tuple]) -> None:
        statuses = [s[2] for _, _, services in data for s in services]
        count = statuses.count
        put(self.query_one("#sum-running", Static), f"RUNNING  {count('up')}")
        put(self.query_one("#sum-warning", Static), f"WARNING  {count('warning')}")
        put(self.query_one("#sum-stopped", Static), f"STOPPED  {count('down')}")
        put(self.query_one("#stat-total", Static), f"{len(data)} hosts")
        put(self.query_one("#stat-services", Static), f"{len(statuses)} services")

    async def _refresh_boxes(self, query: str) -> None:
        data = self._filter(query)
        scroll = self.query_one("#svc-scroll")
        await scroll.query(".box-row, .svc-empty").remove()
        await scroll.mount(*self._box_rows(data, query))
        self._update_stats(data)

    async def on_input_changed(self, event: Input.Changed) -> None:
        await self._refresh_boxes(event.value)

    def live_update(self) -> None:
        for box in self.query(HostBox):
            host = store.host(box.host_name)
            if host is None or getattr(box, "shown", None) == host[1]:
                continue
            box.shown = host[1]
            state = box.query_one(".host-state", Static)
            state.update(f"{HOST_ICON[host[1]]} {host[1].upper()}")
            state.set_classes(f"host-state {host[1]}")
        lookup = {(h, n, p): s for h, _, services in SERVICES for n, p, s in services}
        for row in self.query(ServiceRow):
            status = lookup.get((row.host_name, row.service, row.port))
            if status is not None and status != row.status:
                row.show(status)
        self._update_stats(self._filter(self.query_one("#search", Input).value))

    def action_add_service(self) -> None:
        if not store.all():
            self.notify("Add a host first")
            return
        focused = self.focused
        default = focused.host_name if isinstance(focused, ServiceRow) else None
        self.app.push_screen(AddServiceScreen(default), callback=self.service_added)

    def action_edit_service(self) -> None:
        row = self.focused
        if not isinstance(row, ServiceRow):
            self.notify("Select a service to edit")
            return
        original = (row.host_name, row.service, row.port)
        self.app.push_screen(EditServiceScreen(original), callback=self.service_edited)

    async def service_edited(self, result: dict | None) -> None:
        if result is None:
            return
        try:
            store.update_service(
                result["original"],
                result["host"],
                result["name"],
                result["port"],
                result["protocol"],
                result["interval"],
                result["description"],
            )
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        await self._refresh_boxes(self.query_one("#search", Input).value)
        for row in self.query(ServiceRow):
            if (row.host_name, row.service, row.port) == (result["host"], result["name"], result["port"]):
                row.focus()
                break
        self.notify(f"Saved {result['name']} on {result['host']}")

    def action_delete_service(self) -> None:
        row = self.focused
        if not isinstance(row, ServiceRow):
            self.notify("Select a service to remove")
            return
        original = (row.host_name, row.service, row.port)
        self.app.push_screen(DeleteServiceScreen(original), callback=self.service_deleted)

    async def service_deleted(self, original: tuple | None) -> None:
        if original is None:
            return
        rows = list(self.query(ServiceRow))
        index = next(
            (i for i, r in enumerate(rows) if (r.host_name, r.service, r.port) == original),
            0,
        )
        siblings = [r for r in rows if r.host_name == original[0]]
        local = next(
            (i for i, r in enumerate(siblings) if (r.service, r.port) == original[1:]),
            0,
        )
        try:
            store.remove_service(*original)
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        await self._refresh_boxes(self.query_one("#search", Input).value)
        rows = list(self.query(ServiceRow))
        siblings = [r for r in rows if r.host_name == original[0]]
        if siblings:
            siblings[min(local, len(siblings) - 1)].focus()
        elif rows:
            rows[min(index, len(rows) - 1)].focus()
        else:
            self.set_focus(None)
        self.notify(f"Removed {original[1]} from {original[0]}")

    async def service_added(self, result: dict | None) -> None:
        if result is None:
            return
        try:
            store.add_service(
                result["host"],
                result["name"],
                result["port"],
                result["protocol"],
                result["interval"],
                result["description"],
            )
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        search = self.query_one("#search", Input)
        with search.prevent(Input.Changed):
            search.value = ""
        await self._refresh_boxes("")
        for row in self.query(ServiceRow):
            if (row.host_name, row.service, row.port) == (result["host"], result["name"], result["port"]):
                row.focus()
                break
        self.notify(f"Added {result['name']} to {result['host']}")

    def _focus_first(self) -> None:
        rows = list(self.query(ServiceRow))
        if rows:
            rows[0].focus()
        else:
            self.set_focus(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._focus_first()

    def action_leave_search(self) -> None:
        if self.focused is self.query_one("#search", Input):
            self._focus_first()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    @on(Click, "#search-clear")
    def clear_search(self) -> None:
        self.query_one("#search", Input).value = ""
        self.query_one("#search", Input).focus()

    def action_move(self, step: int) -> None:
        rows = list(self.query(ServiceRow))
        if not rows:
            return
        current = self.focused
        i = rows.index(current) + step if current in rows else 0
        target = rows[max(0, min(len(rows) - 1, i))]
        target.focus()
        self._reveal(target)

    def _reveal(self, row: ServiceRow) -> None:
        if not row.is_first:
            return
        row.parent.scroll_visible(animate=False)
        box_rows = list(self.query(".box-row"))
        if box_rows and row.parent.parent is box_rows[0]:
            self.query_one("#svc-scroll").scroll_home(animate=False)

    def action_hmove(self, step: int) -> None:
        current = self.focused
        if not isinstance(current, ServiceRow):
            return
        boxes = [b for b in self.query(HostBox) if b.query(ServiceRow)]
        box = current.parent
        if box not in boxes:
            return
        idx = list(box.query(ServiceRow)).index(current)
        new_box = boxes[max(0, min(len(boxes) - 1, boxes.index(box) + step))]
        new_rows = list(new_box.query(ServiceRow))
        target = new_rows[min(idx, len(new_rows) - 1)]
        target.focus()
        self._reveal(target)

    def on_service_row_selected(self, event: ServiceRow.Selected) -> None:
        original = (event.host, event.service, event.port)
        self.app.push_screen(ServiceDetailScreen(original), callback=self.service_detail_closed)

    async def service_detail_closed(self, original: tuple | None) -> None:
        await self._refresh_boxes(self.query_one("#search", Input).value)
        rows = list(self.query(ServiceRow))
        target = next((r for r in rows if (r.host_name, r.service, r.port) == original), None)
        if target is None and rows:
            target = rows[0]
        if target is not None:
            target.focus()
        else:
            self.set_focus(None)

    def action_todo(self, what: str) -> None:
        self.notify(f"{what} isn't implemented yet")
