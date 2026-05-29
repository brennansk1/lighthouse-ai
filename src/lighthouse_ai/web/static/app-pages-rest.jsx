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

// Translate the /api/health payload into a uniform list of { name, ok, detail }
// pass/fail rows. The endpoint reports database integrity, external service
// reachability, the audit chain, and outbox depth as separate fields; this turns
// them into plain rows a researcher can scan. Shared by the Health page and the
// Settings → Doctor diagnostics.
function buildHealthChecks(h) {
  if (!h) return [];
  const out = [];
  const dbs = h.databases || {};
  Object.entries(dbs).forEach(([name, status]) => {
    const ok = status === 'ok';
    out.push({ name: `${name} database`, ok, detail: ok ? null : `Integrity: ${status}` });
  });
  const ext = h.external || {};
  const EXT_LABELS = {
    ollama: 'Local model service (Ollama)',
    qdrant: 'Vector search (Qdrant)',
    litestream: 'Backup streaming (Litestream)',
  };
  Object.entries(ext).forEach(([name, up]) => {
    out.push({ name: EXT_LABELS[name] || name, ok: !!up, detail: up ? null : 'Not reachable' });
  });
  if (h.audit_chain_ok != null) {
    out.push({
      name: 'Audit chain integrity',
      ok: h.audit_chain_ok !== false,
      detail: h.audit_chain_ok === false ? 'Chain verification failed' : null,
    });
  }
  if (h.outbox_depth != null) {
    const ok = h.outbox_depth < 100;
    out.push({
      name: 'Outbox queue',
      ok,
      detail: ok ? null : `${h.outbox_depth} items pending — queue is backing up`,
    });
  }
  return out;
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
        title="Watch"
        subtitle="Define topics to follow over time, then schedule sessions that collect new material from your sources."
        actions={
          <Btn onClick={() => setShowNew(true)} aria-label="Add a topic to monitor">
            + Add topic
          </Btn>
        }
      />

      {/* What this tab is for — shown only when the researcher has topics,
          so the empty state can carry the explanation otherwise. */}
      {!loading && !error && topics.length > 0 && (
        <div style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.6,
          marginBottom: 22, maxWidth: '70ch' }}>
          A topic is a subject you want to keep an eye on — an entity, an issue, or a
          question. Each topic carries a query that guides what gets collected. Use the
          scheduler below to run a time-bounded session against specific sources.
        </div>
      )}

      <RMonitorSessions toast={toast} />

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
          icon="◎"
          title="No topics yet"
          hint="A topic is a subject you want to follow over time — an entity, an issue, or a question. Add one to start collecting material from your sources as it appears."
          action={<Btn onClick={() => setShowNew(true)}>+ Add your first topic</Btn>}
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
            {window.modeLabel ? window.modeLabel(t.mode) : t.mode}
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
  const [picked, setPicked] = rUseState([]); // watchable source ids
  const Btn = window.Btn;

  // Only sources that expose a watchable feed can be followed over time.
  const { data: srcData } = window.useApi('/api/sources', { pollMs: 0 });
  const watchable = ((srcData && srcData.sources) || []).filter((s) => s.watchable);

  function togglePick(id) {
    setPicked((p) => p.includes(id) ? p.filter((x) => x !== id) : [...p, id]);
  }

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
        sources: picked,
      });
      onCreated();
    } catch (e) {
      toast.show(e.message || 'Create failed', 'error');
      setBusy(false);
    }
  }

  return (
    <RModal title="Add a topic" onClose={onClose}>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.55,
        marginBottom: 16 }}>
        Name the subject you want to follow, then give a query that tells Lighthouse
        what to collect for it.
      </div>
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
      <RField label="Query *" error={errors.query}
        hint={!errors.query ? 'Keywords that decide what gets collected. Combine terms with OR, and quote exact phrases.' : undefined}>
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setErrors((er) => ({ ...er, query: '' })); }}
          placeholder='e.g. AI regulation OR "foundation models"'
          style={{ ...rInput, borderColor: errors.query ? 'var(--coral-2)' : undefined }}
          aria-label="Topic query string"
        />
      </RField>
      <RField label="Sources to follow"
        hint="Only sources with a live feed can be watched. Leave empty to watch general web + news.">
        {watchable.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--muted)', fontStyle: 'italic' }}>
            No watchable sources installed yet.
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, maxHeight: 140,
            overflowY: 'auto' }}>
            {watchable.map((s) => {
              const on = picked.includes(s.id);
              return (
                <button key={s.id} type="button" onClick={() => togglePick(s.id)}
                  aria-pressed={on}
                  style={{ fontSize: 12, padding: '4px 10px', borderRadius: 999,
                    cursor: 'pointer', fontFamily: 'var(--sans)',
                    border: on ? '1px solid var(--primary)' : '1px solid var(--rule)',
                    background: on ? 'var(--primary)' : 'var(--card)',
                    color: on ? '#fff' : 'var(--ink-2)' }}>
                  {s.name}
                </button>
              );
            })}
          </div>
        )}
      </RField>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
        <Btn kind="ghost" onClick={onClose} disabled={busy}>Cancel</Btn>
        <Btn onClick={submit} disabled={busy}>{busy ? 'Creating…' : 'Create topic'}</Btn>
      </div>
    </RModal>
  );
}

