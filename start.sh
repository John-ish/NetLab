#!/bin/sh
cd "$(dirname "$0")" || exit 1
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        exec "$candidate" run.py "$@"
    fi
done
echo "Python 3.10 or newer is required."
echo "Install it with your package manager, e.g. sudo apt install python3 python3-venv python3-pip"
exit 1