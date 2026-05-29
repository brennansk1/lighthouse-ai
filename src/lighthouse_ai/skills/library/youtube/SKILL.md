# YouTube — Planner Guide

## When to use this skill

YouTube is the right source when the research question has a **video-native
answer**: a recorded talk, a tutorial demonstration, a primary-source statement
(speech, interview, press conference), or a pulse-check on popular reception of
a topic.

**Use YouTube for:**
- Academic or conference talks not published as papers (NeurIPS/ICLR talk
  recordings, TED talks, keynotes).
- Step-by-step tutorials where the visual/procedural component matters.
- Primary-source video: an official statement, a product demo, a legislative
  hearing.
- Popular reception and discourse: how many people are discussing a topic, what
  the mainstream narrative is, which creators are producing authoritative content.
- Breaking-news video evidence (news channel uploads, eyewitness recordings).
- Watch mode: monitoring a topic for new uploads (news, product launches, ongoing
  events).

**Do NOT rely on YouTube as the sole citation for:**
- Any load-bearing academic or medical claim — transcripts are user-generated
  and may contain errors, especially auto-generated captions.
- Quantitative or statistical claims (quotes may be taken out of context).
- Legal or financial advice.
- Topics where authoritativeness requires peer review or regulatory authority.

---

## Legitimate-only constraint

This skill uses **only official YouTube endpoints**:

1. `yt-dlp`'s ytsearch extractor (calls YouTube's public search endpoint — the
   same as browsing youtube.com in a browser).
2. `youtube-transcript-api`'s call to the public timedtext API that YouTube's
   own web player uses for captions.

There is **no** API-key evasion, **no** residential proxy routing, **no**
Tier-C fingerprint escalation.  If YouTube blocks the request (cloud IP,
rate-limit), the skill returns an empty/degraded result — it never attempts
to bypass the block.

---

## Transcript caveats

- **Auto-generated captions** are used when manual captions are unavailable.
  They contain recognition errors, especially for domain-specific terminology,
  proper nouns, and non-native English accents.
- **Missing transcripts**: not all videos have captions enabled.  When no
  transcript is available the document text falls back to the video description,
  which is a creator summary (potentially promotional).
- **Timestamps** are stripped; the transcript is returned as a single prose
  block.  For a time-indexed claim, the planner should note the approximate
  timestamp if known.
- **Language**: this skill requests English transcripts by default.  Videos in
  other languages return an empty transcript unless the creator has provided
  English captions.

---

## Grade = user-generated (C)

`default_grade = "C"` because YouTube hosts **user-generated content** with no
editorial review.  The discipline gate will apply a WEP band reduction on claims
for which YouTube is the sole source.

Exceptions to note in Investigate/Adjudicate:

- Official publisher channels (BBC News, CSPAN, official government channels,
  major academic institutions) may warrant treating a specific document at
  grade B.  This is a planner judgment call, not automatic.
- Peer-reviewed researchers presenting their own published work (citing the
  corresponding paper) can corroborate a grade-A claim; the paper itself is the
  load-bearing citation, the video is supporting context.

---

## Tool playbook

| Task | Call | Notes |
|---|---|---|
| Find relevant videos | `run(ctx, question, max_results=5)` | search + transcript per hit |
| Watch for new uploads | `run_watchable(ctx, query, since=datetime)` | recent upload filter |
| Metadata only (no transcript) | `sources.youtube.fetch_metadata(url)` | fast, no transcript call |
| Transcript only | `sources.youtube.fetch_transcript(video_id)` | empty if not available |

### Typical sequence for Ask / Investigate

```
1. run(ctx, question, max_results=5)   # search + transcripts
2. check doc.metadata["text_type"]     # "transcript" vs "description"
3. if transcript: cite with [video_id, timestamp if known]
4. cross-check load-bearing claims against primary sources
```

---

## Known biases and limitations

1. **Search ranking reflects YouTube's algorithm**, which favours watch-time,
   engagement, and channel authority.  High-view-count popular content surfaces
   above niche but accurate material.
2. **Cloud IP blocking**: YouTube rate-limits cloud addresses.  This skill is
   designed for local-first use; persistent 429/403 in a cloud deployment is
   expected — reduce cadence or skip.
3. **Recency bias in watch mode**: the `since=` filter is applied post-search
   based on the `upload_date` field.  YouTube's public search does not expose a
   machine-queryable date parameter.
4. **No comments or community posts**: only video metadata + transcripts.
5. **Paid/private videos**: yt-dlp returns no data for age-restricted, private,
   or members-only videos.

---

## Watch mode notes

`run_watchable` calls `search_videos` with a slightly larger result set and
filters by `upload_date > since`.  The `upload_date` field is a YYYYMMDD string
from yt-dlp (day-resolution only).  For fast-moving topics (breaking news,
product launches), set Watch cadence to daily; hourly is rarely worth the
request cost for YouTube.