// ── Event sessions (time-bounded monitors) ─────────────────────────────────

const SESSION_STATUS_COLORS = {
  active: 'var(--primary)',
  paused: 'var(--muted)',
  ended: 'var(--ink-2)',
};

function RMonitorSessions({ toast }) {
  const { data, loading, reload } = window.useApi('/api/monitor/sessions', { pollMs: 30000 });
  const [showNew, setShowNew] = rUseState(false);
  const sessions = (data && data.sessions) || [];
  const Btn = window.Btn;

  async function stop(s) {
    try {
      await window.apiPost(`/api/monitor/sessions/${s.id}/stop`, {});
      reload();
      toast.show('Session stopped', 'info');
    } catch (e) {
      toast.show(e.message || 'Stop failed', 'error');
    }
  }

  return (
    <div style={{ ...window.card, padding: 20, marginBottom: 28 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)' }}>Scheduled sessions</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
            A session checks a set of sources on a fixed interval. It ends at a time you set,
            or stops on its own once the sources go quiet.
          </div>
        </div>
        <Btn onClick={() => setShowNew(true)} aria-label="Schedule a new session">
          + Schedule session
        </Btn>
      </div>

      {loading && <RSkeleton h={14} mb={8} />}

      {!loading && sessions.length === 0 && (
        <div style={{ fontSize: 13, color: 'var(--muted)', padding: '8px 0' }}>
          No sessions scheduled. Schedule one to collect from a set of sources over a
          fixed window — useful for following a hearing, a release, or a developing story.
        </div>
      )}

      {!loading && sessions.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sessions.map((s) => (
            <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 12,
              padding: '10px 12px', border: '1px solid var(--rule)', borderRadius: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                background: SESSION_STATUS_COLORS[s.status] || 'var(--muted)' }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {s.label}
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>
                  {s.source_urls.length} source{s.source_urls.length === 1 ? '' : 's'}
                  {' · '}{s.cycles} cycle{s.cycles === 1 ? '' : 's'}
                  {s.ends_at ? ` · ends ${s.ends_at}` : ' · auto-stop'}
                  {s.ended_reason ? ` · ${s.ended_reason}` : ''}
                </div>
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
                letterSpacing: '0.05em', color: SESSION_STATUS_COLORS[s.status] || 'var(--muted)' }}>
                {s.status}
              </span>
              {s.status === 'active' && (
                <Btn kind="ghost" onClick={() => stop(s)} aria-label={`Stop ${s.label}`}>Stop</Btn>
              )}
            </div>
          ))}
        </div>
      )}

      {showNew && (
        <RNewSessionModal
          toast={toast}
          onClose={() => setShowNew(false)}
          onCreated={() => { setShowNew(false); reload(); toast.show('Session created', 'success'); }}
        />
      )}
    </div>
  );
}

