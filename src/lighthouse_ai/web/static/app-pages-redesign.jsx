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

function ResearchPage({ toast }) {
  const { data, loading, error } = useApi('/api/modes', { pollMs: 0 });
  const [step, setStep] = useState(1);
  const [selected, setSelected] = useState(null);
  const [topic, setTopic] = useState('');
  const [options, setOptions] = useState(['', '']);
  const [criteria, setCriteria] = useState([{ label: '', weight: 1.0 }]);
  const [urls, setUrls] = useState('');
  const [depth, setDepth] = useState('standard');
  const [budget, setBudget] = useState('1h');
  const [busy, setBusy] = useState(false);

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
    setDepth('standard'); setBudget('1h');
  }

  function chooseMode(key) {
    setSelected(key);
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

  function goReview() {
    const err = frameError();
    if (err) { toast.show(err, 'error'); return; }
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
          <WizardSteps step={step} />

          {/* ── Step 1 — Choose what you want ── */}
          {step === 1 && (
            <div>
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
                  <Row k="Sources" v={`${cleanUrls.length} URL${cleanUrls.length === 1 ? '' : 's'}`} />}
              </div>

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

function ArtifactBody({ artifact }) {
  const t = artifact.artifact_type;
  const body = artifact.body;
  if (t === 'matrix') return <MatrixView body={body} />;
  if (t === 'table') return <TableView body={body} />;
  if (t === 'timeline') return <TimelineView body={body} />;
  // report / verdict / transcript / digest → prose HTML.
  return <div dangerouslySetInnerHTML={{ __html: artifact.body_html || '<em>No content.</em>' }} />;
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
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 3 }}>
                    {artifactLabel(detail.artifact_type)}
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
  useEvents((name) => { if (name && name.indexOf('job.') === 0) reload(); });

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
              return (
                <div key={j.id} style={{ display: 'flex', gap: 12, alignItems: 'center',
                  padding: '8px 0', borderTop: '1px solid var(--rule-soft)' }}>
                  <span style={{ flex: 1, fontSize: 13, color: 'var(--ink)' }}>
                    {meta.topic || j.id}</span>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                    {window.modeLabel ? window.modeLabel(j.mode) : j.mode}</span>
                  <span style={{ fontSize: 12, color: 'var(--ink-2)', minWidth: 150,
                    textAlign: 'right' }}>{statusPlain(j.status)}</span>
                  <span style={{ width: 44, textAlign: 'right', fontSize: 12,
                    color: 'var(--muted)' }}>{pct}%</span>
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
function WatchPage(props) {
  const C = window.TopicsPage;
  return C ? React.createElement(C, props)
    : React.createElement(window.ErrorBox, { message: 'Watch surface failed to load.' });
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
