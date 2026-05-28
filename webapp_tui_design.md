# Lighthouse — Webapp & TUI Design v1.0

> Comprehensive surface design for the Lighthouse research instrument.
> Companion to `lighthouse_design.md` (system architecture).

This document covers **two surfaces**:
1. **Webapp** — the browser dashboard at `http://127.0.0.1:8765/ui/`. Already booted from the Claude Design handoff (React + babel-standalone); this doc extends it from 1 designed page (Home) to 14.
2. **TUI** — a new Textual-based terminal surface for headless / SSH use, parity with the webapp on every read path and most write paths.

Both share the same **JSON API contract** under `/api/*`, the same **state model** (driven by the 5 SQLite DBs the supervisor owns), and the same **navigation taxonomy** (the `NAV` array in `home-shared.jsx`).

---

## Part 0 — Cross-cutting design language

### 0.1 Visual identity (webapp)

Locked in by the Claude Design handoff:

| Element | Value |
|---|---|
| Palette | "Sunny coastal" — paper `#eaf4fb`, ink `#0a2a44`, cerulean `#0288d1`, sunshine `#ffd54f`, success `#06d6a0` |
| Serif | Source Serif 4 (headlines, lead text, body) |
| Sans | Inter (UI chrome, labels, pills) |
| Mono | JetBrains Mono (numbers, IDs, log) |
| Surfaces | White cards with `--shadow-sm`; "glass" modules with `backdrop-filter: blur(14px)` |
| Radius | 10px primary, 6px tight, 14px lg (glass) |
| Confidence pills | WEP bands → Duolingo-style colored pills (`likely`, `high`, `even`, `unlikely`) |
| Status pills | white + dot (`running`, `queued`, `review`, `paused`) |
| Background | water-wave SVG pattern + compass rose lower-right (page-level) |

### 0.2 Visual identity (TUI)

| Element | Value |
|---|---|
| Framework | **Textual** (Textualize, MIT) — chosen for async, CSS-like styling, mouse + keyboard, screen stack |
| Theme | matches webapp palette: `paper` (light) and `inky` (dark) variants, autoswitch off `TERM_THEME` |
| Glyphs | unicode box-drawing, single-line by default, double-line for "modal" focus |
| Sparklines | unicode `▁▂▃▄▅▆▇█` over 24-cell width |
| Status line | bottom row, always visible: `tier | budget% | jobs running | uptime | NORMAL` |
| Modal indicator | top-right pill, vim-style: `NORMAL` / `COMMAND` / `INSERT` / `CONFIRM` |

### 0.3 Navigation taxonomy (shared)

**v1.0 ships seven top-level pages, not fourteen.** Earlier drafts of this
document followed the design handoff's 14-item sidebar; the handoff was a
designer's *aspiration* (every possible surface). For day-one user-friendliness
we collapse the rarely-visited instruments into tabs inside the page that
needs them most.

| # | Page | Replaces (from the original 14) | When you visit it |
|---|---|---|---|
| 1 | **Home** | Home | Every morning — the bulletin |
| 2 | **Jobs** | Jobs | When something feels stuck |
| 3 | **Drafts** | Drafts | When the bell rings — `a` to approve |
| 4 | **Topics** | Topics + Sources (sources are a tab inside the topic) | When you want a new standing watch |
| 5 | **Positions** | Positions + Hypotheses + Calibration (all three are tabs) | When a prediction resolves |
| 6 | **Health** | Doctor + Governor + Storage + Audit (tabs) | When `lighthouse doctor` flags something |
| 7 | **Settings** | Settings + Skills + Perspectives (tabs) | Rarely |

Counters in the sidebar pill (`<span class="count">N</span>` in the webapp,
`[N]` in the TUI) update via the same SSE event stream. Only counters that
**need user action** are shown — `Drafts [2]` (you have to approve them),
`Positions [4]` (overdue resolutions). We don't surface counts like
"312 positions tracked" — that's information density, not a call-to-action.

#### 0.3.1 User-friendliness principles

These constraints apply to every page in both surfaces.

1. **One-glance Home.** The Home page must answer "what changed since I last
   looked, and what needs me?" in under three seconds.
2. **No jargon labels.** "Confidence" not "WEP," "Calibration tab" not
   "Brier score," "Budget" not "token bucket." (We still record the
   technical name in tooltips and the audit log.)
3. **Defaults that work for everybody.** A fresh install runs without
   the user opening Settings. The five database files, the catalog tier,
   the budget caps, the sandbox scanners — all preset.
