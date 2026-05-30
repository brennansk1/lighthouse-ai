// app-pages-redesign.jsx — the artifact-centric dashboard pages introduced by
// the 7-mode redesign. Loaded after the legacy page files so it can compose
// the existing TopicsPage / PositionsPage / IntelligencePage / HealthPage where
// a tab is a reframing of an existing surface, and define brand-new pages
// (Research launcher, Library, Activity) where there was none.
//
// Conventions mirror the other page files: a single IIFE, React hooks via the
// shared global, primitives + API helpers off window.*, pages exported at the
// end via Object.assign(window, {...}).

(function () {
const { useState, useEffect, useCallback } = React;
const { apiGet, apiPost, useApi, useEvents } = window;
const { PageHeader, EmptyState, Loading, ErrorBox, Btn, StatusPill, card, Row } = window;
const { SidePane } = window;

const PAD = '4px 0 40px';
const GAP = 18;

// Artifact-type → human label + nav-style glyph name.
const ARTIFACT_META = {
  report:     { label: 'Report' },
  digest:     { label: 'Digest' },
  table:      { label: 'Evidence table' },
  timeline:   { label: 'Timeline' },
  matrix:     { label: 'Decision matrix' },
  verdict:    { label: 'Verdict' },
  transcript: { label: 'Transcript' },
};

function artifactLabel(t) {
  return (ARTIFACT_META[t] && ARTIFACT_META[t].label) || (t || 'Artifact');
}

// ── Intent Recipes ──────────────────────────────────────────────────────────
//
// Plain-language starting points for newcomers. Each recipe pre-fills the wizard
// (mode, depth, a suggested source list, and an example prompt placeholder) so
// the user can skip the mode taxonomy and just pick something that sounds right.
// Clicking a recipe sets state and jumps to step 2 (frame). The user can still
// ignore recipes entirely and pick a mode manually — the existing flow is
// unchanged.
//
// suggestedSkills values are skill_ids from the source registry.  The SourcePicker
// in step 2 still lets the user add or remove sources; these are just pre-checks
// so the most-useful sources are already ticked when the user lands on the frame
// step.
//
// Depth keys: 'quick' | 'standard' | 'thorough' | 'deep'
// Mode keys (verified against MODE_PROCESSES.md registry):
//   watch | ask | investigate | survey | reconstruct | decide | adjudicate

const INTENT_RECIPES = [
  {
    id: 'literature-review',
    label: 'Draft a literature review',
    blurb: 'Survey academic sources and produce an evidence table with a PRISMA screen.',
    mode: 'investigate',
    depth: 'thorough',
    suggestedSkills: ['openalex', 'pubmed', 'arxiv', 'semantic_scholar'],
    examplePrompt: 'e.g. What does the recent literature say about GLP-1 drugs for weight maintenance?',
  },
  {
    id: 'fact-check',
    label: 'Fact-check a claim',
    blurb: 'Put a specific assertion through a structured debate — steelman, devil\'s advocate, base rate, fragility.',
    mode: 'adjudicate',
    depth: 'standard',
    suggestedSkills: ['general_web', 'wikipedia', 'news_orchestrator'],
    examplePrompt: 'e.g. The proposed merger will clear regulatory review.',
  },
  {
    id: 'build-timeline',
    label: 'Build a timeline',
    blurb: 'Extract dated events from sources and assemble a sourced chronology.',
    mode: 'reconstruct',
    depth: 'standard',
    suggestedSkills: ['wayback', 'general_web', 'congress'],
    examplePrompt: 'e.g. The sequence of events in the 2022 plant shutdown',
  },
  {
    id: 'compare-options',
    label: 'Compare options to decide',
    blurb: 'Score choices against weighted criteria, find the winner, and name the crux that could flip it.',
    mode: 'decide',
    depth: 'standard',
    suggestedSkills: [],
    examplePrompt: 'e.g. Which vendor should we choose for the data pipeline?',
  },
  {
    id: 'monitor-topic',
    label: 'Monitor a topic',
    blurb: 'Set up a continuous watch on named sources — get alerts for high-salience items and a digest of the rest.',
    mode: 'watch',
    depth: 'auto',
    suggestedSkills: [],
    examplePrompt: 'e.g. New filings and statements from the three largest lithium producers',
  },
  {
    id: 'quick-question',
    label: 'Quick question',
    blurb: 'Get a fast, cited answer from the corpus. Best for pointed factual questions.',
    mode: 'ask',
    depth: 'quick',
    suggestedSkills: ['general_web', 'wikipedia'],
    examplePrompt: 'e.g. What does our corpus say about the 2023 supply agreement?',
  },
];

// RecipeCard: one intent recipe chip.  Compact horizontal layout — label +
// one-liner blurb + small "mode" badge — so six fit in a row without dominating
// the mode grid below.
function RecipeCard({ recipe, onSelect }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={() => onSelect(recipe)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label={`Start from recipe: ${recipe.label}`}
      style={{
        ...card,
        textAlign: 'left',
        padding: '10px 12px',
        cursor: 'pointer',
        border: hover ? '1px solid var(--primary)' : '1px solid var(--rule)',
        background: hover ? 'var(--rule-soft)' : 'var(--card)',
        transition: 'border-color .12s ease, background .12s ease',
        flex: '1 1 160px',
        minWidth: 0,
      }}>
      <div style={{
        fontSize: 12.5, fontWeight: 700, color: 'var(--ink)',
        marginBottom: 3, lineHeight: 1.3,
      }}>{recipe.label}</div>
      <div style={{
        fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.4,
        marginBottom: 6,
      }}>{recipe.blurb}</div>
      <span style={{
        display: 'inline-block', fontSize: 10, fontWeight: 700,
        lineHeight: 1, padding: '2px 6px', borderRadius: 3,
        background: 'var(--rule-soft)', color: 'var(--ink-2)',
        textTransform: 'uppercase', letterSpacing: '0.04em',
      }}>{recipe.mode}</span>
    </button>
  );
}

// RecipeRow: collapsible "Start from a recipe" strip that sits above the mode
// grid in step 1.  Collapsed by default to stay out of the way of returning
// users; newcomers can open it with one click.
function RecipeRow({ onRecipeSelect }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginBottom: 18 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          background: 'none', border: 'none', cursor: 'pointer', padding: 0,
          display: 'inline-flex', alignItems: 'center', gap: 6,
        }}>
        <span style={{
          fontSize: 11, fontWeight: 700, letterSpacing: '0.06em',
          textTransform: 'uppercase', color: 'var(--primary)',
        }}>Start from a recipe</span>
        <span aria-hidden="true" style={{
          fontSize: 10, color: 'var(--muted)',
          display: 'inline-block',
          transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
          transition: 'transform .15s ease',
          lineHeight: 1,
        }}>▶</span>
        <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
          {open ? '' : '— plain-language starting points'}
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 10 }}>
          <p style={{
            fontSize: 12, color: 'var(--muted)', margin: '0 0 10px',
            lineHeight: 1.5, maxWidth: '68ch',
          }}>
            Pick a recipe to pre-fill the wizard with a sensible mode, depth, and
            source set. You can adjust everything in the next step.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {INTENT_RECIPES.map((r) => (
              <RecipeCard key={r.id} recipe={r} onSelect={onRecipeSelect} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// A plain-language placeholder example per mode, so the question field shows the
// kind of input that fits the chosen mode rather than a generic prompt.
const MODE_PLACEHOLDER = {
  watch: 'e.g. New filings and statements from the three largest lithium producers',
  ask: 'e.g. What does our corpus say about the 2023 supply agreement?',
  investigate: 'e.g. What is driving the recent change in regional grid prices?',
  survey: 'e.g. Clinical trials of GLP-1 drugs for weight maintenance since 2020',
  reconstruct: 'e.g. The sequence of events in the 2022 plant shutdown',
  decide: 'e.g. Which vendor should we choose for the data pipeline?',
  adjudicate: 'e.g. Will the proposed merger clear regulatory review?',
};

// One short line, per mode, describing what the produced artifact contains.
// Used in the review step to set expectations in researcher language.
const MODE_OUTCOME = {
  watch: 'a digest of the most salient new items from the sources you name',
  ask: 'a cited transcript of the question and its grounded answer',
  investigate: 'a bounded, sourced report that answers the question',
  survey: 'an evidence table screening the documents, with a PRISMA flow',
  reconstruct: 'a sourced chronology of dated events',
  decide: 'a decision matrix scoring each option against your criteria',
  adjudicate: 'a verdict naming the crux of disagreement after a structured debate',
};

// Modes for which a list of source URLs is a sensible optional input. The API
// accepts source_urls today, so this is safe to send.
const URL_MODES = new Set(['watch', 'investigate', 'adjudicate']);

// Modes where research depth meaningfully changes the work done. (Decide is
// bounded by options×criteria; Watch depth = source breadth, handled separately.)
const DEPTH_MODES = new Set(['investigate', 'ask', 'survey', 'reconstruct']);

// The four depth tiers (see docs/research_depth_matrix.md). Display-layer only.
const DEPTH_TIERS = [
  { key: 'auto', label: 'Auto', time: 'recommended',
    blurb: 'Pick the right depth for this question automatically. You can override.' },
  { key: 'quick', label: 'Quick', time: '~1–3 min',
    blurb: 'A fast, grounded scan. Fewer rounds, top findings only.' },
  { key: 'standard', label: 'Standard', time: '~5–10 min',
    blurb: 'Balanced. Multi-round with coverage check. ≈ frontier deep research.' },
  { key: 'thorough', label: 'Thorough', time: '~20–60 min',
    blurb: 'Doing it properly: more rounds, adversarial refutation, triangulation.' },
  { key: 'deep', label: 'Deep', time: 'hours (budgeted)',
    blurb: 'Overnight. Recursive question-tree to exhaustion — depth frontier tools can’t reach.' },
];
const DEPTH_INVARIANT = 'Depth scales coverage and confidence, never trust — every tier stays grounded.';
const DEEP_BUDGETS = [
  { key: '30m', label: '30 min' }, { key: '1h', label: '1 hour' },
  { key: '2h', label: '2 hours' }, { key: 'overnight', label: 'Overnight' },
];

// Depth selector: four tier cards + (for Deep) a required budget. Honors the
// invariant tooltip and Adjudicate's Standard-minimum rule is enforced server-side.
function DepthSelector({ depth, setDepth, budget, setBudget }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}
        title={DEPTH_INVARIANT}>{DEPTH_INVARIANT}</div>
      <div style={{ display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
        {DEPTH_TIERS.map((t) => {
          const on = depth === t.key;
          return (
            <button key={t.key} onClick={() => setDepth(t.key)} aria-pressed={on}
              style={{ ...card, textAlign: 'left', padding: '10px 12px', cursor: 'pointer',
                border: on ? '2px solid var(--primary)' : '1px solid var(--rule)',
                background: on ? 'var(--rule-soft)' : 'var(--card)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between',
                alignItems: 'baseline', gap: 6 }}>
                <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--ink)' }}>{t.label}</span>
                <span style={{ fontSize: 10.5, color: 'var(--muted)' }}>{t.time}</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 4,
                lineHeight: 1.4 }}>{t.blurb}</div>
            </button>
          );
        })}
      </div>
      {depth === 'deep' && (
        <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8,
          flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink-2)' }}>
            Budget (required):</span>
          {DEEP_BUDGETS.map((b) => (
            <button key={b.key} onClick={() => setBudget(b.key)}
              aria-pressed={budget === b.key}
              style={{ ...card, padding: '4px 10px', cursor: 'pointer', fontSize: 12,
                border: budget === b.key ? '2px solid var(--primary)' : '1px solid var(--rule)',
                background: budget === b.key ? 'var(--rule-soft)' : 'var(--card)' }}>
              {b.label}
            </button>
          ))}
          <span style={{ fontSize: 11, color: 'var(--muted)', flexBasis: '100%' }}>
            Deep runs for up to this long, then stops. It pauses if you go off AC power.
          </span>
        </div>
      )}
    </div>
  );
}

