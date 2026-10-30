import asyncio
import re
import shutil
import time

from .constants import (
    DOCKER_SERVICE, SSH_DEFAULT_PORT, SSH_IDLE_SECONDS, SSH_MISSING, SSH_RETRY_SECONDS,
    SSH_STALE_SECONDS, SSH_USER_RE,
)
from .errors import DatabaseError
from .metrics import monitor, service_monitor
from .network import address_kind
from .ssh import SshError, detect_os, ssh_command, ssh_reason
from .state import HOST_DETAILS
from .store import store


VIRTUAL_NICS = ("docker", "veth", "br-", "virbr", "cni", "flannel", "cali")
WHOLE_DISK = re.compile(r"^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme\d+n\d+|mmcblk\d+)$")
TCP_STATES = {"01": "established", "0A": "listen", "06": "time_wait"}
GIB = 1048576.0

PROCESS_HINTS = {
    "ssh": "sshd",
    "postgresql": "postgres",
    "mysql": "mysqld|mariadbd",
    "mongodb": "mongod",
    "redis": "redis-server",
    "nginx": "nginx",
    "https": "nginx|apache2|httpd|caddy",
    "docker": "dockerd",
    "grafana": "grafana",
    "prometheus": "prometheus",
    "kibana": "kibana",
    "elasticsearch": "elasticsearch",
    "logstash": "logstash",
    "rabbitmq": "beam.smp|rabbitmq",
    "dns": "named|unbound|dnsmasq",
    "dhcp": "dhcpd|dnsmasq|kea",
    "ntp": "chronyd|ntpd|systemd-timesyn",
    "mosquitto": "mosquitto",
    "node exporter": "node_exporter",
    "jellyfin": "jellyfin",
    "pi-hole": "pihole-FTL",
}
IGNORED_COMMS = ("grep", "ps", "sh", "head", "awk")
DOCKER_PORT = re.compile(r"(\d+)->(\d+)/(tcp|udp)")

LINUX_SCRIPT = r"""LC_ALL=C
export LC_ALL
HAVE_GPU=0
command -v nvidia-smi >/dev/null 2>&1 && HAVE_GPU=1
FILES=""
for f in /proc/net/tcp /proc/net/tcp6; do [ -r $f ] && FILES="$FILES $f"; done
n=0
while :; do
echo '@up'
read up _ < /proc/uptime
echo "$up"
echo '@stat'
while read l; do case $l in cpu*) echo "$l";; *) break;; esac; done < /proc/stat
echo '@load'
read a b c _ < /proc/loadavg
echo "$a $b $c"
echo '@mem'
while read k v _; do case $k in MemTotal:|MemFree:|MemAvailable:|Buffers:|Cached:|SwapTotal:|SwapFree:) echo "$k $v";; esac; done < /proc/meminfo
echo '@net'
cat /proc/net/dev
echo '@disk'
cat /proc/diskstats
echo '@freq'
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null
if [ $((n % 10)) -eq 0 ]; then
echo '@df'
df -P -k -T 2>/dev/null
fi
if [ $((n % 5)) -eq 0 ]; then
echo '@conn'
awk 'FNR>1{c[$4]++}END{for(k in c)print k,c[k]}' $FILES 2>/dev/null
echo '@pcpu'
ps -eo pid=,pcpu=,pmem=,comm= --sort=-pcpu 2>/dev/null | head -8
echo '@pmem'
ps -eo pid=,pcpu=,pmem=,comm= --sort=-pmem 2>/dev/null | head -8
fi
if [ $HAVE_GPU -eq 1 ] && [ $((n % 2)) -eq 0 ]; then
echo '@gpu'
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits </dev/null 2>/dev/null
fi
if [ $n -eq 0 ]; then
echo '@info'
echo "os=$( [ -r /etc/os-release ] && . /etc/os-release && echo "$PRETTY_NAME")"
echo "kernel=$(uname -r)"
echo "arch=$(uname -m)"
echo "cpu=$(grep -m1 -E '^(model name|Model|Hardware)' /proc/cpuinfo | cut -d: -f2)"
echo "fmin=$(cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_min_freq 2>/dev/null)"
echo "fmax=$(cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq 2>/dev/null)"
for i in /sys/class/net/*; do echo "nic=${i##*/} $(cat $i/address 2>/dev/null) $(cat $i/speed 2>/dev/null)"; done
fi
if [ $n -eq 1 ]; then
echo '@upd'
/usr/lib/update-notifier/apt-check 2>&1 | head -1
fi
echo '@end'
n=$((n+1))
sleep 1
done
"""

