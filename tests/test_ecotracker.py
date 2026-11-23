"""Tests of the EcoTracker integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from ipaddress import ip_address
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.util import dt as dt_util

from custom_components.ecotracker.const import DOMAIN

URL = "http://ecotracker.home/v1/json"
ANSWER = {
    "power": 512, "powerAvg": 480, "agePower": 1200, "powerPhase1": 100, "powerPhase2": 200,
    "powerPhase3": 212, "energyCounterOut": 1500, "energyCounterIn": 12345678, "rssi": -61, "ssid": "x",
}


@pytest.fixture(autouse=True)
def _custom(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def mdns():
    """No real mDNS or DNS in tests; tests set the TXT answer and the IPs."""
    answer: dict = {}
    ips = {"ecotracker.home": "192.168.75.245", "192.168.75.245": "192.168.75.245"}

    async def info(host, port=5353):
        return dict(answer)

    async def resolve(self, host):
        return ips.get(host)

    with (
        patch("custom_components.ecotracker.async_mdns_info", side_effect=info),
        patch("custom_components.ecotracker.config_flow.async_mdns_info", side_effect=info),
        patch("custom_components.ecotracker.config_flow.EcoTrackerConfigFlow._ip", resolve),
    ):
        yield answer


async def _setup(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="EcoTracker", unique_id="ecotracker.home",
                            data={"host": "ecotracker.home"}, options=options or {})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_flow(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(URL, json=ANSWER)
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert res["type"] is FlowResultType.FORM
    with patch("custom_components.ecotracker.async_setup_entry", return_value=True):
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"host": " EcoTracker.home "})
    assert res["type"] is FlowResultType.CREATE_ENTRY
    assert res["data"] == {"host": "ecotracker.home"}


async def test_flow_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(URL, exc=aiohttp.ClientError())
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"host": "ecotracker.home"})
    assert res["errors"] == {"base": "cannot_connect"}


async def test_options(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(URL, json=ANSWER)
    entry = await _setup(hass)
    res = await hass.config_entries.options.async_init(entry.entry_id)
    res = await hass.config_entries.options.async_configure(
        res["flow_id"], {"scan_interval": 20, "switch": "switch.steckdose_ecotracker", "offline_minutes": 15,
                         "notify_entities": [], "notify_services": ["mobile_app_x"]})
    assert res["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["switch"] == "switch.steckdose_ecotracker"
    assert entry.runtime_data.switch == "switch.steckdose_ecotracker"  # reloaded
    assert hass.states.get("button.ecotracker_restart") is not None


async def test_sensors(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(URL, json=ANSWER)
    await _setup(hass)
    # test HA runs in English -> English entity ids; German ids come from the German system language
    assert float(hass.states.get("sensor.ecotracker_current_consumption").state) == 512
    st = hass.states.get("sensor.ecotracker_energy_import")
    assert float(st.state) == pytest.approx(12345.678)
    assert st.attributes["unit_of_measurement"] == "kWh"
    assert st.attributes["state_class"] == "total_increasing"
    assert float(hass.states.get("sensor.ecotracker_energy_export").state) == pytest.approx(1.5)
    assert float(hass.states.get("sensor.ecotracker_power_l3").state) == 212
    assert hass.states.get("binary_sensor.ecotracker_reachable").state == "on"
    assert hass.states.get("button.ecotracker_restart") is None  # no switch, no button


async def test_offline_at_start(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(URL, exc=aiohttp.ClientError())
    entry = await _setup(hass)
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert hass.states.get("sensor.ecotracker_current_consumption").state == "unavailable"
    assert hass.states.get("binary_sensor.ecotracker_reachable").state == "off"


async def test_watchdog(hass: HomeAssistant, aioclient_mock, freezer) -> None:
    off = async_mock_service(hass, "switch", "turn_off")
    on = async_mock_service(hass, "switch", "turn_on")
    sent = async_mock_service(hass, "notify", "mobile_app_x")
    aioclient_mock.get(URL, json=ANSWER)
    opts = {"scan_interval": 15, "switch": "switch.steckdose_ecotracker", "offline_minutes": 15,
            "notify_services": ["notify.mobile_app_x"]}
    with patch("custom_components.ecotracker.coordinator.asyncio.sleep", AsyncMock()):
        entry = await _setup(hass, opts)
        coord = entry.runtime_data

        async def tick(minutes: float) -> None:
            freezer.tick(timedelta(minutes=minutes))
            async_fire_time_changed(hass, dt_util.utcnow())
            await hass.async_block_till_done()

        aioclient_mock.clear_requests()
        aioclient_mock.get(URL, exc=aiohttp.ClientError())
        await tick(0.5)
        assert coord.offline_since is not None
        await tick(10)
        assert not off  # not yet 15 minutes
        await tick(6)
        assert len(off) == 1 and len(on) == 1 and coord.restarts == 1
        assert not sent  # first restart is silent
        await tick(2)
        assert len(off) == 1  # retry only after 5 minutes
        await tick(4)
        assert len(off) == 2 and coord.restarts == 2
        assert len(sent) == 1 and "offline" in sent[0].data["title"]
        await tick(6)
        assert len(off) == 3 and len(sent) == 1  # no further message
        assert hass.states.get("sensor.ecotracker_watchdog_restarts").state == "3"

        aioclient_mock.clear_requests()
        aioclient_mock.get(URL, json=ANSWER)
        await tick(0.5)
        assert coord.offline_since is None and coord.restarts == 0
        assert len(sent) == 2 and "wieder online" in sent[1].data["title"]
        assert "Neustarts: 3" in sent[1].data["message"]


async def test_watchdog_late_hourly(hass: HomeAssistant, aioclient_mock, freezer) -> None:
    off = async_mock_service(hass, "switch", "turn_off")
    async_mock_service(hass, "switch", "turn_on")
    aioclient_mock.get(URL, exc=aiohttp.ClientError())
    with patch("custom_components.ecotracker.coordinator.asyncio.sleep", AsyncMock()):
        entry = await _setup(hass, {"switch": "switch.s", "offline_minutes": 15})
        coord = entry.runtime_data
        coord.offline_since = dt_util.utcnow() - timedelta(hours=7)
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert len(off) == 1
        assert coord.next_restart - dt_util.utcnow() > timedelta(minutes=55)


async def test_one_success_no_summary(hass: HomeAssistant, aioclient_mock, freezer) -> None:
    async_mock_service(hass, "switch", "turn_off")
    async_mock_service(hass, "switch", "turn_on")
    sent = async_mock_service(hass, "notify", "mobile_app_x")
    aioclient_mock.get(URL, exc=aiohttp.ClientError())
    with patch("custom_components.ecotracker.coordinator.asyncio.sleep", AsyncMock()):
        entry = await _setup(hass, {"switch": "switch.s", "offline_minutes": 1, "notify_services": ["mobile_app_x"]})
        freezer.tick(timedelta(minutes=2))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert entry.runtime_data.restarts == 1
        aioclient_mock.clear_requests()
        aioclient_mock.get(URL, json=ANSWER)
        freezer.tick(timedelta(seconds=20))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert entry.runtime_data.restarts == 0
        assert not sent


async def test_button_while_online(hass: HomeAssistant, aioclient_mock) -> None:
    off = async_mock_service(hass, "switch", "turn_off")
    on = async_mock_service(hass, "switch", "turn_on")
    aioclient_mock.get(URL, json=ANSWER)
    with patch("custom_components.ecotracker.coordinator.asyncio.sleep", AsyncMock()):
        entry = await _setup(hass, {"switch": "switch.s"})
        await hass.services.async_call("button", "press", {"entity_id": "button.ecotracker_restart"}, blocking=True)
        await hass.async_block_till_done()
    assert len(off) == 1 and len(on) == 1
    assert entry.runtime_data.restarts == 0  # no outage, nothing to count
    assert entry.runtime_data.last_restart is not None


async def test_wlan_sensor(hass: HomeAssistant, aioclient_mock, entity_registry) -> None:
    """The Wi-Fi network the EcoTracker reports (diagnostic, off by default)."""
    aioclient_mock.get(URL, json=ANSWER)
    entry = await _setup(hass)
    eid = "sensor.ecotracker_wi_fi_network"
    assert entity_registry.async_get(eid).disabled_by is not None
    entity_registry.async_update_entity(eid, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "x"


async def test_optional_values_disabled_when_missing(hass: HomeAssistant, aioclient_mock, entity_registry) -> None:
    """A one-tariff meter: the tariff counters are created disabled; the delivered values stay enabled."""
    aioclient_mock.get(URL, json=ANSWER)
    await _setup(hass)
    for eid in ("sensor.ecotracker_energy_import_tariff_1", "sensor.ecotracker_energy_import_tariff_2"):
        assert entity_registry.async_get(eid).disabled_by is not None
    for eid in ("sensor.ecotracker_energy_export", "sensor.ecotracker_power_l1", "sensor.ecotracker_average_consumption"):
        assert entity_registry.async_get(eid).disabled_by is None


async def test_two_tariff_meter_and_device_info(hass: HomeAssistant, aioclient_mock, device_registry) -> None:
    """A two-tariff meter: the tariff counters are enabled; serial and firmware go into the device."""
    aioclient_mock.get(URL, json={**ANSWER, "energyCounterInT1": 2000000, "energyCounterInT2": 345678,
                                  "serial": "abc123", "firmwareVersion": "1.2.3"})
    entry = await _setup(hass)
    assert float(hass.states.get("sensor.ecotracker_energy_import_tariff_1").state) == pytest.approx(2000)
    assert float(hass.states.get("sensor.ecotracker_energy_import_tariff_2").state) == pytest.approx(345.678)
    dev = next(iter(device_registry.devices.get_devices_for_config_entry_id(entry.entry_id)))
    assert (dev.serial_number, dev.sw_version) == ("abc123", "1.2.3")


ZC = ZeroconfServiceInfo(
    ip_address=ip_address("192.168.75.245"), ip_addresses=[ip_address("192.168.75.245")], port=80,
    hostname="ecotracker-B43A45DE6E68.local.", type="_everhome._tcp.local.",
    name="ecotracker-B43A45DE6E68._everhome._tcp.local.",
    properties={"productid": "1137", "serial": "3b9ec21c63c4", "ip": "192.168.75.245"},
)


async def test_serial_from_mdns(hass: HomeAssistant, aioclient_mock, device_registry, mdns) -> None:
    mdns["serial"] = "3b9ec21c63c4"
    aioclient_mock.get(URL, json=ANSWER)
    entry = await _setup(hass)
    assert entry.runtime_data.serial == "3b9ec21c63c4"
    device = device_registry.async_get_device(identifiers={(DOMAIN, "ecotracker.home")})
    assert device.serial_number == "3b9ec21c63c4"  # unique ID of old entries stays the host


async def test_flow_uses_serial(hass: HomeAssistant, aioclient_mock, mdns) -> None:
    mdns["serial"] = "3b9ec21c63c4"
    aioclient_mock.get(URL, json=ANSWER)
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch("custom_components.ecotracker.async_setup_entry", return_value=True):
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"host": "ecotracker.home"})
    assert res["type"] is FlowResultType.CREATE_ENTRY
    assert res["result"].unique_id == "3b9ec21c63c4"


async def test_flow_finds_old_entry_by_ip(hass: HomeAssistant, aioclient_mock, mdns) -> None:
    mdns["serial"] = "3b9ec21c63c4"
    aioclient_mock.get("http://192.168.75.245/v1/json", json=ANSWER)
    MockConfigEntry(domain=DOMAIN, unique_id="ecotracker.home", data={"host": "ecotracker.home"}).add_to_hass(hass)
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"host": "192.168.75.245"})
    assert res["type"] is FlowResultType.ABORT
    assert res["reason"] == "already_configured"


async def test_zeroconf(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get("http://192.168.75.245/v1/json", json=ANSWER)
    res = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=ZC)
    assert res["type"] is FlowResultType.FORM
    assert res["step_id"] == "zeroconf_confirm"
    with patch("custom_components.ecotracker.async_setup_entry", return_value=True):
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {})
    assert res["type"] is FlowResultType.CREATE_ENTRY
    assert res["data"] == {"host": "192.168.75.245"}
    assert res["result"].unique_id == "3b9ec21c63c4"


@pytest.mark.parametrize("unique_id", ["ecotracker.home", "3b9ec21c63c4"])
async def test_zeroconf_already_configured(hass: HomeAssistant, unique_id) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=unique_id, data={"host": "ecotracker.home"})
    entry.add_to_hass(hass)
    res = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=ZC)
    assert res["type"] is FlowResultType.ABORT
    assert res["reason"] == "already_configured"
    assert entry.data["host"] == "ecotracker.home"  # the host name the user entered stays


async def test_mdns_unicast(hass: HomeAssistant, socket_enabled) -> None:
    """Real query against a small responder on 127.0.0.1 that answers like the EcoTracker."""
    from zeroconf import DNSIncoming, DNSOutgoing, DNSPointer, DNSText
    from zeroconf.const import _CLASS_IN, _FLAGS_AA, _FLAGS_QR_RESPONSE, _TYPE_PTR, _TYPE_TXT

    from custom_components.ecotracker import mdns as m

    name = "ecotracker-B43A45DE6E68._everhome._tcp.local."
    txt = b"".join(bytes([len(x)]) + x for x in (b"productid=1137", b"serial=3b9ec21c63c4", b"ip=127.0.0.1"))
    asked = []

    class Responder(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            q = DNSIncoming(data).questions[0]
            asked.append(q.type)
            out = DNSOutgoing(_FLAGS_QR_RESPONSE | _FLAGS_AA, multicast=False)
            if q.type == _TYPE_PTR:  # like the device: PTR only, TXT needs a second question
                out.add_answer_at_time(DNSPointer(m.SERVICE, _TYPE_PTR, _CLASS_IN, 120, name), 0)
            else:
                out.add_answer_at_time(DNSText(name, _TYPE_TXT, _CLASS_IN, 120, txt), 0)
            self.transport.sendto(out.packets()[0], addr)

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(Responder, local_addr=("127.0.0.1", 0))
    try:
        port = transport.get_extra_info("sockname")[1]
        assert await m.async_mdns_info("127.0.0.1", port) == {
            "productid": "1137", "serial": "3b9ec21c63c4", "ip": "127.0.0.1"}
        assert asked == [_TYPE_PTR, _TYPE_TXT]
    finally:
        transport.close()


async def test_mdns_no_answer(hass: HomeAssistant, socket_enabled) -> None:
    from custom_components.ecotracker import mdns as m

    with patch.object(m, "TIMEOUT", 0.2):
        assert await m.async_mdns_info("127.0.0.1", 9) == {}
