// app-pages-info.jsx — the Info tab: a comprehensive in-app guide to Lighthouse.
// Loaded via babel-standalone into the shared global scope; registers window.InfoPage.
// Uses window.* primitives from app-lib.jsx (PageHeader, card, Btn, NavIcon, etc.).
//
// Layout: sticky left section-nav + scrolling content pane.
// Sections: Welcome · Getting started · Research modes · Sources · Sandbox ·
//           Watch a website · Settings & control · How we keep it trustworthy

(function () {

// ── Section registry ──────────────────────────────────────────────────────────
const SECTIONS = [
  { id: 'welcome',       label: 'What is Lighthouse' },
  { id: 'getting-started', label: 'Getting started' },
  { id: 'modes',         label: 'Research modes' },
  { id: 'sources',       label: 'Sources' },
  { id: 'sandbox',       label: 'The Sandbox' },
  { id: 'watch',         label: 'Watch a website' },
  { id: 'settings',      label: 'Settings & control' },
  { id: 'trustworthy',   label: 'How we keep it trustworthy' },
];

// ── Design tokens (inline; mirrors app.jsx CSS vars) ─────────────────────────
const prose = {
  fontFamily: 'var(--serif)',
  fontSize: 15,
  lineHeight: 1.7,
  color: 'var(--ink-2)',
};
const h2style = {
  fontFamily: 'var(--serif)',
  fontSize: 22,
  fontWeight: 700,
  color: 'var(--ink)',
  marginTop: 0,
  marginBottom: 10,
  lineHeight: 1.2,
};
const h3style = {
  fontFamily: 'var(--serif)',
  fontSize: 16,
  fontWeight: 700,
  color: 'var(--ink)',
  marginTop: 24,
  marginBottom: 6,
  lineHeight: 1.3,
};
const sectionBox = {
  paddingBottom: 40,
  borderBottom: '1px solid var(--rule)',
  marginBottom: 40,
};
const pill = (bg, fg) => ({
  display: 'inline-block',
  padding: '2px 9px',
  borderRadius: 10,
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: '0.03em',
  background: bg,
  color: fg,
  whiteSpace: 'nowrap',
});
const callout = {
  background: 'rgba(2,136,209,0.06)',
  border: '1px solid rgba(2,136,209,0.18)',
  borderRadius: 'var(--radius)',
  padding: '12px 16px',
  fontSize: 13.5,
  lineHeight: 1.6,
  color: 'var(--ink-2)',
  marginTop: 14,
  marginBottom: 14,
};

// ── Mode data (matches the 7 real modes in modes/) ───────────────────────────
const MODES = [
  {
    name: 'Watch',
    key: 'watch',
    artifact: 'Digest',
    tagline: 'Stay current without watching it yourself.',
    body: 'Define a topic and a set of sources. Lighthouse polls them on a schedule, surfaces high-salience items as alerts, and batches the rest into a digest you can skim.',
    when: 'Something is unfolding and you need to know when it moves.',
  },
  {
    name: 'Ask',
    key: 'ask',
    artifact: 'Transcript',
    tagline: 'Get a cited answer and follow up in conversation.',
    body: 'Ask a focused question and get a sourced answer drawn from your corpus. Each response shows the chunks it used; you can follow up in the same session.',
    when: 'You want a quick, grounded answer and may want to dig deeper in conversation.',
  },
  {
    name: 'Investigate',
    key: 'investigate',
    artifact: 'Report',
    tagline: 'A structured, cited report on one question.',
    body: 'Lighthouse decomposes your question, researches each part, merges the evidence, and stages a report with per-section citations and confidence ratings. Every claim is checked against a real source before it appears.',
    when: 'You need depth and citations, not just a quick answer.',
  },
  {
    name: 'Survey',
    key: 'survey',
    artifact: 'Evidence table',
    tagline: 'Screen many documents into a sortable grid.',
    body: 'Define what to include and what columns you care about. Lighthouse screens each document, extracts a cell per column with citations and a faithfulness check, and reports a PRISMA-style inclusion flow (identified → screened → included).',
    when: 'You have a corpus to triage and want a comparable table, not prose.',
  },
  {
    name: 'Reconstruct',
    key: 'reconstruct',
    artifact: 'Timeline',
    tagline: 'Assemble a sourced chronology of events.',
    body: 'Lighthouse extracts dated events from the corpus, deduplicates them, resolves conflicting dates by weighted vote across sources, and orders them into a timeline with per-event certainty.',
    when: 'You need to know what happened, in what order, with sources.',
  },
  {
    name: 'Decide',
    key: 'decide',
    artifact: 'Decision matrix',
    tagline: 'Score options against weighted criteria.',
    body: 'Provide your options and weighted criteria. Lighthouse scores each cell, computes weighted totals, runs a sensitivity sweep, and names the crux — the criterion that, if wrong, flips the result.',
    when: 'You are choosing between options and want the trade-offs made explicit.',
  },
  {
    name: 'Adjudicate',
    key: 'adjudicate',
    artifact: 'Verdict',
    tagline: 'Run a structured debate and name the crux.',
    body: 'Lighthouse argues four perspectives on a contested question (steelman, devil\'s advocate, base rate, fragility), weighs them, and delivers a verdict that names the crux of disagreement rather than flattening it into one take.',
    when: 'A question is genuinely contested and you want the tensions surfaced rather than smoothed.',
  },
];

// ── Source families ───────────────────────────────────────────────────────────
const SOURCE_FAMILIES = [
  {
    family: 'Academic literature',
    sources: ['arXiv', 'OpenAlex', 'PubMed', 'Crossref', 'Semantic Scholar'],
  },
  {
    family: 'Clinical / biomedical',
    sources: ['ClinicalTrials.gov'],
  },
  {
    family: 'Legal',
    sources: ['CourtListener / RECAP'],
  },
  {
    family: 'U.S. federal government',
    sources: ['Federal Register', 'regulations.gov', 'GovInfo', 'Congress.gov'],
  },
  {
    family: 'Corporate & financial',
    sources: ['SEC EDGAR'],
  },
  {
    family: 'Economic data',
    sources: ['FRED (St. Louis Fed)', 'BEA', 'BLS', 'World Bank Open Data', 'OECD Data'],
  },
  {
    family: 'Engineering & software',
    sources: ['GitHub', 'PyPI / npm / crates.io'],
  },
  {
    family: 'Reference',
    sources: ['Wikipedia', 'Wikidata'],
  },
  {
    family: 'Media',
    sources: ['YouTube', 'Internet Archive (audio / video)'],
  },
  {
    family: 'News',
    sources: ['Reuters', 'Associated Press', 'BBC News', 'NPR', 'The Guardian', 'ProPublica', 'News Orchestrator (cross-outlet)'],
  },
  {
    family: 'Web & archive',
    sources: ['General Web', 'RSS / Atom feeds', 'Wayback Machine'],
  },
  {
    family: 'Public health & demographics',
    sources: ['WHO', 'U.S. Census Bureau'],
  },
];

// ── Depth tiers ───────────────────────────────────────────────────────────────
const DEPTH_TIERS = [
  {
    name: 'Quick',
    feel: '~1–3 min',
    desc: 'A fast, grounded scan. Fewer retrieval rounds, smaller source set. Produces less with humbler confidence — but never lies to go faster.',
  },
  {
    name: 'Standard',
    feel: '~5–10 min',
    desc: 'Balanced coverage with gap-filling and deduplication. Roughly equivalent in depth to what frontier services (Claude, Gemini) can reach in their time-boxed runs.',
  },
  {
    name: 'Thorough',
    feel: '~20–60 min',
    desc: 'Adds adversarial refutation (a skeptic tries to knock down each key claim), a coverage critic (fills missing angles), and triangulation (key claims need at least two independent sources). Depth frontier services can\'t structurally reach.',
  },
  {
    name: 'Deep',
    feel: 'Hours (you set the budget)',
    desc: 'A recursive question-tree run to exhaustion — sub-questions decompose into sub-sub-questions until each leaf is grounded or recorded as a known unknown. Requires a committed budget (30 min / 1 h / 2 h / overnight) before it starts.',
  },
];

// ── Shared sub-components ─────────────────────────────────────────────────────

function SectionAnchor({ id }) {
  // Placed at the top of each section; the IntersectionObserver watches this element
  // to highlight the matching nav entry. scroll-margin-top gives breathing room
  // under the sticky sidebar nav when scrollTo() lands on it.
  return (
    <div id={id} aria-hidden="true" style={{ scrollMarginTop: 80 }} />
  );
}

function ModeCard({ mode }) {
  return (
    <div style={{ ...window.card, padding: '18px 20px', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap',
        marginBottom: 6 }}>
        <span style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
          color: 'var(--ink)' }}>{mode.name}</span>
        <span style={{ ...pill('var(--rule-soft)', 'var(--muted)') }}>{mode.artifact}</span>
      </div>
      <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--primary)',
        marginBottom: 8 }}>{mode.tagline}</div>
      <div style={{ ...prose, fontSize: 13.5, marginBottom: 10 }}>{mode.body}</div>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', borderTop: '1px solid var(--rule)',
        paddingTop: 8, lineHeight: 1.5 }}>
        <strong style={{ color: 'var(--ink-2)' }}>Use when:</strong> {mode.when}
      </div>
    </div>
  );
}

