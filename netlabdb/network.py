import asyncio
import ipaddress
import re
import socket
import ssl
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from http import HTTPStatus


HOSTNAME_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
PING_MISSING = "ping is not available on this system"
PROBE_IO_TIMEOUT = 2
BANNER_PORTS = {21, 22, 25, 110, 143, 3306}


def address_kind(value: str) -> str | None:
    try:
        ipaddress.ip_address(value)
        return "ip"
    except ValueError:
        pass
    if len(value) > 253 or re.fullmatch(r"[\d.]+", value):
        return None
    labels = value.rstrip(".").split(".")
    if all(HOSTNAME_LABEL.match(label) for label in labels):
        return "hostname"
    return None


def normalize_address(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return value.lower().rstrip(".")


def ping_command(address: str) -> list[str]:
    if sys.platform.startswith("win"):
        return ["ping", "-n", "1", "-w", "2000", address]
    if sys.platform == "darwin":
        return ["ping", "-c", "1", "-W", "2000", address]
    return ["ping", "-c", "1", "-W", "2", address]


def run_ping(address: str) -> tuple[int, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    done = subprocess.run(ping_command(address), capture_output=True, timeout=6,
                          stdin=subprocess.DEVNULL, creationflags=flags)
    return done.returncode, done.stdout.decode(errors="ignore")


async def probe_host(address: str) -> tuple[str | None, float | None, str | None]:
    if address_kind(address) is None:
        return None, None, "Invalid address"
    loop = asyncio.get_running_loop()
    try:
        info = await asyncio.wait_for(loop.getaddrinfo(address, None), 3)
    except (socket.gaierror, asyncio.TimeoutError, OSError):
        return None, None, f"Could not resolve “{address}”"
    resolved = info[0][4][0]
    try:
        code, text = await asyncio.to_thread(run_ping, address)
    except FileNotFoundError:
        return resolved, None, PING_MISSING
    except subprocess.TimeoutExpired:
        return resolved, None, "No response (timed out)"
    except OSError:
        return resolved, None, "No response from host"
    match = re.search(r"time[=<]\s*([\d.]+)", text)
    if code == 0 and match:
        return resolved, float(match.group(1)), None
    return resolved, None, "No response from host"


async def probe_service(address: str, port: int, protocol: str) -> tuple[float | None, str | None]:
    if protocol == "UDP":
        return None, "UDP services can't be probed directly"
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(address, port), 3)
    except asyncio.TimeoutError:
        return None, "Connection timed out"
    except ConnectionRefusedError:
        return None, "Connection refused"
    except OSError as error:
        return None, error.strerror or "Connection failed"
    elapsed = (loop.time() - started) * 1000
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return elapsed, None


@lru_cache(maxsize=1)
def probe_tls_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def new_probe(error: str | None = None) -> dict:
    return {"latency": None, "error": error, "alive": False, "alive_ms": None,
            "banner": None, "http": None, "cert_days": None}


def http_phrase(code: int) -> str:
    try:
        return HTTPStatus(code).phrase
    except ValueError:
        return ""


def _der(data: bytes, position: int) -> tuple[int, int, int]:
    tag = data[position]
    size = data[position + 1]
    start = position + 2
    if size & 0x80:
        count = size & 0x7F
        size = int.from_bytes(data[start:start + count], "big")
        start += count
    return tag, start, start + size


def certificate_days(der: bytes) -> int | None:
    try:
        _, body, _ = _der(der, 0)
        _, cursor, _ = _der(der, body)
        tag, _, end = _der(der, cursor)
        if tag == 0xA0:
            tag, _, end = _der(der, end)
        for _ in range(2):
            _, _, end = _der(der, end)
        _, valid, _ = _der(der, end)
        _, _, after = _der(der, valid)
        tag, start, stop = _der(der, after)
        text = der[start:stop].decode("ascii").rstrip("Z")
        expiry = datetime.strptime(text, "%y%m%d%H%M%S" if tag == 0x17 else "%Y%m%d%H%M%S")
        return (expiry.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
    except Exception:
        return None


def parse_banner(data: bytes) -> str | None:
    if not data:
        return None
    if len(data) > 5 and data[4] == 0x0A:
        end = data.find(b"\0", 5)
        if end > 5:
            return "MySQL " + data[5:end].decode("ascii", "ignore")
    lines = data.decode("latin-1").splitlines()
    text = "".join(c for c in (lines[0] if lines else "") if c.isprintable()).strip()
    return text[:40] or None


async def probe_service_details(address: str, port: int, protocol: str) -> dict:
    result = new_probe()
    if address_kind(address) is None:
        result["error"] = "Invalid address"
        return result
    if protocol == "UDP":
        result["error"] = "UDP services can't be probed directly"
        return result
    loop = asyncio.get_running_loop()
    options = {}
    if protocol == "HTTPS":
        options = {"ssl": probe_tls_context(), "server_hostname": address}
    started = loop.time()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(address, port, **options), 3)
    except asyncio.TimeoutError:
        result["error"] = "Connection timed out"
        return result
    except ConnectionRefusedError:
        result.update(error="Connection refused", alive=True, alive_ms=(loop.time() - started) * 1000)
        return result
    except ssl.SSLError:
        result.update(error="TLS handshake failed", alive=True, alive_ms=(loop.time() - started) * 1000)
        return result
    except OSError as error:
        result["error"] = error.strerror or "Connection failed"
        return result
    elapsed = (loop.time() - started) * 1000
    result.update(latency=elapsed, alive=True, alive_ms=elapsed)
    try:
        if protocol == "HTTPS":
            tls = writer.get_extra_info("ssl_object")
            der = tls.getpeercert(binary_form=True) if tls else None
            if der:
                result["cert_days"] = certificate_days(der)
        if protocol in ("HTTP", "HTTPS"):
            request = f"HEAD / HTTP/1.0\r\nHost: {address}\r\nUser-Agent: netlabdb\r\nConnection: close\r\n\r\n"
            writer.write(request.encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), PROBE_IO_TIMEOUT)
            match = re.match(r"HTTP/\d(?:\.\d)?\s+(\d{3})", line.decode("latin-1"))
            if match:
                result["http"] = (int(match.group(1)), round((loop.time() - started) * 1000))
        elif port in BANNER_PORTS:
            result["banner"] = parse_banner(await asyncio.wait_for(reader.read(128), 1))
    except (asyncio.TimeoutError, OSError):
        pass
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return result
