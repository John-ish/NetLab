from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import ListView, Static

from ..collectors import collectors
from ..config import STYLE_PATH
from ..constants import (
    DETAIL_ACTION_EVENTS, DETAIL_NAV_HINTS, DETAIL_REFRESH_SECONDS, HOST_ICON, LEVEL_RANK,
    METRIC_CARDS,
)
from ..detail_builder import health_checks
from ..errors import DatabaseError
from ..helpers import (
    fmt_duration, fmt_rate, interval_label, is_front, kv, level_style, nav_hint_text, newtext,
    palette, put, rate,
)
from ..live import live
from ..metrics import HostMetrics, monitor
from ..network import PING_MISSING, probe_host
from ..ssh import ssh_service_port
from ..store import store
from ..widgets import DetailCard, KeyBar, LiveBadge, ServiceItem, ServiceList, SparkLine, SvcScroll
from .dialogs import IntervalScreen
from .host_forms import EditHostScreen
from .logs import LogsClass
from .metric_detail import MetricDetailScreen
from .service_detail import ServiceDetailScreen
from .ssh_setup import SshSetupScreen


class HostDetailScreen(Screen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "back", "Back"),
        ("m", "app.main_menu", "Main Menu"),
        ("up", "nav(0, -1)", "Up"),
        ("down", "nav(0, 1)", "Down"),
        ("left", "nav(-1, 0)", "Left"),
        ("right", "nav(1, 0)", "Right"),
        ("e", "edit_host", "Edit Host"),
        ("r", "check_now", "Check Now"),
        ("i", "edit_interval", "Interval"),
        ("l", "view_logs", "View Logs"),
        ("s", "ssh_setup", "SSH Setup"),
    ]

    def __init__(self, host_name: str):
        super().__init__()
        self.host_name = host_name
        self.host_metrics = monitor.get(host_name)
        self.checking = False

    def _service_items(self) -> list[ServiceItem]:
        m = self.host_metrics
        return [
            ServiceItem(name, port, state, m.service_latency(name, state, port))
            for name, port, state in store.services_of(self.host_name)
        ]

    def compose(self) -> ComposeResult:
        items = self._service_items()
        with Vertical(id="detail-panel"):
            with SvcScroll(id="detail-scroll"):
                yield LiveBadge("", id="live")
                with Horizontal(id="detail-top"):
                    with Vertical(id="host-box"):
                        yield Static("", id="body-host")
                    yield DetailCard("sysinfo", "SYSTEM INFO", Static("", id="body-sysinfo"))
                yield DetailCard("alerts", "SYSTEM ALERTS", Static("", id="body-alerts"))
                with Horizontal(id="detail-cards"):
                    for kind, title in METRIC_CARDS:
                        yield DetailCard(
                            kind, title,
                            Static("", id=f"val-{kind}", classes="card-value"),
                            Static("", id=f"sub-{kind}", classes="card-sub"),
                            SparkLine(2, 60, id=f"spark-{kind}", classes="card-spark"),
                        )
                with Horizontal(id="detail-bottom"):
                    with Vertical(id="svc-box"):
                        with Horizontal(id="header"):
                            yield Static("", classes="col-cursor")
                            yield Static("SERVICE", classes="col-name")
                            yield Static("PORT", classes="col-port")
                            yield Static("STATUS", classes="col-status")
                            yield Static("LATENCY", classes="col-latency")
                        yield ServiceList(*items, id="detail-services", classes="focus-target")
                        yield Static("No services configured", id="detail-svc-empty", classes="svc-none")
                    yield DetailCard("monitor", "MONITORING", Static("", id="body-monitor"))
            with Horizontal(id="footer-bar"):
                yield KeyBar(DETAIL_ACTION_EVENTS)
                with Horizontal(id="footer-stats"):
                    yield Static("", id="stat-total")
                    yield Static("|", id="stat-sep")
                    yield Static("", id="stat-online", classes="online")
                    yield Static("", id="stat-warning", classes="warning")
                    yield Static("", id="stat-down", classes="error")

    def on_mount(self) -> None:
        collectors.acquire(("host", self.host_name))
        panel = self.query_one("#detail-panel")
        panel.border_title = "HOST DETAILS"
        panel.border_subtitle = nav_hint_text(DETAIL_NAV_HINTS)
        self.query_one("#host-box").border_title = "HOST"
        self.query_one("#svc-box").border_title = "MONITORED SERVICES"
        self._refresh()
        if store.services_of(self.host_name):
            self.query_one("#detail-services").focus()
        else:
            self.query_one("#card-cpu").focus()
        self.set_interval(DETAIL_REFRESH_SECONDS, self._tick)

    def on_unmount(self) -> None:
        collectors.release(("host", self.host_name))

    def _tick(self) -> None:
        row = store.host(self.host_name)
        status = row[1] if row else "offline"
        self.host_metrics.advance(status, store.monitor_interval(self.host_name),
                                  store.services_of(self.host_name))
        if not is_front(self):
            return
        self.query_one("#live", Static).toggle_class("-dim")
        self._refresh()

    def _set_card(self, kind: str, value: str, sub: str, level: str, points, high: float = 100.0) -> None:
        val = self.query_one(f"#val-{kind}", Static)
        put(val, Text(value, no_wrap=True))
        for name in ("ok", "warning", "critical"):
            val.set_class(level == name, name)
        put(self.query_one(f"#sub-{kind}", Static), Text(sub, no_wrap=True, overflow="ellipsis"))
        self.query_one(f"#spark-{kind}", SparkLine).plot(points, high)

    def _refresh(self) -> None:
        name = self.host_name
        row = store.host(name)
        status = row[1] if row else "offline"
        services = store.services_of(name)
        m = self.host_metrics
        pal = palette(self.app)
        interval = store.monitor_interval(name)
        if status != "offline":
            if m.live_data:
                root = m.disks[0][4]
                total = m.mem_info["total"]
                self._set_card("cpu", f"{m.cpu:.0f}%", f"Load {m.load[0]:.2f} / {len(m.cores)} cores",
                               rate("cpu", m.cpu), m.history["cpu"])
                self._set_card("mem", f"{m.mem:.0f}%", f"{total * m.mem / 100:.1f} / {total:.1f} GB",
                               rate("mem", m.mem), m.history["mem"])
                if m.disk_known:
                    self._set_card("disk", f"{root:.0f}%", f"I/O {fmt_rate(m.io_read + m.io_write)}",
                                   rate("disk", root), m.history["disk"])
                else:
                    self._set_card("disk", "—", "No data", "", [])
                self._set_card("net", f"↓ {fmt_rate(m.rx)}", f"↑ {fmt_rate(m.tx)}", "",
                               m.history["rx"], m.ceiling("rx"))
                if m.gpus:
                    gpu = m.gpus[0]
                    avg = sum(g["util"] for g in m.gpus) / len(m.gpus)
                    self._set_card("gpu", f"{avg:.0f}%",
                                   f"{gpu['mem_used'] / 1024:.1f}/{gpu['mem_total'] / 1024:.0f} GB · {gpu['temp']:.0f}°C",
                                   rate("cpu", avg), m.history["gpu"])
                else:
                    self._set_card("gpu", "—", "No GPU detected", "", [])
            else:
                for kind in ("cpu", "mem", "disk", "net", "gpu"):
                    self._set_card(kind, "—", m.telemetry_short(), "", [])
            self._set_card("latency", f"{m.latency:.0f} ms", f"Loss {m.loss:.1f}%",
                           rate("latency", m.latency), m.history["latency"], m.ceiling("latency"))
        else:
            for kind, _ in METRIC_CARDS:
                self._set_card(kind, "—", "Host offline", "", [])
        put(self.query_one("#body-host", Static), self._host_text(row, status, services, m, pal))
        put(self.query_one("#body-alerts", Static), self._alerts_text(status, services, m, pal))
        put(self.query_one("#body-sysinfo", Static), self._sysinfo_text(m))
        put(self.query_one("#body-monitor", Static), self._monitor_text(m, interval, pal))
        self.query_one("#live", LiveBadge).show(interval)
        lookup = {(n, p): s for n, p, s in services}
        for item in self.query(ServiceItem):
            state = lookup.get((item.service, item.port), item.state)
            item.show(state, m.service_latency(item.service, state, item.port))
        self.query_one("#detail-services").display = bool(services)
        self.query_one("#detail-svc-empty").display = not services
        self.query_one("#svc-box").border_subtitle = f"{len(services)} configured"
        states = [s for _, _, s in services]
        put(self.query_one("#stat-total", Static), f"{len(services)} services")
        put(self.query_one("#stat-online", Static), f"{states.count('up')} up")
        put(self.query_one("#stat-warning", Static), f"{states.count('warning')} warning")
        put(self.query_one("#stat-down", Static), f"{states.count('down')} down")

    def _host_text(self, row, status: str, services: list, m: HostMetrics, pal: dict) -> Text:
        details = store.details(self.host_name)
        color = {"online": pal["ok"], "warning": pal["warn"]}.get(status, "dim")
        head = newtext()
        head.append(self.host_name, style="bold")
        head.append("   ")
        head.append(f"{HOST_ICON.get(status, '○')} {status.upper()}", style=color)
        where = details["address"] or "No address saved"
        if details["description"]:
            where += f" · {details['description']}"
        up = sum(1 for _, _, s in services if s == "up")
        offline = status == "offline"
        return newtext("\n").join([
            head,
            newtext(where, style="dim"),
            kv("Services", f"{up} / {len(services)} up", width=11),
            kv("Latency", "—" if offline else f"{m.latency:.0f} ms", width=11),
            kv("Last seen", (row[4] if row else "never") if offline else "now", width=11),
        ])

    def _alerts_text(self, status: str, services: list, m: HostMetrics, pal: dict) -> Text:
        checks = health_checks(status, services, m)
        active = sorted((c for c in checks if c[1] in ("critical", "warning")), key=lambda c: LEVEL_RANK[c[1]])
        crit = sum(1 for c in active if c[1] == "critical")
        summary = newtext()
        if not active:
            summary.append("● All systems healthy", style=pal["ok"])
        else:
            summary.append("● ", style=pal["bad"] if crit else pal["warn"])
            summary.append("Critical: ")
            summary.append(str(crit), style=pal["bad"])
            summary.append(" | Warnings: ")
            summary.append(str(len(active) - crit), style=pal["warn"])
        if not active:
            summary.append(f"  {len(checks)} checks passing", style="dim")
        lines = [summary]
        for check, level, detail in active:
            line = newtext()
            line.append(f"{check:<14}", style=level_style(level, pal))
            line.append(detail)
            lines.append(line)
        return newtext("\n").join(lines)

    def _sysinfo_text(self, m: HostMetrics) -> Text:
        p = m.profile
        uptime = m.uptime()
        return newtext("\n").join([
            kv("OS", p["os"], width=13),
            kv("Kernel", p["kernel"], width=13),
            kv("Architecture", p["arch"], width=13),
            kv("Uptime", "—" if uptime is None else fmt_duration(uptime), width=13),
            kv("CPU", p["cpu_model"], width=13),
        ])

    def _monitor_text(self, m: HostMetrics, interval: int, pal: dict) -> Text:
        state = newtext("❚❚ Paused", style=pal["warn"]) if m.paused else newtext("● Enabled", style=pal["ok"])
        nxt = "paused" if m.paused else f"in {max(0, round(m.countdown))}s"
        lines = [
            state,
            kv("Interval", interval_label(interval), width=12),
            kv("Next check", nxt, width=12),
            kv("Last check", m.last_check or "—", width=12),
            kv("Metrics", m.source_label(), width=12),
            Text(),
            Text("RECENT ACTIVITY", style=f"bold {pal['accent']}"),
        ]
        for stamp, text, level in list(m.activity)[:12]:
            line = newtext()
            line.append(f"{stamp}  ", style="dim")
            line.append(text, style=pal["bad"] if level == "error" else None)
            lines.append(line)
        return newtext("\n").join(lines)

    def action_edit_interval(self) -> None:
        current = store.monitor_interval(self.host_name)
        self.app.push_screen(IntervalScreen(self.host_name, current), callback=self.interval_chosen)

    def interval_chosen(self, seconds: int | None) -> None:
        if seconds is None:
            return
        try:
            store.set_host_interval(self.host_name, seconds)
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        self._refresh()
        self.notify(f"Checking {self.host_name} every {interval_label(seconds)}")

    def action_nav(self, dx: int, dy: int) -> None:
        targets = [w for w in self.query(".focus-target") if w.display]
        current = self.focused
        if current not in targets:
            if targets:
                targets[0].focus()
            return
        region = current.region
        cx, cy = region.x + region.width / 2, region.y + region.height / 2
        best, best_score = None, None
        for widget in targets:
            if widget is current:
                continue
            r = widget.region
            wx, wy = r.x + r.width / 2, r.y + r.height / 2
            along = (wx - cx) * dx + (wy - cy) * dy
            if along <= 0:
                continue
            score = along + 3 * (abs((wx - cx) * dy) + abs((wy - cy) * dx))
            if best_score is None or score < best_score:
                best, best_score = widget, score
        if best is not None:
            best.focus()

    def on_detail_card_opened(self, event: DetailCard.Opened) -> None:
        self.app.push_screen(MetricDetailScreen(self.host_name, event.kind))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ServiceItem):
            original = (self.host_name, event.item.service, event.item.port)
            self.app.push_screen(ServiceDetailScreen(original), callback=self.service_closed)

    async def service_closed(self, original: tuple | None) -> None:
        lv = self.query_one("#detail-services", ListView)
        index = lv.index or 0
        await lv.clear()
        await lv.extend(self._service_items())
        count = len(lv.children)
        lv.index = min(index, count - 1) if count else None
        self._refresh()
        lv.focus()

    def action_back(self) -> None:
        self.dismiss(self.host_name)

    def action_view_logs(self) -> None:
        self.app.push_screen(LogsClass(self.host_name))

    def action_ssh_setup(self) -> None:
        details = store.details(self.host_name)
        if not details["address"]:
            self.notify("No address saved for this host")
            return
        self.app.push_screen(
            SshSetupScreen(details["address"], details.get("ssh_user"),
                           details.get("ssh_port") or ssh_service_port(self.host_name)),
            callback=self.ssh_setup_done,
        )

    def ssh_setup_done(self, result: dict | None) -> None:
        if not result:
            return
        details = store.details(self.host_name)
        try:
            store.update(self.host_name, self.host_name, details["address"], details["description"],
                         ssh_user=result["user"], ssh_port=result["port"])
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        key = ("host", self.host_name)
        if collectors.active(key):
            collectors.restart(key)
        else:
            collectors.acquire(key)
        self.host_metrics = monitor.get(self.host_name)
        self._refresh()
        self.notify(f"SSH ready for {self.host_name}. Live metrics will appear shortly")

    def action_edit_host(self) -> None:
        self.app.push_screen(EditHostScreen(self.host_name), callback=self.host_edited)

    def host_edited(self, result: dict | None) -> None:
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
        self.host_name = result["name"]
        if not collectors.active(("host", self.host_name)):
            collectors.acquire(("host", self.host_name))
        self.host_metrics = monitor.get(self.host_name)
        if result["reachable"] and result["latency"] is not None:
            self.host_metrics.record_latency(result["latency"])
        self._refresh()
        self.notify(f"Saved {result['name']}")

    def action_check_now(self) -> None:
        if self.checking:
            return
        address = store.details(self.host_name)["address"]
        if not address:
            self.notify("No address saved for this host")
            return
        if monitor.get(self.host_name).telemetry == "error":
            collectors.restart(("host", self.host_name))
        self.checking = True
        self.notify(f"Checking {self.host_name}…")
        self.run_worker(self._run_check(self.host_name, address), exclusive=True)

    async def _run_check(self, host: str, address: str) -> None:
        try:
            _, latency, error = await probe_host(address)
        except Exception:
            latency, error = None, "The check could not be completed"
        self.checking = False
        m = monitor.get(host)
        tcp = live.fresh_alive(host) if error else None
        if tcp is not None:
            latency, error = tcp, None
        if error:
            m.note(f"Manual check failed: {error}", "error")
            if error != PING_MISSING:
                try:
                    store.apply_host_result(host, False, None)
                except DatabaseError as db_error:
                    self.notify(str(db_error), severity="error")
            store._log(f"Manual check on {host} failed: {error}", host, "warning")
            self.notify(error, severity="error")
        else:
            ms = max(1, round(latency))
            m.record_latency(ms)
            m.note(f"Manual check completed ({ms} ms)")
            store._log(f"Manual check on {host}: {ms} ms", host)
            try:
                store.apply_host_result(host, True, ms)
            except DatabaseError as db_error:
                self.notify(str(db_error), severity="error")
            self.notify(f"{host} responded in {ms} ms")
        self._refresh()