function DepthCard({ tier }) {
  const badgeColor = {
    Quick: ['rgba(0,100,200,0.1)', '#005b9a'],
    Standard: ['rgba(0,140,100,0.1)', '#006940'],
    Thorough: ['rgba(180,100,0,0.1)', '#8a4f00'],
    Deep: ['rgba(140,30,120,0.1)', '#6d1060'],
  }[tier.name] || ['var(--rule-soft)', 'var(--muted)'];
  return (
    <div style={{ ...window.card, padding: '14px 18px', marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <span style={{ ...pill(badgeColor[0], badgeColor[1]) }}>{tier.name}</span>
        <span style={{ fontSize: 12, color: 'var(--muted)', fontFamily: 'var(--sans)' }}>
          {tier.feel}
        </span>
      </div>
      <div style={{ ...prose, fontSize: 13.5 }}>{tier.desc}</div>
    </div>
  );
}

// ── Section content components ────────────────────────────────────────────────

function SectionWelcome() {
  return (
    <div style={sectionBox}>
      <SectionAnchor id="welcome" />
      <h2 style={h2style}>What is Lighthouse</h2>
      <p style={prose}>
        Lighthouse is a local-first research instrument. It runs entirely on your own hardware — your
        sources, your models, your data — and produces research you can verify, reproduce, and audit.
        No query leaves your machine unless you explicitly choose a source that reaches the open web.
      </p>
      <p style={{ ...prose, marginTop: 12 }}>
        The core bet is that the highest-leverage quality feature in research tooling is not the
        model's fluency — it's whether the output can be trusted. Lighthouse is optimized for
        verifiable and correct rather than impressive on first read. Every claim in an artifact cites
        a real source chunk. Every run produces a tamper-evident audit trail. Confidence levels are
        stated honestly and downgraded when the evidence doesn't support a strong claim.
      </p>

      <h3 style={h3style}>The trust wedge</h3>
      <p style={prose}>
        Three properties hold at every depth tier, for every research mode:
      </p>
      <ul style={{ ...prose, paddingLeft: 22, marginTop: 8 }}>
        <li style={{ marginBottom: 6 }}>
          <strong>Cited and grounded.</strong> A claim that cannot be traced to a real source chunk
          is dropped or flagged — never asserted. Zero fabricated citations is a hard invariant, not
          a goal.
        </li>
        <li style={{ marginBottom: 6 }}>
          <strong>Calibrated.</strong> Confidence is expressed as a band (remote / unlikely / even
          chance / likely / almost certain) and is downgraded automatically when coverage is thin.
          Lighthouse never overstates certainty.
        </li>
        <li style={{ marginBottom: 6 }}>
          <strong>Auditable.</strong> Every run records which model ran, which sources were used,
          which backend actually executed (local vs. mock), and a SHA-256 content hash — so any
          reader (you, a colleague, a reviewer) can see exactly what produced the result.
        </li>
      </ul>

      <div style={callout}>
        <strong>Better than frontier on trust, not model size.</strong> Services like Gemini Deep
        Research and Claude Research time-box to roughly 10–20 minutes of work — about what
        Lighthouse calls Standard depth. Lighthouse's Thorough and Deep tiers — adversarial
        refutation, triangulation, recursive question trees — are depth those services structurally
        cannot reach. And because everything runs locally, your documents never leave your machine.
      </div>

      <h3 style={h3style}>Who it's for</h3>
      <p style={prose}>
        Lighthouse was built for two kinds of people. The first is the regulated-industry professional
        — a lawyer, clinician, compliance officer, or financial analyst — who cannot send their actual
        working documents to a cloud service and needs audit-ready provenance. The second is the
        serious generalist researcher who wants depth and honesty, not just a fast answer that sounds
        plausible. Both benefit from the same core property: research you can stand behind.
      </p>
    </div>
  );
}

function SectionGettingStarted() {
  const steps = [
    {
      num: '1',
      title: 'Pick what to do',
      desc: 'Open the Research tab. Choose a research mode from the seven available (Watch, Ask, Investigate, Survey, Reconstruct, Decide, Adjudicate). Not sure which one? See the Research modes section below.',
    },
    {
      num: '2',
      title: 'Frame the question',
      desc: 'Type your question or topic in the text field. Lighthouse runs a framing pipeline that classifies the question type and decomposes it into sub-questions — so your actual question is the starting point, not a form to fill in.',
    },
    {
      num: '3',
      title: 'Choose sources',
      desc: 'A source picker shows the 36 available sources, with the ones most relevant to your question already checked. You can add or remove sources. Some sources (FRED, BLS, GitHub, etc.) need a free API key — configure those in Settings first.',
    },
    {
      num: '4',
      title: 'Review and start',
      desc: 'Pick a depth tier (Quick / Standard / Thorough / Deep), confirm, and Lighthouse runs. Results appear in the Library tab when the run is staged for your review.',
    },
  ];
  return (
    <div style={sectionBox}>
      <SectionAnchor id="getting-started" />
      <h2 style={h2style}>Getting started</h2>
      <p style={prose}>
        Everything starts from the <strong>Research tab</strong>. The flow has four steps:
      </p>
      <div style={{ marginTop: 18 }}>
        {steps.map((s) => (
          <div key={s.num} style={{ display: 'flex', gap: 16, marginBottom: 18,
            alignItems: 'flex-start' }}>
            <div style={{ flexShrink: 0, width: 32, height: 32, borderRadius: '50%',
              background: 'var(--primary)', color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700 }}>
              {s.num}
            </div>
            <div>
              <div style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700,
                color: 'var(--ink)', marginBottom: 4 }}>{s.title}</div>
              <div style={{ ...prose, fontSize: 13.5 }}>{s.desc}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={callout}>
        <strong>Where results appear.</strong> When a run finishes, the artifact is staged for
        your review in the <strong>Library tab</strong>. You can read it there, approve it to keep
        it, or reject it. Lighthouse never publishes anything automatically.
      </div>
      <p style={{ ...prose, marginTop: 14 }}>
        <strong>API keys.</strong> Several sources require a free key to raise your rate limit or
        unlock extra data — FRED, BLS, BEA, GitHub, and others. All sources still work without a
        key; adding one just improves the experience. Configure keys in <strong>Settings →
        Connect your data sources</strong>. Keys are stored securely on your machine and never
        transmitted to Lighthouse servers.
      </p>
    </div>
  );
}

function SectionModes() {
  return (
    <div style={sectionBox}>
      <SectionAnchor id="modes" />
      <h2 style={h2style}>Research modes</h2>
      <p style={prose}>
        Lighthouse works in seven research modes. Each one produces a different kind of artifact and
        is designed for a different kind of research task. Pick the one that matches what you need.
      </p>

      <div style={{ marginTop: 18 }}>
        {MODES.map((m) => <ModeCard key={m.key} mode={m} />)}
      </div>

      <h3 style={h3style}>Depth tiers: Quick → Deep</h3>
      <p style={prose}>
        Every mode (except Watch, which works differently) takes a depth tier. Depth scales how much
        Lighthouse covers and how hard each claim is stress-tested — not whether the output can be
        trusted. Even a Quick run never fabricates a citation.
      </p>
      <div style={{ marginTop: 14 }}>
        {DEPTH_TIERS.map((t) => <DepthCard key={t.name} tier={t} />)}
      </div>
      <div style={callout}>
        <strong>Auto depth.</strong> The Research tab defaults to <em>Auto</em>, which picks a
        sensible tier based on your question type. Factual lookups go to Quick; comparative or
        decision questions go to Standard; contested or methodological questions go to Thorough.
        You can always override it.
      </div>
      <p style={{ ...prose, marginTop: 14, fontSize: 13 }}>
        <strong>Note on Adjudicate:</strong> A Quick Adjudicate is disabled — a two-perspective
        debate produces the appearance of balance without the rigor. Selecting Adjudicate
        automatically raises the minimum tier to Standard.
      </p>
      <p style={{ ...prose, marginTop: 10, fontSize: 13 }}>
        <strong>Note on Deep:</strong> The Deep tier requires you to commit a budget (30 min,
        1 h, 2 h, or overnight) before it starts. The Governor refuses to launch without one — so
        there is no risk of a run consuming your machine indefinitely.
      </p>
    </div>
  );
}

function SectionSources() {
  return (
    <div style={sectionBox}>
      <SectionAnchor id="sources" />
      <h2 style={h2style}>Sources</h2>
      <p style={prose}>
        Lighthouse ships with 36 sources, one per destination. Each source is a self-contained
        module that knows how to query that destination well — the right API parameters, the right
        politeness rules, the right way to extract a citable document. All sources run through the
        same security broker: every byte fetched is scanned before it enters your corpus.
      </p>

      <h3 style={h3style}>How the source picker works</h3>
      <p style={prose}>
        When you frame a question, a recommender ranks the 36 sources by how well they fit your
        question, mode, and depth. The Research tab shows the top matches pre-checked, each with a
        short reason. You can add or remove sources freely — the recommender is a starting point,
        not a constraint.
      </p>
      <p style={{ ...prose, marginTop: 10 }}>
        Sources recommended for a question are those whose category and content type best match
        what you're asking about. A clinical question surfaces PubMed, ClinicalTrials.gov, and
        WHO; a financial question surfaces SEC EDGAR, FRED, and BLS; an engineering question
        surfaces GitHub and arXiv.
      </p>

      <h3 style={h3style}>The 36 sources by family</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        gap: 12, marginTop: 12 }}>
        {SOURCE_FAMILIES.map((f) => (
          <div key={f.family} style={{ ...window.card, padding: '14px 16px' }}>
            <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--muted)',
              textTransform: 'uppercase', letterSpacing: '0.06em',
              marginBottom: 8 }}>{f.family}</div>
            <ul style={{ margin: 0, paddingLeft: 16, listStyle: 'disc' }}>
              {f.sources.map((s) => (
                <li key={s} style={{ fontSize: 13, color: 'var(--ink-2)',
                  lineHeight: 1.6, marginBottom: 2 }}>{s}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <h3 style={h3style}>Sources that need a free key</h3>
      <p style={prose}>
        Many sources work without authentication at lower rate limits. Adding a free API key raises
        your limit or unlocks additional data. Sources that benefit most from a key: FRED, BEA,
        BLS, U.S. Census Bureau, GitHub, Semantic Scholar, and The Guardian. Configure keys in
        Settings → Connect your data sources; they are stored on your device and never sent off it.
      </p>

      <h3 style={h3style}>Adding a custom source</h3>
      <p style={prose}>
        You can teach Lighthouse to research any new source by creating a source module with the
        command-line tool:
      </p>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 13, background: 'var(--rule-soft)',
        border: '1px solid var(--rule)', borderRadius: 'var(--radius)', padding: '10px 14px',
        marginTop: 8, marginBottom: 8, color: 'var(--ink)' }}>
        lighthouse skill new my_source --name "My Source" --category academic
      </div>
      <p style={{ ...prose, fontSize: 13.5 }}>
        This creates a source folder with a manifest and a stub entrypoint. Fill in the guide and
        the query logic; Lighthouse picks it up automatically the next time it scans for sources.
        Use <code style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>lighthouse skill list</code> to
        see all installed sources, and <code style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>lighthouse skill validate my_source</code> to
        confirm it loads cleanly.
      </p>
      <div style={callout}>
        <strong>Source independence and trust.</strong> Officially curated sources are signed.
        Community or custom sources load with a lower confidence band applied automatically — a
        claim that depends only on an unsigned source is never labeled "almost certain."
        Lighthouse makes the provenance visible so you know what you're relying on.
      </div>
    </div>
  );
}

function SectionSandbox() {
  return (
    <div style={sectionBox}>
      <SectionAnchor id="sandbox" />
      <h2 style={h2style}>The Sandbox</h2>
      <p style={prose}>
        The Sandbox tab is your secured data workspace. It has two zones:
      </p>
      <div style={{ marginTop: 12 }}>
        <div style={{ ...window.card, padding: '14px 18px', marginBottom: 10 }}>
          <div style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700,
            color: 'var(--ink)', marginBottom: 6 }}>Your uploads</div>
          <div style={{ ...prose, fontSize: 13.5 }}>
            Files you bring in for analysis — PDFs, spreadsheets, documents. The assistant can read
            these files but cannot modify them. Everything in this zone is read-only to the research
            pipeline.
          </div>
        </div>
        <div style={{ ...window.card, padding: '14px 18px', marginBottom: 10 }}>
          <div style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700,
            color: 'var(--ink)', marginBottom: 6 }}>Assistant workspace</div>
          <div style={{ ...prose, fontSize: 13.5 }}>
            Analysis results and intermediate artifacts generated by Lighthouse. These are produced
            by the research pipeline, not by you directly.
          </div>
        </div>
      </div>

      <h3 style={h3style}>Security scanning</h3>
      <p style={prose}>
        Every file is scanned on the way in before it enters either zone. The scanners check for
        known malware signatures (EICAR pattern), PDF JavaScript injection, HTML script injection,
        and zip bomb patterns. Files that fail scanning are quarantined and reported — they never
        reach the research pipeline.
      </p>

      <h3 style={h3style}>Size limits and pinning</h3>
      <p style={prose}>
        A configurable size limit keeps the Sandbox bounded. When it fills, the oldest unpinned
        items are removed first. You can pin files you want to keep indefinitely — pinned items are
        never evicted automatically. Configure the size limit in the Sandbox tab itself.
      </p>
      <div style={callout}>
        The Sandbox is where you bring sensitive documents that must never leave your machine.
        Because Lighthouse runs locally, those files stay on your hardware throughout the research
        process — the pipeline reads them; they are never uploaded to a cloud service.
      </div>
    </div>
  );
}

