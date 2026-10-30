import time
from collections import deque
from datetime import datetime
from functools import wraps

from .config import APP_STATUS, DB_CONFIG, DB_STATUS, SERVICE_APP_STATUS, SERVICE_DB_STATUS
from .constants import FLAP_CONFIRM, FLAP_LIMIT, FLAP_WINDOW, REFRESH_SECONDS, SERVICE_PRESETS, THRESHOLDS
from .crypto import decrypt_secret, is_encrypted
from .db import DbWriter, HostDatabase
from .errors import SecretError
from .helpers import ago, interval_label, local_now
from .network import normalize_address
from .state import (
    HOSTS, HOST_DETAILS, LOGS, SERVICES, SERVICE_ACCESS, SERVICE_DETAILS, SERVICE_LIVE, trim_logs,
)


def transactional(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self.persistent:
            return method(self, *args, **kwargs)
        with self.db.transaction():
            return method(self, *args, **kwargs)
    return wrapper


class InMemoryHostStore:

    def __init__(self):
        self.db = HostDatabase(DB_CONFIG)
        self.writer = None
        self.persistent = False
        self.streaks = {}
        self.flaps = {}
        self.flapping = set()
        self.unreadable = 0

    def _confirmed(self, key: tuple, status: str) -> bool:
        streak = self.streaks.get(key)
        count = streak[1] + 1 if streak and streak[0] == status else 1
        if count >= FLAP_CONFIRM:
            self.streaks.pop(key, None)
            return True
        self.streaks[key] = (status, count)
        return False

    def _verdict(self, key: tuple, status: str, old: str):
        if status in ("offline", "down") or old in ("offline", "down", "pending"):
            self.flapping.discard(key)
            self.flaps.pop(key, None)
            return True
        now = time.monotonic()
        times = self.flaps.setdefault(key, deque())
        times.append(now)
        while times and now - times[0] > FLAP_WINDOW:
            times.popleft()
        if len(times) < FLAP_LIMIT:
            self.flapping.discard(key)
            return True
        if key in self.flapping:
            return False
        self.flapping.add(key)
        return "flap"

    def start_writer(self, on_error) -> None:
        if self.writer is None and self.persistent:
            self.writer = DbWriter(DB_CONFIG, on_error)

    def stop_writer(self) -> None:
        if self.writer is not None:
            self.writer.stop()
            self.writer = None

    def _queue(self, method: str, *args, **kwargs) -> None:
        if self.writer is not None:
            self.writer.submit(method, *args, **kwargs)
        elif self.persistent:
            getattr(self.db, method)(*args, **kwargs)

    def load(self) -> None:
        self.db.upgrade()
        self.db.prune_logs()
        rows = self.db.hosts()
        service_rows = self.db.services()
        log_rows = self.db.logs()
        SERVICE_LIVE.clear()
        SERVICE_ACCESS.clear()
        for host, name, port, total, passed, since, latency in self.db.service_stats():
            SERVICE_LIVE[(host, name, port)] = {
                "latency": latency, "total": total, "passed": passed, "since": since,
            }
        self.persistent = True
        grouped, service_info = {}, {}
        self.unreadable = 0
        for host, name, port, db_status, protocol, interval, description, cred_user, cred_password, cred_visible in service_rows:
            password = None
            if cred_password:
                try:
                    password = decrypt_secret(cred_password)
                    if not is_encrypted(cred_password):
                        self.db.update_service_access(host, name, port, cred_user or None, password, bool(cred_visible))
                except SecretError:
                    self.unreadable += 1
            if cred_user or password:
                SERVICE_ACCESS[(host, name, port)] = {
                    "username": cred_user or None, "password": password, "visible": bool(cred_visible),
                }
            grouped.setdefault(host, []).append((name, port, SERVICE_APP_STATUS.get(db_status, "pending")))
            service_info[(host, name, port)] = {
                "protocol": protocol,
                "interval": interval,
                "description": description or "",
            }
        hosts, details, services = [], {}, []
        for name, address, description, db_status, latency, last_seen, interval, ssh_user, ssh_port, family in rows:
            status = APP_STATUS.get(db_status, "offline")
            host_services = grouped.get(name, [])
            up = sum(1 for _, _, state in host_services if state == "up")
            hosts.append((name, status, up, len(host_services), ago(last_seen), latency))
            details[name] = {"address": address, "description": description or "",
                             "ssh_user": ssh_user or None, "ssh_port": ssh_port, "os_family": family}
            if interval:
                details[name]["interval"] = interval
            if last_seen is not None:
                details[name]["seen"] = last_seen
            services.append((name, status, host_services))
        HOSTS[:] = hosts
        HOST_DETAILS.clear()
        HOST_DETAILS.update(details)
        SERVICES[:] = services
        SERVICE_DETAILS.clear()
        SERVICE_DETAILS.update(service_info)
        LOGS[:] = [
            (moment.astimezone().strftime("%H:%M:%S"), kind, text, host, level.lower(), service)
            for moment, kind, text, host, level, service in log_rows
        ]

    def all(self) -> list[tuple]:
        return HOSTS

    def name_taken(self, name: str, ignore: str | None = None) -> bool:
        return any(h[0].lower() == name.lower() and h[0] != ignore for h in HOSTS)

    def address_owner(self, address: str, ignore: str | None = None) -> str | None:
        wanted = normalize_address(address)
        for name, details in HOST_DETAILS.items():
            if name != ignore and normalize_address(details["address"]) == wanted:
                return name
        return None

    def details(self, name: str) -> dict:
        return HOST_DETAILS.get(name, {"address": "", "description": ""})

    def host(self, name: str) -> tuple | None:
        return next((h for h in HOSTS if h[0] == name), None)

    def services_of(self, name: str) -> list[tuple]:
        for host, _, services in SERVICES:
            if host == name:
                return list(services)
        return []

    def monitor_interval(self, name: str) -> int:
        saved = HOST_DETAILS.get(name, {}).get("interval")
        if saved:
            return saved
        intervals = [
            SERVICE_DETAILS.get((name, n, p), {}).get("interval", REFRESH_SECONDS)
            for n, p, _ in self.services_of(name)
        ]
        return min(intervals) if intervals else REFRESH_SECONDS

    @transactional
    def set_host_interval(self, name: str, seconds: int) -> None:
        if self.persistent:
            self.db.update_host_interval(name, seconds)
        details = HOST_DETAILS.setdefault(name, {"address": "", "description": ""})
        details["interval"] = seconds
        self._log(f"Monitoring interval of {name} set to {interval_label(seconds)}", name)

    @transactional
    def set_service_interval(self, host: str, name: str, port: int, seconds: int) -> None:
        if self.persistent:
            self.db.update_service_interval(host, name, port, seconds)
        SERVICE_DETAILS[(host, name, port)] = {**self.service_details(host, name, port), "interval": seconds}
        self._record("SERVICE", f"{{service}} interval set to {interval_label(seconds)}", host, "info", name)

    def service_access(self, host: str, name: str, port: int) -> dict:
        return dict(SERVICE_ACCESS.get((host, name, port)) or {"username": None, "password": None, "visible": False})

    @transactional
    def set_service_access(self, host: str, name: str, port: int, username: str | None,
                           password: str | None, visible: bool) -> None:
        if self.persistent:
            self.db.update_service_access(host, name, port, username, password, visible)
        if username is None and password is None:
            SERVICE_ACCESS.pop((host, name, port), None)
            text = "{service} credentials removed"
        else:
            SERVICE_ACCESS[(host, name, port)] = {"username": username, "password": password, "visible": visible}
            text = "{service} credentials updated"
        self._record("SERVICE", text, host, "info", name)

    def service_count(self, name: str) -> int:
        return sum(len(s[2]) for s in SERVICES if s[0] == name)

    def service_catalog(self) -> list[tuple]:
        catalog = {name: (port, protocol) for name, port, protocol in SERVICE_PRESETS}
        for host, _, services in SERVICES:
            for name, port, _status in services:
                if name not in catalog:
                    protocol = SERVICE_DETAILS.get((host, name, port), {}).get("protocol", "TCP")
                    catalog[name] = (port, protocol)
        return sorted(((n, p, proto) for n, (p, proto) in catalog.items()), key=lambda c: c[0].lower())

    def port_owner(self, host: str, port: int, protocol: str,
                   ignore: tuple | None = None) -> str | None:
        transport = "udp" if protocol == "UDP" else "tcp"
        for entry in SERVICES:
            if entry[0] != host:
                continue
            for name, used_port, _status in entry[2]:
                if used_port != port or (host, name, used_port) == ignore:
                    continue
                other = SERVICE_DETAILS.get((host, name, used_port), {}).get("protocol", "TCP")
                if ("udp" if other == "UDP" else "tcp") == transport:
                    return name
        return None

    @transactional
    def add_service(self, host: str, name: str, port: int, protocol: str,
                    interval: int, description: str) -> None:
        if self.persistent:
            self.db.insert_service(host, name, port, protocol, interval, description,
                                   SERVICE_DB_STATUS["pending"])
        for entry in SERVICES:
            if entry[0] == host:
                entry[2].append((name, port, "pending"))
                break
        else:
            SERVICES.append((host, "offline", [(name, port, "pending")]))
        SERVICE_DETAILS[(host, name, port)] = {
            "protocol": protocol,
            "interval": interval,
            "description": description,
        }
        for i, h in enumerate(HOSTS):
            if h[0] == host:
                HOSTS[i] = h[:3] + (h[3] + 1,) + h[4:]
        self._record("SERVICE", "{service} added", host, "info", name)

    @transactional
    def remove_service(self, host: str, name: str, port: int) -> None:
        from .metrics import service_monitor
        from .collectors import collectors
        if self.persistent:
            self.db.delete_service(host, name, port)
        status = None
        for entry in SERVICES:
            if entry[0] == host:
                for i, (n, p, s) in enumerate(entry[2]):
                    if (n, p) == (name, port):
                        status = s
                        entry[2].pop(i)
                        break
                break
        if status is None:
            return
        SERVICE_DETAILS.pop((host, name, port), None)
        SERVICE_ACCESS.pop((host, name, port), None)
        SERVICE_LIVE.pop((host, name, port), None)
        service_monitor.drop(host, name, port)
        collectors.drop(("service", host, name, port))
        for i, h in enumerate(HOSTS):
            if h[0] == host:
                up = max(0, h[2] - 1) if status == "up" else h[2]
                HOSTS[i] = (h[0], h[1], up, max(0, h[3] - 1)) + h[4:]
        still_used = any(
            n == name for entry in SERVICES if entry[0] == host for n, _, _ in entry[2]
        )
        if not still_used:
            LOGS[:] = [e for e in LOGS if (e[3], e[5]) != (host, name)]
        self._record("SERVICE", "{service} removed", host, "info", name)

    def service_details(self, host: str, name: str, port: int) -> dict:
        return SERVICE_DETAILS.get(
            (host, name, port),
            {"protocol": "TCP", "interval": 5, "description": ""},
        )

    @transactional
    def update_service(self, original: tuple, host: str, name: str, port: int,
                       protocol: str, interval: int, description: str) -> None:
        from .metrics import service_monitor
        from .collectors import collectors
        old_host, old_name, old_port = original
        saved = self.service_details(old_host, old_name, old_port)
        new_details = {"protocol": protocol, "interval": interval, "description": description}
        if (host, name, port) == original and new_details == saved:
            return
        if self.persistent:
            self.db.update_service(original, host, name, port, protocol, interval, description)
        status, position = "pending", None
        for entry in SERVICES:
            if entry[0] == old_host:
                for i, (n, p, s) in enumerate(entry[2]):
                    if (n, p) == (old_name, old_port):
                        status, position = s, i
                        entry[2].pop(i)
                        break
                break
        target = next((e for e in SERVICES if e[0] == host), None)
        if target is None:
            target = (host, "offline", [])
            SERVICES.append(target)
        if host == old_host and position is not None:
            target[2].insert(position, (name, port, status))
        else:
            target[2].append((name, port, status))
        SERVICE_DETAILS.pop(original, None)
        SERVICE_DETAILS[(host, name, port)] = new_details
        service_monitor.rename(original, (host, name, port))
        collectors.drop(("service",) + original)
        if original in SERVICE_ACCESS:
            SERVICE_ACCESS[(host, name, port)] = SERVICE_ACCESS.pop(original)
        if original in SERVICE_LIVE:
            SERVICE_LIVE[(host, name, port)] = SERVICE_LIVE.pop(original)
        if host != old_host:
            for i, h in enumerate(HOSTS):
                if h[0] == old_host:
                    HOSTS[i] = h[:3] + (max(0, h[3] - 1),) + h[4:]
                elif h[0] == host:
                    HOSTS[i] = h[:3] + (h[3] + 1,) + h[4:]
        elif name != old_name:
            LOGS[:] = [
                e[:5] + (name,) if (e[3], e[5]) == (old_host, old_name) else e
                for e in LOGS
            ]
        text = f"{{service}} moved from {old_host}" if host != old_host else "{service} edited"
        self._record("SERVICE", text, host, "info", name)

    def _record(self, kind: str, text: str, host: str, level: str = "info",
                service: str | None = None) -> None:
        if self.persistent:
            if self.db.cursor is not None:
                self.db.insert_log(kind, text, host, level, service, local_now())
            else:
                self._queue("insert_log", kind, text, host, level, service, local_now(), require_host=True)
        LOGS.insert(0, (datetime.now().strftime("%H:%M:%S"), kind, text, host, level, service))
        trim_logs()

    def _log(self, text: str, host: str, level: str = "info") -> None:
        self._record("USER", text, host, level)

    def apply_host_result(self, name: str, reachable: bool, latency: int | None) -> None:
        current = self.host(name)
        if current is None:
            return
        old = current[1]
        if not reachable:
            status = "offline"
        elif latency >= THRESHOLDS["latency"][0]:
            status = "warning"
        else:
            status = "online"
        if old in ("online", "warning") and status in ("online", "warning") and status != old:
            if not self._confirmed(("host", name), status):
                status = old
        else:
            self.streaks.pop(("host", name), None)
        self._queue("update_host_state", name, DB_STATUS[status], latency, reachable)
        details = HOST_DETAILS.setdefault(name, {"address": "", "description": ""})
        if reachable:
            details["seen"] = local_now()
        updated = ago(details.get("seen"))
        for i, h in enumerate(HOSTS):
            if h[0] == name:
                HOSTS[i] = (name, status, h[2], h[3], updated, latency)
                break
        SERVICES[:] = [(name, status, s[2]) if s[0] == name else s for s in SERVICES]
        if status != old:
            text, level = {
                "online": (f"{name} online", "info"),
                "warning": (f"{name} high latency", "warning"),
                "offline": (f"{name} offline", "error"),
            }[status]
            verdict = self._verdict(("host", name), status, old)
            if verdict == "flap":
                self._record("HOST", f"{name} unstable, status keeps changing", name, "warning")
            elif verdict:
                self._record("HOST", text, name, level)

    def apply_service_result(self, host: str, name: str, port: int, ok: bool,
                             latency: float | None, extra: dict | None = None) -> None:
        extra = extra or {}
        entry = next((e for e in SERVICES if e[0] == host), None)
        position = None
        if entry is not None:
            position = next((i for i, (n, p, _) in enumerate(entry[2]) if (n, p) == (name, port)), None)
        if position is None:
            return
        old = entry[2][position][2]
        http = extra.get("http")
        if not ok:
            status = "down"
        elif latency >= THRESHOLDS["latency"][0] or (http and http[0] >= 500):
            status = "warning"
        else:
            status = "up"
        if old in ("up", "warning") and status in ("up", "warning") and status != old:
            if not self._confirmed(("service", host, name, port), status):
                status = old
        else:
            self.streaks.pop(("service", host, name, port), None)
        self._queue("update_service_state", host, name, port, SERVICE_DB_STATUS[status], latency, ok)
        entry[2][position] = (name, port, status)
        stats = SERVICE_LIVE.setdefault(
            (host, name, port), {"latency": None, "total": 0, "passed": 0, "since": None}
        )
        stats["latency"] = latency
        stats["total"] += 1
        stats["passed"] += 1 if ok else 0
        if status != old or stats["since"] is None:
            stats["since"] = local_now()
        stats["error"] = None if ok else extra.get("error")
        if ok:
            stats["http"] = extra.get("http")
            stats["cert_days"] = extra.get("cert_days")
            stats["banner"] = extra.get("banner")
        up = sum(1 for _, _, s in entry[2] if s == "up")
        for i, h in enumerate(HOSTS):
            if h[0] == host:
                HOSTS[i] = h[:2] + (up,) + h[3:]
                break
        if status != old:
            text, level = {
                "up": ("{service} running", "info"),
                "warning": ("{service} degraded", "warning"),
                "down": ("{service} stopped", "error"),
            }[status]
            verdict = self._verdict(("service", host, name, port), status, old)
            if verdict == "flap":
                self._record("SERVICE", "{service} unstable, status keeps changing", host, "warning", name)
            elif verdict:
                self._record("SERVICE", text, host, level, name)

    def refresh_ages(self) -> None:
        for i, h in enumerate(HOSTS):
            seen = HOST_DETAILS.get(h[0], {}).get("seen")
            if seen is not None:
                text = ago(seen)
                if text != h[4]:
                    HOSTS[i] = h[:4] + (text,) + h[5:]

    def record_host_check(self, name: str, latency: int) -> None:
        self._queue("update_host_check", name, latency)
        for i, h in enumerate(HOSTS):
            if h[0] == name:
                HOSTS[i] = (name, "online", h[2], h[3], "just now", latency)
                break
        SERVICES[:] = [(name, "online", s[2]) if s[0] == name else s for s in SERVICES]

    def record_service_check(self, host: str, name: str, port: int, latency: float | None) -> None:
        self._queue("update_service_check", host, name, port, latency)

    @transactional
    def update(self, original: str, name: str, address: str, description: str,
               latency: int | None = None, reachable: bool = False,
               ssh_user: str | None = None, ssh_port: int | None = None) -> None:
        from .metrics import monitor, service_monitor
        from .collectors import collectors
        address = normalize_address(address)
        saved = self.details(original)
        ssh_same = (ssh_user, ssh_port) == (saved.get("ssh_user"), saved.get("ssh_port"))
        if (name, address, description) == (original, saved["address"], saved["description"]) \
                and ssh_same and not reachable:
            return
        family = saved.get("os_family") if ssh_same and address == saved["address"] else None
        if self.persistent:
            current = self.host(original)
            status = "online" if reachable else (current[1] if current else "offline")
            self.db.update_host(original, name, address, description, DB_STATUS[status], latency, reachable)
            self.db.update_host_ssh(name, ssh_user, ssh_port, family)
        for i, h in enumerate(HOSTS):
            if h[0] == original:
                if reachable:
                    HOSTS[i] = (name, "online", h[2], h[3], "just now", latency)
                else:
                    HOSTS[i] = (name,) + h[1:]
                break
        HOST_DETAILS.pop(original, None)
        HOST_DETAILS[name] = {"address": address, "description": description,
                              "ssh_user": ssh_user, "ssh_port": ssh_port, "os_family": family}
        if name != original or address != saved["address"] or not ssh_same:
            collectors.drop_host(original)
        if "interval" in saved:
            HOST_DETAILS[name]["interval"] = saved["interval"]
        if reachable:
            HOST_DETAILS[name]["seen"] = local_now()
        elif "seen" in saved:
            HOST_DETAILS[name]["seen"] = saved["seen"]
        SERVICES[:] = [
            (name, "online" if reachable else s[1], s[2]) if s[0] == original else s
            for s in SERVICES
        ]
        if name != original:
            monitor.rename(original, name)
            service_monitor.rename_host(original, name)
            for key in [k for k in SERVICE_ACCESS if k[0] == original]:
                SERVICE_ACCESS[(name,) + key[1:]] = SERVICE_ACCESS.pop(key)
            for key in [k for k in SERVICE_LIVE if k[0] == original]:
                SERVICE_LIVE[(name,) + key[1:]] = SERVICE_LIVE.pop(key)
            for key in [k for k in SERVICE_DETAILS if k[0] == original]:
                SERVICE_DETAILS[(name,) + key[1:]] = SERVICE_DETAILS.pop(key)
            LOGS[:] = [e[:3] + (name,) + e[4:] if e[3] == original else e for e in LOGS]
            self._log(f"Renamed host {original} to {name}", name)
        else:
            self._log(f"Edited host {name}", name)

    @transactional
    def add(self, name: str, address: str, description: str,
            latency: int | None = None, reachable: bool = False,
            ssh_user: str | None = None, ssh_port: int | None = None) -> None:
        address = normalize_address(address)
        status = "online" if reachable else "offline"
        if self.persistent:
            self.db.insert_host(name, address, description, DB_STATUS[status],
                                latency if reachable else None, local_now() if reachable else None)
            if ssh_user:
                self.db.update_host_ssh(name, ssh_user, ssh_port)
        HOSTS.append((name, status, 0, 0, "just now" if reachable else "never", latency))
        HOST_DETAILS[name] = {"address": address, "description": description,
                              "ssh_user": ssh_user, "ssh_port": ssh_port, "os_family": None}
        if reachable:
            HOST_DETAILS[name]["seen"] = local_now()
        SERVICES.append((name, status, []))
        self._log(f"Added host {name}", name)

    @transactional
    def remove(self, name: str) -> None:
        from .metrics import monitor, service_monitor
        from .collectors import collectors
        if self.persistent:
            self.db.delete_host(name)
        HOSTS[:] = [h for h in HOSTS if h[0] != name]
        monitor.drop(name)
        collectors.drop_host(name)
        service_monitor.drop_host(name)
        HOST_DETAILS.pop(name, None)
        SERVICES[:] = [s for s in SERVICES if s[0] != name]
        for key in [k for k in SERVICE_DETAILS if k[0] == name]:
            del SERVICE_DETAILS[key]
        for key in [k for k in SERVICE_LIVE if k[0] == name]:
            del SERVICE_LIVE[key]
        LOGS[:] = [e for e in LOGS if e[3] != name]
        self._log(f"Removed host {name}", name)


store = InMemoryHostStore()
