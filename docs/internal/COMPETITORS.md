# Lighthouse vs. the incumbents (DRAFT)

> **Status: draft.** This is a stub for honest positioning, not marketing copy.
> Claims here should be checked against current incumbent feature sets before any
> external use. No benchmarks asserted.

The incumbents — **Lexis+ AI**, **Thomson Reuters CoCounsel**, **Harvey** — are
cloud-hosted, professionally validated, well-supported research assistants. They are
genuinely good products. Lighthouse competes on exactly **one** axis, and is honest
about where it does not.

## The one honest differentiator

**Local-first / air-gappable / your corpus never leaves your machine.** Inference
runs on your own Ollama model; your documents stay on your disk; outbound requests
go through an allowlist + audit log (`egress.jsonl`), and `LIGHTHOUSE_AIRGAP=1` is a
hard kill switch. For anyone who cannot or will not send their corpus to a vendor
cloud, that is the whole pitch. The incumbents are cloud services.

## Where Lighthouse wins

- **Data never leaves.** No vendor cloud, no upload of your corpus, no third-party
  retention. Inference and storage are local by default.
- **Auditable egress.** You can see exactly what went out and when, and disable all
  egress with one environment variable.
- **No per-seat cloud cost or account.** Runs on your hardware; no subscription gate
  to read your own files.
- **Open and inspectable.** The controls (allowlist, sandbox, citation gate) are in
  the source tree, not a black box.

## Where the incumbents win (honestly)

- **Polish & UX.** Lexis+ AI / CoCounsel / Harvey ship mature, supported interfaces;
  Lighthouse is a research instrument under active validation.
- **Validation & content licensing.** They have professionally validated pipelines
  and licensed authoritative corpora (case law, filings); Lighthouse's live-data
  validation is still pending.
- **Support & accountability.** Enterprise SLAs, training, and a vendor to call.
  Lighthouse has none of that.
- **Breadth.** Deep, domain-specific coverage (legal especially) that a local-first
  generalist tool does not match today.

---

*Bottom line for the draft: choose Lighthouse when "my corpus never leaves my
machine" is non-negotiable. Choose an incumbent when polish, validated content, and
support matter more than locality.*
