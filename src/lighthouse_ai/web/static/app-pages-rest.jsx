// app-pages-rest.jsx — professional production versions of the four
// "instrument" pages: Topics · Positions · Health · Settings.
//
// Loaded via babel-standalone into ONE shared browser global scope (no module
// system). Every helper is R-prefixed to avoid collisions with app-pages.jsx.
// Shared primitives (useApi, PageHeader, Btn, DataTable, ConfidencePill,
// StatusPill, Bar, EmptyState, ErrorBox, Loading, card, apiGet, apiPost,
// apiPatch, apiDelete) come from app-lib.jsx and are accessed via window.*.

const { useState: rUseState, useEffect: rUseEffect, useRef: rUseRef, useCallback: rUseCallback } = React;

// ── Inject shimmer keyframes once ────────────────────────────────────────
(function ensureShimmerCSS() {
  if (typeof document === 'undefined') return;
  if (document.getElementById('r-shimmer-css')) return;
  const el = document.createElement('style');
  el.id = 'r-shimmer-css';
  el.textContent = `
@keyframes rShimmer {
  0%   { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}
/* Topic card: reveal delete button on hover */
.r-topic-card { position: relative; }
.r-topic-card .r-del-btn { opacity: 0; transition: opacity .15s; }
.r-topic-card:hover .r-del-btn { opacity: 1; }
/* Doctor fade-in */
@keyframes rFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.r-doctor-results { animation: rFadeIn .2s ease; }
/* Collapsible section chevron */
.r-section-chevron { transition: transform .2s; display: inline-block; }
.r-section-chevron.open { transform: rotate(90deg); }
/* Pending empty success state */
.r-all-resolved {
  border: 1.5px solid var(--green-dark);
  border-radius: var(--radius);
  padding: 28px 24px;
  text-align: center;
  background: rgba(6,214,160,0.05);
}
`;
  document.head && document.head.appendChild(el);
})();

// ── Shared style tokens ────────────────────────────────────────────────────
const rInput = {
  fontFamily: 'var(--sans)', fontSize: 13, padding: '8px 10px',
  border: '1px solid var(--rule)', borderRadius: 6, color: 'var(--ink)',
  background: 'var(--card)', width: '100%', boxSizing: 'border-box',
};

// Semantic colors. NOTE: the design token --coral-2 is actually a BLUE in this
// theme, so we use explicit hex for genuine danger/negative signalling to match
// the rest of the app (ErrorBox/Toast use #c62828).
const R_DANGER = '#c62828';
const R_DANGER_DEEP = '#b71c1c';
const R_WARN = '#c05a20';

// Cycling top-border palette for topic cards
const TOPIC_ACCENTS = [
  'var(--primary)', 'var(--green)', 'var(--sand)', 'var(--coral-2)',
];

// ── Tiny shared primitives (R-prefixed) ───────────────────────────────────

function RField({ label, hint, error: fieldError, children }) {
  return (
    <label style={{ display: 'block', marginBottom: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', marginBottom: 5,
        textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      {children}
      {hint && !fieldError && (
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{hint}</div>
      )}
      {fieldError && (
        <div style={{ fontSize: 11, color: 'var(--coral-2)', marginTop: 4, fontWeight: 600 }}>
          {fieldError}
        </div>
      )}
    </label>
  );
}

function RRow({ k, v, accent }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16,
      padding: '7px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 13 }}>
      <span style={{ color: 'var(--muted)', flexShrink: 0 }}>{k}</span>
      <span style={{ color: accent || 'var(--ink)', fontWeight: 500,
        textAlign: 'right', wordBreak: 'break-all' }}>
        {v == null || v === '' ? '—' : String(v)}
      </span>
    </div>
  );
}

function RSkeleton({ h = 16, w = '100%', mb = 8, r = 6 }) {
  return (
    <div aria-hidden="true" style={{
      height: h, width: w, marginBottom: mb, borderRadius: r,
      background: 'linear-gradient(90deg, var(--rule-soft) 25%, var(--rule) 37%, var(--rule-soft) 63%)',
      backgroundSize: '400% 100%', animation: 'rShimmer 1.4s ease infinite',
    }} />
  );
}

function RTableSkeleton({ rows = 4 }) {
  return (
    <div role="status" aria-label="Loading" style={{ ...window.card, padding: 20 }}>
      <RSkeleton h={12} w="40%" mb={16} />
      {Array.from({ length: rows }).map((_, i) => <RSkeleton key={i} h={14} mb={12} />)}
    </div>
  );
}

// Accessible toggle switch
function RToggle({ value, onChange, id }) {
  return (
    <button role="switch" aria-checked={!!value} id={id} onClick={() => onChange(!value)}
      style={{ width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer',
        background: value ? 'var(--primary)' : 'var(--rule)',
        position: 'relative', flexShrink: 0, transition: 'background .2s' }}>
      <span style={{ position: 'absolute', top: 2, left: value ? 18 : 2,
        width: 16, height: 16, borderRadius: '50%', background: '#fff',
        transition: 'left .2s', boxShadow: '0 1px 3px rgba(0,0,0,0.2)' }} />
    </button>
  );
}

// Centered modal dialog with Escape-to-close and initial-focus
function RModal({ title, onClose, children, width = 460 }) {
  const ref = rUseRef(null);
  rUseEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    if (ref.current) {
      const first = ref.current.querySelector('input,select,textarea,button');
      if (first) first.focus();
    }
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 500,
      background: 'rgba(10,42,68,0.35)', display: 'flex', alignItems: 'center',
      justifyContent: 'center', padding: 16 }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        onClick={(e) => e.stopPropagation()}
        style={{ ...window.card, padding: 24, width, maxWidth: '100%',
          maxHeight: '90vh', overflow: 'auto', boxShadow: 'var(--shadow-lg)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between',
          alignItems: 'baseline', marginBottom: 18 }}>
          <h2 style={{ fontFamily: 'var(--serif)', fontSize: 19, margin: 0,
            color: 'var(--ink)', fontWeight: 700 }}>{title}</h2>
          <button onClick={onClose} aria-label="Close dialog"
            style={{ background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 20, lineHeight: 1, color: 'var(--muted)', padding: 2 }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// Sticky right-hand detail panel
function RSidePane({ title, subtitle, onClose, children }) {
  rUseEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div role="dialog" aria-label={title || 'Details'} aria-modal="false"
      style={{ ...window.card, padding: 0, position: 'sticky', top: 12,
        alignSelf: 'start', maxHeight: 'calc(100vh - 52px)', display: 'flex',
        flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--rule)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--serif)', fontSize: 16, fontWeight: 700,
            color: 'var(--ink)', lineHeight: 1.3 }}>{title}</div>
          {subtitle && (
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 3 }}>{subtitle}</div>
          )}
        </div>
        <button onClick={onClose} aria-label="Close panel"
          style={{ background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 18, lineHeight: 1, color: 'var(--muted)', padding: 2, flexShrink: 0 }}>
          ×
        </button>
      </div>
      <div style={{ padding: '16px 18px', overflowY: 'auto', flex: 1 }}>
        {children}
      </div>
    </div>
  );
}

