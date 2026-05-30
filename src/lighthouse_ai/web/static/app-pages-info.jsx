// app-pages-info.jsx — the Info tab: a clean, in-app documentation section.
// Loaded via babel-standalone into the shared global scope; registers window.InfoPage.
// Uses window.* primitives from app-lib.jsx (PageHeader, card, NavIcon, etc.).
//
// Layout: a sticky left table-of-contents + a readable ~720px main column with
// serif headings, generous line-height, and code/keys in --mono. Every section
// has an anchored id so TOC clicks (and #hash links) scroll to it, with a
// scroll-margin offset so headings clear the app's sticky top bar.
//
// Documentation outline:
//   Overview      · What Lighthouse is · Getting started
//   The tabs      · Research · Library · Watch · Track · Activity · Sandbox · Health · Settings
//   Concepts      · Research modes · Depth tiers · Sources · How we keep it trustworthy
//   How to        · Common tasks, step by step

(function () {

// ── Table of contents ─────────────────────────────────────────────────────────
// Grouped so the nav reads like a docs sidebar. Each leaf id matches a section
// anchor rendered in the content column.
const TOC = [
  {
    group: 'Overview',
    items: [
      { id: 'welcome',         label: 'What is Lighthouse' },
      { id: 'getting-started', label: 'Getting started' },
    ],
  },
  {
    group: 'The tabs',
    items: [
      { id: 'tab-research', label: 'Research' },
      { id: 'tab-library',  label: 'Library' },
      { id: 'tab-watch',    label: 'Watch' },
      { id: 'tab-track',    label: 'Track' },
      { id: 'tab-activity', label: 'Activity' },
      { id: 'tab-sandbox',  label: 'Sandbox' },
      { id: 'tab-health',   label: 'Health' },
      { id: 'tab-settings', label: 'Settings' },
    ],
  },
  {
    group: 'Concepts',
    items: [
      { id: 'modes',       label: 'Research modes' },
      { id: 'depth',       label: 'Depth tiers' },
      { id: 'sources',     label: 'Sources' },
      { id: 'trustworthy', label: 'How we keep it trustworthy' },
    ],
  },
  {
    group: 'How to',
    items: [
      { id: 'howto', label: 'Common tasks' },
    ],
  },
];

// Flat id list (for the IntersectionObserver and validation).
const ALL_IDS = TOC.reduce((acc, g) => acc.concat(g.items.map((i) => i.id)), []);

// ── Typographic tokens (inline; mirror app CSS vars) ──────────────────────────
const prose = {
  fontFamily: 'var(--serif)',
  fontSize: 15.5,
  lineHeight: 1.75,
  color: 'var(--ink-2)',
  margin: 0,
};
const h2style = {
  fontFamily: 'var(--serif)',
  fontSize: 24,
  fontWeight: 700,
  color: 'var(--ink)',
  margin: '0 0 12px',
  lineHeight: 1.2,
  letterSpacing: '-0.01em',
};
const h3style = {
  fontFamily: 'var(--serif)',
  fontSize: 17,
  fontWeight: 700,
  color: 'var(--ink)',
  margin: '28px 0 8px',
  lineHeight: 1.3,
};
const groupLabelStyle = {
  fontFamily: 'var(--sans)',
  fontSize: 10.5,
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.09em',
  color: 'var(--muted)',
  padding: '14px 16px 6px',
};
const sectionBox = {
  paddingBottom: 36,
  borderBottom: '1px solid var(--rule)',
  marginBottom: 36,
  // Clears the app's sticky top bar when scrolled into view.
  scrollMarginTop: 84,
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
  fontSize: 14,
  lineHeight: 1.65,
  color: 'var(--ink-2)',
  margin: '16px 0',
};
const codeBlock = {
  fontFamily: 'var(--mono)',
  fontSize: 13,
  background: 'var(--rule-soft)',
  border: '1px solid var(--rule)',
  borderRadius: 'var(--radius)',
  padding: '10px 14px',
  margin: '10px 0',
  color: 'var(--ink)',
  overflowX: 'auto',
};
const kbd = {
  fontFamily: 'var(--mono)',
  fontSize: 12.5,
  color: 'var(--ink)',
  background: 'var(--rule-soft)',
  borderRadius: 4,
  padding: '1px 5px',
};

// ── Mode data (the 7 real modes in modes/) ────────────────────────────────────
const MODES = [
  {
    name: 'Investigate', key: 'investigate', artifact: 'Report',
    tagline: 'A structured, cited report on one question.',
    body: 'Lighthouse decomposes your question, researches each part, merges the evidence, and stages a report with per-section citations and confidence ratings. Every claim is checked against a real source before it appears.',
    when: 'You need depth and citations, not just a quick answer.',
  },
  {
    name: 'Ask', key: 'ask', artifact: 'Transcript',
    tagline: 'Get a cited answer and follow up in conversation.',
    body: 'Ask a focused question and get a sourced answer drawn from your corpus. Each response shows the chunks it used; you can follow up in the same session.',
    when: 'You want a quick, grounded answer and may want to dig deeper in conversation.',
  },
  {
    name: 'Survey', key: 'survey', artifact: 'Evidence table',
    tagline: 'Screen many documents into a sortable grid.',
    body: 'Define what to include and what columns you care about. Lighthouse screens each document, extracts a cell per column with citations and a faithfulness check, and reports a PRISMA-style inclusion flow (identified → screened → included).',
    when: 'You have a corpus to triage and want a comparable table, not prose.',
  },
  {
    name: 'Reconstruct', key: 'reconstruct', artifact: 'Timeline',
    tagline: 'Assemble a sourced chronology of events.',
    body: 'Lighthouse extracts dated events from the corpus, deduplicates them, resolves conflicting dates by weighted vote across sources, and orders them into a timeline with per-event certainty.',
    when: 'You need to know what happened, in what order, with sources.',
  },
  {
    name: 'Decide', key: 'decide', artifact: 'Decision matrix',
    tagline: 'Score options against weighted criteria.',
    body: 'Provide your options and weighted criteria. Lighthouse scores each cell, computes weighted totals, runs a sensitivity sweep, and names the crux — the criterion that, if wrong, flips the result.',
    when: 'You are choosing between options and want the trade-offs made explicit.',
  },
  {
    name: 'Adjudicate', key: 'adjudicate', artifact: 'Verdict',
    tagline: 'Run a structured debate and name the crux.',
    body: 'Lighthouse argues four perspectives on a contested question (steelman, devil\'s advocate, base rate, fragility), weighs them, and delivers a verdict that names the crux of disagreement rather than flattening it into one take.',
    when: 'A question is genuinely contested and you want the tensions surfaced rather than smoothed.',
  },
  {
    name: 'Watch', key: 'watch', artifact: 'Digest',
    tagline: 'Stay current without watching it yourself.',
    body: 'Define a topic and a set of sources. Lighthouse polls them on a schedule, surfaces high-salience items as alerts, and batches the rest into a digest you can skim.',
    when: 'Something is unfolding and you need to know when it moves.',
  },
];

// ── Source families ───────────────────────────────────────────────────────────
const SOURCE_FAMILIES = [
  { family: 'Academic literature', sources: ['arXiv', 'OpenAlex', 'PubMed', 'Crossref', 'Semantic Scholar'] },
  { family: 'Clinical / biomedical', sources: ['ClinicalTrials.gov'] },
  { family: 'Legal', sources: ['CourtListener / RECAP'] },
  { family: 'U.S. federal government', sources: ['Federal Register', 'regulations.gov', 'GovInfo', 'Congress.gov'] },
  { family: 'Corporate & financial', sources: ['SEC EDGAR'] },
  { family: 'Economic data', sources: ['FRED (St. Louis Fed)', 'BEA', 'BLS', 'World Bank Open Data', 'OECD Data'] },
  { family: 'Engineering & software', sources: ['GitHub', 'PyPI / npm / crates.io'] },
  { family: 'Reference', sources: ['Wikipedia', 'Wikidata'] },
  { family: 'Media', sources: ['YouTube', 'Internet Archive (audio / video)'] },
  { family: 'News', sources: ['Reuters', 'Associated Press', 'BBC News', 'NPR', 'The Guardian', 'ProPublica', 'News Orchestrator (cross-outlet)'] },
  { family: 'Web & archive', sources: ['General Web', 'RSS / Atom feeds', 'Wayback Machine'] },
  { family: 'Public health & demographics', sources: ['WHO', 'U.S. Census Bureau'] },
];

// ── Depth tiers ───────────────────────────────────────────────────────────────
const DEPTH_TIERS = [
  { name: 'Quick', feel: '~1–3 min',
    desc: 'A fast, grounded scan. Fewer retrieval rounds, smaller source set. Produces less with humbler confidence — but never lies to go faster.' },
  { name: 'Standard', feel: '~5–10 min',
    desc: 'Balanced coverage with gap-filling and deduplication. Roughly equivalent in depth to what frontier services (Claude, Gemini) reach in their time-boxed runs.' },
  { name: 'Thorough', feel: '~20–60 min',
    desc: 'Adds adversarial refutation (a skeptic tries to knock down each key claim), a coverage critic (fills missing angles), and triangulation (key claims need at least two independent sources). Depth frontier services can\'t structurally reach.' },
  { name: 'Deep', feel: 'Hours (you set the budget)',
    desc: 'A recursive question-tree run to exhaustion — sub-questions decompose into sub-sub-questions until each leaf is grounded or recorded as a known unknown. Requires a committed budget (30 min / 1 h / 2 h / overnight) before it starts.' },
];

// ── Per-tab guide ─────────────────────────────────────────────────────────────
// id matches a TOC leaf; icon reuses window.NavIcon names from app.jsx.
const TABS = [
  {
    id: 'tab-research', icon: 'research', name: 'Research',
    summary: 'Where every research job starts.',
    body: 'Pick a mode, type your question, choose your sources, and set a depth tier. Lighthouse frames the question, runs the pipeline, and stages the result for your review. This is the landing tab and the place you will spend most of your time.',
    points: [
      'A framing pipeline classifies your question and decomposes it into sub-questions.',
      'A recommender pre-checks the sources most relevant to what you asked.',
      'Depth defaults to Auto, which picks a tier from the question type; you can override it.',
    ],
  },
  {
    id: 'tab-library', icon: 'library', name: 'Library',
    summary: 'Your finished research, kept and exportable.',
    body: 'Every completed run is staged here for review. Open an artifact to read it, check its citations, and review its provenance footer (mode, depth, time taken, model). Approve it to keep it, reject it to discard it, or export it. Lighthouse never publishes anything automatically.',
    points: [
      'Filter by artifact type (report, table, timeline, matrix, verdict, digest).',
      'Each artifact carries an audit footer showing exactly what produced it.',
      'Export to share a result with a colleague.',
    ],
  },
  {
    id: 'tab-watch', icon: 'watch', name: 'Watch',
    summary: 'Monitor a topic or website over time.',
    body: 'Set up a topic — a subject, entity, or question you want to follow — and Lighthouse polls your chosen sources on a schedule, deduplicates what it has seen, and scores each new item for salience. High-salience items become alerts; the rest are batched into a digest in the Library.',
    points: [
      'Only sources with a live feed (marked "watchable") appear for Watch topics.',
      'Two layers of dedup: exact URL match, then semantic near-duplicate titles.',
      'Configure a notification channel in Settings to get alerts.',
    ],
  },
  {
    id: 'tab-track', icon: 'track', name: 'Track',
    summary: 'Hold predictions accountable over time.',
    body: 'A position is a prediction you have committed to with a probability. As positions resolve, Lighthouse scores how calibrated you were (Brier score) and plots the trend. The tab also holds the register of open and resolved positions and any escalations that need your attention.',
    points: [
      'See whether your stated probabilities matched real outcomes.',
      'Manage the register of open and resolved positions.',
      'Review escalations — contested claims that were promoted for a closer look.',
    ],
  },
  {
    id: 'tab-activity', icon: 'activity', name: 'Activity',
    summary: 'Watch runs in flight and follow the audit trail.',
    body: 'See every research run move from queued, to running, to ready for review — and pause, resume, or cancel any of them. Below the live runs, the audit trail lists what happened: each state transition, source fetch, and model call.',
    points: [
      'Live status for queued, running, paused, and review-ready jobs.',
      'Per-run controls: pause, resume, cancel.',
      'The audit trail is HMAC-chained, so tampering breaks the chain.',
    ],
  },
  {
    id: 'tab-sandbox', icon: 'sandbox', name: 'Sandbox',
    summary: 'A secured workspace for your own files.',
    body: 'Bring in documents you want analyzed — PDFs, spreadsheets, papers. Every file is scanned on the way in before it can enter the pipeline. The Sandbox has two zones: your read-only uploads, and an assistant workspace for analysis results. Because everything runs locally, sensitive files never leave your machine.',
    points: [
      'Scanners check for malware signatures, PDF/HTML script injection, and zip bombs.',
      'Failed files are quarantined and reported; they never reach the pipeline.',
      'A size limit evicts the oldest unpinned items first; pin anything you want to keep.',
    ],
  },
  {
    id: 'tab-health', icon: 'system', name: 'Health',
    summary: 'A live view of this machine and its models.',
    body: 'See the detected hardware, the models Lighthouse chose to fit it, and the status of the services it depends on. Each check rolls up to an overall verdict so you can tell at a glance whether everything is ready. The view auto-refreshes, and you can force a re-check.',
    points: [
      'Hardware readout and the budget-aware model picks for it.',
      'Per-service checks with a single overall green / degraded verdict.',
      'Auto-polls every 15 seconds; a manual re-check is one click away.',
    ],
  },
  {
    id: 'tab-settings', icon: 'settings', name: 'Settings',
    summary: 'Connect data sources and control reproducibility.',
    body: 'Connect your data sources (paste a free API key to raise a rate limit or unlock data), control reproducibility (lock the model for identical results), and configure notifications. Keys are stored in your operating system\'s keychain and never transmitted to Lighthouse servers.',
    points: [
      'Add free API keys for FRED, BEA, BLS, GitHub, Semantic Scholar, and more.',
      'Lock the model (temperature 0, pinned seed) so a question reproduces exactly.',
      'Set up a notification channel for Watch alerts.',
    ],
  },
];

// ── How-to recipes ────────────────────────────────────────────────────────────
const HOWTOS = [
  {
    title: 'Start a research run',
    steps: [
      'Open the Research tab.',
      'Choose a mode that matches your task (see Research modes below).',
      'Type your question, then review the pre-checked sources and adjust as needed.',
      'Pick a depth tier (or leave it on Auto) and start. The result appears in Library when it is staged for review.',
    ],
  },
  {
    title: 'Watch a website or topic',
    steps: [
      'Open the Watch tab and click "+ Add topic".',
      'Give it a name and a query string — the terms Lighthouse searches with.',
      'Choose from the watchable sources (RSS, news outlets, arXiv, GitHub, general web).',
      'Run a session. Alerts and a digest land in the Library; set up notifications in Settings to be pinged.',
    ],
  },
  {
    title: 'Connect a data source / add an API key',
    steps: [
      'Open Settings → Connect your data sources.',
      'Find the source you want (each shows its status and a link to a free key).',
      'Paste the key and click Save. It is stored in your OS keychain, shown once, and never sent off the machine.',
      'The source now runs at its higher rate limit on your next run.',
    ],
  },
  {
    title: 'Free up your machine with Pause',
    steps: [
      'At the top of the sidebar, click Pause all.',
      'All background work stops immediately — scheduled Watch sessions, calibration runs, pending jobs.',
      'Do the CPU- or RAM-heavy thing you need to do; nothing is lost or cancelled.',
      'Click Resume work and in-progress jobs pick up where they left off.',
    ],
  },
  {
    title: 'Reproduce a result exactly',
    steps: [
      'Open Settings → Reproducibility.',
      'Turn on "Lock the model for identical results" (temperature 0, pinned seed).',
      'Run the question. The same question on the same corpus now produces the same artifact.',
      'Share the artifact, or replay its job ID, to verify identical inputs give identical outputs.',
    ],
  },
  {
    title: 'Add a custom source',
    steps: [
      'Run lighthouse skill new my_source --name "My Source" --category academic to scaffold it.',
      'Fill in the manifest, the guide, and the query logic in the new source folder.',
      'Run lighthouse skill validate my_source to confirm it loads cleanly.',
      'Lighthouse picks it up automatically on its next scan. Custom sources load with a lower confidence band.',
    ],
  },
];

// ── Reusable sub-components ────────────────────────────────────────────────────

function ModeCard({ mode }) {
  return (
    <div style={{ ...window.card, padding: '16px 18px', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
        <span style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700, color: 'var(--ink)' }}>{mode.name}</span>
        <span style={pill('var(--rule-soft)', 'var(--muted)')}>{mode.artifact}</span>
      </div>
      <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--primary)', marginBottom: 8 }}>{mode.tagline}</div>
      <div style={{ ...prose, fontSize: 14, marginBottom: 10 }}>{mode.body}</div>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', borderTop: '1px solid var(--rule)', paddingTop: 8, lineHeight: 1.5 }}>
        <strong style={{ color: 'var(--ink-2)' }}>Use when:</strong> {mode.when}
      </div>
    </div>
  );
}

function DepthCard({ tier }) {
  const badge = {
    Quick: ['rgba(0,100,200,0.1)', '#005b9a'],
    Standard: ['rgba(0,140,100,0.1)', '#006940'],
    Thorough: ['rgba(180,100,0,0.1)', '#8a4f00'],
    Deep: ['rgba(140,30,120,0.1)', '#6d1060'],
  }[tier.name] || ['var(--rule-soft)', 'var(--muted)'];
  return (
    <div style={{ ...window.card, padding: '14px 18px', marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <span style={pill(badge[0], badge[1])}>{tier.name}</span>
        <span style={{ fontSize: 12, color: 'var(--muted)', fontFamily: 'var(--sans)' }}>{tier.feel}</span>
      </div>
      <div style={{ ...prose, fontSize: 14 }}>{tier.desc}</div>
    </div>
  );
}

function TabCard({ tab }) {
  return (
    <div id={tab.id} style={{ ...window.card, padding: '18px 20px', marginBottom: 14, scrollMarginTop: 84 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 8 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 30, height: 30, borderRadius: 'var(--radius)', background: 'rgba(2,136,209,0.08)',
          color: 'var(--primary)', flexShrink: 0 }}>
          <window.NavIcon name={tab.icon} size={17} />
        </span>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontFamily: 'var(--serif)', fontSize: 18, fontWeight: 700, color: 'var(--ink)' }}>{tab.name}</span>
          <span style={{ fontSize: 13, color: 'var(--muted)', fontFamily: 'var(--sans)' }}>{tab.summary}</span>
        </div>
      </div>
      <div style={{ ...prose, fontSize: 14, marginBottom: 10 }}>{tab.body}</div>
      <ul style={{ margin: 0, paddingLeft: 18, listStyle: 'disc' }}>
        {tab.points.map((p, i) => (
          <li key={i} style={{ fontSize: 13.5, color: 'var(--ink-2)', fontFamily: 'var(--serif)',
            lineHeight: 1.6, marginBottom: 3 }}>{p}</li>
        ))}
      </ul>
    </div>
  );
}

function HowToCard({ recipe }) {
  return (
    <div style={{ ...window.card, padding: '16px 20px', marginBottom: 12 }}>
      <div style={{ fontFamily: 'var(--serif)', fontSize: 16, fontWeight: 700, color: 'var(--ink)', marginBottom: 10 }}>
        {recipe.title}
      </div>
      <ol style={{ margin: 0, paddingLeft: 20, listStyle: 'decimal' }}>
        {recipe.steps.map((s, i) => (
          <li key={i} style={{ ...prose, fontSize: 14, marginBottom: 6 }}>{s}</li>
        ))}
      </ol>
    </div>
  );
}

// ── Sections ──────────────────────────────────────────────────────────────────

function SectionWelcome() {
  return (
    <section id="welcome" style={sectionBox}>
      <h2 style={h2style}>What is Lighthouse</h2>
      <p style={prose}>
        Lighthouse is a local-first research instrument. It runs entirely on your own hardware — your
        sources, your models, your data — and produces research you can verify, reproduce, and audit.
        Nothing leaves your machine unless you explicitly choose a source that reaches the open web.
      </p>
      <p style={{ ...prose, marginTop: 12 }}>
        The core bet is that the highest-leverage quality feature in research tooling is not the
        model's fluency — it is whether the output can be trusted. Lighthouse is optimized to be
        verifiable and correct rather than impressive on first read. Every claim in an artifact cites
        a real source chunk. Every run produces a tamper-evident audit trail. Confidence is stated
        honestly and downgraded when the evidence does not support a strong claim.
      </p>

      <h3 style={h3style}>The trust wedge</h3>
      <p style={prose}>Three properties hold at every depth tier, for every research mode:</p>
      <ul style={{ ...prose, paddingLeft: 22, marginTop: 8 }}>
        <li style={{ marginBottom: 6 }}>
          <strong>Cited and grounded.</strong> A claim that cannot be traced to a real source chunk
          is dropped or flagged — never asserted. Zero fabricated citations is a hard invariant.
        </li>
        <li style={{ marginBottom: 6 }}>
          <strong>Calibrated.</strong> Confidence is a band (remote / unlikely / even chance / likely /
          almost certain), downgraded automatically when coverage is thin. Lighthouse never overstates certainty.
        </li>
        <li style={{ marginBottom: 6 }}>
          <strong>Auditable.</strong> Every run records which model ran, which sources were used,
          which backend executed (local vs. mock), and a SHA-256 content hash — so any reader can
          see exactly what produced the result.
        </li>
      </ul>

      <div style={callout}>
        <strong>Better than frontier on trust, not model size.</strong> Services like Gemini Deep
        Research and Claude Research time-box to roughly 10–20 minutes — about what Lighthouse calls
        Standard depth. Lighthouse's Thorough and Deep tiers — adversarial refutation, triangulation,
        recursive question trees — are depth those services structurally cannot reach. And because
        everything runs locally, your documents never leave your machine.
      </div>

      <h3 style={h3style}>Who it is for</h3>
      <p style={prose}>
        Lighthouse was built for two kinds of people. The first is the regulated-industry professional
        — a lawyer, clinician, compliance officer, or financial analyst — who cannot send working
        documents to a cloud service and needs audit-ready provenance. The second is the serious
        generalist researcher who wants depth and honesty, not just a fast answer that sounds plausible.
        Both benefit from the same core property: research you can stand behind.
      </p>
    </section>
  );
}

function SectionGettingStarted() {
  const steps = [
    { num: '1', title: 'Install and launch',
      desc: 'Lighthouse runs on your machine. Initialize it once, start it, and open the dashboard in your browser — the same dashboard you are reading this in.' },
    { num: '2', title: 'Open the Research tab',
      desc: 'Everything starts here. Pick one of the seven research modes (Investigate, Ask, Survey, Reconstruct, Decide, Adjudicate, Watch). Not sure which? See Research modes below.' },
    { num: '3', title: 'Frame the question',
      desc: 'Type your question or topic. A framing pipeline classifies the question type and decomposes it into sub-questions, so your actual question is the starting point — not a form to fill in.' },
    { num: '4', title: 'Choose sources and depth',
      desc: 'The source picker pre-checks the sources most relevant to your question. Pick a depth tier (or leave it on Auto), confirm, and Lighthouse runs.' },
    { num: '5', title: 'Review in the Library',
      desc: 'When a run finishes, the artifact is staged in the Library tab. Read it, check its citations, and approve or reject it. Lighthouse never publishes anything automatically.' },
  ];
  return (
    <section id="getting-started" style={sectionBox}>
      <h2 style={h2style}>Getting started</h2>
      <p style={prose}>
        The first run takes about a minute to set up. Here is the whole path, from launch to your
        first reviewed result:
      </p>
      <div style={{ marginTop: 18 }}>
        {steps.map((s) => (
          <div key={s.num} style={{ display: 'flex', gap: 16, marginBottom: 18, alignItems: 'flex-start' }}>
            <div style={{ flexShrink: 0, width: 30, height: 30, borderRadius: '50%',
              background: 'var(--primary)', color: '#fff', display: 'flex', alignItems: 'center',
              justifyContent: 'center', fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700 }}>
              {s.num}
            </div>
            <div>
              <div style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 3 }}>{s.title}</div>
              <div style={{ ...prose, fontSize: 14 }}>{s.desc}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={callout}>
        <strong>Where results appear.</strong> When a run finishes, its artifact is staged for review
        in the <strong>Library</strong> tab. You can read it there, approve it to keep it, or reject
        it. Nothing is published on its own.
      </div>
      <p style={{ ...prose, marginTop: 14 }}>
        <strong>API keys are optional.</strong> Every source works without a key. Several — FRED, BLS,
        BEA, GitHub, and others — let you paste a free key to raise a rate limit or unlock extra data.
        Add them under <strong>Settings → Connect your data sources</strong>; keys stay on your machine.
      </p>
    </section>
  );
}

function SectionTabs() {
  return (
    <section style={{ ...sectionBox, scrollMarginTop: 0 }}>
      <h2 style={h2style}>A guide to each tab</h2>
      <p style={prose}>
        The sidebar holds nine tabs. Here is what each one is for, in plain language. Most work flows
        from <strong>Research</strong> to <strong>Library</strong>; the rest support monitoring,
        accountability, your own files, and machine health.
      </p>
      <div style={{ marginTop: 18 }}>
        {TABS.map((t) => <TabCard key={t.id} tab={t} />)}
      </div>
    </section>
  );
}

function SectionModes() {
  return (
    <section id="modes" style={sectionBox}>
      <h2 style={h2style}>Research modes</h2>
      <p style={prose}>
        Lighthouse works in seven research modes. Each produces a different kind of artifact and suits
        a different kind of task. Pick the one that matches what you need.
      </p>
      <div style={{ marginTop: 18 }}>
        {MODES.map((m) => <ModeCard key={m.key} mode={m} />)}
      </div>
      <p style={{ ...prose, marginTop: 14, fontSize: 14 }}>
        <strong>Note on Adjudicate:</strong> a Quick Adjudicate is disabled — a two-perspective debate
        produces the appearance of balance without the rigor, so selecting Adjudicate raises the
        minimum tier to Standard.
      </p>
    </section>
  );
}

function SectionDepth() {
  return (
    <section id="depth" style={sectionBox}>
      <h2 style={h2style}>Depth tiers</h2>
      <p style={prose}>
        Every mode (except Watch, which works on a schedule) takes a depth tier. Depth scales how much
        Lighthouse covers and how hard each claim is stress-tested — not whether the output can be
        trusted. Even a Quick run never fabricates a citation.
      </p>
      <div style={{ marginTop: 16 }}>
        {DEPTH_TIERS.map((t) => <DepthCard key={t.name} tier={t} />)}
      </div>
      <div style={callout}>
        <strong>Auto depth.</strong> The Research tab defaults to <em>Auto</em>, which picks a tier
        from your question type: factual lookups go Quick; comparative or decision questions go
        Standard; contested or methodological questions go Thorough. You can always override it.
      </div>
      <p style={{ ...prose, marginTop: 12, fontSize: 14 }}>
        <strong>Note on Deep:</strong> the Deep tier requires you to commit a budget (30 min, 1 h,
        2 h, or overnight) before it starts. The Governor refuses to launch without one — so no run
        can consume your machine indefinitely.
      </p>
    </section>
  );
}

function SectionSources() {
  return (
    <section id="sources" style={sectionBox}>
      <h2 style={h2style}>Sources</h2>
      <p style={prose}>
        Lighthouse ships with 36 sources, one per destination. Each is a self-contained module that
        knows how to query its destination well — the right API parameters, politeness rules, and way
        to extract a citable document. All sources run through the same security broker: every byte
        fetched is scanned before it enters your corpus.
      </p>

      <h3 style={h3style}>How the source picker works</h3>
      <p style={prose}>
        When you frame a question, a recommender ranks the 36 sources by how well they fit your
        question, mode, and depth. The Research tab shows the top matches pre-checked, each with a
        short reason. You can add or remove sources freely — the recommender is a starting point, not
        a constraint. A clinical question surfaces PubMed, ClinicalTrials.gov, and WHO; a financial
        one surfaces SEC EDGAR, FRED, and BLS; an engineering one surfaces GitHub and arXiv.
      </p>

      <h3 style={h3style}>The 36 sources by family</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginTop: 12 }}>
        {SOURCE_FAMILIES.map((f) => (
          <div key={f.family} style={{ ...window.card, padding: '14px 16px' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase',
              letterSpacing: '0.06em', marginBottom: 8 }}>{f.family}</div>
            <ul style={{ margin: 0, paddingLeft: 16, listStyle: 'disc' }}>
              {f.sources.map((s) => (
                <li key={s} style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.6, marginBottom: 2 }}>{s}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <h3 style={h3style}>Sources that benefit from a free key</h3>
      <p style={prose}>
        Most sources work without authentication at lower rate limits. A free API key raises the limit
        or unlocks extra data. The ones that benefit most:
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
        {['FRED', 'BEA', 'BLS', 'U.S. Census', 'GitHub', 'Semantic Scholar', 'The Guardian'].map((s) => (
          <span key={s} style={pill('rgba(2,136,209,0.1)', 'var(--primary)')}>{s}</span>
        ))}
      </div>
      <p style={{ ...prose, fontSize: 13.5, marginTop: 10 }}>
        Add them under Settings → Connect your data sources. Keys are stored on your device and never
        sent off it.
      </p>

      <h3 style={h3style}>Adding a custom source</h3>
      <p style={prose}>You can teach Lighthouse to research any new destination with the command-line tool:</p>
      <div style={codeBlock}>lighthouse skill new my_source --name "My Source" --category academic</div>
      <p style={{ ...prose, fontSize: 14 }}>
        This scaffolds a source folder with a manifest and a stub entrypoint. Fill in the guide and the
        query logic; Lighthouse picks it up on its next scan. Use{' '}
        <span style={kbd}>lighthouse skill list</span> to see installed sources and{' '}
        <span style={kbd}>lighthouse skill validate my_source</span> to confirm it loads cleanly.
      </p>
      <div style={callout}>
        <strong>Source provenance.</strong> Officially curated sources are signed. Community or custom
        sources load with a lower confidence band applied automatically — a claim that depends only on
        an unsigned source is never labeled "almost certain."
      </div>
    </section>
  );
}

function SectionTrustworthiness() {
  const points = [
    { title: 'Verifiable grounding — zero fabricated citations',
      body: 'Every claim in an artifact must be entailed by a real, cited source chunk that exists in the corpus. A cited chunk ID that cannot be found in the evidence fails the gate — the claim is dropped or flagged, not asserted. This is a hard invariant across every mode and every depth tier.' },
    { title: 'Adversarial refutation',
      body: 'At Thorough and Deep, an independent skeptic attempts to refute each key claim against the same evidence. Refuted or contested claims are flagged, not smoothed over. A claim that survives the skeptic is labeled stronger than one never challenged.' },
    { title: 'Triangulation across independent sources',
      body: 'At Thorough and Deep, key claims must be backed by at least two independent sources — different domains or documents, not just different citation numbers from the same paper. A claim supported by only one source is labeled accordingly.' },
    { title: 'Contradictions surfaced, not smoothed',
      body: 'When sources disagree, Lighthouse surfaces the disagreement rather than picking one and ignoring the other. Contradictions are first-class artifacts: they appear in reports, escalate to Adjudicate when load-bearing, and are never silently resolved.' },
    { title: 'Calibration',
      body: 'Every claim carries a confidence band (remote / unlikely / even chance / likely / almost certain). These are honest: a poorly-sourced answer is never labeled "almost certain," and the band is downgraded when citation coverage is thin. Over time, the Track tab records how stated probabilities matched real outcomes (Brier score).' },
    { title: 'The audit trail',
      body: 'Every artifact\'s Library footer shows its provenance compactly: mode, depth tier, time taken, and which model ran. The full audit log — every state transition, source fetch, and model call — is HMAC-chained, so tampering breaks the chain. You can replay a job ID and verify the same inputs produce the same result.' },
  ];
  return (
    <section id="trustworthy" style={sectionBox}>
      <h2 style={h2style}>How we keep it trustworthy</h2>
      <p style={prose}>
        Trustworthiness is not a feature Lighthouse adds at the end — it is the architecture. Six
        mechanisms work together to make every artifact verifiable, honest about uncertainty, and
        resistant to the failure modes that plague LLM-generated research.
      </p>
      <div style={{ marginTop: 18 }}>
        {points.map((p, i) => (
          <div key={i} style={{ ...window.card, padding: '16px 20px', marginBottom: 12 }}>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 15.5, fontWeight: 700, color: 'var(--ink)', marginBottom: 7 }}>{p.title}</div>
            <div style={{ ...prose, fontSize: 14 }}>{p.body}</div>
          </div>
        ))}
      </div>
      <div style={callout}>
        <strong>The invariant that never changes with depth:</strong> depth scales coverage and
        confidence, never trust. Every tier — Quick through Deep — runs the grounding gate. A Quick run
        produces less, with humbler confidence bands. It never lies to go faster.
      </div>
    </section>
  );
}

function SectionHowTo() {
  return (
    <section id="howto" style={{ ...sectionBox, borderBottom: 'none', paddingBottom: 0, marginBottom: 0 }}>
      <h2 style={h2style}>How to: common tasks</h2>
      <p style={prose}>Short, step-by-step recipes for the things you will do most often.</p>
      <div style={{ marginTop: 18 }}>
        {HOWTOS.map((r) => <HowToCard key={r.title} recipe={r} />)}
      </div>
    </section>
  );
}

// ── Main InfoPage ─────────────────────────────────────────────────────────────

function InfoPage() {
  const { useState, useEffect } = React;
  const [activeId, setActiveId] = useState('welcome');

  // Highlight the active TOC item by scroll position. Each section has id={leaf};
  // the topmost intersecting one wins. The rootMargin biases the active line to
  // the heading nearest the top of the viewport under the sticky bar.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting);
        if (visible.length === 0) return;
        visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        const id = visible[0].target.id;
        if (id) setActiveId(id);
      },
      { rootMargin: '-72px 0px -55% 0px', threshold: 0 }
    );
    ALL_IDS.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, []);

  function scrollTo(id) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setActiveId(id);
  }

  return (
    <div>
      <window.PageHeader
        title="Documentation"
        subtitle="Learn Lighthouse from one place: what it is, every tab, and how to do the common tasks."
      />

      <div style={{ display: 'flex', gap: 40, alignItems: 'flex-start' }}>

        {/* ── Table of contents (sticky) ─────────────────────────────── */}
        <nav aria-label="Documentation contents"
          style={{ flexShrink: 0, width: 196, position: 'sticky', top: 72, alignSelf: 'flex-start' }}>
          <div style={{ ...window.card, padding: '4px 0', overflow: 'hidden' }}>
            {TOC.map((g) => (
              <div key={g.group}>
                <div style={groupLabelStyle}>{g.group}</div>
                {g.items.map((item) => {
                  const on = activeId === item.id;
                  return (
                    <button key={item.id} onClick={() => scrollTo(item.id)} className="lh-focusable"
                      style={{
                        display: 'block', width: '100%', textAlign: 'left',
                        background: on ? 'rgba(2,136,209,0.08)' : 'none', border: 'none',
                        borderLeft: `3px solid ${on ? 'var(--primary)' : 'transparent'}`,
                        cursor: 'pointer', fontFamily: 'var(--sans)', fontSize: 12.5,
                        fontWeight: on ? 700 : 400, color: on ? 'var(--primary)' : 'var(--ink-2)',
                        padding: '6px 14px 6px 13px', lineHeight: 1.35,
                        transition: 'background .12s ease, color .12s ease, border-color .12s ease',
                      }}>
                      {item.label}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </nav>

        {/* ── Readable content column (~720px) ───────────────────────── */}
        <div style={{ flex: 1, minWidth: 0, maxWidth: 720 }}>
          <SectionWelcome />
          <SectionGettingStarted />
          <SectionTabs />
          <SectionModes />
          <SectionDepth />
          <SectionSources />
          <SectionTrustworthiness />
          <SectionHowTo />

          <div style={{ marginTop: 36, paddingTop: 24, borderTop: '1px solid var(--rule)', textAlign: 'center' }}>
            <a href="#research" className="btn-primary" style={{ textDecoration: 'none', display: 'inline-block' }}>
              Go to Research
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

window.InfoPage = InfoPage;
})();
