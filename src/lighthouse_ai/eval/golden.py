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

from dataclasses import dataclass, field

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
    "GoldenCase",
    "GoldenSet",
    "build_golden_set",
    "build_index",
    "evaluate",
]


@dataclass(frozen=True)
class GoldenCase:
    """One labelled query: text plus the document ids that should be retrieved."""

    query: str
    relevant_doc_ids: frozenset[str]


@dataclass(frozen=True)
class GoldenSet:
    """An immutable bundle of documents and their labelled queries.

    Bundling the two together keeps the contract obvious: the relevant ids in
    every case must refer to documents present in ``documents``.
    """

    documents: tuple[Document, ...]
    cases: tuple[GoldenCase, ...]


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


def evaluate(
    hybrid: HybridSearch, golden: GoldenSet, *, k: int = 5
) -> dict[str, float]:
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
