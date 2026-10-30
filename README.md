# NETLAB DB

A terminal UI for server monitoring, built with [Textual](https://textual.textualize.io/) and PostgreSQL.
Runs on Windows and Linux.

## Setup

1. Create the database and schema:

   ```
   createdb net-lab-db
   psql -d net-lab-db -f sql/net-lab-db.sql
   ```

2. Install dependencies and run:

   ```
   pip install -r requirements.txt
   python run.py
   ```

   `python -m netlabdb` works too.

## Database configuration

Set these environment variables if the defaults do not fit:

| Variable | Default |
|---|---|
| `NETLAB_DB_HOST` | `localhost` |
| `NETLAB_DB_PORT` | `5432` |
| `NETLAB_DB_NAME` | `net-lab-db` |
| `NETLAB_DB_USER` | `postgres` |
| `NETLAB_DB_PASSWORD` | none |
| `NETLAB_DB_SSLMODE` | `prefer` for local hosts, `require` otherwise |

Settings, the SSH key and the credential encryption key are stored in `~/.netlabdb`.

## Layout

```
netlabdb/
  app.py            application class and entry point
  config.py         paths, DB settings, status maps
  constants.py      shared tables and tuning values
  theme.py          colour schemes
  settings.py       persisted user settings
  crt.py            CRT effect and fast background patches
  helpers.py        formatting and text helpers
  charts.py         braille charts and bars
  network.py        ping, TCP/TLS/HTTP probes
  state.py          in-memory host, service and log data
  errors.py         DatabaseError, SecretError
  crypto.py         credential encryption
  db.py             PostgreSQL access and background writer
  store.py          application data layer (CRUD)
  metrics.py        host and service metrics
  ssh.py            SSH client, keys, host key handling
  collectors.py     live SSH metric streams
  live.py           live probe scheduler
  sudo.py           sudo password check for revealing credentials
  detail_builder.py detail views for host metrics
  widgets.py        shared widgets
  screens/          every screen and dialog
  styles/           stylesheet, split per screen (load order is set in config.py)
```

## Stylesheet

`netlabdb/styles/` holds one `.tcss` file per screen or dialog. Files load in the order listed in
`STYLE_FILES` in `config.py`. Later rules win ties, so keep that order when adding files.
`base`, `common` and `select` hold shared rules, and `overrides` loads last.
