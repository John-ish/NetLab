import statistics
from datetime import datetime, timedelta

from rich import box
from rich.style import Style
from rich.table import Table
from rich.text import Text

from .charts import bar_ruler, line_chart, stacked_bar
from .constants import LEVEL_RANK, SERVICE_ICON, SERVICE_LABEL, THRESHOLDS
from .helpers import (
    add_row, fmt_bytes, fmt_duration, fmt_gb, fmt_ms, fmt_pct, fmt_rate, interval_label, kv,
    level_style, log_event_text, newtext, rate, usage_bar,
)
from .metrics import HostMetrics
from .state import LOGS
from .store import store


def health_checks(status: str, services: list, m: HostMetrics) -> list[tuple]:
    down = sum(1 for _, _, s in services if s == "down")
    degraded = sum(1 for _, _, s in services if s == "warning")
    if status == "offline":
        checks = [("Reachability", "critical", "Host is not responding")]
        if down:
            checks.append(("Services", "critical", f"{down} not running"))
        return checks
    latency_level = rate("latency", m.latency)
    reach = f"Responding · {m.latency:.0f} ms" if latency_level == "ok" else f"High latency · {m.latency:.0f} ms"
    mount, _, _, _, used = max(m.disks, key=lambda d: d[4])
    if down:
        svc = ("Services", "critical", f"{down} failed")
    elif degraded:
        svc = ("Services", "warning", f"{degraded} degraded")
    else:
        svc = ("Services", "ok", "All running")
    updates = m.profile["updates"]
    checks = [("Reachability", latency_level, reach)]
    if m.live_data:
        checks += [
            ("CPU Load", rate("cpu", m.cpu), f"{m.cpu:.0f}% in use"),
            ("Memory", rate("mem", m.mem), f"{m.mem:.0f}% used"),
        ]
        if m.disk_known:
            checks.append(("Disk Usage", rate("disk", used), f"{mount} at {used:.0f}%"))
    checks.append(svc)
    if updates is not None:
        checks.append(("Updates", "info" if updates else "ok", f"{updates} available" if updates else "Up to date"))
    return checks


