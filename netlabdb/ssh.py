import asyncio
import base64
import hashlib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .config import KEY_PATH, KEY_PUB_PATH, KNOWN_HOSTS, SSH_DIR, ensure_private_dir, secure_path
from .constants import SSH_CONNECT_TIMEOUT, SSH_DEFAULT_PORT, SSH_MISSING
from .store import store


SSH_TOOLS = ("ssh", "ssh-keygen", "ssh-keyscan")
PUBKEY_RE = re.compile(r"^ssh-ed25519 [A-Za-z0-9+/=]+(?: [A-Za-z0-9._@-]+)?$")

INSTALL_SCRIPT = """umask 077
mkdir -p "$HOME/.ssh" || exit 1
touch "$HOME/.ssh/authorized_keys" || exit 1
chmod 700 "$HOME/.ssh"
chmod 600 "$HOME/.ssh/authorized_keys"
grep -qF -- '{blob}' "$HOME/.ssh/authorized_keys" || printf '%s\\n' '{line}' >> "$HOME/.ssh/authorized_keys"
"""


class SshError(Exception):

    def __init__(self, message: str, fatal: bool = False, kind: str = ""):
        super().__init__(message)
        self.message = message
        self.fatal = fatal
        self.kind = kind


def ssh_reason(text: str, code: int) -> SshError:
    lowered = text.lower()
    if "identification has changed" in lowered:
        return SshError("Host key changed. Press [s] to review it", True, "changed")
    if "host key verification failed" in lowered:
        return SshError("Host key not trusted yet. Press [s] for SSH setup", True, "hostkey")
    if "permission denied" in lowered:
        return SshError("SSH key login failed. Press [s] for SSH setup", True, "auth")
    if "timed out" in lowered:
        return SshError("SSH connection timed out")
    if "refused" in lowered:
        return SshError("SSH connection refused. Is sshd running?")
    if "could not resolve" in lowered:
        return SshError("Could not resolve host")
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return SshError(lines[-1][:80] if lines else f"SSH exited with code {code}")


def ssh_command(address: str, user: str, port: int, remote: str, password_auth: bool = False) -> list[str]:
    options = [
        f"BatchMode={'no' if password_auth else 'yes'}",
        f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "StrictHostKeyChecking=yes",
        f'UserKnownHostsFile="{KNOWN_HOSTS.as_posix()}"',
        "HashKnownHosts=no",
        "ServerAliveInterval=5",
        "ServerAliveCountMax=3",
        "LogLevel=ERROR",
        "ForwardAgent=no",
        "ForwardX11=no",
        "ClearAllForwardings=yes",
        "PermitLocalCommand=no",
    ]
    command = ["ssh", "-T"]
    if password_auth:
        options += ["PubkeyAuthentication=no", "PreferredAuthentications=password,keyboard-interactive",
                    "NumberOfPasswordPrompts=1"]
    elif KEY_PATH.exists():
        command += ["-i", KEY_PATH.as_posix()]
        options.append("IdentitiesOnly=yes")
    for option in options:
        command += ["-o", option]
    return command + ["-p", str(port), "-l", user, "--", address, remote]


def write_askpass(directory: Path) -> Path:
    if sys.platform.startswith("win"):
        path = directory / "askpass.cmd"
        path.write_text('@echo off\r\npowershell -NoProfile -NonInteractive -Command '
                        '"[Console]::Out.WriteLine($env:NETLAB_ASKPASS)"\r\n', encoding="ascii")
    else:
        path = directory / "askpass.sh"
        path.write_text('#!/bin/sh\nprintf \'%s\\n\' "$NETLAB_ASKPASS"\n', encoding="ascii")
        os.chmod(path, 0o700)
    return path


async def ssh_run(address: str, user: str, port: int, remote: str, timeout: float = 20,
                  stdin_text: str | None = None, password: str | None = None) -> tuple[int, str, str]:
    env, helper, extra = None, None, {}
    if password is not None:
        helper = Path(tempfile.mkdtemp(prefix="askpass-", dir=ensure_private_dir(SSH_DIR)))
        env = dict(os.environ)
        env.update(SSH_ASKPASS=str(write_askpass(helper)), SSH_ASKPASS_REQUIRE="force",
                   DISPLAY=os.environ.get("DISPLAY") or "netlabdb:0", NETLAB_ASKPASS=password)
        if not sys.platform.startswith("win"):
            extra["start_new_session"] = True
    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_command(address, user, port, remote, password is not None),
            stdin=asyncio.subprocess.DEVNULL if stdin_text is None else asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            **extra,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(None if stdin_text is None else stdin_text.encode()), timeout)
        except asyncio.TimeoutError:
            return 255, "", "SSH connection timed out"
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
    finally:
        if helper is not None:
            shutil.rmtree(helper, ignore_errors=True)
    return proc.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")


def ssh_missing_tools() -> list[str]:
    return [tool for tool in SSH_TOOLS if shutil.which(tool) is None]


def ssh_install_hint() -> str:
    if sys.platform.startswith("win"):
        return "Install it from Settings > System > Optional features > OpenSSH Client"
    return "Install it with your package manager, e.g. sudo apt install openssh-client"


