"""Constants for Hikvision NVR Arm/Disarm."""

DOMAIN = "hikvision_nvr_arm"

CONF_TRIGGERS = "triggers"
DEFAULT_PORT = 80
SCAN_INTERVAL_SECONDS = 60

EVENT_NAMES = {
    "VMD": "Motion",
    "fielddetection": "Intrusion",
    "linedetection": "Line crossing",
    "regionEntrance": "Region entrance",
    "regionExiting": "Region exiting",
    "scenechangedetection": "Scene change",
    "tamperdetection": "Tamper",
    "videoloss": "Video loss",
}
