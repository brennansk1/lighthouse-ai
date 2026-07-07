"""Deterministic local Graph-RAG primitive (FUTURE_FEATURES.md §"Graph-RAG").

A *corpus entity-relation graph* built purely from chunk text - no LLM, no
network, fully offline and deterministic. It lets a researcher see how
entities/concepts relate across a body of evidence: nodes are entities,
undirected edges are *co-occurrence within the same chunk*, weighted by how
often two entities appear together.

This is the retrieval-side foundation the Adaptive-RAG ``GRAPH`` route
(:mod:`lighthouse_ai.framing.router`) would call later to "graph-expand" a
query. Surfacing it in a mode/route/UI is a separate, later step - this module
is just the standalone primitive.

Scope (per FUTURE_FEATURES.md §Graph-RAG): *local corpus graph + relation
extraction by co-occurrence*. Causal inference is a labeled STRETCH and is
deliberately **not** implemented here.

Determinism / offline guarantees
--------------------------------
* No ``datetime.now()``; no import-time side effects; no I/O.
* Entity extraction is a fixed regex + stopword heuristic (no models).
* All public outputs use stable ordering with explicit tie-breaks
  (weight desc, then entity name / id asc), so the same input yields a
  byte-identical result across builds.

Bounded build (pathological-corpus safety)
-------------------------------------------
Every accumulation is capped so a hostile or huge corpus can't blow up build
time or memory. The caps are class-level constants on :class:`CorpusGraph`
(overridable via :func:`build_corpus_graph`):

* ``MAX_ENTITIES_PER_CHUNK`` - entities considered per chunk (caps the
  per-chunk co-occurrence pair count, which is otherwise O(n²)).
* ``MAX_NODES`` - total distinct entities kept (the most frequent win).
* ``MAX_EDGES`` - total distinct undirected edges kept (the heaviest win).
* ``MAX_CHUNK_IDS_PER_ENTITY`` - chunk ids tracked per entity.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CorpusGraph",
    "Edge",
    "Node",
    "build_corpus_graph",
    "extract_entities",
]

# --------------------------------------------------------------------------- #
# Entity extraction (deterministic, model-free)
#
# Style follows sandbox/analysis._extract_entities (regex + tiny stopword set),
# but this is a clean, self-contained extractor tuned for *graph nodes*: we
# want normalized, reusable concept/proper-noun/acronym entities, not dates or
# raw numbers (those make poor relation nodes).
# --------------------------------------------------------------------------- #

# Multi-word Capitalized phrase (proper nouns, titled concepts), up to 4 words.
_CAP_PHRASE_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3}\b")
# Acronyms / all-caps tokens (2-6 chars), e.g. NASA, RNA, GDP.
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")

# Tiny offline stopword set (mirrors analysis.py's spirit; lowercased).
_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "he",
        "she",
        "they",
        "we",
        "you",
        "i",
        "not",
        "no",
        "can",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "how",
        "what",
        "when",
        "which",
        "who",
        "whom",
        "whose",
        "than",
        "then",
        "there",
        "here",
        "their",
        "our",
        "your",
        "his",
        "her",
        "them",
        "us",
        "if",
        "so",
        "such",
        "also",
        "into",
        "over",
        "under",
        "about",
        "after",
        "before",
        "between",
        "across",
        "within",
        "while",
        # Sentence-initial capitalized function words that pollute phrase hits.
        "however",
        "therefore",
        "thus",
        "moreover",
        "meanwhile",
        "first",
        "second",
        "third",
        "next",
        "finally",
        "because",
        "although",
    ]
)

_MIN_TOKEN_LEN = 3  # drop too-short single tokens after normalization


def _normalize(entity: str) -> str:
    """Collapse internal whitespace and lowercase for matching/dedupe."""
    return re.sub(r"\s+", " ", entity).strip().lower()


def _trim_stopwords(display: str) -> str:
    """Strip leading/trailing stopword tokens from a capitalized phrase.

    A sentence-initial ``The``/``In`` etc. gets swept into the regex match
    ("The World Health Organization"); trimming them yields the real entity.
    Returns ``""`` if every token is a stopword.
    """
    words = re.sub(r"\s+", " ", display).strip().split(" ")
    while words and words[0].lower() in _STOPWORDS:
        words.pop(0)
    while words and words[-1].lower() in _STOPWORDS:
        words.pop()
    return " ".join(words)


def _is_meaningful(display: str) -> bool:
    """A candidate is kept if it has a multi-word form, is an acronym, or is a
    single token long enough and not a stopword."""
    norm = _normalize(display)
    if not norm:
        return False
    if " " in norm:
        # Multi-word phrase: drop only if *every* word is a stopword.
        words = norm.split(" ")
        return not all(w in _STOPWORDS for w in words)
    # Single token.
    if display.isupper() and 2 <= len(display) <= 6:
        return True  # acronym
    if len(norm) < _MIN_TOKEN_LEN:
        return False
    return norm not in _STOPWORDS


def extract_entities(text: str, *, max_entities: int | None = None) -> list[str]:
    """Extract normalized entity *display forms* from ``text``.

    Returns proper-noun / titled / multi-word-capitalized phrases and acronyms,
    deduped (case-insensitively) and in **stable order of first appearance**.
    The returned strings are the canonical *display* form (the first-seen
    capitalization); call :func:`_normalize` for the matching key.

    Deterministic: same text -> identical list. ``max_entities`` (if given)
    truncates after dedupe, keeping the earliest occurrences.
    """
    if not text:
        return []

    seen: dict[str, str] = {}  # normalized -> first-seen display form
    order: list[str] = []  # normalized keys in first-appearance order

    def _consider(raw: str) -> None:
        display = re.sub(r"\s+", " ", raw).strip()
        if " " in display:
            display = _trim_stopwords(display)
        if not _is_meaningful(display):
            return
        key = _normalize(display)
        if key not in seen:
            seen[key] = display
            order.append(key)

    # Collect candidates with their start offsets so first-appearance order is
    # stable regardless of which regex matched (sort by position, then text).
    candidates: list[tuple[int, str]] = []
    for m in _CAP_PHRASE_RE.finditer(text):
        candidates.append((m.start(), m.group(0)))
    for m in _ACRONYM_RE.finditer(text):
        candidates.append((m.start(), m.group(0)))
    candidates.sort(key=lambda t: (t[0], t[1]))

    for _pos, raw in candidates:
        _consider(raw)

    result = [seen[k] for k in order]
    if max_entities is not None:
        result = result[:max_entities]
    return result


# --------------------------------------------------------------------------- #
# Graph data structures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Node:
    """A graph node: one entity.

    ``id`` is the normalized (lowercase) key used for matching; ``label`` is the
    human display form; ``weight`` is the number of chunks the entity appears in;
    ``chunk_ids`` is the (bounded, sorted) set of chunks it occurs in.
    """

    id: str
    label: str
    weight: int
    chunk_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Edge:
    """An undirected co-occurrence edge. ``source`` < ``target`` lexically so
    each unordered pair is stored once. ``weight`` = co-occurrence count."""

    source: str
    target: str
    weight: int


def _coerce_chunk(chunk: Any, index: int) -> tuple[str, str]:
    """Return ``(chunk_id, text)`` from a chunk object or dict.

    Accepts anything with ``.text`` (and optional ``.id``/``.document_id``) or a
    mapping with ``"text"`` (and optional ``"id"``/``"document_id"``). Falls back
    to a positional id ``"chunk:<index>"`` when none is provided.
    """
    text: str
    cid: Any = None
    if isinstance(chunk, Mapping):
        text = str(chunk.get("text", "") or "")
        cid = chunk.get("id") or chunk.get("document_id")
    else:
        text = str(getattr(chunk, "text", "") or "")
        cid = getattr(chunk, "id", None) or getattr(chunk, "document_id", None)
    chunk_id = str(cid) if cid else f"chunk:{index}"
    return chunk_id, text


@dataclass
class CorpusGraph:
    """An entity co-occurrence graph over a corpus of chunks.

    Build it via :func:`build_corpus_graph`. All query methods are deterministic
    and pure; the graph is immutable after construction.
    """

    # --- bounds (pathological-corpus safety) - see module docstring ---
    MAX_ENTITIES_PER_CHUNK: int = 64
    MAX_NODES: int = 5000
    MAX_EDGES: int = 50000
    MAX_CHUNK_IDS_PER_ENTITY: int = 200

    # --- populated by build (do not mutate after) ---
    _nodes: dict[str, Node] = field(default_factory=dict)
    # adjacency: entity_id -> {neighbor_id: weight}
    _adj: dict[str, dict[str, int]] = field(default_factory=dict)
    # entity_id -> ordered tuple of chunk ids (bounded)
    _entity_chunks: dict[str, tuple[str, ...]] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def __len__(self) -> int:
        return len(self._nodes)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(n) for n in self._adj.values()) // 2

    def has_entity(self, entity: str) -> bool:
        return _normalize(entity) in self._nodes

    def entities(self) -> list[tuple[str, int]]:
        """All entities as ``(display_label, weight)``, sorted by weight desc
        then label asc (stable, deterministic)."""
        nodes = sorted(self._nodes.values(), key=lambda n: (-n.weight, n.id))
        return [(n.label, n.weight) for n in nodes]

    # ------------------------------------------------------------------ #
    # Neighborhood / retrieval
    # ------------------------------------------------------------------ #

    def neighbors(self, entity: str, *, k: int = 10) -> list[tuple[str, int]]:
        """Top-``k`` co-occurring entities of ``entity`` as
        ``(display_label, edge_weight)``, sorted by weight desc then label asc.

        Returns ``[]`` if the entity is absent (never raises). ``k <= 0`` -> ``[]``.
        """
        key = _normalize(entity)
        if key not in self._adj or k <= 0:
            return []
        pairs = sorted(
            self._adj[key].items(),
            key=lambda kv: (-kv[1], self._nodes[kv[0]].id),
        )
        return [(self._nodes[nid].label, w) for nid, w in pairs[:k]]

    def related_chunk_ids(self, entity: str, *, k: int = 10) -> list[str]:
        """Chunk ids where ``entity`` or one of its strongest neighbors appears.

        The entity's own chunks come first (highest signal), then chunks of its
        top neighbors by edge weight, deduped while preserving that priority and
        capped at ``k``. Returns ``[]`` for an unknown entity. ``k <= 0`` -> ``[]``.
        """
        key = _normalize(entity)
        if key not in self._nodes or k <= 0:
            return []
        out: list[str] = []
        seen: set[str] = set()

        def _take(ids: Iterable[str]) -> None:
            for cid in ids:
                if cid not in seen:
                    seen.add(cid)
                    out.append(cid)

        _take(self._entity_chunks.get(key, ()))
        # Strong neighbors next, by descending edge weight then name.
        for nid, _w in sorted(
            self._adj.get(key, {}).items(),
            key=lambda kv: (-kv[1], self._nodes[kv[0]].id),
        ):
            if len(out) >= k:
                break
            _take(self._entity_chunks.get(nid, ()))
        return out[:k]

    def query(self, text: str, *, k: int = 10) -> dict[str, list[str]]:
        """Graph-expand a query: extract its entities, match them into the graph,
        and return the most-connected related entities plus the chunk ids that
        cover them.

        This is the retrieval signal a GRAPH route uses. Returns
        ``{"entities": [labels...], "chunk_ids": [ids...]}`` - both deterministic
        and bounded by ``k``. Query entities not present in the graph are
        ignored; if none match, both lists are empty.
        """
        if k <= 0:
            return {"entities": [], "chunk_ids": []}

        query_entities = [
            _normalize(e) for e in extract_entities(text, max_entities=self.MAX_ENTITIES_PER_CHUNK)
        ]
        matched = [e for e in query_entities if e in self._nodes]

        # Score related entities: matched seeds (by their own weight) plus their
        # neighbors (by edge weight), accumulated. Deterministic tie-break on id.
        scores: dict[str, int] = defaultdict(int)
        for seed in matched:
            scores[seed] += self._nodes[seed].weight
            for nid, w in self._adj.get(seed, {}).items():
                scores[nid] += w

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        top_ids = [nid for nid, _ in ranked[:k]]
        entity_labels = [self._nodes[nid].label for nid in top_ids]

        # Cover chunks: union of chunk ids of the top related entities, ordered
        # by entity rank then chunk id, deduped, capped at k.
        chunk_ids: list[str] = []
        seen: set[str] = set()
        for nid in top_ids:
            for cid in self._entity_chunks.get(nid, ()):
                if cid not in seen:
                    seen.add(cid)
                    chunk_ids.append(cid)
                if len(chunk_ids) >= k:
                    break
            if len(chunk_ids) >= k:
                break

        return {"entities": entity_labels, "chunk_ids": chunk_ids}

    # ------------------------------------------------------------------ #
    # Paths / subgraph
    # ------------------------------------------------------------------ #

    def path(self, a: str, b: str, *, max_hops: int = 4) -> list[str] | None:
        """Shortest entity path (BFS) from ``a`` to ``b`` as a list of display
        labels, or ``None`` if no path within ``max_hops`` (or either endpoint
        is absent). ``a == b`` returns the single-node path. Edge weights are
        ignored (hop-count shortest path).

        Deterministic: ties in BFS frontier are broken by node id, so the
        returned path is stable.
        """
        ka, kb = _normalize(a), _normalize(b)
        if ka not in self._nodes or kb not in self._nodes:
            return None
        if ka == kb:
            return [self._nodes[ka].label]
        if max_hops <= 0:
            return None

        # BFS with deterministic neighbor ordering.
        prev: dict[str, str] = {ka: ka}
        frontier: deque[tuple[str, int]] = deque([(ka, 0)])
        while frontier:
            node, depth = frontier.popleft()
            if depth >= max_hops:
                continue
            for nid in sorted(self._adj.get(node, {}).keys()):
                if nid in prev:
                    continue
                prev[nid] = node
                if nid == kb:
                    return self._reconstruct(prev, ka, kb)
                frontier.append((nid, depth + 1))
        return None

    def _reconstruct(self, prev: dict[str, str], start: str, end: str) -> list[str]:
        chain: list[str] = []
        cur = end
        while cur != start:
            chain.append(cur)
            cur = prev[cur]
        chain.append(start)
        chain.reverse()
        return [self._nodes[k].label for k in chain]

    def subgraph(
        self, seeds: Iterable[str], *, hops: int = 1, max_nodes: int = 40
    ) -> dict[str, list[dict[str, Any]]]:
        """JSON-serializable neighborhood around ``seeds`` (for a future viz).

        Expands ``hops`` BFS levels from each seed that exists in the graph,
        capping at ``max_nodes`` (seeds and highest-weight nodes prioritized).
        Returns ``{"nodes": [{id,label,weight}...], "edges":
        [{source,target,weight}...]}``. Self-edges are excluded; each undirected
        edge appears once (source<target). Deterministic ordering.
        """
        seed_keys = [_normalize(s) for s in seeds]
        seed_keys = [s for s in seed_keys if s in self._nodes]
        if max_nodes <= 0 or not seed_keys:
            return {"nodes": [], "edges": []}

        # BFS expansion collecting reachable node ids within `hops`.
        reached: set[str] = set(seed_keys)
        frontier: set[str] = set(seed_keys)
        for _ in range(max(0, hops)):
            nxt: set[str] = set()
            for node in frontier:
                for nid in self._adj.get(node, {}):
                    if nid not in reached:
                        nxt.add(nid)
            reached |= nxt
            frontier = nxt
            if not frontier:
                break

        # Cap: keep seeds + heaviest nodes up to max_nodes.
        kept = sorted(
            reached, key=lambda nid: (nid not in seed_keys, -self._nodes[nid].weight, nid)
        )[:max_nodes]
        kept_set = set(kept)

        nodes = [
            {"id": nid, "label": self._nodes[nid].label, "weight": self._nodes[nid].weight}
            for nid in sorted(kept, key=lambda nid: (-self._nodes[nid].weight, nid))
        ]

        edges: list[dict[str, Any]] = []
        emitted: set[tuple[str, str]] = set()
        for src in sorted(kept_set):
            for tgt, w in self._adj.get(src, {}).items():
                if tgt not in kept_set or src == tgt:
                    continue
                pair = (src, tgt) if src < tgt else (tgt, src)
                if pair in emitted:
                    continue
                emitted.add(pair)
                edges.append({"source": pair[0], "target": pair[1], "weight": w})
        edges.sort(key=lambda e: (-int(e["weight"]), str(e["source"]), str(e["target"])))

        return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #


def build_corpus_graph(
    chunks: Iterable[Any],
    *,
    max_entities_per_chunk: int | None = None,
    max_nodes: int | None = None,
    max_edges: int | None = None,
    max_chunk_ids_per_entity: int | None = None,
) -> CorpusGraph:
    """Build a :class:`CorpusGraph` from an iterable of chunks.

    ``chunks`` may be :class:`~lighthouse_ai.rag.chunker.Chunk` objects, any
    object with a ``.text`` attribute (and optional ``.id``/``.document_id``), or
    dicts with ``"text"`` (and optional ``"id"``/``"document_id"``). Chunks
    without an id get a positional id ``"chunk:<index>"``.

    Deterministic: the same chunk sequence always yields the same graph. The
    optional ``max_*`` keywords override the default caps (see
    :class:`CorpusGraph`). An empty corpus yields an empty graph.
    """
    g = CorpusGraph(
        MAX_ENTITIES_PER_CHUNK=(
            max_entities_per_chunk
            if max_entities_per_chunk is not None
            else CorpusGraph.MAX_ENTITIES_PER_CHUNK
        ),
        MAX_NODES=max_nodes if max_nodes is not None else CorpusGraph.MAX_NODES,
        MAX_EDGES=max_edges if max_edges is not None else CorpusGraph.MAX_EDGES,
        MAX_CHUNK_IDS_PER_ENTITY=(
            max_chunk_ids_per_entity
            if max_chunk_ids_per_entity is not None
            else CorpusGraph.MAX_CHUNK_IDS_PER_ENTITY
        ),
    )

    # First pass: per-entity chunk membership + co-occurrence pair counts.
    entity_label: dict[str, str] = {}  # key -> display label (first seen)
    entity_chunk_set: dict[str, list[str]] = defaultdict(list)  # key -> chunk ids
    entity_chunk_seen: dict[str, set[str]] = defaultdict(set)
    pair_counts: Counter[tuple[str, str]] = Counter()

    for index, chunk in enumerate(chunks):
        chunk_id, text = _coerce_chunk(chunk, index)
        displays = extract_entities(text, max_entities=g.MAX_ENTITIES_PER_CHUNK)
        # Dedupe to keys for this chunk (an entity counts once per chunk).
        keys: list[str] = []
        seen_in_chunk: set[str] = set()
        for disp in displays:
            key = _normalize(disp)
            if key in seen_in_chunk:
                continue
            seen_in_chunk.add(key)
            keys.append(key)
            entity_label.setdefault(key, disp)
            if (
                chunk_id not in entity_chunk_seen[key]
                and len(entity_chunk_set[key]) < g.MAX_CHUNK_IDS_PER_ENTITY
            ):
                entity_chunk_seen[key].add(chunk_id)
                entity_chunk_set[key].append(chunk_id)

        # Co-occurrence pairs within this chunk (undirected, source<target).
        skeys = sorted(set(keys))
        for i in range(len(skeys)):
            for j in range(i + 1, len(skeys)):
                pair_counts[(skeys[i], skeys[j])] += 1

    # Second pass: select kept nodes (by weight = #chunks, then name).
    weights = {key: len(ids) for key, ids in entity_chunk_set.items()}
    ranked_keys = sorted(weights.keys(), key=lambda key: (-weights[key], key))
    kept_keys = set(ranked_keys[: g.MAX_NODES])

    for key in kept_keys:
        g._nodes[key] = Node(
            id=key,
            label=entity_label[key],
            weight=weights[key],
            chunk_ids=tuple(entity_chunk_set[key]),
        )
        g._entity_chunks[key] = tuple(entity_chunk_set[key])
        g._adj[key] = {}

    # Select kept edges (heaviest first), bounded by MAX_EDGES, both ends kept.
    ranked_pairs = sorted(pair_counts.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
    edge_budget = g.MAX_EDGES
    for (src, tgt), w in ranked_pairs:
        if edge_budget <= 0:
            break
        if src not in kept_keys or tgt not in kept_keys or src == tgt:
            continue
        g._adj[src][tgt] = w
        g._adj[tgt][src] = w
        edge_budget -= 1

    return g