function SectionWatch() {
  return (
    <div style={sectionBox}>
      <SectionAnchor id="watch" />
      <h2 style={h2style}>Watch a website</h2>
      <p style={prose}>
        The Watch tab lets you monitor any topic or website over time. Instead of running a
        one-off research job, you set up a topic — a subject, entity, or question you want to
        follow — and Lighthouse collects material from your chosen sources on a schedule.
      </p>

      <h3 style={h3style}>Setting up a watch</h3>
      <ol style={{ ...prose, paddingLeft: 22, fontSize: 13.5, marginTop: 8 }}>
        <li style={{ marginBottom: 8 }}>
          <strong>Add a topic.</strong> Click "+ Add topic" in the Watch tab. Give it a name
          and a query string — the terms Lighthouse uses when searching your sources.
        </li>
        <li style={{ marginBottom: 8 }}>
          <strong>Choose sources.</strong> Only sources that expose a live feed (marked
          "watchable") appear in the source list for Watch topics. RSS feeds, news outlets,
          arXiv, GitHub, and others support it. General web search supports it too.
        </li>
        <li style={{ marginBottom: 8 }}>
          <strong>Run a session.</strong> Schedule a time-bounded session against your sources.
          Lighthouse polls each source, deduplicates items it has seen before (by URL and by
          near-duplicate title detection), and scores each new item's salience.
        </li>
        <li style={{ marginBottom: 8 }}>
          <strong>Review the digest.</strong> High-salience items appear as alerts; the rest are
          batched into a digest. Both land in the Library tab as a Watch artifact you can review.
        </li>
      </ol>

      <h3 style={h3style}>What counts as a change</h3>
      <p style={prose}>
        Lighthouse uses two layers of deduplication. First, exact URL matching: if Lighthouse has
        seen the URL before, it is suppressed. Second, semantic near-duplicate detection: titles
        that are very similar to something already seen are also suppressed, even if the URL is
        different — this catches the same story republished under a new link.
      </p>
      <p style={{ ...prose, marginTop: 10 }}>
        Items that are genuinely new are scored for salience. Items scoring above the alert
        threshold are surfaced immediately; lower-scoring items go into the digest. You can see
        exactly how many items were suppressed as duplicates in each session's summary.
      </p>

      <div style={callout}>
        <strong>Getting alerts.</strong> Configure a notification channel in Settings →
        Notifications to receive alerts when a Watch session finds something significant or when
        a session ends. Without a notification channel, results land in the Library tab as usual.
      </div>
    </div>
  );
}

