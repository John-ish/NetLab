import getpass
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
SCHEMA = ROOT / "sql" / "net-lab-db.sql"
MODULES = ("textual", "psycopg2", "pyfiglet")
CHILD_FLAG = "NETLAB_BOOTSTRAPPED"
MIN_PYTHON = (3, 10)
HEADER = {"shown": False}


def say(text: str = "") -> None:
    print(text, flush=True)


def fail(text: str) -> None:
    say()
    say(f"  {text}")
    say()
    sys.exit(1)


def header() -> None:
    if HEADER["shown"]:
        return
    HEADER["shown"] = True
    say()
    say("  NETLAB DB - first-time setup")
    say("  ----------------------------")


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        have = ".".join(str(part) for part in sys.version_info[:3])
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required (you have {have}).\n"
             "  Download it from https://www.python.org/downloads/")


def missing_modules() -> list[str]:
    return [name for name in MODULES if importlib.util.find_spec(name) is None]


def in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def install_requirements(python: Path) -> None:
    header()
    say("  Installing dependencies. This only happens on the first run...")
    code = subprocess.call([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                            "-r", str(REQUIREMENTS)])
    if code != 0:
        fail("Could not install the dependencies. Check your internet connection and try again.\n"
             "  You can also install them yourself with: pip install -r requirements.txt")


def venv_hint() -> str:
    if os.name == "nt":
        return "Reinstall Python from python.org and keep the 'pip' option ticked."
    return "Install it with your package manager, e.g. sudo apt install python3-venv python3-pip"


def ensure_environment() -> None:
    if not missing_modules():
        return
    if in_venv():
        install_requirements(Path(sys.executable))
        importlib.invalidate_caches()
        if missing_modules():
            fail("The dependencies could not be loaded after installing them.")
        return
    if os.environ.get(CHILD_FLAG):
        fail("The dependencies are still missing inside .venv. Delete the .venv folder and start again.")
    python = venv_python()
    if not python.exists():
        header()
        say("  Creating a private Python environment in .venv ...")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
        except (subprocess.CalledProcessError, OSError):
            shutil.rmtree(VENV, ignore_errors=True)
            fail(f"Could not create the Python environment. {venv_hint()}")
    ready = subprocess.call([str(python), "-c", "import " + ", ".join(MODULES)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    if not ready:
        install_requirements(python)
    environment = dict(os.environ)
    environment[CHILD_FLAG] = "1"
    sys.exit(subprocess.call([str(python), str(ROOT / "run.py"), *sys.argv[1:]], env=environment))


def first_line(error) -> str:
    lines = str(error).strip().splitlines()
    return lines[0] if lines else error.__class__.__name__


def classify(text: str) -> tuple[str, str]:
    low = text.lower()
    if 'database "' in low and "does not exist" in low:
        return "no_database", text
    if any(word in low for word in ("password", "authentication", 'role "')):
        return "auth", text
    if any(word in low for word in ("refused", "could not connect", "timeout", "translate host",
                                    "not known", "unreachable", "is the server running")):
        return "unreachable", text
    return "unknown", text


def inspect(cfg: dict) -> tuple[str, str]:
    import psycopg2
    try:
        conn = psycopg2.connect(**cfg)
    except UnicodeDecodeError:
        return "unknown", "The server could not be reached or refused the login"
    except psycopg2.Error as error:
        return classify(first_line(error))
    try:
        with conn, conn.cursor() as cursor:
            cursor.execute("SELECT to_regclass('hosts'), to_regclass('services'), "
                           "to_regclass('maintenance_logs')")
            found = cursor.fetchone()
    except psycopg2.Error as error:
        return "unknown", first_line(error)
    finally:
        conn.close()
    return ("ready" if all(found) else "no_schema"), ""


def apply_schema(cfg: dict) -> str | None:
    import psycopg2
    try:
        script = SCHEMA.read_text(encoding="utf-8")
    except OSError:
        return f"Cannot read {SCHEMA}"
    try:
        conn = psycopg2.connect(**cfg)
        try:
            with conn, conn.cursor() as cursor:
                cursor.execute(script)
        finally:
            conn.close()
    except UnicodeDecodeError:
        return "The server refused the connection"
    except psycopg2.Error as error:
        return first_line(error)
    return None


def create_database(cfg: dict) -> str | None:
    import psycopg2
    from psycopg2 import sql
    last = "Could not connect to the PostgreSQL server"
    for maintenance in ("postgres", "template1"):
        try:
            conn = psycopg2.connect(**dict(cfg, dbname=maintenance))
        except UnicodeDecodeError:
            continue
        except psycopg2.Error as error:
            last = first_line(error)
            continue
        try:
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cfg["dbname"])))
            return None
        except psycopg2.Error as error:
            return first_line(error)
        finally:
            conn.close()
    return last