SERVICE_SCRIPT = r"""LC_ALL=C
export LC_ALL
FILES=""
if [ "$PROTO" = udp ]; then LIST="/proc/net/udp /proc/net/udp6"; else LIST="/proc/net/tcp /proc/net/tcp6"; fi
for f in $LIST; do [ -r $f ] && FILES="$FILES $f"; done
HEX=$(printf '%04X' "$PORT")
n=0
while :; do
echo '@up'
read up _ < /proc/uptime
echo "$up"
echo '@conn'
awk -v p="$HEX" 'FNR>1{split($2,a,":"); if ((a[2] "") == (p "")) c[$4]++}END{for(k in c)print k,c[k]}' $FILES 2>/dev/null
echo '@proc'
CAND=$(ps -eo pid=,ppid=,etimes=,user=,comm=,args= 2>/dev/null | grep -E -- "$PAT" | head -40)
echo "$CAND"
echo '@pstat'
echo "$CAND" | while read p _; do
if [ -n "$p" ] && [ -r "/proc/$p/stat" ]; then
read -r l < "/proc/$p/stat"
r=${l##*) }
set -- $r
echo "$p ${12} ${13} ${18} ${22}"
fi
done
if [ $DOCKER -eq 1 ]; then
if [ $((n % 2)) -eq 0 ]; then
echo '@dps'
docker ps -a --format '{{.Names}}|{{.Image}}|{{.State}}|{{.Ports}}' 2>&1 | head -40
fi
if [ $((n % 5)) -eq 0 ]; then
echo '@dstats'
docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}' 2>/dev/null | head -40
fi
fi
if [ $n -eq 0 ]; then
echo '@info'
echo "clk=$(getconf CLK_TCK)"
echo "page=$(getconf PAGESIZE)"
read k v _ < /proc/meminfo
echo "memtotal=$v"
fi
echo '@end'
n=$((n+1))
sleep 1
done
"""


def is_docker(name: str) -> bool:
    return name.lower() == DOCKER_SERVICE.lower()


def process_pattern(name: str) -> str:
    hint = PROCESS_HINTS.get(name.lower())
    if hint:
        return hint
    clean = re.sub(r"[^a-z0-9._-]", "", name.lower())
    return clean or "^$"


def to_float(text) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def parse_gpus(lines) -> list[dict]:
    gpus = []
    for line in lines:
        parts = [part.strip() for part in line.rsplit(",", 4)]
        if len(parts) == 5:
            gpus.append({"name": parts[0], "util": to_float(parts[1]), "mem_used": to_float(parts[2]),
                         "mem_total": to_float(parts[3]), "temp": to_float(parts[4])})
    return gpus


def cpu_usage(old: list, new: list) -> tuple[float, float, float, float]:
    delta = [b - a for a, b in zip(old, new)]
    total = sum(delta)
    if total <= 0:
        return 0.0, 0.0, 0.0, 0.0
    idle = delta[3] + delta[4]
    return (100.0 * (total - idle) / total, 100.0 * (delta[0] + delta[1]) / total,
            100.0 * (delta[2] + delta[5] + delta[6]) / total, 100.0 * delta[4] / total)


