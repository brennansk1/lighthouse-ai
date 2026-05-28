// app-pages-rest.jsx — polished production versions of the four "instrument"
// pages: Topics · Positions · Health · Settings.
//
// Loaded via babel-standalone into ONE shared browser global scope (no module
// system). To avoid redeclaration collisions with app-pages.jsx (which also
// declares Modal/Field/Row/Metric/TopicsPage/…), every helper in this file is
// namespaced with an `R` prefix and the page components are assigned to window
// at the very bottom. Shared primitives (useApi, PageHeader, Btn, DataTable,
// ConfidencePill, StatusPill, Bar, EmptyState, ErrorBox, Loading, card) come
// from app-lib.jsx and are read off the global scope.

const { useState: rUseState, useEffect: rUseEffect, useRef: rUseRef, useCallback: rUseCallback } = React;

// ── tiny self-contained primitives (R-prefixed, no global collisions) ─────
const rInput = {
  fontFamily: 'var(--sans)', fontSize: 13, padding: '8px 10px',
  border: '1px solid var(--rule)', borderRadius: 6, color: 'var(--ink)',
  background: 'var(--card)', width: '100%',
};

function RField({ label, hint, children }) {
  return (
    <label style={{ display: 'block', marginBottom: 12 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', marginBottom: 4,
        textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      {children}
      {hint && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{hint}</div>}
    </label>
  );
}

function RRow({ k, v, accent }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, padding: '7px 0',
      borderBottom: '1px solid var(--rule-soft)', fontSize: 13 }}>
      <span style={{ color: 'var(--muted)' }}>{k}</span>
      <span style={{ color: accent || 'var(--ink)', fontWeight: 500, textAlign: 'right',
        wordBreak: 'break-word' }}>{v == null || v === '' ? '—' : String(v)}</span>
    </div>
  );
}

function RMetric({ label, value, hint, accent }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
        letterSpacing: '0.06em' }}>{label}</div>
      <div className="num" style={{ fontSize: 28, fontWeight: 600,
        color: accent || 'var(--ink)' }}>{value}</div>
      {hint && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{hint}</div>}
    </div>
  );
}

// Skeleton shimmer block — used while initial data loads.
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
    <div role="status" aria-label="Loading" style={{ ...window.card, padding: 16 }}>
      <RSkeleton h={12} w="40%" mb={14} />
      {Array.from({ length: rows }).map((_, i) => (
        <RSkeleton key={i} h={14} mb={12} />
      ))}
    </div>
  );
}

// Right-hand sliding detail pane (the "SidePane" the brief asks for).
function RSidePane({ title, subtitle, tabs, activeTab, onTab, onClose, children }) {
  rUseEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div role="dialog" aria-label={title || 'Details'} aria-modal="false"
      style={{ ...window.card, padding: 0, position: 'sticky', top: 12,
        alignSelf: 'start', maxHeight: 'calc(100vh - 40px)', display: 'flex',
        flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--rule)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 600,
            color: 'var(--ink)' }}>{title}</div>
          {subtitle && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{subtitle}</div>}
        </div>
        <button onClick={onClose} aria-label="Close panel" style={{ background: 'none',
          border: 'none', cursor: 'pointer', fontSize: 18, lineHeight: 1, color: 'var(--muted)',
          padding: 2 }}>×</button>
      </div>
      {tabs && (
        <div role="tablist" style={{ display: 'flex', gap: 4, padding: '0 12px',
          borderBottom: '1px solid var(--rule)' }}>
          {tabs.map((t) => (
            <button key={t} role="tab" aria-selected={activeTab === t} onClick={() => onTab(t)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '8px 10px',
                fontSize: 12, fontWeight: 600, fontFamily: 'var(--sans)',
                color: activeTab === t ? 'var(--primary)' : 'var(--muted)',
                borderBottom: activeTab === t ? '2px solid var(--primary)' : '2px solid transparent' }}>
              {t}
            </button>
          ))}
        </div>
      )}
      <div style={{ padding: '14px 18px', fontSize: 13, overflow: 'auto' }}>{children}</div>
    </div>
  );
}