function RNewSessionModal({ toast, onClose, onCreated }) {
  const [label, setLabel] = rUseState('');
  const [urls, setUrls] = rUseState('');
  const [mode, setMode] = rUseState('auto'); // 'auto' | 'time'
  const [endsAt, setEndsAt] = rUseState('');
  const [pollMin, setPollMin] = rUseState(5);
  const [busy, setBusy] = rUseState(false);
  const [errors, setErrors] = rUseState({});
  const Btn = window.Btn;

  function validate() {
    const e = {};
    if (!label.trim()) e.label = 'Label is required.';
    if (!urls.trim()) e.urls = 'At least one source URL is required.';
    if (mode === 'time' && !endsAt.trim()) e.endsAt = 'End time is required for a timed session.';
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function submit() {
    if (!validate()) return;
    setBusy(true);
    const sourceUrls = urls.split(/[\n,]+/).map((u) => u.trim()).filter(Boolean);
    try {
      await window.apiPost('/api/monitor/sessions', {
        label: label.trim(),
        source_urls: sourceUrls,
        ends_at: mode === 'time' ? new Date(endsAt).toISOString() : null,
        auto_stop: mode === 'auto',
        poll_interval_s: Math.max(60, Math.round(pollMin * 60)),
      });
      onCreated();
    } catch (e) {
      toast.show(e.message || 'Create failed', 'error');
      setBusy(false);
    }
  }

  return (
    <RModal title="Schedule a session" onClose={onClose}>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.55,
        marginBottom: 16 }}>
        Point a session at one or more source feeds. Lighthouse checks them on the
        interval you set and stops at the end time, or once the feeds go quiet.
      </div>
      <RField label="Label *" error={errors.label}>
        <input
          value={label}
          onChange={(e) => { setLabel(e.target.value); setErrors((er) => ({ ...er, label: '' })); }}
          placeholder="e.g. Pam Bondi confirmation hearing"
          style={{ ...rInput, borderColor: errors.label ? 'var(--coral-2)' : undefined }}
          aria-label="Session label"
          autoFocus
        />
      </RField>
      <RField label="Source URLs *" error={errors.urls}
        hint={!errors.urls ? 'One RSS/Atom feed per line (or comma-separated).' : undefined}>
        <textarea
          value={urls}
          onChange={(e) => { setUrls(e.target.value); setErrors((er) => ({ ...er, urls: '' })); }}
          rows={3}
          placeholder="https://example.com/feed.xml"
          style={{ ...rInput, resize: 'vertical',
            borderColor: errors.urls ? 'var(--coral-2)' : undefined }}
          aria-label="Source URLs"
        />
      </RField>
      <RField label="Stop condition">
        <div style={{ display: 'flex', gap: 16, fontSize: 13, color: 'var(--ink-2)' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
            <input type="radio" name="stopmode" checked={mode === 'auto'}
              onChange={() => setMode('auto')} />
            Auto-stop when quiet
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
            <input type="radio" name="stopmode" checked={mode === 'time'}
              onChange={() => setMode('time')} />
            End at a set time
          </label>
        </div>
      </RField>
      {mode === 'time' && (
        <RField label="End time *" error={errors.endsAt}>
          <input
            type="datetime-local"
            value={endsAt}
            onChange={(e) => { setEndsAt(e.target.value); setErrors((er) => ({ ...er, endsAt: '' })); }}
            style={{ ...rInput, borderColor: errors.endsAt ? 'var(--coral-2)' : undefined }}
            aria-label="End time"
          />
        </RField>
      )}
      <RField label="Poll interval (minutes)" hint="How often to check the sources.">
        <input
          type="number"
          min={1}
          value={pollMin}
          onChange={(e) => setPollMin(Number(e.target.value) || 1)}
          style={{ ...rInput, width: 120 }}
          aria-label="Poll interval in minutes"
        />
      </RField>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
        <Btn kind="ghost" onClick={onClose} disabled={busy}>Cancel</Btn>
        <Btn onClick={submit} disabled={busy}>{busy ? 'Creating…' : 'Create session'}</Btn>
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
        title="Track"
        subtitle="Review the predictions Lighthouse has made and see how accurate they turn out to be."
        tabs={['Pending', 'Resolved']}
        activeTab={tab}
        onTab={setTab}
      />

      {/* Plain-language primer */}
      <div style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.6,
        marginBottom: 18, maxWidth: '72ch' }}>
        A position is a forecast about a claim, stated as a probability. It stays
        <strong> pending</strong> until the real outcome is known, then you mark it
        <strong> resolved</strong> as confirmed or refuted. Over many resolved positions,
        the Brier score below measures how well the stated probabilities matched reality —
        lower is better.
      </div>

      {/* Calibration summary — always visible */}
      <div style={{ ...window.card, padding: '16px 22px', marginBottom: 20,
        display: 'flex', gap: 36, alignItems: 'flex-start', flexWrap: 'wrap' }}>
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
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, maxWidth: '24ch' }}>
            0 is perfect; lower means better-calibrated forecasts.
          </div>
        </div>

        {/* Resolved count */}
        <div>
          <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.07em', marginBottom: 4 }}>Resolved</div>
          <span className="num" style={{ fontSize: 26, fontWeight: 700,
            color: 'var(--ink)' }}>{resolved.length}</span>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
            Outcome recorded
          </div>
        </div>

        {/* Pending count */}
        <div>
          <div style={{ fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.07em', marginBottom: 4 }}>Pending</div>
          <span className="num" style={{ fontSize: 26, fontWeight: 700,
            color: 'var(--ink)' }}>{pending.length}</span>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
            Awaiting outcome
          </div>
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
        hint="Once you mark a pending position as confirmed or refuted, it moves here with its outcome and its contribution to the Brier score."
      />
    );
  }

  // ── Render one position card. Reused across all groups. ──────────────────
  function renderCard(p) {
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
  }

  // ── Group positions into ordered sections. Pending → by timeline
  //    (Overdue / Due soon / Upcoming); Resolved → by outcome. ─────────────
  function buildGroups() {
    if (isResolved) {
      const buckets = { Confirmed: [], Refuted: [], Other: [] };
      for (const p of positions) {
        if (p.outcome === true || p.outcome === 'confirmed') buckets.Confirmed.push(p);
        else if (p.outcome === false || p.outcome === 'refuted') buckets.Refuted.push(p);
        else buckets.Other.push(p);
      }
      return [
        { key: 'Confirmed', label: 'Confirmed', color: 'var(--green-dark)', items: buckets.Confirmed },
        { key: 'Refuted',   label: 'Refuted',   color: 'var(--coral-2)',    items: buckets.Refuted },
        { key: 'Other',     label: 'Other',     color: 'var(--muted)',      items: buckets.Other },
      ];
    }
    const now = Date.now();
    const soonMs = 7 * 24 * 3600 * 1000;
    const buckets = { Overdue: [], Soon: [], Upcoming: [] };
    for (const p of positions) {
      const due = p.due_at ? new Date(p.due_at).getTime() : null;
      if (due != null && due < now) buckets.Overdue.push(p);
      else if (due != null && due - now <= soonMs) buckets.Soon.push(p);
      else buckets.Upcoming.push(p);
    }
    return [
      { key: 'Overdue',  label: 'Overdue',  color: 'var(--coral-2)', items: buckets.Overdue },
      { key: 'Soon',     label: 'Due soon', color: 'var(--sand)',    items: buckets.Soon },
      { key: 'Upcoming', label: 'Upcoming', color: 'var(--muted)',   items: buckets.Upcoming },
    ];
  }

  const groups = buildGroups().filter((g) => g.items.length > 0);

  return (
    <div style={{ display: 'grid',
      gridTemplateColumns: sel ? '1fr minmax(320px, 380px)' : '1fr',
      gap: 16, alignItems: 'start' }}>

      {/* Grouped position list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
        {groups.map((g) => (
          <div key={g.key}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: g.color,
                textTransform: 'uppercase', letterSpacing: '0.07em' }}>{g.label}</span>
              <span className="num" style={{ fontSize: 11, color: 'var(--muted)',
                background: 'rgba(106,138,166,0.12)', padding: '1px 7px', borderRadius: 999 }}>
                {g.items.length}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {g.items.map(renderCard)}
            </div>
          </div>
        ))}
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
                letterSpacing: '0.07em', marginBottom: 6 }}>Record the outcome</div>
              <div style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.5,
                marginBottom: 10 }}>
                Once the real result is known, mark it here. Defer if it is not yet decided.
              </div>
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

  const h   = data   || {};

  const hw     = h.hardware || {};
  const models = h.chosen_models || {};

  // Build the checks list from the live health payload (see buildHealthChecks).
  const checks = buildHealthChecks(h);

  // The backend gives an overall verdict; fall back to the per-check rollup.
  const overallGreen = h.overall ? h.overall === 'green'
    : (checks.length > 0 && checks.every((c) => c.ok));
  const tripped = false;
  const degraded = data != null && !overallGreen;

  const allOk    = checks.length > 0 && checks.every((c) => c.ok);
  const failCount = checks.filter((c) => !c.ok).length;

  const statusColor = degraded ? '#d98020'
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
        subtitle="Live view of this machine's hardware, the models chosen for it, and the services Lighthouse depends on."
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ fontSize: 11.5, color: 'var(--muted)', fontFamily: 'var(--sans)' }}>
              {lastRefreshed
                ? `Last checked ${elapsed}s ago`
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
            : '— Gathering diagnostics…'}
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
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6, lineHeight: 1.45 }}>
                  The capability band measured for this machine. It sets which models Lighthouse can run.
                </div>
              </div>
            )}

            <RRow k="Platform" v={hw.platform ? `${hw.platform}${hw.arch ? ` · ${hw.arch}` : ''}` : '—'} />
            <RRow k="Processor cores"
              v={hw.cpu_cores_logical != null
                ? `${hw.cpu_cores_logical}${hw.cpu_cores_physical != null
                    ? ` (${hw.cpu_cores_physical} physical)` : ''}`
                : '—'} />
            <RRow k="Graphics"
              v={(hw.gpu && hw.gpu.length)
                ? hw.gpu.map((g) => g.name + (g.vram_gb ? ` · ${g.vram_gb} GB` : '')).join(', ')
                : '—'} />
            <RRow k="Total RAM" v={hw.total_ram_gb != null ? `${hw.total_ram_gb} GB` : '—'} />
            <div style={{ fontSize: 11, color: 'var(--muted)', margin: '2px 0 6px' }}>
              Physical memory installed on this machine.
            </div>
            <RRow k="Free RAM" v={hw.free_ram_gb != null ? `${hw.free_ram_gb} GB` : '—'} />
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
              Headroom available right now for running models.
            </div>
          </div>

          {/* ── Models column ─────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
              Models for this hardware
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.45, marginBottom: 12 }}>
              The local model chosen for each task, sized to fit the measured hardware.
            </div>

            {Object.keys(models).length === 0 ? (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                No model selection reported yet.
              </div>
            ) : (
              Object.entries(models).map(([role, name]) => (
                <RRow key={role} k={role.replace(/_/g, ' ')} v={name} />
              ))
            )}
          </div>

          {/* ── Checks column ─────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
              Services and integrity
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.45, marginBottom: 12 }}>
              Databases, local services, and data integrity. Select a failing row to see the detail.
            </div>

            {checks.length === 0 && (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                No checks reported yet.
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {checks.map((c, i) => <RCheckRow key={c.name || i} check={c} />)}
            </div>
          </div>

          {/* ── Sources column ────────────────────────────────────────── */}
          <RSourceHealth />

        </div>
      )}
    </div>
  );
}

