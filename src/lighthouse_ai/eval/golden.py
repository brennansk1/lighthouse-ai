"""A small, built-in golden set + an end-to-end ``evaluate()``.

Why ship the golden set in code rather than a data file: it must run with zero
setup (no fixtures to download, no model to load) so the harness can act as a
fast CI gate and a living example of how to wire up :class:`HybridSearch`.

The documents are deliberately written with strong, topic-distinct lexical
signal. The test-tier embedder (``HashEmbedder``) and BM25 are both purely
lexical, so topical word overlap is the only signal available; phrasing the
corpus this way lets the harness demonstrate real, non-trivial retrieval
numbers. Queries reuse vocabulary from their target documents so a working
pipeline should rank the right document first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..rag.bm25 import BM25Index
from ..rag.chunker import Document, chunk_document
from ..rag.embedder import Embedder, HashEmbedder
from ..rag.hybrid import HybridSearch
from ..rag.rerank import Reranker, ScoreReranker
from ..rag.store import InMemoryStore, VectorStore
from .metrics import mean_metric, mrr, precision_at_k, recall_at_k

__all__ = [
    "GOLDEN_CASES",
    "GOLDEN_DOCUMENTS",
    "ContradictionCase",
    "GoldenCase",
    "GoldenSet",
    "build_golden_set",
    "build_index",
    "evaluate",
    "golden_to_json_dict",
    "load_golden_from_json",
    "save_golden_to_json",
]


@dataclass(frozen=True)
class GoldenCase:
    """One labelled query: text plus the document ids that should be retrieved."""

    query: str
    relevant_doc_ids: frozenset[str]


@dataclass(frozen=True)
class ContradictionCase:
    """One faithfulness probe: a claim with a supporting and a contradicting passage.

    Used by the entailment harness: a real NLI scorer should rate
    ``supporting_passage`` as entailing the claim and ``contradicting_passage``
    as *not* entailing it. The lexical cosine/overlap path that ``entailment``
    deliberately deleted would wave the contradiction through (high word
    overlap), so this subset is the regression that proves the real scorer earns
    its keep.
    """

    claim: str
    supporting_passage: str
    contradicting_passage: str
    id: str = ""


@dataclass(frozen=True)
class GoldenSet:
    """An immutable bundle of documents and their labelled queries.

    Bundling the two together keeps the contract obvious: the relevant ids in
    every case must refer to documents present in ``documents``. An optional
    ``contradictions`` subset rides along for the faithfulness/entailment
    harness; it is independent of the retrieval corpus.
    """

    documents: tuple[Document, ...]
    cases: tuple[GoldenCase, ...]
    contradictions: tuple[ContradictionCase, ...] = ()


# --- Corpus: 8 documents across 3 topics -----------------------------------
# Topic A: vector databases / retrieval infrastructure
# Topic B: solar power / photovoltaics
# Topic C: sourdough bread baking
GOLDEN_DOCUMENTS: tuple[Document, ...] = (
    Document(
        id="vec-hnsw",
        text=(
            "HNSW is a graph index for approximate nearest neighbor vector "
            "search. The hierarchical navigable small world graph trades "
            "recall for latency by tuning ef_construct and the m parameter. "
            "Vector databases like Qdrant build an HNSW index over embedding "
            "vectors to answer similarity queries quickly."
        ),
        metadata={"topic": "vectors"},
    ),
    Document(
        id="vec-bm25",
        text=(
            "BM25 is a sparse lexical ranking function over token frequency. "
            "It scores documents by term frequency and inverse document "
            "frequency with the k1 and b parameters. Hybrid search fuses a "
            "dense vector retriever with the sparse BM25 retriever using "
            "reciprocal rank fusion."
        ),
        metadata={"topic": "vectors"},
    ),
    Document(
        id="vec-rerank",
        text=(
            "A reranker re-scores the fused candidate chunks from hybrid "
            "search. Cross encoder rerankers read the query and chunk together "
            "and emit a relevance score, reordering the top candidates before "
            "they enter the generation context window."
        ),
        metadata={"topic": "vectors"},
    ),
    Document(
        id="solar-pv",
        text=(
            "Photovoltaic solar panels convert sunlight into electricity using "
            "silicon semiconductor cells. The photovoltaic effect frees "
            "electrons when photons strike the silicon, producing direct "
            "current that an inverter turns into alternating current for the "
            "grid."
        ),
        metadata={"topic": "solar"},
    ),
    Document(
        id="solar-battery",
        text=(
            "Home solar battery storage saves excess photovoltaic electricity "
            "for night use. Lithium iron phosphate battery packs store the "
            "daytime surplus and discharge after sunset, improving solar self "
            "consumption and grid independence for a household."
        ),
        metadata={"topic": "solar"},
    ),
    Document(
        id="bread-starter",
        text=(
            "A sourdough starter is a living culture of wild yeast and "
            "lactobacillus bacteria in flour and water. Bakers feed the "
            "starter daily so the yeast ferments the dough and the bacteria "
            "produce the sour tang of sourdough bread."
        ),
        metadata={"topic": "bread"},
    ),
    Document(
        id="bread-bake",
        text=(
            "Baking sourdough bread in a hot dutch oven traps steam so the "
            "loaf develops a crackling crust and an open crumb. The dough is "
            "scored before baking so it expands along the cut while the oven "
            "spring lifts the bread."
        ),
        metadata={"topic": "bread"},
    ),
    Document(
        id="bread-hydration",
        text=(
            "Dough hydration is the ratio of water to flour by weight in "
            "sourdough bread. Higher hydration dough is wetter and yields a "
            "more open crumb, but it is stickier and harder to shape than a "
            "low hydration dough."
        ),
        metadata={"topic": "bread"},
    ),
)


# --- 6 labelled queries -----------------------------------------------------
GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        query="how does the HNSW graph index speed up nearest neighbor vector search",
        relevant_doc_ids=frozenset({"vec-hnsw"}),
    ),
    GoldenCase(
        query="BM25 sparse lexical ranking term frequency hybrid fusion",
        relevant_doc_ids=frozenset({"vec-bm25"}),
    ),
    GoldenCase(
        query="cross encoder reranker rescores fused candidate chunks relevance",
        relevant_doc_ids=frozenset({"vec-rerank"}),
    ),
    GoldenCase(
        query="photovoltaic silicon cells convert sunlight into electricity",
        relevant_doc_ids=frozenset({"solar-pv"}),
    ),
    GoldenCase(
        query="lithium battery storage of excess solar electricity for night use",
        relevant_doc_ids=frozenset({"solar-battery"}),
    ),
    GoldenCase(
        query="sourdough starter wild yeast lactobacillus ferments the dough",
        relevant_doc_ids=frozenset({"bread-starter"}),
    ),
)


def build_golden_set() -> GoldenSet:
    """Return the immutable built-in golden set."""
    return GoldenSet(documents=GOLDEN_DOCUMENTS, cases=GOLDEN_CASES)


# --- JSON (de)serialisation -------------------------------------------------
# The in-code golden set is the zero-setup default, but a real, maintainer-
# curated set wants to live as data so it can grow past a handful of hand-typed
# documents. The schema below is the contract for that file.
#
# Schema (all keys lower_snake_case):
#
#   {
#     "version": 1,                      # int, schema version (currently 1)
#     "name": "legal-gold",              # str, optional human label
#     "documents": [                     # the retrieval corpus
#       {"id": "doc-1",                  # str, unique within the set (required)
#        "text": "...",                  # str, the passage body (required)
#        "metadata": {"topic": "..."}}   # object, optional free-form labels
#     ],
#     "queries": [                       # the labelled retrieval cases
#       {"query": "...",                 # str, the query text (required)
#        "relevant_doc_ids": ["doc-1"]}  # list[str], gold doc ids (required);
#     ],                                 #   every id MUST exist in "documents"
#     "contradictions": [                # optional faithfulness/entailment subset
#       {"id": "c-1",                    # str, optional case id
#        "claim": "...",                 # str, the asserted claim (required)
#        "supporting_passage": "...",    # str, a passage that entails it (required)
#        "contradicting_passage": "..."} # str, a passage that refutes it (required)
#     ]
#   }
#
# ``load_golden_from_json`` validates the doc-id referential integrity so a
# typo in a gold label fails loudly at load time, not as a silent recall miss.


def load_golden_from_json(path: str | Path) -> GoldenSet:
    """Load a :class:`GoldenSet` from a JSON file following the documented schema.

    Validates that every ``relevant_doc_ids`` entry refers to a document
    actually present in the set — a dangling gold id is almost always a typo,
    and surfacing it as a ``ValueError`` at load time beats letting it masquerade
    as a permanent recall miss in the metrics. The ``contradictions`` block is
    optional; when absent the returned set simply has an empty subset.

    Raises ``ValueError`` on a malformed file (missing required keys, wrong
    types, or a dangling gold doc id).
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("golden JSON root must be an object")

    docs_raw = raw.get("documents")
    if not isinstance(docs_raw, list):
        raise ValueError("golden JSON requires a 'documents' list")
    documents: list[Document] = []
    for i, d in enumerate(docs_raw):
        if not isinstance(d, dict) or "id" not in d or "text" not in d:
            raise ValueError(f"document[{i}] needs 'id' and 'text'")
        documents.append(
            Document(
                id=str(d["id"]),
                text=str(d["text"]),
                metadata=dict(d.get("metadata") or {}),
            )
        )
    doc_ids = {doc.id for doc in documents}

    queries_raw = raw.get("queries")
    if not isinstance(queries_raw, list):
        raise ValueError("golden JSON requires a 'queries' list")
    cases: list[GoldenCase] = []
    for i, q in enumerate(queries_raw):
        if not isinstance(q, dict) or "query" not in q:
            raise ValueError(f"query[{i}] needs a 'query'")
        rel = q.get("relevant_doc_ids") or []
        if not isinstance(rel, list):
            raise ValueError(f"query[{i}].relevant_doc_ids must be a list")
        rel_ids = frozenset(str(r) for r in rel)
        dangling = rel_ids - doc_ids
        if dangling:
            raise ValueError(f"query[{i}] references unknown doc ids: {sorted(dangling)}")
        cases.append(GoldenCase(query=str(q["query"]), relevant_doc_ids=rel_ids))

    contradictions: list[ContradictionCase] = []
    for i, c in enumerate(raw.get("contradictions") or []):
        required = ("claim", "supporting_passage", "contradicting_passage")
        if not isinstance(c, dict) or any(k not in c for k in required):
            raise ValueError(f"contradiction[{i}] needs {required}")
        contradictions.append(
            ContradictionCase(
                claim=str(c["claim"]),
                supporting_passage=str(c["supporting_passage"]),
                contradicting_passage=str(c["contradicting_passage"]),
                id=str(c.get("id", "")),
            )
        )

    return GoldenSet(
        documents=tuple(documents),
        cases=tuple(cases),
        contradictions=tuple(contradictions),
    )