function SectionSettings() {
  return (
    <div style={sectionBox}>
      <SectionAnchor id="settings" />
      <h2 style={h2style}>Settings and control</h2>
      <p style={prose}>
        The Settings tab has three main areas relevant to day-to-day use: connecting data sources,
        controlling reproducibility, and the global Pause.
      </p>

      <h3 style={h3style}>Connecting data sources</h3>
      <p style={prose}>
        Many of Lighthouse's 36 sources work without authentication, but adding a free API key
        raises your rate limit or unlocks additional data. In Settings → Connect your data sources,
        you will see a list of sources that accept keys, their current status (configured or not),
        and a link to get a free key for each.
      </p>
      <p style={{ ...prose, marginTop: 10 }}>
        Paste a key into the field and click Save. The key is stored securely in your operating
        system's keychain — it is never shown again and never transmitted to Lighthouse servers.
        You can remove a key at any time.
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10, marginBottom: 4 }}>
        {['FRED', 'BEA', 'BLS', 'GitHub', 'Semantic Scholar', 'The Guardian', 'U.S. Census'].map(
          (s) => (
            <span key={s} style={{ ...pill('var(--sky-soft,rgba(0,120,200,0.1))',
              'var(--primary)') }}>
              {s}
            </span>
          )
        )}
      </div>
      <p style={{ ...prose, fontSize: 12.5, color: 'var(--muted)', marginTop: 6 }}>
        Sources that most benefit from a free API key.
      </p>

      <h3 style={h3style}>Reproducibility: lock the model</h3>
      <p style={prose}>
        Settings → Reproducibility lets you control how much randomness the model uses. The main
        toggle is <em>Lock the model for identical results</em> — it sets the temperature to 0 and
        pins the random seed so that the same question, run again on the same corpus, produces the
        same artifact. This is useful for:
      </p>
      <ul style={{ ...prose, paddingLeft: 22, fontSize: 13.5, marginTop: 8 }}>
        <li style={{ marginBottom: 6 }}>Comparing runs where you want only the sources to change, not the model's variability.</li>
        <li style={{ marginBottom: 6 }}>Sharing a result with a colleague who needs to reproduce it exactly.</li>
        <li style={{ marginBottom: 6 }}>Audit scenarios where identical inputs must produce identical outputs.</li>
      </ul>
      <p style={{ ...prose, marginTop: 10 }}>
        When not locked, you can also set advanced knobs — a manual random seed, temperature,
        and top-p — for fine-grained control.
      </p>

      <h3 style={h3style}>The global Pause button</h3>
      <p style={prose}>
        At the top of the sidebar, the <strong>Pause all</strong> button stops all background work
        immediately: scheduled Watch sessions, calibration runs, pending jobs. It frees up your
        machine when you need full CPU and RAM for something else. Click <strong>Resume work</strong> to
        start again — in-progress jobs pick up where they left off.
      </p>
      <div style={callout}>
        Pause is a soft stop, not a shutdown. No data is lost and no jobs are cancelled —
        they just wait. You can walk away, close the lid, and come back; the work will be there
        when you resume.
      </div>
    </div>
  );
}

