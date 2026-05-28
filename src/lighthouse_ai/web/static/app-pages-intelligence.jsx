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

function IReflectionsPanel({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/reflections');
  const [acting, iSetActing] = iUseState(null); // id of reflection being acted on

  window.useEvents(iUseCallback((name) => {
    if (name === 'intelligence.acted') reload();
  }, [reload]));

  async function handleAct(r) {
    iSetActing(r.id);
    try {
      const res = await window.apiPost(`/api/reflections/${r.id}/act`, {});
      toast.show(`Job ${res.job_id} spawned`, 'success');
      reload();
    } catch (e) {
      toast.show(e.message || 'Act failed', 'error');
    } finally {
      iSetActing(null);
    }
  }

  if (loading) return <div style={{ padding: 20, color: 'var(--muted)' }}>Loading reflections…</div>;
  if (error)   return <window.ErrorBox message={`Could not load reflections — ${error}`} />;

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

function IEscalationsPanel({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/escalations');
  const [updating, iSetUpdating] = iUseState(null);

  window.useEvents(iUseCallback((name) => {
    if (name === 'intelligence.escalation_updated') reload();
  }, [reload]));

  async function setStatus(id, status) {
    iSetUpdating(id);
    try {
      await window.apiPatch(`/api/escalations/${id}/status`, { status });
      toast.show(`Status → ${status}`, 'success');
      reload();
    } catch (e) {
      toast.show(e.message || 'Update failed', 'error');
    } finally {
      iSetUpdating(null);
    }
  }

  if (loading) return <div style={{ padding: 20, color: 'var(--muted)' }}>Loading escalations…</div>;
  if (error)   return <window.ErrorBox message={`Could not load escalations — ${error}`} />;

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
  const [tab, iSetTab] = iUseState('reflections');

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '32px 24px 48px' }}>
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
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

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20,
        borderBottom: '1px solid var(--rule)', paddingBottom: 0 }}>
        {['reflections', 'escalations'].map((t) => (
          <button
            key={t}
            onClick={() => iSetTab(t)}
            style={{
              padding: '8px 18px', border: 'none', cursor: 'pointer',
              fontFamily: 'var(--sans)', fontSize: 13, fontWeight: tab === t ? 600 : 500,
              background: 'transparent',
              color: tab === t ? 'var(--primary)' : 'var(--muted)',
              borderBottom: tab === t ? '2px solid var(--primary)' : '2px solid transparent',
              marginBottom: -1, borderRadius: 0,
              transition: 'color .12s',
              textTransform: 'capitalize',
            }}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Panel */}
      {tab === 'reflections' && <IReflectionsPanel toast={toast} />}
      {tab === 'escalations' && <IEscalationsPanel toast={toast} />}
    </div>
  );
};
