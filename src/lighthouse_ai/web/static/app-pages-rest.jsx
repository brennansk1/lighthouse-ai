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
    return new Date(dateStr).toLocaleDateString(undefined,
      { month: 'short', day: 'numeric', year: 'numeric' });
  } catch (e) { return String(dateStr); }
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
            This won't delete existing jobs but will stop future collection for this topic.
            This action cannot be undone.
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
  const jobCount = t.job_count != null ? t.job_count : (t.source_count != null ? t.source_count : 0);
  return (
    <div className="r-topic-card"
      style={{ ...window.card, padding: 20, display: 'flex', flexDirection: 'column', gap: 10,
        borderTop: `3px solid ${accent}` }}>
      {/* Delete button — top-right, appears on card hover */}
      <button
        onClick={onDelete}
        className="r-del-btn"
        aria-label={`Delete topic ${t.name}`}
        title="Delete topic"
        style={{ position: 'absolute', top: 10, right: 10, background: 'none', border: 'none',
          cursor: 'pointer', fontSize: 13, color: 'var(--muted)', padding: '2px 5px',
          borderRadius: 4, lineHeight: 1 }}>
        ✕
      </button>

      {/* Topic name */}
      <div style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
        color: 'var(--ink)', lineHeight: 1.3, paddingRight: 20 }}>
        {t.name || 'Untitled'}
      </div>

      {/* Description — 3-line clamp */}
      {t.description && (
        <div style={{ fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.55,
          display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
          overflow: 'hidden' }}>
          {t.description}
        </div>
      )}

      {/* Query mono chip */}
      {t.query && (
        <div style={{ display: 'flex', minWidth: 0 }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11,
            background: 'var(--sky-soft)', color: 'var(--ink-2)',
            padding: '3px 9px', borderRadius: 'var(--radius-sm)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            maxWidth: '100%' }}>
            {t.query}
          </span>
        </div>
      )}

      {/* Footer row: job count + mode */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8,
        marginTop: 'auto', paddingTop: 4 }}>
        {jobCount > 0 && (
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700,
            background: 'var(--primary)', color: '#fff', padding: '2px 8px',
            borderRadius: 10 }}>
            {jobCount} {jobCount === 1 ? 'job' : 'jobs'}
          </span>
        )}
        {t.mode && (
          <span style={{ fontSize: 11, color: 'var(--muted)',
            textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {t.mode}
          </span>
        )}
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
  const [description, setDescription] = rUseState('');
  const [query, setQuery] = rUseState('');
  const [busy, setBusy] = rUseState(false);
  const [errors, setErrors] = rUseState({});
  const Btn = window.Btn;

  function validate() {
    const e = {};
    if (!name.trim()) e.name = 'Name is required.';
    if (!query.trim()) e.query = 'Query string is required.';
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function submit() {
    if (!validate()) return;
    setBusy(true);
    try {
      await window.apiPost('/api/topics', {
        name: name.trim(),
        description: description.trim() || undefined,
        query: query.trim(),
      });
      onCreated();
    } catch (e) {
      toast.show(e.message || 'Create failed', 'error');
      setBusy(false);
    }
  }

  return (
    <RModal title="New Research Topic" onClose={onClose}>
      <RField label="Name *" error={errors.name}>
        <input
          value={name}
          onChange={(e) => { setName(e.target.value); setErrors((er) => ({ ...er, name: '' })); }}
          placeholder="e.g. EU AI Act"
          style={{ ...rInput, borderColor: errors.name ? 'var(--coral-2)' : undefined }}
          aria-label="Topic name"
          autoFocus
        />
      </RField>
      <RField label="Description" hint="Optional — what are you watching for?">
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          placeholder="Regulatory developments and enforcement decisions…"
          style={{ ...rInput, resize: 'vertical' }}
          aria-label="Topic description"
        />
      </RField>
      <RField label="Query string *" error={errors.query}
        hint={!errors.query ? 'A keyword expression to guide collection.' : undefined}>
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setErrors((er) => ({ ...er, query: '' })); }}
          placeholder='e.g. AI regulation OR "foundation models"'
          style={{ ...rInput, borderColor: errors.query ? 'var(--coral-2)' : undefined }}
          aria-label="Topic query string"
        />
      </RField>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
        <Btn kind="ghost" onClick={onClose} disabled={busy}>Cancel</Btn>
        <Btn onClick={submit} disabled={busy}>{busy ? 'Creating…' : 'Create topic'}</Btn>
      </div>
    </RModal>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  POSITIONS PAGE
// ════════════════════════════════════════════════════════════════════════════
function PositionsPage({ toast }) {
  const [tab, setTab] = rUseState('Pending');
  const { data: allData, reload: reloadAll } = window.useApi('/api/positions');
  const allPositions = (allData && allData.positions) || [];

  const resolved = allPositions.filter((p) => p.resolved || p.outcome != null);
  const pending  = allPositions.filter((p) => !p.resolved && p.outcome == null);

  // Brier score over resolved positions
  function computeBrier(positions) {
    const valid = positions.filter(
      (p) => p.probability != null &&
        (p.outcome === true || p.outcome === false ||
         p.outcome === 'confirmed' || p.outcome === 'refuted')
    );
    if (!valid.length) return null;
    const sum = valid.reduce((acc, p) => {
      const prob = Number(p.probability);
      const out  = (p.outcome === true || p.outcome === 'confirmed') ? 1 : 0;
      return acc + Math.pow(prob - out, 2);
    }, 0);
    return sum / valid.length;
  }

  const brier = computeBrier(resolved);

  function brierInfo(b) {
    if (b == null) return { label: 'No data yet',  color: 'var(--muted)' };
    if (b < 0.1)   return { label: 'Excellent',    color: 'var(--green-dark)' };
    if (b < 0.2)   return { label: 'Good',         color: '#0aa' };
    if (b < 0.25)  return { label: 'Fair',         color: 'var(--sand)' };
    return               { label: 'Needs work',    color: 'var(--coral-2)' };
  }
  const bi = brierInfo(brier);

  // SSE refresh
  window.useEvents(rUseCallback((name) => {
    if (name === 'position.resolved') reloadAll();
  }, [reloadAll]));

  return (
    <div>
      <window.PageHeader
        title="Calibration"
        subtitle="Track predictions and measure forecasting accuracy"
        tabs={['Pending', 'Resolved']}
        activeTab={tab}
        onTab={setTab}
      />

      {/* Calibration summary — always visible */}
      <div style={{ ...window.card, padding: '16px 22px', marginBottom: 20,
        display: 'flex', gap: 36, alignItems: 'center', flexWrap: 'wrap' }}>
        {/* Brier score */}
        <div>
          <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.07em', marginBottom: 4 }}>Brier Score</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            {/* Optionally use window.BrierScore if available */}
            {window.BrierScore && resolved.length > 0
              ? <window.BrierScore value={brier} />
              : (
                <span className="num"
                  style={{ fontSize: 26, fontWeight: 700, color: bi.color }}>
                  {brier != null ? brier.toFixed(3) : '—'}
                </span>
              )
            }
            <span style={{ fontSize: 12, color: bi.color, fontWeight: 600 }}>{bi.label}</span>
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
      </div>

      {tab === 'Pending'  && (
        <RPositionList key="pending"  filterFn={(p) => !p.resolved && p.outcome == null}
          isPending toast={toast} />
      )}
      {tab === 'Resolved' && (
        <RPositionList key="resolved" filterFn={(p) => p.resolved || p.outcome != null}
          isResolved toast={toast} />
      )}
    </div>
  );
}

function RPositionList({ filterFn, isPending, isResolved, toast }) {
  const { data, loading, error, reload } = window.useApi('/api/positions');
  const [sel, setSel] = rUseState(null);

  const rawPositions = (data && data.positions) || [];
  const positions = rawPositions.filter(filterFn);

  // SSE
  window.useEvents(rUseCallback((name) => {
    if (name === 'position.resolved') { reload(); setSel(null); }
  }, [reload]));

  async function resolve(id, outcome) {
    try {
      await window.apiPost(`/api/positions/${id}/resolve`, { outcome });
      reload();
      toast.show(
        outcome === 'defer' ? 'Position deferred 30 days' : 'Position resolved',
        'success'
      );
      setSel(null);
    } catch (e) {
      toast.show(e.message || 'Resolve failed', 'error');
    }
  }

  if (loading) return <RTableSkeleton rows={5} />;
  if (error)   return <window.ErrorBox message={`Could not load positions — ${error}`} />;

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
    <div style={{ display: 'grid',
      gridTemplateColumns: sel ? '1fr minmax(320px, 380px)' : '1fr',
      gap: 16, alignItems: 'start' }}>

      {/* Position list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {positions.map((p) => {
          const isSelected = sel && sel.id === p.id;
          const prob = p.probability != null ? p.probability : p.confidence;
          const isOpen = !p.resolved && p.outcome == null;

          return (
            <div
              key={p.id}
              onClick={() => setSel(isSelected ? null : p)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') setSel(isSelected ? null : p);
              }}
              aria-selected={isSelected}
              style={{ ...window.card, padding: '14px 18px', cursor: 'pointer',
                border: `1px solid ${isSelected ? 'var(--primary)' : 'transparent'}`,
                transition: 'border-color .15s',
                outline: 'none' }}>
              {/* Claim text — 2-line clamp */}
              <div style={{ fontFamily: 'var(--serif)', fontSize: 14.5, color: 'var(--ink)',
                lineHeight: 1.45, display: '-webkit-box', WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical', overflow: 'hidden', marginBottom: 9 }}>
                {p.claim || '(no claim text)'}
              </div>

              {/* Meta row */}
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                {prob != null && (
                  <window.ConfidencePill
                    phrase={p.wep_band || p.wep_phrase || ''}
                    band={String(prob)}
                  />
                )}
                {prob != null && (
                  <span className="num" style={{ fontSize: 12.5,
                    color: 'var(--ink-2)', fontWeight: 600 }}>
                    {(prob * 100).toFixed(0)}%
                  </span>
                )}
                {p.created_at && (
                  <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
                    {fmtDate(p.created_at)}
                  </span>
                )}
                {p.due_at && (
                  <span style={{ fontSize: 11.5, color: 'var(--sand)', fontWeight: 600 }}>
                    due {fmtDate(p.due_at)}
                  </span>
                )}
                {!isOpen && (
                  <span style={{ fontSize: 12, fontWeight: 700,
                    color: (p.outcome === 'refuted' || p.outcome === false)
                      ? 'var(--coral-2)' : 'var(--green-dark)' }}>
                    {p.outcome === false ? 'refuted'
                      : p.outcome === true ? 'confirmed' : p.outcome}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Detail pane */}
      {sel && (
        <RSidePane title="Position" onClose={() => setSel(null)}>
          {/* Full claim text */}
          <div style={{ fontFamily: 'var(--serif)', fontSize: 15.5, color: 'var(--ink)',
            lineHeight: 1.6, marginBottom: 18 }}>
            {sel.claim}
          </div>

          {/* Probability bar */}
          {(() => {
            const prob = sel.probability != null ? sel.probability : sel.confidence;
            if (prob == null) return null;
            return (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
                  letterSpacing: '0.07em', marginBottom: 6 }}>Probability</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ flex: 1 }}>
                    <window.Bar value={prob} max={1} color="var(--primary)" />
                  </div>
                  <span className="num" style={{ fontSize: 14, fontWeight: 700,
                    color: 'var(--ink)', whiteSpace: 'nowrap' }}>
                    {(prob * 100).toFixed(0)}%
                  </span>
                </div>
                {/* WEP band chip */}
                {(sel.wep_band || sel.wep_phrase) && (
                  <div style={{ marginTop: 8 }}>
                    {window.WepBar
                      ? <window.WepBar band={sel.wep_band || sel.wep_phrase} />
                      : (
                        <span className="wep" style={{ fontSize: 11 }}>
                          {sel.wep_band || sel.wep_phrase}
                        </span>
                      )}
                  </div>
                )}
              </div>
            );
          })()}

          {/* Resolved outcome + Brier */}
          {(sel.resolved || sel.outcome != null) && (
            <div style={{ marginBottom: 14, padding: '10px 14px', borderRadius: 8,
              background: (sel.outcome === false || sel.outcome === 'refuted')
                ? 'rgba(240,80,80,0.07)' : 'rgba(6,214,160,0.07)',
              border: `1px solid ${
                (sel.outcome === false || sel.outcome === 'refuted')
                  ? 'var(--coral-2)' : 'var(--green-dark)'}` }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                letterSpacing: '0.06em', marginBottom: 3 }}>Outcome</div>
              <div style={{ fontWeight: 700, fontSize: 14,
                color: (sel.outcome === false || sel.outcome === 'refuted')
                  ? 'var(--coral-2)' : 'var(--green-dark)' }}>
                {sel.outcome === false ? 'Refuted (false)'
                  : sel.outcome === true ? 'Confirmed (true)'
                  : String(sel.outcome)}
              </div>
              {sel.brier != null && (
                <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                  Brier score: <strong>{Number(sel.brier).toFixed(3)}</strong>
                </div>
              )}
            </div>
          )}

          {/* Metadata rows */}
          {sel.created_at && <RRow k="Created"  v={fmtDate(sel.created_at)} />}
          {sel.due_at      && <RRow k="Due"      v={fmtDate(sel.due_at)}     />}
          {sel.resolved_at && <RRow k="Resolved" v={fmtDate(sel.resolved_at)} />}

          {/* Resolve buttons — only for pending positions */}
          {!sel.resolved && sel.outcome == null && (
            <div style={{ marginTop: 20 }}>
              <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
                letterSpacing: '0.07em', marginBottom: 10 }}>Resolve this position</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <button
                  onClick={() => resolve(sel.id, 'confirmed')}
                  aria-label="Mark outcome as true"
                  style={{ background: 'var(--green-dark)', color: '#fff', border: 'none',
                    borderRadius: 'var(--radius)', padding: '9px 16px', cursor: 'pointer',
                    fontSize: 13, fontWeight: 600, fontFamily: 'var(--sans)',
                    textAlign: 'left' }}>
                  ✓ True outcome — confirmed
                </button>
                <button
                  onClick={() => resolve(sel.id, 'refuted')}
                  aria-label="Mark outcome as false"
                  style={{ background: 'var(--coral-2)', color: '#fff', border: 'none',
                    borderRadius: 'var(--radius)', padding: '9px 16px', cursor: 'pointer',
                    fontSize: 13, fontWeight: 600, fontFamily: 'var(--sans)',
                    textAlign: 'left' }}>
                  ✕ False outcome — refuted
                </button>
                <button
                  onClick={() => resolve(sel.id, 'defer')}
                  aria-label="Defer this position 30 days"
                  className="btn-ghost"
                  style={{ padding: '9px 16px', fontSize: 13, fontWeight: 600,
                    textAlign: 'left' }}>
                  — Defer 30 days
                </button>
              </div>
            </div>
          )}
        </RSidePane>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  HEALTH PAGE
// ════════════════════════════════════════════════════════════════════════════
function HealthPage({ toast }) {
  const [lastRefreshed, setLastRefreshed] = rUseState(null);
  const [elapsed, setElapsed] = rUseState(0);
  const [reloading, setReloading] = rUseState(false);

  const { data, loading, error, reload } = window.useApi('/api/health');
  const { data: govData } = window.useApi('/api/governor');

  const h   = data   || {};
  const gov = govData || {};

  const hw     = h.hardware || {};
  const budget = h.budget   || {};
  const checks = h.checks   || [];

  const govTier = gov.tier || budget.tier || '—';
  const degraded = gov.degraded || govTier === 'degrade' || govTier === 'tripped';
  const tripped  = gov.tripped  || govTier === 'tripped';

  const allOk    = checks.length > 0 && checks.every((c) => c.ok !== false && c.status !== 'fail');
  const failCount = checks.filter((c) => c.ok === false || c.status === 'fail').length;

  const statusColor = tripped  ? 'var(--coral-2)'
    : degraded ? '#d98020'
    : allOk && checks.length  ? 'var(--green-dark)'
    : 'var(--muted)';

  // Auto-poll every 15s
  rUseEffect(() => {
    setLastRefreshed(Date.now());
    setElapsed(0);
    const pollId = setInterval(() => {
      reload();
      setLastRefreshed(Date.now());
      setElapsed(0);
    }, 15000);
    return () => clearInterval(pollId);
  }, []); // eslint-disable-line

  // 1-second elapsed tick
  rUseEffect(() => {
    const tickId = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(tickId);
  }, []);

  async function manualRecheck() {
    setReloading(true);
    reload();
    setLastRefreshed(Date.now());
    setElapsed(0);
    // Small delay so the loading spinner is visible
    await new Promise((r) => setTimeout(r, 400));
    setReloading(false);
  }

  function govChipClass(t) {
    if (!t || t === '—') return 'lh-tier-chip lh-tier-unknown';
    const key = String(t).toLowerCase().replace(/[^a-z_]/g, '_');
    return `lh-tier-chip lh-tier-${key}`;
  }

  const Btn = window.Btn;

  return (
    <div>
      <window.PageHeader
        title="System Health"
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ fontSize: 11.5, color: 'var(--muted)', fontFamily: 'var(--sans)' }}>
              {lastRefreshed
                ? `Last checked: ${elapsed}s ago`
                : 'Checking…'}
            </span>
            <Btn kind="ghost" onClick={manualRecheck} disabled={reloading}
              aria-label="Re-check health now">
              {reloading ? 'Checking…' : 'Re-check'}
            </Btn>
          </div>
        }
      />

      {/* Overall status banner */}
      {!loading && data && (
        <div style={{ padding: '10px 16px', borderRadius: 'var(--radius)',
          marginBottom: 18, fontSize: 13, fontWeight: 600, fontFamily: 'var(--sans)',
          background: allOk
            ? 'rgba(6,214,160,0.09)'
            : failCount > 0 ? 'rgba(255,152,100,0.12)' : 'var(--rule-soft)',
          color: allOk ? 'var(--green-dark)' : failCount > 0 ? '#c05a20' : 'var(--muted)',
          border: `1px solid ${allOk ? 'var(--green-dark)' : failCount > 0 ? '#c05a20' : 'var(--rule)'}` }}>
          {allOk
            ? '✓ All systems operational'
            : failCount > 0 ? `⚠ ${failCount} check${failCount > 1 ? 's' : ''} need attention`
            : '— Health data loading…'}
        </div>
      )}

      {loading && !data && <RTableSkeleton rows={6} />}
      {!loading && error && (
        <window.ErrorBox message={`Could not reach the health endpoint — ${error}`} />
      )}

      {(data || (!loading && !error)) && (
        <div style={{ display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 16, alignItems: 'start' }}>

          {/* ── System column ─────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14 }}>
              System
            </div>

            {/* Status light + tier badge */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
              <span
                role="img"
                aria-label={tripped ? 'tripped' : degraded ? 'degraded' : 'healthy'}
                style={{ width: 10, height: 10, borderRadius: '50%',
                  background: statusColor, display: 'inline-block', flexShrink: 0,
                  boxShadow: `0 0 6px ${statusColor}` }}
              />
              <span style={{ fontSize: 13, color: 'var(--ink)', fontWeight: 600 }}>
                {tripped ? 'Tripped' : degraded ? 'Degraded' : 'Healthy'}
              </span>
            </div>

            {/* Hardware tier — big badge */}
            {hw.tier && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
                  letterSpacing: '0.06em', marginBottom: 5 }}>Hardware tier</div>
                <span className={govChipClass(hw.tier)} style={{ fontSize: 12 }}>
                  {hw.tier}
                </span>
              </div>
            )}

            <RRow k="Model" v={hw.model || h.version || '—'} />
            <RRow k="RAM"   v={hw.ram_gb != null ? `${hw.ram_gb} GB`
              : hw.total_ram_gb != null ? `${hw.total_ram_gb} GB` : '—'} />
            <RRow k="Version" v={h.version || '—'} />
          </div>

          {/* ── Budget column ─────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
                textTransform: 'uppercase', letterSpacing: '0.08em' }}>Budget</div>
              <span className={govChipClass(govTier)}>{govTier}</span>
            </div>

            {budget.usd && (() => {
              const used = Number(budget.usd.used || 0);
              const cap  = Number(budget.usd.cap  || 0);
              const ratio = cap > 0 ? used / cap : 0;
              const hot = ratio > 0.85;
              return (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 12, color: 'var(--ink-2)', marginBottom: 6 }}>
                    <span>Cloud USD</span>
                    <span className="num" style={{ color: hot ? 'var(--coral-2)' : 'var(--ink)' }}>
                      ${used.toFixed(2)} / ${cap.toFixed(0)}/mo
                    </span>
                  </div>
                  <window.Bar value={used} max={cap || 1}
                    color={hot ? 'var(--coral-2)' : 'var(--primary)'} />
                </div>
              );
            })()}

            {budget.tokens && (() => {
              const used = Number(budget.tokens.used || 0);
              const cap  = Number(budget.tokens.cap  || 0);
              const hot  = cap > 0 && used / cap > 0.85;
              return (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 12, color: 'var(--ink-2)', marginBottom: 6 }}>
                    <span>Tokens</span>
                    <span className="num" style={{ color: hot ? 'var(--coral-2)' : 'var(--ink)' }}>
                      {(used / 1e6).toFixed(1)}M / {(cap / 1e6).toFixed(1)}M/day
                    </span>
                  </div>
                  <window.Bar value={used} max={cap || 1}
                    color={hot ? 'var(--coral-2)' : 'var(--primary)'} />
                </div>
              );
            })()}

            {gov.usd_remaining != null && (
              <RRow k="USD remaining" v={`$${Number(gov.usd_remaining).toFixed(2)}`} />
            )}
            {gov.tokens_remaining != null && (
              <RRow k="Tokens remaining"
                v={`${(Number(gov.tokens_remaining) / 1e6).toFixed(2)}M`} />
            )}

            {!budget.usd && !budget.tokens && !gov.usd_remaining && (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                No budget data reported yet.
              </div>
            )}
          </div>

          {/* ── Checks column ─────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14 }}>
              Checks
            </div>

            {checks.length === 0 && (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                No checks reported by backend.
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {checks.map((c, i) => <RCheckRow key={c.name || i} check={c} />)}
            </div>
          </div>

        </div>
      )}
    </div>
  );
}

function RCheckRow({ check }) {
  const [open, setOpen] = rUseState(false);
  const ok       = check.ok !== false && check.status !== 'fail';
  const hasDetail = !ok && !!check.detail;

  return (
    <div style={{ borderBottom: '1px solid var(--rule-soft)' }}>
      <div
        style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 13,
          padding: '8px 0', cursor: hasDetail ? 'pointer' : 'default' }}
        onClick={hasDetail ? () => setOpen((o) => !o) : undefined}
        role={hasDetail ? 'button' : undefined}
        tabIndex={hasDetail ? 0 : undefined}
        onKeyDown={hasDetail ? (e) => { if (e.key === 'Enter') setOpen((o) => !o); } : undefined}
        aria-expanded={hasDetail ? open : undefined}>
        <span
          aria-label={ok ? 'passing' : 'failing'}
          style={{ fontSize: 14, lineHeight: 1, flexShrink: 0,
            color: ok ? 'var(--green-dark)' : 'var(--coral-2)' }}>
          {ok ? '✓' : '✕'}
        </span>
        <span style={{ flex: 1, fontWeight: 500, color: 'var(--ink)' }}>
          {check.name}
        </span>
        {hasDetail && (
          <span style={{ fontSize: 10.5, color: 'var(--muted)' }}>
            {open ? '▾' : '▸'} detail
          </span>
        )}
      </div>

      {hasDetail && open && (
        <div style={{ paddingLeft: 24, paddingBottom: 8, paddingTop: 2,
          fontSize: 11.5, color: 'var(--coral-2)', fontFamily: 'var(--mono)',
          wordBreak: 'break-word', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
          {check.detail}
        </div>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
//  SETTINGS PAGE
// ════════════════════════════════════════════════════════════════════════════
function SettingsPage({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/settings');
  const [form, setForm] = rUseState(null);
  const [dirty, setDirty] = rUseState(false);
  const [saving, setSaving] = rUseState(false);
  const [saved, setSaved] = rUseState(false);
  const [doctorData, setDoctorData] = rUseState(null);
  const [doctorLoading, setDoctorLoading] = rUseState(false);
  const [copied, setCopied] = rUseState(false);
  const Btn = window.Btn;

  // Sync form from fetched data — only on first load
  rUseEffect(() => {
    if (data && !form) {
      setForm({
        data_dir:       data.data_dir       || '',
        offline_mode:   !!data.offline_mode,
        backup_enabled: !!data.backup_enabled,
        notify_enabled: !!data.notify_enabled,
        theme:          data.theme          || 'system',
      });
    }
  }, [data]); // eslint-disable-line

  function patch(key, val) {
    setForm((f) => ({ ...f, [key]: val }));
    setDirty(true);
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    try {
      await window.apiPatch('/api/settings', form);
      setDirty(false);
      setSaved(true);
      toast.show('Settings saved', 'success');
      reload();
      // Clear "Saved" label after 2.5s
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      toast.show(e.message || 'Save failed', 'error');
    }
    setSaving(false);
  }

  async function copyDataDir() {
    try {
      await navigator.clipboard.writeText(form.data_dir || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch (e) {
      toast.show('Could not copy to clipboard', 'error');
    }
  }

  async function runDiagnostics() {
    setDoctorLoading(true);
    setDoctorData(null);
    try {
      const d = await window.apiGet('/api/health');
      setDoctorData(d);
    } catch (e) {
      toast.show(e.message || 'Diagnostics failed', 'error');
    }
    setDoctorLoading(false);
  }

  if (loading && !form) return <RTableSkeleton rows={8} />;
  if (error   && !form) return <window.ErrorBox message={`Could not load settings — ${error}`} />;
  if (!form)            return <RTableSkeleton rows={8} />;

  const doctorChecks   = (doctorData && doctorData.checks)  || [];
  const doctorFailCount = doctorChecks.filter((c) => c.ok === false || c.status === 'fail').length;

  return (
    <div>
      <window.PageHeader
        title="Settings"
        actions={
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {/* Unsaved changes indicator */}
            {dirty && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 5,
                fontSize: 12, color: '#a07a00', fontWeight: 600, fontFamily: 'var(--sans)' }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%',
                  background: '#c99a00', display: 'inline-block', flexShrink: 0 }} />
                Unsaved changes
              </span>
            )}
            <Btn onClick={save} disabled={saving || !dirty}>
              {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save changes'}
            </Btn>
          </div>
        }
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 640 }}>

        {/* ── General ──────────────────────────────────────────────────── */}
        <RSettingsSection title="General">
          {/* Data dir — read-only + copy button */}
          <RField label="Data directory" hint="Location of the Lighthouse data folder on disk.">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                readOnly
                value={form.data_dir}
                style={{ ...rInput, background: 'var(--rule-soft)', color: 'var(--ink-2)',
                  cursor: 'default', flex: 1 }}
                aria-label="Data directory path (read-only)"
              />
              <button
                onClick={copyDataDir}
                aria-label="Copy data directory path"
                style={{ padding: '8px 12px', fontSize: 12, background: 'var(--card)',
                  border: '1px solid var(--rule)', borderRadius: 6, cursor: 'pointer',
                  color: copied ? 'var(--green-dark)' : 'var(--muted)',
                  fontFamily: 'var(--sans)', flexShrink: 0, transition: 'color .2s' }}>
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
          </RField>
          <RToggleRow
            label="Offline mode"
            hint="Disables all cloud model calls — uses local models only."
            value={form.offline_mode}
            onChange={(v) => patch('offline_mode', v)}
            id="s-offline"
          />
        </RSettingsSection>

        {/* ── Backup ───────────────────────────────────────────────────── */}
        <RSettingsSection title="Backup">
          <RToggleRow
            label="Enable backup"
            hint="Stream SQLite WAL to configured replicas via Litestream."
            value={form.backup_enabled}
            onChange={(v) => patch('backup_enabled', v)}
            id="s-backup"
          />
        </RSettingsSection>

        {/* ── Notifications ────────────────────────────────────────────── */}
        <RSettingsSection title="Notifications">
          <RToggleRow
            label="Enable notifications"
            hint="Send alerts via configured channels (Telegram, etc.)."
            value={form.notify_enabled}
            onChange={(v) => patch('notify_enabled', v)}
            id="s-notify"
          />
        </RSettingsSection>

        {/* ── Appearance ───────────────────────────────────────────────── */}
        <RSettingsSection title="Appearance">
          <RField label="Theme">
            <select
              value={form.theme}
              onChange={(e) => patch('theme', e.target.value)}
              style={rInput}
              aria-label="Theme selection">
              <option value="light">Light</option>
              <option value="dark">Dark</option>
              <option value="system">System (auto)</option>
            </select>
          </RField>
        </RSettingsSection>

        {/* ── Doctor ───────────────────────────────────────────────────── */}
        <RSettingsSection title="Doctor">
          <div style={{ marginBottom: 14, fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.5 }}>
            Run a full diagnostics pass against the live health endpoint to surface
            any configuration or connectivity issues.
          </div>
          <Btn kind="ghost" onClick={runDiagnostics} disabled={doctorLoading}>
            {doctorLoading ? 'Running diagnostics…' : 'Run diagnostics'}
          </Btn>

          {/* Results — fade in */}
          {doctorData && (
            <div className="r-doctor-results" style={{ marginTop: 16 }}>
              {/* Overall verdict */}
              <div style={{ padding: '8px 14px', borderRadius: 8, marginBottom: 12,
                fontSize: 13, fontWeight: 700,
                background: doctorFailCount === 0
                  ? 'rgba(6,214,160,0.09)' : 'rgba(255,152,100,0.1)',
                color: doctorFailCount === 0
                  ? 'var(--green-dark)' : '#c05a20',
                border: `1px solid ${doctorFailCount === 0
                  ? 'var(--green-dark)' : '#c05a20'}` }}>
                {doctorFailCount === 0
                  ? '✓ All good — no issues found'
                  : `⚠ ${doctorFailCount} issue${doctorFailCount > 1 ? 's' : ''} found`}
              </div>

              {doctorChecks.length === 0 && (
                <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                  No checks returned from the health endpoint.
                </div>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {doctorChecks.map((c, i) => <RCheckRow key={c.name || i} check={c} />)}
              </div>
            </div>
          )}
        </RSettingsSection>

      </div>
    </div>
  );
}

// ── Export all four pages to the global window scope ─────────────────────
Object.assign(window, { TopicsPage, PositionsPage, HealthPage, SettingsPage });
