# Internet Archive Wayback Machine — Planner Guide

## When to use this skill

Wayback is the primary tool for **historical web retrieval**: what did a page
say on a specific date, is a cited URL still live, and what does the edit
history of a site reveal about an organisation's changing positions.

**Use Wayback for:**
- **Dead-link recovery**: a cited URL returns 404 — look it up in Wayback and
  fetch the preserved content.
- **Reconstruct mode**: building a timeline of how a page (regulatory notice,
  corporate statement, government policy, news article) changed over time.
- **Legal / policy research**: "what did the FDA's website say before the 2018
  rule change?" needs a dated snapshot, not current content.
- **OSINT / journalism**: confirm a statement was made (e.g. a company's 'About'
  page before a scandal) or identify when a page was deleted.
- **Submitting for archiving**: ensure a live page is preserved before citing it
  in research that will be published.

**Do NOT use Wayback for:**
- Current content — use `general_web` or a specialist skill.
- Pages that were never crawled — Wayback crawls selectively; small or
  private sites may have no snapshots.  `list_snapshots` returns an empty
  list in that case; report this to the user.
- JavaScript-heavy pages that require rendering — Wayback stores the raw HTML
  as captured.  Post-2018 captures may be better; pre-2010 captures of
  heavily dynamic pages are often incomplete.
- Watch mode — Wayback is a lookup tool, not a live feed.

---

## CDX API overview

The Wayback CDX HTTP API is the backbone of this skill:

```
https://web.archive.org/cdx/search/cdx
  ?url=<target_url>
  &output=json
  &fl=timestamp,original,statuscode,mimetype
  &limit=50
  &filter=statuscode:200
  &collapse=timestamp:8   # one per day
  &from=20200101000000
  &to=20231231235959
```

Response: JSON array where the first element is the field-name header row and
subsequent elements are records.

Snapshot retrieval:
- Raw content (no Wayback banner): `https://web.archive.org/web/{timestamp}id_/{url}`
- Rendered with Wayback toolbar: `https://web.archive.org/web/{timestamp}/{url}`

Use the `id_/` (raw) form for content extraction — it avoids Wayback's link
rewriting and banner injection.

---

## Tool playbook

| Task | Tool | Notes |
|---|---|---|
| Find closest snapshot to a date | `lookup_url_at_date(ctx, url, date)` | ``date`` as ``YYYYMMDD`` or ``YYYY-MM-DD`` |
| List all snapshots | `list_snapshots(ctx, url)` | Returns CDX record dicts |
| Fetch a specific snapshot | `fetch_snapshot(ctx, timestamp, url)` | 14-digit CDX timestamp |
| Archive a live URL | `submit_for_archiving(ctx, url)` | SPN2 endpoint; returns job/snapshot URL |
| run() convenience | `run(ctx, question_with_url)` | Extracts URLs + date hints from question |

### Typical sequence for Reconstruct

```
1. list_snapshots(ctx, url, from_date="20150101", to_date="20231231", limit=50)
   → get chronology of snapshots
2. For each key date: fetch_snapshot(ctx, timestamp, url)
   → get the archived content
3. Compare Documents across timestamps to identify changes
```

### Typical sequence for dead-link recovery

```
1. lookup_url_at_date(ctx, dead_url, "20231231")
   → get most recent snapshot
2. Return the snapshot Document as the replacement citation
3. Include snapshot_timestamp in the citation metadata
```

---

## Known biases and limitations

1. **Coverage gaps.** Not all URLs have been crawled.  Government sites,
   major news outlets, and large commercial sites have good coverage (esp.
   post-2000); small blogs, intranets, and JavaScript-only SPAs may have poor
   or zero coverage.

2. **Robots.txt exclusions.** Sites that excluded the Wayback crawler via
   `robots.txt` have no or limited snapshots.  Some sites later removed their
   exclusion but the gap remains.  `list_snapshots` returning empty is
   informative — report it.

3. **Incomplete captures.** A snapshot captures the HTML but may miss
   embedded resources (images, CSS, JS).  For text-extraction purposes this is
   usually fine; for visual fidelity it is not.

4. **Timestamp precision.** The CDX timestamp is when the Wayback crawler
   fetched the page, not when the content was authored.  A policy change on
   Jan 1 may first appear in a snapshot dated Jan 3 if the crawler ran then.

5. **Grade A provenance.** Documents from Wayback are graded `A` by default
   because the content is a verbatim preserved copy of what a server returned
   at crawl time — the archive does not editorially alter pages.  However, the
   *original source* may have had lower reliability; note both in citations.

6. **Submit-for-archiving latency.** SPN2 may take seconds to minutes per page.
   `submit_for_archiving` fires the request but does not wait for completion.

---

## Watch mode notes

Wayback is NOT watchable.  It is a historical lookup tool.  The Watch engine
should not schedule ticks for this skill.  For monitoring live changes to a
site over time, use `general_web` or a specialist skill; then use Wayback to
retrieve historical context.

## Domains best served

journalism · legal · policy · IC/OSINT · history

## Modes best served

reconstruct · investigate