def golden_to_json_dict(golden: GoldenSet, *, name: str | None = None) -> dict:
    """Serialise a :class:`GoldenSet` to a plain dict matching the load schema.

    The round-trip ``load_golden_from_json(... save_golden_to_json(g) ...)`` is
    lossless for the fields the schema models (ids, text, metadata, queries,
    contradictions). Frozensets are emitted as sorted lists so the output is
    deterministic and diff-friendly.
    """
    out: dict = {"version": 1}
    if name is not None:
        out["name"] = name
    out["documents"] = [
        {"id": d.id, "text": d.text, "metadata": dict(d.metadata)} for d in golden.documents
    ]
    out["queries"] = [
        {"query": c.query, "relevant_doc_ids": sorted(c.relevant_doc_ids)} for c in golden.cases
    ]
    if golden.contradictions:
        out["contradictions"] = [
            {
                "id": c.id,
                "claim": c.claim,
                "supporting_passage": c.supporting_passage,
                "contradicting_passage": c.contradicting_passage,
            }
            for c in golden.contradictions
        ]
    return out


def save_golden_to_json(golden: GoldenSet, path: str | Path, *, name: str | None = None) -> None:
    """Write ``golden`` to ``path`` as UTF-8 JSON following the documented schema."""
    payload = golden_to_json_dict(golden, name=name)
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build_index(
    golden: GoldenSet | None = None,
    *,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    reranker: Reranker | None = None,
) -> HybridSearch:
    """Chunk + index the golden documents into a real ``HybridSearch``.

    By default we assemble the test-tier pipeline (InMemoryStore + HashEmbedder
    + BM25Index + ScoreReranker) so the harness runs with zero setup. Callers
    that have real backends (bge-m3 embedder, Qdrant store, FlagReranker) inject
    them here to turn the same harness into a production quality gate. Each
    document is chunked through ``chunk_document`` so we also cover the
    chunk -> document id projection that real retrieval requires.
    """
    if golden is None:
        golden = build_golden_set()
    hybrid = HybridSearch(
        store=store if store is not None else InMemoryStore(),
        embedder=embedder if embedder is not None else HashEmbedder(),
        bm25=BM25Index(),
        reranker=reranker if reranker is not None else ScoreReranker(),
    )
    for doc in golden.documents:
        hybrid.add(chunk_document(doc))
    return hybrid