4. **Empty states teach the next step.** Every list, when empty, shows one
   sentence + one button. (Drafts: "No drafts staged. Run a Deep-Dive to
   produce one — [Start research].") No empty grid screens.
5. **Confirm only the destructive 5%.** Approval, rejection, navigation —
   one tap. Delete-a-topic, kill-switch, budget-reset, purge-quarantine,
   wipe-secrets — typed confirm.
6. **Errors come with the fix.** "Ollama not reachable" → "Open Ollama.app
   or run `ollama serve`" with a copy-button next to the command.
7. **Progressive disclosure.** Every page has a "Show details" toggle in
   the top-right that reveals the power-user fields. Default view is
   the minimum the user needs.

### 0.4 Three classes of surface

Every page in this design fits one of three patterns; the layout, the keyboard shortcuts, and the API shape derive from the class.

| Class | Examples | Pattern |
|---|---|---|
| **Stream** | Home (Lead/Alerts/Digest), Jobs, Audit | newest-first list, live append via SSE, infinite scroll, focus = open detail in a side pane |
| **Library** | Topics, Sources, Positions, Hypotheses, Skills, Perspectives | searchable + filterable table, optional grouping; row click → detail; click-create-edit |
| **Instrument** | Calibration, Governor, Storage, Doctor | dashboard of metrics + controls; sparse interactivity; refresh on a poll |

The Drafts surface is a hybrid (Stream → Detail with rich preview). Settings is its own thing.

### 0.5 The Approval Pattern

Per design §22.6, every result Lighthouse stages requires `#approve` before publish. Both surfaces share an **approval workflow**:

```
┌─ Staged draft #d-7f2a ──────────────────────┐
│  Topic: EU AI Act amendments                │
│  Confidence: very likely  (0.85–0.95)       │
│  23 sources · 14d 02h · Brier history -0.07 │
│                                              │
│  [ Read ]  [ Approve ]  [ Reject ]  [ Send back with note ]
└──────────────────────────────────────────────┘
```

Rejection asks for a one-line reason (becomes a Skill candidate per §23.2). Send-back-with-note re-queues with the note prepended to the planner's system prompt.

---

# PART I — WEBAPP

## 1. Architecture

```
Browser
   │
   │  fetch /api/dashboard         every 10 s (poll)
   │  EventSource /api/events      live deltas (SSE)
   ▼
FastAPI control plane :8765
   │
   ├─ /ui/             → StaticFiles (React + babel-standalone)
   ├─ /api/*           → JSON state endpoints
   └─ /api/events      → SSE multiplexer (supervisor writes)
   │
   ▼
SQLite spine (state, audit, intents, positions, hypotheses)
+ chosen_models.yaml, hardware.json, quarantine/
```

**State flow.** The supervisor owns mutation. The webapp reads + acts:
- Reads go through `GET /api/*` (idempotent, cacheable).
- Actions go through `POST /api/jobs/*`, `POST /api/drafts/<id>/approve`, etc. (each opens an intent via the outbox so the supervisor is the single writer).

**Why no client-side state library** (Redux/Zustand): the dashboard is read-mostly and the SSE channel pushes deltas straight into React component state. Premature for a single-user tool.

## 2. Page inventory

**Seven top-level pages, not fourteen.** The original 14-item taxonomy
(Sources / Hypotheses / Calibration / Governor / Storage / Audit / Skills /
Perspectives) are now **tabs inside the page that needs them most** —
fewer nav clicks, less decision fatigue. Each page below specifies:
**purpose**, **URL**, **layout**, **data source** (`GET /api/...`),
**actions** (`POST /api/...`), **live updates** (SSE event names),
**empty/loading/error states**, and the **tabs** it contains.

### 2.1 Home `/ui/`

Already designed (Variants A/B/C, the Captain's bridge / Atrium / Lab notebook). Status: **shipped Sprint 15-16 + 21.7**.

**Live wiring (Sprint 21):** `useDashboard()` hook in `home-shared.jsx` polls `/api/dashboard` every 10 s; deep-merges over the React MOCK so any field the server hasn't populated keeps a sane preview value.

### 2.2 Jobs `/ui/jobs`

**Purpose.** Operate the queue: see what's running, why, ETA; pause/resume/cancel; create a new job.

**Layout.**
```
┌──────────────────────────────────────────────────────────────────────┐
│  Jobs                                       [+ New job]   filter: …  │
├──────────────────────────────────────────────────────────────────────┤
│  ID    Mode      Topic                       Status  Progress  ETA  │
│  ────  ────────  ────────────────────────  ──────  ────────  ───── │
│  7f2a  Deep-Dive EU AI Act Article 6        ▶ run   ████░ 62%  2h14 │
│  3e8b  Monitor   Fed discount window        ▶ run   ██░░░ 34%  cont │
│  a91d  QUC       ARM Cortex-M errata        ✎ rev   █████ 100%  —   │
│  5c0f  Debate    Steelman RAG vs fine-tune  ⏸ que   ░░░░░  0%   …   │
└──────────────────────────────────────────────────────────────────────┘
```

Row-click opens a **side pane** (640px) with: framing pipeline trace, sub-questions, evidence ledger, last 50 model calls (model · tokens · ms · cost), pause/resume/cancel.

**Data.** `GET /api/jobs?status=*&mode=*&limit=N` → list of job records from `state.db`.
**Detail.** `GET /api/jobs/<id>` → joined with audit_events (model calls), intents (pending writes), positions (claims emitted).
**Actions.** `POST /api/jobs` (create), `POST /api/jobs/<id>/pause|resume|cancel`, `POST /api/jobs/<id>/escalate` (cloud).
**Live.** `event: job.progress` → `{id, progress, eta}`; `event: job.status` → `{id, status}`.
**Empty.** "No jobs yet — try `lighthouse monitor run --source-url ...` or click + New job."

### 2.3 Drafts `/ui/drafts`

**Purpose.** The single most important page. Every staged result waits here for `#approve`.

**Layout.** Three-column reading layout (Tufte sidenotes preserved):
```
┌──────────────┬──────────────────────────────────────┬───────────────┐
│  STAGED (3)  │  Two preprints overturn the          │  Sidenote      │
│  ▸ d-7f2a    │  Hawking-Page transition timing.     │  [1] Witten,   │
│    d-3e8b    │                                       │  arXiv:2503.…  │
│    d-a91d    │  A 14-day Bounded Deep-Dive          │                │
│  PUBLISHED   │  resolved with three independent     │  [2] Maldacena │
│    d-5c0f    │  replications. The earlier consensus │  2024 (Tier A) │
│              │  held since 2019.                    │                │
│              │  ───                                  │                │
│              │  Sources: 23 (5 Tier-A, 12 Tier-B…)  │                │
│              │  Brier history: -0.07 (improving)    │                │
│              │  ───                                  │                │
│              │  [ Approve ]  [ Reject ]  [ Note ]   │                │
└──────────────┴──────────────────────────────────────┴───────────────┘
```

The middle column is **rendered by the Tufte-CSS HTML output template** (already shipped — `output/html.py`). Right margin holds sidenote citations, WEP-colored bullets, expandable evidence chains.

**Approve flow.** Approve → `POST /api/drafts/<id>/approve` → intent fans out (Logseq write, Zotero add, audit append). The supervisor displays "publishing…" until intents resolve, then transitions to `PUBLISHED`.

**Reject flow.** Modal asks for a reason (one-line, required). The reason is appended to the Skill candidate stream (§23.2) and the draft is moved to a `rejected/` bucket.

**Data.** `GET /api/drafts?status=staged|published|rejected`; `GET /api/drafts/<id>` returns HTML body + metadata. **Actions.** `POST /api/drafts/<id>/approve|reject`. **Live.** `event: draft.staged` / `draft.approved` / `draft.rejected`.

### 2.4 Topics `/ui/topics`

**Purpose.** Add, edit, or remove the standing topics Lighthouse watches.
A topic is "what you care about" — a mode binding (Monitor / Deep-Dive /
QUC) + a source list + a refresh cadence.

**Tabs.** None at top level. Each topic *detail* has tabs:
`Overview · Sources · Recent items`.

**Layout (list view).**
```
┌─ Topics ─────────────────────────────────────  [+ New topic]  ─┐
│  NAME             MODE      LAST   #ITEMS  ✓/✗                │
│  EU AI Act        Monitor   3 min  142     ✓                  │
│  mRNA chain       Deep-Dive 2h     8       ✓                  │
│  Carbon credits   Monitor   12m    67      ✓                  │
│                                                                │
│  (No topics yet?  Click [+ New topic] to start watching one.) │
└────────────────────────────────────────────────────────────────┘
```

**Detail view (after clicking a row).** Side pane slides in from the right.
Tab 1 (Overview): mode, cadence, last refresh, error count. Tab 2 (Sources):
the per-source list — what used to be the separate Sources page. Inline
A/B/C/D grade override, pause toggle. Tab 3 (Recent items): last 50 items
the topic produced.

**Data.** `GET /api/topics`; `GET /api/topics/<id>` (includes sources).
**Actions.** `POST /api/topics` (create — wizard: pick mode, name, paste source URLs),
`PATCH /api/topics/<id>`, `DELETE /api/topics/<id>` (requires typed confirm).

### 2.5 Positions `/ui/positions`

**Purpose.** Where the user resolves predictions and watches their
own calibration improve. This is the *honesty surface* — what makes
Lighthouse different from Gemini DR.

**Tabs.** `Overdue · All positions · Calibration · Hypotheses`.

* **Overdue** (default tab) — only positions whose resolve-by date passed.
  This is the "do work" tab; everything else is reference.
* **All positions** — searchable, filterable by confidence band.
* **Calibration** — the visualization (Brier sparkline, reliability
  diagram, by-domain breakdown). What used to be its own page.
* **Hypotheses** — kanban of open / supported / refuted / retired.
  What used to be its own page. Drag-and-drop reassigns status.

**Overdue layout (default).**
```
┌─ 4 positions need a verdict ─────────────────────────────────┐
│                                                                │
│  ● Caesium-137 cleanup will finish by 2026-05-15              │
│    Confidence: likely (75%) · Created 2025-11-20              │
│    [ Confirmed ]  [ Refuted ]  [ Defer 30 days ]              │
│                                                                │
│  ● EU AI Act Article 6(2)(c) weakened by 2026-Q2              │
│    Confidence: even (50%) · Created 2026-01-15                │
│    [ Confirmed ]  [ Refuted ]  [ Defer 30 days ]              │
│                                                                │
│  …                                                             │
└────────────────────────────────────────────────────────────────┘
```

Three buttons per row, no modal — one click resolves. The notes field is
hidden under a "Add note" disclosure (most resolutions don't need one).

**Data.** `GET /api/positions?overdue=true` (default), `GET /api/positions`,
`GET /api/calibration`, `GET /api/hypotheses`.
**Actions.** `POST /api/positions/<id>/resolve {outcome, notes?}`;
`POST /api/hypotheses`; `PATCH /api/hypotheses/<id>`.

### 2.6 Health `/ui/health`

**Purpose.** One place to look when something feels wrong. Replaces
the four old "system" pages (Doctor + Governor + Storage + Audit).

**Tabs.** `Overview · Budget · Storage · Audit log`.

* **Overview** (default) — the `lighthouse doctor` output. Green ✓ / yellow
  hint / red ✗ checklist of subsystems. Failed rows have a `[Fix]` button
  with the copy-pasteable command.
* **Budget** — the Governor view: USD/tokens/tool-calls bars (per the
  earlier mock). One `[Reset]` button (typed confirm). One `[Kill all]`
  button (Telegram-confirm if Telegram enabled, typed confirm otherwise).
* **Storage** — disk usage, replica lag, quarantine counts. Quarantine
  rows expand to a restore/purge action.
* **Audit log** — scrollable event stream. `[Verify chain]` button at
  top-right.

**Overview layout (default).**
```
┌─ Health · all green ✓  ─────────────────  Last check 3 sec ago  ─┐
│                                                                    │
│  ✓ Hardware       macOS arm64 · 64 GB · tier T3                  │
│  ✓ Storage        4.2 GB used · 312 GB free                       │
│  ✓ Databases      5/5 integrity ok                                │
│  ✓ Audit chain    intact (4,127 events verified)                  │
│  - External       ollama ✓ · qdrant offline (optional)            │
│  ✓ Budget         $32 / $50 monthly (tier: green)                 │
│                                                                    │
│  No action needed.                                                │
└────────────────────────────────────────────────────────────────────┘
```

When everything is green, the page is *short and reassuring*. When something
breaks, the broken row expands inline with the fix.

**Data.** `GET /api/health` (combines doctor + governor + storage),
`GET /api/audit?limit=…`.
**Actions.** `POST /api/audit/verify`, `POST /api/governor/kill`,
`POST /api/governor/reset`, `POST /api/quarantine/<sha>/restore`,
`POST /api/quarantine/purge`.

### 2.7 Settings `/ui/settings`

**Purpose.** Edit anything Lighthouse stores about itself. Most users
will visit this twice ever: once to add their Logseq path, once to
enable cloud escalation.

**Tabs.** `General · Models · Secrets · Skills · Perspectives · Advanced`.

* **General** — Logseq path, Telegram on/off, output format default,
  notification channels.
* **Models** — the catalog table for the detected tier; one-click
  `[Pull]` for missing models; drift indicators.
* **Secrets** — masked entries for `audit.chain`, `langfuse.api_key`,
  `lighthouse.zotero.api_key`, etc. Reveal-and-copy buttons.
* **Skills** — searchable list of auto-curated skills (§23.2);
  inline editor (CodeMirror via CDN). What used to be its own page.
* **Perspectives** — debate perspectives (`steelman`, `devil's advocate`,
  etc.); card grid; click to edit. What used to be its own page.
* **Advanced** — the full `config.toml` editor, one form section per
  `[section]`. Most users never open this tab.

**Data.** `GET /api/settings` (with `secrets` masked as `***`),
`GET /api/skills`, `GET /api/perspectives`.
**Actions.** `POST /api/settings`, `POST /api/skills`,
`POST /api/perspectives`, `POST /api/secrets {key, value}`.

## 3. Shared components

These are React components the existing variants already use; new pages re-use the same primitives (registered on `window.*` from `home-shared.jsx`).

| Component | Purpose | New in Sprint 22 |
|---|---|---|
| `Sidebar` | nav | — |
| `LighthouseMark` | brand icon | — |
| `BackgroundPattern` | page bg | — |
| `WepBadge` | confidence pill | — |
| `Sparkline` | inline trend | — |
| `Pill` | status dot | — |
| `JobRow` | one job in a list | yes (extract from home-a.jsx) |
| `SidePane` | right-docked detail drawer | yes |
| `DraftReader` | Tufte HTML embed | yes |
| `KanbanColumn` | hypothesis status column | yes |
| `ReliabilityDiagram` | calibration scatter | yes |
| `BudgetBar` | governor budget | yes |
| `EvidenceLedger` | source list with grades | yes |

## 4. API contract

All endpoints serve JSON, default `Content-Type: application/json`. Listed below by page; each maps to existing modules.

| Endpoint | Method | Backed by | Drives |
|---|---|---|---|
| `/api/dashboard` | GET | `web/routes.py:_build_dashboard` (exists) | Home |
| `/api/jobs` | GET, POST | new — `state.db` jobs table | Jobs |
| `/api/jobs/<id>` | GET | joins audit + intents | Jobs detail |
| `/api/jobs/<id>/{pause,resume,cancel}` | POST | new | Jobs |
| `/api/drafts` | GET | new — `state.db` drafts table | Drafts |
| `/api/drafts/<id>` | GET | returns HTML body | Drafts |
| `/api/drafts/<id>/{approve,reject}` | POST | new — outbox fan-out | Drafts |
| `/api/topics` | GET, POST | new | Topics |
| `/api/topics/<id>` | GET, PATCH, DELETE | new — includes sources | Topics detail |
| `/api/positions` | GET | `verification/positions.py` | Positions/Overdue |
| `/api/positions/<id>/resolve` | POST | `verification/positions.py:resolve_position` | Positions |
| `/api/calibration` | GET | `score_all` + domain join | Positions/Calibration |
| `/api/hypotheses` | GET, POST | `verification/hypotheses.py` | Positions/Hypotheses |
| `/api/hypotheses/<id>` | PATCH | `verification/hypotheses.py` | Positions/Hypotheses |
| `/api/health` | GET | new — combines doctor + governor + storage | Health |
| `/api/governor/{kill,reset}` | POST | new | Health/Budget |
| `/api/quarantine/<sha>/restore` | POST | `sandbox/quarantine.py:restore` | Health/Storage |
| `/api/quarantine/purge` | POST | `sandbox/quarantine.py:purge` | Health/Storage |
| `/api/audit` | GET | paginated `audit_events` reader | Health/Audit |
| `/api/audit/verify` | POST | `audit_chain.py:verify_audit_chain` | Health/Audit |
| `/api/settings` | GET, POST | `config.toml` reader/writer | Settings |
| `/api/skills` | GET, PATCH, DELETE | `verification/skills.py` | Settings/Skills |
| `/api/perspectives` | GET, POST, PATCH | new — `state.db` perspectives table | Settings/Perspectives |
| `/api/secrets` | GET, POST, DELETE | `secrets.py` (values masked on GET) | Settings/Secrets |
| `/api/events` | GET (SSE) | new — `asyncio.Queue` multiplexer | all pages |

### 4.1 SSE event taxonomy

`/api/events` is one long-lived SSE stream. Event names:

```
job.progress     {id, progress, eta}
job.status       {id, status}
draft.staged     {id, topic, wep}
draft.approved   {id}
draft.rejected   {id, reason}
position.created {id, claim, wep}
position.resolved{id, outcome, brier}
audit.appended   {seq, actor, event_type}
governor.tier    {tier, remaining}
governor.tripped {dimension, period}
doctor.changed   {section, status}
intent.dead      {id, target, reason}
```

The webapp's `useDashboard` hook (Sprint 21.7) is the polling fallback; SSE is the primary push channel. When the SSE drops we fall back to the 10-s poll.

## 5. State & loading & error

Every page implements three states; the existing Home does this implicitly via the MOCK fallback:

| State | UX |
|---|---|
| Loading (first paint) | skeleton matching the eventual layout, MOCK data as placeholder so the page never flashes "empty" |
| Empty (no rows yet) | inline help: one sentence + one CLI command + one link |
| Error (fetch / SSE drop) | yellow toast top-right; page keeps last-known data; "Reconnecting…" indicator |

## 6. Keyboard shortcuts (webapp)

**Eight keys total to memorize.** We deliberately don't ship a vim-style
chord vocabulary — it scares non-power-users and most webapp use is mouse-led.
Power users get a command palette (`Cmd-K`) for everything else.

| Key | Action | Applies on |
|---|---|---|
| `Cmd-K` (or `Ctrl-K`) | Command palette | every page |
| `?` | Show this shortcut overlay | every page |
| `/` | Focus search | any page with a list |
| `Enter` | Open focused row's detail | any page with a list |
| `Esc` | Close side pane / modal | when open |
| `a` | Approve | Drafts (when one is focused) |
| `r` | Reject | Drafts (when one is focused) |
| `↑` `↓` | Move row focus | any page with a list |

Sidebar nav uses **mouse click only** by default. Power users open the
command palette (`Cmd-K`) and type the page name; tab completion narrows
to one result after 2-3 keystrokes.

We don't ship `g h` / `g j` / `g d` chords — they're invisible (no UI
hint), conflict with single-key shortcuts, and reward muscle memory the
average user never builds. The palette is the keyboard "fast path."

---

# PART II — TUI

## 7. Why a TUI

Use cases:
- Headless servers (a researcher running Lighthouse on a remote machine over SSH).
- Quick ops without leaving `$EDITOR`'s terminal.
- Power-user job queueing + approval (the user already lives in vim).
- Doctor + Audit are 80% of the troubleshooting surface and they're text-native.

Out of scope:
- Rich draft reading (lean on the webapp; TUI shows the markdown source + offers `o` to open in browser).
- Anything that benefits from real graphs (Calibration's reliability diagram degrades to ASCII; the diagram itself opens in browser via `o`).

## 8. Framework choice: Textual

Textual is the right choice for this app:
- Async-native (matches FastAPI/asyncio).
- CSS-like styling so we keep the webapp palette discipline.
- Built-in `DataTable`, `Tree`, `Markdown`, `Tabs`, `Header`, `Footer`.
- Excellent mouse + keyboard support.
- Snapshot testing (record terminal state, diff over time).
- Already MIT, pip-installable, no system deps.

```
$ uv add textual
$ uv run lighthouse tui
```

(The `lighthouse tui` entrypoint added in Sprint 22 is the only new console script; it imports `lighthouse_ai.tui` and runs the Textual `App`.)

## 9. Top-level layout

Same seven pages as the webapp. The sidebar is short on purpose — no
group headers, no chord shortcuts to memorize.

```
┌─ Lighthouse · 0.2.0 ───────────────────────────────────────── 14d 03h ─┐
│ ┌─ NAV ────────┐ ┌─ MAIN PANE ───────────────────────────────────────┐ │
│ │              │ │                                                    │ │
│ │  ▸ Home      │ │                                                    │ │
│ │    Jobs   2  │ │            (the active screen)                     │ │
│ │    Drafts 2  │ │                                                    │ │
│ │              │ │                                                    │ │
│ │    Topics    │ │                                                    │ │
│ │    Positions 4│ │                                                    │ │
│ │              │ │                                                    │ │
│ │    Health    │ │                                                    │ │
│ │    Settings  │ │                                                    │ │
│ │              │ │                                                    │ │
│ └──────────────┘ └────────────────────────────────────────────────────┘ │
│ tier T3 │ $32 of $50 │ 2 running, 1 needs review │ ? help              │
└────────────────────────────────────────────────────────────────────────┘
```

Counters appear only where the user must act: `Jobs 2` (running), `Drafts
2` (staged), `Positions 4` (overdue). No counter on `Topics`, `Health`,
or `Settings` — those are reference, not work.

Top bar: app name + version + uptime. Status bar: tier · monthly USD
(rounded) · the one or two job stats that matter · help hint.

## 10. Screen inventory

**Seven screens, matching the webapp.** Per-screen tabs replace what were
separate screens in earlier drafts. Below: layout + keybindings + data
per screen.

### 10.1 Home

Stream of the day. Three sections, vertically stacked:

```
┌─ Today ────────────────────────────────────────────────────────────────┐
│  Wednesday · 27 May 2026 · 09:47 local                                 │
│                                                                          │
│  ┌─ Lead ────────────────────────────────────────────────────────────┐ │
│  │ Two preprints overturn the Hawking-Page transition timing.        │ │
│  │ very likely  (0.85–0.95)  · 23 sources · 14d 02h                   │ │
│  │ [r] read draft   [a] approve   [x] reject                          │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  Alerts (3)                                                             │
│   • RETRACTION  2 sources retracted (mRNA cold-chain)                  │
│   • BUDGET      Monthly cloud at 71%                                   │
│   • RESOLUTION  4 positions overdue (fed-rate-cuts)                    │
│                                                                          │
│  Topic deltas — last 24h                                                │
│   EU AI ACT          New consolidated text published Tuesday. ▸ likely │
│   MRNA COLD-CHAIN    3 retractions propagated from PubMed.    ▸ certain│
│   LOGSEQ PLUGIN      v0.10.13 ships breaking change.          ▸ likely │
│                                                                          │
│  Calibration: 0.183 Brier ▼0.014 · ▁▂▂▃▂▂▂▂▁▂▁▁▂▁▂▂▂▁▂▁▂▁▂▁▁▂▁ (30d) │
└──────────────────────────────────────────────────────────────────────────┘
```

### 10.2 Jobs

Sortable `DataTable`. Press `Enter` on a row → push the Job Detail screen.

```
ID    MODE        TOPIC                                  STATUS  PROGRESS  ETA
7f2a  Deep-Dive   EU AI Act — Article 6 amendments       ▶run   ████░62%  2h14m
3e8b  Monitor     Federal Reserve discount-window data   ▶run   ██░░░34%  cont
a91d  QUC         ARM Cortex-M errata half-life          ✎rev   █████100% —
5c0f  Debate      Steelman RAG vs fine-tune              ⏸que    ░░░░░ 0%  after 7f2a

  [n] new   [p] pause   [r] resume   [c] cancel   [Enter] detail   [/] filter
```

Job detail screen has tabs: `[1] Trace` (framing → planner → researchers → denoiser), `[2] Evidence` (chunks retrieved per sub-question), `[3] Model calls` (table), `[4] Intents` (per-target outbox status).

### 10.3 Drafts

Two-pane (Textual `Horizontal`): list on left, rendered markdown body on right (`Markdown` widget). `Tab` swaps focus.

```
STAGED  d-7f2a  Two preprints overturn ▸▸
        d-3e8b  Fed discount window      
        d-a91d  ARM Cortex-M errata      

  [a] approve   [x] reject   [n] add note   [o] open in browser   [/] search
```

Approval triggers an inline confirm: `Approve d-7f2a? (y/n)`. Reject opens a `TextArea` for the one-line reason.

### 10.4 Topics

Library template — list + detail; detail has three tabs
(`Overview / Sources / Recent items`).

```
┌─ Topics ──────────────────────────────────────────┬─ Detail ────────────┐
│ NAME            MODE      LAST   #ITEMS  ✓        │ EU AI Act           │
│ ▸ EU AI Act     Monitor   3 min  142     ✓        │ Overview │ Sources │ Items │
│   mRNA chain    Deep-Dive 2h     8       ✓        │                     │
│   Carbon credits Monitor   12m    67      ✓        │ Mode: Monitor       │
│                                                     │ Sources: 4          │
│                                                     │ Last fetch: 3 min   │
│ [n] new   [d] delete   [/] search                  │ Errors: 0           │
└────────────────────────────────────────────────────┴─────────────────────┘
```

### 10.5 Positions

Four tabs: `Overdue · All · Calibration · Hypotheses`. The default tab is
Overdue (where the work is).

**Overdue tab (default).** One position per row; three buttons per row.
```
┌─ 4 positions need a verdict ─────────────────────────────────────────┐
│                                                                         │
│  Caesium-137 cleanup will finish by 2026-05-15                          │
│  Confidence: likely (75%) · Created 2025-11-20                           │
│  [ y ] confirmed    [ n ] refuted    [ d ] defer 30d                     │
│                                                                         │
│  EU AI Act Article 6(2)(c) weakened by 2026-Q2                          │
│  Confidence: even (50%) · Created 2026-01-15                             │
│  [ y ] confirmed    [ n ] refuted    [ d ] defer 30d                     │
│                                                                         │
│  …                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

**Calibration tab.** ASCII reliability diagram + Brier sparkline + domains:
```
Brier 30d                                            0.183 ▼0.014
  ▁▂▂▃▂▂▂▂▁▂▁▁▂▁▂▂▂▁▂▁▂▁▂▁▁▂▁

Reliability (resolved n=312)
  1.0│                              ●
     │                          ●
     │                      ●                   (closer to diagonal =
  0.5│              ●●                            better calibrated)
     │       ●
     │   ●
  0.0│●
     └───────────────────────────────
      0.0    0.3    0.5    0.7   1.0

By domain
  DOMAIN       N    BRIER    Δ7d
  AI policy    38   0.14    -0.02
  Markets      64   0.27    +0.04   ⚠
  …

  [o] open in browser for the proper diagram
```

**Hypotheses tab.** Four columns (kanban):
```
OPEN (3)            SUPPORTED (5)        REFUTED (2)         RETIRED (1)
─────────────────  ─────────────────   ─────────────────   ─────────────
H-039 Carbon …    H-038 mRNA cold…    H-031 LLM scaling…   H-002 …
H-040 EU AI …     H-035 Logseq API…   H-029 Federal …
H-041 Quantum …   …
                  …

  [j/k] move  [h/l] reassign column  [n] new  [Enter] detail
```

### 10.6 Health

Four tabs: `Overview · Budget · Storage · Audit`.

**Overview tab (default) — the friendly summary.**
```
┌─ Health · all green ✓ ──────────────────────  Last check 3 sec ago ─┐
│                                                                       │
│  ✓ Hardware      macOS arm64 · 64 GB · tier T3                       │
│  ✓ Storage       4.2 GB used · 312 GB free                            │
│  ✓ Databases     5 of 5 healthy                                       │
│  ✓ Audit chain   intact (4,127 events)                                │
│  - External      ollama ✓ · qdrant offline (optional)                 │
│  ✓ Budget        $32 of $50 monthly  (tier: green)                    │
│                                                                       │
│  No action needed.                                                   │
│                                                                       │
│  Press [r] re-check · [Enter] expand a row                            │
└───────────────────────────────────────────────────────────────────────┘
```

**Budget tab.**
```
USD       monthly  █████████░░░  $32.58 of $50
          weekly   ███████░░░░░  $10.20 of $15
          daily    ████░░░░░░░░   $1.21 of $3
Tokens    daily    █░░░░░░░░░░░   0.8M of 8M
Tool calls daily   ███░░░░░░░░░   1.5k of 5k

Tier: green

  [b] reset budget (typed confirm)
  [K] kill all jobs (typed confirm; Telegram if enabled)
```

**Storage tab.** Disk bar + replicas + quarantine summary; press `Enter`
on the quarantine row to drill in.

**Audit tab.** Scrollable event stream; rows tween in from the bottom on
the SSE `audit.appended` event. `[v]` verifies the HMAC chain.

### 10.7 Settings

Six tabs: `General · Models · Secrets · Skills · Perspectives · Advanced`.
Each tab is a Vertical of Input widgets. `s` saves; saving goes through
the outbox so a bad save can be rolled back.

Most users only ever open the General tab. The Advanced tab opens the
full `config.toml` editor and is hidden behind a "Show advanced" toggle
on first open.

## 11. TUI keybinding system

**No vim modes; no chord shortcuts.** The TUI is keyboard-first but uses a
flat, discoverable keymap. Every screen shows its keybindings in a footer
line, always visible. Power users get a command palette (`:`) for everything
else.

**Always available (any screen):**

| Key | Action |
|---|---|
| `?` | Help overlay (lists every binding for the current screen) |
| `:` | Command palette (typeahead) |
| `q` | Quit (asks confirm if intents pending) |
| `Esc` | Back / close pane |
| `Ctrl-r` | Reconnect SSE |

**Navigation:** click sidebar with mouse, or press `1`-`7` for the seven
top-level pages (number prefixes match the sidebar order). The footer
shows the digits on hover. No `g h` chords — they're invisible and the
user can't see what `g` did.

**In a list (Jobs, Topics, Positions, etc.):**

| Key | Action |
|---|---|
| `↑` `↓` | Move row focus |
| `Enter` | Open detail |
| `/` | Search |
| `n` | New item |

**On Drafts:** `a` approves the focused draft; `r` rejects (prompts for
reason). On Positions/Overdue: `y` / `n` / `d` resolve.

That's the entire keymap. Memorability beats efficiency at scale 1.

## 12. Command palette

`:` opens a small input at the bottom; supports tab completion. Examples:

```
:job pause 7f2a              → POST /api/jobs/7f2a/pause
:draft approve d-7f2a        → POST /api/drafts/d-7f2a/approve
:hypothesis new "…"          → POST /api/hypotheses
:monitor run hnrss.org HN    → spawns the same command as the CLI
:budget reset --confirm      → POST /api/budget/reset
:open jobs                   → push Jobs screen
:open https://…              → open URL in browser
```

The palette runs the same code path as the CLI subcommands; both call into `lighthouse_ai.cli`'s typer functions where possible.

## 13. Status bar

Bottom row, single line, always visible. **Plain-English only** — no
acronyms, no per-second throughput counters that nobody reads.

```
tier T3 │ $32 of $50 │ 2 running, 1 needs review │ ? help
```

The right edge always shows `? help` so the user knows where the help is.
Updates every second from `/api/health`.

## 14. Real-time updates

The TUI uses the **same SSE channel** as the webapp:
- `App.on_mount` opens an `httpx.AsyncClient` SSE connection to `/api/events`.
- Incoming events are pushed onto an asyncio `Queue`; the app's main loop drains and routes to the active screen (`screen.on_event(name, data)`).
- If the SSE drops, the app falls back to a 5-s poll on the active screen's primary endpoint.

## 15. Offline / disconnected mode

If the supervisor isn't running, the TUI shows:

```
┌─ Lighthouse — supervisor offline ──────────────────────────────────┐
│  Could not reach 127.0.0.1:8765/api/health.                         │
│                                                                       │
│  • Start the supervisor:  lighthouse start                           │
│  • Or run foreground:     lighthouse-supervisor                      │
│                                                                       │
│  [r] retry   [d] open doctor offline   [q] quit                      │
└───────────────────────────────────────────────────────────────────────┘
```

The doctor screen is the only one that runs without the supervisor (it reads `~/.lighthouse/` directly through the existing CLI code path).

---

# PART III — Implementation roadmap

## 16. Webapp build-out (Sprint 22 candidate)

**Phase A — schema & API (3 days):**
1. Extend `state.db`: tables `jobs`, `drafts`, `topics`, `sources`, `perspectives` per design above.
2. Implement read endpoints first: `/api/jobs`, `/api/drafts`, `/api/topics`, `/api/sources`, `/api/positions`, `/api/hypotheses`, `/api/calibration`, `/api/storage`, `/api/skills`, `/api/perspectives`, `/api/doctor`, `/api/audit`, `/api/settings`. Each is a thin shim over an existing module.
3. SSE multiplexer at `/api/events` backed by an `asyncio.Queue` in the supervisor; first publishers are the Effector (intent.dead, intent.applied) and the Governor (governor.tier, governor.tripped).

**Phase B — write endpoints + outbox adapters (2 days):**
4. Job lifecycle adapters (`targets/jobs.py`): create, pause, resume, cancel.
5. Draft approval adapter (fans out Logseq + Zotero + audit).
6. Settings save through outbox with rollback.

**Phase C — React pages (5 days):**
7. Extract shared components from `home-a.jsx` (`SidePane`, `JobRow`, `WepBadge`, etc.) into `components.jsx`.
8. Wire each page (`pages/jobs.jsx`, `pages/drafts.jsx`, etc.), each subscribing via `useDashboard()` + `useEvents()` hooks.
9. Client-side router (`pages.jsx`) — tiny, no Next.js: `window.location.hash` based.
10. Keyboard shortcut layer (`shortcuts.jsx`).

**Phase D — tests + screenshots (1 day):**
11. Smoke test per page (fetch /ui/<page>, assert 200 + key text).
12. API contract tests per endpoint.
13. Screenshot stash for visual regression (playwright via Docker — optional).

## 17. TUI build-out (Sprint 23 candidate)

**Phase A — scaffold (1 day):**
1. Add `textual` to `pyproject.toml`.
2. New module `src/lighthouse_ai/tui/`: `app.py` (root `App` class), `screens/` (one per nav item), `widgets/` (status bar, sparkline, wep badge).
3. Console script `lighthouse tui = "lighthouse_ai.tui.app:main"`.

**Phase B — screens (4 days):**
4. Implement Home, Jobs, Drafts, Doctor, Audit first (the 80%).
5. Then Library screens (Topics, Sources, Positions, Hypotheses, Skills, Perspectives) sharing the Library template.
6. Then Instrument screens (Calibration, Governor, Storage).
7. Settings last.

**Phase C — interactivity (2 days):**
8. SSE client + event router (`events.py`).
9. Command palette + tab completion.
10. Modal `y/n` confirm component.

**Phase D — tests (1 day):**
11. Textual snapshot tests per screen (record + diff terminal state).
12. Keybinding tests (programmatic key presses).
13. Offline-mode test (no supervisor running).

## 18. Open questions

`[OPEN]` markers — decisions deferred to implementation:

- **Settings TOML round-trip preserves comments?** Currently `tomli_w` doesn't. Workaround: keep a side-by-side template + only write changed keys. **[OPEN]**
- **Telegram kill confirmation requires a Telegram bot already configured.** If `[telegram] enabled = false`, the kill button asks for typed confirmation in-app instead. **[OPEN]**
- **Audit pagination cursor strategy.** Time-based vs seq-based. Lean seq-based (monotonic, no clock skew). **[OPEN]**
- **Webapp dark mode.** Design doc didn't specify; the React palette is light-only. Add `--theme` toggle in v0.3. **[OPEN]**
- **TUI mouse support.** Textual supports it but the design above is keyboard-first. Default mouse-on, document keyboard as the canonical interaction. **[OPEN]**

## 19. Closing notes

The webapp is the **single user-facing dashboard**; the TUI is the **same product, headless**. Both speak the same JSON, share the same nav, surface the same state. The only legitimate divergence is rendering — the webapp gets graphs and Tufte HTML, the TUI gets sparklines and markdown.

Every Sprint 22+ feature should ship in **both surfaces simultaneously** (after the initial scaffold catch-up). Add a `[Sprint XX]` marker when a new surface is mocked in either side without backing data.

Total surface count when complete:
- **Webapp:** 14 pages × 3 states (loading/empty/error) × responsive = ~50 distinct screens.
- **TUI:** 14 screens + 5 modals (confirm, palette, fix-it, kill, reject-reason) + 1 offline = 20 screens.

Estimated implementation: **Sprint 22 (webapp build-out)** = 11 days, **Sprint 23 (TUI build-out)** = 8 days. Run them in parallel since they share the API but not the rendering layer.
