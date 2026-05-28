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

const { useState: rUseState, useEffect: rUseEffect, useRef: rUseRef } = React;

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

function RConfirmBtn(props) {
  // thin alias so we read Btn off the global scope lazily at render time
  const B = window.Btn;
  return <B {...props} />;
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

// ════════════════════════════ TOPICS ════════════════════════════
function TopicsPage({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/topics', { pollMs: 15000 });
  const [sel, setSel] = rUseState(null);
  const [detail, setDetail] = rUseState(null);
  const [detailErr, setDetailErr] = rUseState(null);
  const [tab, setTab] = rUseState('Overview');
  const [showNew, setShowNew] = rUseState(false);

  window.useEvents((name) => { if (name && name.indexOf('topic') === 0) reload(); });

  const topics = (data && data.topics) || [];

  rUseEffect(() => {
    if (sel == null) { setDetail(null); setDetailErr(null); return; }
    let live = true;
    setDetail(null); setDetailErr(null);
    window.apiGet(`/api/topics/${sel}`)
      .then((d) => { if (live) setDetail(d); })
      .catch((e) => { if (live) setDetailErr(e.message); });
    return () => { live = false; };
  }, [sel]);

  async function del(id) {
    if (!window.confirm('Delete this topic and all of its sources? This cannot be undone.')) return;
    try {
      await window.apiDelete(`/api/topics/${id}`);
      setSel(null); reload();
      toast.show('Topic deleted', 'info');
    } catch (e) { toast.show(e.message, 'error'); }
  }

  const columns = [
    { key: 'name', label: 'Name', render: (r) => (
      <span style={{ fontFamily: 'var(--serif)', fontWeight: 600 }}>{r.name || 'Untitled'}</span>
    ) },
    { key: 'mode', label: 'Mode', render: (r) => r.mode || '—' },
    { key: 'source_count', label: 'Sources', render: (r) => (
      <span className="num">{r.source_count != null ? r.source_count : (r.sources ? r.sources.length : 0)}</span>
    ) },
    { key: 'status', label: '', render: (r) => (
      <window.StatusPill status={r.status === 'active' ? 'running' : 'paused'} />
    ) },
  ];

  const PageHeader = window.PageHeader, Btn = window.Btn;

  return (
    <div>
      <PageHeader title="Topics" subtitle={`${topics.length} standing ${topics.length === 1 ? 'watch' : 'watches'}`}
        actions={<Btn onClick={() => setShowNew(true)} aria-label="Create a new topic">+ New topic</Btn>} />

      {loading && <RTableSkeleton />}
      {!loading && error && <window.ErrorBox message={`Could not load topics — ${error}`} />}
      {!loading && !error && topics.length === 0 && (
        <window.EmptyState title="No topics yet" icon="🗺"
          hint="A topic is something Lighthouse watches for you — a feed, a question, a theme to track over time."
          action={<Btn onClick={() => setShowNew(true)}>+ New topic</Btn>} />
      )}

      {!loading && !error && topics.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: sel != null ? '1fr 380px' : '1fr', gap: 16 }}>
          <window.DataTable columns={columns} activeRow={sel}
            rows={topics.map((t) => ({ ...t, _key: t.id }))}
            onRow={(r) => { setSel(r.id); setTab('Overview'); }} />

          {sel != null && (
            <RSidePane title={detail ? detail.name : 'Loading…'}
              subtitle={detail ? detail.mode : ''}
              tabs={['Overview', 'Sources', 'Recent items']} activeTab={tab} onTab={setTab}
              onClose={() => setSel(null)}>
              {detailErr && <window.ErrorBox message={detailErr} />}
              {!detail && !detailErr && <div><RSkeleton /><RSkeleton w="80%" /><RSkeleton w="60%" /></div>}
              {detail && tab === 'Overview' && (
                <div>
                  <RRow k="Mode" v={detail.mode} />
                  <RRow k="Cadence" v={detail.cadence} />
                  <RRow k="Status" v={detail.status} />
                  <RRow k="Sources" v={(detail.sources || []).length} />
                  <RRow k="Created" v={detail.created_at} />
                  <div style={{ marginTop: 16 }}>
                    <Btn kind="danger" size="sm" onClick={() => del(detail.id)}
                      aria-label={`Delete topic ${detail.name}`}>Delete topic</Btn>
                  </div>
                </div>
              )}
              {detail && tab === 'Sources' && (
                (detail.sources || []).length
                  ? (detail.sources || []).map((s, i) => (
                    <div key={s.id != null ? s.id : i} style={{ display: 'flex', gap: 8,
                      alignItems: 'center', padding: '7px 0', borderBottom: '1px solid var(--rule-soft)' }}>
                      <RGrade grade={s.grade} />
                      <span style={{ fontSize: 12, color: 'var(--ink-2)', wordBreak: 'break-all' }}>
                        {s.url || s.name || '(unnamed source)'}
                      </span>
                    </div>
                  ))
                  : <div style={{ color: 'var(--muted)' }}>No sources attached to this topic yet.</div>
              )}
              {detail && tab === 'Recent items' && (
                (detail.recent_items || detail.items || []).length
                  ? (detail.recent_items || detail.items || []).map((it, i) => (
                    <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid var(--rule-soft)' }}>
                      <div style={{ fontFamily: 'var(--serif)', fontSize: 13.5, color: 'var(--ink)' }}>
                        {it.title || it.text || it.summary || 'Item'}
                      </div>
                      {it.ts && <div className="num" style={{ fontSize: 11, color: 'var(--muted)',
                        marginTop: 2 }}>{it.ts}</div>}
                    </div>
                  ))
                  : <div style={{ color: 'var(--muted)' }}>Items appear here after the first refresh.</div>
              )}
            </RSidePane>
          )}
        </div>
      )}

      {showNew && <RNewTopicModal toast={toast} onClose={() => setShowNew(false)}
        onCreated={() => { setShowNew(false); reload(); toast.show('Topic created', 'success'); }} />}
    </div>
  );
}

