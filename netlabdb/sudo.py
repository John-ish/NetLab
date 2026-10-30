import asyncio
import os
import shutil
import sys
import time

from .constants import SUDO_LOCKOUT_SECONDS


SUDO_LOCK = {"until": 0.0, "level": 0}


def sudo_lock_remaining() -> float:
    return SUDO_LOCK["until"] - time.monotonic()


def sudo_lock_fail() -> None:
    SUDO_LOCK["until"] = time.monotonic() + SUDO_LOCKOUT_SECONDS * 2 ** min(SUDO_LOCK["level"], 6)
    SUDO_LOCK["level"] += 1


def sudo_lock_clear() -> None:
    SUDO_LOCK["until"] = 0.0
    SUDO_LOCK["level"] = 0


def _verify_windows_password(password: str) -> tuple[bool, str | None]:
    import ctypes
    import getpass
    try:
        token = ctypes.c_void_p()
        granted = ctypes.windll.advapi32.LogonUserW(
            getpass.getuser(), os.environ.get("USERDOMAIN", "."), password, 2, 0, ctypes.byref(token)
        )
        if not granted:
            return False, "Incorrect password"
        ctypes.windll.kernel32.CloseHandle(token)
    except Exception:
        return False, "Could not verify the password on this system"
    return True, None


async def verify_sudo_password(password: str) -> tuple[bool, str | None]:
    if not password:
        return False, "Enter your password"
    if sys.platform.startswith("win"):
        return await asyncio.to_thread(_verify_windows_password, password)
    if shutil.which("sudo") is None:
        return False, "sudo is not available on this system"
    try:
        probe = await asyncio.create_subprocess_exec(
            "sudo", "-n", "-k", "true",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        if await asyncio.wait_for(probe.wait(), 5) == 0:
            return False, "sudo doesn't ask for a password here, so it can't be verified"
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-S", "-k", "-p", "", "-v",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(password.encode() + b"\n"), 10)
    except (OSError, asyncio.TimeoutError):
        return False, "Could not verify the password"
    return (True, None) if proc.returncode == 0 else (False, "Incorrect password")
