import queue
import threading
import time
from contextlib import contextmanager

from .constants import LOG_INFO_DAYS, LOG_KEEP_DAYS, WRITER_BATCH
from .crypto import encrypt_secret
from .errors import DatabaseError
from .helpers import local_now


try:
    import psycopg2
    import psycopg2.errors
except ImportError:
    psycopg2 = None

SCHEMA_UPGRADES = [
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS checks_total int NOT NULL DEFAULT 0",
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS checks_passed int NOT NULL DEFAULT 0",
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS status_since timestamptz",
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS cred_user varchar(100)",
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS cred_password text",
    "ALTER TABLE services ADD COLUMN IF NOT EXISTS cred_visible boolean NOT NULL DEFAULT false",
    "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS ssh_user varchar(64)",
    "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS ssh_port int CHECK (ssh_port BETWEEN 1 AND 65535)",
    "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS os_family varchar(10) CHECK (os_family = 'linux')",
]


class HostDatabase:

    def __init__(self, config: dict):
        self.config = config
        self.conn = None
        self.cursor = None

    @staticmethod
    def _reason(error) -> str:
        lines = str(error).strip().splitlines()
        return lines[0] if lines else error.__class__.__name__

    def connect(self):
        if psycopg2 is None:
            raise DatabaseError("psycopg2 is not installed")
        if self.conn is not None and not self.conn.closed:
            return self.conn
        try:
            self.conn = psycopg2.connect(**self.config)
        except UnicodeDecodeError as error:
            self.conn = None
            raise DatabaseError("Could not connect to the database") from error
        except psycopg2.Error as error:
            self.conn = None
            raise DatabaseError(self._reason(error)) from error
        return self.conn

    def close(self) -> None:
        if self.conn is not None and not self.conn.closed:
            self.conn.close()
        self.conn = None

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            with conn:
                with conn.cursor() as cursor:
                    self.cursor = cursor
                    try:
                        yield
                    finally:
                        self.cursor = None
        except psycopg2.Error as error:
            raise DatabaseError(self._reason(error)) from error

    @staticmethod
    def _execute(cursor, sql: str, params: tuple, fetch: bool):
        cursor.execute(sql, params)
        return cursor.fetchall() if fetch else cursor.rowcount

    def _run(self, sql: str, params: tuple = (), fetch: bool = False,
             duplicate: str = "Host name or address is already in use"):
        try:
            if self.cursor is not None:
                return self._execute(self.cursor, sql, params, fetch)
            conn = self.connect()
            with conn:
                with conn.cursor() as cursor:
                    return self._execute(cursor, sql, params, fetch)
        except psycopg2.errors.UniqueViolation as error:
            raise DatabaseError(duplicate) from error
        except psycopg2.Error as error:
            raise DatabaseError(self._reason(error)) from error

    def hosts(self) -> list[tuple]:
        return self._run(
            "SELECT hostname, ip_address, description, status, latency_ms, last_seen, check_interval, "
            "ssh_user, ssh_port, os_family FROM hosts ORDER BY host_id",
            fetch=True,
        )

    def insert_host(self, name: str, address: str, description: str, status: str,
                    latency: int | None = None, last_seen=None) -> None:
        self._run(
            "INSERT INTO hosts (hostname, ip_address, description, status, latency_ms, last_seen) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (name, address, description, status, latency, last_seen),
        )

    def update_host(self, original: str, name: str, address: str, description: str, status: str,
                    latency: int | None = None, reachable: bool = False) -> None:
        changed = self._run(
            "UPDATE hosts SET hostname = %s, ip_address = %s, description = %s, status = %s, "
            "latency_ms = CASE WHEN %s THEN %s::int ELSE latency_ms END, "
            "last_seen = CASE WHEN %s THEN %s::timestamptz ELSE last_seen END "
            "WHERE hostname = %s",
            (name, address, description, status, reachable, latency, reachable, local_now(), original),
        )
        if not changed:
            raise DatabaseError(f"Host {original} no longer exists in the database")
        if name != original:
            self._run("UPDATE maintenance_logs SET host_name = %s WHERE host_name = %s", (name, original))

    def update_host_state(self, name: str, status: str, latency: int | None, reachable: bool) -> None:
        changed = self._run(
            "UPDATE hosts SET status = %s, latency_ms = %s, "
            "last_seen = CASE WHEN %s THEN %s::timestamptz ELSE last_seen END WHERE hostname = %s",
            (status, latency, reachable, local_now(), name),
        )
        if not changed:
            raise DatabaseError(f"Host {name} no longer exists in the database")

    def update_host_interval(self, name: str, interval: int) -> None:
        changed = self._run("UPDATE hosts SET check_interval = %s WHERE hostname = %s", (interval, name))
        if not changed:
            raise DatabaseError(f"Host {name} no longer exists in the database")

    def update_host_ssh(self, name: str, ssh_user: str | None, ssh_port: int | None,
                        family: str | None = None) -> None:
        self._run(
            "UPDATE hosts SET ssh_user = %s, ssh_port = %s, os_family = %s WHERE hostname = %s",
            (ssh_user, ssh_port, family, name),
        )

    def update_host_os(self, name: str, family: str) -> None:
        self._run("UPDATE hosts SET os_family = %s WHERE hostname = %s", (family, name))

    def update_host_check(self, name: str, latency: int) -> None:
        changed = self._run(
            "UPDATE hosts SET latency_ms = %s, last_seen = %s, status = 'ACTIVE' WHERE hostname = %s",
            (latency, local_now(), name),
        )
        if not changed:
            raise DatabaseError(f"Host {name} no longer exists in the database")

    def delete_host(self, name: str) -> None:
        self._run("DELETE FROM maintenance_logs WHERE host_name = %s", (name,))
        self._run("DELETE FROM hosts WHERE hostname = %s", (name,))

    def services(self) -> list[tuple]:
        return self._run(
            "SELECT h.hostname, s.service_name, s.port_number, s.status, s.protocol, "
            "s.check_interval, s.description, s.cred_user, s.cred_password, s.cred_visible "
            "FROM services s JOIN hosts h ON h.host_id = s.host_id ORDER BY s.service_id",
            fetch=True,
        )

    def insert_service(self, host: str, name: str, port: int, protocol: str,
                       interval: int, description: str, status: str) -> None:
        added = self._run(
            "INSERT INTO services (host_id, service_name, port_number, protocol, check_interval, "
            "description, status) SELECT host_id, %s, %s, %s, %s, %s, %s FROM hosts WHERE hostname = %s",
            (name, port, protocol, interval, description, status, host),
            duplicate="That service already exists on this host",
        )
        if not added:
            raise DatabaseError(f"Host {host} no longer exists in the database")

    def update_service(self, original: tuple, host: str, name: str, port: int,
                       protocol: str, interval: int, description: str) -> None:
        old_host, old_name, old_port = original
        changed = self._run(
            "UPDATE services s SET host_id = nh.host_id, service_name = %s, port_number = %s, "
            "protocol = %s, check_interval = %s, description = %s "
            "FROM hosts nh, hosts oh WHERE nh.hostname = %s AND oh.hostname = %s "
            "AND s.host_id = oh.host_id AND s.service_name = %s AND s.port_number = %s",
            (name, port, protocol, interval, description, host, old_host, old_name, old_port),
            duplicate="That service already exists on this host",
        )
        if not changed:
            raise DatabaseError(f"Service {old_name} no longer exists in the database")
        if host == old_host and name != old_name:
            self._run(
                "UPDATE maintenance_logs SET service_name = %s WHERE host_name = %s AND service_name = %s",
                (name, host, old_name),
            )

    def update_service_access(self, host: str, name: str, port: int, username: str | None,
                              password: str | None, visible: bool) -> None:
        changed = self._run(
            "UPDATE services s SET cred_user = %s, cred_password = %s, cred_visible = %s FROM hosts h "
            "WHERE s.host_id = h.host_id AND h.hostname = %s AND s.service_name = %s AND s.port_number = %s",
            (username, encrypt_secret(password) if password else None, visible, host, name, port),
        )
        if not changed:
            raise DatabaseError(f"Service {name} no longer exists in the database")

    def update_service_interval(self, host: str, name: str, port: int, interval: int) -> None:
        changed = self._run(
            "UPDATE services s SET check_interval = %s FROM hosts h "
            "WHERE s.host_id = h.host_id AND h.hostname = %s AND s.service_name = %s AND s.port_number = %s",
            (interval, host, name, port),
        )
        if not changed:
            raise DatabaseError(f"Service {name} no longer exists in the database")

    def upgrade(self) -> None:
        for statement in SCHEMA_UPGRADES:
            self._run(statement)

    def service_stats(self) -> list[tuple]:
        return self._run(
            "SELECT h.hostname, s.service_name, s.port_number, s.checks_total, s.checks_passed, "
            "s.status_since, s.latency_ms FROM services s JOIN hosts h ON h.host_id = s.host_id",
            fetch=True,
        )

    def update_service_state(self, host: str, name: str, port: int, status: str,
                             latency: float | None, passed: bool) -> None:
        now = local_now()
        self._run(
            "UPDATE services s SET status = %s, latency_ms = %s, last_check = %s, "
            "checks_total = s.checks_total + 1, checks_passed = s.checks_passed + %s, "
            "status_since = CASE WHEN s.status IS DISTINCT FROM %s OR s.status_since IS NULL "
            "THEN %s::timestamptz ELSE s.status_since END "
            "FROM hosts h WHERE s.host_id = h.host_id AND h.hostname = %s "
            "AND s.service_name = %s AND s.port_number = %s",
            (status, latency, now, 1 if passed else 0, status, now, host, name, port),
        )

    def update_service_check(self, host: str, name: str, port: int, latency: float | None) -> None:
        self._run(
            "UPDATE services s SET latency_ms = %s, last_check = %s FROM hosts h "
            "WHERE s.host_id = h.host_id AND h.hostname = %s AND s.service_name = %s AND s.port_number = %s",
            (latency, local_now(), host, name, port),
        )

    def delete_service(self, host: str, name: str, port: int) -> None:
        self._run(
            "DELETE FROM services s USING hosts h "
            "WHERE s.host_id = h.host_id AND h.hostname = %s AND s.service_name = %s AND s.port_number = %s",
            (host, name, port),
        )
        self._run(
            "DELETE FROM maintenance_logs WHERE host_name = %s AND service_name = %s "
            "AND NOT EXISTS (SELECT 1 FROM services s JOIN hosts h ON h.host_id = s.host_id "
            "WHERE h.hostname = %s AND s.service_name = %s)",
            (host, name, host, name),
        )

    def prune_logs(self) -> None:
        self._run(
            "DELETE FROM maintenance_logs WHERE (level = 'INFO' AND log_date < now() - make_interval(days => %s)) "
            "OR log_date < now() - make_interval(days => %s)",
            (LOG_INFO_DAYS, LOG_KEEP_DAYS),
        )

    def logs(self) -> list[tuple]:
        return self._run(
            "SELECT log_date, log_type, changes_performed, host_name, level, service_name "
            "FROM maintenance_logs ORDER BY log_date DESC, log_id DESC LIMIT 1000",
            fetch=True,
        )

    def insert_log(self, kind: str, text: str, host: str, level: str,
                   service: str | None, moment, require_host: bool = False) -> None:
        if require_host:
            self._run(
                "INSERT INTO maintenance_logs (host_id, host_name, log_type, level, service_name, "
                "changes_performed, log_date) SELECT host_id, %s, %s, %s, %s, %s, %s FROM hosts "
                "WHERE hostname = %s",
                (host, kind, level.upper(), service, text, moment, host),
            )
            return
        self._run(
            "INSERT INTO maintenance_logs (host_id, host_name, log_type, level, service_name, "
            "changes_performed, log_date) "
            "VALUES ((SELECT host_id FROM hosts WHERE hostname = %s), %s, %s, %s, %s, %s, %s)",
            (host, host, kind, level.upper(), service, text, moment),
        )