// First-run welcome card. Shown once on the Research tab until dismissed
// (remembered in localStorage). Surfaces the §7 first-launch defaults in plain
// language: General Web is on, the no-login sources are ready, and where to add
// more. Kept brief so it doesn't overwhelm a first-time researcher.
function useFirstRun(key) {
  const [seen, setSeen] = useState(() => {
    try { return localStorage.getItem(key) === '1'; } catch (e) { return true; }
  });
  const dismiss = useCallback(() => {
    try { localStorage.setItem(key, '1'); } catch (e) { /* private mode */ }
    setSeen(true);
  }, [key]);
  return { seen, dismiss };
}

function FirstRunCard({ onDismiss }) {
  return (
    <div style={{ ...card, padding: '18px 20px', marginBottom: GAP,
      borderLeft: '3px solid var(--primary)', position: 'relative' }}>
      <button onClick={onDismiss} aria-label="Dismiss welcome"
        style={{ position: 'absolute', top: 12, right: 14, background: 'none',
          border: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--muted)',
          lineHeight: 1, padding: 2 }}>×</button>
      <div style={{ fontFamily: 'var(--serif)', fontSize: 16, fontWeight: 700,
        color: 'var(--ink)', marginBottom: 6, paddingRight: 24 }}>
        Welcome — you're ready to research
      </div>
      <div style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.6,
        marginBottom: 10, maxWidth: '70ch' }}>
        Lighthouse runs on your own hardware. General web search is on by default,
        and many trusted sources — Wikipedia, arXiv, PubMed, OpenAlex, the major
        news wires, and more — work right away with no login. Just frame a question
        below; Lighthouse recommends the right sources for it.
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.5 }}>
        Want to turn outlets on or off, or add your own feeds? Visit{' '}
        <a href="#settings" style={{ color: 'var(--primary)', fontWeight: 600 }}>
          Settings → Sources &amp; trust</a>. New to the modes?{' '}
        <a href="#info" style={{ color: 'var(--primary)', fontWeight: 600 }}>
          Read the primer</a>.
      </div>
    </div>
  );
}

// ─────────────────────────── Research (wizard) ───────────────────────────
//
// A three-step launcher driven by GET /api/modes:
//   1. Choose a mode (what you want and the artifact it produces).
//   2. Frame the question (mode-specific inputs; Decide adds options + criteria).
//   3. Review the plan in plain language, then launch.
// Launch POSTs to /api/jobs, which normalizes the mode key and validates Decide
// server-side; on success we route to #activity.

function ModeCard({ mode, selected, onSelect }) {
  return (
    <button
      onClick={() => onSelect(mode.key)}
      aria-pressed={selected}
      style={{
        ...card, textAlign: 'left', padding: '14px 16px', cursor: 'pointer',
        border: selected ? '2px solid var(--primary)' : '1px solid var(--rule)',
        background: selected ? 'var(--rule-soft)' : 'var(--card)',
      }}>
      <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 700,
        color: 'var(--ink)' }}>{mode.label}</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4,
        lineHeight: 1.45 }}>{mode.summary}</div>
      <div style={{ fontSize: 10.5, color: 'var(--muted)', marginTop: 8,
        textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Produces: {artifactLabel(mode.artifact_type)}
      </div>
    </button>
  );
}

// Visible "Step N of 3" progress indicator with labelled dots.
function WizardSteps({ step }) {
  const labels = ['Choose', 'Frame', 'Review'];
  return (
    <div style={{ marginBottom: GAP }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.06em',
        textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 8 }}>
        Step {step} of 3
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        {labels.map((label, i) => {
          const n = i + 1;
          const done = n < step;
          const here = n === step;
          return (
            <div key={label} style={{ display: 'flex', alignItems: 'center',
              gap: 8, flex: 1 }}>
              <span aria-hidden="true" style={{
                width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 700,
                background: here || done ? 'var(--primary)' : 'var(--rule-soft)',
                color: here || done ? '#fff' : 'var(--muted)',
                border: '1px solid ' + (here || done ? 'var(--primary)' : 'var(--rule)'),
              }}>{n}</span>
              <span style={{ fontSize: 12, fontWeight: here ? 700 : 500,
                color: here ? 'var(--ink)' : 'var(--muted)' }}>{label}</span>
              {n < 3 && <span aria-hidden="true" style={{ flex: 1, height: 1,
                background: 'var(--rule)' }} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CriteriaEditor({ criteria, setCriteria }) {
  const update = (i, field, val) => {
    const next = criteria.slice();
    next[i] = { ...next[i], [field]: val };
    setCriteria(next);
  };
  const add = () => setCriteria([...criteria, { label: '', weight: 1.0 }]);
  const remove = (i) => setCriteria(criteria.filter((_, j) => j !== i));
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 6,
        fontSize: 11, fontWeight: 700, letterSpacing: '0.04em',
        textTransform: 'uppercase', color: 'var(--muted)' }}>
        <span style={{ flex: 1 }}>Criterion</span>
        <span style={{ width: 80 }}>Weight</span>
        <span style={{ width: 30 }} />
      </div>
      {criteria.map((c, i) => (
        <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
          <input value={c.label} placeholder={i === 0 ? 'e.g. Cost' : 'criterion'}
            onChange={(e) => update(i, 'label', e.target.value)}
            style={{ flex: 1, padding: '6px 9px', border: '1px solid var(--rule)',
              borderRadius: 6, fontSize: 13 }} />
          <input type="number" step="0.1" min="0" value={c.weight}
            aria-label="weight"
            onChange={(e) => update(i, 'weight', parseFloat(e.target.value) || 0)}
            style={{ width: 80, padding: '6px 9px', border: '1px solid var(--rule)',
              borderRadius: 6, fontSize: 13 }} />
          <Btn kind="ghost" onClick={() => remove(i)} aria-label="remove criterion">×</Btn>
        </div>
      ))}
      <Btn kind="ghost" onClick={add}>+ Add criterion</Btn>
      <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 8,
        lineHeight: 1.5 }}>
        Weight is each criterion's relative importance — a criterion weighted 2
        counts twice as much as one weighted 1. Score each option 0 to 10 later;
        higher is better.
      </div>
    </div>
  );
}

// Field label + optional helper text, used throughout the framing step.
function WizardField({ label, hint, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink-2)',
        display: 'block', marginBottom: hint ? 2 : 6 }}>{label}</label>
      {hint && <div style={{ fontSize: 11.5, color: 'var(--muted)',
        marginBottom: 6, lineHeight: 1.45 }}>{hint}</div>}
      {children}
    </div>
  );
}

// ── Source Picker ──────────────────────────────────────────────────────────
//
// Fetches /api/sources and /api/recommend-sources?q=&mode=&depth=, renders
// categorized checkboxes with recommendation reasons and tier/grade badges.
// Pre-checks recommended skill_ids and enabled_by_default sources.

// Small pill badge used for tier, grade, community, and role labels.
function SkillBadge({ label, color }) {
  return (
    <span style={{
      display: 'inline-block', fontSize: 10, fontWeight: 700,
      lineHeight: 1, padding: '2px 6px', borderRadius: 3,
      background: color || 'var(--rule-soft)', color: 'var(--ink-2)',
      textTransform: 'uppercase', letterSpacing: '0.04em', marginRight: 4,
    }}>{label}</span>
  );
}

const TIER_COLOR = { A: '#e8f5e9', B: '#fff3e0', C: '#fce4ec' };
const GRADE_COLOR = { A: '#c8e6c9', B: '#ffe0b2', C: '#f8bbd0' };

// Plain-language source badges. The backend speaks in tiers (A/B/C fetch path)
// and grades (A/B/C evidence quality); researchers don't. Translate to words
// that say what the badge *means* for trust, not an internal code.
//   tier A  → "official source"  (first-party API / clean fetch)
//   tier B  → "web source"        (rendered/extracted web)
//   tier C  → "needs approval"    (fingerprint fallback, allowlisted)
//   grade A → "high quality"      grade B → "standard"  grade C → "use with care"
const TIER_PLAIN = { A: 'official source', B: 'web source', C: 'needs approval' };
const GRADE_PLAIN = { A: 'high quality', B: 'standard', C: 'use with care' };
// authority values from the manifest, surfaced verbatim-ish in plain words.
const AUTHORITY_PLAIN = {
  peer_reviewed: 'peer-reviewed',
  wire_service: 'wire service',
  public_broadcaster: 'public broadcaster',
  investigative_nonprofit: 'investigative nonprofit',
  newspaper: 'newspaper',
  government: 'government data',
  official: 'official data',
};
function authorityPlain(a) {
  if (!a) return null;
  return AUTHORITY_PLAIN[a] || a.replace(/_/g, ' ');
}