// Centered modal dialog with focus trap basics + Escape to close.
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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
          marginBottom: 16 }}>
          <h2 style={{ fontFamily: 'var(--serif)', fontSize: 19, margin: 0,
            color: 'var(--ink)' }}>{title}</h2>
          <button onClick={onClose} aria-label="Close dialog" style={{ background: 'none',
            border: 'none', cursor: 'pointer', fontSize: 20, lineHeight: 1,
            color: 'var(--muted)' }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// Source-grade chip (A/B/C…) styled with the WEP classes.
function RGrade({ grade }) {
  const g = (grade || '?').toString().toUpperCase();
  const klass = g === 'A' ? 'high' : g === 'B' ? 'likely' : g === 'C' ? 'even' : 'unlikely';
  return <span className={`wep ${klass}`} style={{ minWidth: 22, justifyContent: 'center' }}>{g}</span>;
}

// inject the shimmer keyframes once
(function ensureShimmerCSS() {
  if (typeof document === 'undefined') return;
  if (document.getElementById('r-shimmer-css')) return;
  const el = document.createElement('style');
  el.id = 'r-shimmer-css';
  el.textContent = '@keyframes rShimmer{0%{background-position:100% 0}100%{background-position:-100% 0}}';
  document.head && document.head.appendChild(el);
})();

// ── Shared: small toggle switch component ─────────────────────────────────
function RToggle({ value, onChange, id }) {
  return (
    <button role="switch" aria-checked={!!value} id={id} onClick={() => onChange(!value)}
      style={{
        width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer',
        background: value ? 'var(--primary)' : 'var(--rule)',
        position: 'relative', flexShrink: 0, transition: 'background .2s',
      }}>
      <span style={{
        position: 'absolute', top: 2, left: value ? 18 : 2,
        width: 16, height: 16, borderRadius: '50%',
        background: '#fff', transition: 'left .2s',
        boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      }} />
    </button>
  );
}

// ════════════════════════════ TOPICS ════════════════════════════
function TopicsPage({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/topics', { pollMs: 15000 });
  const [showNew, setShowNew] = rUseState(false);
  const [confirmDel, setConfirmDel] = rUseState(null); // topic object to confirm-delete

  window.useEvents((name) => { if (name && name.indexOf('topic') === 0) reload(); });

  const topics = (data && data.topics) || [];

  async function del(topic) {
    try {
      await window.apiDelete(`/api/topics/${topic.id}`);
      setConfirmDel(null);
      reload();
      toast.show('Topic deleted', 'info');
    } catch (e) { toast.show(e.message, 'error'); }
  }

  const Btn = window.Btn;

  return (
    <div>
      <window.PageHeader title="Topics"
        subtitle={`${topics.length} standing ${topics.length === 1 ? 'watch' : 'watches'}`}
        actions={<Btn onClick={() => setShowNew(true)} aria-label="Create a new topic">+ New topic</Btn>} />

      {loading && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
          {[1,2,3,4].map((i) => (
            <div key={i} style={{ ...window.card, padding: 20 }}>
              <RSkeleton h={18} w="60%" mb={10} />
              <RSkeleton h={12} mb={8} />
              <RSkeleton h={12} w="80%" mb={14} />
              <RSkeleton h={20} w={60} r={10} />
            </div>
          ))}
        </div>
      )}

      {!loading && error && <window.ErrorBox message={`Could not load topics — ${error}`} />}

      {!loading && !error && topics.length === 0 && (
        <window.EmptyState title="No research topics yet" icon="🗂"
          hint="No research topics yet — add one to start monitoring."
          action={<Btn onClick={() => setShowNew(true)}>+ New topic</Btn>} />
      )}

      {!loading && !error && topics.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
          {topics.map((t) => (
            <RTopicCard key={t.id} topic={t} onDelete={() => setConfirmDel(t)} />
          ))}
        </div>
      )}

      {showNew && (
        <RNewTopicModal toast={toast} onClose={() => setShowNew(false)}
          onCreated={() => { setShowNew(false); reload(); toast.show('Topic created', 'success'); }} />
      )}

      {confirmDel && (
        <RModal title="Delete topic?" onClose={() => setConfirmDel(null)} width={400}>
          <div style={{ fontSize: 14, color: 'var(--ink-2)', marginBottom: 20, lineHeight: 1.5 }}>
            Delete <strong style={{ color: 'var(--ink)' }}>{confirmDel.name}</strong> and all of its
            associated sources? This cannot be undone.
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Btn kind="ghost" onClick={() => setConfirmDel(null)}>Cancel</Btn>
            <Btn kind="danger" onClick={() => del(confirmDel)}>Delete</Btn>
          </div>
        </RModal>
      )}
    </div>
  );
}

