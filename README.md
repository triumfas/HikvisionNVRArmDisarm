# Hikvision NVR Arm/Disarm

Home Assistant custom integration that arms and disarms **Hik-Connect push notifications** on a Hikvision NVR, with a single switch.

## How it works

Hik-Connect sends push notifications only for events whose linkage has **Notify Surveillance Center** enabled. The integration adds or removes
`<notificationMethod>center</notificationMethod>` on the selected event triggers through ISAPI (`/ISAPI/Event/triggers/<id>`), then reads the NVR back to verify.

- **On** = armed (push notifications are sent), **Off** = disarmed (none are sent).
- The Hik-Connect app itself stays armed all the time; the NVR decides what gets sent.
- State is read from the NVR every minute, so changes made in the NVR UI show up too.
- If only some of the selected events are armed the switch state is *unknown* (attribute `partial: true`).

Verified on a DS-7608NI-M2/8P (firmware V5.04.087) with DS-2CD2347G2H-LISU/SL cameras.

### Good to know

- **Motion events reach Home Assistant only while armed.** The NVR's event stream (`alertStream`, used by e.g. `hikvision_next`) is fed by the same
  *Notify Surveillance Center* linkage, so disarming silences it too. Use another source if you need motion sensors while disarmed.
- The NVR may accept **only SHA-256 digest** authentication (as the test NVR does). This integration implements it (MD5 digest too), which is why plain
  `curl --digest` / `rest_command` do not work against such NVRs.
- The NVR username is **case-sensitive**.

## Requirements

- Home Assistant 2025.1 or newer, able to reach the NVR over HTTP.
- An NVR user with **Remote: Parameters Settings** (Configuration → System → User Management). Create a dedicated user for this.

## Install

Copy `custom_components/hikvision_nvr_arm` into your Home Assistant `config/custom_components/` folder (or add this repository to HACS as a custom repository),
restart Home Assistant, then *Settings → Devices & services → Add integration → Hikvision NVR Arm/Disarm*.

The setup asks for the NVR host and credentials, then which events to control. The events that are armed right now are preselected, so set up
the integration while the NVR is armed. Change the selection later under *Configure*.

## Entities

| Entity | Description |
| --- | --- |
| `switch.<nvr>_hik_connect_notifications` | On = armed. Attributes: `armed_events`, `disarmed_events`, `partial`. |

Turning the switch on or off raises an error (visible in the UI, usable in automations with `continue_on_error`) if any event could not be changed or the read-back
does not match.

## Tools

`tools/` has PowerShell scripts used while developing this (`hik-notify.ps1` arm/disarm/status, `hik-events.ps1` event stream listener) and
`tests/live_api_check.py` checks the API client against a real NVR. They read credentials from `NVR_USER` / `NVR_PASS` environment variables.
