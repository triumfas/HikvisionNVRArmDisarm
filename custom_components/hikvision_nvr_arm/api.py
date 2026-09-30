"""Minimal ISAPI client for arming/disarming Hik-Connect notifications on a Hikvision NVR.

Hik-Connect push is sent only when an event's linkage contains
<notificationMethod>center</notificationMethod> ("Notify Surveillance Center").
Arm = add that block, disarm = remove it.

Newer NVR firmware offers only SHA-256 digest authentication, which aiohttp/httpx
do not do out of the box, so digest is implemented here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import os
import re

import aiohttp

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

CENTER_RE = re.compile(r"<notificationMethod>\s*center\s*</notificationMethod>")
CENTER_BLOCK_RE = re.compile(
    r"<EventTriggerNotification>\s*<id>center</id>.*?</EventTriggerNotification>\s*",
    re.S,
)
CENTER_BLOCK = (
    "<EventTriggerNotification>\n<id>center</id>\n"
    "<notificationMethod>center</notificationMethod>\n</EventTriggerNotification>\n"
)
TRIGGER_RE = re.compile(r"<EventTrigger\s*>.*?</EventTrigger>", re.S)
CHALLENGE_RE = re.compile(r'(\w+)=(?:"([^"]*)"|([^\s,]+))')

_HASHES = {
    "MD5": hashlib.md5,
    "SHA-256": hashlib.sha256,
    "SHA-512-256": lambda data: hashlib.new("sha512_256", data),
}


class HikNvrError(Exception):
    """Cannot talk to the NVR."""


class HikAuthError(HikNvrError):
    """Wrong username or password."""


class HikPermissionError(HikNvrError):
    """The user lacks the rights for the operation."""


@dataclass(frozen=True)
class Trigger:
    """One event linkage on the NVR (e.g. fielddetection-2)."""

    id: str
    event_type: str
    channel: int | None
    armed: bool


def _tag(block: str, name: str) -> str | None:
    match = re.search(rf"<{name}>([^<]*)</{name}>", block)
    return match.group(1) if match else None


class HikNvrClient:
    """Talks ISAPI with SHA-256 (or MD5) digest authentication."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._base = f"http://{host}:{port}"
        self._username = username
        self._password = password
        self._lock = asyncio.Lock()

    async def _request(self, method: str, path: str, body: str | None = None) -> str:
        url = f"{self._base}{path}"
        data = body.encode() if body else None
        headers = {"Content-Type": "application/xml"} if body else {}
        try:
            async with self._session.request(
                method, url, timeout=REQUEST_TIMEOUT, headers=headers or None
            ) as challenge:
                if challenge.status != 401:
                    return await self._finish(challenge)
                header = challenge.headers.get("WWW-Authenticate", "")
            headers["Authorization"] = self._digest(method, path, header)
            async with self._session.request(
                method, url, data=data, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                return await self._finish(response)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise HikNvrError(f"Cannot reach NVR: {err}") from err

    @staticmethod
    async def _finish(response: aiohttp.ClientResponse) -> str:
        text = await response.text()
        if response.status == 401:
            raise HikAuthError("Invalid credentials")
        if response.status == 403 or "lowPrivilege" in text:
            raise HikPermissionError("Insufficient NVR user permissions")
        if response.status != 200:
            raise HikNvrError(f"NVR returned HTTP {response.status}: {text[:200]}")
        return text

    def _digest(self, method: str, path: str, header: str) -> str:
        if not header.lower().startswith("digest"):
            raise HikNvrError("NVR did not offer digest authentication")
        ch = {k: a or b for k, a, b in CHALLENGE_RE.findall(header)}
        algorithm = ch.get("algorithm", "MD5")
        hash_fn = _HASHES.get(algorithm.upper())
        if hash_fn is None:
            raise HikNvrError(f"Unsupported digest algorithm {algorithm}")

        def h(value: str) -> str:
            return hash_fn(value.encode()).hexdigest()

        cnonce = os.urandom(8).hex()
        nc = "00000001"
        ha1 = h(f"{self._username}:{ch['realm']}:{self._password}")
        ha2 = h(f"{method}:{path}")
        response = h(f"{ha1}:{ch['nonce']}:{nc}:{cnonce}:auth:{ha2}")
        parts = [
            f'username="{self._username}"',
            f'realm="{ch["realm"]}"',
            f'nonce="{ch["nonce"]}"',
            f'uri="{path}"',
            f"algorithm={algorithm}",
            "qop=auth",
            f"nc={nc}",
            f'cnonce="{cnonce}"',
            f'response="{response}"',
        ]
        if "opaque" in ch:
            parts.append(f'opaque="{ch["opaque"]}"')
        return "Digest " + ", ".join(parts)

    async def device_info(self) -> dict[str, str]:
        """Return name/model/serial (also serves as a credentials check)."""
        text = await self._request("GET", "/ISAPI/System/deviceInfo")
        return {
            "name": _tag(text, "deviceName") or "NVR",
            "model": _tag(text, "model") or "NVR",
            "serial": _tag(text, "serialNumber") or _tag(text, "deviceID") or "",
            "firmware": _tag(text, "firmwareVersion") or "",
        }

    async def list_triggers(self) -> list[Trigger]:
        """All per-channel event linkages and whether Notify Surveillance Center is set."""
        text = await self._request("GET", "/ISAPI/Event/triggers")
        triggers = []
        for block in TRIGGER_RE.findall(text):
            channel = _tag(block, "dynVideoInputChannelID")
            trigger_id = _tag(block, "id")
            if channel is None or trigger_id is None:
                continue  # skip IO, disk, network events
            triggers.append(
                Trigger(
                    id=trigger_id,
                    event_type=_tag(block, "eventType") or "",
                    channel=int(channel),
                    armed=bool(CENTER_RE.search(block)),
                )
            )
        return triggers

    async def set_armed(self, trigger_ids: list[str], armed: bool) -> list[str]:
        """Set the center linkage on the given triggers. Returns ids that failed."""
        failed: list[str] = []
        async with self._lock:
            for trigger_id in trigger_ids:
                path = f"/ISAPI/Event/triggers/{trigger_id}"
                try:
                    xml = await self._request("GET", path)
                    xml = xml[xml.index("<?xml") :] if "<?xml" in xml else xml
                    if bool(CENTER_RE.search(xml)) == armed:
                        continue
                    if armed:
                        new = xml.replace(
                            "</EventTriggerNotificationList>",
                            CENTER_BLOCK + "</EventTriggerNotificationList>",
                        )
                    else:
                        new = CENTER_BLOCK_RE.sub("", xml)
                    reply = await self._request("PUT", path, new)
                    if "<statusString>OK" not in reply:
                        failed.append(trigger_id)
                except (HikAuthError, HikPermissionError):
                    raise
                except HikNvrError:
                    failed.append(trigger_id)
        return failed