function RTopicCard({ topic: t, onDelete }) {
  const Btn = window.Btn;
  const jobCount = t.job_count != null ? t.job_count : (t.source_count != null ? t.source_count : 0);
  const active = t.status === 'active' || !t.status;
  return (
    <div style={{ ...window.card, padding: 20, display: 'flex', flexDirection: 'column', gap: 10,
      borderTop: `3px solid ${active ? 'var(--primary)' : 'var(--rule)'}` }}>
      {/* Name */}
      <div style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 600,
        color: 'var(--ink)', lineHeight: 1.3 }}>{t.name || 'Untitled'}</div>

      {/* Description */}
      {t.description && (
        <div style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.5,
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
          overflow: 'hidden' }}>{t.description}</div>
      )}

      {/* Query tag */}
      {t.query && (
        <div style={{ display: 'flex' }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--sky-soft)',
            color: 'var(--ink-2)', padding: '2px 8px', borderRadius: 'var(--radius-sm)',
            maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {t.query}
          </span>
        </div>
      )}

      {/* Footer: job count badge + mode + delete */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 'auto', paddingTop: 4 }}>
        {jobCount > 0 && (
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 700,
            background: 'var(--primary)', color: '#fff', padding: '2px 7px',
            borderRadius: 10 }}>{jobCount} {jobCount === 1 ? 'job' : 'jobs'}</span>
        )}
        {t.mode && (
          <span style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.05em' }}>{t.mode}</span>
        )}
        <span style={{ flex: 1 }} />
        <button onClick={onDelete} aria-label={`Delete topic ${t.name}`}
          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14,
            color: 'var(--muted)', padding: '2px 4px', lineHeight: 1,
            borderRadius: 4 }} title="Delete topic">✕</button>
      </div>
    </div>
  );
}

function RNewTopicModal({ toast, onClose, onCreated }) {
  const [name, setName] = rUseState('');
  const [description, setDescription] = rUseState('');
  const [query, setQuery] = rUseState('');
  const [busy, setBusy] = rUseState(false);
  const Btn = window.Btn;

  async function submit() {
    if (!name.trim()) { toast.show('Give the topic a name first.', 'error'); return; }
    setBusy(true);
    try {
      await window.apiPost('/api/topics', {
        name: name.trim(),
        description: description.trim() || undefined,
        query: query.trim() || undefined,
      });
      onCreated();
    } catch (e) { toast.show(e.message, 'error'); setBusy(false); }
  }

  return (
    <RModal title="New topic" onClose={onClose}>
      <RField label="Name">
        <input value={name} onChange={(e) => setName(e.target.value)}
          placeholder="e.g. EU AI Act" style={rInput} aria-label="Topic name" autoFocus />
      </RField>
      <RField label="Description">
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2}
          placeholder="What are you watching for?" style={{ ...rInput, resize: 'vertical' }}
          aria-label="Topic description" />
      </RField>
      <RField label="Query" hint="A search expression or keyword cluster to guide collection.">
        <input value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. AI regulation OR \"foundation models\"" style={rInput}
          aria-label="Topic query" />
      </RField>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
        <Btn kind="ghost" onClick={onClose} disabled={busy}>Cancel</Btn>
        <Btn onClick={submit} disabled={busy}>{busy ? 'Creating…' : 'Create'}</Btn>
      </div>
    </RModal>
  );
}

