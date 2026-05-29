# Sprint 28 — Research-Quality Push

Goal: close the gap to leading open deep-research stacks by upgrading the *quality* of each mode, not
adding new ones. Driven by the improvement analysis across five areas (retrieval, framing, denoising,
orchestration, evaluation). See `MODE_PROCESSES.md` for the current start-to-end behavior each item
modifies.

**Resource guardrails (binding):** no heavy model is downloaded by default or in CI. Every model-based
upgrade lands as a **lazy-imported, optional-dependency, injected-scorer** adapter that degrades to the
existing heuristic when the dep/model is absent — the established `FlagReranker` pattern. Real-backend
behavior is exercised only under `LIGHTHOUSE_REAL_BACKEND=1`. No background processes.

## Guiding decisions (from the analysis)

- **Highest leverage = retrieval reranking.** Golden-set precision@5 ≈ 0.17 with recall@5 ≈ 0.83 is the
  exact signature a cross-encoder fixes. Anthropic "Contextual Retrieval" (2024-09-19): reranking +
  contextual embeddings + contextual BM25 cut top-20 retrieval failure 67% (5.7%→1.9%).
- **LangGraph only for Mode B** (and secondarily Mode E). Modes A/C/D are fixed workflows — keep the
  plain Python loop. LangGraph earns its keep where checkpointing, interrupt/resume, fan-out/fan-in, and
  SSE streaming matter (steerable Deep-Dive).
- **No new modes yet.** PRISMA, comparison-matrix, timeline, hypothesis-gen, living-document are all
  Deep-Dive presets + a structured-output schema. The one genuinely new mode (citation-graph,
  Connected-Papers style) needs an external API / local OpenAlex dump and breaks local-first — punt.

## Model / dependency choices (all local-capable)

| Role | Model | License | Footprint | Notes |
|------|-------|---------|-----------|-------|
| Reranker (primary) | `BAAI/bge-reranker-v2-m3` via `FlagEmbedding` | MIT | ~1.1 GB FP16 (568M) | cross-encoder; ~8 ms/pair CPU |
| Reranker (upgrade) | `Qwen3-Reranker-0.6B` | Apache-2.0 | 0.6B | +8 pts MTEB-R/MMTEB-R over bge-reranker |
| Contradiction NLI | `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` | MIT | ~900 MB FP16 (435M) | entail/neutral/contradict; doubles as Debate stance |
| Grounding (fast) | `vectara/hallucination_evaluation_model` (HHEM-2.1) | Apache-2.0 | <600 MB (184M) | 0–1 support score per claim |
| Citation faithfulness | `lytang/MiniCheck-Flan-T5-Large` | MIT | ~770M | GPT-4-level fact-check <1B; escalation tier |
| Claim decomposition | `factscore` (PyPI) + Core extension | MIT | — | atomic-claim split replacing regex |
| Injection (added layer) | `protectai/deberta-v3-base-prompt-injection-v2` | Apache-2.0 | ~500 MB (184M), ONNX | additive: `max(regex, deberta) ≥ 0.5` |
| Framing classifier fallback | `MoritzLaurer/deberta-v3-base-zeroshot-v2.0` | MIT | ~184M | deterministic when LLM gated |
| Synthesizer floor | `qwen3:14b` Q4 | Apache-2.0 | ~9 GB | report writer floor on 24 GB M4 |
| Synthesizer ceiling | `Alibaba-NLP/Tongyi-DeepResearch-30B-A3B` Q4 | Apache-2.0 | ~17 GB (3.3B active) | profile RAM under load first |
| Framing program | `dspy` (PyPI) | MIT | — | `BootstrapFewShot` over 30–50 golden set |
| Orchestration (Mode B) | `langgraph` + `SqliteSaver` | MIT | — | pin tightly (API churned in 2025) |
| Eval | `ragas` (PyPI) + DeepResearch Bench (`Ayanami0730/deep_research_bench`) | — | — | RAGAS in CI; bench monthly |

## Ordered plan (success criterion in parens)

1. **Wire the reranker** — replace `ScoreReranker` passthrough with `make_reranker()`
   (`FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=True)` when available). HybridSearch:
   retrieve 50 → rerank → 8. *(precision@5 ≥ 0.40; if <0.30 try Qwen3-Reranker-0.6B)*  ← **this sprint**
2. **Persist MonitorState dedup ledger** to SQLite (`monitor_dedupe(url_sha PK, first_seen, embedding)`).
   *(dedupe survives restart)*
3. **Activate Contextual Retrieval prepass** (`rag/contextual.py`); re-index.
   *(precision@5 ≥ 0.55 after reranker + contextual)*
4. **Real denoiser** for Mode B — atomic-claim extraction + HHEM-2.1 grounding + DeBERTa-v3 NLI
   contradiction surfacing + targeted re-retrieval + regenerate working report.
   *(reports show explicit contradiction-resolution; RAGAS faithfulness ≥ 0.80)*
