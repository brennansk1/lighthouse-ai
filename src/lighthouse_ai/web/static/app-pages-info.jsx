// app-pages-info.jsx — the Info page: a friendly primer on the seven research
// modes. Lives near Health at the end of the sidebar. Loaded via babel-standalone
// into the shared global scope; registers window.InfoPage. Uses window.*
// primitives (PageHeader, card, NavIcon) from sibling files.

(function () {
const MODES = [
  {
    icon: 'watch',
    name: 'Watch',
    artifact: 'Digest',
    tagline: 'Monitor entities and sources over time.',
    body: 'Track named entities, topics, or sources across a schedule. Lighthouse polls, surfaces what is new and salient, and rolls cycles into a digest you can skim.',
    when: 'Use when something is unfolding and you want to stay current without watching it yourself.',
  },
  {
    icon: 'activity',
    name: 'Ask',
    artifact: 'Transcript',
    tagline: 'A cited, conversational Q&A over your corpus.',
    body: 'Ask focused questions and get sourced answers in a back-and-forth transcript. Each turn attaches the chunks it drew from, and any answer can be promoted into a saved artifact.',
    when: 'Use for a quick, grounded answer where you want to follow up in conversation.',
  },
  {
    icon: 'research',
    name: 'Investigate',
    artifact: 'Report',
    tagline: 'A bounded, sourced report on one question.',
    body: 'Lighthouse gathers evidence, drafts a structured report in sections, and grades each claim by how well it is sourced. The result is staged for your review before it is kept.',
    when: 'Use when you need depth and citations, not just a quick answer.',
  },
  {
    icon: 'library',
    name: 'Survey',
    artifact: 'Evidence table',
    tagline: 'Screen many documents into a sortable grid.',
    body: 'Define screening criteria and the attributes you care about; Lighthouse screens each document, extracts a cell per attribute with citations and a faithfulness check, and reports a PRISMA-style inclusion flow.',
    when: 'Use when you have a corpus to triage and want a comparable table, not prose.',
  },
  {
    icon: 'track',
    name: 'Reconstruct',
    artifact: 'Timeline',
    tagline: 'Assemble a sourced chronology of events.',
    body: 'Lighthouse extracts dated events from the corpus, deduplicates them, resolves conflicting dates by weighted vote, and orders them into a timeline with per-event certainty and sources.',
    when: 'Use when you need to know what happened, in what order, with sources.',
  },
  {
    icon: 'settings',
    name: 'Decide',
    artifact: 'Decision matrix',
    tagline: 'Score options against weighted criteria.',
    body: 'Provide your options and weighted criteria; Lighthouse scores each cell, computes weighted totals, runs a sensitivity sweep, and names the crux that decides the call — ready to hand to Adjudicate.',
    when: 'Use when you are choosing between options and want the trade-offs made explicit.',
  },
  {
    icon: 'system',
    name: 'Adjudicate',
    artifact: 'Verdict',
    tagline: 'Run a structured debate and name the crux.',
    body: 'Lighthouse argues several perspectives on a contested question, weighs them, and delivers a verdict that names the crux of disagreement rather than a single flattened take.',
    when: 'Use when a question is genuinely contested and you want the tensions surfaced.',
  },
];

function InfoPage() {
  const NavIcon = window.NavIcon;
  return (
    <div>
      <window.PageHeader
        title="Welcome to Lighthouse"
        subtitle="A local-first research instrument. Everything runs on your own hardware — your sources, your models, your data."
      />

      <div style={{ ...window.card, padding: '18px 22px', marginBottom: 22,
        fontFamily: 'var(--serif)', fontSize: 15.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
        Lighthouse works in seven <strong>research modes</strong>, each producing one
        kind of artifact. Pick the one that matches what you need — a live watch, a
        cited answer, a deep report, an evidence table, a timeline, a decision matrix,
        or an adjudicated verdict. Below is what each is for. When you are ready, head
        to <a href="#research" style={{ color: 'var(--primary)', fontWeight: 600 }}>Research</a> to
        launch a run.
      </div>

      <div style={{ display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
        {MODES.map((m) => (
          <div key={m.name} style={{ ...window.card, padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10,
              color: 'var(--primary)' }}>
              <span style={{ display: 'inline-flex' }}>
                {NavIcon ? <NavIcon name={m.icon} size={20} /> : null}
              </span>
              <span style={{ fontFamily: 'var(--serif)', fontSize: 18, fontWeight: 700,
                color: 'var(--ink)' }}>{m.name}</span>
              <span style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700,
                letterSpacing: 0.4, textTransform: 'uppercase', color: 'var(--muted)' }}>
                {m.artifact}
              </span>
            </div>
            <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--ink-2)',
              marginBottom: 10 }}>{m.tagline}</div>
            <div style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--ink-2)',
              marginBottom: 12 }}>{m.body}</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.5, color: 'var(--muted)',
              borderTop: '1px solid var(--rule)', paddingTop: 10 }}>
              <strong style={{ color: 'var(--ink-2)' }}>When:</strong> {m.when}
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 24, textAlign: 'center' }}>
        <a href="#research" className="btn-primary" style={{ textDecoration: 'none',
          display: 'inline-block' }}>
          Go to Research →
        </a>
      </div>
    </div>
  );
}

window.InfoPage = InfoPage;
})();