@dataclass(frozen=True)
class _CaseResult:
    """Per-query metrics; kept private since callers want aggregates."""

    query: str
    precision_at_5: float
    recall_at_5: float
    rr: float
    retrieved_doc_ids: tuple[str, ...] = field(default_factory=tuple)


def _retrieved_doc_ids(hybrid: HybridSearch, query: str, top_k: int) -> list[str]:
    """Project ranked chunk results down to their parent document ids.

    Relevance in the golden set is labelled at the document level, but the
    pipeline returns chunks. We map each result to ``chunk.document_id`` in
    rank order; the metric functions de-duplicate, so multiple chunks from one
    document collapse to that document's best rank.
    """
    results = hybrid.search(query, top_k=top_k)
    return [r.chunk.document_id for r in results]


def evaluate(hybrid: HybridSearch, golden: GoldenSet, *, k: int = 5) -> dict[str, float]:
    """Run every golden query and return aggregate retrieval metrics.

    Returns a dict keyed ``"precision@5"``, ``"recall@5"``, ``"mrr"`` (the key
    suffix follows ``k`` so changing ``k`` keeps the labels honest). The point
    of returning plain floats is that this is an *instrument*: callers log the
    numbers, gate CI on thresholds, or diff them across embedder swaps.
    """
    per_case: list[_CaseResult] = []
    for case in golden.cases:
        ranked = _retrieved_doc_ids(hybrid, case.query, top_k=k)
        per_case.append(
            _CaseResult(
                query=case.query,
                precision_at_5=precision_at_k(ranked, case.relevant_doc_ids, k),
                recall_at_5=recall_at_k(ranked, case.relevant_doc_ids, k),
                rr=mrr(ranked, case.relevant_doc_ids),
                retrieved_doc_ids=tuple(ranked),
            )
        )
    return {
        f"precision@{k}": mean_metric(c.precision_at_5 for c in per_case),
        f"recall@{k}": mean_metric(c.recall_at_5 for c in per_case),
        "mrr": mean_metric(c.rr for c in per_case),
    }
