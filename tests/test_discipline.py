"""Quality discipline (§12) + Logseq export + source adapters."""

from __future__ import annotations

import httpx
import respx

from lighthouse_ai.verification.discipline import (
    check,
    downgrade_wep,
    extract_claims,
)

# --- claim extraction ---

def test_extract_claims_captures_citations():
    text = "Decoherence is the central challenge [1]. Error correction helps [1,2]."
    claims = extract_claims(text)
    assert len(claims) == 2
    assert claims[0].citation_ids == [1]
    assert claims[1].citation_ids == [1, 2]
    assert claims[1].is_two_sourced


def test_extract_skips_questions_and_fragments():
    text = "What is X? Yes. This is a real declarative sentence with content [1]."
    claims = extract_claims(text)
    assert len(claims) == 1
    assert "declarative" in claims[0].text


# --- discipline gate ---

def test_check_passes_when_well_sourced():
    text = ("The sky appears blue due to Rayleigh scattering [1]. "
            "Shorter wavelengths scatter more strongly [2]. "
            "This effect is wavelength dependent [1].")
    rep = check(text, min_coverage=0.6)
    assert rep.passed
    assert rep.citation_coverage == 1.0


def test_check_flags_unsourced():
    text = ("The market will crash next week. Interest rates drive everything. "
            "Only this final claim has a source [1].")
    rep = check(text, min_coverage=0.6)
    assert not rep.passed
    assert rep.unsourced >= 2
    assert rep.notes


def test_two_source_rule_for_high_stakes():
    text = "Vaccine X is safe for infants [1]. It prevents disease Y [1]."
    rep = check(text, high_stakes=True)
    # single-citation claims fail the two-source rule
    assert not rep.passed
    assert any("two-source" in n for n in rep.notes)


def test_check_empty_text():
    assert not check("").passed


# --- WEP downgrade ---

def test_downgrade_lowers_band_for_poor_sourcing():
    poor = check("Unsourced claim one here. Unsourced claim two here.")
    good = check("Sourced claim one here [1]. Sourced claim two here [2].")
    band_poor = downgrade_wep(0.75, poor)
    band_good = downgrade_wep(0.75, good)
    # poorly-sourced answer must land in a lower band than the well-sourced one
    order = ["remote", "unlikely", "even", "likely", "almost_certain"]
    assert order.index(band_poor.name) < order.index(band_good.name)


# --- Logseq export ---

def test_logseq_export_writes_page(tmp_path):
    from lighthouse_ai.targets.logseq import export_draft
    page = export_draft(tmp_path / "graph", draft_id="d-1",
                        title="Quantum challenge", body_html="<h2>Finding</h2><p>Body text here.</p>",
                        topic="physics", wep_phrase="likely", source_count=3)
    assert page.path.exists()
    md = page.path.read_text()
    assert "title:: Quantum challenge" in md
    assert "lighthouse-draft-id:: d-1" in md
    assert "confidence:: likely" in md
    assert "## Finding" in md


def test_logseq_export_strips_style_and_script(tmp_path):
    from lighthouse_ai.targets.logseq import export_draft
    html = ("<style>:root { --bg:#fff; } body { color: red; }</style>"
            "<h2>Real Heading</h2><p>Actual content.</p>"
            "<script>alert(1)</script>")
    page = export_draft(tmp_path / "g", draft_id="d-9", title="T", body_html=html)
    md = page.path.read_text()
    assert "Real Heading" in md and "Actual content" in md
    assert "--bg" not in md and "alert(1)" not in md   # no CSS/JS leaked


def test_logseq_export_idempotent_uuid(tmp_path):
    from lighthouse_ai.targets.logseq import export_draft
    a = export_draft(tmp_path / "g", draft_id="d-1", title="T", body_html="<p>x</p>")
    b = export_draft(tmp_path / "g", draft_id="d-1", title="T", body_html="<p>y</p>")
    assert a.uuid == b.uuid          # same draft → same block id
    assert a.path == b.path          # overwrites, no duplicate


# --- arXiv adapter ---

ARXIV_XML = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001</id>
    <title>Quantum Error Correction Advances</title>
    <summary>We present new surface codes for fault tolerance.</summary>
    <published>2024-01-01T00:00:00Z</published>
  </entry>
</feed>"""


@respx.mock
def test_arxiv_search_parses():
    from lighthouse_ai.sources.arxiv import search_arxiv
    respx.get("http://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(200, content=ARXIV_XML))
    docs = search_arxiv("quantum error correction", max_results=1)
    assert len(docs) == 1
    assert "Quantum Error Correction" in docs[0].text
    assert docs[0].metadata["source"] == "arxiv"
    assert docs[0].metadata["grade"] == "A"


# --- OpenAlex adapter ---

OPENALEX_JSON = {
    "results": [{
        "id": "https://openalex.org/W123",
        "title": "Topological Qubits Review",
        "publication_date": "2025-03-01",
        "cited_by_count": 42,
        "abstract_inverted_index": {"Topological": [0], "qubits": [1], "resist": [2],
                                    "errors": [3]},
    }]
}


def test_check_source_diversity_counts_distinct_domains():
    from lighthouse_ai.rag.chunker import Chunk
    from lighthouse_ai.rag.hybrid import HybridResult
    from lighthouse_ai.verification.discipline import check_source_diversity
    def _hr(doc_id, source):
        c = Chunk(id=f"{doc_id}:0", document_id=doc_id, text="text",
                  position=0, metadata={"source": source})
        return HybridResult(chunk=c, score=1.0, dense_rank=1, sparse_rank=1)
    results = [_hr("a1", "arxiv"), _hr("a2", "arxiv"), _hr("p1", "pubmed")]
    assert check_source_diversity(results) == 2

def test_check_source_diversity_empty():
    from lighthouse_ai.verification.discipline import check_source_diversity
    assert check_source_diversity([]) == 0

def test_check_source_diversity_falls_back_to_document_id():
    from lighthouse_ai.rag.chunker import Chunk
    from lighthouse_ai.rag.hybrid import HybridResult
    from lighthouse_ai.verification.discipline import check_source_diversity
    c = Chunk(id="d:0", document_id="my_doc", text="x", position=0, metadata={})
    r = HybridResult(chunk=c, score=1.0, dense_rank=1, sparse_rank=1)
    assert check_source_diversity([r]) == 1


@respx.mock
def test_openalex_search_reconstructs_abstract():
    from lighthouse_ai.sources.openalex import search_openalex
    respx.get("https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json=OPENALEX_JSON))
    docs = search_openalex("topological qubits", max_results=1)
    assert len(docs) == 1
    assert "Topological qubits resist errors" in docs[0].text
    assert docs[0].metadata["cited_by"] == 42