function SourcePicker({ topic, mode, depth, selectedSkills, setSelectedSkills }) {
  const [sources, setSources] = useState([]);
  const [recMap, setRecMap] = useState({});   // skill_id -> {score, reason, role}
  const [loadingSources, setLoadingSources] = useState(false);
  const [sourcesError, setSourcesError] = useState(null);

  // Fetch both endpoints whenever topic/mode/depth change.
  useEffect(() => {
    let live = true;
    setLoadingSources(true);
    setSourcesError(null);

    const sourcesFetch = apiGet('/api/sources').catch(() => ({ sources: [] }));
    const recQ = encodeURIComponent(topic || '');
    const recFetch = apiGet(
      `/api/recommend-sources?q=${recQ}&mode=${encodeURIComponent(mode || '')}&depth=${encodeURIComponent(depth || '')}`
    ).catch(() => ({ recommended: [] }));

    Promise.all([sourcesFetch, recFetch]).then(([sData, rData]) => {
      if (!live) return;
      const allSources = Array.isArray(sData && sData.sources) ? sData.sources : [];
      const recs = Array.isArray(rData && rData.recommended) ? rData.recommended : [];

      // Build recommendation lookup.
      const rm = {};
      recs.forEach((r) => { if (r.skill_id) rm[r.skill_id] = r; });
      setRecMap(rm);
      setSources(allSources);

      // Pre-select: recommended skill_ids + enabled_by_default, deduplicated.
      const preSelected = new Set();
      recs.forEach((r) => { if (r.skill_id) preSelected.add(r.skill_id); });
      allSources.forEach((s) => { if (s.enabled_by_default) preSelected.add(s.id); });
      // Only update selection if this is the first load (selectedSkills is empty).
      setSelectedSkills((prev) => {
        if (prev.length > 0) return prev;
        return Array.from(preSelected);
      });
    }).catch(() => {
      if (live) setSourcesError('Could not load sources. You can still launch.');
    }).finally(() => {
      if (live) setLoadingSources(false);
    });

    return () => { live = false; };
  }, [topic, mode, depth]);

  function toggleSkill(id) {
    setSelectedSkills((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  // Group sources by category.
  const grouped = {};
  sources.forEach((s) => {
    const cat = s.category || 'Other';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(s);
  });
  const categories = Object.keys(grouped).sort();

  if (loadingSources) {
    return (
      <div style={{ fontSize: 12.5, color: 'var(--muted)', padding: '6px 0' }}>
        Loading sources…
      </div>
    );
  }

  if (sourcesError) {
    return (
      <div style={{ fontSize: 12.5, color: 'var(--muted)', padding: '6px 0' }}>
        {sourcesError}
      </div>
    );
  }

  if (sources.length === 0) {
    return (
      <div style={{ fontSize: 12.5, color: 'var(--muted)', padding: '8px 0',
        fontStyle: 'italic' }}>
        No sources configured. The run will use default corpus access.
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 10,
        lineHeight: 1.45 }}>
        Pre-checked sources are recommended for this question and mode.
        Add or remove sources — the run uses whatever is checked.
      </div>

      {categories.map((cat) => (
        <div key={cat} style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.06em', color: 'var(--muted)', marginBottom: 6,
            paddingBottom: 3, borderBottom: '1px solid var(--rule-soft)' }}>
            {cat}
          </div>
          {grouped[cat].map((src) => {
            const checked = selectedSkills.includes(src.id);
            const rec = recMap[src.id];
            return (
              <label key={src.id} style={{ display: 'flex', alignItems: 'flex-start',
                gap: 8, padding: '6px 0', cursor: 'pointer',
                borderBottom: '1px solid var(--rule-soft)' }}>
                <input type="checkbox" checked={checked}
                  onChange={() => toggleSkill(src.id)}
                  style={{ marginTop: 2, flexShrink: 0, accentColor: 'var(--primary)' }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center',
                    flexWrap: 'wrap', gap: 4, marginBottom: 2 }}>
                    <span style={{ fontSize: 13, fontWeight: 600,
                      color: 'var(--ink)' }}>{src.name}</span>
                    {authorityPlain(src.authority) && (
                      <SkillBadge label={authorityPlain(src.authority)}
                        color="#e8f5e9" />
                    )}
                    {src.tier && TIER_PLAIN[src.tier] && (
                      <SkillBadge label={TIER_PLAIN[src.tier]}
                        color={TIER_COLOR[src.tier] || 'var(--rule-soft)'} />
                    )}
                    {src.default_grade && src.default_grade !== 'A' && GRADE_PLAIN[src.default_grade] && (
                      <SkillBadge label={GRADE_PLAIN[src.default_grade]}
                        color={GRADE_COLOR[src.default_grade] || 'var(--rule-soft)'} />
                    )}
                    {src.community && (
                      <SkillBadge label="community-contributed" color="#f3e5f5" />
                    )}
                    {rec && rec.role && (
                      <SkillBadge label={rec.role.replace(/_/g, ' ')}
                        color="#e3f2fd" />
                    )}
                  </div>
                  {src.description && (
                    <div style={{ fontSize: 11.5, color: 'var(--muted)',
                      lineHeight: 1.4 }}>{src.description}</div>
                  )}
                  {rec && rec.reason && (
                    <div style={{ fontSize: 11, color: 'var(--primary)',
                      marginTop: 2, lineHeight: 1.35 }}>
                      Recommended: {rec.reason}
                    </div>
                  )}
                </div>
              </label>
            );
          })}
        </div>
      ))}

      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
        {selectedSkills.length} source{selectedSkills.length === 1 ? '' : 's'} selected
      </div>
    </div>
  );
}

