import asyncio
import random
import time

from .constants import (
    LIVE_ALIVE_MIN_SECONDS, LIVE_CONCURRENCY, LIVE_DB_RETRY_SECONDS, LIVE_FAIL_THRESHOLD,
    LIVE_RETRY_SECONDS,
)
from .errors import DatabaseError
from .metrics import monitor, service_monitor
from .network import PING_MISSING, new_probe, probe_host, probe_service_details
from .state import SERVICES
from .store import store


class LiveMonitor:

    def __init__(self):
        self.due = {}
        self.fails = {}
        self.alive = {}
        self.active = set()
        self.tasks = set()
        self.slots = None
        self.task = None
        self.on_change = None
        self.on_error = None
        self.last_error = None
        self.hold_until = 0.0

    def start(self, on_change, on_error) -> None:
        if self.task is not None:
            return
        self.on_change, self.on_error = on_change, on_error
        self.slots = asyncio.Semaphore(LIVE_CONCURRENCY)
        self.task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            self.task = None
        for task in list(self.tasks):
            task.cancel()
        self.tasks.clear()
        self.active.clear()

    def fresh_alive(self, name: str) -> float | None:
        seen = self.alive.get(name)
        if seen is None:
            return None
        if time.monotonic() - seen[0] > max(LIVE_ALIVE_MIN_SECONDS, 2.0 * store.monitor_interval(name)):
            return None
        return seen[1]

    def _report(self, message: str) -> None:
        if message != self.last_error:
            self.last_error = message
            self.on_error(message)

    def _db_failed(self, error) -> None:
        self.hold_until = time.monotonic() + LIVE_DB_RETRY_SECONDS
        self._report(f"Database error: {error}. Live updates paused for {LIVE_DB_RETRY_SECONDS}s")

    async def _loop(self) -> None:
        while True:
            try:
                self._schedule()
                store.refresh_ages()
                self.on_change()
            except Exception as error:
                self._report(str(error) or error.__class__.__name__)
            await asyncio.sleep(1)

    def _launch(self, key: tuple, now: float, interval: int, runner, *args) -> None:
        due = min(self.due.setdefault(key, now + random.uniform(0.2, 2.5)), now + interval)
        self.due[key] = due
        if now < due or key in self.active:
            return
        self.due[key] = now + interval
        self.active.add(key)
        task = asyncio.create_task(runner(key, *args))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _schedule(self) -> None:
        now = time.monotonic()
        valid = set()
        for name, *_ in list(store.all()):
            address = store.details(name)["address"]
            item = monitor.items.get(name)
            if not address or (item is not None and item.paused):
                continue
            key = ("host", name)
            valid.add(key)
            self._launch(key, now, store.monitor_interval(name), self._check_host, name, address)
        for host, _, services in list(SERVICES):
            address = store.details(host)["address"]
            item = monitor.items.get(host)
            if not address or (item is not None and item.paused):
                continue
            for name, port, _state in list(services):
                info = store.service_details(host, name, port)
                if info["protocol"] == "UDP":
                    continue
                key = ("service", host, name, port)
                valid.add(key)
                self._launch(key, now, info["interval"], self._check_service,
                             host, name, port, address, info["protocol"])
        for key in [k for k in self.due if k not in valid]:
            del self.due[key]
        for key in [k for k in self.fails if k not in valid]:
            del self.fails[key]
        for name in [n for n in self.alive if store.host(n) is None]:
            del self.alive[name]

    async def _check_host(self, key: tuple, name: str, address: str) -> None:
        try:
            async with self.slots:
                try:
                    _, latency, error = await probe_host(address)
                except Exception:
                    latency, error = None, "The check could not be completed"
            self._apply_host(name, address, latency, error)
        finally:
            self.active.discard(key)

    def _apply_host(self, name: str, address: str, latency: float | None, error: str | None) -> None:
        now = time.monotonic()
        via = "Ping"
        if error is not None:
            tcp = self.fresh_alive(name)
            if tcp is not None:
                latency, error, via = tcp, None, "TCP"
            elif error == PING_MISSING:
                self._report("ping is not available on this system, host checks rely on service probes")
                return
        if now < self.hold_until:
            return
        current = store.host(name)
        if current is None or store.details(name)["address"] != address:
            return
        key = ("host", name)
        reachable = error is None
        if reachable:
            self.fails.pop(key, None)
        else:
            streak = self.fails.get(key, 0) + 1
            self.fails[key] = streak
            if current[1] != "offline" and streak < LIVE_FAIL_THRESHOLD:
                self.due[key] = now + LIVE_RETRY_SECONDS
                return
        ms = max(1, round(latency)) if reachable else None
        try:
            store.apply_host_result(name, reachable, ms)
        except DatabaseError as exc:
            self._db_failed(exc)
            return
        self.last_error = None
        item = monitor.items.get(name)
        if item is not None:
            item.record_probe(reachable, ms, error, store.monitor_interval(name), via)
        self.on_change()

    async def _check_service(self, key: tuple, host: str, name: str, port: int,
                             address: str, protocol: str) -> None:
        try:
            async with self.slots:
                try:
                    result = await probe_service_details(address, port, protocol)
                except Exception:
                    result = new_probe("The check could not be completed")
            self._apply_service(host, name, port, address, result)
        finally:
            self.active.discard(key)

    def _apply_service(self, host: str, name: str, port: int, address: str, result: dict) -> None:
        now = time.monotonic()
        if result["alive"]:
            self.alive[host] = (now, result["alive_ms"])
        if now < self.hold_until:
            return
        state = next((s for n, p, s in store.services_of(host) if (n, p) == (name, port)), None)
        if state is None or store.details(host)["address"] != address:
            return
        key = ("service", host, name, port)
        ok = result["error"] is None
        if ok:
            self.fails.pop(key, None)
        else:
            streak = self.fails.get(key, 0) + 1
            self.fails[key] = streak
            if state != "down" and streak < LIVE_FAIL_THRESHOLD:
                self.due[key] = now + LIVE_RETRY_SECONDS
                return
        latency = round(result["latency"], 1) if ok else None
        flipped = None
        try:
            store.apply_service_result(host, name, port, ok, latency, result)
            row = store.host(host)
            if result["alive"] and row is not None and row[1] == "offline":
                flipped = max(1, round(result["alive_ms"]))
                store.apply_host_result(host, True, flipped)
        except DatabaseError as exc:
            self._db_failed(exc)
            return
        self.last_error = None
        if flipped is not None:
            host_item = monitor.items.get(host)
            if host_item is not None:
                host_item.record_probe(True, flipped, None, store.monitor_interval(host), "TCP")
        item = service_monitor.items.get((host, name, port))
        if item is not None:
            item.record_probe(ok, latency, result["error"])
            item.countdown = float(store.service_details(host, name, port)["interval"])
        self.on_change()


live = LiveMonitor()