function SectionTrustworthiness() {
  const points = [
    {
      title: 'Verifiable grounding — zero fabricated citations',
      body: 'Every claim in an artifact must be entailed by a real, cited source chunk that exists in the corpus. A cited chunk ID that cannot be found in the evidence fails the gate — the claim is dropped or flagged, not asserted. This is a hard invariant across every mode and every depth tier.',
    },
    {
      title: 'Adversarial refutation',
      body: 'At Thorough and Deep, an independent skeptic attempts to refute each key claim against the same evidence. Claims that are refuted or contested are flagged in the artifact, not smoothed over. A claim that survives the skeptic is labeled stronger than one that was never challenged.',
    },
    {
      title: 'Triangulation across independent sources',
      body: 'At Thorough and Deep, key claims are required to be backed by at least two independent sources — meaning different domains or documents, not just different citation numbers from the same paper. A claim supported only by one source is labeled accordingly.',
    },
    {
      title: 'Contradictions surfaced, not smoothed',
      body: 'When sources disagree about a claim, Lighthouse surfaces the disagreement rather than picking one and ignoring the other. Contradictions are first-class artifacts: they appear in reports, escalate to Adjudicate when load-bearing, and are never silently resolved.',
    },
    {
      title: 'Calibration',
      body: 'Every claim carries a confidence band (remote / unlikely / even chance / likely / almost certain). These are honest: a poorly-sourced answer is never labeled "almost certain," and the band is downgraded automatically when citation coverage is thin. Over time, the Track tab records how the stated probabilities matched real outcomes (Brier score), so you can see whether Lighthouse is well-calibrated.',
    },
    {
      title: 'The audit trail',
      body: 'Every artifact\'s Library footer shows its provenance compactly: mode, depth tier, time taken, and which model ran. The full audit log — every state transition, every source fetch, every model call — is HMAC-chained so tampering breaks the chain. You can replay a job ID and verify that the same inputs produce the same result.',
    },
  ];
  return (
    <div style={{ paddingBottom: 40 }}>
      <SectionAnchor id="trustworthy" />
      <h2 style={h2style}>How we keep it trustworthy</h2>
      <p style={prose}>
        Trustworthiness is not a feature Lighthouse adds at the end — it is the architecture. Six
        mechanisms work together to make every artifact verifiable, honest about uncertainty, and
        resistant to the failure modes that plague LLM-generated research.
      </p>
      <div style={{ marginTop: 18 }}>
        {points.map((p, i) => (
          <div key={i} style={{ ...window.card, padding: '16px 20px', marginBottom: 12 }}>
            <div style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700,
              color: 'var(--ink)', marginBottom: 8 }}>{p.title}</div>
            <div style={{ ...prose, fontSize: 13.5 }}>{p.body}</div>
          </div>
        ))}
      </div>
      <div style={{ ...callout, marginTop: 24 }}>
        <strong>The invariant that never changes with depth:</strong> depth scales coverage and
        confidence, never trust. Every tier — Quick through Deep — runs the grounding gate.
        A Quick run produces less, with humbler confidence bands. It never lies to go faster.
      </div>
    </div>
  );
}