function ResearchPage({ toast }) {
  const { data, loading, error } = useApi('/api/modes', { pollMs: 0 });
  const [step, setStep] = useState(1);
  const [selected, setSelected] = useState(null);
  const [topic, setTopic] = useState('');
  const [options, setOptions] = useState(['', '']);
  const [criteria, setCriteria] = useState([{ label: '', weight: 1.0 }]);
  const [urls, setUrls] = useState('');
  const [depth, setDepth] = useState('auto');
  const [budget, setBudget] = useState('1h');
  const [plan, setPlan] = useState([]);
  const [busy, setBusy] = useState(false);
  const [selectedSkills, setSelectedSkills] = useState([]);
  const firstRun = useFirstRun('lh-seen-research-intro');

  const modes = (data && Array.isArray(data.modes)) ? data.modes : [];
  const sel = modes.find((m) => m.key === selected) || null;
  const isDecide = sel && sel.key === 'decide';
  const wantsUrls = sel && URL_MODES.has(sel.key);
  const wantsDepth = sel && DEPTH_MODES.has(sel.key);

  const cleanOptions = options.map((o) => o.trim()).filter(Boolean);
  const cleanCriteria = criteria.filter((c) => c.label.trim() && c.weight > 0);
  const cleanUrls = urls.split(/[\n,]+/).map((u) => u.trim()).filter(Boolean);

  function reset() {
    setStep(1); setSelected(null); setTopic('');
    setOptions(['', '']); setCriteria([{ label: '', weight: 1.0 }]); setUrls('');
    setDepth('auto'); setBudget('1h'); setPlan([]); setSelectedSkills([]);
  }

  function chooseMode(key) {
    setSelected(key);
    setStep(2);
  }

  // Recipe selection: pre-fill mode + depth + suggestedSkills, then jump to
  // step 2 so the user lands on the frame step with sensible defaults already
  // set.  The SourcePicker in step 2 will further pre-check recommended sources
  // on top of these; the user can change anything before launching.
  function applyRecipe(recipe) {
    setSelected(recipe.mode);
    if (recipe.depth && recipe.depth !== 'auto') {
      setDepth(recipe.depth);
    } else {
      setDepth('auto');
    }
    // Pre-seed the skill selection with the recipe's suggested sources.
    // SourcePicker's useEffect will only overwrite this if selectedSkills is
    // empty (prev.length > 0 guard), so our pre-seeds survive the fetch.
    if (recipe.suggestedSkills && recipe.suggestedSkills.length > 0) {
      setSelectedSkills(recipe.suggestedSkills);
    }
    // Pre-fill the topic placeholder text so the user sees a concrete example.
    // We don't actually set the topic value (that would require editing to
    // clear), but we store the example so the placeholder is recipe-aware.
    // The input already shows MODE_PLACEHOLDER[mode] by default; since we jump
    // straight to step 2 the correct placeholder will render.
    setStep(2);
  }

  // Per-step validation. Returns an error string, or null when the step is good.
  function frameError() {
    if (!topic.trim()) return 'Enter a question or topic to continue.';
    if (isDecide) {
      if (cleanOptions.length < 2) return 'Add at least two options to compare.';
      if (cleanCriteria.length < 1) return 'Add at least one weighted criterion.';
    }
    return null;
  }

  async function goReview() {
    const err = frameError();
    if (err) { toast.show(err, 'error'); return; }
    // For research modes, classify the question to (a) resolve Auto depth and
    // (b) fetch the research plan (load-bearing sub-questions) to show before launch.
    if (wantsDepth) {
      try {
        const c = await apiGet(`/api/classify?q=${encodeURIComponent(topic.trim())}`);
        setPlan(Array.isArray(c.sub_questions) ? c.sub_questions : []);
        if (depth === 'auto') {
          const t = c.suggested_tier || 'standard';
          setDepth(t);
          const label = (DEPTH_TIERS.find((x) => x.key === t) || {}).label || t;
          toast.show(`Auto chose ${label} depth (${(c.question_type || '').replace(/_/g, ' ')}).`, 'info');
        }
      } catch (e) {
        if (depth === 'auto') setDepth('standard');
        setPlan([]);
      }
    }
    setStep(3);
  }

  async function launch() {
    if (!sel) return;
    setBusy(true);
    try {
      const body = { mode: selected, topic: topic.trim() };
      if (isDecide) {
        body.options = cleanOptions;
        body.criteria = cleanCriteria;
      }
      if (wantsDepth) {
        body.depth = depth;
        if (depth === 'deep') body.budget = budget;
      }
      if (wantsUrls && cleanUrls.length) body.source_urls = cleanUrls;
      if (selectedSkills.length) body.selected_skills = selectedSkills;
      const r = await apiPost('/api/jobs', body);
      toast.show(`Started ${sel.label}. Track it in Activity (run ${r.id}).`, 'success');
      reset();
      window.location.hash = 'activity';
    } catch (err) {
      toast.show(err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  // Plain-language summary shown on the review step (built as one string so the
  // sentence reads naturally and stays easy to translate).
  let reviewSentence = '';
  if (sel) {
    const outcome = MODE_OUTCOME[sel.key] || 'a research artifact';
    const decideTail = isDecide
      ? `, comparing ${cleanOptions.length} option${cleanOptions.length === 1 ? '' : 's'} `
        + `across ${cleanCriteria.length} criteri${cleanCriteria.length === 1 ? 'on' : 'a'}`
      : '';
    const depthTail = wantsDepth
      ? ` at ${(DEPTH_TIERS.find((t) => t.key === depth) || {}).label || depth} depth`
        + (depth === 'deep' ? ` (budget: ${(DEEP_BUDGETS.find((b) => b.key === budget) || {}).label || budget})` : '')
      : '';
    reviewSentence = `You are about to run ${sel.label} on "${topic.trim()}"${depthTail}. `
      + `This produces ${outcome}${decideTail}.`;
  }

  return (
    <div style={{ padding: PAD, maxWidth: 1100 }}>
      <PageHeader title="Research"
        subtitle="Set up a research run in three steps: choose what you want, frame the question, then launch." />
      {loading && !data && <Loading />}
      {error && <ErrorBox message={error} />}

      {!loading && !error && (
        <React.Fragment>
          {step === 1 && !firstRun.seen && (
            <FirstRunCard onDismiss={firstRun.dismiss} />
          )}
          <WizardSteps step={step} />

          {/* ── Step 1 — Choose what you want ── */}
          {step === 1 && (
            <div>
              {/* Recipe row — collapsible, secondary; sits above the mode grid */}
              <RecipeRow onRecipeSelect={applyRecipe} />

              <p style={{ fontSize: 13, color: 'var(--muted)', margin: '0 0 14px',
                lineHeight: 1.5, maxWidth: '60ch' }}>
                Each mode produces one kind of research artifact. Pick the one
                that matches the question you are asking.
              </p>
              <div style={{ display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))',
                gap: 12 }}>
                {modes.map((m) => (
                  <ModeCard key={m.key} mode={m} selected={m.key === selected}
                    onSelect={chooseMode} />
                ))}
              </div>
            </div>
          )}

          {/* ── Step 2 — Frame your research ── */}
          {step === 2 && sel && (
            <div style={{ ...card, padding: '20px 22px' }}>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
                color: 'var(--ink)', marginBottom: 4 }}>Frame your {sel.label} run</div>
              <div style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 18 }}>
                This run will produce {MODE_OUTCOME[sel.key] || 'a research artifact'}.
              </div>

              <WizardField
                label={isDecide ? 'What are you deciding?' : 'Your question or topic'}
                hint={isDecide
                  ? 'State the decision in one line. You will list the options below.'
                  : 'State it as a clear, specific question or topic.'}>
                <input value={topic} onChange={(e) => setTopic(e.target.value)}
                  placeholder={MODE_PLACEHOLDER[sel.key] || 'What do you want to know?'}
                  style={{ width: '100%', padding: '9px 11px',
                    border: '1px solid var(--rule)', borderRadius: 7, fontSize: 14,
                    boxSizing: 'border-box' }} />
              </WizardField>

              {isDecide && (
                <React.Fragment>
                  <WizardField label="Options to compare"
                    hint="List at least two choices. Each becomes a row in the decision matrix.">
                    {options.map((o, i) => (
                      <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                        <input value={o} placeholder={`Option ${i + 1}`}
                          onChange={(e) => {
                            const next = options.slice(); next[i] = e.target.value;
                            setOptions(next);
                          }}
                          style={{ flex: 1, padding: '6px 9px',
                            border: '1px solid var(--rule)', borderRadius: 6, fontSize: 13 }} />
                        {options.length > 2 && (
                          <Btn kind="ghost"
                            onClick={() => setOptions(options.filter((_, j) => j !== i))}
                            aria-label="remove option">×</Btn>
                        )}
                      </div>
                    ))}
                    <Btn kind="ghost" onClick={() => setOptions([...options, ''])}>+ Add option</Btn>
                  </WizardField>

                  <WizardField label="Weighted criteria"
                    hint="The factors that matter for this decision. Each becomes a column.">
                    <CriteriaEditor criteria={criteria} setCriteria={setCriteria} />
                  </WizardField>
                </React.Fragment>
              )}

              {wantsUrls && (
                <WizardField label="Source URLs (optional)"
                  hint="Paste one URL per line to point the run at specific sources. Leave blank to use the corpus.">
                  <textarea value={urls} onChange={(e) => setUrls(e.target.value)}
                    rows={3} placeholder={'https://example.com/report\nhttps://example.com/filing'}
                    style={{ width: '100%', padding: '8px 11px',
                      border: '1px solid var(--rule)', borderRadius: 7, fontSize: 13,
                      boxSizing: 'border-box', fontFamily: 'var(--mono, monospace)',
                      resize: 'vertical' }} />
                </WizardField>
              )}

              {wantsDepth && (
                <WizardField label="Research depth"
                  hint="How far the run goes. Quick for a fast answer; Deep runs overnight on a recursive question-tree.">
                  <DepthSelector depth={depth} setDepth={setDepth}
                    budget={budget} setBudget={setBudget} />
                </WizardField>
              )}

              <WizardField label="Sources"
                hint="Select the sources the run should draw on. Recommended sources are pre-checked based on your question and mode.">
                <SourcePicker
                  topic={topic}
                  mode={selected}
                  depth={depth}
                  selectedSkills={selectedSkills}
                  setSelectedSkills={setSelectedSkills} />
              </WizardField>

              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <Btn kind="ghost" onClick={() => setStep(1)}>Back</Btn>
                <Btn onClick={goReview}>Next: review</Btn>
              </div>
            </div>
          )}

          {/* ── Step 3 — Review & launch ── */}
          {step === 3 && sel && (
            <div style={{ ...card, padding: '20px 22px' }}>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
                color: 'var(--ink)', marginBottom: 14 }}>Review and launch</div>

              <p style={{ fontSize: 14, color: 'var(--ink)', lineHeight: 1.6,
                margin: '0 0 14px', maxWidth: '64ch' }}>
                {reviewSentence}
              </p>

              <div style={{ background: 'var(--rule-soft)', borderRadius: 8,
                padding: '12px 14px', marginBottom: 16 }}>
                <Row k="Mode" v={sel.label} />
                <Row k="Artifact" v={artifactLabel(sel.artifact_type)} />
                <Row k="Question" v={topic.trim()} />
                {isDecide && <Row k="Options" v={cleanOptions.join(', ')} />}
                {isDecide && <Row k="Criteria"
                  v={cleanCriteria.map((c) => `${c.label} (×${c.weight})`).join(', ')} />}
                {wantsUrls && cleanUrls.length > 0 &&
                  <Row k="Source URLs" v={`${cleanUrls.length} URL${cleanUrls.length === 1 ? '' : 's'}`} />}
                {wantsDepth && depth !== 'auto' &&
                  <Row k="Depth" v={(DEPTH_TIERS.find((t) => t.key === depth) || {}).label || depth} />}
                <Row k="Research sources"
                  v={selectedSkills.length
                    ? `${selectedSkills.length} source${selectedSkills.length === 1 ? '' : 's'} selected`
                    : 'Default corpus access'} />
              </div>

              {wantsDepth && plan.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--ink-2)',
                    textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
                    Research plan
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
                    The run will work through these load-bearing sub-questions; each
                    is answered with cited evidence or recorded as a known-unknown.
                  </div>
                  <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13,
                    color: 'var(--ink-2)', lineHeight: 1.6 }}>
                    {plan.map((q, i) => <li key={i}>{q}</li>)}
                  </ol>
                </div>
              )}

              <p style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.5,
                margin: '0 0 16px', maxWidth: '64ch' }}>
                After you launch, the run appears in <strong>Activity</strong> while
                it works and lands in <strong>Library</strong> for review when it is
                ready.
              </p>

              <div style={{ display: 'flex', gap: 8 }}>
                <Btn kind="ghost" onClick={() => setStep(2)}>Back</Btn>
                <Btn onClick={launch} loading={busy}>
                  {busy ? 'Launching' : `Launch ${sel.label}`}
                </Btn>
              </div>
            </div>
          )}
        </React.Fragment>
      )}
    </div>
  );
}

// ──────────────────────────────── Library ─────────────────────────────────
//
// All artifacts (drafts awaiting review + published) filtered by type/status,
// with a viewer that switches on artifact_type and an export button.

