import random
import time
import zlib
from collections import deque
from datetime import datetime, timedelta

from .constants import HISTORY_LENGTH, SSH_STALE_SECONDS
from .helpers import fmt_mb, fmt_ms, fmt_num, fmt_pct, nice_ceiling
from .state import SERVICE_LIVE
from .store import store


def _profile(os_name, kernel, cpu_model, cores, mem_gb, uptime_days, cpu, mem, disk,
             rx, tx, arch="x86_64", updates=0, disk_size=238, freq_max=3600):
    return {
        "os": os_name,
        "kernel": kernel,
        "arch": arch,
        "cpu_model": cpu_model,
        "cores": cores,
        "mem_gb": mem_gb,
        "uptime": uptime_days * 86400 + 4 * 3600 + 32 * 60,
        "freq": (800, freq_max),
        "updates": updates,
        "iface": "eth0",
        "disks": [
            ("/", "nvme0n1p2", "ext4", disk_size, disk),
            ("/boot/efi", "nvme0n1p1", "vfat", 1, 7),
        ],
        "base": {"cpu": cpu, "mem": mem, "io": 4e6 + cpu * 2e5, "rx": rx, "tx": tx},
    }


def blank_profile() -> dict:
    profile = _profile("—", "—", "—", 0, 0, 0, 0, 0, 0, 0.0, 0.0, arch="—")
    profile.update(uptime=0, updates=None, iface="—", disks=[("/", "—", "—", 0, 0)])
    return profile


class TelemetryState:

    telemetry = "none"
    telemetry_note = ""
    last_sample = 0.0

    @property
    def live_data(self) -> bool:
        return self.telemetry == "live" and time.monotonic() - self.last_sample < SSH_STALE_SECONDS

    def set_telemetry(self, state: str, note: str = "") -> None:
        if state == "error" and note != self.telemetry_note:
            self.note(f"SSH: {note}", "error")
        self.telemetry = state
        self.telemetry_note = note

    def telemetry_text(self) -> tuple[str, str]:
        if self.telemetry == "none":
            return "No SSH access configured", "Press [s] on this screen to run the guided SSH setup."
        if self.telemetry == "connecting":
            return "Connecting over SSH…", "Live data appears after the first sample."
        if self.telemetry == "error":
            return "SSH unavailable", self.telemetry_note
        return "Waiting for data", "Live data resumes when the SSH session reconnects."

    def telemetry_short(self) -> str:
        return {"none": "No SSH access", "connecting": "Connecting…", "error": self.telemetry_note}.get(
            self.telemetry, "Waiting for data")

    def source_label(self) -> str:
        if self.live_data:
            return "SSH · live"
        if self.telemetry == "none":
            return "Ping only"
        if self.telemetry == "error":
            return f"SSH · {self.telemetry_note}"
        return "SSH · connecting"