class SshStream:

    def __init__(self, key: tuple):
        self.key = key
        self.host = key[1]
        self.viewers = 0
        self.idle_since = None
        self.task = None
        self.proc = None
        self.stderr_tail = ""
        self.reset()

    def reset(self) -> None:
        self.prev = None
        self.cache = {}

    def metrics(self):
        raise NotImplementedError

    def script(self) -> str:
        raise NotImplementedError

    def sample(self, sections: dict) -> dict | None:
        raise NotImplementedError

    def target(self):
        details = HOST_DETAILS.get(self.host) or {}
        user, address = details.get("ssh_user"), details.get("address")
        if not user or not address or not SSH_USER_RE.match(user) or address_kind(address) is None:
            return None
        return address, user, details.get("ssh_port") or SSH_DEFAULT_PORT

    def expired(self) -> bool:
        return self.viewers == 0 and self.idle_since is not None \
            and time.monotonic() - self.idle_since > SSH_IDLE_SECONDS

    def ensure(self) -> None:
        metrics = self.metrics()
        if self.target() is None:
            metrics.set_telemetry("none")
            return
        if self.task is None or self.task.done():
            if not metrics.live_data:
                metrics.set_telemetry("connecting")
            self.task = asyncio.create_task(self.run())

    def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            self.task = None

    async def run(self) -> None:
        attempt = 0
        while not self.expired():
            target = self.target()
            metrics = self.metrics()
            if target is None:
                metrics.set_telemetry("none")
                return
            try:
                streamed = await self._session(target, metrics)
            except asyncio.CancelledError:
                raise
            except SshError as error:
                metrics.set_telemetry("error", error.message)
                if error.fatal:
                    return
                streamed = False
            except Exception as error:
                metrics.set_telemetry("error", str(error) or error.__class__.__name__)
                streamed = False
            attempt = 0 if streamed else attempt + 1
            await asyncio.sleep(SSH_RETRY_SECONDS[min(attempt, len(SSH_RETRY_SECONDS) - 1)])
            if not self.expired() and not metrics.live_data:
                metrics.set_telemetry("connecting")
        self.metrics().set_telemetry("idle")

    async def _drain(self, stream) -> None:
        self.stderr_tail = ""
        while True:
            chunk = await stream.read(512)
            if not chunk:
                return
            self.stderr_tail = (self.stderr_tail + chunk.decode(errors="ignore"))[-2000:]

    def parse(self, lines: list) -> dict | None:
        sections, key = {}, None
        for line in lines:
            if line.startswith("@"):
                key = line[1:]
                sections[key] = []
            elif key is not None:
                sections[key].append(line)
        try:
            return self.sample(sections)
        except (ValueError, IndexError, KeyError, ZeroDivisionError):
            return None

    async def _session(self, target: tuple, metrics) -> bool:
        address, user, port = target
        if shutil.which("ssh") is None:
            raise SshError(SSH_MISSING, True)
        details = HOST_DETAILS.get(self.host)
        if not (details and details.get("os_family") == "linux"):
            family = await detect_os(address, user, port)
            if details is not None and HOST_DETAILS.get(self.host) is details:
                details["os_family"] = family
                try:
                    store._queue("update_host_os", self.host, family)
                except DatabaseError:
                    pass
        script = self.script()
        self.reset()
        proc = await asyncio.create_subprocess_exec(
            *ssh_command(address, user, port, "sh -s"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1 << 20,
        )
        self.proc = proc
        errors = asyncio.create_task(self._drain(proc.stderr))
        got, ended = False, "eof"
        block = []
        last = time.monotonic()
        try:
            proc.stdin.write(script.encode())
            await proc.stdin.drain()
            proc.stdin.close()
            while True:
                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(), 5)
                except asyncio.TimeoutError:
                    ended = "stalled"
                    if self.expired():
                        ended = "idle"
                        break
                    if time.monotonic() - last > (SSH_STALE_SECONDS if got else 20):
                        break
                    continue
                if not raw:
                    break
                line = raw.decode("utf-8", "ignore").rstrip("\r\n")
                if line == "@end":
                    sample, block = self.parse(block), []
                    if sample is not None:
                        got = True
                        last = time.monotonic()
                        metrics.ingest(sample)
                else:
                    block.append(line)
                if self.expired():
                    ended = "idle"
                    break
            if ended == "idle":
                return got
            if not got:
                await asyncio.wait({errors}, timeout=2)
                try:
                    code = await asyncio.wait_for(proc.wait(), 2)
                except asyncio.TimeoutError:
                    code = 255
                if not self.stderr_tail.strip() and ended != "eof":
                    raise SshError("No data received from host")
                raise ssh_reason(self.stderr_tail, code)
            metrics.set_telemetry("error", "Connection lost, reconnecting")
            return True
        finally:
            errors.cancel()
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass


