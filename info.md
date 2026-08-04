# Climote

Home Assistant integration for [Climote](https://www.climote.ie/) smart heating
controls. Climote has no public API, so this integration drives the same web
endpoints as the manager UI at climote.climote.ie.

## Installation

1. In HACS go to **Settings → Add custom repository**.
2. Add `https://github.com/sparkeh/home-assistant-climote` as an
   **Integration**.
3. Click **Explore & download repositories**, search for *Climote* and install.
4. Restart Home Assistant, then add the integration under **Settings → Devices
   & Services**.

You will need your Climote device number (on the SIM card holder in your
welcome pack), the email and password for your Climote account.

## Acknowledgements

Maintained fork of the original
[home-assistant-climote](https://github.com/brianbola90/home-assistant-climote);
the 2026 rewrite was carried out with assistance from AI tooling.