class HostMetrics(TelemetryState):

    def __init__(self, name: str):
        from .live import live
        self.host = name
        self.live = False
        self.live_latency = None
        self.rng = random.Random(zlib.crc32(name.encode()))
        row = store.host(name)
        self.status = row[1] if row else "offline"
        self.base_latency = float(row[5]) if row and row[5] else 20.0
        self.profile = blank_profile()
        self.mac = "—"
        self.telemetry = "none"
        self.telemetry_note = ""
        self.last_sample = 0.0
        self.seen = False
        self.info_known = False
        self.disk_known = False
        self.core_split = []
        self.mem_info = None
        self.rx_pps = self.tx_pps = 0.0
        self.net_errors = (0, 0)
        self.conns = None
        self.freq_mhz = None
        self.freq_range = None
        self.link_speed = None
        self.top_cpu, self.top_mem = [], []
        self.gpus = None
        self.probe_results = deque(maxlen=20)
        base = self.profile["base"]
        cores = self.profile["cores"]
        uptime = self.profile["uptime"]
        self.cpu, self.mem = float(base["cpu"]), float(base["mem"])
        self.io_read, self.io_write = base["io"] * 0.6, base["io"] * 0.4
        self.rx, self.tx = float(base["rx"]), float(base["tx"])
        self.rx_total, self.tx_total = base["rx"] * uptime * 0.2, base["tx"] * uptime * 0.2
        self.latency, self.loss = self.base_latency, 0.0
        self.core_bias = [self.rng.uniform(-12, 12) for _ in range(cores)]
        self.cores = [self.cpu] * cores
        self.load = [self.cpu / 100 * cores] * 3
        self.disks = [list(d) for d in self.profile["disks"]]
        self.disk_base = float(self.disks[0][4])
        self.history = {k: deque(maxlen=HISTORY_LENGTH) for k in ("cpu", "mem", "disk", "io", "rx", "tx", "latency", "gpu")}
        self.activity = deque(maxlen=40)
        self.paused = False
        self.checks = 0
        self.last_check = None
        self.started = self.last_tick = time.monotonic()
        interval = store.monitor_interval(name)
        self.countdown = float(interval)
        for _ in range(HISTORY_LENGTH - 1):
            self._step_latency()
            self.history["latency"].append(self.latency)
        self._step()
        self.sampled_at = datetime.now()
        if live.task is not None and self.status != "offline" and row and row[5]:
            self.live_latency = float(row[5])
        services = store.services_of(name)
        for k in range(4, 0, -1):
            stamp = (datetime.now() - timedelta(seconds=interval * k)).strftime("%H:%M:%S")
            self._record_check(stamp, services)

    def _walk(self, value, target, sigma, low, high):
        value += (target - value) * 0.2 + self.rng.gauss(0, sigma)
        return max(low, min(high, value))

    def _step(self, detail: bool = True) -> None:
        rng, base = self.rng, self.profile["base"]
        degraded = self.status == "warning"
        self.cpu = self._walk(self.cpu, base["cpu"] * (1.15 if degraded else 1.0), 3.0, 1.0, 99.0)
        if rng.random() < 0.04:
            self.cpu = min(99.0, self.cpu + rng.uniform(10, 25))
        self.mem = self._walk(self.mem, base["mem"], 0.3, 5.0, 98.0)
        self.io_read = self._walk(self.io_read, base["io"] * 0.6, base["io"] * 0.2, 0.0, base["io"] * 4)
        self.io_write = self._walk(self.io_write, base["io"] * 0.4, base["io"] * 0.15, 0.0, base["io"] * 4)
        self.rx = self._walk(self.rx, base["rx"], base["rx"] * 0.3, 0.0, base["rx"] * 6)
        self.tx = self._walk(self.tx, base["tx"], base["tx"] * 0.3, 0.0, base["tx"] * 6)
        self.rx_total += self.rx
        self.tx_total += self.tx
        self._step_latency()
        if detail:
            self.cores = [max(0.0, min(100.0, self.cpu + bias + rng.gauss(0, 5))) for bias in self.core_bias]
            raw = self.cpu / 100 * len(self.cores)
            self.load = [
                self.load[0] + (raw - self.load[0]) * 0.3,
                self.load[1] + (raw - self.load[1]) * 0.08,
                self.load[2] + (raw - self.load[2]) * 0.03,
            ]
        h = self.history
        h["cpu"].append(self.cpu)
        h["mem"].append(self.mem)
        self.disks[0][4] = self._walk(self.disks[0][4], self.disk_base, 0.06, 1.0, 99.0)
        h["disk"].append(self.disks[0][4])
        h["io"].append(self.io_read + self.io_write)
        h["rx"].append(self.rx)
        h["tx"].append(self.tx)
        h["latency"].append(self.latency)

    def _step_latency(self) -> None:
        if self.live_latency is not None:
            self.latency = self.live_latency
        else:
            self.latency = self._walk(self.latency, self.base_latency, max(1.0, self.base_latency * 0.1), 1.0, 999.0)
        if self.probe_results:
            self.loss = 100.0 * (1 - sum(self.probe_results) / len(self.probe_results))
        else:
            self.loss = self._walk(self.loss, 1.8, 0.4, 0.0, 100.0) if self.status == "warning" else 0.0

    def ingest(self, s: dict) -> None:
        if not self.seen:
            self.seen = True
            for key in ("cpu", "mem", "disk", "io", "rx", "tx", "gpu"):
                self.history[key].clear()
        if self.telemetry != "live":
            self.note("SSH metrics connected")
        self.cpu, self.cores, self.core_split = s["cpu"], s["cores"], s["core_split"]
        self.load = s["load"]
        self.mem, self.mem_info = s["mem"], s["mem_info"]
        self.io_read, self.io_write = s["io_read"], s["io_write"]
        self.rx, self.tx = s["rx"], s["tx"]
        self.rx_total, self.tx_total = s["rx_total"], s["tx_total"]
        self.rx_pps, self.tx_pps = s["rx_pps"], s["tx_pps"]
        self.net_errors = s["net_errors"]
        self.freq_mhz = s.get("freq")
        self.conns = s.get("conns")
        self.top_cpu, self.top_mem = s.get("top_cpu") or [], s.get("top_mem") or []
        self.gpus = s["gpus"]
        if s.get("updates") is not None:
            self.profile["updates"] = s["updates"]
        info = s.get("info")
        if info:
            for key in ("os", "kernel", "arch", "cpu_model", "iface"):
                self.profile[key] = info[key]
            self.mac, self.link_speed, self.freq_range = info["mac"], info["link"], info["freq"]
            self.info_known = True
        if s.get("disks"):
            self.disks = s["disks"]
            self.disk_known = True
        self.profile["cores"] = len(self.cores)
        self.profile["mem_gb"] = round(self.mem_info["total"], 1)
        self.profile["uptime"] = s["uptime"]
        self.started = time.monotonic()
        h = self.history
        h["cpu"].append(self.cpu)
        h["mem"].append(self.mem)
        if self.disk_known:
            h["disk"].append(self.disks[0][4])
        h["io"].append(self.io_read + self.io_write)
        h["rx"].append(self.rx)
        h["tx"].append(self.tx)
        if self.gpus:
            h["gpu"].append(sum(g["util"] for g in self.gpus) / len(self.gpus))
        self.last_sample = time.monotonic()
        self.telemetry, self.telemetry_note = "live", ""
        self.sampled_at = datetime.now()

    def _record_check(self, stamp: str, services: list) -> None:
        self.checks += 1
        self.last_check = stamp
        if self.status == "offline":
            self.activity.appendleft((stamp, "Host unreachable", "error"))
            return
        self.activity.appendleft((stamp, "Updated metrics", "info"))
        failed = next((n for n, _, s in services if s == "down"), None)
        if failed:
            self.activity.appendleft((stamp, f"Service check ({failed}) failed", "error"))
        self.activity.appendleft((stamp, "Health check completed", "info"))

    def advance(self, status: str, interval: int, services: list) -> None:
        self.status = status
        now = time.monotonic()
        elapsed, self.last_tick = now - self.last_tick, now
        if self.paused:
            return
        self.countdown = min(self.countdown - elapsed, float(interval))
        if self.countdown <= 0:
            self.countdown = float(interval)
            if not self.live:
                self._record_check(datetime.now().strftime("%H:%M:%S"), services)
        if status != "offline":
            for _ in range(max(1, min(HISTORY_LENGTH, round(elapsed)))):
                self._step_latency()
                self.history["latency"].append(self.latency)
            self.sampled_at = datetime.now()

    def ceiling(self, key: str) -> float:
        floors = {"rx": 1e5, "tx": 1e5, "io": 1e6, "latency": 50.0}
        if key not in floors:
            return 100.0
        return nice_ceiling(max(self.history[key], default=0.0) * 1.05, floors[key])

    def note(self, text: str, level: str = "info") -> None:
        self.activity.appendleft((datetime.now().strftime("%H:%M:%S"), text, level))

    def record_latency(self, value: float) -> None:
        self.latency = float(value)
        self.live_latency = self.latency
        self.history["latency"].append(self.latency)

    def record_probe(self, ok: bool, latency: int | None, error: str | None, interval: int,
                     via: str = "Ping") -> None:
        self.live = True
        self.probe_results.append(ok)
        self.checks += 1
        self.countdown = float(interval)
        stamp = datetime.now().strftime("%H:%M:%S")
        self.last_check = stamp
        if ok:
            self.record_latency(latency)
            self.activity.appendleft((stamp, f"{via} reply in {latency} ms", "info"))
        else:
            self.live_latency = None
            self.activity.appendleft((stamp, error or "Host unreachable", "error"))

    def uptime(self):
        if self.status == "offline" or not self.info_known:
            return None
        return self.profile["uptime"] + time.monotonic() - self.started

    def service_latency(self, name: str, status: str, port: int | None = None):
        from .live import live
        if status not in ("up", "warning"):
            return None
        if live.task is not None:
            return (SERVICE_LIVE.get((self.host, name, port)) or {}).get("latency")
        spread = zlib.crc32(name.encode()) % 9
        value = max(1.0, self.latency * 0.5 + spread + self.rng.gauss(0, 0.8))
        return value * (2.5 if status == "warning" else 1.0)


