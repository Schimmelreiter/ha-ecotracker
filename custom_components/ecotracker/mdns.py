"""Ask the EcoTracker itself for its mDNS service record (serial, product ID).

The EcoTracker announces `_everhome._tcp` with TXT records like `serial=...` and `productid=...`.
Multicast often does not cross from Wi-Fi to the LAN, so the integration asks the device directly
(unicast to port 5353, legacy unicast reply to our port).
"""

from __future__ import annotations

import asyncio
import logging
import socket

from zeroconf import DNSIncoming, DNSOutgoing, DNSPointer, DNSQuestion, DNSText
from zeroconf.const import _CLASS_IN, _FLAGS_QR_QUERY, _TYPE_PTR, _TYPE_TXT

_LOGGER = logging.getLogger(__name__)

SERVICE = "_everhome._tcp.local."
TIMEOUT = 2.0


class _Client(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.answers: asyncio.Queue[bytes] = asyncio.Queue()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.answers.put_nowait(data)


def _query(name: str, rtype: int) -> bytes:
    out = DNSOutgoing(_FLAGS_QR_QUERY, multicast=False)
    out.add_question(DNSQuestion(name, rtype, _CLASS_IN))
    return out.packets()[0]


def parse_txt(raw: bytes) -> dict[str, str]:
    """TXT strings (length-prefixed key=value) to a dict."""
    props: dict[str, str] = {}
    i = 0
    while i < len(raw):
        n = raw[i]
        item = raw[i + 1 : i + 1 + n].decode("utf-8", "replace")
        i += 1 + n
        if "=" in item:
            key, value = item.split("=", 1)
            props[key.lower()] = value
    return props


async def _ask(transport: asyncio.DatagramTransport, client: _Client, name: str, rtype: int) -> list:
    transport.sendto(_query(name, rtype))
    async with asyncio.timeout(TIMEOUT):
        while True:
            msg = DNSIncoming(await client.answers.get())
            records = msg.answers()
            if any(r.name.lower() == name.lower() or r.type == rtype for r in records):
                return records


async def async_mdns_info(host: str, port: int = 5353) -> dict[str, str]:
    """Serial and product ID from the device's TXT record; {} if it does not answer."""
    loop = asyncio.get_running_loop()
    transport = None
    try:
        ip = (await loop.getaddrinfo(host, None, family=socket.AF_INET))[0][4][0]
        transport, client = await loop.create_datagram_endpoint(_Client, remote_addr=(ip, port))
        records = await _ask(transport, client, SERVICE, _TYPE_PTR)
        props = {}
        for rec in records:
            if isinstance(rec, DNSText):
                props.update(parse_txt(rec.text))
        if "serial" not in props:
            ptr = next((r.alias for r in records if isinstance(r, DNSPointer)), None)
            if ptr:
                for rec in await _ask(transport, client, ptr, _TYPE_TXT):
                    if isinstance(rec, DNSText):
                        props.update(parse_txt(rec.text))
        return props
    except (OSError, TimeoutError, IndexError, ValueError) as err:
        _LOGGER.debug("No mDNS answer from %s: %s", host, err)
        return {}
    finally:
        if transport is not None:
            transport.close()
