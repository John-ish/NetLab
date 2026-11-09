import getpass
import json
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path


STYLES_DIR = Path(__file__).with_name("styles")
STYLE_FILES = [
    "base.tcss",
    "menu.tcss",
    "common.tcss",
    "hosts.tcss",
    "services.tcss",
    "logs.tcss",
    "select.tcss",
    "host_form.tcss",
    "delete_dialogs.tcss",
    "service_form.tcss",
    "host_detail.tcss",
    "metric_detail.tcss",
    "service_detail.tcss",
    "sudo.tcss",
    "interval.tcss",
    "text_edit.tcss",
    "toast.tcss",
    "startup.tcss",
    "settings.tcss",
    "access.tcss",
    "ssh_setup.tcss",
    "overrides.tcss",
]
STYLE_PATH = [STYLES_DIR / name for name in STYLE_FILES]

SETTINGS_PATH = Path.home() / ".netlabdb" / "settings.json"
DATA_DIR = SETTINGS_PATH.parent
LAYOUT_PATH = DATA_DIR / "dashboard.json"
DB_PATH = DATA_DIR / "database.json"
SSH_DIR = DATA_DIR / "ssh"
KEY_PATH = SSH_DIR / "netlab_ed25519"
KEY_PUB_PATH = SSH_DIR / "netlab_ed25519.pub"
KNOWN_HOSTS = SSH_DIR / "known_hosts"
SECRET_PATH = DATA_DIR / "secret.key"

APP_VERSION = "0.1"

try:
    TEXTUAL_VERSION = package_version("textual")
except PackageNotFoundError:
    TEXTUAL_VERSION = "?"


def default_sslmode(host: str) -> str:
    local = host in ("localhost", "127.0.0.1", "::1") or host.startswith("/")
    return "prefer" if local else "require"


def load_db_config() -> dict:
    try:
        saved = json.loads(DB_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}

    def pick(variable: str, key: str, default: str) -> str:
        return os.environ.get(variable) or str(saved.get(key) or "") or default

    host = pick("NETLAB_DB_HOST", "host", "localhost")
    config = {
        "host": host,
        "sslmode": pick("NETLAB_DB_SSLMODE", "sslmode", "") or default_sslmode(host),
        "port": pick("NETLAB_DB_PORT", "port", "5432"),
        "dbname": pick("NETLAB_DB_NAME", "dbname", "net-lab-db"),
        "user": pick("NETLAB_DB_USER", "user", "postgres"),
        "connect_timeout": 3,
    }
    password = pick("NETLAB_DB_PASSWORD", "password", "")
    if password:
        config["password"] = password
    return config


DB_CONFIG = load_db_config()

DB_STATUS = {"online": "ACTIVE", "warning": "INACTIVE", "offline": "OFFLINE"}
APP_STATUS = {value: key for key, value in DB_STATUS.items()}

SERVICE_DB_STATUS = {"up": "RUNNING", "warning": "WARNING", "down": "STOPPED", "pending": "PENDING"}
SERVICE_APP_STATUS = {value: key for key, value in SERVICE_DB_STATUS.items()}


def secure_path(path: Path, directory: bool = False) -> None:
    try:
        if sys.platform.startswith("win"):
            grant = f"{getpass.getuser()}:(OI)(CI)F" if directory else f"{getpass.getuser()}:F"
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", grant],
                           capture_output=True, timeout=10, check=False)
        else:
            os.chmod(path, 0o700 if directory else 0o600)
    except (OSError, subprocess.SubprocessError):
        pass


def ensure_private_dir(path: Path) -> Path:
    created = not path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if created:
        secure_path(path, True)
    return path