// ════════════════════════════ POSITIONS ════════════════════════════
function PositionsPage({ toast }) {
  const [tab, setTab] = rUseState('Pending');
  // Fetch all positions once for calibration summary
  const { data: allData } = window.useApi('/api/positions');
  const allPositions = (allData && allData.positions) || [];
  const resolved = allPositions.filter((p) => p.resolved || p.outcome != null);
  const pending = allPositions.filter((p) => !p.resolved && p.outcome == null);

  // Brier score calculation from resolved positions
  function computeBrier(positions) {
    const valid = positions.filter((p) =>
      p.probability != null && (p.outcome === true || p.outcome === false ||
        p.outcome === 'confirmed' || p.outcome === 'refuted')
    );
    if (!valid.length) return null;
    const sum = valid.reduce((acc, p) => {
      const prob = Number(p.probability);
      const out = p.outcome === true || p.outcome === 'confirmed' ? 1 : 0;
      return acc + Math.pow(prob - out, 2);
    }, 0);
    return sum / valid.length;
  }

  const brier = computeBrier(resolved);

  function brierInfo(b) {
    if (b == null) return { label: 'No data', color: 'var(--muted)' };
    if (b < 0.1)  return { label: 'Excellent', color: 'var(--green-dark)' };
    if (b < 0.2)  return { label: 'Good',      color: '#0aa' };
    if (b < 0.25) return { label: 'Fair',       color: 'var(--sand)' };
    return              { label: 'Needs work',  color: 'var(--coral-2)' };
  }
  const bi = brierInfo(brier);

  const PageHeader = window.PageHeader;
  return (
    <div>
      <PageHeader title="Positions"
        subtitle="Resolve predictions and watch your calibration improve"
        tabs={['Pending', 'Resolved']} activeTab={tab} onTab={setTab} />

      {/* Calibration summary header */}
      <div style={{ ...window.card, padding: '14px 20px', marginBottom: 16,
        display: 'flex', gap: 32, alignItems: 'center', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.06em', marginBottom: 2 }}>Brier Score</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span className="num" style={{ fontSize: 22, fontWeight: 700,
              color: bi.color }}>
              {brier != null ? brier.toFixed(3) : '—'}
            </span>
            <span style={{ fontSize: 12, color: bi.color, fontWeight: 600 }}>{bi.label}</span>
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.06em', marginBottom: 2 }}>Resolved</div>
          <span className="num" style={{ fontSize: 22, fontWeight: 700,
            color: 'var(--ink)' }}>{resolved.length}</span>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.06em', marginBottom: 2 }}>Pending</div>
          <span className="num" style={{ fontSize: 22, fontWeight: 700,
            color: 'var(--ink)' }}>{pending.length}</span>
        </div>
      </div>

      {tab === 'Pending'  && <RPositionList key="pending"  pending toast={toast} />}
      {tab === 'Resolved' && <RPositionList key="resolved" resolved toast={toast} />}
    </div>
  );
}

