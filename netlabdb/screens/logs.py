from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Input, ListItem, ListView, Select, Static

from ..config import STYLE_PATH
from ..constants import (
    LOG_ACTION_EVENTS, LOG_LEVELS, LOG_NAV_HINTS, LOG_TYPES, LOG_VIEW_LIMIT, LOG_VIEW_SLACK,
)
from ..helpers import log_event_text, nav_hint_text, palette, put
from ..state import LOGS
from ..store import store
from ..widgets import KeyBar


class LogRow(ListItem):

    def __init__(self, time, kind, text, host, level, service=None):
        super().__init__()
        self.entry = (time, kind, text, host, level, service)

    def render(self) -> Text:
        stamp, kind, _, _, level, _ = self.entry
        pal = palette(self.app)
        marked = self.has_class("-highlight")
        line = Text(no_wrap=True, overflow="ellipsis")
        line.append(" ❱ " if marked else "   ", style=f"bold {pal['accent']}")
        line.append(f"{stamp:<14}", style="dim")
        line.append(f"{kind:<14}", style=pal["accent"])
        color = {"warning": pal["warn"], "error": pal["bad"]}.get(level)
        style = " ".join(part for part in ("bold" if marked else "", color or "") if part)
        line.append(log_event_text(self.entry), style=style or None)
        return line