class DbWriter:

    def __init__(self, config: dict, on_error):
        self.db = HostDatabase(config)
        self.on_error = on_error
        self.jobs = queue.Queue()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def submit(self, method: str, *args, **kwargs) -> None:
        self.jobs.put((method, args, kwargs))

    def stop(self) -> None:
        self.on_error = lambda message: None
        self.jobs.put(None)
        self.thread.join(5)
        self.db.close()

    def _loop(self) -> None:
        while True:
            batch = [self.jobs.get()]
            while len(batch) < WRITER_BATCH:
                try:
                    batch.append(self.jobs.get_nowait())
                except queue.Empty:
                    break
            stopping = None in batch
            batch = [job for job in batch if job is not None]
            if batch:
                try:
                    self._flush(batch)
                except Exception:
                    pass
            if stopping:
                return

    def _flush(self, batch: list) -> None:
        try:
            with self.db.transaction():
                for method, args, kwargs in batch:
                    getattr(self.db, method)(*args, **kwargs)
            return
        except Exception as error:
            failure = error
        conn = self.db.conn
        if conn is None or conn.closed:
            self.on_error(str(failure))
            time.sleep(1)
            return
        for method, args, kwargs in batch:
            try:
                getattr(self.db, method)(*args, **kwargs)
            except DatabaseError as error:
                if "no longer exists" not in str(error):
                    self.on_error(str(error))
            except Exception:
                continue