function RPositionList({ pending, resolved, toast }) {
  const path = pending ? '/api/positions' : '/api/positions';
  const { data, loading, error, reload } = window.useApi(path);
  const [sel, setSel] = rUseState(null); // selected position object

  const rawPositions = (data && data.positions) || [];
  const positions = pending
    ? rawPositions.filter((p) => !p.resolved && p.outcome == null)
    : rawPositions.filter((p) => p.resolved || p.outcome != null);

  async function resolve(id, outcome) {
    try {
      await window.apiPost(`/api/positions/${id}/resolve`, { outcome });
      reload();
      toast.show(outcome === 'defer' ? 'Deferred 30 days' : `Marked ${outcome}`, 'success');
      setSel(null);
    } catch (e) { toast.show(e.message, 'error'); }
  }

  function fmt(dateStr) {
    if (!dateStr) return null;
    try {
      return new Date(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    } catch (e) { return dateStr; }
  }

  if (loading) return <RTableSkeleton rows={4} />;
  if (error) return <window.ErrorBox message={`Could not load positions — ${error}`} />;

  if (!positions.length) {
    return (
      <window.EmptyState icon={pending ? '✓' : '◎'}
        title={pending ? 'All positions resolved — calibration is up to date.' : 'No resolved positions yet'}
        hint={pending
          ? 'Every prediction is either resolved or still has time on the clock.'
          : 'Resolve a prediction and it will appear here with its outcome.'} />
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: sel ? '1fr 360px' : '1fr', gap: 16, alignItems: 'start' }}>
      {/* Position rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {positions.map((p) => {
          const isSelected = sel && sel.id === p.id;
          const open = !p.resolved && p.outcome == null;
          const prob = p.probability != null ? p.probability : p.confidence;
          return (
            <div key={p.id} onClick={() => setSel(isSelected ? null : p)}
              role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSel(isSelected ? null : p); }}
              aria-selected={isSelected}
              style={{ ...window.card, padding: '13px 18px', cursor: 'pointer',
                border: `1px solid ${isSelected ? 'var(--primary)' : 'transparent'}`,
                transition: 'border-color .15s' }}>
              {/* Claim text — truncated to 2 lines */}
              <div style={{ fontFamily: 'var(--serif)', fontSize: 14.5, color: 'var(--ink)',
                lineHeight: 1.45,
                display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                overflow: 'hidden', marginBottom: 8 }}>
                {p.claim || '(no claim text)'}
              </div>
              {/* Meta row */}
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                {prob != null && (
                  <window.ConfidencePill phrase={p.wep_band || p.wep_phrase || ''}
                    band={String(prob)} />
                )}
                {prob != null && (
                  <span className="num" style={{ fontSize: 12, color: 'var(--ink-2)' }}>
                    {(prob * 100).toFixed(0)}%
                  </span>
                )}
                {p.created_at && (
                  <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
                    {fmt(p.created_at)}
                  </span>
                )}
                {p.due_at && (
                  <span style={{ fontSize: 11.5, color: 'var(--sand)' }}>due {fmt(p.due_at)}</span>
                )}
                {!open && (
                  <span style={{ fontSize: 12, fontWeight: 600,
                    color: (p.outcome === 'refuted' || p.outcome === false) ? 'var(--coral-2)' : 'var(--green-dark)' }}>
                    {p.outcome === false ? 'refuted' : p.outcome === true ? 'confirmed' : p.outcome}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Side detail pane */}
      {sel && (
        <RSidePane title="Position detail" onClose={() => setSel(null)}>
          <div style={{ fontFamily: 'var(--serif)', fontSize: 15, color: 'var(--ink)',
            lineHeight: 1.55, marginBottom: 14 }}>{sel.claim}</div>

          {/* Probability bar */}
          {(sel.probability != null || sel.confidence != null) && (() => {
            const prob = sel.probability != null ? sel.probability : sel.confidence;
            return (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                  letterSpacing: '0.06em', marginBottom: 4 }}>Probability</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <window.Bar value={prob} max={1} color="var(--primary)" />
                  <span className="num" style={{ fontSize: 13, fontWeight: 700,
                    color: 'var(--ink)', whiteSpace: 'nowrap' }}>{(prob * 100).toFixed(0)}%</span>
                </div>
              </div>
            );
          })()}

          {/* Brier score if resolved */}
          {sel.brier != null && (
            <RRow k="Brier score" v={Number(sel.brier).toFixed(3)} />
          )}
          {sel.created_at && <RRow k="Created" v={sel.created_at} />}
          {sel.due_at && <RRow k="Due" v={sel.due_at} />}
          {sel.resolved_at && <RRow k="Resolved" v={sel.resolved_at} />}

          {/* Resolve buttons for pending positions */}
          {(!sel.resolved && sel.outcome == null) && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                letterSpacing: '0.06em', marginBottom: 8 }}>Resolve</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <window.Btn kind="success" size="sm" onClick={() => resolve(sel.id, 'confirmed')}
                  aria-label="Mark confirmed">True — Confirmed</window.Btn>
                <window.Btn kind="danger" size="sm" onClick={() => resolve(sel.id, 'refuted')}
                  aria-label="Mark refuted">False — Refuted</window.Btn>
                <window.Btn kind="ghost" size="sm" onClick={() => resolve(sel.id, 'defer')}
                  aria-label="Defer 30 days">Defer 30d</window.Btn>
              </div>
            </div>
          )}
        </RSidePane>
      )}
    </div>
  );
}

