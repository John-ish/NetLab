import time
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from ..charts import line_chart
from ..collectors import collectors, is_docker
from ..config import STYLE_PATH
from ..constants import (
    CONTAINER_ICON, CONTAINER_LABEL, DETAIL_REFRESH_SECONDS, HOST_ICON, RANGES, RANGE_MEMORY,
    REVEAL_SECONDS, SERVICE_DETAIL_EVENTS, SERVICE_DETAIL_HINTS, SERVICE_ICON, SERVICE_LABEL,
    SERVICE_PRESETS,
)
from ..errors import DatabaseError
from ..helpers import (
    ago, fmt_duration, fmt_mb, interval_label, is_front, kv, local_now, nav_hint_text, newtext,
    palette, put, service_site, usage_bar,
)
from ..metrics import ServiceMetrics, service_monitor
from ..network import http_phrase, new_probe, probe_service_details
from ..state import SERVICE_LIVE
from ..store import store
from ..sudo import sudo_lock_clear, sudo_lock_fail, sudo_lock_remaining
from ..widgets import DetailCard, KeyBar, LiveBadge, RangeOption, SvcScroll
from .dialogs import AccessScreen, DeleteServiceScreen, IntervalScreen, SudoScreen
from .service_forms import EditServiceScreen


class ServiceDetailScreen(Screen):

    CSS_PATH = STYLE_PATH

    BINDINGS = [
        ("escape", "back", "Back"),
        ("m", "app.main_menu", "Main Menu"),
        ("e", "edit_service", "Edit"),
        ("d", "delete_service", "Remove"),
        ("r", "check_now", "Check"),
        ("i", "edit_interval", "Interval"),
        ("v", "reveal", "Reveal"),
        ("a", "edit_access", "Access"),
        ("t", "next_range", "Range"),
        ("g", "next_graph", "Graph"),
        ("1", "pick_range(0)", "1 min"),
        ("2", "pick_range(1)", "5 min"),
        ("3", "pick_range(2)", "15 min"),
        ("4", "pick_range(3)", "1 hour"),
    ]

    def __init__(self, original: tuple):
        super().__init__()
        self.original = original
        self.svc = service_monitor.get(*original)
        self.range_index = RANGE_MEMORY.get("service", 0)
        self.series_index = 0
        self.revealed_until = 0.0
        self.checking = False

    def compose(self) -> ComposeResult:
        with Vertical(id="sv-panel"):
            with SvcScroll(id="sv-scroll"):
                yield LiveBadge("", id="live")
                with Horizontal(id="sv-top"):
                    with Vertical(id="sv-status"):
                        yield Static("", id="body-status")
                    with Vertical(id="sv-info"):
                        yield Static("", id="body-info")
                with Vertical(id="sv-graph"):
                    with Horizontal(id="sv-range"):
                        yield Static("Range", id="range-label")
                        for index, (label, _) in enumerate(RANGES):
                            yield RangeOption(label, index)
                        yield Static("", id="sv-graph-name")
                    yield Static("", id="sv-chart")
                with Vertical(id="sv-docker"):
                    yield Static("", id="body-docker")
                with Horizontal(id="sv-bottom"):
                    with Vertical(id="sv-res"):
                        yield Static("", id="body-res")
                    with Vertical(id="sv-checks"):
                        yield Static("", id="body-checks")
                    yield DetailCard("access", "ACCESS", Static("", id="body-access"), subtitle="[a] Edit  [v] Reveal")
            with Horizontal(id="footer-bar"):
                yield KeyBar(SERVICE_DETAIL_EVENTS)
                with Horizontal(id="footer-stats"):
                    yield Static("", id="stat-total")
                    yield Static("|", id="stat-sep")
                    yield Static("", id="stat-online", classes="online")

    def on_mount(self) -> None:
        collectors.acquire(("service",) + self.original)
        panel = self.query_one("#sv-panel")
        panel.border_title = "SERVICE DETAILS"
        panel.border_subtitle = nav_hint_text(SERVICE_DETAIL_HINTS)
        self.query_one("#sv-status").border_title = "STATUS"
        self.query_one("#sv-info").border_title = "DETAILS"
        self.query_one("#sv-graph").border_title = "RESPONSE TIME"
        self.query_one("#sv-res").border_title = "RESOURCES"
        self.query_one("#sv-checks").border_title = "RECENT CHECKS"
        self.query_one("#sv-docker").border_title = "CONTAINERS"
        self._sync_range()
        self._refresh()
        self.query_one("#card-access").focus()
        self.call_after_refresh(self._refresh)
        self.set_interval(DETAIL_REFRESH_SECONDS, self._tick)

    def on_unmount(self) -> None:
        collectors.release(("service",) + self.original)

    def _state(self) -> str:
        host, name, port = self.original
        return next((s for n, p, s in store.services_of(host) if (n, p) == (name, port)), "pending")

    def _tick(self) -> None:
        host, name, port = self.original
        interval = store.service_details(host, name, port)["interval"]
        self.svc.advance(self._state(), interval)
        if self.revealed_until and time.monotonic() >= self.revealed_until:
            self.revealed_until = 0.0
        if not is_front(self):
            return
        self.query_one("#live", Static).toggle_class("-dim")
        self._refresh()

    def _refresh(self) -> None:
        host, name, port = self.original
        m = self.svc
        m.state = self._state()
        pal = palette(self.app)
        details = store.service_details(host, name, port)
        put(self.query_one("#body-status", Static), self._status_text(m, details, pal))
        put(self.query_one("#body-info", Static), self._info_text(host, name, port, details, pal))
        self._draw_chart(m, pal)
        put(self.query_one("#body-res", Static), self._res_text(m, pal))
        put(self.query_one("#body-checks", Static), self._checks_text(m, pal))
        put(self.query_one("#body-access", Static), self._access_text(pal))
        self.query_one("#live", LiveBadge).show(details["interval"])
        docker = is_docker(name)
        self.query_one("#sv-docker").display = docker
        if docker:
            containers = (m.containers or []) if m.live_data and m.state in ("up", "warning") else []
            running = sum(1 for c in containers if c["state"] == "running")
            self.query_one("#sv-docker").border_subtitle = f"{running} running / {len(containers)}"
            put(self.query_one("#body-docker", Static), self._docker_text(host, pal))
        color = {"up": pal["ok"], "warning": pal["warn"], "down": pal["bad"]}.get(m.state, "dim")
        total = self.query_one("#stat-total", Static)
        put(total, Text(f"{SERVICE_ICON[m.state]} {SERVICE_LABEL[m.state].upper()}", style=color))
        latency = m.latency if m.state in ("up", "warning") else None
        put(self.query_one("#stat-online", Static), "—" if latency is None else f"{latency:.0f} ms")

    def _status_text(self, m: ServiceMetrics, details: dict, pal: dict) -> Text:
        color = {"up": pal["ok"], "warning": pal["warn"], "down": pal["bad"]}.get(m.state, "dim")
        head = newtext()
        head.append(f"{SERVICE_ICON[m.state]}  {SERVICE_LABEL[m.state].upper()}", style=f"bold {color}")
        stats = SERVICE_LIVE.get(self.original) or {}
        since = stats.get("since")
        running = m.state in ("up", "warning")
        if since is not None:
            uptime = max(0.0, (local_now() - since).total_seconds()) if running else None
        else:
            uptime = None
        if m.live_data and m.proc and running:
            uptime = m.proc["uptime"]
        last = m.checks[0] if m.checks else None
        last_text = "—"
        if last:
            last_text = f"{last[0]} · " + ("OK" if last[1] else (last[3] or "Failed"))
        total = stats.get("total")
        if total:
            passed = stats["passed"]
        else:
            total, passed = m.total_checks, m.passed
        return newtext("\n").join([
            head,
            kv("Uptime", "—" if uptime is None else fmt_duration(uptime), width=14),
            kv("State since", "—" if since is None else ago(since), width=14),
            kv("Last check", last_text, width=14),
            kv("Next check", f"in {max(0, round(m.countdown))}s", width=14),
            kv("Response", f"{m.latency:.0f} ms" if running and m.latency is not None else "—", width=14),
            kv("Availability", f"{passed / total * 100:.2f}%" if total else "—", width=14),
            kv("Checks", f"{total:,} · {total - passed:,} failed", width=14),
        ])

    def _info_text(self, host: str, name: str, port: int, details: dict, pal: dict) -> Text:
        info = store.details(host)
        row = store.host(host)
        status = row[1] if row else "offline"
        host_color = {"online": pal["ok"], "warning": pal["warn"]}.get(status, "dim")
        where = newtext()
        where.append(f"{'Host':<14}", style="dim")
        where.append(f"{HOST_ICON.get(status, '○')} ", style=host_color)
        where.append(host)
        preset = name in {n for n, _, _ in SERVICE_PRESETS}
        lines = [
            kv("Service", f"{name} · {'Preset' if preset else 'Custom'}", width=14),
            kv("Description", details["description"] or "—", width=14),
            where,
            kv("Address", f"{info['address'] or '—'}:{port}", width=14),
            kv("Protocol", details["protocol"], width=14),
            kv("Interval", interval_label(details["interval"]), width=14),
        ]
        live = self.svc
        if live.live_data and live.listening is not None:
            lines.append(kv("Listening", "Yes" if live.listening else "No", width=14,
                            style=pal["ok"] if live.listening else pal["bad"]))
        stats = SERVICE_LIVE.get((host, name, port)) or {}
        http = stats.get("http")
        if http:
            code, ms = http
            color = pal["bad"] if code >= 500 else pal["warn"] if code >= 400 else pal["ok"]
            lines.append(kv("HTTP", f"{code} {http_phrase(code)} · {ms} ms".replace("  ", " "), width=14, style=color))
        cert = stats.get("cert_days")
        if cert is not None:
            color = pal["bad"] if cert < 7 else pal["warn"] if cert < 30 else pal["ok"]
            lines.append(kv("Certificate", "Expired" if cert < 0 else f"{cert} days left", width=14, style=color))
        if stats.get("banner"):
            lines.append(kv("Version", stats["banner"], width=14))
        return newtext("\n").join(lines)

    def _draw_chart(self, m: ServiceMetrics, pal: dict) -> None:
        chart = self.query_one("#sv-chart", Static)
        series = m.series()
        title, key, fmt = series[self.series_index % len(series)]
        box = self.query_one("#sv-graph")
        box.border_title = title.upper()
        box.border_subtitle = Text("[g] Switch graph" if len(series) > 1 else "")
        put(self.query_one("#sv-graph-name", Static), Text(f"Graph: {title}", style="dim"))
        if m.state not in ("up", "warning"):
            down = m.state == "down"
            chart.update(newtext("\n").join([
                Text(f"Service is {SERVICE_LABEL[m.state].lower()}", style=f"bold {pal['bad'] if down else 'dim'}"),
                Text("No data is collected while the service is not running." if down
                     else "Waiting for the first check to complete.", style="dim"),
            ]))
            return
        if key != "latency" and not m.live_data:
            title_text, hint = m.telemetry_text()
            chart.update(newtext("\n").join([Text(title_text, style=f"bold {pal['warn']}"), Text(hint, style="dim")]))
            return
        window = RANGES[self.range_index][1]
        values = list(m.history[key])[-window:]
        room = chart.size.height - 2
        rows = next((r for r in (21, 17, 13, 9) if room >= r), 5)
        head = Text(no_wrap=True)
        head.append(title, style=f"bold {pal['accent']}")
        if values:
            head.append(f"   now {fmt(values[-1])}   avg {fmt(sum(values) / len(values))}   peak {fmt(max(values))}", style="dim")
        lines = line_chart(values, window, chart.size.width or 100, rows, 0.0, m.ceiling(key), fmt,
                           datetime.now(), pal, max_cols=220)
        chart.update(newtext("\n").join([head, *lines]))

    def _docker_text(self, host: str, pal: dict) -> Text:
        m = self.svc
        if m.state not in ("up", "warning"):
            return newtext("\n").join([
                Text("Docker daemon is not running", style=f"bold {pal['bad']}"),
                Text("Container data is unavailable until it responds again.", style="dim"),
            ])
        if not m.live_data:
            title, hint = m.telemetry_text()
            return newtext("\n").join([Text(title, style=f"bold {pal['warn']}"), Text(hint, style="dim")])
        if m.docker_error:
            return newtext("\n").join([
                Text("Docker is not accessible", style=f"bold {pal['bad']}"),
                Text(m.docker_error, style="dim"),
                Text("The SSH user needs access to the Docker socket (docker group).", style="dim"),
            ])
        containers = m.containers or []
        if not containers:
            return Text("No containers found", style="dim")
        state_colors = {"running": pal["ok"], "restarting": pal["warn"]}
        status_colors = {"up": pal["ok"], "warning": pal["warn"], "down": pal["bad"]}
        lines = []
        for index, c in enumerate(containers):
            if index:
                lines.append(Text())
            head = newtext()
            head.append(f"{CONTAINER_ICON[c['state']]} ", style=state_colors.get(c["state"], "dim"))
            head.append(f"{c['name']:<16}", style="bold")
            head.append(f"{c['image']:<24}", style="dim")
            head.append(f"{CONTAINER_LABEL[c['state']]:<12}", style=state_colors.get(c["state"], "dim"))
            if c["state"] == "running" and c.get("cpu") is not None:
                head.append(f"CPU {c['cpu']:>5.1f}%   MEM {c['mem']:>5.1f}%")
            lines.append(head)
            for i, (svc, port, state) in enumerate(c["services"]):
                line = newtext()
                line.append("   └─ " if i == len(c["services"]) - 1 else "   ├─ ", style="dim")
                line.append(f"{svc:<14}")
                line.append(f"{':' + str(port):<8}", style=pal["accent"])
                line.append(f"{SERVICE_ICON[state]} {SERVICE_LABEL[state]}", style=status_colors[state])
                lines.append(line)
        return newtext("\n").join(lines)

    def _res_text(self, m: ServiceMetrics, pal: dict) -> Text:
        if not m.live_data:
            title, hint = m.telemetry_text()
            return newtext("\n").join([Text(title, style=f"bold {pal['warn']}"), Text(hint, style="dim")])
        proc = m.proc
        if proc is None:
            return newtext("\n").join([
                Text("Process not found", style=f"bold {pal['warn']}"),
                Text("No running process matched this service.", style="dim"),
            ])
        width = self.query_one("#body-res", Static).size.width or 44
        bar_width = max(8, width - 8 - 2 - 12)
        cpu = newtext()
        cpu.append(f"{'CPU':<8}", style="dim")
        cpu.append_text(usage_bar(min(proc["cpu"], 100.0), bar_width, pal))
        cpu.append(f" {proc['cpu']:>5.1f}%")
        ram = newtext()
        ram.append(f"{'RAM':<8}", style="dim")
        ram.append_text(usage_bar(proc["mem_pct"], bar_width, pal))
        ram.append(f" {fmt_mb(proc['rss_mb']):>8}")
        return newtext("\n").join([
            cpu,
            ram,
            kv("Process", f"{proc['name']} (pid {proc['pid']})", width=10),
            kv("Owner", f"{proc['user']} · {proc['count']} process{'es' if proc['count'] != 1 else ''}", width=10),
            kv("Threads", proc["threads"], width=10),
            kv("Memory", f"{proc['mem_pct']:.1f}% of host", width=10),
        ])

    def _checks_text(self, m: ServiceMetrics, pal: dict) -> Text:
        lines = []
        for stamp, ok, latency, error in list(m.checks)[:7]:
            line = newtext()
            line.append(f"{stamp}  ", style="dim")
            if ok:
                line.append("✓ OK", style=pal["ok"])
                if latency is not None:
                    line.append(f"   {latency:.0f} ms")
            else:
                line.append(f"× {error or 'Failed'}", style=pal["bad"])
            lines.append(line)
        if not lines:
            return Text("Waiting for the first check", style="dim")
        return newtext("\n").join(lines)

    def _access_text(self, pal: dict) -> Text:
        host, name, port = self.original
        site = service_site(host, name, port)
        access = store.service_access(host, name, port)
        lines = [kv(site["label"], site["value"], width=10)]
        if not access["username"] and not access["password"]:
            lines.append(kv("Login", "No credentials stored", width=10))
            lines.append(Text())
            lines.append(newtext("Press [a] to add credentials", style="dim"))
            return newtext("\n").join(lines)
        if access["username"]:
            lines.append(kv("Username", access["username"], width=10))
        if not access["password"]:
            lines.append(kv("Password", "Not stored", width=10))
            return newtext("\n").join(lines)
        password = newtext()
        password.append(f"{'Password':<10}", style="dim")
        if access["visible"]:
            password.append(access["password"], style=f"bold {pal['warn']}")
            lines += [password, Text(), newtext("Always visible · press [a] to change", style="dim")]
            return newtext("\n").join(lines)
        remaining = self.revealed_until - time.monotonic()
        if remaining > 0:
            password.append(access["password"], style=f"bold {pal['warn']}")
            password.append(f"   hides in {int(remaining) + 1}s", style="dim")
        else:
            password.append("*" * 12)
        lines.append(password)
        lines.append(Text())
        locked = sudo_lock_remaining()
        if locked > 0:
            lines.append(newtext(f"Locked for {int(locked) + 1}s after failed attempts", style=pal["bad"]))
        elif remaining > 0:
            lines.append(newtext("Press [v] to hide now", style="dim"))
        else:
            lines.append(newtext("Press [v] to reveal · sudo password required", style="dim"))
        return newtext("\n").join(lines)

    def _sync_range(self) -> None:
        for option in self.query(RangeOption):
            option.set_class(option.index == self.range_index, "-active")

    def action_pick_range(self, index: int) -> None:
        self.range_index = max(0, min(len(RANGES) - 1, index))
        RANGE_MEMORY["service"] = self.range_index
        self._sync_range()
        self._refresh()

    def action_next_range(self) -> None:
        self.action_pick_range((self.range_index + 1) % len(RANGES))

    def action_next_graph(self) -> None:
        count = len(self.svc.series())
        self.series_index = (self.series_index + 1) % count
        self._refresh()

    def on_detail_card_opened(self, event: DetailCard.Opened) -> None:
        access = store.service_access(*self.original)
        if access["username"] or access["password"]:
            self.action_reveal()
        else:
            self.action_edit_access()

    def action_edit_access(self) -> None:
        self.app.push_screen(AccessScreen(self.original), callback=self.access_saved)

    def access_saved(self, result: dict | None) -> None:
        if result is None:
            return
        try:
            store.set_service_access(*self.original, result["username"], result["password"], result["visible"])
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        self.revealed_until = 0.0
        self._refresh()
        removed = result["username"] is None and result["password"] is None
        self.notify("Credentials removed" if removed else "Credentials saved")

    def action_reveal(self) -> None:
        if self.revealed_until:
            self.revealed_until = 0.0
            self._refresh()
            return
        host, name, port = self.original
        access = store.service_access(host, name, port)
        if not access["password"]:
            self.notify("No password is stored. Press [a] to add one")
            return
        if access["visible"]:
            self.notify("This password is always visible")
            return
        remaining = sudo_lock_remaining()
        if remaining > 0:
            self.notify(f"Too many failed attempts. Try again in {int(remaining) + 1}s", severity="error")
            return
        self.app.push_screen(SudoScreen(name), callback=self.sudo_result)

    def sudo_result(self, granted: bool | None) -> None:
        if granted:
            sudo_lock_clear()
            self.revealed_until = time.monotonic() + REVEAL_SECONDS
        elif granted is False:
            sudo_lock_fail()
            self.notify("Too many failed attempts", severity="error")
        self._refresh()

    def action_back(self) -> None:
        self.dismiss(self.original)

    def action_edit_interval(self) -> None:
        host, name, port = self.original
        current = store.service_details(host, name, port)["interval"]
        self.app.push_screen(IntervalScreen(name, current), callback=self.interval_chosen)

    def interval_chosen(self, seconds: int | None) -> None:
        if seconds is None:
            return
        try:
            store.set_service_interval(*self.original, seconds)
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        self.svc.countdown = min(self.svc.countdown, float(seconds))
        self._refresh()
        self.notify(f"Checking {self.original[1]} every {interval_label(seconds)}")

    def action_edit_service(self) -> None:
        self.app.push_screen(EditServiceScreen(self.original), callback=self.service_edited)

    def service_edited(self, result: dict | None) -> None:
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
        self.original = (result["host"], result["name"], result["port"])
        self.svc = service_monitor.get(*self.original)
        self.revealed_until = 0.0
        self.series_index = 0
        if not collectors.active(("service",) + self.original):
            collectors.acquire(("service",) + self.original)
        self._refresh()
        self.notify(f"Saved {result['name']} on {result['host']}")

    def action_delete_service(self) -> None:
        self.app.push_screen(DeleteServiceScreen(self.original), callback=self.service_deleted)

    def service_deleted(self, original: tuple | None) -> None:
        if original is None:
            return
        try:
            store.remove_service(*original)
        except DatabaseError as error:
            self.notify(str(error), severity="error")
            return
        self.notify(f"Removed {original[1]} from {original[0]}")
        self.dismiss(None)

    def action_check_now(self) -> None:
        if self.checking:
            return
        host, name, port = self.original
        address = store.details(host)["address"]
        if not address:
            self.notify("No address saved for this host")
            return
        protocol = store.service_details(host, name, port)["protocol"]
        if self.svc.telemetry == "error":
            collectors.restart(("service",) + self.original)
        self.checking = True
        self.notify(f"Checking {name}…")
        self.run_worker(self._run_probe(self.original, address, protocol), exclusive=True)

    async def _run_probe(self, original: tuple, address: str, protocol: str) -> None:
        host, name, port = original
        try:
            result = await probe_service_details(address, port, protocol)
        except Exception:
            result = new_probe("The check could not be completed")
        latency, error = result["latency"], result["error"]
        self.checking = False
        service_monitor.get(*original).record_probe(error is None, latency, error)
        if protocol != "UDP":
            try:
                store.apply_service_result(host, name, port, error is None,
                                           None if error else round(latency, 1), result)
            except DatabaseError as db_error:
                self.notify(str(db_error), severity="error")
        if error:
            store._log(f"Manual check on {name} failed: {error}", host, "warning")
            self.notify(error, severity="error")
        else:
            store._log(f"Manual check on {name}: {latency:.0f} ms", host)
            self.notify(f"{name} responded in {latency:.0f} ms")
        self._refresh()