class MetricsHub:

    def __init__(self):
        self.items = {}

    def get(self, name: str) -> HostMetrics:
        if name not in self.items:
            self.items[name] = HostMetrics(name)
        return self.items[name]

    def drop(self, name: str) -> None:
        self.items.pop(name, None)

    def rename(self, old: str, new: str) -> None:
        if old in self.items:
            self.items[new] = self.items.pop(old)
            self.items[new].host = new


monitor = MetricsHub()


class ServiceMetrics(TelemetryState):

    def __init__(self, host: str, name: str, port: int):
        self.key = (host, name, port)
        self.state = next((s for n, p, s in store.services_of(host) if (n, p) == (name, port)), "pending")
        self.latency = None
        self.history = {k: deque(maxlen=HISTORY_LENGTH) for k in ("conns", "latency", "cpu", "mem")}
        self.checks = deque(maxlen=30)
        self.total_checks = self.passed = 0
        self.started = self.last_tick = time.monotonic()
        self.countdown = float(store.service_details(host, name, port)["interval"])
        self.live = False
        self.seen = False
        self.conns = self.listening = self.proc = None
        self.containers = self.docker_error = None
        known = SERVICE_LIVE.get(self.key)
        if known is not None:
            if known.get("latency") is not None:
                self.latency = float(known["latency"])
            self.live = True

    def advance(self, state: str, interval: int) -> None:
        self.state = state
        now = time.monotonic()
        elapsed, self.last_tick = now - self.last_tick, now
        self.countdown = min(self.countdown - elapsed, float(interval))
        if self.countdown <= 0:
            self.countdown = float(interval)
        if state in ("up", "warning") and self.latency is not None:
            for _ in range(max(1, min(HISTORY_LENGTH, round(elapsed)))):
                self.history["latency"].append(self.latency)

    def record_probe(self, ok: bool, latency: float | None, error: str | None) -> None:
        self.live = True
        self.total_checks += 1
        self.passed += 1 if ok else 0
        self.checks.appendleft((datetime.now().strftime("%H:%M:%S"), ok, latency, error))
        if ok and latency is not None:
            self.latency = float(latency)
            self.history["latency"].append(self.latency)

    def ingest(self, s: dict) -> None:
        if not self.seen:
            self.seen = True
            for key in ("conns", "cpu", "mem"):
                self.history[key].clear()
        self.conns, self.listening, self.proc = s["conns"], s["listening"], s["proc"]
        self.containers, self.docker_error = s["containers"], s["docker_error"]
        if self.conns is not None:
            self.history["conns"].append(self.conns)
        self.history["cpu"].append(self.proc["cpu"] if self.proc else 0.0)
        self.history["mem"].append(self.proc["rss_mb"] if self.proc else 0.0)
        self.last_sample = time.monotonic()
        self.telemetry, self.telemetry_note = "live", ""

    def series(self) -> list[tuple]:
        out = []
        if store.service_details(*self.key)["protocol"] != "UDP":
            out += [("Active connections", "conns", fmt_num), ("Response time", "latency", fmt_ms)]
        out += [("Process CPU", "cpu", fmt_pct), ("Process memory", "mem", fmt_mb)]
        return out

    def ceiling(self, key: str) -> float:
        floors = {"conns": 10.0, "latency": 50.0, "cpu": 10.0, "mem": 64.0}
        return nice_ceiling(max(self.history[key], default=0.0) * 1.05, floors[key])


class ServiceHub:

    def __init__(self):
        self.items = {}

    def get(self, host: str, name: str, port: int) -> ServiceMetrics:
        key = (host, name, port)
        if key not in self.items:
            self.items[key] = ServiceMetrics(host, name, port)
        return self.items[key]

    def drop(self, host: str, name: str, port: int) -> None:
        self.items.pop((host, name, port), None)

    def drop_host(self, host: str) -> None:
        for key in [k for k in self.items if k[0] == host]:
            del self.items[key]

    def rename(self, old: tuple, new: tuple) -> None:
        if old in self.items:
            self.items[new] = self.items.pop(old)
            self.items[new].key = new

    def rename_host(self, old: str, new: str) -> None:
        for key in [k for k in self.items if k[0] == old]:
            self.items[(new,) + key[1:]] = self.items.pop(key)
            self.items[(new,) + key[1:]].key = (new,) + key[1:]


service_monitor = ServiceHub()
