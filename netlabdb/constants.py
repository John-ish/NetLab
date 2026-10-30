import re


MENU_ENTRIES = [
    ("Dashboard", "startup", "d"),
    ("Hosts", "hosts", "h"),
    ("Services", "services", "s"),
    ("Logs", "logs", "l"),
    ("Settings", "settings", "t"),
]

SERVICE_ICON = {"up": "●", "warning": "◐", "down": "×", "pending": "○"}
HOST_ICON = {"online": "●", "warning": "◐", "offline": "○"}

DOCKER_SERVICE = "Docker"
CONTAINER_ICON = {"running": "●", "restarting": "◐", "stopped": "○"}
CONTAINER_LABEL = {"running": "Running", "restarting": "Restarting", "stopped": "Stopped"}

CUSTOM_SERVICE = "__custom__"

SERVICE_PROTOCOLS = ["TCP", "UDP", "HTTP", "HTTPS"]

SERVICE_INTERVALS = [
    ("5 seconds", 5),
    ("10 seconds", 10),
    ("30 seconds", 30),
    ("1 minute", 60),
    ("5 minutes", 300),
]

SERVICE_PRESETS = [
    ("DHCP", 67, "UDP"),
    ("DNS", 53, "UDP"),
    ("Docker", 2376, "TCP"),
    ("Elasticsearch", 9200, "HTTP"),
    ("Grafana", 3000, "HTTP"),
    ("HTTPS", 443, "HTTPS"),
    ("Jellyfin", 8096, "HTTP"),
    ("Kibana", 5601, "HTTP"),
    ("Logstash", 5044, "TCP"),
    ("MongoDB", 27017, "TCP"),
    ("Mosquitto", 1883, "TCP"),
    ("MySQL", 3306, "TCP"),
    ("Nginx", 80, "HTTP"),
    ("Node Exporter", 9100, "HTTP"),
    ("NTP", 123, "UDP"),
    ("Pi-hole", 8080, "HTTP"),
    ("PostgreSQL", 5432, "TCP"),
    ("Prometheus", 9090, "HTTP"),
    ("RabbitMQ", 5672, "TCP"),
    ("Redis", 6379, "TCP"),
    ("SSH", 22, "TCP"),
]

BOXES_PER_ROW = 3
BOX_SLOT_WIDTH = 36

SERVICE_NAV_HINTS = [
    ("[↑/↓]", "Navigate"),
    ("[←/→]", "Host"),
    ("[Enter]", "Details"),
    ("[m]", "Menu"),
]

SERVICE_ACTION_EVENTS = [
    ("[a]", "Add"),
    ("[e]", "Edit"),
    ("[d]", "Remove"),
    ("[/]", "Search"),
]

HOST_ACTION_EVENTS = [
    ("[a]", "Add Host"),
    ("[e]", "Edit Host"),
    ("[d]", "Delete"),
    ("[/]", "Search"),
]

REFRESH_SECONDS = 5

NAV_HINTS = [
    ("[↑/↓]", "Navigate"),
    ("[Enter]", "Select"),
    ("[m]", "Menu"),
]

MAX_LOGS = 1000
LOG_VIEW_LIMIT = 150
LOG_VIEW_SLACK = 50
LIVE_REFRESH_SECONDS = 0.5

FLAP_CONFIRM = 3
FLAP_WINDOW = 300
FLAP_LIMIT = 4
LOG_INFO_DAYS = 7
LOG_KEEP_DAYS = 90

LOG_TYPES = ["ALL", "HOST", "SERVICE", "USER"]
LOG_LEVELS = ["ALL", "INFO", "WARNING", "ERROR"]

LOG_NAV_HINTS = [
    ("[↑/↓]", "Navigate"),
    ("[Enter]", "Details"),
    ("[m]", "Menu"),
]

LOG_ACTION_EVENTS = [
    ("[/]", "Search"),
    ("[f]", "Type"),
    ("[h]", "Host"),
    ("[l]", "Level"),
    ("[p]", "Pause"),
]

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

HISTORY_LENGTH = 3600
DETAIL_REFRESH_SECONDS = 1

THRESHOLDS = {
    "cpu": (75, 90),
    "mem": (80, 90),
    "disk": (80, 90),
    "latency": (150, 300),
}

DETAIL_NAV_HINTS = [
    ("[↑/↓/←/→]", "Navigate"),
    ("[Enter]", "Details"),
    ("[Esc]", "Back"),
    ("[m]", "Menu"),
]

DETAIL_ACTION_EVENTS = [
    ("[e]", "Edit Host"),
    ("[r]", "Check Now"),
    ("[i]", "Interval"),
    ("[l]", "View Logs"),
    ("[s]", "SSH"),
]

SERVICE_DETAIL_HINTS = [
    ("[Enter]", "Reveal"),
    ("[Esc]", "Back"),
    ("[m]", "Menu"),
]

SERVICE_DETAIL_EVENTS = [
    ("[e]", "Edit"),
    ("[d]", "Remove"),
    ("[r]", "Check"),
    ("[i]", "Interval"),
    ("[t]", "Range"),
]

METRIC_CARDS = [
    ("cpu", "CPU"),
    ("mem", "MEMORY"),
    ("disk", "FILE SYSTEM"),
    ("net", "NETWORK"),
    ("gpu", "GPU"),
    ("latency", "LATENCY"),
]

KIND_TITLES = {
    "cpu": "CPU USAGE",
    "mem": "MEMORY USAGE",
    "disk": "FILE SYSTEM",
    "net": "NETWORK TRAFFIC",
    "gpu": "GPU USAGE",
    "latency": "LATENCY",
    "alerts": "SYSTEM ALERTS",
    "sysinfo": "SYSTEM INFO",
    "monitor": "MONITORING",
}

SERVICE_LABEL = {"up": "Online", "warning": "Degraded", "down": "Offline", "pending": "Pending"}
LEVEL_RANK = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
BRAILLE_DOTS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))

RANGES = [("1 min", 60), ("5 min", 300), ("15 min", 900), ("1 hour", 3600)]
CHART_KINDS = ("cpu", "mem", "disk", "net", "gpu", "latency")
RANGE_MEMORY = {}

SSH_USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,31}$")
SSH_DEFAULT_PORT = 22
SSH_CONNECT_TIMEOUT = 6
SSH_STALE_SECONDS = 10
SSH_IDLE_SECONDS = 10
SSH_RETRY_SECONDS = (2, 5, 10, 30)
SSH_MISSING = "ssh client not found. Install OpenSSH to enable live metrics"

REVEAL_SECONDS = 15
SUDO_ATTEMPTS = 3
SUDO_LOCKOUT_SECONDS = 30

LIVE_CONCURRENCY = 16
LIVE_DB_RETRY_SECONDS = 20
LIVE_FAIL_THRESHOLD = 2
LIVE_RETRY_SECONDS = 2
LIVE_ALIVE_MIN_SECONDS = 30.0

WRITER_BATCH = 64