// Collapsible settings section card
function RSettingsSection({ title, children, defaultOpen = true }) {
  const [open, setOpen] = rUseState(defaultOpen);
  return (
    <div style={{ ...window.card, padding: 0, overflow: 'hidden' }}>
      <button onClick={() => setOpen((o) => !o)}
        style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10,
          padding: '14px 20px', background: 'none', border: 'none', cursor: 'pointer',
          borderBottom: open ? '1px solid var(--rule)' : 'none' }}
        aria-expanded={open}>
        <span className={`r-section-chevron${open ? ' open' : ''}`}
          style={{ fontSize: 11, color: 'var(--muted)' }}>▶</span>
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
          textTransform: 'uppercase', letterSpacing: '0.08em', flex: 1, textAlign: 'left' }}>
          {title}
        </span>
      </button>
      {open && <div style={{ padding: '16px 20px' }}>{children}</div>}
    </div>
  );
}

// Toggle row used in settings sections
function RToggleRow({ label, hint, value, onChange, id }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      gap: 16, marginBottom: 14 }}>
      <label htmlFor={id} style={{ cursor: 'pointer', flex: 1 }}>
        <div style={{ fontSize: 13, color: 'var(--ink)', fontFamily: 'var(--sans)',
          fontWeight: 500 }}>{label}</div>
        {hint && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{hint}</div>}
      </label>
      <RToggle id={id} value={value} onChange={onChange} />
    </div>
  );
}

function fmtDate(dateStr) {
  if (!dateStr) return null;
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return String(dateStr);
    return d.toLocaleDateString(undefined,
      { month: 'short', day: 'numeric', year: 'numeric' });
  } catch (e) { return String(dateStr); }
}

// Days until a date string (negative = overdue). Returns null if unparseable.
function daysUntil(dateStr) {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return null;
  return Math.ceil((d.getTime() - Date.now()) / 86400000);
}

// Tier / status chip. The CSS `lh-tier-chip` classes referenced by an earlier
// version don't exist in index.html, so we render a self-contained styled chip.
function RChip({ children, tone = 'neutral' }) {
  const tones = {
    neutral: { bg: 'var(--rule-soft)', fg: 'var(--ink-2)', bd: 'var(--rule)' },
    ok:      { bg: 'rgba(0,137,123,0.10)', fg: 'var(--green-dark)', bd: 'var(--green-dark)' },
    warn:    { bg: 'rgba(255,213,79,0.20)', fg: R_WARN, bd: '#d98020' },
    bad:     { bg: 'rgba(198,40,40,0.10)', fg: R_DANGER, bd: R_DANGER },
    info:    { bg: 'var(--sky-soft)', fg: 'var(--primary-dark)', bd: 'var(--primary)' },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <span style={{ display: 'inline-block', fontSize: 11, fontWeight: 700,
      fontFamily: 'var(--sans)', letterSpacing: '0.04em', textTransform: 'uppercase',
      padding: '2px 9px', borderRadius: 999, background: t.bg, color: t.fg,
      border: `1px solid ${t.bd}` }}>
      {children}
    </span>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  TOPICS PAGE
// ════════════════════════════════════════════════════════════════════════════
function TopicsPage({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/topics', { pollMs: 60000 });
  const [showNew, setShowNew] = rUseState(false);
  const [confirmDel, setConfirmDel] = rUseState(null); // topic object

  window.useEvents(rUseCallback((name) => {
    if (name && name.startsWith('topic')) reload();
  }, [reload]));

  const topics = (data && data.topics) || [];
  const Btn = window.Btn;

  async function deleteTopic(topic) {
    try {
      await window.apiDelete(`/api/topics/${topic.id}`);
      setConfirmDel(null);
      reload();
      toast.show('Topic deleted', 'info');
    } catch (e) {
      toast.show(e.message || 'Delete failed', 'error');
    }
  }

  return (
    <div>
      <window.PageHeader
        title="Research Topics"
        subtitle="Monitor named topics across sources"
        actions={
          <Btn onClick={() => setShowNew(true)} aria-label="Create a new topic">
            + New Topic
          </Btn>
        }
      />

      {/* Loading skeleton grid */}
      {loading && (
        <div style={{ display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 20 }}>
          {[1, 2, 3, 4].map((i) => (
            <div key={i} style={{ ...window.card, padding: 20 }}>
              <RSkeleton h={18} w="55%" mb={10} />
              <RSkeleton h={12} mb={6} />
              <RSkeleton h={12} w="80%" mb={16} />
              <RSkeleton h={20} w={70} r={10} />
            </div>
          ))}
        </div>
      )}

      {!loading && error && (
        <window.ErrorBox message={`Could not load topics — ${error}`} />
      )}

      {/* Empty state */}
      {!loading && !error && topics.length === 0 && (
        <window.EmptyState
          icon="🗂"
          title="No research topics yet"
          hint="Add your first topic to start monitoring."
          action={<Btn onClick={() => setShowNew(true)}>+ Add Topic</Btn>}
        />
      )}

      {/* Topic card grid */}
      {!loading && !error && topics.length > 0 && (
        <div style={{ display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 20 }}>
          {topics.map((t, idx) => (
            <RTopicCard
              key={t.id}
              topic={t}
              accent={TOPIC_ACCENTS[idx % TOPIC_ACCENTS.length]}
              onDelete={() => setConfirmDel(t)}
            />
          ))}
          {/* "+ Add" card at the end */}
          <RAddTopicCard onClick={() => setShowNew(true)} />
        </div>
      )}

      {/* New topic modal */}
      {showNew && (
        <RNewTopicModal
          toast={toast}
          onClose={() => setShowNew(false)}
          onCreated={() => {
            setShowNew(false);
            reload();
            toast.show('Topic created', 'success');
          }}
        />
      )}

      {/* Delete confirm modal */}
      {confirmDel && (
        <RModal title={`Delete "${confirmDel.name}"?`} onClose={() => setConfirmDel(null)} width={400}>
          <div style={{ fontSize: 14, color: 'var(--ink-2)', marginBottom: 22, lineHeight: 1.6 }}>
            Delete topic <strong style={{ color: 'var(--ink)' }}>{confirmDel.name}</strong>?
            This removes the topic and its configured sources and stops future
            collection. This action cannot be undone.
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Btn kind="ghost" onClick={() => setConfirmDel(null)}>Cancel</Btn>
            <Btn kind="danger" onClick={() => deleteTopic(confirmDel)}>Delete topic</Btn>
          </div>
        </RModal>
      )}
    </div>
  );
}

function RTopicCard({ topic: t, accent, onDelete }) {
  // Real /api/topics rows expose: id, name, mode, cadence, source_count,
  // created_at, updated_at. (No description/query/job_count columns.)
  const sourceCount = t.source_count != null ? t.source_count : 0;
  return (
    <div className="r-topic-card"
      style={{ ...window.card, padding: 20, display: 'flex', flexDirection: 'column', gap: 10,
        minHeight: 140, borderTop: `3px solid ${accent}` }}>
      {/* Delete button — top-right, appears on card hover */}
      <button
        onClick={onDelete}
        className="r-del-btn lh-focusable"
        aria-label={`Delete topic ${t.name || 'Untitled'}`}
        title="Delete topic"
        style={{ position: 'absolute', top: 10, right: 10, background: 'none', border: 'none',
          cursor: 'pointer', fontSize: 13, color: 'var(--muted)', padding: '2px 5px',
          borderRadius: 4, lineHeight: 1 }}>
        ✕
      </button>

      {/* Topic name */}
      <div style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
        color: 'var(--ink)', lineHeight: 1.3, paddingRight: 20, wordBreak: 'break-word' }}>
        {t.name || 'Untitled'}
      </div>

      {/* Cadence line */}
      {t.cadence && (
        <div style={{ fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.5 }}>
          Collecting <strong style={{ color: 'var(--ink)' }}>{t.cadence}</strong>
        </div>
      )}

      {/* Footer row: source count + mode */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        marginTop: 'auto', paddingTop: 4 }}>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700,
          background: sourceCount > 0 ? 'var(--primary)' : 'var(--rule)',
          color: sourceCount > 0 ? '#fff' : 'var(--muted)', padding: '2px 8px',
          borderRadius: 10 }}>
          {sourceCount} {sourceCount === 1 ? 'source' : 'sources'}
        </span>
        {t.mode && <RChip tone="info">{t.mode}</RChip>}
      </div>
    </div>
  );
}