class LogsClass(Screen):
    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("m", "app.main_menu", "Menu"),
        ("escape", "back", "Back"),
        ("/", "focus_search", "Search"),
        ("f", "open_filter('type')", "Type"),
        ("h", "open_filter('host')", "Host"),
        ("l", "open_filter('level')", "Level"),
        ("p", "toggle_pause", "Pause"),
    ]

    def __init__(self, host: str | None = None):
        super().__init__()
        self.opened_from_host = host is not None
        self.log_paused = False
        self.search_text = ""
        self.filt = {"type": "ALL", "host": host or "ALL", "level": "ALL"}
        self.top_entry = None
        self.head = LOGS[0] if LOGS else None
        self.log_busy = False

    def _filter_options(self, which: str) -> list[str]:
        if which == "type":
            return LOG_TYPES
        if which == "level":
            return LOG_LEVELS
        return ["ALL"] + sorted({h[0] for h in store.all()} | {e[3] for e in LOGS})

    def _filtered_logs(self) -> list[tuple]:
        t, h, lv = self.filt["type"], self.filt["host"], self.filt["level"]
        words = self.search_text.lower().split()
        return [
            e for e in LOGS
            if (t == "ALL" or e[1] == t)
            and (h == "ALL" or e[3] == h)
            and (lv == "ALL" or e[4] == lv.lower())
            and all(w in f"{e[0]} {e[1]} {log_event_text(e)}".lower() for w in words)
        ]

    def compose(self) -> ComposeResult:
        with Vertical(id="logs-panel"):
            with Horizontal(id="search-bar"):
                yield Static("⌕", id="search-icon")
                yield Input(placeholder="Search logs...", id="search")
                yield Static("✕", id="search-clear")

            with Horizontal(id="filters"):
                for key, name in (("type", "TYPE"), ("host", "HOST"), ("level", "LEVEL")):
                    with Horizontal(classes="chip"):
                        yield Static(f"{name}:", classes="flabel")
                        yield Select(
                            [(o, o) for o in self._filter_options(key)],
                            value=self.filt[key],
                            allow_blank=False,
                            id=f"sel-{key}",
                        )

            with Horizontal(id="header"):
                yield Static("", classes="log-cursor")
                yield Static("TIME", classes="log-time")
                yield Static("TYPE", classes="log-type")
                yield Static("EVENT", classes="log-event")

            yield ListView(*[LogRow(*e) for e in self._filtered_logs()[:LOG_VIEW_LIMIT]], id="log-list")
            yield Static("", id="log-empty")

            with Horizontal(id="footer-bar"):
                yield KeyBar(LOG_ACTION_EVENTS)
                with Horizontal(id="footer-stats"):
                    yield Static("", id="stat-total")
                    yield Static("|", id="stat-sep")
                    yield Static("", id="stat-warning", classes="warning")
                    yield Static("", id="stat-error", classes="err")
                    yield Static("", id="stat-paused", classes="paused")

    def on_mount(self) -> None:
        panel = self.query_one("#logs-panel")
        panel.border_title = "LOGS"
        panel.border_subtitle = nav_hint_text(LOG_NAV_HINTS)
        self.query_one("#log-list", ListView).focus()
        entries = self._filtered_logs()
        self.top_entry = entries[0] if entries else None
        self._update_stats(entries)
        self._show_empty(bool(entries))

    def _update_stats(self, entries: list[tuple]) -> None:
        warnings = sum(1 for e in entries if e[4] == "warning")
        errors = sum(1 for e in entries if e[4] == "error")
        if len(entries) > LOG_VIEW_LIMIT:
            total = f"{LOG_VIEW_LIMIT} of {len(entries):,} events"
        else:
            total = f"{len(entries):,} events"
        put(self.query_one("#stat-total", Static), total)
        put(self.query_one("#stat-warning", Static), f"{warnings} warnings")
        put(self.query_one("#stat-error", Static), f"{errors} errors")

    async def _refresh_logs(self, entries: list[tuple] | None = None) -> None:
        if entries is None:
            entries = self._filtered_logs()
        self.head = LOGS[0] if LOGS else None
        self.top_entry = entries[0] if entries else None
        lv = self.query_one("#log-list", ListView)
        await lv.clear()
        await lv.extend([LogRow(*e) for e in entries[:LOG_VIEW_LIMIT]])
        lv.index = 0 if entries else None
        self._update_stats(entries)
        self._show_empty(bool(entries))

    def _show_empty(self, has_rows: bool) -> None:
        self.query_one("#log-list", ListView).display = has_rows
        empty = self.query_one("#log-empty", Static)
        empty.display = not has_rows
        if not has_rows:
            search = self.search_text.strip()
            if search:
                text = f"No logs match “{search}”"
            elif any(value != "ALL" for value in self.filt.values()):
                text = "No logs match the selected filters"
            else:
                text = "No logs yet"
            empty.update(Text(text))

    def live_update(self) -> None:
        if self.log_paused or self.log_busy:
            return
        if (LOGS[0] if LOGS else None) is self.head:
            return
        self.log_busy = True
        self.run_worker(self._live_logs(), group="live-logs")

    async def _live_logs(self) -> None:
        try:
            self.head = LOGS[0] if LOGS else None
            entries = self._filtered_logs()
            top = entries[0] if entries else None
            previous = self.top_entry
            if top is previous:
                return
            lv = self.query_one("#log-list", ListView)
            index = lv.index or 0
            shift = None
            if previous is not None:
                shift = next((i for i, e in enumerate(entries) if e is previous), None)
            if shift is None or not lv.children or len(lv.children) + shift > LOG_VIEW_LIMIT + LOG_VIEW_SLACK:
                await self._refresh_logs(entries)
                if index and shift is not None and lv.children:
                    lv.index = min(index + shift, len(lv.children) - 1)
                return
            current = lv.highlighted_child
            if current is not None:
                current.highlighted = False
            await lv.mount(*[LogRow(*e) for e in entries[:shift]], before=lv.children[0])
            lv.index = None
            lv.index = min(index + shift, len(lv.children) - 1) if index else 0
            self.top_entry = top
            self._update_stats(entries)
            self._show_empty(True)
        finally:
            self.log_busy = False

    async def on_input_changed(self, event: Input.Changed) -> None:
        self.search_text = event.value
        await self._refresh_logs()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#log-list", ListView).focus()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    @on(Click, "#search-clear")
    def clear_search(self) -> None:
        self.query_one("#search", Input).value = ""
        self.query_one("#search", Input).focus()

    def action_open_filter(self, which: str) -> None:
        select = self.query_one(f"#sel-{which}", Select)
        select.focus()
        select.expanded = True

    async def on_select_changed(self, event: Select.Changed) -> None:
        which = (event.select.id or "").removeprefix("sel-")
        if which not in self.filt or str(event.value) == self.filt[which]:
            return
        self.filt[which] = str(event.value)
        await self._refresh_logs()
        self.call_after_refresh(self.query_one("#log-list", ListView).focus)

    def action_back(self) -> None:
        if self.opened_from_host:
            self.app.pop_screen()

    def action_toggle_pause(self) -> None:
        self.log_paused = not self.log_paused
        self.query_one("#stat-paused", Static).update(Text("❚❚ PAUSED") if self.log_paused else "")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, LogRow):
            time, kind, text, host, level, service = event.item.entry
            self.notify(f"{kind} on {host} at {time}")
