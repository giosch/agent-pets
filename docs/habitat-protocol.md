# Pet habitat activity protocol v1

A display consumes session facts and chooses its own poses, colors, and layout. This protocol has a separate version namespace from the original Clawd Tank BLE GATT protocol v1/v2. The browser milestone implements HTTP snapshots and Server-Sent Events over loopback TCP.

## Connect a display

Start the host with `python host/habitat.py serve`. Open `GET /v1/events` on the printed address (normally `http://127.0.0.1:19873`). The response is UTF-8 `text/event-stream`. Each unnamed SSE event has one JSON object in its `data` field. A colon-prefixed heartbeat keeps an idle connection open. A polling display can use `GET /v1/snapshot` for current state.

Every new connection receives a complete snapshot first. Replace the local collection with it even if the host’s sequence is lower than a previous connection. Process subsequent updates in sequence order. A slow consumer can receive a fresh snapshot when it falls behind. A reconnect restores persistent attention and activity. Brief events belong only to the live connection on which they arrive.

```json
{"version":1,"type":"snapshot","sequence":12,"sessions":[{"id":"codex:abc","order":2,"activity":"editing","attention":"none","helpers":0}]}
{"version":1,"type":"update","sequence":13,"session":{"id":"codex:abc","order":2,"activity":"idle","attention":"ready","helpers":0},"moment":"completed"}
{"version":1,"type":"remove","sequence":14,"id":"codex:abc"}
```

## Messages and session fields

| Field | Meaning |
|---|---|
| `version` | Integer protocol major version. Implementations using v1 can ignore additional fields. |
| `sequence` | Host revision. It increases for each committed change and is persisted. Duplicate or older deltas within a connection can be ignored. |
| `id` | Opaque stable session identity. The current host namespaces local IDs by runtime. Treat the whole value as a key. |
| `order` | Nonnegative, stable order of appearance. Use it for tie-breaking and deriving a session’s palette while it is open. |
| `activity` | `idle`, `working`, `inspecting`, `editing`, `executing`, `building`, `transferring`, `researching`, `coordinating`, or `external`. A limited endpoint can draw a single working pose for all active categories. |
| `attention` | `none`, `question`, `approval`, `failure`, or `ready`. A normal finished turn remains ready until the chat continues or ends. |
| `helpers` | Number of known active helpers associated with the parent session. |
| `active_calls` | Number of observed tool calls still running in this session. Older hosts can omit this field. |
| `moment` | Optional on an update. Play `forked`, `completed`, `setback`, `compacted`, or `interrupted` once, then return to the current pose. An outstanding blocking alert has priority. |

A session start explicitly marked `source: "fork"` produces a split reaction for that child once. Snapshots carry no moments.

An update replaces the entire record for its session and a remove deletes that ID. An empty snapshot represents an available host with no open sessions. A disconnected transport represents loss of contact. The browser shows those conditions separately. Endpoints can choose their own capacity. Rank question/approval/failure first, ready second, and ordinary activity third, then use increasing `order`.

The host retains normalized identifiers needed to correlate tool requests, turns, and helpers. Raw prompts, diffs, paths, and tool results are excluded from the display stream. Register hooks once for each local runtime. Current hooks write normalized observations into a per-user SQLite inbox, then notify the host through an authenticated loopback request. The host drains the inbox before publishing its connection information on startup. A session that closed during downtime therefore disappears from the restored snapshot.

## Renderer packs

Built-in authoring manifests live under `assets/habitat/packs`. A character supplies an `idle` SVG and optional pose artwork. A habitat supplies a `scene` SVG. Use the `colors` map for character source colors named `body`, `shadow`, and `accent`. The browser exporter substitutes the session palette and sets `data-pose` on the SVG root, so a single SVG can express several poses. Characters can fall back to their idle drawing for unsupported poses.

```sh
python host/habitat.py export-pack character fox fox.zip
python host/habitat.py export-pack habitat grove grove.zip
python host/habitat.py install-pack fox.zip
```

The SVG renderer’s archive contains a format-1 `manifest.json` and its referenced SVG files. Install writes a validated copy in the local habitat’s `packs` directory. Restart the host to load it. Characters and habitats with separate IDs can be mixed freely. A new hardware renderer can use its own format and exporter. Its activity messages stay the same.

Pixel-art characters can instead provide an optional `fur_palettes` list (1–32
palettes). Each palette has exactly `fur.shadow`, `fur.base`, and `fur.highlight`
hex colors. Set `colors` to `{}` when using this mode. SVG elements tagged with
`data-material="fur.base"` (or either of the other fur roles) receive that role's
fill; all other elements retain their source colors, even if their RGB values
match fur. The session variant selects a palette modulo the list length. This
optional format-1 extension leaves legacy `colors` packs unchanged. See the
[Monke pilot pipeline](../../tools/monke/README.md) for authoring and previews.

## Physical transport work

The live JSON meanings above are the common contract. A native TCP or USB serial binding can delimit complete records with newlines. A BLE binding also needs a tested fragmentation and reassembly scheme for the negotiated MTU. The first hardware milestone must verify discovery, framing, the initial snapshot, and resynchronization on disconnect on a real device. The existing board’s BLE service still speaks its documented [Clawd Tank protocol](protocol-changelog.md).