// ════════════════════════════ HEALTH ════════════════════════════
function HealthPage({ toast }) {
  const [lastRefreshed, setLastRefreshed] = rUseState(null);
  const [elapsed, setElapsed] = rUseState(0);

  const { data, loading, error, reload } = window.useApi('/api/health');
  const { data: govData } = window.useApi('/api/governor');
  const h = data || {};
  const gov = govData || {};

  const PageHeader = window.PageHeader, Btn = window.Btn;

  // Auto-poll every 15s and track last refresh time
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

  // Tick elapsed counter every second
  rUseEffect(() => {
    const tickId = setInterval(() => {
      setElapsed((e) => e + 1);
    }, 1000);
    return () => clearInterval(tickId);
  }, []);

  function manualReload() {
    reload();
    setLastRefreshed(Date.now());
    setElapsed(0);
  }

  const hw = h.hardware || {};
  const budget = h.budget || gov || {};
  const checks = h.checks || [];
  const degraded = gov.degraded || budget.tier === 'degrade';
  const tier = hw.tier;
  const statusLight = degraded ? 'var(--coral-2)'
    : (tier === 'T3' ? 'var(--sand)' : 'var(--green-dark)');

  // Governor tier for coloring
  const govTier = (gov.tier || budget.tier || '—');
  function govChipClass(t) {
    if (!t || t === '—') return 'lh-tier-chip lh-tier-unknown';
    const key = String(t).toLowerCase().replace(/[^a-z_]/g, '_');
    return `lh-tier-chip lh-tier-${key}`;
  }

  return (
    <div>
      <PageHeader title="Health"
        subtitle={loading ? 'Checking…' : h.overall === 'green' ? 'All systems nominal' : 'Some items need attention'}
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 11.5, color: 'var(--muted)', fontFamily: 'var(--sans)' }}>
              {lastRefreshed ? `Refreshed ${elapsed}s ago` : 'Refreshing…'}
            </span>
            <Btn kind="ghost" onClick={manualReload} aria-label="Re-check health now">Re-check</Btn>
          </div>
        } />

      {loading && !data && <RTableSkeleton rows={6} />}
      {!loading && error && <window.ErrorBox message={`Could not reach the health endpoint — ${error}`} />}

      {(data || !loading) && !error && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* ── 1. System ─────────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%',
                background: statusLight, display: 'inline-block',
                boxShadow: `0 0 6px ${statusLight}` }} aria-label="system status indicator" />
              <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 600,
                color: 'var(--ink)' }}>System</div>
            </div>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                  letterSpacing: '0.06em', marginBottom: 4 }}>Hardware tier</div>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 700,
                  background: tier === 'T1' || tier === 'T2' ? 'rgba(6,214,160,0.12)' : 'rgba(255,213,79,0.18)',
                  color: tier === 'T1' || tier === 'T2' ? 'var(--green-dark)' : '#9e7b00',
                  padding: '3px 10px', borderRadius: 8 }}>{tier || '—'}</span>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                  letterSpacing: '0.06em', marginBottom: 4 }}>Model</div>
                <span className="num" style={{ fontSize: 13, color: 'var(--ink)' }}>
                  {hw.model || h.version || '—'}
                </span>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                  letterSpacing: '0.06em', marginBottom: 4 }}>RAM</div>
                <span className="num" style={{ fontSize: 13, color: 'var(--ink)' }}>
                  {hw.ram_gb != null ? `${hw.ram_gb} GB`
                    : hw.total_ram_gb != null ? `${hw.total_ram_gb} GB` : '—'}
                </span>
              </div>
            </div>
          </div>

          {/* ── 2. Budget ─────────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              marginBottom: 14 }}>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 600,
                color: 'var(--ink)' }}>Budget</div>
              <span className={govChipClass(govTier)}>{govTier}</span>
            </div>

            {budget.usd && (() => {
              const used = budget.usd.used || 0, cap = budget.usd.cap || 0;
              const hot = cap > 0 && used / cap > 0.85;
              return (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 12, color: 'var(--ink-2)', marginBottom: 5 }}>
                    <span>Cloud USD</span>
                    <span className="num" style={{ color: hot ? 'var(--coral-2)' : 'var(--ink)' }}>
                      ${used.toFixed(2)} of ${cap.toFixed(2)} remaining: ${(cap - used).toFixed(2)}
                    </span>
                  </div>
                  <window.Bar value={used} max={cap || 1}
                    color={hot ? 'var(--coral-2)' : 'var(--primary)'} />
                </div>
              );
            })()}

            {budget.tokens && (() => {
              const used = budget.tokens.used || 0, cap = budget.tokens.cap || 0;
              const hot = cap > 0 && used / cap > 0.85;
              return (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 12, color: 'var(--ink-2)', marginBottom: 5 }}>
                    <span>Tokens</span>
                    <span className="num" style={{ color: hot ? 'var(--coral-2)' : 'var(--ink)' }}>
                      {(used / 1e6).toFixed(1)}M of {(cap / 1e6).toFixed(1)}M
                      — {((cap - used) / 1e6).toFixed(1)}M remaining
                    </span>
                  </div>
                  <window.Bar value={used} max={cap || 1}
                    color={hot ? 'var(--coral-2)' : 'var(--primary)'} />
                </div>
              );
            })()}

            {!budget.usd && !budget.tokens && (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>No budget data reported yet.</div>
            )}
          </div>

          {/* ── 3. Checks ─────────────────────────────────────────────── */}
          <div style={{ ...window.card, padding: 20 }}>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 600,
              color: 'var(--ink)', marginBottom: 14 }}>Checks</div>

            {checks.length === 0 && (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>No checks reported by backend.</div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {checks.map((c, i) => (
                <RCheckRow key={c.name || i} check={c} />
              ))}
            </div>
          </div>

        </div>
      )}
    </div>
  );
}

