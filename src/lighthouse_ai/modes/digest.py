"""Mode D — Daily / weekly digest (§9.4).

Aggregates monitor outputs across all watched topics into a single
HTML/markdown bulletin. The aggregator is pure; the IO (write to file,
notify Telegram) is the caller's job.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .monitor import ClassifiedItem, MonitorReport


@dataclass(frozen=True)
class DigestSection:
    topic: str
    alert_count: int
    digest_count: int
    suppressed: int
    items: list[ClassifiedItem]


@dataclass(frozen=True)
class Digest:
    period_label: str
    generated_at: str
    sections: list[DigestSection] = field(default_factory=list)
    total_alerts: int = 0
    total_items: int = 0


def aggregate_digest(reports: list[MonitorReport], *,
                     period_label: str | None = None) -> Digest:
    by_topic: dict[str, list[MonitorReport]] = defaultdict(list)
    for r in reports:
        by_topic[r.topic].append(r)
    sections: list[DigestSection] = []
    total_alerts = 0
    total_items = 0
    for topic, rs in by_topic.items():
        alerts = [a for r in rs for a in r.alerts]
        digest = [d for r in rs for d in r.digest]
        suppressed = sum(r.suppressed_duplicates for r in rs)
        seen = sum(r.total_seen for r in rs)
        items = alerts + digest[:5]  # top 5 of digest per topic
        sections.append(DigestSection(
            topic=topic, alert_count=len(alerts),
            digest_count=len(digest), suppressed=suppressed, items=items,
        ))
        total_alerts += len(alerts)
        total_items += seen
    sections.sort(key=lambda s: s.alert_count, reverse=True)
    return Digest(
        period_label=period_label or date.today().isoformat(),
        generated_at=date.today().isoformat(),
        sections=sections, total_alerts=total_alerts,
        total_items=total_items,
    )
