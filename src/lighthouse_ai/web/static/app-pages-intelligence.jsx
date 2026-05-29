// app-pages-intelligence.jsx — Intelligence page (§3 dashboard, OpenHuman §3).
//
// Shows passive reflections (provenance notes; never auto-post) + actionable
// escalations (status + priority). "Investigate" spawns a fresh research job
// seeded from the reflection body via POST /api/reflections/{id}/act.
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
.i-kind-chip.provenance     { background: rgba(2,136,209,0.10);  color: var(--primary-dark); }
.i-kind-chip.contradiction  { background: rgba(199,21,133,0.10);  color: #880e4f; }
.i-kind-chip.gap            { background: rgba(255,213,79,0.20);  color: #8d6e00; }
.i-kind-chip.stale_position { background: rgba(183,28,28,0.10);  color: #b71c1c; }

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

// ── Kind label map — translate internal enum values to plain language ─────────
const KIND_LABELS = {
  provenance:     'Source Note',
  contradiction:  'Conflicting Evidence',
  gap:            'Research Gap',
  stale_position: 'Outdated Position',
};

function IKindChip({ kind }) {
  const label = KIND_LABELS[kind] || (kind || '').replace(/_/g, ' ');
  return (
    <span
      className={`i-kind-chip ${kind || ''}`}
      title={kind ? `Kind: ${kind}` : undefined}
    >
      {label}
    </span>
  );
}

// Priority is already clear; "High" / "Medium" / "Low" need no translation.
function IPriorityChip({ priority }) {
  const p = priority || 'low';
  const LABELS = { high: 'High Priority', medium: 'Medium Priority', low: 'Low Priority' };
  return (
    <span className={`i-priority-chip ${p}`} title={`Priority: ${p}`}>
      {LABELS[p] || p}
    </span>
  );
}

// Status chip — plain-language labels for each workflow state.
const STATUS_LABELS = {
  open:         'Open',
  acknowledged: 'In Review',
  resolved:     'Resolved',
};
function IStatusChip({ status }) {
  const s = status || 'open';
  return (
    <span className={`i-status-chip ${s}`}>
      {STATUS_LABELS[s] || s.replace(/_/g, ' ')}
    </span>
  );
}

// ── Panel description bar — appears directly below the tab strip ──────────────
function IPanelDesc({ children }) {
  return (
    <div style={{
      background: 'var(--rule-soft)',
      border: '1px solid var(--rule)',
      borderRadius: 'var(--radius)',
      padding: '10px 14px',
      fontSize: 13,
      color: 'var(--ink-2)',
      lineHeight: 1.55,
      marginBottom: 20,
    }}>
      {children}
    </div>
  );
}

// ── Source reference tag ──────────────────────────────────────────────────────
function ISourceRef({ ref: refStr, index }) {
  return (
    <span
      title={`Source reference: ${refStr}`}
      style={{
        fontSize: 10.5, fontFamily: 'var(--mono)',
        background: 'var(--rule-soft)', color: 'var(--muted)',
        padding: '1px 6px', borderRadius: 4,
      }}
    >
      {refStr}
    </span>
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
      toast.show(`Investigation job ${res.job_id} started`, 'success');
      reload();
    } catch (e) {
      toast.show(e.message || 'Could not start investigation job', 'error');
    } finally {
      iSetActing(null);
    }
  }

  if (loading) return <window.Loading label="Loading observations..." />;
  if (error) {
    return (
      <window.ErrorBox
        message={`Could not load observations — ${error}`}
        onRetry={reload}
      />
    );
  }

  const items = (data && data.reflections) || [];

  if (!items.length) {
    return (
      <window.EmptyState
        icon="◎"
        title="No observations yet"
        hint={
          'Observations appear here as the system monitors your research topics. ' +
          'Each one notes something worth your attention — a source conflict, ' +
          'a coverage gap, or a position that may need updating. ' +
          'Start a research job to generate your first observations.'
        }
      />
    );
  }

  return (
    <div>
      {items.map((r) => (
        <div key={r.id} className="i-card">
          {/* Header row: kind chip + timestamp + action button */}
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            alignItems: 'flex-start', gap: 12, marginBottom: 10,
          }}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <IKindChip kind={r.kind} />
              <span style={{ fontSize: 10.5, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>
                {r.created_at ? r.created_at.slice(0, 19).replace('T', ' ') : ''}
              </span>
            </div>

            {r.proposed_action && (
              <button
                className="i-act-btn"
                disabled={acting === r.id}
                onClick={() => handleAct(r)}
                title="Start a new research job based on this observation"
              >
                {acting === r.id ? 'Starting...' : 'Investigate'}
              </button>
            )}
          </div>

          {/* Observation body */}
          <div style={{
            fontFamily: 'var(--serif)', fontSize: 14.5, color: 'var(--ink)',
            lineHeight: 1.55, marginBottom: r.proposed_action ? 10 : 0,
          }}>
            {r.body}
          </div>

          {/* Suggested next step */}
          {r.proposed_action && (
            <div style={{
              fontSize: 12.5, color: 'var(--ink-2)',
              borderTop: '1px solid var(--rule)',
              paddingTop: 8, marginTop: 6,
            }}>
              <span style={{
                fontWeight: 700, color: 'var(--muted)',
                fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.07em',
                marginRight: 6,
              }}>Suggested action</span>
              {r.proposed_action}
            </div>
          )}

          {/* Source references */}
          {r.source_refs && r.source_refs.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{
                fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                letterSpacing: '0.07em', color: 'var(--muted)', marginRight: 2,
              }}>Sources</span>
              {r.source_refs.map((ref, i) => (
                <ISourceRef key={i} ref={ref} index={i} />
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
      const VERB = { acknowledged: 'marked as in review', resolved: 'resolved' };
      toast.show(`Item ${VERB[status] || status}`, 'success');
      reload();
    } catch (e) {
      toast.show(e.message || 'Could not update status', 'error');
    } finally {
      iSetUpdating(null);
    }
  }

  if (loading) return <window.Loading label="Loading items requiring attention..." />;
  if (error) {
    return (
      <window.ErrorBox
        message={`Could not load items requiring attention — ${error}`}
        onRetry={reload}
      />
    );
  }

  const items = (data && data.escalations) || [];
  const open   = items.filter((e) => e.status === 'open');
  const others = items.filter((e) => e.status !== 'open');

  if (!items.length) {
    return (
      <window.EmptyState
        icon="+"
        title="Nothing requires attention"
        hint={
          'Items appear here when the system detects something that needs your decision — ' +
          'an outdated position, a missed deadline, or a finding that conflicts with your ' +
          'current conclusions. You can acknowledge items to mark them as seen, or resolve ' +
          'them once addressed.'
        }
      />
    );
  }

  function EscCard({ e }) {
    const borderColor =
      e.priority === 'high'   ? '#b71c1c' :
      e.priority === 'medium' ? '#ffd54f' :
      'var(--green)';

    return (
      <div className="i-card" style={{ borderLeft: `3px solid ${borderColor}` }}>
        {/* Header: classification chips + timestamp + action buttons */}
        <div style={{
          display: 'flex', justifyContent: 'space-between',
          alignItems: 'flex-start', gap: 12, marginBottom: 10,
        }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <IKindChip kind={e.kind} />
            <IPriorityChip priority={e.priority} />
            <IStatusChip status={e.status} />
            <span style={{ fontSize: 10.5, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>
              {e.created_at ? e.created_at.slice(0, 19).replace('T', ' ') : ''}
            </span>
          </div>

          {/* Status transition buttons */}
          {e.status === 'open' && (
            <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
              <button
                disabled={updating === e.id}
                onClick={() => setStatus(e.id, 'acknowledged')}
                title="Mark as seen — you are aware of this item and will address it"
                style={{
                  fontSize: 11, padding: '4px 10px', borderRadius: 6,
                  border: '1px solid var(--rule)', background: 'var(--card)',
                  color: 'var(--ink-2)', cursor: 'pointer',
                }}
              >
                Mark as seen
              </button>
              <button
                disabled={updating === e.id}
                onClick={() => setStatus(e.id, 'resolved')}
                title="Mark as resolved — this item has been addressed"
                style={{
                  fontSize: 11, padding: '4px 10px', borderRadius: 6,
                  background: 'var(--green)', border: 'none',
                  color: '#fff', cursor: 'pointer',
                }}
              >
                Resolve
              </button>
            </div>
          )}
          {e.status === 'acknowledged' && (
            <button
              disabled={updating === e.id}
              onClick={() => setStatus(e.id, 'resolved')}
              title="Mark as resolved — this item has been addressed"
              style={{
                fontSize: 11, padding: '4px 10px', borderRadius: 6,
                background: 'var(--green)', border: 'none',
                color: '#fff', cursor: 'pointer', flexShrink: 0,
              }}
            >
              Resolve
            </button>
          )}
        </div>

        {/* Item description */}
        <div style={{
          fontFamily: 'var(--serif)', fontSize: 14.5, color: 'var(--ink)',
          lineHeight: 1.55,
        }}>
          {e.body}
        </div>

        {/* Source references */}
        {e.source_refs && e.source_refs.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{
              fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: '0.07em', color: 'var(--muted)', marginRight: 2,
            }}>Sources</span>
            {e.source_refs.map((ref, i) => (
              <ISourceRef key={i} ref={ref} index={i} />
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
          <div style={{
            fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.09em', color: 'var(--muted)', marginBottom: 8,
          }}>
            Needs attention ({open.length})
          </div>
          {open.map((e) => <EscCard key={e.id} e={e} />)}
        </div>
      )}
      {others.length > 0 && (
        <div>
          <div style={{
            fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.09em', color: 'var(--muted)', marginBottom: 8,
          }}>
            Addressed ({others.length})
          </div>
          {others.map((e) => <EscCard key={e.id} e={e} />)}
        </div>
      )}
    </div>
  );
}

// ── IntelligencePage ──────────────────────────────────────────────────────────

const INTEL_TABS = ['Observations', 'Attention Required'];

window.IntelligencePage = function IntelligencePage({ toast }) {
  const [tab, iSetTab] = iUseState('Observations');

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '32px 24px 48px' }}>
      <window.PageHeader
        title="Intelligence"
        subtitle="Passive observations and items that need your attention, surfaced automatically as your research runs."
        tabs={INTEL_TABS}
        activeTab={tab}
        onTab={iSetTab}
      />

      {/* Per-tab orientation text */}
      {tab === 'Observations' && (
        <IPanelDesc>
          The system notes patterns in your research automatically — source conflicts,
          coverage gaps, and positions that may be outdated. These observations do not
          change your data; they are read-only notes. If one suggests a next step,
          you can start an investigation job directly from the item.
        </IPanelDesc>
      )}
      {tab === 'Attention Required' && (
        <IPanelDesc>
          These items have been flagged as needing a decision from you. Review each one,
          then mark it as seen to acknowledge it, or resolve it once you have addressed it.
          High-priority items appear at the top of the list.
        </IPanelDesc>
      )}

      {/* Panels */}
      {tab === 'Observations'       && <IReflectionsPanel toast={toast} />}
      {tab === 'Attention Required' && <IEscalationsPanel toast={toast} />}
    </div>
  );
};