function RAddTopicCard({ onClick }) {
  return (
    <button onClick={onClick} aria-label="Add new topic"
      style={{ ...window.card, padding: 20, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 10, minHeight: 140,
        border: '2px dashed var(--rule)', background: 'transparent', cursor: 'pointer',
        borderRadius: 'var(--radius)', transition: 'border-color .15s, background .15s',
        outline: 'none', boxShadow: 'none' }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--primary)';
        e.currentTarget.style.background = 'rgba(var(--primary-rgb,0,123,255),0.03)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--rule)';
        e.currentTarget.style.background = 'transparent';
      }}>
      <span style={{ fontSize: 28, color: 'var(--muted)', lineHeight: 1 }}>+</span>
      <span style={{ fontSize: 13, color: 'var(--muted)', fontFamily: 'var(--sans)' }}>
        Add topic
      </span>
    </button>
  );
}

function RNewTopicModal({ toast, onClose, onCreated }) {
  const [name, setName] = rUseState('');
  const [mode, setMode] = rUseState('Monitor');
  const [cadence, setCadence] = rUseState('continuous');
  const [busy, setBusy] = rUseState(false);
  const [errors, setErrors] = rUseState({});
  const Btn = window.Btn;

  function validate() {
    const e = {};
    if (!name.trim()) e.name = 'Name is required.';
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function submit() {
    if (!validate()) return;
    setBusy(true);
    try {
      // Backend NewTopic accepts: name, mode, cadence, sources.
      await window.apiPost('/api/topics', {
        name: name.trim(),
        mode,
        cadence,
      });
      onCreated();
    } catch (e) {
      toast.show(e.message || 'Create failed', 'error');
      setBusy(false);
    }
  }

  function onSubmit(e) { e.preventDefault(); submit(); }

  return (
    <RModal title="New Research Topic" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <RField label="Name" error={errors.name}
          hint={!errors.name ? 'What you want Lighthouse to watch.' : undefined}>
          <input
            value={name}
            onChange={(e) => { setName(e.target.value); setErrors((er) => ({ ...er, name: '' })); }}
            placeholder="e.g. EU AI Act"
            style={{ ...rInput, borderColor: errors.name ? R_DANGER : undefined }}
            aria-label="Topic name"
            aria-invalid={!!errors.name}
            autoFocus
          />
        </RField>
        <RField label="Mode" hint="Monitor watches continuously; Deepdive runs one focused pass.">
          <select value={mode} onChange={(e) => setMode(e.target.value)}
            style={rInput} aria-label="Topic mode">
            <option value="Monitor">Monitor</option>
            <option value="Deepdive">Deepdive</option>
          </select>
        </RField>
        <RField label="Cadence" hint="How often collection runs.">
          <select value={cadence} onChange={(e) => setCadence(e.target.value)}
            style={rInput} aria-label="Collection cadence">
            <option value="continuous">Continuous</option>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
          </select>
        </RField>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
          <Btn kind="ghost" onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn type="submit" loading={busy}>{busy ? 'Creating…' : 'Create topic'}</Btn>
        </div>
      </form>
    </RModal>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  POSITIONS PAGE
// ════════════════════════════════════════════════════════════════════════════
// Outcome semantics: backend stores `outcome` as 1 (confirmed) / 0 (refuted) /
// null (unresolved). A position is pending iff outcome == null.
function rIsPending(p) { return p && p.outcome == null; }
function rIsConfirmed(p) { return p && p.outcome != null && Number(p.outcome) === 1; }
function rProb(p) { return p && p.confidence != null ? Number(p.confidence) : null; }

function PositionsPage({ toast }) {
  const [tab, setTab] = rUseState('Pending');
  // Single source of truth for both the summary and the lists, so counts and
  // the calibration score stay consistent and we avoid double-fetching.
  const { data, loading, error, reload } = window.useApi('/api/positions');
  const { data: calData } = window.useApi('/api/calibration');

  const positions = (data && data.positions) || [];
  const resolved = positions.filter((p) => !rIsPending(p));
  const pending  = positions.filter(rIsPending);
  const overdue  = pending.filter((p) => { const d = daysUntil(p.resolve_by); return d != null && d < 0; });

  // Prefer the server's authoritative mean Brier; fall back to client compute.
  let brier = (calData && typeof calData.mean_brier === 'number' && calData.n > 0)
    ? calData.mean_brier : null;
  if (brier == null && resolved.length) {
    const scored = resolved.filter((p) => p.brier != null);
    if (scored.length) brier = scored.reduce((a, p) => a + Number(p.brier), 0) / scored.length;
  }

  function brierInfo(b) {
    if (b == null) return { label: 'No data yet', color: 'var(--muted)' };
    if (b < 0.1)   return { label: 'Excellent',   color: 'var(--green-dark)' };
    if (b < 0.2)   return { label: 'Good',        color: 'var(--green-dark)' };
    if (b < 0.25)  return { label: 'Fair',        color: R_WARN };
    return              { label: 'Needs work',     color: R_DANGER };
  }
  const bi = brierInfo(brier);

  // SSE refresh
  window.useEvents(rUseCallback((name) => {
    if (name === 'position.resolved') reload();
  }, [reload]));

  return (
    <div>
      <window.PageHeader
        title="Calibration"
        subtitle="Track predictions and measure forecasting accuracy"
        tabs={['Pending', 'Resolved']}
        activeTab={tab}
        onTab={setTab}
      />

      {error && !data && (
        <div style={{ marginBottom: 16 }}>
          <window.ErrorBox message={`Could not load positions — ${error}`} onRetry={reload} />
        </div>
      )}

      {/* Calibration summary — always visible */}
      <div style={{ ...window.card, padding: '16px 22px', marginBottom: 20,
        display: 'flex', gap: 36, alignItems: 'center', flexWrap: 'wrap' }}>
        {/* Brier score */}
        <div>
          <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.07em', marginBottom: 4 }}>Brier Score</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            {window.BrierScore && brier != null
              ? <window.BrierScore score={brier} />
              : (
                <span className="num"
                  style={{ fontSize: 26, fontWeight: 700, color: bi.color }}>
                  {brier != null ? brier.toFixed(3) : '—'}
                </span>
              )
            }
            <span style={{ fontSize: 12, color: bi.color, fontWeight: 600 }}>{bi.label}</span>
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--muted)', marginTop: 3 }}>
            lower is better · 0 = perfect
          </div>
        </div>

        {/* Resolved count */}
        <div>
          <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.07em', marginBottom: 4 }}>Resolved</div>
          <span className="num" style={{ fontSize: 26, fontWeight: 700,
            color: 'var(--ink)' }}>{resolved.length}</span>
        </div>

        {/* Pending count */}
        <div>
          <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.07em', marginBottom: 4 }}>Pending</div>
          <span className="num" style={{ fontSize: 26, fontWeight: 700,
            color: 'var(--ink)' }}>{pending.length}</span>
        </div>

        {/* Overdue count — only when there are any */}
        {overdue.length > 0 && (
          <div>
            <div style={{ fontSize: 10.5, color: R_DANGER, textTransform: 'uppercase',
              letterSpacing: '0.07em', marginBottom: 4, fontWeight: 700 }}>Overdue</div>
            <span className="num" style={{ fontSize: 26, fontWeight: 700,
              color: R_DANGER }}>{overdue.length}</span>
          </div>
        )}
      </div>

      {tab === 'Pending'  && (
        <RPositionList key="pending" positions={pending} loading={loading} error={error}
          reload={reload} isPending toast={toast} />
      )}
      {tab === 'Resolved' && (
        <RPositionList key="resolved" positions={resolved} loading={loading} error={error}
          reload={reload} isResolved toast={toast} />
      )}
    </div>
  );
}

function RPositionList({ positions: rawPositions, loading, error, reload, isPending, isResolved, toast }) {
  const [sel, setSel] = rUseState(null);
  const [busyId, setBusyId] = rUseState(null);

  // Pending: surface the most urgent (soonest / overdue) first. Resolved: keep
  // newest-resolved order from the API.
  const positions = isPending
    ? rawPositions.slice().sort((a, b) => {
        const da = daysUntil(a.resolve_by), db = daysUntil(b.resolve_by);
        if (da == null && db == null) return 0;
        if (da == null) return 1;
        if (db == null) return -1;
        return da - db;
      })
    : rawPositions;

  // Keep the open detail pane in sync with refreshed data (e.g. after resolve).
  const selLive = sel ? (positions.find((p) => p.id === sel.id) || sel) : null;

  async function resolve(id, outcome) {
    setBusyId(id);
    try {
      await window.apiPost(`/api/positions/${id}/resolve`, { outcome });
      toast.show(
        outcome === 'defer' ? 'Position deferred' : 'Position resolved',
        'success'
      );
      setSel(null);
      reload();
    } catch (e) {
      toast.show(e.message || 'Resolve failed', 'error');
    } finally {
      setBusyId(null);
    }
  }

  if (loading && !rawPositions.length) return <RTableSkeleton rows={5} />;
  if (error && !rawPositions.length) {
    return <window.ErrorBox message={`Could not load positions — ${error}`} onRetry={reload} />;
  }

  // Empty states differ for pending vs resolved
  if (!positions.length && isPending) {
    return (
      <div className="r-all-resolved">
        <div style={{ fontSize: 28, marginBottom: 8 }}>✓</div>
        <div style={{ fontFamily: 'var(--serif)', fontSize: 17, color: 'var(--green-dark)',
          fontWeight: 700, marginBottom: 4 }}>
          All positions are resolved
        </div>
        <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.5 }}>
          Calibration is up to date. Every prediction has been resolved or is still on the clock.
        </div>
      </div>
    );
  }

  if (!positions.length && isResolved) {
    return (
      <window.EmptyState
        icon="◎"
        title="No resolved positions yet"
        hint="Resolve a prediction and it will appear here with its outcome and scoring."
      />
    );
  }

  return (
    <React.Fragment>
      {/* Position list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {positions.map((p) => {
          const isSelected = selLive && selLive.id === p.id;
          const prob = rProb(p);
          const pending = rIsPending(p);
          const dleft = pending ? daysUntil(p.resolve_by) : null;
          const isOverdue = dleft != null && dleft < 0;
          const dueSoon = dleft != null && dleft >= 0 && dleft <= 7;

          return (
            <div
              key={p.id}
              onClick={() => setSel(isSelected ? null : p)}
              role="button"
              tabIndex={0}
              className="lh-focusable"
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(isSelected ? null : p); }
              }}
              aria-pressed={!!isSelected}
              style={{ ...window.card, padding: '14px 18px', cursor: 'pointer',
                borderColor: isSelected ? 'var(--primary)' : (isOverdue ? R_DANGER : 'var(--rule)'),
                borderLeft: isOverdue ? `3px solid ${R_DANGER}` : undefined,
                transition: 'border-color .15s' }}>
              {/* Claim text — 2-line clamp */}
              <div style={{ fontFamily: 'var(--serif)', fontSize: 14.5, color: 'var(--ink)',
                lineHeight: 1.45, display: '-webkit-box', WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical', overflow: 'hidden', marginBottom: 9 }}>
                {p.claim || '(no claim text)'}
              </div>

              {/* Meta row */}
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                {p.wep_band && (
                  <window.ConfidencePill phrase={p.wep_band}
                    band={prob != null ? String(prob) : undefined} />
                )}
                {prob != null && (
                  <span className="num" style={{ fontSize: 12.5,
                    color: 'var(--ink-2)', fontWeight: 600 }}>
                    {(prob * 100).toFixed(0)}%
                  </span>
                )}
                {pending && p.resolve_by && (
                  <span style={{ fontSize: 11.5, fontWeight: 700,
                    color: isOverdue ? R_DANGER : dueSoon ? R_WARN : 'var(--muted)' }}>
                    {isOverdue
                      ? `overdue by ${Math.abs(dleft)}d`
                      : dleft === 0 ? 'due today'
                      : `due ${fmtDate(p.resolve_by)}`}
                  </span>
                )}
                {!pending && (
                  <span style={{ fontSize: 12, fontWeight: 700,
                    color: rIsConfirmed(p) ? 'var(--green-dark)' : R_DANGER }}>
                    {rIsConfirmed(p) ? 'confirmed' : 'refuted'}
                  </span>
                )}
                {!pending && p.brier != null && (
                  <span className="num" style={{ fontSize: 11.5, color: 'var(--muted)' }}>
                    Brier {Number(p.brier).toFixed(3)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Detail pane — SidePane is a fixed overlay, so it lives outside the list flow */}
      {selLive && (
        <window.SidePane title="Position" onClose={() => setSel(null)}>
          {/* Full claim text */}
          <div style={{ fontFamily: 'var(--serif)', fontSize: 15.5, color: 'var(--ink)',
            lineHeight: 1.6, marginBottom: 18 }}>
            {selLive.claim || '(no claim text)'}
          </div>

          {/* Probability */}
          {(() => {
            const prob = rProb(selLive);
            if (prob == null) return null;
            return (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
                  letterSpacing: '0.07em', marginBottom: 6 }}>Stated probability</div>
                {window.WepBar
                  ? <window.WepBar probability={prob} />
                  : (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ flex: 1 }}>
                        <window.Bar value={prob} max={1} color="var(--primary)" />
                      </div>
                      <span className="num" style={{ fontSize: 14, fontWeight: 700,
                        color: 'var(--ink)', whiteSpace: 'nowrap' }}>
                        {(prob * 100).toFixed(0)}%
                      </span>
                    </div>
                  )}
                {selLive.wep_band && (
                  <div style={{ marginTop: 8 }}>
                    <window.ConfidencePill phrase={selLive.wep_band} band={String(prob)} />
                  </div>
                )}
              </div>
            );
          })()}

          {/* Resolution criterion — tells the user HOW to decide the outcome */}
          {selLive.resolution_criterion && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
                letterSpacing: '0.07em', marginBottom: 6 }}>Resolution criterion</div>
              <div style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.55 }}>
                {selLive.resolution_criterion}
              </div>
            </div>
          )}

          {/* Resolved outcome + Brier */}
          {!rIsPending(selLive) && (
            <div style={{ marginBottom: 14, padding: '10px 14px', borderRadius: 8,
              background: rIsConfirmed(selLive) ? 'rgba(0,137,123,0.08)' : 'rgba(198,40,40,0.07)',
              border: `1px solid ${rIsConfirmed(selLive) ? 'var(--green-dark)' : R_DANGER}` }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                letterSpacing: '0.06em', marginBottom: 3 }}>Outcome</div>
              <div style={{ fontWeight: 700, fontSize: 14,
                color: rIsConfirmed(selLive) ? 'var(--green-dark)' : R_DANGER }}>
                {rIsConfirmed(selLive) ? 'Confirmed (true)' : 'Refuted (false)'}
              </div>
              {selLive.brier != null && (
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                  Brier score: <strong>{Number(selLive.brier).toFixed(3)}</strong>
                </div>
              )}
            </div>
          )}

          {/* Metadata rows */}
          {selLive.created_at  && <RRow k="Created"  v={fmtDate(selLive.created_at)} />}
          {selLive.resolve_by  && rIsPending(selLive) && (() => {
            const d = daysUntil(selLive.resolve_by);
            const od = d != null && d < 0;
            return <RRow k="Due" v={fmtDate(selLive.resolve_by)} accent={od ? R_DANGER : undefined} />;
          })()}
          {selLive.resolved_at && <RRow k="Resolved" v={fmtDate(selLive.resolved_at)} />}

          {/* Resolve actions — only for pending positions */}
          {rIsPending(selLive) && (
            <div style={{ marginTop: 20 }}>
              <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
                letterSpacing: '0.07em', marginBottom: 10 }}>Resolve this position</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <button
                  onClick={() => resolve(selLive.id, 'confirmed')}
                  disabled={busyId === selLive.id}
                  className="lh-focusable"
                  aria-label="Resolve as confirmed (true)"
                  style={{ background: 'var(--green-dark)', color: '#fff', border: 'none',
                    borderRadius: 'var(--radius-sm)', padding: '9px 16px',
                    cursor: busyId === selLive.id ? 'wait' : 'pointer',
                    opacity: busyId === selLive.id ? 0.6 : 1,
                    fontSize: 13, fontWeight: 600, fontFamily: 'var(--sans)', textAlign: 'left' }}>
                  ✓ True outcome — confirmed
                </button>
                <button
                  onClick={() => resolve(selLive.id, 'refuted')}
                  disabled={busyId === selLive.id}
                  className="lh-focusable"
                  aria-label="Resolve as refuted (false)"
                  style={{ background: R_DANGER, color: '#fff', border: 'none',
                    borderRadius: 'var(--radius-sm)', padding: '9px 16px',
                    cursor: busyId === selLive.id ? 'wait' : 'pointer',
                    opacity: busyId === selLive.id ? 0.6 : 1,
                    fontSize: 13, fontWeight: 600, fontFamily: 'var(--sans)', textAlign: 'left' }}>
                  ✕ False outcome — refuted
                </button>
                <button
                  onClick={() => resolve(selLive.id, 'defer')}
                  disabled={busyId === selLive.id}
                  aria-label="Defer this position"
                  className="btn-ghost lh-focusable"
                  style={{ padding: '9px 16px', fontSize: 13, fontWeight: 600,
                    cursor: busyId === selLive.id ? 'wait' : 'pointer',
                    opacity: busyId === selLive.id ? 0.6 : 1, textAlign: 'left' }}>
                  — Defer for now
                </button>
              </div>
            </div>
          )}
        </window.SidePane>
      )}
    </React.Fragment>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  HEALTH PAGE
