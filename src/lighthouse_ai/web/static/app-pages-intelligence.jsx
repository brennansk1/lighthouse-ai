// app-pages-intelligence.jsx — Intelligence page (§3 dashboard, OpenHuman §3).
//
// Shows passive reflections (provenance notes; never auto-post) + actionable
// escalations (status + priority). "Act" spawns a fresh research job seeded
// from the reflection body via POST /api/reflections/{id}/act.
//
// Loaded via babel-standalone. All helpers come from app-lib.jsx / app-pages-rest.jsx
// (window.*). I-prefixed to avoid collision with other page files.

const {
  useState: iUseState,
  useEffect: iUseEffect,
  useCallback: iUseCallback,
} = React;

// ── Inject page-specific CSS once ────────────────────────────────────────────
(function ensureIntelCSS() {
  if (typeof document === 'undefined') return;
  if (document.getElementById('i-intel-css')) return;
  const el = document.createElement('style');
  el.id = 'i-intel-css';
  el.textContent = `
.i-kind-chip {
  display: inline-block;
  font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.08em;
  padding: 2px 8px; border-radius: 999px;
  background: var(--rule-soft); color: var(--muted);
}
.i-kind-chip.provenance   { background: rgba(2,136,209,0.10);  color: var(--primary-dark); }
.i-kind-chip.contradiction{ background: rgba(199,21,133,0.10);  color: #880e4f; }
.i-kind-chip.gap          { background: rgba(255,213,79,0.20);  color: #8d6e00; }
.i-kind-chip.stale_position { background: rgba(183,28,28,0.10); color: #b71c1c; }

.i-priority-chip {
  display: inline-block;
  font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.08em;
  padding: 2px 8px; border-radius: 999px;
}
.i-priority-chip.high   { background: rgba(183,28,28,0.12); color: #b71c1c; }
.i-priority-chip.medium { background: rgba(255,213,79,0.22); color: #8d6e00; }
.i-priority-chip.low    { background: rgba(6,214,160,0.14);  color: var(--green-dark); }

.i-status-chip {
  display: inline-block;
  font-size: 10px; font-weight: 600;
  padding: 2px 8px; border-radius: 999px;
  border: 1px solid var(--rule); background: var(--card); color: var(--muted);
}
.i-status-chip.open         { color: var(--primary-dark); border-color: var(--primary); }
.i-status-chip.acknowledged { color: #8d6e00; border-color: #ffd54f; }
.i-status-chip.resolved     { color: var(--green-dark); border-color: var(--green); }

.i-act-btn {
  font-size: 11.5px; font-weight: 600;
  padding: 5px 12px; border-radius: 6px;
  background: var(--primary); color: #fff;
  border: none; cursor: pointer;
  transition: background .14s;
}
.i-act-btn:hover { background: var(--primary-dark); }
.i-act-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.i-card {
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 16px 20px;
}
.i-card + .i-card { margin-top: 8px; }
`;
  document.head && document.head.appendChild(el);
})();

// ── Small presentational components ──────────────────────────────────────────

function IKindChip({ kind }) {
  const label = (kind || '').replace(/_/g, ' ');
  return <span className={`i-kind-chip ${kind || ''}`}>{label}</span>;
}

function IPriorityChip({ priority }) {
  return <span className={`i-priority-chip ${priority || 'low'}`}>{priority || 'low'}</span>;
}

function IStatusChip({ status }) {
  return <span className={`i-status-chip ${status || 'open'}`}>{(status || 'open').replace(/_/g, ' ')}</span>;
}

function IEmptyState({ icon, title, hint }) {
  return (
    <div style={{ ...window.card, padding: '40px 24px', textAlign: 'center' }}>
      <div style={{ fontSize: 32, marginBottom: 10 }}>{icon}</div>
      <div style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
        color: 'var(--ink)', marginBottom: 6 }}>{title}</div>
      {hint && <div style={{ fontSize: 13, color: 'var(--muted)', maxWidth: 420,
        margin: '0 auto', lineHeight: 1.5 }}>{hint}</div>}
    </div>
  );
}

// ── Reflections panel ─────────────────────────────────────────────────────────