5. **DSPy framing rewrite** — 5 signatures (Classify/Critique/MultiplyFrames/PickFrame/Decompose),
   `BootstrapFewShot`, Question-Library warm-start. *(≥90% qtype agreement; frame-override rate <30%)*
6. **LangGraph for Mode B** — `StateGraph`: framing → skeleton → fan-out research (`Send`) → barrier →
   denoise → progress conditional; `SqliteSaver` checkpoint; `WorkingReport` (IterResearch-style,
   regenerated per round); SSE streaming. *(a run can be interrupted mid-round and resumed with a note)*
7. **Wire Debate into the pipeline** — trigger on unresolved contradictions / load-bearing flags / user
   request; distinct system prompt per perspective; NLI-as-stance judge; crux fed back as a new
   sub-question. *(Debate auto-triggers on flagged contradictions)*
8. **Injection deBERTa + MiniCheck** — both additive on top of existing gates.
9. **Calibration auto-resolution** — add `resolve_by`, `resolution_criterion`, `resolved`, `outcome` to
   `Position`; periodic resolver task feeds the Brier loop real data.
10. **Monitor LLM salience + per-topic centroid novelty; Digest "what changed" pass** (DBSCAN cross-topic
    dedup).
11. **Evaluation harness** — RAGAS in CI on a 50-item golden set; DeepResearch Bench monthly
    (floor target: open_deep_research's 0.4344).

## Default-value changes (apply with step 1)

- Deep-Dive `max_rounds` 2 → 3 (TTD-DR uses up to 5).
- Discovery-progress termination: `<0.1` → `<0.05` **AND** open-questions count unchanged.
- Hybrid `top_k` 5 → retrieve 50 → rerank → 8 (when reranker active).
- ReSum compaction invoked at the end of every round (step 6).

## Per-mode technique map

- **Deep-Dive:** CRAG (graded retrieval evaluator → fallback), HyDE for empty sub-question retrieval,
  IRCoT for follow-up retrieval, RAPTOR for long-document corpora (>50 chunks).
- **Monitor:** per-topic centroid novelty (cosine <0.85 vs centroid = novel; 0.85–0.97 = echo, group).
- **QUC:** Adaptive-RAG routing {no/single/multi-hop}; ReSum at >4000 chars; HyDE for hard queries;
  conversational system prompt (not the `researcher` role).
- **Framing:** DSPy `BootstrapFewShot`.
- **Debate:** NLI-as-stance; load-bearing dispute = highest betweenness in citation graph × highest
  stance variance.

## Hallucination control (cross-cutting)

- Drafter "support gate" line: every factual claim must carry `[src: <chunk_id>]` or be marked
  `[UNVERIFIED]` and stripped post-draft. (Lands with step 4 so the discipline-gate citation parser is
  updated in lockstep — `[src: id]` is non-numeric and would otherwise read as uncited.)
- Two-stage faithfulness: HHEM-2.1 ≥0.7 trust; 0.4–0.7 escalate to MiniCheck; <0.4 unsupported.

## Provenance capture (extend the existing HMAC audit chain)

Per Position, record: model tag + quantization + sampler settings, seed, retriever RRF `k`, reranker
model tag. Emit outputs in `deep_research_bench` JSONL so reports can be benchmarked with zero
conversion.

## Decision thresholds (change course if…)

- precision@5 < 0.30 after reranker + contextual → embedding model is the bottleneck; switch bge-m3 →
  `Qwen3-Embedding-0.6B`.
- Qwen3-14B produces structurally bad reports → bump to Tongyi-DeepResearch-30B-A3B Q4.
- 5-section / 3-round run > 6 min on M4 → synthesizer is the bottleneck; quantize harder before cutting
  top_k.
- frame-override rate > 50% after DSPy → golden set is wrong; rebuild from the user's real past
  questions.

## Caveats (carry into implementation)

- Anthropic's failure-reduction numbers are from *their* corpora — treat 67% as an upper bound on our
  golden set.
- LangGraph 0.6+ API churned twice in 2025; pin versions. `deepagents` sits on top of it.
- Tongyi-30B Q4 (~17 GB) leaves narrow headroom alongside embedder + reranker + Qdrant on 24 GB —
  profile under load.
- HHEM-2.1 AggreFact F1 (66.77%) < HHEM-1.0 (90.47%); Vectara argues RAGTruth is more representative —
  pick the version per corpus.
- FActScore atomic-facts are gameable by trivial/repetitive claims — use the Core extension.
- DeepResearch Bench RACE uses an LLM judge → 5–10 pt judge bias; same for a local Qwen3-30B judge.
- Verify MoritzLaurer/DeBERTa licensing per distribution; `-c` zero-shot variants are commercially clean.

## This-sprint scope (turn 1)

Step 1 + the default-value changes, landed download-free: reranker wiring with graceful fallback,
`rerank_candidates` cap in HybridSearch, Deep-Dive top_k/rerank-candidates plumbing, `max_rounds`
default 3, and the tightened termination condition. Remaining steps tracked above.