function RCheckRow({ check }) {
  const [open, setOpen] = rUseState(false);
  const ok = check.ok !== false && check.status !== 'fail';
  const hasDetail = !ok && check.detail;

  return (
    <div style={{ padding: '7px 0', borderBottom: '1px solid var(--rule-soft)' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 13,
        cursor: hasDetail ? 'pointer' : 'default' }}
        onClick={hasDetail ? () => setOpen((o) => !o) : undefined}
        role={hasDetail ? 'button' : undefined}
        tabIndex={hasDetail ? 0 : undefined}
        onKeyDown={hasDetail ? (e) => { if (e.key === 'Enter') setOpen((o) => !o); } : undefined}>
        <span style={{ fontSize: 15, lineHeight: 1, flexShrink: 0,
          color: ok ? 'var(--green-dark)' : 'var(--coral-2)' }}
          aria-label={ok ? 'passing' : 'failing'}>
          {ok ? '✓' : '✕'}
        </span>
        <span style={{ fontWeight: 500, color: 'var(--ink)', flex: 1 }}>{check.name}</span>
        {hasDetail && (
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>{open ? '▾' : '▸'} detail</span>
        )}
      </div>
      {hasDetail && open && (
        <div style={{ paddingLeft: 25, paddingTop: 5, fontSize: 12,
          color: 'var(--coral-2)', fontFamily: 'var(--mono)', wordBreak: 'break-word' }}>
          {check.detail}
        </div>
      )}
    </div>
  );
}