class HostCollector(SshStream):

    def metrics(self):
        return monitor.get(self.host)

    def script(self) -> str:
        return LINUX_SCRIPT

    def sample(self, sections: dict) -> dict | None:
        return self._linux_sample(sections)

    def _linux_info(self, lines: list) -> dict:
        info, nics = {}, {}
        for line in lines:
            key, _, value = line.partition("=")
            if key == "nic":
                parts = value.split()
                if parts:
                    speed = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
                    nics[parts[0]] = (parts[1] if len(parts) > 1 else "—", speed)
            else:
                info[key] = value.strip()
        fmin, fmax = info.get("fmin", ""), info.get("fmax", "")
        return {
            "os": info.get("os") or "Linux",
            "kernel": info.get("kernel") or "—",
            "arch": info.get("arch") or "—",
            "cpu_model": " ".join(info.get("cpu", "").split()) or "—",
            "freq": (int(fmin) / 1000, int(fmax) / 1000) if fmin.isdigit() and fmax.isdigit() else None,
            "nics": nics,
        }

    def _linux_disks(self, lines: list) -> list:
        out, seen = [], set()
        for line in lines:
            parts = line.split(None, 6)
            if len(parts) < 7 or not parts[0].startswith("/dev/") or parts[0].startswith("/dev/loop") \
                    or parts[0] in seen:
                continue
            try:
                blocks, used, avail = int(parts[2]), int(parts[3]), int(parts[4])
            except ValueError:
                continue
            seen.add(parts[0])
            pct = used / (used + avail) * 100 if used + avail else 0.0
            out.append([parts[6].strip(), parts[0][5:], parts[1], blocks / GIB, pct])
        out.sort(key=lambda d: (d[0] != "/", d[0]))
        return out

    def _linux_ps(self, lines: list) -> list:
        rows = []
        for line in lines:
            parts = line.split(None, 3)
            if len(parts) == 4:
                try:
                    rows.append((int(parts[0]), parts[3].strip(), float(parts[1]), float(parts[2])))
                except ValueError:
                    continue
        return rows

    def _linux_sample(self, s: dict) -> dict | None:
        cache = self.cache
        if "info" in s:
            cache["info"] = self._linux_info(s["info"])
        if "df" in s:
            cache["disks"] = self._linux_disks(s["df"])
        if "conn" in s:
            counts = {}
            for line in s["conn"]:
                parts = line.split()
                if len(parts) == 2 and parts[0] in TCP_STATES and parts[1].isdigit():
                    name = TCP_STATES[parts[0]]
                    counts[name] = counts.get(name, 0) + int(parts[1])
            cache["conns"] = counts
        if "pcpu" in s:
            cache["top_cpu"] = self._linux_ps(s["pcpu"])
        if "pmem" in s:
            cache["top_mem"] = self._linux_ps(s["pmem"])
        if "gpu" in s:
            cache["gpus"] = parse_gpus(s["gpu"])
        if "upd" in s:
            match = re.fullmatch(r"(\d+);\d+", (s["upd"] or [""])[0].strip())
            cache["updates"] = int(match.group(1)) if match else None
        up = float(s["up"][0])
        cpu = {}
        for line in s["stat"]:
            parts = line.split()
            if parts and parts[0].startswith("cpu"):
                values = [int(v) for v in parts[1:9]]
                cpu[parts[0]] = values + [0] * (8 - len(values))
        mem = {}
        for line in s["mem"]:
            parts = line.split()
            mem[parts[0].rstrip(":")] = int(parts[1])
        per, packets, errors, rx, tx = {}, [0, 0], [0, 0], 0, 0
        for line in s["net"]:
            if ":" not in line:
                continue
            name, data = line.split(":", 1)
            name = name.strip()
            if name == "lo" or name.startswith(VIRTUAL_NICS):
                continue
            f = data.split()
            rx += int(f[0])
            tx += int(f[8])
            packets[0] += int(f[1])
            packets[1] += int(f[9])
            errors[0] += int(f[2]) + int(f[3])
            errors[1] += int(f[10]) + int(f[11])
            per[name] = int(f[0]) + int(f[8])
        rd = wr = 0
        for line in s["disk"]:
            f = line.split()
            if len(f) > 9 and WHOLE_DISK.match(f[2]):
                rd += int(f[5])
                wr += int(f[9])
        now = {"up": up, "cpu": cpu, "rx": rx, "tx": tx, "pk": packets, "rd": rd, "wr": wr}
        prev, self.prev = self.prev, now
        info = cache.pop("info", None)
        if info is not None and per:
            iface = max(per, key=per.get)
            mac, speed = info.pop("nics", {}).get(iface, ("—", None))
            info.update(iface=iface, mac=mac, link=speed)
        elif info is not None:
            info.pop("nics", None)
            info.update(iface="—", mac="—", link=None)
        if info is not None:
            cache["pending_info"] = info
        if prev is None:
            return None
        dt = up - prev["up"]
        if dt <= 0:
            return None
        usage = cpu_usage(prev["cpu"]["cpu"], cpu["cpu"])
        names = sorted((k for k in cpu if k != "cpu" and k in prev["cpu"]), key=lambda k: int(k[3:]))
        cores, split = [], []
        for name in names:
            c = cpu_usage(prev["cpu"][name], cpu[name])
            cores.append(c[0])
            split.append((c[1], c[2], c[3]))
        total = mem["MemTotal"]
        available = mem.get("MemAvailable", mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0))
        freqs = [int(v) for v in s.get("freq", []) if v.strip().isdigit()]

        def per_second(new: float, old: float) -> float:
            return max(0.0, (new - old) / dt)

        return {
            "cpu": usage[0], "cores": cores, "core_split": split,
            "load": [float(v) for v in s["load"][0].split()[:3]],
            "mem": (total - available) / total * 100,
            "mem_info": {"total": total / GIB, "available": available / GIB,
                         "cache": mem.get("Cached", 0) / GIB, "buffers": mem.get("Buffers", 0) / GIB,
                         "swap_total": mem.get("SwapTotal", 0) / GIB, "swap_free": mem.get("SwapFree", 0) / GIB},
            "io_read": per_second(rd, prev["rd"]) * 512, "io_write": per_second(wr, prev["wr"]) * 512,
            "rx": per_second(rx, prev["rx"]), "tx": per_second(tx, prev["tx"]),
            "rx_total": float(rx), "tx_total": float(tx),
            "rx_pps": per_second(packets[0], prev["pk"][0]), "tx_pps": per_second(packets[1], prev["pk"][1]),
            "net_errors": (errors[0], errors[1]),
            "uptime": up,
            "freq": sum(freqs) / len(freqs) / 1000 if freqs else None,
            "disks": cache.get("disks"),
            "conns": cache.get("conns"),
            "top_cpu": cache.get("top_cpu"), "top_mem": cache.get("top_mem"),
            "gpus": cache.get("gpus", []),
            "updates": cache.get("updates"),
            "info": cache.pop("pending_info", None),
        }


