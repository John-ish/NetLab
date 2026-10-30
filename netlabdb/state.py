from .constants import MAX_LOGS


HOSTS = [
    ("server-01", "online",  7, 7, "12s ago", 12),
    ("server-02", "online",  9, 9, "4m ago",  34),
    ("server-03", "offline", 0, 0, "2h ago",  None),
    ("server-04", "warning", 6, 7, "18s ago", 187),
    ("server-05", "online",  8, 8, "6m ago",  21),
    ("server-06", "online",  7, 7, "3m ago",  45),
    ("server-07", "online",  5, 6, "1h ago",  98),
    ("server-08", "warning", 6, 7, "9m ago",  240),
    ("server-09", "offline", 0, 0, "5h ago",  None),
    ("server-10", "online",  8, 8, "22s ago", 16),
]

HOST_DETAILS = {
    "server-01": {"address": "10.0.0.1",  "description": "Primary web server"},
    "server-02": {"address": "10.0.0.2",  "description": "Database server"},
    "server-03": {"address": "10.0.0.3",  "description": ""},
    "server-04": {"address": "10.0.0.4",  "description": "Monitoring stack"},
    "server-05": {"address": "10.0.0.5",  "description": "Document store"},
    "server-06": {"address": "10.0.0.6",  "description": "Message queue"},
    "server-07": {"address": "10.0.0.7",  "description": "Search and logging"},
    "server-08": {"address": "10.0.0.8",  "description": "DNS and DHCP"},
    "server-09": {"address": "10.0.0.9",  "description": ""},
    "server-10": {"address": "10.0.0.10", "description": "Application server"},
}

SERVICES = [
    ("server-01", "online", [
        ("SSH",        22,    "up"),
        ("PostgreSQL", 5432,  "up"),
        ("Nginx",      80,    "up"),
        ("Docker",     2376,  "up"),
    ]),
    ("server-02", "online", [
        ("SSH",        22,    "up"),
        ("PostgreSQL", 5432,  "up"),
        ("Redis",      6379,  "up"),
    ]),
    ("server-03", "offline", [
        ("SSH",        22,    "down"),
        ("Nginx",      80,    "down"),
        ("Grafana",    3000,  "down"),
    ]),
    ("server-04", "warning", [
        ("SSH",        22,    "up"),
        ("MySQL",      3306,  "warning"),
        ("Nginx",      80,    "up"),
        ("Redis",      6379,  "up"),
        ("Prometheus", 9090,  "down"),
        ("Grafana",    3000,  "up"),
    ]),
    ("server-05", "online", [
        ("SSH",        22,    "up"),
        ("MongoDB",    27017, "up"),
        ("Nginx",      80,    "up"),
        ("HTTPS",      443,   "up"),
    ]),
    ("server-06", "online", [
        ("SSH",        22,    "up"),
        ("RabbitMQ",   5672,  "up"),
        ("Docker",     2376,  "up"),
    ]),
    ("server-07", "online", [
        ("SSH",        22,    "up"),
        ("Elasticsearch", 9200, "up"),
        ("Kibana",     5601,  "up"),
        ("Logstash",   5044,  "up"),
        ("Nginx",      80,    "down"),
    ]),
    ("server-08", "warning", [
        ("SSH",        22,    "up"),
        ("DNS",        53,    "warning"),
        ("DHCP",       67,    "up"),
        ("NTP",        123,   "up"),
    ]),
    ("server-09", "offline", [
        ("SSH",        22,    "down"),
        ("Mosquitto",  1883,  "down"),
    ]),
    ("server-10", "online", [
        ("SSH",        22,    "up"),
        ("PostgreSQL", 5432,  "up"),
        ("Redis",      6379,  "up"),
        ("Nginx",      80,    "up"),
        ("Node Exporter", 9100, "up"),
        ("Docker",     2376,  "up"),
    ]),
]

SERVICE_DETAILS = {}
SERVICE_ACCESS = {}
SERVICE_LIVE = {}

LOGS = [
    ("21:42:18", "HOST",    "server-01 online",          "server-01", "info",    None),
    ("21:42:11", "SERVICE", "{service} stopped",         "server-04", "error",   "Nginx"),
    ("21:41:52", "SERVICE", "{service} running",         "server-01", "info",    "PostgreSQL"),
    ("21:40:32", "USER",    "Added host server-04",      "server-04", "info",    None),
    ("21:39:18", "HOST",    "server-03 offline",         "server-03", "error",   None),
    ("21:38:51", "SERVICE", "{service} running",         "server-02", "info",    "SSH"),
    ("21:37:40", "SERVICE", "{service} degraded",        "server-04", "warning", "MySQL"),
    ("21:36:05", "HOST",    "server-08 high latency",    "server-08", "warning", None),
    ("21:34:27", "SERVICE", "{service} slow response",   "server-08", "warning", "DNS"),
    ("21:33:10", "USER",    "Edited host server-02",     "server-02", "info",    None),
    ("21:31:58", "SERVICE", "{service} stopped",         "server-04", "error",   "Prometheus"),
    ("21:30:12", "HOST",    "server-09 offline",         "server-09", "error",   None),
    ("21:28:44", "SERVICE", "{service} running",         "server-02", "info",    "Redis"),
    ("21:27:03", "USER",    "Removed service {service}", "server-03", "info",    "Grafana"),
    ("21:25:36", "HOST",    "server-10 online",          "server-10", "info",    None),
    ("21:24:19", "SERVICE", "{service} running",         "server-07", "info",    "Elasticsearch"),
]


def trim_logs() -> None:
    excess = len(LOGS) - MAX_LOGS
    if excess <= 0:
        return
    for i in range(len(LOGS) - 1, 0, -1):
        if LOGS[i][4] == "info":
            del LOGS[i]
            excess -= 1
            if not excess:
                return
    del LOGS[MAX_LOGS:]
