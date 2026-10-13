# ha-plugin MEMORY

Status: first in line after the Zigbee release. Do not start plugin work yet.

## Where things live
- Plugin code: `~/dev/github/ha-poe-plugin` (github.com/exavizco/ha-poe-plugin); lane worktree `~/dev/ha-plugin`. Branch `feat/zigbee-status` in the main checkout has in-progress Zigbee status work (dashboard helper) from os-support.
- Site band "Works with Home Assistant": `~/dev/exaviz.com/layouts/index.html` (`#h-ha`), also `layouts/products/product.html`.
- exa-pedia HA guide: `~/dev/documentation/content/en/docs/home-assistant/` (exa-pedia.com/docs/home-assistant/).

## HA anywhere (M2)
Epic #458: #459 API+SSE, #460 pairing/token/TOFU TLS, #461 mDNS `_exaviz._tcp`, #462 Zigbee network radio, #463 plugin (ours), #464 off-LAN via #446. Mgmt owns board side.

## #175 Zigbee facts (2026-10-13)
- ESP32-C6 coordinator on .51 served by ziggurat at ws://192.168.86.51:9999 (OpenThread RCP on /dev/ttyAMA4).
- HA test container ha-zig-test on the Mac: localhost:8123, admin/admin (bench login also kept for scripts).
- Third Reality plug joined 4:41 PM ET 10/13, ieee 4c:e1:75:53:58:b2:00:00.
- Bench Zigbee firmware replaces the PoE firmware, so PoE is down while it runs. No apt or CI build yet.
- Lesson: Shannon's home Zigbee hub grabbed the plug. Turn off other hubs before pairing.
- Lesson: board ships without an antenna on the C6 W.FL connector, so signal is weak.
- Beacon burst is a separate low-priority bug.

## Requirements
- Customer CLI (exaviz-tools) must let customers install Zigbee firmware (os-support owns).
- Helper message drafts, need Shannon's approval:
  - Shannon: "You don't have Zigbee firmware installed on this Cruiser board."
  - Marketing: "Zigbee firmware is not installed on this Cruiser board. Update the board's radio firmware to use Zigbee."

## Contacts
os-support #175. Exaviz Management #455/#446/#458. Marketing for copy. Shannon only via ATC.

## Cautions
- Copy can name Home Assistant; be careful naming Frigate.
- admin/admin for internal services.
- Never use "Axzez" publicly.
