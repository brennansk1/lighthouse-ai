# compounding/

Compounding knowledge: deterministic entity-importance scoring and the
job → durable-corpus archivist. (OpenHuman §2 + §8.)

## Public surface

- `hotness.py` — `hotness`/`hotness_at`, `recency_decay`, `EntityStats`,
  `HotnessBreakdown` (five named terms), `TOPIC_CREATION_THRESHOLD` (= 10.0).
- `archivist.py` — `clean_turns`, `compose_md`, `report_to_markdown`,
  `archive_report`, `archive_conversation`, `ArchiveOutcome`.

## Calls into

- `..targets.logseq.export_draft` — optional Logseq page on archive.
- (hotness has no internal deps — pure functions.)

## Called by

- `..modes.monitor.make_hotness_salience` — hotness-backed salience scorer.
- (planned) dossier materialisation when `hotness(entity) ≥ TOPIC_CREATION_THRESHOLD`;
  finished Deep-Dive/QUC jobs → `archive_report` / `archive_conversation`.

## Invariants

- `distinct_sources` is the count of *independent* sources (discipline-layer
  semantics), never raw citation count.
- Hotness is monotonic in mentions/sources/query-hits and non-increasing in age.
- Archive artifacts are content-addressed (sha256) → archiving twice is idempotent.