function IReflectionsPanel({ toast, data, loading, error, reload }) {
  const [acting, iSetActing] = iUseState(null); // id of reflection being acted on

  async function handleAct(r) {
    iSetActing(r.id);
    try {
      const res = await window.apiPost(`/api/reflections/${r.id}/act`, {});
      toast.show(`Research job ${res.job_id} spawned — view it on the Jobs page`, 'success');
      reload();
    } catch (e) {
      toast.show(e.message || 'Could not act on this reflection', 'error');
    } finally {
      iSetActing(null);
    }
  }

  if (loading && !data) return <window.Loading label="Loading reflections…" />;
  if (error)   return <window.ErrorBox message={`Could not load reflections — ${error}`} onRetry={reload} />;

  const items = (data && data.reflections) || [];
  if (!items.length) {
    return (
      <IEmptyState
        icon="◎"
        title="No reflections yet"
        hint="Passive observations (provenance notes, contradictions, gaps) appear here as research runs."
      />
    );
  }

  return (
    <div>
      {items.map((r) => (
        <div key={r.id} className="i-card">
          <div style={{ display: 'flex', justifyContent: 'space-between',
            alignItems: 'flex-start', gap: 12, marginBottom: 10 }}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <IKindChip kind={r.kind} />
              <span style={{ fontSize: 10.5, color: 'var(--muted)',
                fontFamily: 'var(--mono)' }}>
                {r.created_at ? r.created_at.slice(0, 19).replace('T', ' ') : ''}
              </span>
            </div>
            {r.proposed_action && (
              <button
                className="i-act-btn"
                disabled={acting === r.id}
                onClick={() => handleAct(r)}
                title="Spawn a research job seeded from this reflection"
              >
                {acting === r.id ? 'Acting…' : 'Act'}
              </button>
            )}
          </div>

          <div style={{ fontFamily: 'var(--serif)', fontSize: 14.5, color: 'var(--ink)',
            lineHeight: 1.55, marginBottom: r.proposed_action ? 10 : 0 }}>
            {r.body}
          </div>

          {r.proposed_action && (
            <div style={{ fontSize: 12.5, color: 'var(--ink-2)', borderTop: '1px solid var(--rule)',
              paddingTop: 8, marginTop: 6 }}>
              <span style={{ fontWeight: 700, color: 'var(--muted)',
                fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.07em',
                marginRight: 6 }}>Proposed</span>
              {r.proposed_action}
            </div>
          )}

          {r.source_refs && r.source_refs.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {r.source_refs.map((ref, i) => (
                <span key={i} style={{ fontSize: 10.5, fontFamily: 'var(--mono)',
                  background: 'var(--rule-soft)', color: 'var(--muted)',
                  padding: '1px 6px', borderRadius: 4 }}>
                  {ref}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Escalations panel ─────────────────────────────────────────────────────────

function IEscalationsPanel({ toast, data, loading, error, reload }) {
  const [updating, iSetUpdating] = iUseState(null);

  async function setStatus(id, status) {
    iSetUpdating(id);
    try {
      await window.apiPatch(`/api/escalations/${id}/status`, { status });
      toast.show(status === 'resolved' ? 'Escalation resolved' : `Escalation ${status}`, 'success');
      reload();
    } catch (e) {
      toast.show(e.message || 'Could not update escalation', 'error');
    } finally {
      iSetUpdating(null);
    }
  }

  if (loading && !data) return <window.Loading label="Loading escalations…" />;
  if (error)   return <window.ErrorBox message={`Could not load escalations — ${error}`} onRetry={reload} />;

  const items = (data && data.escalations) || [];
  const open   = items.filter((e) => e.status === 'open');
  const others = items.filter((e) => e.status !== 'open');

  if (!items.length) {
    return (
      <IEmptyState
        icon="✓"
        title="No active escalations"
        hint="Actionable findings (stale positions, deadline breaches) appear here when they arise."
      />
    );
  }

  function EscCard({ e }) {
    return (
      <div className="i-card" style={{ borderLeft: `3px solid ${
        e.priority === 'high' ? '#b71c1c' : e.priority === 'medium' ? '#ffd54f' : 'var(--green)'
      }` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between',
          alignItems: 'flex-start', gap: 12, marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <IKindChip kind={e.kind} />
            <IPriorityChip priority={e.priority} />
            <IStatusChip status={e.status} />
            <span style={{ fontSize: 10.5, color: 'var(--muted)',
              fontFamily: 'var(--mono)' }}>
              {e.created_at ? e.created_at.slice(0, 19).replace('T', ' ') : ''}
            </span>
          </div>

          {/* Status transition buttons */}
          {e.status === 'open' && (
            <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
              <button
                disabled={updating === e.id}
                onClick={() => setStatus(e.id, 'acknowledged')}
                style={{ fontSize: 11, padding: '4px 10px', borderRadius: 6,
                  border: '1px solid var(--rule)', background: 'var(--card)',
                  color: 'var(--ink-2)', cursor: 'pointer' }}>
                Acknowledge
              </button>
              <button
                disabled={updating === e.id}
                onClick={() => setStatus(e.id, 'resolved')}
                style={{ fontSize: 11, padding: '4px 10px', borderRadius: 6,
                  background: 'var(--green)', border: 'none',
                  color: '#fff', cursor: 'pointer' }}>
                Resolve
              </button>
            </div>
          )}
          {e.status === 'acknowledged' && (
            <button
              disabled={updating === e.id}
              onClick={() => setStatus(e.id, 'resolved')}
              style={{ fontSize: 11, padding: '4px 10px', borderRadius: 6,
                background: 'var(--green)', border: 'none',
                color: '#fff', cursor: 'pointer', flexShrink: 0 }}>
              Resolve
            </button>
          )}
        </div>

        <div style={{ fontFamily: 'var(--serif)', fontSize: 14.5, color: 'var(--ink)',
          lineHeight: 1.55 }}>
          {e.body}
        </div>

        {e.source_refs && e.source_refs.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {e.source_refs.map((ref, i) => (
              <span key={i} style={{ fontSize: 10.5, fontFamily: 'var(--mono)',
                background: 'var(--rule-soft)', color: 'var(--muted)',
                padding: '1px 6px', borderRadius: 4 }}>
                {ref}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      {open.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.09em', color: 'var(--muted)', marginBottom: 8 }}>
            Open ({open.length})
          </div>
          {open.map((e) => <EscCard key={e.id} e={e} />)}
        </div>
      )}
      {others.length > 0 && (
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.09em', color: 'var(--muted)', marginBottom: 8 }}>
            Closed ({others.length})
          </div>
          {others.map((e) => <EscCard key={e.id} e={e} />)}
        </div>
      )}
    </div>
  );
}

// ── IntelligencePage ──────────────────────────────────────────────────────────

window.IntelligencePage = function IntelligencePage({ toast }) {
  // Data is owned here so the tab bar can show accurate "needs attention"
  // badges and pick a sensible default tab. Panels render from these props.
  const reflections = window.useApi('/api/reflections');
  const escalations = window.useApi('/api/escalations');

  // Live refresh both lists when the subconscious engine emits.
  window.useEvents(iUseCallback((name) => {
    if (name === 'intelligence.acted') reflections.reload();
    if (name === 'intelligence.escalation_updated') escalations.reload();
  }, [reflections.reload, escalations.reload]));

  const escItems = (escalations.data && escalations.data.escalations) || [];
  const openEsc = escItems.filter((e) => e.status === 'open');
  const reflItems = (reflections.data && reflections.data.reflections) || [];

  // Default to whichever surface needs the user: open escalations win.
  const [tab, iSetTab] = iUseState(null);
  const effectiveTab = tab || (openEsc.length > 0 ? 'escalations' : 'reflections');

  const tabMeta = {
    reflections: { label: 'Reflections', count: reflItems.length, urgent: false },
    escalations: { label: 'Escalations', count: openEsc.length, urgent: openEsc.length > 0 },
  };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '32px 24px 48px' }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontFamily: 'var(--serif)', fontSize: 26, fontWeight: 700,
          color: 'var(--ink)', margin: 0, letterSpacing: '-0.01em' }}>
          Intelligence
        </h1>
        <p style={{ margin: '6px 0 0', fontSize: 13.5, color: 'var(--muted)',
          lineHeight: 1.5 }}>
          Passive reflections (provenance notes, contradictions, gaps) and actionable
          escalations produced by the subconscious tick engine. Reflections are never
          auto-posted; escalations track status until resolved.
        </p>
      </div>

      {/* "Needs your attention" summary — the obvious next step. */}
      <div role="status" style={{ marginBottom: 20, padding: '10px 14px',
        borderRadius: 'var(--radius-sm)', fontFamily: 'var(--sans)', fontSize: 13,
        background: openEsc.length > 0 ? 'rgba(183,28,28,0.07)' : 'var(--rule-soft)',
        border: openEsc.length > 0 ? '1px solid rgba(183,28,28,0.2)' : '1px solid var(--rule)',
        color: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span aria-hidden="true">{openEsc.length > 0 ? '🔔' : '✓'}</span>
        {openEsc.length > 0
          ? <span><strong style={{ color: 'var(--ink)' }}>{openEsc.length} open escalation{openEsc.length === 1 ? '' : 's'}</strong> need your attention.</span>
          : <span>Nothing needs your attention. All escalations are resolved.</span>}
      </div>

      {/* Tab bar */}
      <div role="tablist" style={{ display: 'flex', gap: 4, marginBottom: 20,
        borderBottom: '1px solid var(--rule)', paddingBottom: 0 }}>
        {['reflections', 'escalations'].map((t) => {
          const m = tabMeta[t];
          const on = effectiveTab === t;
          return (
            <button
              key={t}
              role="tab"
              aria-selected={on}
              onClick={() => iSetTab(t)}
              style={{
                padding: '8px 18px', border: 'none', cursor: 'pointer',
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: on ? 600 : 500,
                background: 'transparent',
                color: on ? 'var(--primary)' : 'var(--muted)',
                borderBottom: on ? '2px solid var(--primary)' : '2px solid transparent',
                marginBottom: -1, borderRadius: 0,
                transition: 'color .12s',
                display: 'inline-flex', alignItems: 'center', gap: 7,
              }}
            >
              {m.label}
              {m.count > 0 && (
                <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, fontWeight: 700,
                  lineHeight: 1, padding: '2px 6px', borderRadius: 999,
                  background: m.urgent ? '#b71c1c' : 'var(--rule)',
                  color: m.urgent ? '#fff' : 'var(--muted)' }}>
                  {m.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Panel */}
      {effectiveTab === 'reflections' && (
        <IReflectionsPanel toast={toast} data={reflections.data}
          loading={reflections.loading} error={reflections.error} reload={reflections.reload} />
      )}
      {effectiveTab === 'escalations' && (
        <IEscalationsPanel toast={toast} data={escalations.data}
          loading={escalations.loading} error={escalations.error} reload={escalations.reload} />
      )}
    </div>
  );
};
