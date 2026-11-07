import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import ListItem, ListView, Static

from ..config import APP_VERSION, STYLE_PATH
from ..constants import HOST_ICON, SERVICE_ICON, SERVICE_LABEL
from ..dashboard import (
    LISTS, current_layout, expand, footer_for, logo_text, resolve_color, resolve_logo, section_style,
    tip_for,
)
from ..helpers import is_front, log_event_text, newtext, palette, rate
from ..state import LOGS, SERVICES
from ..store import store
from .hosts import HostClass


LAYOUT_SPARE = 2

SECTION_IDS = {
    "logo": "home-logo", "tagline": "home-tag", "summary": "home-summary",
    "activity": "home-activity", "tip": "home-tip", "footer": "home-footer",
}


class HomeItem(ListItem):

    def __init__(self, icon: str, label: str, route: str, key: str, show_key: bool = True, center: int = 0):
        super().__init__()
        self.icon, self.label, self.route, self.key = icon, label, route, key
        self.show_key, self.center = show_key, center
        if center:
            self.styles.padding = (0, 5, 0, 2)

    def compose(self) -> ComposeResult:
        yield Static("❱", classes="home-cursor")
        if self.center:
            accent = palette(self.app)["accent"]
            yield Static(Text.assemble((self.icon, accent), "  ", self.label.ljust(self.center)), classes="home-label home-label-center")
        else:
            yield Static(self.icon, classes="home-icon")
            yield Static(self.label, classes="home-label")
        if self.show_key:
            yield Static(self.key, classes="home-key")


