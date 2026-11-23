# everHome EcoTracker for Home Assistant

A Home Assistant custom integration for the [everHome EcoTracker](https://everhome.cloud), the reading head
for electricity meters. It reads the EcoTracker's local JSON API (`http://<host>/v1/json`) and needs no cloud.

## Features

- **Sensors:** current and average power, power per phase (L1 to L3), energy drawn from and fed into the grid
  (kWh, ready for the energy dashboard), Wi-Fi signal strength and network, and the age of the last reading.
- **Two-tariff meters:** energy drawn in tariff 1 and tariff 2. Values the EcoTracker does not deliver
  (for example the tariff counters with a one-tariff meter) are created as disabled entities.
- **Device info:** firmware version, if the EcoTracker reports it, and the serial number, from the JSON API
  or from the EcoTracker's mDNS record (asked directly, so it also works where multicast does not reach).
- **Discovery:** Home Assistant offers EcoTrackers it finds over mDNS (`_everhome._tcp`).
- **Reachable:** a binary sensor that shows whether the EcoTracker answers.
- **Restart button:** switches the EcoTracker off and on again through the switch that powers it.
- **Watchdog (optional):** if you power the EcoTracker through a smart socket, the integration restarts it
  when it has been offline for a set time (default 15 minutes), again every 5 minutes while it stays offline
  and every 60 minutes after 6 hours. It can notify you from the second restart on and once it is back.

## Installation

1. In HACS, open the menu, choose **Custom repositories** and add
   `https://github.com/Schimmelreiter/ha-ecotracker` as an **Integration**.
2. Install **everHome EcoTracker** and restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration** and choose **everHome EcoTracker**.
   Enter the host name or IP address of the EcoTracker (default `ecotracker.home`), or confirm an
   EcoTracker that Home Assistant has found.

## Options

- **Polling interval** (seconds, default 15).
- **Upstream switch:** the switch (smart socket) that powers the EcoTracker. Leave empty to turn off the
  watchdog and the restart button.
- **Restart after minutes offline** (default 15).
- **Notify:** notify entities and/or notify actions (for example `mobile_app_my_phone`). The texts of the
  notifications are in German.

## Notes

- Tested with an EcoTracker on Home Assistant 2026.11.
- Not affiliated with everHome GmbH.
