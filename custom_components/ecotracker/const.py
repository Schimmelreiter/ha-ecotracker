"""Constants of the everHome EcoTracker integration."""

from __future__ import annotations

DOMAIN = "ecotracker"
DEFAULT_HOST = "ecotracker.home"
DEFAULT_SCAN_INTERVAL = 15

CONF_SCAN_INTERVAL = "scan_interval"
# watchdog
CONF_SWITCH = "switch"  # upstream switch (socket) that powers the EcoTracker
CONF_OFFLINE_MINUTES = "offline_minutes"
CONF_NOTIFY_ENTITIES = "notify_entities"
CONF_NOTIFY_SERVICES = "notify_services"

DEFAULT_OFFLINE_MINUTES = 15
OFF_SECONDS = 10  # power off this long for a restart
RETRY_MINUTES = 5  # next restart while it stays offline
RETRY_MINUTES_LATE = 60  # ... after LATE_HOURS
LATE_HOURS = 6
