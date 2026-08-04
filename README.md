# Climote for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant integration for [Climote](https://www.climote.ie/), the remote
heating controller used across Ireland.

Climote does not provide a public API. This integration talks to the same web
endpoints the Climote manager UI uses (`climote.climote.ie`), which is why it
performs a login and carries a session cookie between requests.

## Installation

### HACS (recommended)

1. In HACS, go to **Settings → Add custom repository**.
2. Add `https://github.com/sparkeh/home-assistant-climote` as an
   **Integration**.
3. Click **Explore & download repositories**, search for *Climote* and install it.
4. Restart Home Assistant.

### Manual

Copy the `custom_components/climote` folder into your Home Assistant
`custom_components` directory, then restart Home Assistant.

## Setup

Add the integration via **Settings → Devices & Services → Add Integration →
Climote** and fill in:

| Field                       | Value                                                        |
| --------------------------- | ------------------------------------------------------------ |
| Climote device number       | The number printed on the SIM card holder in your welcome pack (not your phone number) |
| Email address               | The email used to register your Climote account              |
| Password                    | Your Climote account password                                |
| Default boost duration      | How long a boost runs when you switch a zone to heat (0.5–9 h) |
| Full refresh interval       | How often the hub is asked to report its status over SMS (hours) |
| Status poll interval        | How often the cached status is polled (minutes)              |

## How it works

The Climote hub reports its status over SMS. Reading the *cached* status
(`force=0`) is fast and free, so the integration polls it regularly. Asking the
hub for a *fresh* report (`force=1`) costs a text message and can take up to
two minutes, so that is only done:

- automatically after you change something (boost on/off, target temperature), so
  the new state shows up promptly, and
- once per *full refresh interval* to pick up changes made elsewhere.

## Entities

Per active zone the integration creates:

- **Climate** – set the target temperature, turn the heat on (boost) or off.
- **Boost duration (select)** – how long a boost runs for that zone.
- **Boost remaining (sensor)** – minutes left on the current boost as reported
  by the hub.

All entities are grouped under a single **Climote Hub** device.

## Troubleshooting

- **Authentication errors**: your email/device number/password are checked
  against the web UI, so the same credentials you use on climote.climote.ie will
  work here.
- **Slow status updates**: this is expected. The hub communicates over SMS, so
  state changes can take a minute or two to appear.

## Acknowledgements

This integration is a maintained fork of the original
[home-assistant-climote](https://github.com/brianbola90/home-assistant-climote).
The 2026 rewrite was carried out with assistance from AI tooling.
