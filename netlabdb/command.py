import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .config import DATA_DIR, ensure_private_dir


ROOT = Path(__file__).resolve().parent.parent
MARKER = DATA_DIR / "command.done"
NAMES = ("netlab", "nl")

PATH_SCRIPT = """$dir = $env:NL_DIR
$current = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @()
if ($current) { $parts = @($current.Split(';') | Where-Object { $_ }) }
if ($parts -notcontains $dir) {
    [Environment]::SetEnvironmentVariable('Path', (($parts + $dir) -join ';'), 'User')
}
"""


def signature() -> str:
    return f"{ROOT}\n{','.join(NAMES)}"


def up_to_date() -> bool:
    try:
        return MARKER.read_text(encoding="utf-8").strip() == signature()
    except OSError:
        return False


def mark_created() -> None:
    try:
        ensure_private_dir(DATA_DIR)
        MARKER.write_text(signature(), encoding="utf-8")
    except OSError:
        pass


def _on_path(folder: Path) -> bool:
    wanted = os.path.normcase(str(folder)).rstrip("\\/")
    return any(os.path.normcase(part).rstrip("\\/") == wanted
               for part in os.environ.get("PATH", "").split(os.pathsep) if part)


def _windows() -> tuple[bool, str]:
    local = os.environ.get("LOCALAPPDATA")
    apps = Path(local) / "Microsoft" / "WindowsApps" if local else None
    folder = apps if apps is not None and apps.is_dir() and _on_path(apps) else DATA_DIR / "bin"
    folder.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        (folder / f"{name}.cmd").write_text(
            f'@echo off\r\ncall "{ROOT / "start.bat"}" %*\r\n', encoding="ascii", errors="replace")
    if not _on_path(folder) and folder != apps:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", PATH_SCRIPT],
            env=dict(os.environ, NL_DIR=str(folder)), capture_output=True, timeout=30,
            stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if done.returncode != 0:
            return False, f"Created the commands in {folder} but could not add it to your PATH"
    return True, "Added the 'netlab' and 'nl' commands. Open a new terminal and type: netlab  (or: nl)"


def _unix() -> tuple[bool, str]:
    folder = Path.home() / ".local" / "bin"
    folder.mkdir(parents=True, exist_ok=True)
    system = shutil.which("nl")
    clash = system is not None and Path(system) != folder / "nl"
    for name in NAMES:
        path = folder / name
        path.write_text(f"#!/bin/sh\nexec sh {shlex.quote(str(ROOT / 'start.sh'))} \"$@\"\n", encoding="utf-8")
        os.chmod(path, 0o755)
    message = "Added the 'netlab' and 'nl' commands. Type: netlab  (or: nl)"
    if not _on_path(folder):
        message += (f"\n  {folder} is not on your PATH yet. Add this line to your shell profile "
                    f"(~/.bashrc or ~/.zshrc) and open a new terminal:\n"
                    f"  export PATH=\"$HOME/.local/bin:$PATH\"")
    if clash:
        message += (f"\n  Note: this system already has an 'nl' command ({system}). "
                    "'nl' only starts NETLAB DB if ~/.local/bin comes first in your PATH; "
                    "'netlab' always works.")
    return True, message


def create_command() -> tuple[bool, str]:
    try:
        return _windows() if os.name == "nt" else _unix()
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"Could not create the command: {getattr(error, 'strerror', None) or error}"