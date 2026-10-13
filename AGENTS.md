# AGENTS.md

Priority: first in line after the Zigbee release. Do NOT start plugin work yet.

Hive-wide rules: `~/dev/shared-memory/COMMON.md` (imported via `~/AGENTS.md`). Hive name for this lane: **ha-plugin**.
Workspace: `~/dev/ha-plugin` (git worktree of `~/dev/github/ha-poe-plugin`, remote github.com/exavizco/ha-poe-plugin).
Read `agent-memory/MEMORY.md` first. Add durable lessons there.

## Source of truth

- GitHub `exavizco/ha-poe-plugin` is the canonical repo and the only one customers know about.
- The local clone `~/dev/github/ha-poe-plugin` and this worktree `~/dev/ha-plugin` are working copies.
- All releases and pushes go to GitHub. Any Forgejo copy or mirror (for example the old private `shannon/ha-client-plugin`) is secondary and is not a release source.
- Lane setup files (this AGENTS.md, `agent-memory/`) stay off the public main branch unless they genuinely belong there.

## Ownership
- The Exaviz Home Assistant plugin: code (`custom_components/`, `lovelace-cards/`), tests, releases (HACS, PLUGIN_VERSION).
- The exa-pedia HA setup guide (`~/dev/documentation/content/en/docs/home-assistant/`). Edits go through the docs lane's normal PR flow.
- The facts behind the site's "Works with Home Assistant" claims (`~/dev/exaviz.com/layouts/index.html`, band `#h-ha`). If a claim is not true in a shipped release, tell Marketing.

## HA anywhere
The plugin connects to a Cruiser over the LAN. Customers never move HA onto the board.
Exaviz Management M2 epic #458. Mgmt owns the board side; this lane owns #463 and the plugin side of the rest:
- #459 versioned exaviz-mgmt HTTPS API plus SSE push (consume it, no polling)
- #460 pairing code, scoped revocable token, TLS pinned on first use
- #461 mDNS `_exaviz._tcp` discovery (zeroconf in the config flow, manual IP fallback)
- #462 Zigbee network radio to a remote HA (ZHA / Zigbee2MQTT socket URL)
- #463 HA plugin: config flow, zeroconf, pairing, entities (PoE switches, wattage, health)
- #464 off-LAN later via #446, never cloud

## Zigbee
- Plugin shows Zigbee coordinator status and a helper message when Zigbee firmware is not installed.
- Draft wording: "You don't have Zigbee firmware installed on this Cruiser board." Final wording needs Shannon's approval. Keep it one easy-to-change string.
- Current fact (#175): PoE does not run alongside the bench Zigbee RCP firmware on the ESP32-C6. Never claim both work together until a combined firmware is verified.
- Customer CLI install path (exaviz-tools) for Zigbee firmware: os-support owns the CLI; coordinate there.

## Coordination
- os-support: #175 (Zigbee firmware, exaviz-tools).
- Exaviz Management: #455, #446, epic #458.
- Marketing: any public copy. Nothing public without Shannon's OK.
- Reach Shannon only through ATC (message-atc / spool). Never ping him directly.

## Rules
- Hive style, no em dashes.
- Internal services use admin/admin.
- TDD. Opus plans, Grok 4.7 review, Sonnet code.
- e2e: HA container `ha-zig-test` on the Mac (localhost:8123, admin/admin) against board .51.
- Never use "Axzez" publicly. Be careful naming Frigate.
