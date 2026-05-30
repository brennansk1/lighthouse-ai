"""Web Monitor skill — user-defined website monitors (Watch v2, FUTURE_FEATURES §1).

Lets a user point Watch at an arbitrary web page: ``run`` does a one-shot
fetch + scrapability verdict for the URL(s) in the question; ``run_watchable``
fetches each monitored URL, builds a :class:`Snapshot`, and emits a tagged
"change" Document when the page differs from the prior snapshot.

Security invariants:
  - No httpx / requests / urllib / socket imports anywhere in this package; all
    outbound I/O goes through ``ctx.fetch`` only (enforced by the import guard).
  - Page bytes flow through ``ctx.fetch_and_document`` (broker-gated) for the
    change documents; the scrapability pre-flight reads ``ctx.fetch`` responses
    only to compute a verdict, never to corpus-ingest unbrokered bytes.
  - The skill holds no state. ``run_watchable`` returns the *current* snapshot
    in each change Document's metadata so the dispatcher/monitor session can
    persist it in ``state.db`` and pass the prior one back on the next tick.
"""