// ════════════════════════════ SETTINGS ════════════════════════════
function SettingsPage({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/settings');
  const [form, setForm] = rUseState(null);
  const [dirty, setDirty] = rUseState(false);
  const [saving, setSaving] = rUseState(false);
  const [doctorData, setDoctorData] = rUseState(null);
  const [doctorLoading, setDoctorLoading] = rUseState(false);
  const Btn = window.Btn;

  // Sync form from fetched data (only on initial load, not on every poll)
  rUseEffect(() => {
    if (data && !form) {
      setForm({
        data_dir: data.data_dir || '',
        offline_mode: !!data.offline_mode,
        backup_enabled: !!data.backup_enabled,
        notify_enabled: !!data.notify_enabled,
        theme: data.theme || 'system',
      });
    }
  }, [data]); // eslint-disable-line

  function patch(key, val) {
    setForm((f) => ({ ...f, [key]: val }));
    setDirty(true);
  }

  async function save() {
    setSaving(true);
    try {
      await window.apiPatch('/api/settings', form);
      setDirty(false);
      toast.show('Settings saved', 'success');
      reload();
    } catch (e) { toast.show(e.message, 'error'); }
    setSaving(false);
  }

  async function runDiagnostics() {
    setDoctorLoading(true);
    setDoctorData(null);
    try {
      const d = await window.apiGet('/api/health');
      setDoctorData(d);
    } catch (e) { toast.show(e.message, 'error'); }
    setDoctorLoading(false);
  }

  if (loading && !form) return <RTableSkeleton rows={8} />;
  if (error && !form) return <window.ErrorBox message={`Could not load settings — ${error}`} />;
  if (!form) return <RTableSkeleton rows={8} />;

  return (
    <div>
      <window.PageHeader title="Settings"
        actions={
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {dirty && (
              <span style={{ fontSize: 12, color: 'var(--sand)', fontWeight: 600,
                fontFamily: 'var(--sans)' }}>Unsaved changes</span>
            )}
            <Btn onClick={save} disabled={saving || !dirty}>
              {saving ? 'Saving…' : 'Save'}
            </Btn>
          </div>
        } />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 600 }}>

        {/* ── General ──────────────────────────────────────────────── */}
        <RSettingsSection title="General">
          <RField label="Data directory">
            <input value={form.data_dir} onChange={(e) => patch('data_dir', e.target.value)}
              style={rInput} aria-label="Data directory path" placeholder="~/.lighthouse" />
          </RField>
          <RToggleRow label="Offline mode" hint="Disables all cloud model calls."
            value={form.offline_mode} onChange={(v) => patch('offline_mode', v)} id="s-offline" />
        </RSettingsSection>

        {/* ── Backup ───────────────────────────────────────────────── */}
        <RSettingsSection title="Backup">
          <RToggleRow label="Enable backup" hint="Stream SQLite WAL to configured replicas via Litestream."
            value={form.backup_enabled} onChange={(v) => patch('backup_enabled', v)} id="s-backup" />
        </RSettingsSection>

        {/* ── Notifications ────────────────────────────────────────── */}
        <RSettingsSection title="Notifications">
          <RToggleRow label="Enable notifications" hint="Send alerts via configured channels (Telegram, etc.)."
            value={form.notify_enabled} onChange={(v) => patch('notify_enabled', v)} id="s-notify" />
        </RSettingsSection>

        {/* ── Appearance ───────────────────────────────────────────── */}
        <RSettingsSection title="Appearance">
          <RField label="Theme">
            <select value={form.theme} onChange={(e) => patch('theme', e.target.value)}
              style={rInput} aria-label="Theme selection">
              <option value="system">System (auto)</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </RField>
        </RSettingsSection>

        {/* ── Doctor ───────────────────────────────────────────────── */}
        <RSettingsSection title="Doctor">
          <div style={{ marginBottom: 12 }}>
            <Btn kind="ghost" onClick={runDiagnostics} disabled={doctorLoading}>
              {doctorLoading ? 'Running diagnostics…' : 'Run diagnostics'}
            </Btn>
          </div>
          {doctorData && (
            <div>
              {(doctorData.checks || []).length === 0 && (
                <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                  No checks returned from the health endpoint.
                </div>
              )}
              {(doctorData.checks || []).map((c, i) => (
                <RCheckRow key={c.name || i} check={c} />
              ))}
              {doctorData.overall && (
                <div style={{ marginTop: 10, fontSize: 13, fontWeight: 600,
                  color: doctorData.overall === 'green' ? 'var(--green-dark)' : 'var(--coral-2)' }}>
                  Overall: {doctorData.overall}
                </div>
              )}
            </div>
          )}
        </RSettingsSection>

      </div>
    </div>
  );
}

function RSettingsSection({ title, children }) {
  return (
    <div style={{ ...window.card, padding: '18px 20px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase',
        letterSpacing: '0.08em', marginBottom: 14 }}>{title}</div>
      {children}
    </div>
  );
}

function RToggleRow({ label, hint, value, onChange, id }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      gap: 16, marginBottom: 12 }}>
      <label htmlFor={id} style={{ cursor: 'pointer' }}>
        <div style={{ fontSize: 13, color: 'var(--ink)', fontFamily: 'var(--sans)',
          fontWeight: 500 }}>{label}</div>
        {hint && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{hint}</div>}
      </label>
      <RToggle id={id} value={value} onChange={onChange} />
    </div>
  );
}

// ── export ────────────────────────────────────────────────────────────────
Object.assign(window, { TopicsPage, PositionsPage, HealthPage, SettingsPage });