// ── Main InfoPage component ───────────────────────────────────────────────────

function InfoPage() {
  const { useState, useEffect, useRef } = React;
  const [activeSection, setActiveSection] = useState('welcome');

  // Highlight the active nav item based on scroll position.
  // SectionAnchor renders <div id={sectionId} /> just before each section heading.
  // We observe those anchors; the one most recently entering the viewport wins.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the entry with the largest intersection ratio that is intersecting,
        // or the first intersecting one — whichever is nearest the top.
        const visible = entries.filter((e) => e.isIntersecting);
        if (visible.length === 0) return;
        // Sort by bounding rect top ascending (topmost visible section wins)
        visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        const id = visible[0].target.id;
        if (id) setActiveSection(id);
      },
      { rootMargin: '-60px 0px -50% 0px', threshold: 0 }
    );
    SECTIONS.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, []);

  function scrollTo(id) {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    setActiveSection(id);
  }

  return (
    <div>
      <window.PageHeader
        title="Lighthouse Guide"
        subtitle="Everything you need to know about Lighthouse, in one place."
      />

      <div style={{ display: 'flex', gap: 32, alignItems: 'flex-start' }}>

        {/* ── Left section nav (sticky) ──────────────────────────────── */}
        <nav
          aria-label="Guide sections"
          style={{
            flexShrink: 0,
            width: 178,
            position: 'sticky',
            top: 72,
            alignSelf: 'flex-start',
          }}
        >
          <div style={{ ...window.card, padding: '10px 0', overflow: 'hidden' }}>
            {SECTIONS.map((s) => {
              const on = activeSection === s.id;
              return (
                <button
                  key={s.id}
                  onClick={() => scrollTo(s.id)}
                  className="lh-focusable"
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    background: on ? 'rgba(2,136,209,0.08)' : 'none',
                    border: 'none',
                    borderLeft: `3px solid ${on ? 'var(--primary)' : 'transparent'}`,
                    cursor: 'pointer',
                    fontFamily: 'var(--sans)',
                    fontSize: 12.5,
                    fontWeight: on ? 700 : 400,
                    color: on ? 'var(--primary)' : 'var(--ink-2)',
                    padding: '7px 14px 7px 13px',
                    lineHeight: 1.35,
                    transition: 'background .12s ease, color .12s ease, border-color .12s ease',
                  }}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        </nav>

        {/* ── Content pane ──────────────────────────────────────────── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Each Section* component starts with a <SectionAnchor id={sectionId} /> */}
          <SectionWelcome />
          <SectionGettingStarted />
          <SectionModes />
          <SectionSources />
          <SectionSandbox />
          <SectionWatch />
          <SectionSettings />
          <SectionTrustworthiness />

          {/* Footer CTA */}
          <div style={{ marginTop: 16, paddingTop: 24,
            borderTop: '1px solid var(--rule)', textAlign: 'center' }}>
            <a href="#research" className="btn-primary"
              style={{ textDecoration: 'none', display: 'inline-block' }}>
              Go to Research →
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

window.InfoPage = InfoPage;
})();