class StartupScreen(Screen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [("m", "app.main_menu", "Main Menu")]

    def __init__(self):
        super().__init__()
        self.cursor_on = True
        self.opened = time.monotonic()
        self.plan = current_layout()
        self.entries = []
        self.leaves = []
        self.menu_keys = {}
        self.counter = 0
        self.warned = None
        self.rebuilding = False

    def compose(self) -> ComposeResult:
        with Vertical(id="home"):
            yield from self._build()

    def _build(self) -> list:
        self.entries, self.leaves, self.menu_keys, self.counter = [], [], {}, 0
        widgets = []
        for section in self.plan.sections:
            entry = self._entry(section, None)
            self.entries.append(entry)
            widgets.append(entry["outer"])
        return widgets

    def _entry(self, section: dict, columns) -> dict:
        kind = section["type"]
        entry = {
            "section": section, "index": self.counter, "lines": [], "empty": False, "hidden": False,
            "rows": section.get("lines", 0) if kind in LISTS else 0, "count": 99, "drawn_rows": None,
            "drawn_width": None, "columns": None, "holders": [], "in_column": columns is not None,
            "fallback": 40,
        }
        self.counter += 1
        if kind == "columns":
            holders, groups = [], []
            for position, column in enumerate(section["columns"]):
                children = [self._entry(child, len(section["columns"])) for child in column["sections"]]
                holder = Vertical(*[child["outer"] for child in children])
                holder.styles.width = column["width"]
                holder.styles.height = "auto"
                holder.styles.margin = (0, section["gap"] if position < len(section["columns"]) - 1 else 0, 0, 0)
                holders.append(holder)
                groups.append(children)
            entry["columns"], entry["holders"] = groups, holders
            row = Horizontal(*holders)
            row.styles.height = "auto"
            row.styles.width = "100%"
            row.styles.margin = (section["margin"], 0, 0, 0)
            entry["widget"] = entry["outer"] = row
            return entry
        entry["fallback"] = max(10, min(self.app.size.width, self.plan.width) // (columns or 1) - 3)
        if kind == "menu":
            pad = max(len(i["label"]) for i in section["items"]) if section["label_align"] == "center" else 0
            if pad:
                icon = max(len(i["icon"]) for i in section["items"])
                keys = max(len(i["key"]) for i in section["items"]) + 1 if section["keys"] else 0
                section = dict(section, width=10 + icon + 2 + pad + keys)
                entry["section"] = section
            items = [
                HomeItem(i["icon"], i["label"], i["action"], i["key"], section["keys"], pad)
                for i in section["items"]
            ]
            self.menu_keys.update({i["key"]: i["action"] for i in section["items"] if i["key"] and i["key"] != "m"})
            widget = ListView(*items, id="home-menu")
        elif kind in SECTION_IDS:
            widget = Static("", id=SECTION_IDS[kind])
        else:
            widget = Static("", classes=f"home-{kind}")
        entry["widget"] = widget
        self._style(entry)
        self.leaves.append(entry)
        return entry

    def _style(self, entry: dict) -> None:
        section, widget = entry["section"], entry["widget"]
        kind = section["type"]
        if kind == "spacer":
            widget.styles.height = section["height"]
        if kind != "menu":
            widget.styles.text_align = section["align"]
        if section["width"]:
            widget.styles.width = section["width"]
        if section["border"]:
            color = resolve_color(section["border_color"]) or palette(self.app)["accent"]
            widget.styles.border = (section["border"], color)
            widget.styles.border_title_color = color
        if section["padding"] != "":
            widget.styles.padding = (0, section["padding"])
        elif section["border"]:
            widget.styles.padding = (0, 1)
        outer = widget
        if section["width"] and section["align"] in ("center", "right"):
            outer = Vertical(widget)
            outer.styles.width = "100%"
            outer.styles.height = "auto"
            outer.styles.align_horizontal = section["align"]
        outer.styles.margin = (0 if kind == "spacer" else section["margin"], 0, 0, 0)
        entry["outer"] = outer

    def on_mount(self) -> None:
        menu = self.query("#home-menu")
        if menu:
            menu.first().focus()
        self._draw_logos()
        self._tick()
        self.call_after_refresh(self._after_layout)
        self.set_interval(1, self._tick)
        self.set_interval(1, self._watch)
        self.set_interval(0.5, self._blink)

    def _after_layout(self) -> None:
        self._draw_logos()
        self._tick()

    def on_resize(self, event) -> None:
        if self.rebuilding or not self.entries:
            return
        self._draw_logos()
        self._layout()

    def on_key(self, event) -> None:
        action = self.menu_keys.get(event.key)
        if action is not None:
            event.stop()
            event.prevent_default()
            self.action_open(action)

    async def _watch(self) -> None:
        if self.rebuilding or not is_front(self):
            return
        plan = current_layout()
        if plan.error != self.warned:
            self.warned = plan.error
            if plan.error:
                self.notify(plan.error, severity="warning", timeout=10)
        if plan.signature != self.plan.signature:
            await self._rebuild(plan)

    async def _rebuild(self, plan) -> None:
        self.rebuilding = True
        try:
            self.plan = plan
            home = self.query_one("#home")
            await home.remove_children()
            await home.mount(*self._build())
            menu = self.query("#home-menu")
            if menu:
                menu.first().focus()
        finally:
            self.rebuilding = False
        self._draw_logos()
        self._tick()
        self.call_after_refresh(self._after_layout)

    def _draw_logos(self) -> None:
        widest = 0
        for entry in self.leaves:
            section = entry["section"]
            if section["type"] not in ("logo", "art"):
                continue
            if entry["in_column"]:
                available = entry["widget"].size.width or entry["fallback"]
            else:
                available = self.app.size.width - 2
            available = max(10, available - (4 if section["border"] else 0))
            if available != entry["drawn_width"]:
                entry["drawn_width"] = available
                lines, font, fill, shadow = resolve_logo(section, available)
                entry["lines"] = lines
                entry["widget"].update(logo_text(lines, font, fill, shadow) if lines else "")
            if not entry["in_column"] and entry["lines"]:
                widest = max(widest, len(entry["lines"][0]))
        self.query_one("#home").styles.width = max(self.plan.width, widest + 4)
        self._layout()

    def _header(self, entry: dict) -> int:
        section = entry["section"]
        return 1 if section.get("title") and not section["border"] else 0

    def _height(self, entry: dict) -> int:
        section = entry["section"]
        kind = section["type"]
        if kind == "columns":
            return max((self._column_height(column) for column in entry["columns"]), default=0)
        if kind in ("logo", "art"):
            body = len(entry["lines"])
        elif kind == "menu":
            body = len(section["items"])
        elif kind in LISTS:
            body = max(1, min(entry["rows"], entry["count"]))
        elif kind == "stats":
            body = 4
        elif kind == "spacer":
            return section["height"]
        elif kind == "text":
            body = section["text"].count("\n") + 1
        else:
            body = 1
        header = self._header(entry) if kind in LISTS + ("stats",) else 0
        return body + header + (2 if section["border"] else 0)

    def _column_height(self, column: list) -> int:
        visible = [c for c in column if not c["hidden"]]
        return sum(self._height(c) + (c["section"]["margin"] if n else 0) for n, c in enumerate(visible))

    def _shown(self, entry: dict) -> bool:
        if entry["columns"] is not None:
            return not entry["hidden"] and any(not c["hidden"] for column in entry["columns"] for c in column)
        return not entry["hidden"]

    def _need(self) -> int:
        top = [e for e in self.entries if self._shown(e)]
        return sum(self._height(e) + (e["section"]["margin"] if n else 0) for n, e in enumerate(top))

    def _shrink(self, need: int) -> bool:
        pool = [e for e in self.leaves if not e["hidden"] and e["section"]["type"] in LISTS and e["rows"] > 1]
        pool.sort(key=lambda e: e["index"], reverse=True)
        for entry in pool:
            entry["rows"] -= 1
            if self._need() < need:
                return True
            entry["rows"] += 1
        if pool:
            pool[0]["rows"] -= 1
            return True
        return False

    def _drop(self, need: int) -> bool:
        pool = [e for e in self.leaves if not e["hidden"] and e["section"]["priority"] > 0]
        pool.sort(key=lambda e: (e["section"]["priority"], e["index"]), reverse=True)
        if not pool:
            return False
        for entry in pool:
            entry["hidden"] = True
            if self._need() < need:
                return True
            entry["hidden"] = False
        pool[0]["hidden"] = True
        return True

    def _layout(self) -> None:
        height = self.app.size.height
        for entry in self.leaves:
            section = entry["section"]
            kind = section["type"]
            entry["hidden"] = bool(
                entry["empty"] or (kind in ("logo", "art") and not entry["lines"])
                or (section["min_height"] and height < section["min_height"])
            )
            if kind in LISTS:
                entry["rows"] = section["lines"]
        for entry in self.entries:
            if entry["columns"] is not None:
                section = entry["section"]
                entry["hidden"] = bool(section["min_height"] and height < section["min_height"])
        available = height - LAYOUT_SPARE
        while True:
            need = self._need()
            if need <= available:
                break
            if self._shrink(need):
                continue
            if not self._drop(need):
                break
        pal = palette(self.app)
        for entry in self.leaves:
            entry["outer"].display = not entry["hidden"]
            if entry["section"]["border"] and entry["section"]["type"] not in ("menu", "spacer"):
                entry["widget"].styles.height = self._height(entry)
        for entry in self.entries:
            if entry["columns"] is not None:
                section = entry["section"]
                entry["outer"].display = self._shown(entry)
                heights = [self._column_height(column) for column in entry["columns"]]
                tallest = max(heights, default=0)
                last = len(heights) - 1
                for position, (holder, column) in enumerate(zip(entry["holders"], entry["columns"])):
                    holder.display = any(not c["hidden"] for c in column)
                    spare = tallest - heights[position]
                    offset = {"top": 0, "middle": spare // 2, "bottom": spare}[section["valign"]]
                    holder.styles.margin = (offset, section["gap"] if position < last else 0, 0, 0)
        for entry in self.leaves:
            if entry["section"]["type"] in LISTS and entry["drawn_rows"] != entry["rows"]:
                self._draw(entry, pal)

    def _blink(self) -> None:
        if self.rebuilding or not is_front(self):
            return
        self.cursor_on = not self.cursor_on
        pal = palette(self.app)
        for entry in self.leaves:
            if entry["section"]["type"] == "tagline":
                self._draw_tag(entry, pal)

    def _inner(self, entry: dict) -> int:
        return max(20, entry["widget"].content_size.width or 40)

    def _head(self, entry: dict, pal: dict) -> list:
        title = entry["section"].get("title")
        if not title or entry["section"]["border"]:
            return []
        return [Text(title, style=f"bold {pal['accent']}", no_wrap=True)]

    def _draw_tag(self, entry: dict, pal: dict) -> None:
        section = entry["section"]
        text = expand(section["text"])
        tag = Text(no_wrap=True)
        tag.append(text, style="dim")
        if section["version"]:
            tag.append(("  " if text else "") + "v" + APP_VERSION, style=pal["accent"])
        if section["cursor"]:
            tag.append(" █" if self.cursor_on else "  ", style=pal["accent"])
        entry["empty"] = not (text or section["version"] or section["cursor"])
        entry["widget"].update(tag)

    def _draw_summary(self, entry: dict, pal: dict) -> None:
        section = entry["section"]
        if section["text"]:
            entry["widget"].update(Text(expand(section["text"]), style="dim", no_wrap=True, overflow="ellipsis"))
            return
        hosts = store.all()
        states = [h[1] for h in hosts]
        services = sum(len(s[2]) for s in SERVICES)
        summary = Text(no_wrap=True)
        summary.append(f"● {states.count('online')} online", style=pal["ok"])
        summary.append("   ")
        summary.append(f"◐ {states.count('warning')} warning", style=pal["warn"])
        summary.append("   ")
        summary.append(f"○ {states.count('offline')} offline", style="dim")
        summary.append("   ·   ", style="dim")
        summary.append(f"{len(hosts)} hosts  {services} services", style="dim")
        entry["widget"].update(summary)

    def _draw_activity(self, entry: dict, pal: dict) -> None:
        entry["drawn_rows"] = entry["rows"]
        entry["count"] = len(LOGS)
        lines = self._head(entry, pal)
        colors = {"error": pal["bad"], "warning": pal["warn"]}
        for log in LOGS[:entry["rows"]]:
            line = newtext()
            line.append(f"{log[0]}  ", style="dim")
            line.append(f"{log[1]:<8}", style=pal["accent"])
            line.append(log_event_text(log), style=colors.get(log[4]))
            lines.append(line)
        entry["widget"].update(newtext("\n").join(lines))

    def _draw_hosts(self, entry: dict, pal: dict) -> None:
        section = entry["section"]
        entry["drawn_rows"] = entry["rows"]
        hosts = list(store.all())
        if section["sort"] == "name":
            hosts.sort(key=lambda h: h[0].lower())
        elif section["sort"] == "latency":
            hosts.sort(key=lambda h: -(h[5] if h[5] is not None else -1))
        else:
            order = {"offline": 0, "warning": 1, "online": 2}
            hosts.sort(key=lambda h: (order.get(h[1], 3), h[0].lower()))
        entry["count"] = len(hosts)
        width = self._inner(entry)
        lines = self._head(entry, pal)
        if not hosts:
            lines.append(Text("No hosts yet", style="dim", no_wrap=True))
        for name, status, _, _, _, latency in hosts[:entry["rows"]]:
            color = {"online": pal["ok"], "warning": pal["warn"]}.get(status, "dim")
            right = "—" if latency is None else f"{latency} ms"
            level = None if latency is None else {"ok": pal["ok"], "warning": pal["warn"], "critical": pal["bad"]}[rate("latency", latency)]
            line = newtext()
            line.append(f"{HOST_ICON.get(status, '○')} ", style=color)
            line.append(name)
            line.append(" " * max(1, width - len(name) - 2 - len(right)))
            line.append(right, style=level or "dim")
            lines.append(line)
        entry["widget"].update(newtext("\n").join(lines))

    def _draw_alerts(self, entry: dict, pal: dict) -> None:
        entry["drawn_rows"] = entry["rows"]
        items = []
        for host, status, services in SERVICES:
            if status == "offline":
                items.append((0, "○", host, "Host offline", pal["bad"]))
                continue
            for name, _, state in services:
                if state == "down":
                    items.append((0, SERVICE_ICON[state], f"{name} [{host}]", SERVICE_LABEL[state], pal["bad"]))
                elif state == "warning":
                    items.append((1, SERVICE_ICON[state], f"{name} [{host}]", SERVICE_LABEL[state], pal["warn"]))
        items.sort(key=lambda item: item[0])
        entry["count"] = len(items)
        width = self._inner(entry)
        lines = self._head(entry, pal)
        if not items:
            lines.append(Text("✓ All systems healthy", style=pal["ok"], no_wrap=True))
        for _, icon, text, label, color in items[:entry["rows"]]:
            line = newtext()
            line.append(f"{icon} ", style=color)
            line.append(text)
            line.append(" " * max(1, width - len(text) - 2 - len(label)))
            line.append(label, style=color)
            lines.append(line)
        entry["widget"].update(newtext("\n").join(lines))

    def _meter(self, label: str, value: int, total: int, width: int, pal: dict) -> Text:
        pct = value / total * 100 if total else 0.0
        color = "dim" if not total else pal["ok"] if pct >= 90 else pal["warn"] if pct >= 60 else pal["bad"]
        filled = round(width * pct / 100)
        line = newtext()
        line.append(f"{label:<10}", style="dim")
        line.append("▰" * filled, style=color)
        line.append("▱" * (width - filled), style="dim")
        line.append(f" {value}/{total}")
        return line

    def _draw_stats(self, entry: dict, pal: dict) -> None:
        hosts = store.all()
        states = [state for _, _, services in SERVICES for _, _, state in services]
        online = sum(1 for h in hosts if h[1] != "offline")
        bar = max(6, self._inner(entry) - 10 - 9)
        latencies = [h[5] for h in hosts if h[5] is not None and h[1] != "offline"]
        problems = states.count("down") + states.count("warning")
        latency = newtext()
        latency.append(f"{'LATENCY':<10}", style="dim")
        latency.append(f"{sum(latencies) / len(latencies):.0f} ms avg" if latencies else "—")
        alerts = newtext()
        alerts.append(f"{'ALERTS':<10}", style="dim")
        alerts.append(f"{problems} need attention" if problems else "none", style=pal["warn"] if problems else pal["ok"])
        lines = self._head(entry, pal) + [
            self._meter("HOSTS", online, len(hosts), bar, pal),
            self._meter("SERVICES", states.count("up"), len(states), bar, pal),
            latency, alerts,
        ]
        entry["widget"].update(newtext("\n").join(lines))

    def _draw_footer(self, entry: dict, pal: dict) -> None:
        section = entry["section"]
        left, right = footer_for(section)
        footer = Text(no_wrap=True, overflow="ellipsis")
        if left:
            footer.append(left)
        if left and right:
            footer.append(section["separator"])
        if right:
            footer.append(right, style=pal["accent"])
        entry["empty"] = not (left or right)
        entry["widget"].update(footer)

    def _draw(self, entry: dict, pal: dict) -> None:
        section = entry["section"]
        kind = section["type"]
        if kind == "tagline":
            self._draw_tag(entry, pal)
        elif kind == "summary":
            self._draw_summary(entry, pal)
        elif kind == "activity":
            self._draw_activity(entry, pal)
        elif kind == "hosts":
            self._draw_hosts(entry, pal)
        elif kind == "alerts":
            self._draw_alerts(entry, pal)
        elif kind == "stats":
            self._draw_stats(entry, pal)
        elif kind == "tip":
            entry["widget"].update(Text(tip_for(section, self.opened), no_wrap=True, overflow="ellipsis"))
        elif kind == "footer":
            self._draw_footer(entry, pal)
        elif kind == "text":
            text = expand(section["text"])
            entry["empty"] = not text.strip()
            entry["widget"].update(Text(text, style=section_style(section), no_wrap=True, overflow="ellipsis"))
        if section["border"] and kind not in ("menu", "spacer"):
            entry["widget"].border_title = expand(section.get("title", ""))

    def _tick(self) -> None:
        if self.rebuilding or not is_front(self):
            return
        pal = palette(self.app)
        for entry in self.leaves:
            self._draw(entry, pal)
        self._draw_logos()

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
        else:
            self.notify(f"Unknown menu action “{route}”", severity="warning")


class DashboardPreview(StartupScreen):

    BINDINGS = [("escape", "close", "Close")]

    def action_open(self, route: str) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)