def ssh_service_port(host: str) -> int | None:
    return next((p for n, p, _ in store.services_of(host) if n.lower() == "ssh"), None)


def host_spec(address: str, port: int) -> str:
    return address if port == SSH_DEFAULT_PORT else f"[{address}]:{port}"


def key_fingerprint(blob: str) -> str:
    raw = base64.b64decode(blob)
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")


def parse_scan(text: str) -> list[tuple[str, str, str]]:
    keys = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and not line.startswith("#"):
            try:
                key_fingerprint(parts[2])
            except ValueError:
                continue
            keys.append((parts[1], parts[2], " ".join(parts[:3])))
    return keys


async def learn_keys_with_ssh(address: str, port: int) -> list[tuple[str, str, str]]:
    ensure_private_dir(SSH_DIR)
    scratch = Path(tempfile.mkdtemp(prefix="scan-", dir=SSH_DIR))
    known = scratch / "known_hosts"
    text = ""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-T",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f'UserKnownHostsFile="{known.as_posix()}"',
            "-o", "HashKnownHosts=no", "-o", "PreferredAuthentications=none",
            "-o", "LogLevel=ERROR", "-p", str(port), "-l", "netlab-probe", "--", address, "exit",
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), 25)
        except asyncio.TimeoutError:
            proc.kill()
        if known.exists():
            text = known.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return parse_scan(text)


async def scan_host_keys(address: str, port: int) -> list[tuple[str, str, str]]:
    detail = ""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh-keyscan", "-T", "10", "-p", str(port), address,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        raise SshError(SSH_MISSING, True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 30)
        lines = [line.strip() for line in err.decode(errors="ignore").splitlines()
                 if line.strip() and not line.startswith("#")]
        detail = lines[-1][:70] if lines else ""
    except asyncio.TimeoutError:
        proc.kill()
        out = b""
        detail = "timed out"
    keys = parse_scan(out.decode(errors="ignore"))
    if not keys:
        keys = await learn_keys_with_ssh(address, port)
    if not keys:
        raise SshError(f"No host key received from {address}:{port}"
                       + (f" ({detail})" if detail else ". Check the SSH port, the firewall and that sshd is running"))
    return keys


def known_keys(address: str, port: int) -> dict[str, str]:
    spec, found = host_spec(address, port), {}
    try:
        lines = KNOWN_HOSTS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        parts = line.split()
        if len(parts) >= 3 and spec in parts[0].split(","):
            found[parts[1]] = parts[2]
    return found


def save_host_keys(lines: list[str]) -> None:
    ensure_private_dir(SSH_DIR)
    with open(KNOWN_HOSTS, "a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
    secure_path(KNOWN_HOSTS)


def forget_host(address: str, port: int) -> None:
    spec = host_spec(address, port)
    try:
        lines = KNOWN_HOSTS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    kept = [line for line in lines if spec not in (line.split() or [""])[0].split(",")]
    KNOWN_HOSTS.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    secure_path(KNOWN_HOSTS)


async def ensure_keypair() -> str:
    if not KEY_PATH.exists() or not KEY_PUB_PATH.exists():
        ensure_private_dir(SSH_DIR)
        for stale in (KEY_PATH, KEY_PUB_PATH):
            stale.unlink(missing_ok=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "netlabdb", "-f", str(KEY_PATH),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            raise SshError(SSH_MISSING, True)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), 30)
        except asyncio.TimeoutError:
            proc.kill()
            raise SshError("Creating the SSH key timed out")
        if proc.returncode != 0 or not KEY_PATH.exists() or not KEY_PUB_PATH.exists():
            detail = err.decode(errors="ignore").strip().splitlines()
            raise SshError("Could not create the SSH key" + (f": {detail[-1][:60]}" if detail else ""))
        secure_path(KEY_PATH)
    pub = KEY_PUB_PATH.read_text(encoding="ascii", errors="ignore").strip()
    if not PUBKEY_RE.match(pub):
        raise SshError("The NETLAB SSH key is not a valid ed25519 key. Delete the ssh folder in ~/.netlabdb to recreate it", True)
    return pub


def authorized_line(pub: str) -> str:
    return f"no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty {pub}"


async def remote_missing_tools(address: str, user: str, port: int) -> list[str]:
    code, out, _ = await ssh_run(
        address, user, port,
        "for c in awk ps df; do command -v $c >/dev/null 2>&1 || printf '%s ' $c; done; echo")
    return out.split() if code == 0 else []


async def detect_os(address: str, user: str, port: int) -> str:
    if shutil.which("ssh") is None:
        raise SshError(SSH_MISSING, True)
    try:
        code, out, err = await ssh_run(address, user, port, "uname -s")
    except OSError:
        raise SshError(SSH_MISSING, True)
    if code == 255:
        raise ssh_reason(err, code)
    if code == 0:
        if out.strip().lower() == "linux":
            return "linux"
        raise SshError(f"Unsupported system: {out.strip() or 'unknown'}", True)
    raise SshError("Only Linux servers can be monitored", True)