class DetailBuilder:

    def __init__(self, host: str, metrics: HostMetrics, pal: dict, width: int, range_seconds: int = 60):
        self.host, self.m, self.pal = host, metrics, pal
        self.width = max(40, width)
        self.window = range_seconds
        row = store.host(host)
        self.status = row[1] if row else "offline"
        self.services = store.services_of(host)
        self.details = store.details(host)
        self.p = metrics.profile

    def build(self, kind: str) -> list:
        return getattr(self, kind)()

    def _head(self, text: str, extra: str = "") -> Text:
        accent = self.pal["accent"]
        line = Text(no_wrap=True, overflow="crop")
        line.append("── ", style=f"dim {accent}")
        line.append(text, style=f"bold {accent}")
        if extra:
            line.append(extra, style="dim")
        line.append(" " + "─" * max(0, self.width - len(text) - len(extra) - 5), style=f"dim {accent}")
        return line

    def _table(self, *columns, right=()) -> Table:
        table = Table(box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 2), pad_edge=False,
                      header_style=f"bold {self.pal['accent']}", expand=False)
        for column in columns:
            table.add_column(column, justify="right" if column in right else "left", no_wrap=True)
        return table

    def _bar(self, pct: float, width: int = 24, low: float = 70, high: float = 90) -> Text:
        return usage_bar(pct, width, self.pal, low, high)

    def _plot(self, title: str, key: str, rows: int, fmt) -> list:
        m = self.m
        values = list(m.history[key])[-self.window:]
        extra = f"   avg {fmt(sum(values) / len(values))}   peak {fmt(max(values))}" if values else ""
        head = self._head(title, extra)
        lines = line_chart(values, self.window, self.width, rows, 0.0, m.ceiling(key), fmt, m.sampled_at, self.pal)
        return [head, *lines]

    def _status_cell(self, state: str) -> Text:
        color = {"up": self.pal["ok"], "warning": self.pal["warn"], "down": self.pal["bad"]}.get(state)
        return Text(f"{SERVICE_ICON[state]} {SERVICE_LABEL[state]}", style=color or "dim")

    def _process_table(self, key: str) -> Table:
        rows = self.m.top_cpu if key == "cpu" else self.m.top_mem
        table = self._table("PID", "Process", "CPU %", "Mem %", right=("PID", "CPU %", "Mem %"))
        for pid, name, cpu, mem in rows:
            add_row(table, str(pid), name, f"{cpu:.1f}", f"{mem:.1f}")
        if not rows:
            add_row(table, "—", "Not available on this host", "—", "—")
        return table

    def _offline(self) -> list:
        return [
            Text("Host is offline", style=f"bold {self.pal['bad']}"),
            Text("Live data is unavailable until the host responds again.", style="dim"),
        ]

    def _unavailable(self) -> list:
        title, hint = self.m.telemetry_text()
        return [Text(title, style=f"bold {self.pal['warn']}"), Text(hint, style="dim")]

    def cpu(self) -> list:
        if self.status == "offline":
            return self._offline()
        m, p = self.m, self.p
        if not m.live_data:
            return self._unavailable()
        usage = newtext()
        usage.append(f"{'Usage':<16}", style="dim")
        usage.append_text(self._bar(m.cpu, 30))
        usage.append(f"  {m.cpu:.0f}%", style="bold")
        freq = "—" if m.freq_mhz is None else f"{m.freq_mhz:.0f} MHz"
        if m.freq_range:
            freq += f" ({m.freq_range[0]:.0f}–{m.freq_range[1]:.0f})"
        out = [
            usage,
            kv("Load average", f"{m.load[0]:.2f} (1m)   {m.load[1]:.2f} (5m)   {m.load[2]:.2f} (15m)"),
            kv("Model", p["cpu_model"]),
            kv("Cores", p["cores"]),
            kv("Frequency", freq),
            Text(),
        ]
        out += self._plot("Load history", "cpu", 9, fmt_pct)
        out += [Text(), self._head("Per-core usage")]
        table = self._table("Core", "Usage", "%", "User", "System", "Idle", "I/O Wait",
                            right=("%", "User", "System", "Idle", "I/O Wait"))
        for i, c in enumerate(m.cores):
            user, system, wait = m.core_split[i]
            add_row(table, f"Core {i}", self._bar(c, 14), f"{c:.0f}%", f"{user:.0f}%",
                    f"{system:.0f}%", f"{max(0.0, 100 - c):.0f}%", f"{wait:.0f}%")
        out += [table, Text(), self._head("Top processes"), self._process_table("cpu")]
        return out

    def mem(self) -> list:
        if self.status == "offline":
            return self._offline()
        m = self.m
        if not m.live_data:
            return self._unavailable()
        info = m.mem_info
        total = info["total"]
        used = total * m.mem / 100
        available = info["available"]
        swap_total = info["swap_total"]
        usage = newtext()
        usage.append(f"{'Memory':<16}", style="dim")
        usage.append_text(self._bar(m.mem, 30, 80, 90))
        usage.append(f"  {m.mem:.0f}%", style="bold")
        table = self._table("Type", "Usage", "Amount")
        add_row(table, "RAM used", self._bar(m.mem, 14, 80, 90), f"{used:.1f} / {total:.1f} GB ({m.mem:.0f}%)")
        if swap_total:
            swap_used = swap_total - info["swap_free"]
            add_row(table, "Swap used", self._bar(swap_used / swap_total * 100, 14),
                    f"{swap_used:.1f} / {swap_total:.1f} GB")
        if info["cache"] is not None:
            add_row(table, "Cache", "", f"{info['cache']:.1f} GB")
            add_row(table, "Buffers", "", f"{info['buffers']:.1f} GB")
        add_row(table, "Available", "", f"{available:.1f} GB ({available / total * 100:.0f}%)")
        out = [usage, kv("Total", f"{total:.1f} GB"), kv("Used", f"{used:.1f} GB"), Text(),
               self._head("Memory breakdown"), table, Text()]
        out += self._plot("Memory history", "mem", 9, fmt_pct)
        out += [Text(), self._head("Top consumers"), self._process_table("mem")]
        return out

    def _space_bar(self) -> list:
        m, pal = self.m, self.pal
        disks = [d for d in m.disks if not d[0].startswith("/boot")] or m.disks
        total = sum(d[3] for d in disks)
        colors = [pal["accent"], pal["warn"], "#5fafff", "#af87ff", "#5fd7af"]
        slices = [(f"{d[0]} used", d[3] * d[4] / 100, colors[i % len(colors)]) for i, d in enumerate(disks)]
        used = sum(v for _, v, _ in slices)
        free = total - used
        slices.append(("Free", free, "#3a3a3a"))
        labels = [f"{d[0]}  {fmt_gb(v)}  {v / total * 100:.0f}%" for d, (_, v, _) in zip(disks, slices)]
        labels.append(f"Free  {fmt_gb(free)}  {free / total * 100:.0f}%")
        width = max(30, min(self.width - 4, 84))
        bar = stacked_bar(slices, width, 3, labels, f"dim {pal['accent']}")
        ruler = bar_ruler(width, [(THRESHOLDS["disk"][0], pal["warn"]), (THRESHOLDS["disk"][1], pal["bad"])], pal)
        legend = Text(" ", no_wrap=True)
        for name, _, color in slices:
            legend.append("■ ", style=Style(color=color))
            legend.append(f"{name}    ")
        pct = used / total * 100
        level = rate("disk", pct)
        status = Text(f"● {'Healthy' if level == 'ok' else level.capitalize()}", style=level_style(level, pal))
        summary = Table.grid(padding=(0, 2))
        for _ in range(4):
            summary.add_column(no_wrap=True)
        dim = lambda text: Text(text, style="dim")
        summary.add_row(dim("Total capacity"), Text(fmt_gb(total)), dim("Inodes (/)"), Text(f"{m.disks[0][4] * 0.1:.0f}% used"))
        summary.add_row(dim("Used"), Text(f"{fmt_gb(used)} ({pct:.1f}%)"), dim("Read"), Text(fmt_rate(m.io_read)))
        summary.add_row(dim("Free"), Text(f"{fmt_gb(free)} ({100 - pct:.1f}%)"), dim("Write"), Text(fmt_rate(m.io_write)))
        summary.add_row(dim("Status"), status, dim("Thresholds"),
                        Text(f"warn {THRESHOLDS['disk'][0]}% · critical {THRESHOLDS['disk'][1]}%"))
        return [*bar, *ruler, Text(), legend, Text(), summary]

    def disk(self) -> list:
        if self.status == "offline":
            return self._offline()
        m = self.m
        if not m.live_data:
            return self._unavailable()
        if not m.disk_known:
            return [Text("Filesystem data is not available", style="dim")]
        table = self._table("Mount", "Device", "Type", "Size", "Used", "Available", "Usage",
                            right=("Size", "Used", "Available"))
        for mount, device, fstype, size, pct in m.disks:
            used = size * pct / 100
            usage = self._bar(pct, 14, 80, 90)
            usage.append(f" {pct:.0f}%")
            add_row(table, mount, device, fstype, fmt_gb(size), fmt_gb(used), fmt_gb(size - used), usage)
        out = [self._head("Space usage"), Text(), *self._space_bar(), Text(), self._head("Filesystems"), table, Text()]
        out += self._plot("Disk I/O", "io", 5, fmt_rate)
        return out

    def net(self) -> list:
        if self.status == "offline":
            return self._offline()
        m, p = self.m, self.p
        if not m.live_data:
            return self._unavailable()
        peak = max(max(m.history["rx"], default=0.0), max(m.history["tx"], default=0.0), 1.0) * 1.25
        table = self._table("Direction", "Speed", "Activity", "Total", "Packets/s", right=("Speed", "Total", "Packets/s"))
        add_row(table, "↓ RX", fmt_rate(m.rx), self._bar(m.rx / peak * 100, 16, 101, 101), fmt_bytes(m.rx_total), f"{m.rx_pps:,.0f}")
        add_row(table, "↑ TX", fmt_rate(m.tx), self._bar(m.tx / peak * 100, 16, 101, 101), fmt_bytes(m.tx_total), f"{m.tx_pps:,.0f}")
        conns = m.conns or {}
        out = [
            kv("Interface", p["iface"]),
            kv("IP address", self.details["address"] or "—"),
            kv("MAC address", m.mac),
            kv("Link speed", "—" if m.link_speed is None else f"{m.link_speed:,} Mbit/s"),
            Text(), self._head("Traffic"), table, Text(),
            kv("Established", conns.get("established", "—")),
            kv("Listening", conns.get("listen", "—")),
            kv("Time wait", conns.get("time_wait", "—")),
            kv("Errors / drops", f"{m.net_errors[0]} / {m.net_errors[1]}"),
            Text(),
        ]
        out += self._plot("Download", "rx", 5, fmt_rate)
        out += [Text()]
        out += self._plot("Upload", "tx", 5, fmt_rate)
        return out

    def gpu(self) -> list:
        if self.status == "offline":
            return self._offline()
        m = self.m
        if not m.live_data:
            return self._unavailable()
        if not m.gpus:
            return [Text("No GPU detected", style=f"bold {self.pal['warn']}"),
                    Text("Live GPU metrics need nvidia-smi on the host.", style="dim")]
        avg = sum(g["util"] for g in m.gpus) / len(m.gpus)
        usage = newtext()
        usage.append(f"{'Usage':<16}", style="dim")
        usage.append_text(self._bar(avg, 30))
        usage.append(f"  {avg:.0f}%", style="bold")
        table = self._table("GPU", "Name", "Usage", "Memory", "Temp", right=("Usage", "Memory", "Temp"))
        for i, g in enumerate(m.gpus):
            add_row(table, str(i), g["name"], f"{g['util']:.0f}%",
                    f"{g['mem_used'] / 1024:.1f} / {g['mem_total'] / 1024:.1f} GB", f"{g['temp']:.0f} °C")
        out = [usage, Text(), self._head("Devices"), table, Text()]
        out += self._plot("Usage history", "gpu", 9, fmt_pct)
        return out

    def latency(self) -> list:
        if self.status == "offline":
            return self._offline()
        m = self.m
        values = list(m.history["latency"])[-self.window:]
        jitter = statistics.pstdev(values[-20:]) if len(values) > 1 else 0.0
        out = [
            kv("Target", self.details["address"] or "—"),
            kv("Current", f"{m.latency:.0f} ms"),
            kv("Average", f"{sum(values) / len(values):.0f} ms"),
            kv("Min / Max", f"{min(values):.0f} / {max(values):.0f} ms"),
            kv("Jitter", f"{jitter:.1f} ms"),
            kv("Packet loss", f"{m.loss:.1f}%"),
            Text(),
        ]
        out += self._plot("Latency", "latency", 9, fmt_ms)
        table = self._table("Service", "Port", "Status", "Latency", right=("Port", "Latency"))
        for name, port, state in self.services:
            lat = m.service_latency(name, state, port)
            add_row(table, name, str(port), self._status_cell(state), "—" if lat is None else f"{lat:.0f} ms")
        out += [Text(), self._head("Service latency"), table]
        return out

    def alerts(self) -> list:
        pal = self.pal
        checks = health_checks(self.status, self.services, self.m)
        crit = sum(1 for c in checks if c[1] == "critical")
        warn = sum(1 for c in checks if c[1] == "warning")
        summary = newtext()
        summary.append("● ", style=pal["bad"] if crit else pal["warn"] if warn else pal["ok"])
        summary.append("Critical: ")
        summary.append(str(crit), style=pal["bad"])
        summary.append(" | Warnings: ")
        summary.append(str(warn), style=pal["warn"])
        table = self._table("Check", "Status", "Details")
        for check, level, detail in sorted(checks, key=lambda c: LEVEL_RANK[c[1]]):
            add_row(table, check, Text(level.upper() if level != "ok" else "OK", style=level_style(level, pal)), detail)
        out = [summary, Text(), self._head("Health checks"), table, Text(), self._head("Recent alerts")]
        recent = [e for e in LOGS if e[3] == self.host and e[4] in ("warning", "error")][:8]
        if not recent:
            out.append(Text("No recent alerts", style="dim"))
        else:
            log_table = self._table("Time", "Level", "Event")
            for entry in recent:
                color = pal["bad"] if entry[4] == "error" else pal["warn"]
                add_row(log_table, entry[0], Text(entry[4].upper(), style=color), log_event_text(entry))
            out.append(log_table)
        return out

    def sysinfo(self) -> list:
        m, p, d = self.m, self.p, self.details
        uptime = m.uptime()
        booted = "—" if uptime is None else (datetime.now() - timedelta(seconds=uptime)).strftime("%Y-%m-%d %H:%M")
        return [
            self._head("System"),
            kv("Hostname", self.host),
            kv("Address", d["address"] or "—"),
            kv("Description", d["description"] or "—"),
            kv("OS", p["os"]),
            kv("Kernel", p["kernel"]),
            kv("Architecture", p["arch"]),
            kv("Uptime", "Unknown" if uptime is None else fmt_duration(uptime)),
            kv("Booted", booted),
            Text(),
            self._head("Hardware"),
            kv("CPU", p["cpu_model"]),
            kv("Cores", p["cores"] or "—"),
            kv("Memory", f"{p['mem_gb']} GB" if p["mem_gb"] else "—"),
            kv("Network", f"{p['iface']} · {m.mac}" if m.info_known else "—"),
            kv("Storage", ", ".join(f"{disk[0]} ({fmt_gb(disk[3])})" for disk in m.disks) if m.disk_known else "—"),
            Text(),
            self._head("Monitoring"),
            kv("Services", f"{len(self.services)} configured"),
            kv("Interval", interval_label(store.monitor_interval(self.host))),
        ]

    def monitor(self) -> list:
        m, pal = self.m, self.pal
        interval = store.monitor_interval(self.host)
        state = Text("❚❚ Paused", style=pal["warn"]) if m.paused else Text("● Enabled", style=pal["ok"])
        nxt = "paused" if m.paused else f"in {max(0, round(m.countdown))}s"
        out = [
            state,
            kv("Check interval", interval_label(interval)),
            kv("Next check", nxt),
            kv("Last check", m.last_check or "—"),
            kv("Checks run", m.checks),
            kv("Metrics source", m.source_label()),
            Text(),
            self._head("Service checks"),
        ]
        table = self._table("Service", "Port", "Protocol", "Interval", "Status", "Latency", right=("Port", "Latency"))
        for name, port, state_name in self.services:
            info = store.service_details(self.host, name, port)
            lat = m.service_latency(name, state_name, port)
            add_row(table, name, str(port), info["protocol"], interval_label(info["interval"]),
                    self._status_cell(state_name), "—" if lat is None else f"{lat:.0f} ms")
        out.append(table if self.services else Text("No services configured", style="dim"))
        limits = self._table("Metric", "Warning", "Critical")
        add_row(limits, "CPU usage", f"{THRESHOLDS['cpu'][0]}%", f"{THRESHOLDS['cpu'][1]}%")
        add_row(limits, "Memory usage", f"{THRESHOLDS['mem'][0]}%", f"{THRESHOLDS['mem'][1]}%")
        add_row(limits, "Disk usage", f"{THRESHOLDS['disk'][0]}%", f"{THRESHOLDS['disk'][1]}%")
        add_row(limits, "Latency", f"{THRESHOLDS['latency'][0]} ms", f"{THRESHOLDS['latency'][1]} ms")
        out += [Text(), self._head("Alert thresholds"), limits, Text(), self._head("Recent activity")]
        log = self._table("Time", "Event")
        for stamp, text, level in m.activity:
            add_row(log, stamp, Text(text, style=pal["bad"] if level == "error" else ""))
        out.append(log)
        return out