function MatrixView({ body }) {
  if (!body || !body.cells) return null;
  const options = (body.options || []).map((o) => o.label || o);
  const criteria = (body.criteria || []).map((c) => c.label || c);
  const cell = (opt, crit) => {
    const c = body.cells.find((x) => x.option === opt && x.criterion === crit);
    return c ? c.score : '';
  };
  return (
    <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
      <thead><tr>
        <th style={{ textAlign: 'left', padding: '6px 10px' }}></th>
        {criteria.map((c) => <th key={c} style={{ padding: '6px 10px' }}>{c}</th>)}
        <th style={{ padding: '6px 10px' }}>Total</th>
      </tr></thead>
      <tbody>
        {options.map((o) => (
          <tr key={o} style={{ borderTop: '1px solid var(--rule-soft)' }}>
            <td style={{ padding: '6px 10px', fontWeight: 700 }}>{o}</td>
            {criteria.map((c) => <td key={c} style={{ padding: '6px 10px', textAlign: 'center' }}>{cell(o, c)}</td>)}
            <td style={{ padding: '6px 10px', textAlign: 'center', fontWeight: 700 }}>
              {body.totals && body.totals[o] != null ? body.totals[o] : ''}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TableView({ body }) {
  if (!body || !body.rows) return null;
  const attrs = (body.attributes || []).map((a) => a.label || a);
  return (
    <div>
      {body.prisma && (
        <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
          PRISMA — identified {body.prisma.identified}, included {body.prisma.included},
          excluded {body.prisma.excluded}
        </div>
      )}
      <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
        <thead><tr>
          <th style={{ textAlign: 'left', padding: '6px 10px' }}>Document</th>
          {attrs.map((a) => <th key={a} style={{ textAlign: 'left', padding: '6px 10px' }}>{a}</th>)}
        </tr></thead>
        <tbody>
          {body.rows.map((row) => (
            <tr key={row.doc_id} style={{ borderTop: '1px solid var(--rule-soft)' }}>
              <td style={{ padding: '6px 10px', fontWeight: 600 }}>{row.title || row.doc_id}</td>
              {attrs.map((a) => {
                const c = (row.cells || []).find((x) => x.attribute === a);
                return <td key={a} style={{ padding: '6px 10px' }}>{c ? c.value : ''}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TimelineView({ body }) {
  if (!body || !body.events) return null;
  return (
    <div>
      {body.events.map((e) => (
        <div key={e.event_id} style={{ display: 'flex', gap: 12, padding: '8px 0',
          borderTop: '1px solid var(--rule-soft)' }}>
          <div style={{ width: 110, fontFamily: 'var(--mono, monospace)', fontSize: 12,
            color: 'var(--primary)' }}>{e.date}</div>
          <div style={{ flex: 1, fontSize: 13, color: 'var(--ink)' }}>
            {e.action}
            {e.date_conflicts && e.date_conflicts.length > 0 && (
              <span style={{ fontSize: 11, color: 'var(--coral, #bf5820)', marginLeft: 8 }}>
                (disputed; certainty {e.certainty})
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// KnownUnknowns: renders the open_questions section if present on the artifact.
// These are surfaced as a clearly-labeled "Known unknowns" block — questions the
// run identified but could not answer. They are distinct from the main content.
function KnownUnknowns({ openQuestions }) {
  if (!openQuestions || openQuestions.length === 0) return null;
  return (
    <div style={{ marginTop: 22, borderTop: '2px solid var(--rule)', paddingTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.06em', color: 'var(--muted)' }}>Known unknowns</span>
        <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 400 }}>
          — questions the run identified but could not answer
        </span>
      </div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: 'var(--ink-2)',
        lineHeight: 1.65 }}>
        {openQuestions.map((q, i) => (
          <li key={i} style={{ marginBottom: 4 }}>{q}</li>
        ))}
      </ul>
    </div>
  );
}

// Contradictions: surfaced, never hidden. A run flags claims that conflict with
// each other or with prior evidence; we render them in a clearly-labeled block so
// the reader sees the tension rather than a falsely-clean answer.
function Contradictions({ items }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ marginTop: 22, borderTop: '2px solid var(--rule)', paddingTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span aria-hidden="true" style={{ fontSize: 13, color: '#a83269' }}>⚠</span>
        <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.06em', color: '#880e4f' }}>Contradictions</span>
        <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 400 }}>
          — claims in conflict that this run did not resolve
        </span>
      </div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: 'var(--ink-2)',
        lineHeight: 1.65 }}>
        {items.map((c, i) => (
          <li key={i} style={{ marginBottom: 6 }}>
            {typeof c === 'string'
              ? c
              : (c.statement || c.summary || c.description
                  || `${c.claim_a || '?'} vs. ${c.claim_b || '?'}`)}
            {c && c.sources && c.sources.length > 0 && (
              <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 6 }}>
                ({c.sources.length} source{c.sources.length === 1 ? '' : 's'})
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// EvidenceConnections — "How the evidence connects" panel.
//
// Fetches /api/graph/draft/{id} on first expand and renders a plain-language
// view of the key people, places, and concepts the report connects.
//
// Design choices:
//   • Collapsed by default — non-intrusive, progressive disclosure.
//   • Zero jargon: no "entity", "co-occurrence", "subgraph" visible to the user.
//   • Chip list is the primary interaction; clicking a chip reveals neighbors.
//   • A compact SVG node-edge map is shown alongside when the graph has edges.
//   • Empty state: plain sentence, no error shown.

function _buildSvgLayout(nodes, edges) {
  // Simple deterministic circular layout for up to 40 nodes.
  // Returns { positions: {id: {x,y}}, r: radius }.
  const n = nodes.length;
  if (n === 0) return { positions: {}, r: 0 };
  const R = Math.min(160, Math.max(80, n * 12));
  const cx = 200, cy = 160;
  const positions = {};
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    positions[node.id] = { x: cx + R * Math.cos(angle), y: cy + R * Math.sin(angle) };
  });
  return { positions, cx, cy, R };
}

function EvidenceConnections({ artifactId }) {
  const [open, setOpen] = useState(false);
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [fetched, setFetched] = useState(false);
  const [activeChip, setActiveChip] = useState(null);

  function handleToggle() {
    const nextOpen = !open;
    setOpen(nextOpen);
    if (nextOpen && !fetched) {
      setLoading(true);
      apiGet('/api/graph/draft/' + artifactId)
        .then((d) => { setGraphData(d); setFetched(true); setLoading(false); })
        .catch(() => { setGraphData(null); setFetched(true); setLoading(false); });
    }
  }

  const hasData = graphData && graphData.entities && graphData.entities.length > 0;
  const entities = hasData ? graphData.entities : [];
  const graphNodes = (graphData && graphData.graph && graphData.graph.nodes) || [];
  const graphEdges = (graphData && graphData.graph && graphData.graph.edges) || [];

  // Find neighbors of the active chip from graph edges.
  function neighborsOf(label) {
    if (!graphData || !graphData.graph) return [];
    const nodeById = {};
    graphNodes.forEach((n) => { nodeById[n.id] = n.label; });
    // Find the id for this label.
    const matchNode = graphNodes.find(
      (n) => n.label.toLowerCase() === label.toLowerCase()
    );
    if (!matchNode) return [];
    const nbrIds = new Set();
    graphEdges.forEach((e) => {
      if (e.source === matchNode.id) nbrIds.add(e.target);
      if (e.target === matchNode.id) nbrIds.add(e.source);
    });
    return Array.from(nbrIds)
      .map((id) => nodeById[id])
      .filter(Boolean)
      .sort();
  }

  const neighbors = activeChip ? neighborsOf(activeChip) : [];

  // SVG map — only when there are edges and enough nodes.
  const showSvg = graphEdges.length > 0 && graphNodes.length >= 2;
  const { positions } = showSvg ? _buildSvgLayout(graphNodes, graphEdges) : { positions: {} };

  // Highlight the active chip's node in the SVG.
  const activeNodeId = activeChip
    ? (graphNodes.find((n) => n.label.toLowerCase() === activeChip.toLowerCase()) || {}).id
    : null;
  const connectedIds = activeNodeId
    ? new Set(
        graphEdges
          .filter((e) => e.source === activeNodeId || e.target === activeNodeId)
          .flatMap((e) => [e.source, e.target])
      )
    : new Set();

  return (
    <div style={{ marginTop: 22, borderTop: '2px solid var(--rule)', paddingTop: 14 }}>
      <button
        onClick={handleToggle}
        style={{
          background: 'none', border: 'none', padding: 0, cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
        }}
        aria-expanded={open}
      >
        <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.06em', color: 'var(--muted)' }}>
          How the evidence connects
        </span>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          — the people, places, and concepts this report links together
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--muted)',
          transform: open ? 'rotate(180deg)' : 'none', display: 'inline-block',
          transition: 'transform 0.15s' }}>
          ▾
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 12 }}>
          {loading && (
            <div style={{ fontSize: 13, color: 'var(--muted)', padding: '8px 0' }}>
              Building connection map…
            </div>
          )}
          {fetched && !loading && !hasData && (
            <div style={{ fontSize: 13, color: 'var(--muted)', padding: '4px 0' }}>
              Not enough text to map relationships yet.
            </div>
          )}
          {hasData && (
            <div>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                Click any term to see what else it connects to in this report.
              </div>
              {/* Chip list */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
                {entities.map((e) => {
                  const isActive = activeChip === e.label;
                  return (
                    <button
                      key={e.label}
                      onClick={() => setActiveChip(isActive ? null : e.label)}
                      style={{
                        border: isActive
                          ? '1.5px solid var(--primary)'
                          : '1px solid var(--rule)',
                        borderRadius: 20,
                        padding: '3px 11px',
                        fontSize: 12,
                        cursor: 'pointer',
                        background: isActive ? 'var(--rule-soft)' : 'var(--card)',
                        color: isActive ? 'var(--primary)' : 'var(--ink)',
                        fontWeight: isActive ? 600 : 400,
                      }}
                    >
                      {e.label}
                    </button>
                  );
                })}
              </div>

              {/* Neighbor panel */}
              {activeChip && (
                <div style={{ marginBottom: 14, padding: '10px 14px',
                  background: 'var(--rule-soft)', borderRadius: 6,
                  fontSize: 13, color: 'var(--ink)' }}>
                  <span style={{ fontWeight: 600 }}>{activeChip}</span>
                  {neighbors.length > 0 ? (
                    <span>
                      {' '}connects in this report to:{' '}
                      {neighbors.map((n, i) => (
                        <React.Fragment key={n}>
                          <button
                            onClick={() => setActiveChip(n)}
                            style={{
                              background: 'none', border: 'none', padding: 0,
                              cursor: 'pointer', color: 'var(--primary)',
                              fontWeight: 500, fontSize: 13, textDecoration: 'underline',
                              textDecorationStyle: 'dotted',
                            }}
                          >
                            {n}
                          </button>
                          {i < neighbors.length - 1 ? ', ' : ''}
                        </React.Fragment>
                      ))}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--muted)' }}>
                      {' '}appears in this report but has no strong connection to other terms here.
                    </span>
                  )}
                </div>
              )}

              {/* Compact SVG node-edge map */}
              {showSvg && (
                <div style={{ marginTop: 4, overflowX: 'auto' }}>
                  <svg
                    viewBox="0 0 400 320"
                    style={{ width: '100%', maxWidth: 400, height: 'auto',
                      display: 'block', margin: '0 auto' }}
                    aria-label="Connection map of key terms in this report"
                    role="img"
                  >
                    {/* Edges */}
                    {graphEdges.map((e, i) => {
                      const s = positions[e.source];
                      const t = positions[e.target];
                      if (!s || !t) return null;
                      const isHighlighted = activeNodeId &&
                        (e.source === activeNodeId || e.target === activeNodeId);
                      return (
                        <line
                          key={'e' + i}
                          x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                          stroke={isHighlighted ? 'var(--primary, #2563eb)' : 'var(--rule, #ddd)'}
                          strokeWidth={isHighlighted ? 2 : 1}
                          opacity={isHighlighted ? 0.8 : 0.5}
                        />
                      );
                    })}
                    {/* Nodes */}
                    {graphNodes.map((node) => {
                      const pos = positions[node.id];
                      if (!pos) return null;
                      const isActive = node.id === activeNodeId;
                      const isConnected = connectedIds.has(node.id);
                      const r = isActive ? 7 : isConnected ? 5 : 4;
                      return (
                        <g
                          key={node.id}
                          onClick={() => setActiveChip(
                            activeChip === node.label ? null : node.label
                          )}
                          style={{ cursor: 'pointer' }}
                          role="button"
                          aria-label={node.label}
                        >
                          <circle
                            cx={pos.x} cy={pos.y} r={r}
                            fill={isActive ? 'var(--primary, #2563eb)'
                              : isConnected ? 'var(--primary-light, #93c5fd)'
                              : 'var(--muted, #999)'}
                            opacity={0.85}
                          />
                          {(isActive || isConnected || graphNodes.length <= 15) && (
                            <text
                              x={pos.x} y={pos.y - r - 3}
                              fontSize={9} fill="var(--ink-2, #555)"
                              textAnchor="middle"
                              style={{ userSelect: 'none', pointerEvents: 'none' }}
                            >
                              {node.label.length > 18
                                ? node.label.slice(0, 17) + '…'
                                : node.label}
                            </text>
                          )}
                        </g>
                      );
                    })}
                  </svg>
                  <div style={{ fontSize: 11, color: 'var(--muted)', textAlign: 'center',
                    marginTop: 2 }}>
                    Lines show terms that appear together in the same section of this report.
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ArtifactBody({ artifact }) {
  const t = artifact.artifact_type;
  const body = artifact.body;

  // Contradictions can live on the body or top-level; surface either.
  const contradictions = (
    (body && Array.isArray(body.contradictions) && body.contradictions.length > 0
      ? body.contradictions : null) ||
    (Array.isArray(artifact.contradictions) && artifact.contradictions.length > 0
      ? artifact.contradictions : null) ||
    []
  );

  // Normalize open_questions from body.open_questions or top-level artifact.open_questions.
  const openQuestions = (
    (body && Array.isArray(body.open_questions) && body.open_questions.length > 0
      ? body.open_questions
      : null) ||
    (Array.isArray(artifact.open_questions) && artifact.open_questions.length > 0
      ? artifact.open_questions
      : null) ||
    []
  );

  if (t === 'matrix') return (
    <React.Fragment>
      <MatrixView body={body} />
      <Contradictions items={contradictions} />
      <KnownUnknowns openQuestions={openQuestions} />
      {artifact.id && <EvidenceConnections artifactId={artifact.id} />}
    </React.Fragment>
  );
  if (t === 'table') return (
    <React.Fragment>
      <TableView body={body} />
      <Contradictions items={contradictions} />
      <KnownUnknowns openQuestions={openQuestions} />
      {artifact.id && <EvidenceConnections artifactId={artifact.id} />}
    </React.Fragment>
  );
  if (t === 'timeline') return (
    <React.Fragment>
      <TimelineView body={body} />
      <Contradictions items={contradictions} />
      <KnownUnknowns openQuestions={openQuestions} />
      {artifact.id && <EvidenceConnections artifactId={artifact.id} />}
    </React.Fragment>
  );
  // report / verdict / transcript / digest → prose HTML + contradictions + known unknowns.
  return (
    <React.Fragment>
      <div dangerouslySetInnerHTML={{ __html: artifact.body_html || '<em>No content.</em>' }} />
      <Contradictions items={contradictions} />
      <KnownUnknowns openQuestions={openQuestions} />
      {artifact.id && <EvidenceConnections artifactId={artifact.id} />}
    </React.Fragment>
  );
}

const LIBRARY_FILTERS = [
  { key: '', label: 'All' },
  { key: 'report', label: 'Reports' },
  { key: 'matrix', label: 'Decisions' },
  { key: 'table', label: 'Surveys' },
  { key: 'timeline', label: 'Timelines' },
  { key: 'verdict', label: 'Verdicts' },
  { key: 'transcript', label: 'Transcripts' },
];

function LibraryPage({ toast }) {
  const [typeFilter, setTypeFilter] = useState('');
  const q = typeFilter ? `/api/library?type=${typeFilter}` : '/api/library';
  const { data, loading, error, reload } = useApi(q, { pollMs: 15000 });
  const [selId, setSelId] = useState(null);
  const [detail, setDetail] = useState(null);

  useEvents((name) => { if (name && name.indexOf('draft.') === 0) reload(); });

  useEffect(() => {
    if (selId == null) { setDetail(null); return; }
    let live = true;
    apiGet(`/api/library/${selId}`).then((d) => { if (live) setDetail(d); })
      .catch((e) => { if (live) toast.show(e.message, 'error'); });
    return () => { live = false; };
  }, [selId]);

  const artifacts = (data && Array.isArray(data.artifacts)) ? data.artifacts : [];

  function exportArtifact(fmt) {
    if (!selId) return;
    window.open(`/api/library/${selId}/export?format=${fmt}`, '_blank');
  }

  return (
    <div style={{ padding: PAD, maxWidth: 1200 }}>
      <PageHeader title="Library"
        subtitle="Completed research outputs you can read, review, and export. Select one to open it." />

      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap',
        alignItems: 'center' }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.04em',
          textTransform: 'uppercase', color: 'var(--muted)', marginRight: 4 }}>
          Filter by type
        </span>
        {LIBRARY_FILTERS.map((f) => (
          <Btn key={f.key} kind={f.key === typeFilter ? 'primary' : 'ghost'} size="sm"
            onClick={() => { setTypeFilter(f.key); setSelId(null); }}>{f.label}</Btn>
        ))}
      </div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: GAP }}>
        {artifacts.length} artifact{artifacts.length === 1 ? '' : 's'} shown
      </div>

      {loading && !data && <Loading />}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!loading && !error && artifacts.length === 0 && (
        <EmptyState title="No completed research yet"
          hint="Finished runs land here as reviewable artifacts — reports, decision matrices, evidence tables, timelines, and more. Start a run from the Research tab to fill this shelf."
          cta={<Btn onClick={() => { window.location.hash = 'research'; }}>Go to Research</Btn>} />
      )}

      {artifacts.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: selId ? '360px 1fr' : '1fr',
          gap: GAP }}>
          <div>
            {artifacts.map((a) => (
              <button key={a.id} onClick={() => setSelId(a.id)}
                style={{ ...card, display: 'block', width: '100%', textAlign: 'left',
                  padding: '12px 14px', marginBottom: 8, cursor: 'pointer',
                  border: a.id === selId ? '2px solid var(--primary)' : '1px solid var(--rule)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--ink)' }}>{a.title}</span>
                  <StatusPill status={a.status} />
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  {artifactLabel(a.artifact_type)} · {a.created_at}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8,
                  marginTop: 8, flexWrap: 'wrap' }}>
                  {(a.wep_phrase || a.wep_band) && (
                    <window.ConfidencePill phrase={a.wep_phrase || a.wep_band}
                      band={a.confidence} />
                  )}
                  {a.source_count != null && (
                    <span style={{ fontSize: 11, color: 'var(--muted)',
                      display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      <span aria-hidden="true">◆</span>
                      {a.source_count} source{a.source_count === 1 ? '' : 's'}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>

          {selId && detail && (
            <div style={{ ...card, padding: '20px 22px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between',
                alignItems: 'flex-start', marginBottom: 14, gap: 12 }}>
                <div>
                  <div style={{ fontFamily: 'var(--serif)', fontSize: 18, fontWeight: 700,
                    color: 'var(--ink)' }}>{detail.title}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8,
                    marginTop: 5, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                      {artifactLabel(detail.artifact_type)}
                    </span>
                    {(detail.wep_phrase || detail.wep_band) && (
                      <window.ConfidencePill phrase={detail.wep_phrase || detail.wep_band}
                        band={detail.confidence} />
                    )}
                    {detail.source_count != null && (
                      <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                        · {detail.source_count} source{detail.source_count === 1 ? '' : 's'}
                      </span>
                    )}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, flexShrink: 0,
                  alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>Export</span>
                  <Btn kind="ghost" size="sm" onClick={() => exportArtifact('md')}>Markdown</Btn>
                  <Btn kind="ghost" size="sm" onClick={() => exportArtifact('csv')}>CSV</Btn>
                  <Btn kind="ghost" size="sm" onClick={() => exportArtifact('json')}>JSON</Btn>
                </div>
              </div>
              <ArtifactBody artifact={detail} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────── Activity ────────────────────────────────
//
// In-flight + recent runs (job.progress / job.status SSE) plus a tail of the
// audit log, so the user can watch a run move queued → running → review.

// Raw job status → plain words for a researcher who has not seen the internals.
const STATUS_PLAIN = {
  queued: 'Waiting to start',
  running: 'In progress',
  paused: 'Paused',
  review: 'Ready for review in Library',
  done: 'Done',
  completed: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

function statusPlain(s) {
  return STATUS_PLAIN[(s || '').toString()] || (s || 'Unknown');
}

function ActivityPage({ toast }) {
  const { data, loading, error, reload } = useApi('/api/jobs', { pollMs: 5000 });
  const { data: auditData } = useApi('/api/audit?limit=30', { pollMs: 15000 });
  const [watchId, setWatchId] = useState(null);
  // Only reload on job lifecycle events, not the high-frequency job.step stream.
  useEvents((name) => { if (name && name.indexOf('job.') === 0 && name !== 'job.step') reload(); });

  // Pause / resume / cancel a run via the jobs control endpoints.
  async function control(jobId, action, label) {
    try {
      await apiPost(`/api/jobs/${jobId}/${action}`, {});
      toast.show(`Run ${jobId} ${label}.`, 'info');
      reload();
    } catch (err) {
      toast.show(err.message || `Could not ${action} run.`, 'error');
    }
  }

  const jobs = (data && Array.isArray(data.jobs)) ? data.jobs : [];
  const active = jobs.filter((j) => ['queued', 'running', 'paused', 'review'].includes(j.status));
  const events = (auditData && Array.isArray(auditData.events)) ? auditData.events : [];
  const noRuns = !loading && !error && jobs.length === 0;

  return (
    <div style={{ padding: PAD, maxWidth: 1100 }}>
      <PageHeader title="Activity"
        subtitle="Watch your research runs as they progress, and follow the audit trail of what happened." />
      {loading && !data && <Loading />}
      {error && <ErrorBox message={error} onRetry={reload} />}

      {noRuns && (
        <EmptyState title="No runs yet"
          hint="This is where you watch research runs move from waiting, to in progress, to ready for review. Start one from the Research tab and it will appear here."
          cta={<Btn onClick={() => { window.location.hash = 'research'; }}>Go to Research</Btn>} />
      )}

      {!noRuns && (
        <React.Fragment>
          <div style={{ ...card, padding: '14px 16px', marginBottom: GAP }}>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 700,
              color: 'var(--ink)', marginBottom: 2 }}>Active runs</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
              Runs that are waiting, working, or ready for review. Completed runs
              move to the Library.
            </div>
            {active.length === 0 && (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                Nothing running right now. Recent finished runs are in the Library.
              </div>
            )}
            {active.map((j) => {
              const meta = j.metadata || {};
              const pct = Math.round((meta.progress || 0) * 100);
              const canPause = j.status === 'running';
              const canResume = j.status === 'paused';
              const canCancel = ['queued', 'running', 'paused'].includes(j.status);
              return (
                <div key={j.id} style={{ padding: '10px 0',
                  borderTop: '1px solid var(--rule-soft)' }}>
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                    <span style={{ flex: 1, fontSize: 13, color: 'var(--ink)' }}>
                      {meta.topic || j.id}</span>
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                      {window.modeLabel ? window.modeLabel(j.mode) : j.mode}</span>
                    <span style={{ fontSize: 12, color: 'var(--ink-2)', minWidth: 150,
                      textAlign: 'right' }}>{statusPlain(j.status)}</span>
                    <span style={{ width: 44, textAlign: 'right', fontSize: 12,
                      color: 'var(--muted)' }}>{pct}%</span>
                  </div>
                  {/* Progress bar — what's happening, at a glance. */}
                  <div style={{ marginTop: 8 }}>
                    <window.Bar value={pct} max={100}
                      color={j.status === 'paused' ? 'var(--muted)' : 'var(--primary)'} />
                  </div>
                  {/* Watch live + pause / resume / cancel — visible, not hidden. */}
                  <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                    <Btn kind="ghost" size="sm" icon="◎"
                      onClick={() => setWatchId(j.id)}
                      aria-label={`Watch live: ${meta.topic || j.id}`}>Watch live</Btn>
                  </div>
                  {(canPause || canResume || canCancel) && (
                    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                      {canPause && (
                        <Btn kind="ghost" size="sm"
                          onClick={() => control(j.id, 'pause', 'paused')}>Pause</Btn>
                      )}
                      {canResume && (
                        <Btn kind="ghost" size="sm"
                          onClick={() => control(j.id, 'resume', 'resumed')}>Resume</Btn>
                      )}
                      {canCancel && (
                        <Btn kind="danger" size="sm"
                          onClick={() => control(j.id, 'cancel', 'cancelled')}>Cancel</Btn>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div style={{ ...card, padding: '14px 16px' }}>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 700,
              color: 'var(--ink)', marginBottom: 2 }}>Audit trail</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
              A tamper-evident, time-ordered record of every action the system
              took — useful for verifying how a result was produced.
            </div>
            {events.length === 0 && (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                No recorded actions yet.
              </div>
            )}
            {events.map((e, i) => (
              <div key={i} style={{ display: 'flex', gap: 10, padding: '5px 0',
                borderTop: i ? '1px solid var(--rule-soft)' : 'none', fontSize: 12 }}>
                <span style={{ color: 'var(--muted)', fontFamily: 'var(--mono, monospace)',
                  minWidth: 150 }}>{e.created_at || e.ts || ''}</span>
                <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{e.event_type}</span>
                <span style={{ color: 'var(--muted)', flex: 1, overflow: 'hidden',
                  textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.actor || ''}</span>
              </div>
            ))}
          </div>
        </React.Fragment>
      )}

      {watchId && window.JobTrace && (
        <SidePane title="Live research trace" onClose={() => setWatchId(null)}>
          <window.JobTrace jobId={watchId} onClose={() => setWatchId(null)} />
        </SidePane>
      )}
    </div>
  );
}

// A short section intro card used to explain a composed surface the user lands on.
function SectionIntro({ title, children }) {
  return (
    <div style={{ ...card, padding: '14px 16px', marginBottom: GAP,
      borderLeft: '3px solid var(--primary)' }}>
      {title && <div style={{ fontFamily: 'var(--serif)', fontSize: 15,
        fontWeight: 700, color: 'var(--ink)', marginBottom: 4 }}>{title}</div>}
      <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.55,
        maxWidth: '70ch' }}>{children}</div>
    </div>
  );
}

// ───────────────────────── Watch (compose monitors) ───────────────────────
//
// The Watch tab is the existing monitors surface (topics + monitor sessions +
// reflections feed) owned by other files. TopicsPage already renders its own
// "Watch" PageHeader and intro, so we compose it directly rather than wrap it
// in a second, competing header.
//
// WebMonitorSection adds a "Monitor a website" card below the topic surface.

// ── Plain-language cadence options ──────────────────────────────────────────
const CADENCE_OPTIONS = [
  { key: 60,    label: 'Hourly',             hint: 'Checks once an hour' },
  { key: 360,   label: 'A few times a day',  hint: 'Checks every 6 hours' },
  { key: 1440,  label: 'Daily',              hint: 'Checks once a day' },
];

// ── Plain-language criteria chooser options ──────────────────────────────────
// Maps to the API criteria shape: {kind, ...kind-specific fields}
const CRITERIA_KINDS = [
  { key: 'any_change',    label: 'Any change to the page',        hint: 'Alert me whenever anything on the page is different from last time.' },
  { key: 'keyword',       label: 'When it mentions…',             hint: 'Alert me only when specific words or phrases appear.' },
  { key: 'threshold',     label: 'When a number crosses…',        hint: 'Alert me when a number on the page goes above or below a value you set.' },
  { key: 'selector_text', label: 'When a specific section changes', hint: 'Alert me when a particular part of the page (identified by a text fragment) changes.' },
];

// ── Verdict display ──────────────────────────────────────────────────────────
// Maps backend status values to plain-language labels and visual style.
// No internal terminology ("scrapability", "egress", "extract_tier") shown.
function verdictStyle(status) {
  if (status === 'good') return { icon: '✓', iconColor: '#2e7d32', bg: '#f1f8e9', border: '#aed581', label: 'Ready to monitor' };
  if (status === 'limited') return { icon: '◐', iconColor: '#e65100', bg: '#fff8e1', border: '#ffcc02', label: 'Can monitor with limitations' };
  return { icon: '✗', iconColor: '#c62828', bg: '#ffebee', border: '#ef9a9a', label: 'Cannot be monitored' };
}

// ── WebMonitorSection ────────────────────────────────────────────────────────
function WebMonitorSection({ toast }) {
  // URL entry + verify state
  const [url, setUrl] = useState('');
  const [checking, setChecking] = useState(false);
  const [verdict, setVerdict] = useState(null);   // result of /api/watch/verify

  // New monitor form state (shown after a good/limited verdict)
  const [name, setName] = useState('');
  const [criteriaKind, setCriteriaKind] = useState('any_change');
  const [kwTermsRaw, setKwTermsRaw] = useState('');  // comma-separated for keyword
  const [thresholdOp, setThresholdOp] = useState('>');
  const [thresholdValue, setThresholdValue] = useState('');
  const [selectorNeedle, setSelectorNeedle] = useState('');
  const [cadence, setCadence] = useState(360);
  const [saving, setSaving] = useState(false);

  // Existing web monitors list
  const { data: listData, loading: listLoading, reload: listReload } = useApi('/api/watch/web', { pollMs: 0 });
  const [confirmDel, setConfirmDel] = useState(null);  // monitor id to confirm deletion

  const monitors = (listData && Array.isArray(listData.monitors)) ? listData.monitors
    : (Array.isArray(listData) ? listData : []);

  // Check whether a URL can be monitored
  async function handleCheck(e) {
    if (e) e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) { toast.show('Paste a URL first.', 'error'); return; }
    setChecking(true);
    setVerdict(null);
    try {
      const result = await apiPost('/api/watch/verify', { url: trimmed });
      setVerdict(result);
      // Pre-fill name from headline if available and name is blank
      if (result && result.headline && !name) {
        setName(result.headline.slice(0, 60));
      }
    } catch (err) {
      toast.show(err.message || 'Could not check that URL. Try again.', 'error');
    } finally {
      setChecking(false);
    }
  }

  // Build the criteria object from the current chooser state
  function buildCriteria() {
    if (criteriaKind === 'keyword') {
      const terms = kwTermsRaw.split(',').map((t) => t.trim()).filter(Boolean);
      return { kind: 'keyword', terms };
    }
    if (criteriaKind === 'threshold') {
      return { kind: 'threshold', op: thresholdOp, value: parseFloat(thresholdValue) || 0 };
    }
    if (criteriaKind === 'selector_text') {
      return { kind: 'selector_text', needle: selectorNeedle.trim() };
    }
    return { kind: 'any_change' };
  }

  // Human-readable summary of the criteria (used in the list view)
  function criteriaSummary(c) {
    if (!c) return 'Any change';
    if (c.kind === 'keyword') return `Mentions: ${(c.terms || []).join(', ') || '—'}`;
    if (c.kind === 'threshold') return `Number ${c.op || '>'} ${c.value != null ? c.value : '—'}`;
    if (c.kind === 'selector_text') return `Section: "${c.needle || '—'}"`;
    return 'Any change';
  }

  // Save the new monitor
  async function handleSave() {
    const trimmedUrl = url.trim();
    if (!trimmedUrl) { toast.show('Enter a URL first.', 'error'); return; }
    if (!verdict || !verdict.can_watch) { toast.show('Check the URL first.', 'error'); return; }
    setSaving(true);
    try {
      const body = {
        url: trimmedUrl,
        criteria: buildCriteria(),
        cadence_minutes: cadence,
      };
      if (name.trim()) body.name = name.trim();
      await apiPost('/api/watch/web', body);
      toast.show('Website monitor saved.', 'success');
      // Reset form
      setUrl('');
      setVerdict(null);
      setName('');
      setCriteriaKind('any_change');
      setKwTermsRaw('');
      setThresholdOp('>');
      setThresholdValue('');
      setSelectorNeedle('');
      setCadence(360);
      listReload();
    } catch (err) {
      toast.show(err.message || 'Could not save. Try again.', 'error');
    } finally {
      setSaving(false);
    }
  }

  // Delete a monitor (after confirmation)
  async function handleDelete(id) {
    try {
      await apiDelete(`/api/watch/web/${id}`);
      setConfirmDel(null);
      toast.show('Monitor removed.', 'info');
      listReload();
    } catch (err) {
      toast.show(err.message || 'Could not delete. Try again.', 'error');
    }
  }

  const vs = verdict ? verdictStyle(verdict.status) : null;
  const canSave = verdict && verdict.can_watch === true;

  // Validation for keyword/threshold/selector_text before saving
  function saveDisabled() {
    if (!canSave) return true;
    if (criteriaKind === 'keyword' && !kwTermsRaw.trim()) return true;
    if (criteriaKind === 'threshold' && !thresholdValue.toString().trim()) return true;
    if (criteriaKind === 'selector_text' && !selectorNeedle.trim()) return true;
    return false;
  }

  return (
    <div style={{ marginTop: 36 }}>
      {/* Section divider */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 28, marginBottom: 18 }}>
        <div style={{ fontFamily: 'var(--serif)', fontSize: 18, fontWeight: 700,
          color: 'var(--ink)', marginBottom: 4 }}>Monitor a website</div>
        <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.55, maxWidth: '68ch' }}>
          Paste a link to any public webpage and Lighthouse will check it regularly,
          alerting you when something you care about changes.
        </div>
      </div>

      {/* ── Step 1: URL entry + Check button ── */}
      <div style={{ ...card, padding: '18px 20px', marginBottom: 16 }}>
        <div style={{ fontWeight: 700, fontSize: 13.5, color: 'var(--ink)', marginBottom: 10 }}>
          Which website would you like to watch?
        </div>
        <form onSubmit={handleCheck} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input
            type="url"
            value={url}
            onChange={(e) => { setUrl(e.target.value); setVerdict(null); }}
            placeholder="https://example.com/page-to-watch"
            aria-label="URL to monitor"
            style={{
              flex: '1 1 260px', padding: '9px 12px',
              border: '1px solid var(--rule)', borderRadius: 'var(--radius-sm)',
              fontSize: 14, fontFamily: 'var(--mono, monospace)',
              boxSizing: 'border-box',
            }}
          />
          <Btn loading={checking} onClick={handleCheck}>
            {checking ? 'Checking…' : 'Check'}
          </Btn>
        </form>
        <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>
          We'll tell you right away whether this page can be monitored.
        </div>

        {/* ── Verdict card ── */}
        {verdict && vs && (
          <div style={{
            marginTop: 14, padding: '14px 16px',
            background: vs.bg, border: `1px solid ${vs.border}`,
            borderRadius: 'var(--radius-sm)',
            display: 'flex', flexDirection: 'column', gap: 4,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span aria-hidden="true" style={{ fontSize: 18, color: vs.iconColor, lineHeight: 1 }}>
                {vs.icon}
              </span>
              <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--ink)' }}>
                {verdict.headline || vs.label}
              </span>
            </div>
            {verdict.detail && (
              <div style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.5, marginLeft: 26 }}>
                {verdict.detail}
              </div>
            )}
            {verdict.needs_trust && verdict.trust_hint && (
              <div style={{
                marginTop: 6, marginLeft: 26, fontSize: 12.5,
                color: '#7b1fa2', lineHeight: 1.5,
              }}>
                This site needs to be trusted first. Run{' '}
                <code style={{
                  background: 'rgba(123,31,162,0.08)', padding: '1px 5px',
                  borderRadius: 3, fontFamily: 'var(--mono, monospace)', fontSize: 12,
                }}>
                  {verdict.trust_hint}
                </code>
                {' '}in the terminal, then try again.
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Step 2 & 3: Change criteria + cadence (only when can_watch) ── */}
      {canSave && (
        <div style={{ ...card, padding: '18px 20px', marginBottom: 16 }}>
          {/* Optional name */}
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink-2)',
              display: 'block', marginBottom: 4 }}>
              Give it a name <span style={{ fontWeight: 400, color: 'var(--muted)' }}>(optional)</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Company pricing page"
              style={{
                width: '100%', padding: '8px 11px', boxSizing: 'border-box',
                border: '1px solid var(--rule)', borderRadius: 'var(--radius-sm)', fontSize: 13,
              }}
            />
          </div>

          {/* What counts as a change */}
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink-2)', marginBottom: 8 }}>
              What counts as a change?
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {CRITERIA_KINDS.map((ck) => {
                const on = criteriaKind === ck.key;
                return (
                  <label key={ck.key} style={{
                    display: 'flex', alignItems: 'flex-start', gap: 10,
                    padding: '10px 12px', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                    border: on ? '2px solid var(--primary)' : '1px solid var(--rule)',
                    background: on ? 'var(--rule-soft)' : 'var(--card)',
                    transition: 'border-color .12s ease, background .12s ease',
                  }}>
                    <input
                      type="radio"
                      name="criteria-kind"
                      value={ck.key}
                      checked={on}
                      onChange={() => setCriteriaKind(ck.key)}
                      style={{ marginTop: 2, accentColor: 'var(--primary)', flexShrink: 0 }}
                    />
                    <div>
                      <div style={{ fontSize: 13, fontWeight: on ? 700 : 500, color: 'var(--ink)', lineHeight: 1.3 }}>
                        {ck.label}
                      </div>
                      <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2, lineHeight: 1.4 }}>
                        {ck.hint}
                      </div>

                      {/* Inline inputs for each criteria kind */}
                      {on && ck.key === 'keyword' && (
                        <input
                          type="text"
                          value={kwTermsRaw}
                          onChange={(e) => setKwTermsRaw(e.target.value)}
                          placeholder="e.g. price increase, new feature, sold out"
                          aria-label="Words or phrases to watch for (comma-separated)"
                          style={{
                            marginTop: 8, width: '100%', padding: '7px 10px',
                            border: '1px solid var(--rule)', borderRadius: 'var(--radius-sm)',
                            fontSize: 13, boxSizing: 'border-box',
                          }}
                        />
                      )}
                      {on && ck.key === 'threshold' && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                          <span style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>Alert me when the number goes</span>
                          <select
                            value={thresholdOp}
                            onChange={(e) => setThresholdOp(e.target.value)}
                            aria-label="above or below"
                            style={{
                              padding: '5px 8px', border: '1px solid var(--rule)',
                              borderRadius: 'var(--radius-sm)', fontSize: 13,
                              background: 'var(--card)', color: 'var(--ink)',
                            }}
                          >
                            <option value=">">above</option>
                            <option value="<">below</option>
                          </select>
                          <input
                            type="number"
                            value={thresholdValue}
                            onChange={(e) => setThresholdValue(e.target.value)}
                            placeholder="e.g. 100"
                            aria-label="Threshold value"
                            style={{
                              width: 100, padding: '5px 8px',
                              border: '1px solid var(--rule)', borderRadius: 'var(--radius-sm)', fontSize: 13,
                            }}
                          />
                        </div>
                      )}
                      {on && ck.key === 'selector_text' && (
                        <input
                          type="text"
                          value={selectorNeedle}
                          onChange={(e) => setSelectorNeedle(e.target.value)}
                          placeholder="Paste a short snippet of text from that section"
                          aria-label="Text from the section to watch"
                          style={{
                            marginTop: 8, width: '100%', padding: '7px 10px',
                            border: '1px solid var(--rule)', borderRadius: 'var(--radius-sm)',
                            fontSize: 13, boxSizing: 'border-box',
                          }}
                        />
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          {/* How often */}
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink-2)', marginBottom: 8 }}>
              How often should we check?
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {CADENCE_OPTIONS.map((co) => {
                const on = cadence === co.key;
                return (
                  <button
                    key={co.key}
                    type="button"
                    onClick={() => setCadence(co.key)}
                    aria-pressed={on}
                    style={{
                      ...card, padding: '10px 14px', cursor: 'pointer', textAlign: 'left',
                      border: on ? '2px solid var(--primary)' : '1px solid var(--rule)',
                      background: on ? 'var(--rule-soft)' : 'var(--card)',
                      transition: 'border-color .12s ease, background .12s ease',
                      flex: '1 1 120px',
                    }}
                  >
                    <div style={{ fontWeight: on ? 700 : 500, fontSize: 13, color: 'var(--ink)' }}>
                      {co.label}
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>
                      {co.hint}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Save button */}
          <Btn onClick={handleSave} loading={saving} disabled={saveDisabled()}>
            {saving ? 'Saving…' : 'Start monitoring'}
          </Btn>
        </div>
      )}

      {/* ── Existing website monitors list ── */}
      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.05em',
          textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 10 }}>
          Your website monitors
        </div>

        {listLoading && (
          <div style={{ fontSize: 13, color: 'var(--muted)', padding: '8px 0' }}>Loading…</div>
        )}

        {!listLoading && monitors.length === 0 && (
          <div style={{
            ...card, padding: '28px 20px', textAlign: 'center',
            color: 'var(--muted)', fontSize: 13, lineHeight: 1.55,
          }}>
            You're not monitoring any websites yet. Paste a link above to start.
          </div>
        )}

        {!listLoading && monitors.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {monitors.map((m) => {
              const mCriteria = m.criteria || {};
              // TODO(api): last_checked, status fields may use different key names at integration time
              const lastChecked = m.last_checked || m.last_checked_at || null;
              const status = m.status || 'active';
              return (
                <div key={m.id} style={{
                  ...card, padding: '13px 16px',
                  display: 'flex', alignItems: 'flex-start', gap: 12,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--ink)',
                      marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {m.name || m.url || 'Unnamed monitor'}
                    </div>
                    {m.name && (
                      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {m.url}
                      </div>
                    )}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>
                        Watching for: <strong>{criteriaSummary(mCriteria)}</strong>
                      </span>
                      {lastChecked && (
                        <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
                          Last checked: {lastChecked}
                        </span>
                      )}
                      <StatusPill status={status} />
                    </div>
                  </div>
                  <Btn kind="danger" size="sm" onClick={() => setConfirmDel(m.id)}>
                    Remove
                  </Btn>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Delete confirm modal ── */}
      {confirmDel && (
        <Modal title="Remove this monitor?" onClose={() => setConfirmDel(null)} size="sm">
          <div style={{ fontSize: 14, color: 'var(--ink-2)', lineHeight: 1.6, marginBottom: 20 }}>
            This will stop Lighthouse from checking that website. Any alerts already
            sent are not affected. You can add it back any time.
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Btn kind="ghost" onClick={() => setConfirmDel(null)}>Keep it</Btn>
            <Btn kind="danger" onClick={() => handleDelete(confirmDel)}>Yes, remove</Btn>
          </div>
        </Modal>
      )}
    </div>
  );
}

// WatchPage composes the existing topic monitor surface with the new website
// monitor section. TopicsPage owns its own PageHeader so we don't add another.
function WatchPage(props) {
  const C = window.TopicsPage;
  if (!C) {
    return React.createElement(window.ErrorBox, { message: 'Watch surface failed to load.' });
  }
  return (
    <div>
      {React.createElement(C, props)}
      <div style={{ padding: '0 0 40px' }}>
        <WebMonitorSection toast={props.toast} />
      </div>
    </div>
  );
}

// ───────────────────── Track (positions + calibration + escalations) ──────
//
// Track is the accountability surface: calibration timeline on top, then the
// existing Positions register, then open escalations from Insights.
function CalibrationTimeline({ toast }) {
  const { data } = useApi('/api/calibration/timeline?bucket=week', { pollMs: 0 });
  const buckets = (data && Array.isArray(data.buckets)) ? data.buckets : [];
  if (buckets.length === 0) {
    return (
      <div style={{ ...card, padding: '14px 16px', marginBottom: GAP }}>
        <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 700,
          color: 'var(--ink)', marginBottom: 6 }}>Calibration over time</div>
        <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.55,
          maxWidth: '70ch' }}>
          Calibration measures how well your stated probabilities match what
          actually happened. Once you record predictions and resolve them as
          confirmed or refuted, this chart will track whether you are over- or
          under-confident over time. Nothing to plot yet.
        </div>
      </div>
    );
  }
  return (
    <div style={{ ...card, padding: '14px 16px', marginBottom: GAP }}>
      <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 700,
        color: 'var(--ink)', marginBottom: 4 }}>Calibration over time (weekly)</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10,
        lineHeight: 1.5, maxWidth: '70ch' }}>
        How well your stated probabilities matched outcomes, by week. Lower mean
        Brier is better; an outcome rate near your mean probability means you are
        well calibrated.
      </div>
      <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
        <thead><tr>
          {['Week', 'Predictions', 'Mean Brier', 'Mean probability', 'Outcome rate'].map((h) => (
            <th key={h} style={{ textAlign: 'left', padding: '4px 8px',
              color: 'var(--muted)' }}>{h}</th>
          ))}
        </tr></thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.bucket} style={{ borderTop: '1px solid var(--rule-soft)' }}>
              <td style={{ padding: '4px 8px' }}>{b.bucket}</td>
              <td style={{ padding: '4px 8px' }}>{b.n}</td>
              <td style={{ padding: '4px 8px' }}>{b.mean_brier}</td>
              <td style={{ padding: '4px 8px' }}>{b.mean_probability}</td>
              <td style={{ padding: '4px 8px' }}>{b.mean_outcome_rate}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Track is the accountability surface. PositionsPage and IntelligencePage each
// render their own PageHeader, so we lead with a single SectionIntro that frames
// the whole tab and let those surfaces carry their own section titles, rather
// than stacking a second top-level PageHeader on top of theirs.
function TrackPage(props) {
  const Positions = window.PositionsPage;
  const Insights = window.IntelligencePage;
  return (
    <div style={{ padding: PAD, maxWidth: 1200 }}>
      <PageHeader title="Track"
        subtitle="Hold predictions accountable: see how well-calibrated you are, manage open positions, and review escalations." />
      <SectionIntro title="What this tab does">
        A position is a prediction you have committed to with a probability. As
        positions resolve, Lighthouse scores how calibrated you were. Below you
        will find your calibration trend, the register of open and resolved
        positions, and any escalations that need attention.
      </SectionIntro>
      <CalibrationTimeline {...props} />
      {Positions ? React.createElement(Positions, props) : null}
      {Insights ? React.createElement(Insights, props) : null}
    </div>
  );
}

Object.assign(window, {
  ResearchPage, LibraryPage, ActivityPage, WatchPage, TrackPage,
});
})();