// ════════════════════════════════════════════════════════════════════════════
// Map a database status string ("ok" | "absent" | "error: ...") to a chip tone.
function rDbTone(status) {
  if (status === 'ok') return 'ok';
  if (status === 'absent') return 'neutral';
  return 'bad';
}

// Section header label used across Health cards.
function RCardLabel({ children }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
      textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14 }}>
      {children}
    </div>
  );
}

// One labeled budget bar (usd / tokens / tool_calls).
function RBudgetBar({ label, used, cap, fmt }) {
  const u = Number(used || 0);
  const c = Number(cap || 0);
  const ratio = c > 0 ? u / c : 0;
  const hot = ratio > 0.85;
  const format = fmt || ((n) => String(Math.round(n)));
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between',
        fontSize: 12, color: 'var(--ink-2)', marginBottom: 6 }}>
        <span>{label}</span>
        <span className="num" style={{ color: hot ? R_DANGER : 'var(--ink)' }}>
          {format(u)} / {format(c)}
        </span>
      </div>
      <window.Bar value={u} max={c || 1} color={hot ? R_DANGER : 'var(--primary)'} />
    </div>
  );
}

// External service up/down row.
function RServiceRow({ name, up }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      gap: 12, padding: '8px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 13 }}>
      <span style={{ color: 'var(--ink)', fontWeight: 500 }}>{name}</span>
      <RChip tone={up ? 'ok' : 'bad'}>{up ? 'up' : 'down'}</RChip>
    </div>
  );
}