// Per-source health summary. The catalog (/api/sources) tells us which sources
// are installed and which need extra approval; live reachability + per-outlet
// error rates are not yet exposed by an endpoint.
// TODO(api): a /api/sources/health endpoint (last fetch, error rate, rate-limit
//            status, robots freshness per skill) would make this live rather
//            than a static catalog summary.
function RSourceHealth() {
  const { data, loading } = window.useApi('/api/sources', { pollMs: 0 });
  const sources = (data && Array.isArray(data.sources)) ? data.sources : [];
  const news = sources.filter((s) => (s.category || '').toLowerCase() === 'news'
    && s.id !== 'news_orchestrator');
  const tierC = sources.filter((s) => s.tier === 'C' || s.tierc_escalation);
  const noAuth = sources.length;

  return (
    <div style={{ ...window.card, padding: 20 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)',
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
        Sources
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.45, marginBottom: 12 }}>
        Which research sources are available on this machine. Manage trust in
        Settings → Sources &amp; trust.
      </div>

      {loading && !data && <RSkeleton h={14} mb={8} />}

      {!loading && (
        <React.Fragment>
          <RRow k="Sources installed" v={noAuth || '—'} />
          <RRow k="News outlets" v={news.length || '—'} />
          <RRow k="Need extra approval" v={tierC.length} />
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 12, lineHeight: 1.5 }}>
            For live news reachability and bias overlays, run{' '}
            <code style={{ fontFamily: 'var(--mono)', fontSize: 11,
              background: 'var(--rule-soft)', padding: '1px 5px', borderRadius: 3 }}>
              lighthouse doctor news</code>.
          </div>
        </React.Fragment>
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
//  SOURCES & TRUST  (Settings §4 — News trust matrix, community skills, Tier-C)
// ════════════════════════════════════════════════════════════════════════════
//
// The catalog comes from GET /api/sources (SkillManifest.as_dict): id, name,
// category, tier, default_grade, community, authority, enabled_by_default,
// tierc_escalation. The §4 trust matrix also wants per-outlet *fetch status*
// (✓ / ◐ metadata-only / ✗ paywall-with-reason) and AllSides bias ratings —
// those are NOT in the catalog payload today (they live in the news_orchestrator
// skill + the `lighthouse doctor news` CLI). We surface what the API gives us
// and add the non-fetchable platform-invariant outlets from §4 as static rows
// so the user sees them with a reason rather than a silent omission.
//
// Trust toggles persist to localStorage only — there is no settings endpoint
// for per-source enablement yet. See TODO(api) notes below.

// Plain-language authority labels (mirror of the wizard's source picker).
const R_AUTHORITY_PLAIN = {
  peer_reviewed: 'peer-reviewed', wire_service: 'wire service',
  public_broadcaster: 'public broadcaster', investigative_nonprofit: 'investigative nonprofit',
  newspaper: 'newspaper', multi_outlet_composite: 'multi-outlet tool',
  government: 'government data', official: 'official data',
};
function rAuthorityPlain(a) {
  if (!a) return null;
  return R_AUTHORITY_PLAIN[a] || String(a).replace(/_/g, ' ');
}

// §4 platform-invariant outlets that are NOT fetchable (paywall / ToS) or are
// metadata-only. These are not in /api/sources because no skill ships for them;
// we show them so the trust matrix is honest about what cannot be read.
// TODO(api): expose fetch-status (✓/◐/✗ + reason) + AllSides rating per outlet
//            from the News Orchestrator so this list is data-driven, not hard-coded.
const R_NEWS_INVARIANTS = [
  { name: 'New York Times', status: 'partial', reason: 'metadata + abstract only (API terms)' },
  { name: 'Fox News', status: 'partial', reason: 'headlines via RSS only' },
  { name: 'Wall Street Journal', status: 'blocked', reason: 'paywall — body not fetchable' },
  { name: 'Bloomberg', status: 'blocked', reason: 'paywall / ToS — not fetchable' },
  { name: 'Financial Times', status: 'blocked', reason: 'paywall / ToS — not fetchable' },
];

const R_FETCH_STATUS = {
  ok:      { mark: '✓', label: 'Readable',      color: 'var(--green-dark)' },
  partial: { mark: '◐', label: 'Limited',       color: '#a07a00' },
  blocked: { mark: '✗', label: 'Not readable',  color: 'var(--coral-2)' },
};

function RFetchStatus({ status }) {
  const s = R_FETCH_STATUS[status] || R_FETCH_STATUS.ok;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
      fontSize: 12, fontWeight: 600, color: s.color }}>
      <span aria-hidden="true" style={{ fontSize: 13 }}>{s.mark}</span>
      {s.label}
    </span>
  );
}