def ask(label: str, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    try:
        value = input(f"  {label}{shown}: ").strip()
    except EOFError:
        value = ""
    return value or default


def ask_secret(label: str) -> str:
    try:
        return getpass.getpass(f"  {label}: ")
    except EOFError:
        return ""


def pick(prompt: str, valid: str, default: str) -> str:
    while True:
        try:
            answer = input(f"  {prompt} ").strip().lower()[:1] or default
        except EOFError:
            return "q"
        if answer in valid:
            return answer


def ask_credentials(cfg: dict) -> dict:
    user = ask("Database user", cfg["user"])
    password = ask_secret(f"Password for {user} (leave empty for none)")
    updated = dict(cfg, user=user)
    if password:
        updated["password"] = password
    else:
        updated.pop("password", None)
    return updated


def ask_connection(cfg: dict) -> dict:
    from .config import default_sslmode
    host = ask("Host", cfg["host"])
    port = ask("Port", str(cfg["port"]))
    if not (port.isascii() and port.isdigit() and 1 <= int(port) <= 65535):
        say(f"  Not a valid port, keeping {cfg['port']}.")
        port = str(cfg["port"])
    name = ask("Database name", cfg["dbname"])
    updated = ask_credentials(dict(cfg, host=host, port=port, dbname=name))
    if not os.environ.get("NETLAB_DB_SSLMODE"):
        updated["sslmode"] = default_sslmode(host)
    return updated


def unreachable_help(cfg: dict) -> list[str]:
    if cfg["host"] not in ("localhost", "127.0.0.1", "::1") and not str(cfg["host"]).startswith("/"):
        return ["Check the host name, the port and any firewall in between."]
    if os.name == "nt":
        return ["PostgreSQL is not running or not installed.",
                "Download it from https://www.postgresql.org/download/windows/",
                "or run: winget install PostgreSQL.PostgreSQL",
                "Remember the password you choose for the 'postgres' user during installation."]
    if sys.platform == "darwin":
        return ["PostgreSQL is not running or not installed.",
                "Install it with: brew install postgresql   then: brew services start postgresql"]
    return ["PostgreSQL is not running or not installed.",
            "Debian/Ubuntu: sudo apt install postgresql",
            "Fedora: sudo dnf install postgresql-server    Arch: sudo pacman -S postgresql",
            "Then start it with: sudo systemctl enable --now postgresql"]


def auth_help() -> list[str]:
    if os.name == "nt":
        return ["Use the password you chose for the 'postgres' user when you installed PostgreSQL."]
    return ["If you never set a password for 'postgres', set one with:",
            "sudo -u postgres psql -c \"ALTER USER postgres PASSWORD 'choose-a-password';\""]


def save_connection(cfg: dict) -> None:
    from .config import DB_PATH, ensure_private_dir, secure_path
    data = {key: str(cfg[key]) for key in ("host", "port", "dbname", "user")}
    if cfg.get("password"):
        data["password"] = cfg["password"]
    try:
        ensure_private_dir(DB_PATH.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(DB_PATH, flags, 0o600), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        secure_path(DB_PATH)
    except OSError as error:
        say(f"  Could not save the connection settings: {error.strerror or error}")
        return
    say(f"  Connection settings saved to {DB_PATH}")


def prepare_database(reconfigure: bool) -> None:
    from . import config
    cfg = config.load_db_config()
    interactive = sys.stdin.isatty()
    edited = False
    repairs = 0
    if reconfigure:
        if not interactive:
            fail("--setup needs an interactive terminal.")
        header()
        say("  Database connection")
        cfg = ask_connection(cfg)
        edited = True
    while True:
        state, detail = inspect(cfg)
        if state == "ready":
            break
        repairs += 1
        if state in ("no_schema", "no_database") and repairs > 4:
            fail("The database could not be prepared automatically.\n"
                 f"  Create it manually with: createdb {cfg['dbname']}   then: psql -d {cfg['dbname']} -f sql/net-lab-db.sql")
        if state == "no_schema":
            header()
            say("  Creating the database tables...")
            error = apply_schema(cfg)
            if error:
                fail(f"Could not create the tables: {error}")
            continue
        if state == "no_database":
            header()
            say(f"  Creating the database '{cfg['dbname']}'...")
            error = create_database(cfg)
            if error:
                fail(f"Could not create the database: {error}\n  Create it yourself with: createdb {cfg['dbname']}")
            continue
        header()
        if not interactive:
            say(f"  Database unavailable: {detail}")
            say("  Starting without a database. Hosts will not be saved.")
            return
        if state == "auth":
            say(f"  PostgreSQL rejected the login: {detail}")
            for line in auth_help():
                say(f"  {line}")
            choice = pick("[E]nter credentials, [S]kip, [Q]uit:", "esq", "e")
            if choice == "e":
                cfg = ask_credentials(cfg)
                edited = True
        else:
            say(f"  Could not reach the database: {detail}")
            for line in unreachable_help(cfg):
                say(f"  {line}")
            choice = pick("[R]etry, [C]hange connection, [S]kip, [Q]uit:", "rcsq", "r")
            if choice == "c":
                cfg = ask_connection(cfg)
                edited = True
        if choice == "q":
            sys.exit(0)
        if choice == "s":
            say("  Starting without a database. Hosts will not be saved.")
            return
    config.DB_CONFIG.clear()
    config.DB_CONFIG.update(cfg)
    if edited:
        save_connection(cfg)


def make_command() -> None:
    from .command import create_command, mark_created
    ok, message = create_command()
    mark_created()
    if ok:
        say(f"  {message}")
    else:
        say(f"  {message}")
        say("  Run 'python run.py --command' to try again.")


def ensure_command() -> None:
    from . import command
    if command.up_to_date():
        return
    header()
    say()
    make_command()


def launch() -> None:
    try:
        check_python()
        if "--command" in sys.argv[1:]:
            make_command()
            return
        ensure_environment()
        prepare_database("--setup" in sys.argv[1:])
        ensure_command()
        if HEADER["shown"]:
            say("  Starting NETLAB DB...")
            say()
    except KeyboardInterrupt:
        say()
        sys.exit(130)
    from .app import main
    main()