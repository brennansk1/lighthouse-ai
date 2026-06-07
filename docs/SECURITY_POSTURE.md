# Security Posture

A one-page, honest description of what Lighthouse does with your data and the
controls that enforce it. This describes **controls, not certifications** — there
are no compliance claims here, only mechanisms you can inspect in the source and
in your own logs.

---

## Data flow — what stays local, what egresses, and when

Lighthouse is local-first. By default the things you care about most never leave
your machine:

| Data | Where it lives | Egresses? |
| --- | --- | --- |
| Your documents / corpus | `~/.lighthouse/corpus/` (SQLite + files on your disk) | **No.** Never uploaded. |
| Your raw, user-typed query (pre-disambiguation) | In-process / local DBs | **No.** Classified `PRIVATE` — denied egress even to allowlisted hosts. |
| LLM inference | Your local Ollama instance | **No.** Lighthouse does not call a cloud LLM. |
| Embeddings, drafts, citations, positions | `~/.lighthouse/*.db` | **No.** |

Egress happens **only** when you explicitly pull from an external source — an
`--arxiv` / `--openalex` / `--pubmed` / `--crossref` query, a `--url` fetch, or a
research skill that reaches a known API. Even then, every such request is supposed
to pass through one chokepoint (see below), and a *search-class* query that goes
out is classified `PUBLIC-OK` / `PUBLIC-WIDE` — never `PRIVATE`.

---

## The egress chokepoint: allowlist + audit log

All policy lives in one place: `lighthouse_ai/governor/egress_proxy.py`
(`EgressProxy`). For each outbound request it decides, in this order:

1. **Air-gap kill switch** (see below) — if set, deny everything.
2. **Privacy tier** — a `PRIVATE` request (your raw query) is denied *before* the
   allowlist is even consulted. Privacy tier is the binding constraint, not the host.
3. **Allowlist** — the destination host must match `[egress] allowed_domains`
   (defaults in `DEFAULT_ALLOWED_DOMAINS`: arXiv, OpenAlex, PubMed, Crossref,
   SEC, CourtListener, FRED, World Bank, Wikipedia, official skill sources, etc.).
   Anything not on the list is **denied with an audit entry**. Subdomain matches
   are on label boundaries, so `evilarxiv.org` never matches `arxiv.org`.

Every connection is appended as one JSON line to **`~/.lighthouse/logs/egress.jsonl`**
(host, port, bytes sent/received, duration, privacy tier, allowed/denied, reason).
This is your "what left my machine?" record — newline-delimited, greppable, append-only.

### Reading the audit log

```sh
uv run lighthouse audit-egress --since 7d
```

This produces a report of external network calls recorded in the audit trail. If
nothing went out, it tells you so explicitly — i.e. it confirms Lighthouse operated
in airplane mode for the window. You can also just read the raw log directly:

```sh
grep '"allowed": false' ~/.lighthouse/logs/egress.jsonl   # everything that was denied
```

---

## The hard kill switch: `LIGHTHOUSE_AIRGAP=1`

Set this environment variable to a truthy value (`1`, `true`, `yes`) and **all
egress is denied before any socket opens**:

```sh
export LIGHTHOUSE_AIRGAP=1
```

It is checked first, at decision time (not import time), so you can toggle it within
a running process and it overrides tier and allowlist alike. This is the control to
use when you want a guarantee — not a policy, a guarantee — that nothing leaves the
machine.

**Coverage of the kill switch.** `LIGHTHOUSE_AIRGAP=1` is honored by every outbound
path, including the ones that do not flow through the httpx fetch guard:

- the 25 source adapters and the standard `ctx.fetch` path (via `EgressProxy.check`);
- the Telegram and Discord notification channels (via the guarded HTTP helper);
- the **SMTP / email** channel (checked in `EmailChannel.send` before any socket);
- the **Playwright / `js_render` (Tier-B)** browser path, which refuses to launch
  Chromium when air-gap is set and degrades to static fetch.

---

## ⚠️ Honest known limitation: Tier-B browser fetches are not host-allowlisted

`LIGHTHOUSE_AIRGAP=1` *does* stop the Playwright / `js_render` path (it refuses to
render at all when set — see above). The remaining honest gap is **finer-grained
allowlisting when air-gap is OFF**: `lighthouse_ai/sources/js_render.py` launches a
headless Chromium and calls `page.goto(url)` directly, so with air-gap disabled it
does **not** consult the per-host egress allowlist, and Chromium additionally fetches
page sub-resources (scripts, images, beacons) that the `EgressProxy` never sees.

Practical implications until this is fixed:

- With air-gap **off**, a Tier-B render can reach a host that is *not* on the egress
  allowlist, and those fetches may not appear in `egress.jsonl`.
- For a hard guarantee, set `LIGHTHOUSE_AIRGAP=1` (which blocks Tier-B entirely), or
  do not install the Playwright Tier-B path; verify either way with `audit-egress`.

Routing `js_render` through the `EgressProxy` per host (and auditing its sub-resource
fetches) when air-gap is off is tracked as outstanding work.