function RNewTopicModal({ toast, onClose, onCreated }) {
  const [name, setName] = rUseState('');
  const [mode, setMode] = rUseState('Monitor');
  const [sources, setSources] = rUseState('');
  const [busy, setBusy] = rUseState(false);
  const Btn = window.Btn;

  async function submit() {
    if (!name.trim()) { toast.show('Give the topic a name first.', 'error'); return; }
    const srcs = sources.split('\n').map((s) => s.trim()).filter(Boolean);
    setBusy(true);
    try {
      await window.apiPost('/api/topics', { name: name.trim(), mode, sources: srcs });
      onCreated();
    } catch (e) { toast.show(e.message, 'error'); setBusy(false); }
  }

  return (
    <RModal title="New topic" onClose={onClose}>
      <RField label="Name">
        <input value={name} onChange={(e) => setName(e.target.value)}
          placeholder="e.g. EU AI Act" style={rInput} aria-label="Topic name" autoFocus />
      </RField>
      <RField label="Mode">
        <select value={mode} onChange={(e) => setMode(e.target.value)} style={rInput} aria-label="Topic mode">
          {['Monitor', 'Deep-Dive', 'QUC'].map((m) => <option key={m}>{m}</option>)}
        </select>
      </RField>
      <RField label="Sources" hint="One URL per line. Optional — you can add them later.">
        <textarea value={sources} onChange={(e) => setSources(e.target.value)} rows={4}
          placeholder="https://hnrss.org/frontpage" style={{ ...rInput, resize: 'vertical' }}
          aria-label="Sources, one URL per line" />
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
  const [tab, setTab] = rUseState('Overdue');
  const PageHeader = window.PageHeader;
  return (
    <div>
      <PageHeader title="Positions" subtitle="Resolve predictions and watch your calibration improve"
        tabs={['Overdue', 'All', 'Calibration', 'Hypotheses']} activeTab={tab} onTab={setTab} />
      {tab === 'Overdue' && <RPositionList key="overdue" overdue toast={toast} />}
      {tab === 'All' && <RPositionList key="all" toast={toast} />}
      {tab === 'Calibration' && <RCalibrationView />}
      {tab === 'Hypotheses' && <RHypothesesView toast={toast} />}
    </div>
  );
}

function RPositionList({ overdue, toast }) {
  const path = overdue ? '/api/positions?overdue=true' : '/api/positions';
  const { data, loading, error, reload } = window.useApi(path);
  const positions = (data && data.positions) || [];

  async function resolve(id, outcome) {
    try {
      await window.apiPost(`/api/positions/${id}/resolve`, { outcome });
      reload();
      toast.show(outcome === 'defer' ? 'Deferred 30 days' : `Marked ${outcome}`, 'success');
    } catch (e) { toast.show(e.message, 'error'); }
  }

  if (loading) return <RTableSkeleton rows={3} />;
  if (error) return <window.ErrorBox message={`Could not load positions — ${error}`} />;
  if (!positions.length) {
    return <window.EmptyState icon="✓"
      title={overdue ? 'Nothing overdue' : 'No positions yet'}
      hint={overdue
        ? 'Every prediction is either resolved or still has time on the clock.'
        : 'Positions are recorded automatically when research emits a falsifiable claim.'} />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {positions.map((p) => {
        const open = p.outcome == null;
        return (
          <div key={p.id} style={{ ...window.card, padding: '14px 18px' }}>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 15, color: 'var(--ink)' }}>
              {p.claim || '(no claim text)'}
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
              <window.ConfidencePill phrase={p.wep_band || p.wep_phrase}
                band={p.confidence != null ? String(p.confidence) : ''} />
              {p.due_at && <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>due {p.due_at}</span>}
              {p.created_at && <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>created {p.created_at}</span>}
              <span style={{ flex: 1 }} />
              {open ? (
                <div style={{ display: 'flex', gap: 6 }} role="group" aria-label="Resolve position">
                  <window.Btn size="sm" kind="success" onClick={() => resolve(p.id, 'confirmed')}
                    aria-label="Mark confirmed">Confirmed</window.Btn>
                  <window.Btn size="sm" kind="danger" onClick={() => resolve(p.id, 'refuted')}
                    aria-label="Mark refuted">Refuted</window.Btn>
                  <window.Btn size="sm" kind="ghost" onClick={() => resolve(p.id, 'defer')}
                    aria-label="Defer 30 days">Defer 30d</window.Btn>
                </div>
              ) : (
                <span className="num" style={{ fontSize: 12,
                  color: p.outcome === 'refuted' || p.outcome === false ? 'var(--coral-2)' : 'var(--green-dark)' }}>
                  {p.outcome === false ? 'refuted' : p.outcome === true ? 'confirmed' : p.outcome}
                  {p.brier != null && ` · Brier ${Number(p.brier).toFixed(3)}`}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RCalibrationView() {
  const { data, loading, error } = window.useApi('/api/calibration');
  const canvasRef = rUseRef(null);
  const m = data || {};
  const bins = m.bins || m.reliability || [];

  rUseEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const W = 320, H = 320, pad = 32;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const x = (v) => pad + v * (W - 2 * pad);
    const y = (v) => (H - pad) - v * (H - 2 * pad);
    // grid box
    ctx.strokeStyle = '#d4e2ed'; ctx.lineWidth = 1;
    ctx.strokeRect(pad, pad, W - 2 * pad, H - 2 * pad);
    // perfect-calibration diagonal
    ctx.strokeStyle = '#6a8aa6'; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(x(0), y(0)); ctx.lineTo(x(1), y(1)); ctx.stroke();
    ctx.setLineDash([]);
    // points
    ctx.fillStyle = '#0288d1';
    (bins || []).forEach((b) => {
      const px = b.predicted != null ? b.predicted : b.confidence;
      const py = b.observed != null ? b.observed : b.outcome_rate;
      if (px == null || py == null) return;
      ctx.beginPath();
      const r = 4 + Math.min((b.n || 1), 20) * 0.5;
      ctx.arc(x(px), y(py), r, 0, Math.PI * 2);
      ctx.globalAlpha = 0.75; ctx.fill(); ctx.globalAlpha = 1;
    });
    // axis labels
    ctx.fillStyle = '#6a8aa6'; ctx.font = '10px sans-serif';
    ctx.fillText('predicted →', pad, H - 8);
    ctx.save(); ctx.translate(10, H - pad); ctx.rotate(-Math.PI / 2);
    ctx.fillText('observed →', 0, 0); ctx.restore();
  }, [data]);

  if (loading) return <RTableSkeleton rows={2} />;
  if (error) return <window.ErrorBox message={`Could not load calibration — ${error}`} />;
  const n = m.n != null ? m.n : m.resolved;
  if (!n) {
    return <window.EmptyState icon="◎" title="No resolved positions yet"
      hint="Resolve a handful of predictions and your reliability curve will appear here." />;
  }

  const brier = m.mean_brier != null ? m.mean_brier : m.brier;
  return (
    <div style={{ ...window.card, padding: 24 }}>
      <div style={{ display: 'flex', gap: 40, flexWrap: 'wrap', marginBottom: 24 }}>
        <RMetric label="Mean Brier" value={brier != null ? Number(brier).toFixed(3) : '—'} hint="lower is better" />
        <RMetric label="Resolved" value={n} />
        <RMetric label="Avg confidence"
          value={m.mean_probability != null ? Number(m.mean_probability).toFixed(2) : '—'} />
        <RMetric label="Hit rate"
          value={m.mean_outcome_rate != null ? Number(m.mean_outcome_rate).toFixed(2) : '—'} />
        <RMetric label="Calibration error"
          value={m.calibration_error != null ? Number(m.calibration_error).toFixed(3) : '—'}
          hint="|confidence − outcome|" />
      </div>
      <div className="small-caps" style={{ marginBottom: 8 }}>Reliability diagram</div>
      {bins && bins.length
        ? <canvas ref={canvasRef} role="img"
            aria-label="Reliability scatter: predicted probability versus observed outcome rate" />
        : <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Not enough binned data yet to plot a reliability curve.</div>}
    </div>
  );
}

function RHypothesesView({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/hypotheses');
  const [stmt, setStmt] = rUseState('');
  const [busy, setBusy] = rUseState(false);
  const cols = ['open', 'supported', 'refuted', 'retired'];
  const items = (data && data.hypotheses) || [];
  const Btn = window.Btn;

  const colColor = { open: 'var(--primary)', supported: 'var(--green-dark)',
    refuted: 'var(--coral-2)', retired: 'var(--muted)' };

  async function add() {
    if (!stmt.trim()) { toast.show('Type a hypothesis first.', 'error'); return; }
    setBusy(true);
    try {
      await window.apiPost('/api/hypotheses', { statement: stmt.trim() });
      setStmt(''); reload(); toast.show('Hypothesis added', 'success');
    } catch (e) { toast.show(e.message, 'error'); }
    setBusy(false);
  }
  async function move(h, status) {
    try { await window.apiPatch(`/api/hypotheses/${h.id}`, { status }); reload(); }
    catch (e) { toast.show(e.message, 'error'); }
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
        <input value={stmt} onChange={(e) => setStmt(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') add(); }}
          placeholder="State a new hypothesis…" aria-label="New hypothesis"
          style={{ ...rInput, flex: 1 }} />
        <Btn onClick={add} disabled={busy}>{busy ? 'Adding…' : 'Add'}</Btn>
      </div>

      {loading && <RTableSkeleton rows={3} />}
      {error && <window.ErrorBox message={`Could not load hypotheses — ${error}`} />}
      {!loading && !error && items.length === 0 && (
        <window.EmptyState icon="🜂" title="No hypotheses yet"
          hint="Frame a falsifiable statement above; evidence will sort it across the board." />
      )}

      {!loading && !error && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {cols.map((col) => {
            const inCol = items.filter((h) => h.status === col);
            return (
              <div key={col} style={{ ...window.card, padding: 10, minHeight: 200 }}>
                <div className="small-caps" style={{ color: colColor[col] }}>
                  {col} ({inCol.length})
                </div>
                {inCol.length === 0 && <div style={{ fontSize: 11, color: 'var(--muted)',
                  marginTop: 8 }}>—</div>}
                {inCol.map((h) => (
                  <div key={h.id} style={{ ...window.card, padding: 8, margin: '8px 0', fontSize: 12.5 }}>
                    <div style={{ fontFamily: 'var(--serif)', color: 'var(--ink)' }}>{h.statement}</div>
                    <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
                      {cols.filter((c) => c !== col).map((c) => (
                        <button key={c} onClick={() => move(h, c)} title={`Move to ${c}`}
                          aria-label={`Move hypothesis to ${c}`}
                          style={{ fontSize: 9, border: '1px solid var(--rule)', borderRadius: 3,
                            background: 'var(--card)', cursor: 'pointer', color: 'var(--muted)',
                            padding: '2px 5px', fontWeight: 700, letterSpacing: '0.04em' }}>
                          → {c[0].toUpperCase()}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ════════════════════════════ HEALTH ════════════════════════════
function HealthPage({ toast }) {
  const [tab, setTab] = rUseState('Overview');
  const { data, loading, error, reload } = window.useApi('/api/health', { pollMs: 10000 });
  const h = data || {};
  const PageHeader = window.PageHeader, Btn = window.Btn;

  return (
    <div>
      <PageHeader title="Health"
        subtitle={loading ? 'Checking…' : h.overall === 'green' ? 'All systems nominal' : 'Some items need attention'}
        tabs={['Overview', 'Budget', 'Storage', 'Audit']} activeTab={tab} onTab={setTab}
        actions={<Btn kind="ghost" onClick={reload} aria-label="Re-check health now">Re-check</Btn>} />

      {loading && tab !== 'Audit' && <RTableSkeleton rows={5} />}
      {!loading && error && tab !== 'Audit' && (
        <window.ErrorBox message={`Could not reach the health endpoint — ${error}`} />
      )}
      {!loading && !error && tab === 'Overview' && <RHealthOverview h={h} />}
      {!loading && !error && tab === 'Budget' && <RHealthBudget h={h} toast={toast} reload={reload} />}
      {!loading && !error && tab === 'Storage' && <RHealthStorage h={h} />}
      {tab === 'Audit' && <RHealthAudit toast={toast} />}
    </div>
  );
}

function RHealthRow({ ok, label, detail, expandable, children }) {
  const [open, setOpen] = rUseState(false);
  const mark = ok
    ? <span style={{ color: 'var(--green-dark)' }} aria-label="healthy">✓</span>
    : <span style={{ color: 'var(--coral-2)' }} aria-label="needs attention">!</span>;
  const canExpand = !ok && expandable;
  return (
    <div style={{ borderBottom: '1px solid var(--rule-soft)', paddingBottom: 6 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 13.5,
        cursor: canExpand ? 'pointer' : 'default' }}
        onClick={canExpand ? () => setOpen((o) => !o) : undefined}
        role={canExpand ? 'button' : undefined} tabIndex={canExpand ? 0 : undefined}
        onKeyDown={canExpand ? (e) => { if (e.key === 'Enter') setOpen((o) => !o); } : undefined}>
        <span style={{ width: 16, textAlign: 'center', fontWeight: 700 }}>{mark}</span>
        <span style={{ width: 110, fontWeight: 600, color: 'var(--ink)' }}>{label}</span>
        <span style={{ color: ok ? 'var(--ink-2)' : 'var(--coral-2)', flex: 1 }}>{detail}</span>
        {canExpand && <span style={{ color: 'var(--muted)' }}>{open ? '▾' : '▸'}</span>}
      </div>
      {canExpand && open && <div style={{ paddingLeft: 28, marginTop: 6 }}>{children}</div>}
    </div>
  );
}

function RHealthOverview({ h }) {
  const dbVals = h.databases ? Object.values(h.databases) : [];
  const dbOk = dbVals.length > 0 && dbVals.every((v) => v === 'ok');
  const extOllamaOk = !!(h.external && h.external.ollama);
  const budgetOk = !!(h.budget && h.budget.tier === 'green');
  const chainOk = h.audit_chain_ok !== false;
  const healthy = h.overall === 'green';

  return (
    <div style={{ ...window.card, padding: 24, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <RHealthRow ok={true} label="Hardware"
        detail={h.hardware
          ? `${h.hardware.platform || '?'} ${h.hardware.arch || ''} · ${h.hardware.total_ram_gb ?? '?'} GB · tier ${h.hardware.tier ?? '?'}`
          : 'detected'} />
      <RHealthRow ok={true} label="Storage"
        detail={h.storage
          ? `${(h.storage.disk_total_gb || 0) - (h.storage.disk_free_gb || 0)} GB used · ${h.storage.disk_free_gb ?? '?'} GB free`
          : 'available'} />
      <RHealthRow ok={dbOk} label="Databases" expandable
        detail={h.databases
          ? `${dbVals.filter((v) => v === 'ok').length} of ${dbVals.length} healthy`
          : 'unknown'}>
        {h.databases && Object.entries(h.databases).map(([name, st]) => (
          <RRow key={name} k={name} v={st} accent={st === 'ok' ? 'var(--green-dark)' : 'var(--coral-2)'} />
        ))}
      </RHealthRow>
      <RHealthRow ok={chainOk} label="Audit chain" expandable
        detail={chainOk ? 'intact' : 'BROKEN — verify on the Audit tab'}>
        <div style={{ fontSize: 12, color: 'var(--coral-2)' }}>
          The hash chain failed verification. Open the Audit tab and run “Verify chain” to find the break.
        </div>
      </RHealthRow>
      <RHealthRow ok={extOllamaOk} label="External" expandable
        detail={h.external
          ? `ollama ${extOllamaOk ? '✓' : 'offline'} · qdrant ${h.external.qdrant ? '✓' : 'offline (optional)'}`
          : 'unknown'}>
        <div style={{ fontSize: 12, color: 'var(--coral-2)' }}>
          Ollama is unreachable. Start it with <span className="num">ollama serve</span> so local models can run.
        </div>
      </RHealthRow>
      <RHealthRow ok={budgetOk} label="Budget" expandable
        detail={h.budget
          ? `$${h.budget.usd ? h.budget.usd.used : '?'} of $${h.budget.usd ? h.budget.usd.cap : '?'} monthly · tier ${h.budget.tier}`
          : 'unknown'}>
        <div style={{ fontSize: 12, color: 'var(--coral-2)' }}>
          A budget tier above green throttles spend. Review or reset buckets on the Budget tab.
        </div>
      </RHealthRow>

      <div style={{ marginTop: 10, fontSize: 13,
        color: healthy ? 'var(--green-dark)' : 'var(--coral-2)' }}>
        {healthy ? 'Everything looks good. No action needed.' : 'Expand the flagged rows above for next steps.'}
      </div>
    </div>
  );
}

function RHealthBudget({ h, toast, reload }) {
  if (!h.budget) {
    return <window.EmptyState icon="◔" title="No budget data"
      hint="The governor hasn’t reported budget buckets yet." />;
  }
  const b = h.budget;
  const Btn = window.Btn;

  async function reset() {
    if (!window.confirm('Reset all budget buckets back to zero?')) return;
    try { await window.apiPost('/api/governor/reset'); reload(); toast.show('Budget reset', 'success'); }
    catch (e) { toast.show(e.message, 'error'); }
  }
  async function kill() {
    if (!window.confirm('Engage the kill switch and stop ALL running jobs? This halts the supervisor.')) return;
    try { await window.apiPost('/api/governor/kill'); reload(); toast.show('Kill switch engaged', 'error'); }
    catch (e) { toast.show(e.message, 'error'); }
  }

  const line = (label, bucket, fmt) => {
    if (!bucket) return null;
    const used = bucket.used || 0, cap = bucket.cap || 0;
    const hot = cap > 0 && used / cap > 0.85;
    return (
      <div key={label} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '6px 0' }}>
        <span style={{ width: 150, fontSize: 12.5, color: 'var(--ink-2)' }}>{label}</span>
        <window.Bar value={used} max={cap} color={hot ? 'var(--coral-2)' : 'var(--primary)'} />
        <span className="num" style={{ fontSize: 12, color: hot ? 'var(--coral-2)' : 'var(--ink)' }}>
          {fmt(used)} of {fmt(cap)}
        </span>
      </div>
    );
  };

  return (
    <div style={{ ...window.card, padding: 24 }}>
      {line('USD (monthly)', b.usd, (v) => `$${v}`)}
      {line('Tokens (daily)', b.tokens, (v) => `${(v / 1e6).toFixed(1)}M`)}
      {line('Tool calls (daily)', b.tool_calls, (v) => `${v}`)}
      <div style={{ marginTop: 14, fontSize: 13 }}>Tier: <b style={{
        color: b.tier === 'green' ? 'var(--green-dark)' : 'var(--coral-2)' }}>{b.tier}</b></div>
      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        <Btn kind="ghost" onClick={reset}>Reset budget</Btn>
        <Btn kind="danger" onClick={kill}>Kill all jobs</Btn>
      </div>
    </div>
  );
}

function RHealthStorage({ h }) {
  if (!h.storage) {
    return <window.EmptyState icon="◇" title="No storage data"
      hint="Disk usage hasn’t been reported yet." />;
  }
  const s = h.storage;
  const subdirs = s.subdirs_bytes || {};
  const maxBytes = Math.max(1, ...Object.values(subdirs));
  const replicas = s.replicas || [];

  return (
    <div style={{ ...window.card, padding: 24 }}>
      <div style={{ marginBottom: 16, fontSize: 13 }}>
        <b>{(s.disk_total_gb || 0) - (s.disk_free_gb || 0)} GB</b> used of {s.disk_total_gb ?? '?'} GB
        {' '}({s.disk_free_gb ?? '?'} GB free)
      </div>
      <div className="small-caps" style={{ marginBottom: 6 }}>By subdirectory</div>
      {Object.keys(subdirs).length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>No subdirectory breakdown reported.</div>
      )}
      {Object.entries(subdirs).map(([name, bytes]) => (
        <div key={name} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '4px 0' }}>
          <span style={{ width: 100, fontSize: 12, color: 'var(--ink-2)' }}>{name}/</span>
          <window.Bar value={bytes} max={maxBytes} />
          <span className="num" style={{ fontSize: 11, color: 'var(--muted)', width: 70, textAlign: 'right' }}>
            {(bytes / 1e6).toFixed(1)} MB
          </span>
        </div>
      ))}
      <div className="small-caps" style={{ marginTop: 18, marginBottom: 6 }}>Litestream replicas</div>
      {replicas.length === 0 && <div style={{ fontSize: 12, color: 'var(--muted)' }}>No replicas configured.</div>}
      {replicas.map((r) => (
        <div key={r.name} style={{ fontSize: 12, padding: '3px 0', color: 'var(--ink-2)' }}>
          {r.name}: {r.lag_seconds == null
            ? <span style={{ color: 'var(--muted)' }}>no snapshot yet</span>
            : <span className="num" style={{ color: r.lag_seconds > 60 ? 'var(--coral-2)' : 'var(--green-dark)' }}>
                lag {r.lag_seconds}s</span>}
        </div>
      ))}
    </div>
  );
}

function RHealthAudit({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/audit?limit=100', { pollMs: 10000 });
  const events = (data && data.events) || [];
  const [verifying, setVerifying] = rUseState(false);
  window.useEvents((name) => { if (name === 'audit.appended') reload(); });

  async function verify() {
    setVerifying(true);
    try {
      const r = await window.apiPost('/api/audit/verify');
      toast.show(r.ok ? 'Chain intact ✓' : `BROKEN at ${r.bad_seqs || '?'}`, r.ok ? 'success' : 'error');
    } catch (e) { toast.show(e.message, 'error'); }
    setVerifying(false);
  }

  const columns = [
    { key: 'seq', label: 'Seq', render: (r) => <span className="num">{r.seq}</span> },
    { key: 'ts', label: 'Time', render: (r) => <span className="num" style={{ fontSize: 11 }}>{r.ts}</span> },
    { key: 'actor', label: 'Actor', render: (r) => r.actor || '—' },
    { key: 'event_type', label: 'Event', render: (r) => r.event_type || r.type || '—' },
  ];

  return (
    <div>
      <div style={{ marginBottom: 10 }}>
        <window.Btn kind="ghost" onClick={verify} disabled={verifying}
          aria-label="Verify the audit hash chain">{verifying ? 'Verifying…' : 'Verify chain'}</window.Btn>
      </div>
      {loading && <RTableSkeleton rows={6} />}
      {!loading && error && <window.ErrorBox message={`Could not load the audit log — ${error}`} />}
      {!loading && !error && (
        <window.DataTable columns={columns} rows={events.map((e) => ({ ...e, _key: e.seq }))}
          empty={<window.EmptyState icon="🗒" title="No audit events yet"
            hint="Every governed action appends a tamper-evident entry here." />} />
      )}
    </div>
  );
}

// ════════════════════════════ SETTINGS ════════════════════════════
function SettingsPage({ toast }) {
  const [tab, setTab] = rUseState('General');
  const PageHeader = window.PageHeader;
  return (
    <div>
      <PageHeader title="Settings"
        tabs={['General', 'Models', 'Secrets', 'Skills', 'Perspectives', 'Advanced']}
        activeTab={tab} onTab={setTab} />
      {tab === 'General' && <RSettingsGeneral />}
      {tab === 'Models' && <RSettingsModels />}
      {tab === 'Secrets' && <RSettingsSecrets toast={toast} />}
      {tab === 'Skills' && <RSimpleList path="/api/skills" keyName="skills"
        emptyTitle="No skills curated yet"
        emptyHint="Skills accumulate as Lighthouse learns reusable research procedures."
        render={(s) => (
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontFamily: 'var(--serif)', color: 'var(--ink)' }}>{s.name || 'Unnamed skill'}</span>
            <span className="num" style={{ color: 'var(--muted)', fontSize: 12 }}>
              used {s.use_count != null ? s.use_count : 0}×</span>
          </div>
        )} />}
      {tab === 'Perspectives' && <RSimpleList path="/api/perspectives" keyName="perspectives"
        emptyTitle="No perspectives defined"
        emptyHint="Perspectives are stances the debate engine argues from."
        render={(p) => (
          <div>
            <span style={{ fontFamily: 'var(--serif)', fontWeight: 600, color: 'var(--ink)' }}>{p.name || 'Unnamed'}</span>
            {p.stance && <span style={{ color: 'var(--ink-2)' }}> — {p.stance}</span>}
          </div>
        )} />}
      {tab === 'Advanced' && <RSettingsAdvanced />}
    </div>
  );
}

function RSettingsGeneral() {
  const { data, loading, error } = window.useApi('/api/settings');
  if (loading) return <RTableSkeleton rows={5} />;
  if (error) return <window.ErrorBox message={`Could not load settings — ${error}`} />;
  const cfg = (data && data.config) || {};
  const lh = cfg.lighthouse || {}, hw = cfg.hardware || {}, ls = cfg.logseq || {}, tg = cfg.telegram || {};
  return (
    <div style={{ ...window.card, padding: 24 }}>
      <RRow k="Version" v={lh.version} />
      <RRow k="Data dir" v={lh.data_dir || '~/.lighthouse'} />
      <RRow k="Detected tier" v={hw.detected_tier} />
      <RRow k="Logseq" v={ls.enabled ? (ls.graph_path || 'enabled') : 'disabled'} />
      <RRow k="Telegram" v={tg.enabled ? 'enabled' : 'disabled'} />
      <div style={{ marginTop: 14, fontSize: 12, color: 'var(--muted)' }}>
        Edit these in the Advanced tab or directly in <span className="num">~/.lighthouse/config.toml</span>.
      </div>
    </div>
  );
}

function RSettingsModels() {
  const { data, loading, error } = window.useApi('/api/health');
  if (loading) return <RTableSkeleton rows={3} />;
  if (error) return <window.ErrorBox message={`Could not reach the model host — ${error}`} />;
  const ext = (data && data.external) || {};
  return (
    <div style={{ ...window.card, padding: 24 }}>
      <RRow k="Ollama" v={ext.ollama ? 'reachable ✓' : 'offline — run ollama serve'}
        accent={ext.ollama ? 'var(--green-dark)' : 'var(--coral-2)'} />
      <RRow k="Qdrant" v={ext.qdrant ? 'reachable ✓' : 'offline (optional)'}
        accent={ext.qdrant ? 'var(--green-dark)' : 'var(--muted)'} />
      <div style={{ marginTop: 12, fontSize: 12, color: 'var(--muted)' }}>
        Pull models from the CLI: <span className="num">lighthouse models pull qwen3:8b</span>
      </div>
    </div>
  );
}

function RSettingsSecrets({ toast }) {
  const { data, loading, error, reload } = window.useApi('/api/secrets');
  const [key, setKey] = rUseState('');
  const [val, setVal] = rUseState('');
  const [busy, setBusy] = rUseState(false);
  const secrets = (data && data.secrets) || {};
  const Btn = window.Btn;

  async function save() {
    if (!key.trim()) { toast.show('Provide a key name.', 'error'); return; }
    setBusy(true);
    try {
      await window.apiPost('/api/secrets', { key: key.trim(), value: val });
      setKey(''); setVal(''); reload(); toast.show('Secret stored', 'success');
    } catch (e) { toast.show(e.message, 'error'); }
    setBusy(false);
  }

  if (loading) return <RTableSkeleton rows={3} />;
  if (error) return <window.ErrorBox message={`Could not load secrets — ${error}`} />;

  return (
    <div style={{ ...window.card, padding: 24 }}>
      {Object.keys(secrets).length === 0 && (
        <div style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 12 }}>
          No secrets stored in the file store. (Keychain entries are not listable.)
        </div>
      )}
      {Object.entries(secrets).map(([k, v]) => <RRow key={k} k={k} v={v} />)}
      <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
        <input value={key} onChange={(e) => setKey(e.target.value)} placeholder="key"
          aria-label="Secret key" style={{ ...rInput, width: 200 }} />
        <input value={val} onChange={(e) => setVal(e.target.value)} type="password"
          placeholder="value (masked)" aria-label="Secret value"
          style={{ ...rInput, flex: 1, minWidth: 160 }} />
        <Btn onClick={save} disabled={busy}>{busy ? 'Storing…' : 'Store'}</Btn>
      </div>
      <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
        Values are write-only from here and are never echoed back in full.
      </div>
    </div>
  );
}

function RSettingsAdvanced() {
  const { data, loading, error } = window.useApi('/api/settings');
  if (loading) return <RTableSkeleton rows={6} />;
  if (error) return <window.ErrorBox message={`Could not load settings — ${error}`} />;
  return (
    <div style={{ ...window.card, padding: 24 }}>
      <div className="small-caps" style={{ marginBottom: 8 }}>config.toml (read-only preview)</div>
      <pre style={{ fontFamily: 'var(--mono)', fontSize: 11.5, background: 'var(--rule-soft)',
        padding: 14, borderRadius: 8, overflow: 'auto', maxHeight: 420, margin: 0,
        color: 'var(--ink)' }}>
        {JSON.stringify((data && data.config) || {}, null, 2)}
      </pre>
    </div>
  );
}

function RSimpleList({ path, keyName, emptyTitle, emptyHint, render }) {
  const { data, loading, error } = window.useApi(path);
  if (loading) return <RTableSkeleton rows={3} />;
  if (error) return <window.ErrorBox message={`Could not load — ${error}`} />;
  const items = (data && data[keyName]) || [];
  if (!items.length) return <window.EmptyState icon="◌" title={emptyTitle} hint={emptyHint} />;
  return (
    <div style={{ ...window.card, padding: 16 }}>
      {items.map((it, i) => (
        <div key={i} style={{ padding: '9px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 13 }}>
          {render(it)}
        </div>
      ))}
    </div>
  );
}

// ── export ────────────────────────────────────────────────────────────────
Object.assign(window, { TopicsPage, PositionsPage, HealthPage, SettingsPage });