// localStorage-backed trust set. Keyed by source id; absent = use default.
function useTrustOverrides() {
  const KEY = 'lh-source-trust';
  const [map, setMap] = rUseState(() => {
    try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; }
  });
  const setTrust = rUseCallback((id, on) => {
    setMap((prev) => {
      const next = { ...prev, [id]: on };
      try { localStorage.setItem(KEY, JSON.stringify(next)); } catch (e) { /* noop */ }
      return next;
    });
  }, []);
  const isTrusted = rUseCallback((src) => {
    if (Object.prototype.hasOwnProperty.call(map, src.id)) return !!map[src.id];
    return !!src.enabled_by_default;
  }, [map]);
  return { isTrusted, setTrust };
}

function RSourcesTrust({ toast }) {
  const { data, loading, error } = window.useApi('/api/sources', { pollMs: 0 });
  const { isTrusted, setTrust } = useTrustOverrides();
  const sources = (data && Array.isArray(data.sources)) ? data.sources : [];

  const news = sources.filter((s) => (s.category || '').toLowerCase() === 'news'
    && s.id !== 'news_orchestrator');
  const community = sources.filter((s) => s.community);
  const tierC = sources.filter((s) => s.tier === 'C' || s.tierc_escalation);

  function toggle(src) {
    const next = !isTrusted(src);
    setTrust(src.id, next);
    // TODO(api): persist trust to a real settings endpoint. No PATCH /api/sources
    //            or /api/settings field exists for per-source trust today, so the
    //            choice is remembered in this browser only.
    toast.show(
      `${src.name} ${next ? 'trusted' : 'muted'} (saved in this browser)`,
      'info');
  }

  return (
    <RSettingsSection title="Sources & trust">
      <div style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.55, marginBottom: 16 }}>
        Choose which sources Lighthouse may draw on, and see exactly what it can and
        cannot read. What we can't fetch is shown with the reason — never silently
        dropped.
        <span style={{ color: 'var(--muted)' }}>
          {' '}Trust choices are remembered in this browser.
        </span>
      </div>

      {loading && !data && <RSkeleton h={14} mb={8} />}
      {error && <window.ErrorBox message={`Could not load sources — ${error}`} />}

      {/* ── News outlets ─────────────────────────────────────────────── */}
      {news.length > 0 && (
        <div style={{ marginBottom: 22 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink)', marginBottom: 4 }}>
            News outlets
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 10, lineHeight: 1.45 }}>
            The seed outlets ship trusted and readable. Toggle any off to exclude it
            from news research.
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: 'left' }}>
                {['Outlet', 'Type', 'Can read?', 'Trusted'].map((h) => (
                  <th key={h} style={{ padding: '4px 8px', fontSize: 10.5, fontWeight: 700,
                    textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--muted)' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {news.map((s) => (
                <tr key={s.id} style={{ borderTop: '1px solid var(--rule-soft)' }}>
                  <td style={{ padding: '8px', fontWeight: 600, color: 'var(--ink)' }}>{s.name}</td>
                  <td style={{ padding: '8px', color: 'var(--ink-2)' }}>
                    {rAuthorityPlain(s.authority) || '—'}
                  </td>
                  <td style={{ padding: '8px' }}><RFetchStatus status="ok" /></td>
                  <td style={{ padding: '8px' }}>
                    <RToggle value={isTrusted(s)} onChange={() => toggle(s)} id={`trust-${s.id}`} />
                  </td>
                </tr>
              ))}
              {/* Platform-invariant outlets the user cannot enable (shown with reason). */}
              {R_NEWS_INVARIANTS.map((o) => (
                <tr key={o.name} style={{ borderTop: '1px solid var(--rule-soft)', opacity: 0.85 }}>
                  <td style={{ padding: '8px', fontWeight: 600, color: 'var(--ink-2)' }}>{o.name}</td>
                  <td style={{ padding: '8px', color: 'var(--muted)', fontSize: 11.5 }}>{o.reason}</td>
                  <td style={{ padding: '8px' }}><RFetchStatus status={o.status} /></td>
                  <td style={{ padding: '8px', fontSize: 11, color: 'var(--muted)' }}>
                    {o.status === 'blocked' ? 'unavailable' : 'limited'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8, lineHeight: 1.45 }}>
            Bias ratings (AllSides) and live reachability checks run from{' '}
            <code style={{ fontFamily: 'var(--mono)' }}>lighthouse doctor news</code>.
          </div>
        </div>
      )}

      {/* ── Community-contributed skills ─────────────────────────────── */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink)', marginBottom: 4 }}>
          Community-contributed sources
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 10, lineHeight: 1.45 }}>
          Unsigned sources from the community. They work, but findings that rely on
          them are marked lower-confidence. Off by default for deep research.
        </div>
        {community.length === 0 ? (
          <div style={{ fontSize: 12.5, color: 'var(--muted)', fontStyle: 'italic' }}>
            No community sources installed.
          </div>
        ) : (
          community.map((s) => (
            <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 12,
              padding: '8px 0', borderTop: '1px solid var(--rule-soft)' }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{s.name}</div>
                <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>{s.description}</div>
              </div>
              <RToggle value={isTrusted(s)} onChange={() => toggle(s)} id={`trust-${s.id}`} />
            </div>
          ))
        )}
      </div>

      {/* ── Tier-C trust allowlist ───────────────────────────────────── */}
      <div>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink)', marginBottom: 4 }}>
          Sources needing extra approval
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 10, lineHeight: 1.45 }}>
          A few sources can only be reached with browser-fingerprint techniques. They
          stay off until you approve them for a specific site.
        </div>
        {tierC.length === 0 ? (
          <div style={{ fontSize: 12.5, color: 'var(--muted)', fontStyle: 'italic' }}>
            None — every active source uses a clean, first-party fetch path.
          </div>
        ) : (
          tierC.map((s) => (
            <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 12,
              padding: '8px 0', borderTop: '1px solid var(--rule-soft)' }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{s.name}</div>
                <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>
                  {s.tierc_reason || 'Requires explicit per-site approval.'}
                </div>
              </div>
              <RToggle value={isTrusted(s)} onChange={() => toggle(s)} id={`trust-${s.id}`} />
            </div>
          ))
        )}
      </div>
    </RSettingsSection>
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

  const doctorChecks   = buildHealthChecks(doctorData);
  const doctorFailCount = doctorChecks.filter((c) => !c.ok).length;

  return (
    <div>
      <window.PageHeader
        title="Settings"
        subtitle="Configure how Lighthouse runs on this machine — sources and trust, storage, privacy, backups, notifications, and appearance."
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
          <RField label="Data directory" hint="Where Lighthouse keeps your collected material, databases, and logs on this machine.">
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
            hint="Keep all work on this machine. No data leaves your hardware; only local models are used."
            value={form.offline_mode}
            onChange={(v) => patch('offline_mode', v)}
            id="s-offline"
          />
        </RSettingsSection>

        {/* ── Sources & trust (§4 News matrix, community, Tier-C) ───────── */}
        <RSourcesTrust toast={toast} />

        {/* ── Backup ───────────────────────────────────────────────────── */}
        <RSettingsSection title="Backup">
          <RToggleRow
            label="Enable backup"
            hint="Continuously copy your data to the backup location you have configured, so it can be restored if needed."
            value={form.backup_enabled}
            onChange={(v) => patch('backup_enabled', v)}
            id="s-backup"
          />
        </RSettingsSection>

        {/* ── Notifications ────────────────────────────────────────────── */}
        <RSettingsSection title="Notifications">
          <RToggleRow
            label="Enable notifications"
            hint="Send an alert through your configured channel when a monitor finds something or a session ends."
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
            Run a full check of databases, local services, and data integrity to surface
            any configuration or connectivity issues. The same checks appear live on the
            System Health page.
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
