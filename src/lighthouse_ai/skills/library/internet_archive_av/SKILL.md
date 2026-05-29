# Internet Archive — Audio/Video Collections — Planner Guide

## When to use this skill

The Internet Archive AV skill is the primary tool for **media archive research**:
public-domain films, Creative Commons audio recordings, archived radio and
television, the Television News Archive (captioned and searchable), oral
histories, and government footage.

**This skill is DISTINCT from the Wayback skill.** Wayback retrieves historical
*web page* snapshots. This skill retrieves *media files* (movies, audio,
broadcast recordings) catalogued in the IA collections system.

**Use this skill for:**
- **Television archive research**: "What did evening news report on 9/11?" — query
  the Television News Archive (`tvarchive` collection).
- **Historical radio**: archived NPR, BBC, old-time radio recordings
  (`oldtimeradio` collection).
- **Public-domain film**: Prelinger Archives, silent films, educational films
  (`prelinger` collection).
- **Oral histories and lectures**: recorded interviews, academic talks, government
  hearings.
- **Pop-culture research**: music recordings, vintage commercials, television
  shows in the public domain.
- **Journalism media corroboration**: verify broadcast claims with archived
  footage or audio.

**Do NOT use this skill for:**
- Historical *web page* snapshots — use `wayback`.
- Current/live video — use `youtube` or `general_web`.
- Modern paywalled television — those are not in the IA catalogue.
- Music streaming from commercial platforms.

---

## API overview

### advancedsearch.php

The full-text search endpoint:

```
https://archive.org/advancedsearch.php
  ?q=<query> AND mediatype:(movies OR audio)
  &fl[]=identifier&fl[]=title&fl[]=description&fl[]=date&fl[]=creator
  &sort[]=downloads desc
  &rows=10&page=1&output=json
```

Returns a `response.docs` array of item metadata dicts.

### Metadata API

```
https://archive.org/metadata/<identifier>
```

Returns full item metadata including the `files` list.  Use this to find
caption/subtitle files (`.srt`, `.vtt`, closed-caption text files).

### Download (direct file access)

```
https://archive.org/download/<identifier>/<filename>
```

Used by `fetch_transcript` to retrieve caption files.

---

## Tool playbook

| Task | Tool | Notes |
|---|---|---|
| Search the AV catalogue | `search_av(ctx, query)` | Adds `mediatype:(movies OR audio)` automatically |
| Get full item metadata + files list | `fetch_metadata(ctx, identifier)` | Returns dict with `metadata` and `files` keys |
| Retrieve transcript / captions | `fetch_transcript(ctx, identifier)` | Returns `None` gracefully when no captions present |
| List a named collection | `get_collection_listing(ctx, collection)` | Convenience wrapper around `search_av` |
| Full run (search + metadata + transcripts) | `run(ctx, question)` | Standard entrypoint |

### Typical sequence for Television News Archive research

```
1. search_av(ctx, "September 11 2001 NBC evening news", collection="tvarchive")
   → list of matching broadcast items
2. fetch_metadata(ctx, identifier)
   → full metadata + files list (find caption .srt files)
3. fetch_transcript(ctx, identifier, metadata=meta)
   → transcript text from the caption file
4. Build Documents from transcript text + broadcast metadata
```

### Typical sequence for oral history / lecture research

```
1. search_av(ctx, "oral history civil rights movement")
   → list of items
2. fetch_metadata(ctx, identifier) for the top hit
3. fetch_transcript(ctx, identifier) → likely None (no captions) → fall back to description
4. Return metadata-only Document with archive URL for the user to review
```

---

## Transcript retrieval

`fetch_transcript` uses `lighthouse_ai.sources.transcript` (shared with the
CourtListener and YouTube skills).  Priority order:

1. **In-process cache** — if a transcript was already retrieved this session.
2. **Caption/subtitle file** — looks for `.vtt`, `.srt`, or text files in the
   item's `files` list and fetches via `ctx.fetch`.
3. **Registered ASR providers** — `transcribe_or_fetch_captions(identifier)`
   tries any registered backends.
4. **`None`** — documented v1 stub; returns gracefully.

**The Television News Archive** has closed-caption text for most items (look
for `format = "Closed Caption Text"` in the files list).  These are the richest
source for broadcast media research.

---

## Known biases and limitations

1. **Coverage is not exhaustive.** IA catalogues selectively; recent commercial
   broadcasts, most foreign-language television, and paywall-protected content
   are absent.

2. **Grade B default.** Items are user-uploaded or partner-donated.  Most are
   authentic (especially Television News Archive items) but the grade reflects
   the heterogeneous provenance of the collection.  Adjust downstream for
   known-authoritative items (e.g. U.S. government footage in `USGovernment`).

3. **Transcript quality varies.** Closed captions from broadcast television can
   have OCR/transcription errors.  Audio-only items often lack captions entirely.

4. **No ASR in v1.** `fetch_transcript` returns `None` for items without
   pre-existing caption files.  An ASR backend can be wired in via
   `transcript.register_provider` without modifying this skill.

5. **Search relevance.** `advancedsearch.php` full-text search quality is
   variable; for Television News Archive queries use specific dates and outlet
   names for best results.

6. **Temporal tools available.** Sort by `date asc` / `date desc` in
   `search_av` for chronological ordering. Use `fetch_metadata` to get precise
   broadcast dates.

---

## Domains best served

media · journalism · pop_culture · history

## Modes best served

investigate · reconstruct