function HealthPage({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/health', { pollMs: 10000 });
  const [busy, setBusy] = rUseState(false);
  const [confirmKill, setConfirmKill] = rUseState(false);
  const Btn = window.Btn;

  const h        = data || {};
  const hw       = h.hardware || {};
  const dbs      = h.databases || {};
  const external = h.external || {};
  const budget   = h.budget || {};
  const storage  = h.storage || {};

  const overall = h.overall;
  const healthy = overall === 'green';

  const fmtUsd = (n) => `$${Number(n).toFixed(2)}`;
  const fmtCompact = (n) => {
    const v = Number(n);
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return String(Math.round(v));
  };

  async function governorAction(path, label) {
    setBusy(true);
    try {
      await window.apiPost(path, {});
      toast.show(label, 'success');
      reload();
    } catch (e) {
      toast.show(e.message || 'Action failed', 'error');
    } finally {
      setBusy(false);
      setConfirmKill(false);
    }
  }

  const dbNames = Object.keys(dbs);

  return (
    <div>
      <window.PageHeader
        title="System Health"
        subtitle="Live status of hardware, services, budget and storage"
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            {h.checked_at && (
              <span style={{ fontSize: 11.5, color: 'var(--muted)', fontFamily: 'var(--sans)' }}>
                Checked {fmtDate(h.checked_at) || ''} · auto every 10s
              </span>
            )}
            <Btn kind="ghost" onClick={reload} disabled={loading}
              aria-label="Re-check health now">
              {loading ? 'Checking…' : 'Re-check'}
            </Btn>
          </div>
        }
      />

      {/* Overall status banner */}
      {data && (
        <div style={{ padding: '12px 18px', borderRadius: 'var(--radius)',
          marginBottom: 18, fontSize: 14, fontWeight: 600, fontFamily: 'var(--sans)',
          display: 'flex', alignItems: 'center', gap: 10,
          background: healthy ? 'rgba(6,214,160,0.09)' : 'rgba(255,152,100,0.12)',
          color: healthy ? 'var(--green-dark)' : R_WARN,
          border: `1px solid ${healthy ? 'var(--green-dark)' : '#d98020'}` }}>
          <span style={{ fontSize: 16, lineHeight: 1 }}>{healthy ? '✓' : '⚠'}</span>
          {healthy
            ? 'All systems healthy'
            : 'Attention needed — one or more checks are degraded'}
        </div>
      )}

      {loading && !data && <RTableSkeleton rows={6} />}
      {!loading && error && !data && (
        <window.ErrorBox message={`Could not reach the health endpoint — ${error}`} onRetry={reload} />
      )}

      {data && (
        <div style={{ display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: 16, alignItems: 'start' }}>

          {/* ── System ───────────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <RCardLabel>System</RCardLabel>
            <RRow k="Platform" v={hw.platform} />
            <RRow k="Architecture" v={hw.arch} />
            <RRow k="Total RAM" v={hw.total_ram_gb != null ? `${hw.total_ram_gb} GB` : null} />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              gap: 12, padding: '8px 0', fontSize: 13 }}>
              <span style={{ color: 'var(--muted)' }}>Tier</span>
              {hw.tier ? <RChip tone="info">{hw.tier}</RChip>
                : <span style={{ color: 'var(--ink)' }}>—</span>}
            </div>
          </div>

          {/* ── Databases ────────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <RCardLabel>Databases</RCardLabel>
            {dbNames.length === 0 && (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>No databases reported.</div>
            )}
            {dbNames.map((name) => {
              const status = dbs[name];
              const short = status && status.startsWith('error')
                ? 'error' : status;
              return (
                <div key={name}
                  title={status}
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    gap: 12, padding: '8px 0', borderBottom: '1px solid var(--rule-soft)',
                    fontSize: 13 }}>
                  <span style={{ color: 'var(--ink)', fontWeight: 500 }}>{name}</span>
                  <RChip tone={rDbTone(status)}>{short}</RChip>
                </div>
              );
            })}
          </div>

          {/* ── External services ────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <RCardLabel>External services</RCardLabel>
            <RServiceRow name="Ollama" up={!!external.ollama} />
            <RServiceRow name="Qdrant" up={!!external.qdrant} />
            <RServiceRow name="Litestream" up={!!external.litestream} />
          </div>

          {/* ── Budget ───────────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
                textTransform: 'uppercase', letterSpacing: '0.08em' }}>Budget</div>
              {budget.tier && <RChip tone="info">{budget.tier}</RChip>}
            </div>

            {budget.usd && (
              <RBudgetBar label="Cloud USD / mo"
                used={budget.usd.used} cap={budget.usd.cap} fmt={fmtUsd} />
            )}
            {budget.tokens && (
              <RBudgetBar label="Tokens / day"
                used={budget.tokens.used} cap={budget.tokens.cap} fmt={fmtCompact} />
            )}
            {budget.tool_calls && (
              <RBudgetBar label="Tool calls / day"
                used={budget.tool_calls.used} cap={budget.tool_calls.cap} fmt={fmtCompact} />
            )}
            {!budget.usd && !budget.tokens && !budget.tool_calls && (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>No budget data reported.</div>
            )}

            {/* Optional governor controls */}
            <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
              <Btn kind="ghost" onClick={() => setConfirmKill(true)} disabled={busy}
                aria-label="Pause all spending">Pause all</Btn>
              <Btn kind="ghost" onClick={() => governorAction('/api/governor/reset', 'Budget reset')}
                disabled={busy} aria-label="Reset budget counters">Reset</Btn>
            </div>
          </div>

          {/* ── Storage ──────────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <RCardLabel>Storage</RCardLabel>
            {(() => {
              const total = Number(storage.disk_total_gb || 0);
              const free  = Number(storage.disk_free_gb || 0);
              const used  = total > 0 ? total - free : 0;
              return (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 12, color: 'var(--ink-2)', marginBottom: 6 }}>
                    <span>Disk used</span>
                    <span className="num">{used.toFixed(1)} / {total.toFixed(1)} GB</span>
                  </div>
                  <window.Bar value={used} max={total || 1} color="var(--primary)" />
                </div>
              );
            })()}
            <RRow k="Disk free" v={storage.disk_free_gb != null
              ? `${storage.disk_free_gb} GB` : null} />
            {Array.isArray(storage.replicas) && (
              <RRow k="Replicas" v={storage.replicas.length} />
            )}
          </div>

          {/* ── Reliability ──────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <RCardLabel>Reliability</RCardLabel>
            <RRow k="Outbox depth"
              v={h.outbox_depth != null ? h.outbox_depth : null}
              accent={Number(h.outbox_depth) >= 100 ? R_DANGER : undefined} />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              gap: 12, padding: '8px 0', fontSize: 13 }}>
              <span style={{ color: 'var(--muted)' }}>Audit chain</span>
              {h.audit_chain_ok == null ? (
                <span style={{ color: 'var(--muted)', fontWeight: 600 }}>— unknown</span>
              ) : h.audit_chain_ok ? (
                <span style={{ color: 'var(--green-dark)', fontWeight: 700 }}>✓ verified</span>
              ) : (
                <span style={{ color: R_DANGER, fontWeight: 700 }}>✕ broken</span>
              )}
            </div>
          </div>

        </div>
      )}

      {confirmKill && (
        <RModal title="Pause all spending?" onClose={() => setConfirmKill(false)} width={400}>
          <div style={{ fontSize: 14, color: 'var(--ink-2)', marginBottom: 22, lineHeight: 1.6 }}>
            This trips the budget governor kill switch, halting all cloud model calls
            and tool spending until you reset it. Continue?
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Btn kind="ghost" onClick={() => setConfirmKill(false)} disabled={busy}>Cancel</Btn>
            <Btn kind="danger" onClick={() => governorAction('/api/governor/kill', 'Spending paused')}
              disabled={busy}>Pause all</Btn>
          </div>
        </RModal>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  SETTINGS PAGE
// ════════════════════════════════════════════════════════════════════════════
// ── Notifications section ──────────────────────────────────────────────────
function RNotificationsSection({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/settings/notifications');
  const [savingEvent, setSavingEvent] = rUseState(null);

  const channels = (data && data.channels) || {};
  const allEvents = (data && data.all_events) || [];
  const events = (data && data.events) || [];
  const enabled = new Set(events);

  async function toggleEvent(name, on) {
    const next = on
      ? Array.from(new Set([...events, name]))
      : events.filter((e) => e !== name);
    setSavingEvent(name);
    try {
      await window.apiPatch('/api/settings/notifications', { events: next, telegram_events: null });
      toast.show(`Notifications updated — ${name} ${on ? 'on' : 'off'}`, 'success');
      reload();
    } catch (e) {
      toast.show(e.message || 'Update failed', 'error');
    } finally {
      setSavingEvent(null);
    }
  }

  if (loading && !data) return <window.Loading />;
  if (error && !data) {
    return <window.ErrorBox message={`Could not load notifications — ${error}`} onRetry={reload} />;
  }

  const tg = channels.telegram || {};
  return (
    <div>
      {/* Channel status */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 18 }}>
        <RChannelChip name="Desktop" on={channels.desktop && channels.desktop.enabled} />
        <RChannelChip name="Discord" on={channels.discord && channels.discord.enabled} />
        <RChannelChip name="Telegram"
          on={tg.enabled} hint={tg.configured ? undefined : 'not configured'} />
      </div>

      {/* Event checklist */}
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
        textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
        Events to notify on
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {allEvents.length === 0 && (
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>No event types available.</div>
        )}
        {allEvents.map((name) => {
          const on = enabled.has(name);
          const busy = savingEvent === name;
          return (
            <label key={name}
              style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: busy ? 'wait' : 'pointer',
                padding: '7px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 13,
                opacity: busy ? 0.6 : 1 }}>
              <input type="checkbox" checked={on} disabled={busy}
                onChange={(e) => toggleEvent(name, e.target.checked)}
                aria-label={`Notify on ${name}`} />
              <span style={{ color: 'var(--ink)', fontFamily: 'var(--mono)', fontSize: 12.5 }}>
                {name}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

function RChannelChip({ name, on, hint }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <RChip tone={on ? 'ok' : 'neutral'}>{name} {on ? 'on' : 'off'}</RChip>
      {hint && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{hint}</span>}
    </div>
  );
}

// ── Logseq section (read-only) ──────────────────────────────────────────────
function RLogseqSection() {
  const { data, loading, error } = window.useApi('/api/settings/logseq');
  if (loading && !data) return <window.Loading />;
  if (error && !data) return <window.ErrorBox message={`Could not load Logseq status — ${error}`} />;
  const d = data || {};
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 12, padding: '8px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 13 }}>
        <span style={{ color: 'var(--muted)' }}>Status</span>
        <RChip tone={d.enabled ? 'ok' : 'neutral'}>{d.enabled ? 'enabled' : 'disabled'}</RChip>
      </div>
      <RRow k="Graph directory" v={d.graph_dir} />
      <RRow k="Sync interval" v={d.sync_interval_hours != null ? `every ${d.sync_interval_hours}h` : null} />
      <RRow k="Pending sync" v={d.pending_sync != null ? d.pending_sync : null} />
    </div>
  );
}

// ── Learned skills section ──────────────────────────────────────────────────
function RSkillsSection() {
  const { data, loading, error } = window.useApi('/api/skills');
  if (loading && !data) return <window.Loading />;
  if (error && !data) return <window.ErrorBox message={`Could not load skills — ${error}`} />;
  const skills = (data && data.skills) || [];
  const top = skills.slice()
    .sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0))
    .slice(0, 5);
  return (
    <div>
      <div style={{ fontSize: 13, color: 'var(--ink-2)', marginBottom: 12, lineHeight: 1.5 }}>
        <strong style={{ color: 'var(--ink)' }}>{skills.length}</strong>{' '}
        learned skill{skills.length === 1 ? '' : 's'} from self-evaluation. Manage via{' '}
        <code style={{ fontFamily: 'var(--mono)', fontSize: 12, background: 'var(--rule-soft)',
          padding: '1px 5px', borderRadius: 4 }}>lighthouse skills</code>.
      </div>
      {top.length === 0 && (
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>
          No skills learned yet — they appear as the system evaluates its own work.
        </div>
      )}
      {top.map((s) => (
        <div key={s.id || s.name}
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            gap: 12, padding: '8px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 13 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: 'var(--ink)', fontWeight: 500, wordBreak: 'break-word' }}>
              {s.name || s.id}
            </div>
            {s.applied_count != null && (
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                applied {s.applied_count}× · {s.win_count != null ? `${s.win_count} wins` : ''}
              </div>
            )}
          </div>
          {s.score != null && (
            <span className="num" style={{ fontSize: 13, fontWeight: 700,
              color: 'var(--ink)', flexShrink: 0 }}>
              {Number(s.score).toFixed(2)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Secrets section ─────────────────────────────────────────────────────────
function RSecretsSection({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/secrets');
  const [key, setKey] = rUseState('');
  const [value, setValue] = rUseState('');
  const [busy, setBusy] = rUseState(false);
  const Btn = window.Btn;

  const secrets = (data && data.secrets) || {};
  const keys = Object.keys(secrets);

  async function addSecret(e) {
    e.preventDefault();
    if (!key.trim() || !value) return;
    setBusy(true);
    try {
      await window.apiPost('/api/secrets', { key: key.trim(), value });
      toast.show(`Secret "${key.trim()}" saved`, 'success');
      setKey('');
      setValue('');
      reload();
    } catch (err) {
      toast.show(err.message || 'Could not save secret', 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {error && !data && (
        <div style={{ marginBottom: 12 }}>
          <window.ErrorBox message={`Could not load secrets — ${error}`} onRetry={reload} />
        </div>
      )}
      {loading && !data && <window.Loading />}

      {data && (
        <div style={{ marginBottom: 16 }}>
          {keys.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 10 }}>
              No secrets stored yet.
            </div>
          )}
          {keys.map((k) => (
            <div key={k}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                gap: 12, padding: '8px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 13 }}>
              <span style={{ color: 'var(--ink)', fontFamily: 'var(--mono)', fontSize: 12.5 }}>{k}</span>
              <span style={{ color: 'var(--muted)', fontFamily: 'var(--mono)',
                letterSpacing: '0.15em' }}>••••••</span>
            </div>
          ))}
        </div>
      )}

      {/* Add form — write-only */}
      <form onSubmit={addSecret}>
        <RField label="Add or update a secret"
          hint="Values are write-only and never displayed after saving.">
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <input value={key} onChange={(e) => setKey(e.target.value)}
              placeholder="KEY (e.g. ANTHROPIC_API_KEY)"
              style={{ ...rInput, flex: 1 }} aria-label="Secret key" />
            <input value={value} onChange={(e) => setValue(e.target.value)}
              type="password" placeholder="value"
              style={{ ...rInput, flex: 1 }} aria-label="Secret value" autoComplete="off" />
            <Btn type="submit" loading={busy} disabled={busy || !key.trim() || !value}>
              {busy ? 'Saving…' : 'Save'}
            </Btn>
          </div>
        </RField>
      </form>
    </div>
  );
}

function SettingsPage({ toast }) {
  const { data, loading, error } = window.useApi('/api/settings');

  return (
    <div>
      <window.PageHeader
        title="Settings"
        subtitle="Notifications, integrations, learned skills and secrets"
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 680 }}>

        <RSettingsSection title="Notifications">
          <RNotificationsSection toast={toast} />
        </RSettingsSection>

        <RSettingsSection title="Logseq integration">
          <RLogseqSection />
        </RSettingsSection>

        <RSettingsSection title="Learned skills">
          <RSkillsSection />
        </RSettingsSection>

        <RSettingsSection title="Secrets">
          <RSecretsSection toast={toast} />
        </RSettingsSection>

        {/* Configuration overview — read-only from /api/settings */}
        <RSettingsSection title="Configuration" defaultOpen={false}>
          {loading && !data && <window.Loading />}
          {error && !data && (
            <window.ErrorBox message={`Could not load configuration — ${error}`} />
          )}
          {data && (
            <pre style={{ margin: 0, fontFamily: 'var(--mono)', fontSize: 11.5,
              color: 'var(--ink-2)', background: 'var(--rule-soft)', padding: 14,
              borderRadius: 8, overflow: 'auto', maxHeight: 320, lineHeight: 1.5 }}>
              {JSON.stringify((data && data.config) || {}, null, 2)}
            </pre>
          )}
        </RSettingsSection>

      </div>
    </div>
  );
}

// ── Export all four pages to the global window scope ─────────────────────
Object.assign(window, { TopicsPage, PositionsPage, HealthPage, SettingsPage });