class ServiceCollector(SshStream):

    def metrics(self):
        return service_monitor.get(*self.key[1:])

    def target(self):
        _, host, name, port = self.key
        if not any((n, p) == (name, port) for n, p, _ in store.services_of(host)):
            return None
        return super().target()

    def script(self) -> str:
        _, host, name, port = self.key
        protocol = store.service_details(host, name, port)["protocol"]
        pattern = process_pattern(name)
        self.pattern = re.compile(pattern)
        header = (f"PORT={int(port)}\nPROTO={'udp' if protocol == 'UDP' else 'tcp'}\n"
                  f"PAT='{pattern}'\nDOCKER={1 if is_docker(name) else 0}\n")
        return header + SERVICE_SCRIPT

    def _containers(self, cache: dict, s: dict) -> None:
        if "dps" in s:
            rows = [line for line in s["dps"] if line.strip()]
            if any("|" not in line for line in rows):
                cache["docker_error"] = rows[0].strip()[:100]
                cache["dps"] = []
            else:
                cache["docker_error"] = None
                parsed = []
                for line in rows:
                    parts = line.split("|", 3)
                    if len(parts) < 4:
                        continue
                    name, image, state, ports = parts
                    state = state.strip().lower()
                    state = state if state in ("running", "restarting") else "stopped"
                    seen, services = set(), []
                    for host_port, inner, proto in DOCKER_PORT.findall(ports):
                        if (host_port, inner, proto) not in seen:
                            seen.add((host_port, inner, proto))
                            services.append((f"{inner}/{proto}", int(host_port), "up" if state == "running" else "down"))
                    parsed.append({"name": name, "image": image, "state": state, "services": services})
                cache["dps"] = parsed
        if "dstats" in s:
            stats = {}
            for line in s["dstats"]:
                parts = line.split("|")
                if len(parts) == 3:
                    stats[parts[0]] = (to_float(parts[1].strip("% ")), to_float(parts[2].strip("% ")))
            cache["dstats"] = stats

    def sample(self, s: dict) -> dict | None:
        cache = self.cache
        if "info" in s:
            info = {}
            for line in s["info"]:
                key, _, value = line.partition("=")
                info[key] = value.strip()
            cache["clk"] = int(info.get("clk") or 100)
            cache["page"] = int(info.get("page") or 4096)
            cache["memtotal_mb"] = int(info.get("memtotal") or 0) / 1024
        self._containers(cache, s)
        up = float(s["up"][0])
        counts = {}
        for line in s.get("conn", []):
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                counts[parts[0]] = int(parts[1])
        candidates = {}
        for line in s.get("proc", []):
            parts = line.split(None, 5)
            if len(parts) < 5 or parts[4] in IGNORED_COMMS:
                continue
            try:
                pid, etimes = int(parts[0]), int(parts[2])
            except ValueError:
                continue
            args = parts[5] if len(parts) > 5 else ""
            if self.pattern.search(f"{parts[4]} {args}"):
                candidates[pid] = (etimes, parts[3], parts[4])
        ticks = {}
        for line in s.get("pstat", []):
            parts = line.split()
            if len(parts) == 5 and parts[0].isdigit() and int(parts[0]) in candidates:
                try:
                    ticks[int(parts[0])] = (int(parts[1]) + int(parts[2]), int(parts[3]), int(parts[4]))
                except ValueError:
                    continue
        prev, self.prev = self.prev, {"up": up, "ticks": {pid: t[0] for pid, t in ticks.items()}}
        if prev is None:
            return None
        dt = up - prev["up"]
        if dt <= 0:
            return None
        clk, page, memtotal = cache.get("clk", 100), cache.get("page", 4096), cache.get("memtotal_mb", 0.0)
        proc = None
        if ticks:
            main = max(ticks, key=lambda pid: candidates[pid][0])
            cpu = sum(max(0, t[0] - prev["ticks"].get(pid, t[0])) for pid, t in ticks.items()) / clk / dt * 100
            rss_mb = sum(t[2] for t in ticks.values()) * page / 1048576
            proc = {"pid": main, "name": candidates[main][2], "user": candidates[main][1],
                    "count": len(ticks), "cpu": cpu, "rss_mb": rss_mb,
                    "mem_pct": rss_mb / memtotal * 100 if memtotal else 0.0,
                    "threads": sum(t[1] for t in ticks.values()), "uptime": float(candidates[main][0])}
        udp = store.service_details(*self.key[1:])["protocol"] == "UDP"
        containers = None
        if "dps" in cache:
            stats = cache.get("dstats", {})
            containers = [dict(c, cpu=stats.get(c["name"], (None, None))[0], mem=stats.get(c["name"], (None, None))[1])
                          for c in cache["dps"]]
        return {
            "conns": None if udp else counts.get("01", 0),
            "listening": sum(counts.values()) > 0 if udp else counts.get("0A", 0) > 0,
            "proc": proc,
            "containers": containers,
            "docker_error": cache.get("docker_error"),
        }


class CollectorHub:

    def __init__(self):
        self.items = {}

    def active(self, key: tuple) -> bool:
        return key in self.items

    def acquire(self, key: tuple) -> None:
        item = self.items.get(key)
        if item is None:
            item = self.items[key] = (HostCollector if key[0] == "host" else ServiceCollector)(key)
        item.viewers += 1
        item.idle_since = None
        item.ensure()

    def release(self, key: tuple) -> None:
        item = self.items.get(key)
        if item is not None:
            item.viewers = max(0, item.viewers - 1)
            if not item.viewers:
                item.idle_since = time.monotonic()

    def restart(self, key: tuple) -> None:
        item = self.items.get(key)
        if item is not None:
            item.stop()
            item.ensure()

    def drop(self, key: tuple) -> None:
        item = self.items.pop(key, None)
        if item is not None:
            item.stop()

    def drop_host(self, host: str) -> None:
        for key in [k for k in self.items if k[1] == host]:
            self.drop(key)


collectors = CollectorHub()
