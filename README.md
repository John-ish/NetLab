# NETLAB

A homelab monitoring tool with a lot of terminal eye candy.
Built with: Python · Textual · PostgreSQL

Supports Windows and Linux.

## Features

- **Host Monitoring** – Track server availability, latency and connection status.
- **Service Monitoring** – Monitor services using TCP, HTTP and HTTPS checks.
- **Live Metrics** – View CPU, memory, disk, network and GPU usage through SSH.
- **Docker Integration** – Monitor containers, their status and resource usage.
- **Service Details** – View response times, process information and resource usage.
- **Event Logs** – Track host, service and user events with search and filters.
- **Credential Storage** – Store service credentials with database encryption.
- **Customizable UI** – Choose themes, dashboard layouts, colors and CRT effects.

## Screenshots

## Installation

### Requirements

- [Python 3.10 or newer](https://www.python.org/downloads/). On Windows, tick "Add python.exe to PATH" in the installer.
- [PostgreSQL](https://www.postgresql.org/download/). On Windows, remember the password you choose for the `postgres` user.
- To collect live metrics: an OpenSSH client on your machine (`ssh`, `ssh-keygen`, `ssh-keyscan`) and a Linux server with an SSH login

### Quick start

Start the app:

- Windows: double-click `start.bat`
- Linux / macOS: run `sh start.sh` (or `chmod +x start.sh` once, then `./start.sh`)
- Any system: `python run.py`

On the first run NETLAB sets everything up for you:

- creates a private `.venv` and installs the dependencies from `requirements.txt`
- connects to PostgreSQL and asks for the user and password if the login fails
- creates the `net-lab-db` database and its tables
- saves the working connection to `~/.netlabdb/database.json`, so later launches ask nothing
- adds the `netlab` command, and `nl` as a short form, so you can start the app from any terminal

If PostgreSQL is not installed or not running, the setup tells you how to install or start it, then lets you retry, change the connection, or continue without a database (hosts will not be saved).

### Opening the app later

Open a new terminal and type:

```bash
netlab
```

or the short form:

```bash
nl
```

On Linux and macOS a system command named `nl` (it numbers the lines of a file) already exists. Our `nl` takes priority only when `~/.local/bin` comes before `/usr/bin` in your `PATH`, which is the default on Ubuntu and Debian. `netlab` always works.

`start.bat`, `start.sh` and `python run.py` keep working too. If you move the project folder, the commands are updated the next time you start the app from its new location.

| Command                   | What it does                                |
| ------------------------- | ------------------------------------------- |
| `python run.py --setup`   | enter the database connection details again |
| `python run.py --command` | create the `netlab` and `nl` commands again |

### Manual setup

If you prefer to do it by hand:

```bash
createdb net-lab-db
psql -d net-lab-db -f sql/net-lab-db.sql
pip install -r requirements.txt
python run.py
```

`python -m netlabdb` works too.

### Monitoring a server with live metrics

1. Select a host and press `s` on its detail screen (or use the SSH setup button when adding a host).
2. Enter the SSH user and port. The wizard checks your local SSH tools, shows the server's host key fingerprints for you to confirm, creates a dedicated key pair, and installs the public key.
3. If the server does not accept the key yet, enter the server password once, or copy the one-line command and run it on the server yourself.

The monitored server must run Linux with a POSIX shell, `awk`, `ps` and `df`. `nvidia-smi`, `docker` and `apt-check` are optional and only add GPU, container and update information.

## Configuration

NETLAB DB stores its configuration in `~/.netlabdb/`.

| File             | Purpose                               |
| ---------------- | ------------------------------------- |
| `database.json`  | Database connection                   |
| `settings.json`  | Application settings                  |
| `dashboard.json` | Custom dashboard layout               |
| `secret.key`     | Encryption key for stored credentials |
| `ssh/`           | NETLAB SSH keys and known hosts       |

Database settings can also be configured using environment variables such as `NETLAB_DB_HOST`, `NETLAB_DB_PORT`, `NETLAB_DB_NAME`, `NETLAB_DB_USER` and `NETLAB_DB_PASSWORD`.

## Project Structure

```text
netlabdb/
├── screens/       # Application screens and dialogs
├── styles/        # Textual stylesheets
├── app.py         # Main application
├── db.py          # PostgreSQL connection and queries
├── network.py     # Network monitoring
├── metrics.py     # Host and service metrics
├── ssh.py         # SSH connections and key management
├── collectors.py  # Live metric collection
├── crypto.py      # Credential encryption
└── charts.py      # Charts and visualizations

sql/               # Database schema
run.py             # Application entry point
requirements.txt   # Python dependencies
```

## Security

- Service credentials are encrypted before being stored in PostgreSQL.
- SSH uses a dedicated key pair and verifies server host keys.
- SSH monitoring uses read-only system information.
- Database credentials are stored locally. Use environment variables if you don't want to store the database password in the configuration file.

See the configuration and security implementation for more details.


## License

Released under the [MIT License](LICENSE).
