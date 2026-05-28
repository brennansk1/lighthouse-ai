// app-pages-today.jsx — polished Home · Jobs · Drafts for the Lighthouse
// dashboard. Static React (UMD + babel-standalone), one shared browser scope,
// no imports. Defines HomePage / JobsPage / DraftsPage and hangs them on
// window at the end. Uses the global primitives from app-lib.jsx and provides
// its own small, file-local helpers (Modal, Field, etc.) so it never depends
// on declarations leaking from sibling scripts.

(function () {
  const { useState, useEffect, useRef, useCallback } = React;

  // ── file-local helpers (kept private to avoid clobbering window) ────────
  const inputStyle = {
    fontFamily: 'var(--sans)', fontSize: 13, padding: '8px 10px',
    border: '1px solid var(--rule)', borderRadius: 6, color: 'var(--ink)',
    background: 'var(--card)', width: '100%', outline: 'none',
  };

  function Field({ label, children, htmlFor }) {
    return (
      <div style={{ marginBottom: 12 }}>
        {label && <label htmlFor={htmlFor} style={{ display: 'block', fontSize: 11,
          fontWeight: 600, color: 'var(--muted)', marginBottom: 4,
          textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</label>}
        {children}
      </div>
    );
  }

  function Row({ k, v }) {
    return (
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16,
        padding: '6px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 13 }}>
        <span style={{ color: 'var(--muted)' }}>{k}</span>
        <span className="num" style={{ color: 'var(--ink)', fontWeight: 500,
          textAlign: 'right', wordBreak: 'break-word' }}>{v == null ? '—' : String(v)}</span>
      </div>
    );
  }

  function Metric({ label, value, hint, accent }) {
    return (
      <div>
        <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
          letterSpacing: '0.06em' }}>{label}</div>
        <div className="num" style={{ fontSize: 28, fontWeight: 600,
          color: accent ? 'var(--coral-2)' : 'var(--ink)' }}>{value}</div>
        {hint && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{hint}</div>}
      </div>
    );
  }

  // Shimmering placeholder block while data loads.
  function Skeleton({ h = 16, w = '100%', r = 6, style }) {
    return (
      <div aria-hidden="true" style={{ height: h, width: w, borderRadius: r,
        background: 'linear-gradient(90deg, var(--rule-soft) 25%, var(--rule) 37%, var(--rule-soft) 63%)',
        backgroundSize: '400% 100%', animation: 'lhshimmer 1.4s ease infinite', ...style }} />
    );
  }

  // Right-hand slide-over panel with a backdrop. Closes on Esc / backdrop click.
  function SidePane({ title, subtitle, onClose, children, footer }) {
    useEffect(() => {
      const onKey = (e) => { if (e.key === 'Escape') onClose(); };
      window.addEventListener('keydown', onKey);
      return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);
    return (
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 480,
        background: 'rgba(10,42,68,0.30)', display: 'flex', justifyContent: 'flex-end' }}>
        <div role="dialog" aria-modal="true" aria-label={title || 'Detail'}
          onClick={(e) => e.stopPropagation()} style={{ width: 460, maxWidth: '92vw',
            height: '100%', background: 'var(--card)', boxShadow: 'var(--shadow-lg)',
            display: 'flex', flexDirection: 'column', borderLeft: '1px solid var(--rule)' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
            gap: 12, padding: '18px 22px', borderBottom: '1px solid var(--rule)' }}>
            <div>
              <h2 style={{ fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 19,
                margin: 0, color: 'var(--ink)' }}>{title}</h2>
              {subtitle && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 3 }}>{subtitle}</div>}
            </div>
            <button onClick={onClose} aria-label="Close panel" style={{ background: 'none',
              border: 'none', cursor: 'pointer', fontSize: 20, lineHeight: 1, color: 'var(--muted)',
              padding: 4 }}>×</button>
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: '18px 22px' }}>{children}</div>
          {footer && <div style={{ padding: '14px 22px', borderTop: '1px solid var(--rule)' }}>{footer}</div>}
        </div>
      </div>
    );
  }

  // Centered modal dialog. Closes on Esc / backdrop click.
  function Modal({ title, onClose, children }) {
    useEffect(() => {
      const onKey = (e) => { if (e.key === 'Escape') onClose(); };
      window.addEventListener('keydown', onKey);
      return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);
    return (
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 500,
        background: 'rgba(10,42,68,0.35)', display: 'flex', alignItems: 'center',
        justifyContent: 'center', padding: 20 }}>
        <div role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
          style={{ ...card, padding: 24, width: 460, maxWidth: '100%',
            boxShadow: 'var(--shadow-lg)' }}>
          <h2 style={{ fontFamily: 'var(--serif)', fontSize: 19, margin: '0 0 16px',
            color: 'var(--ink)' }}>{title}</h2>
          {children}
        </div>
      </div>
    );
  }

  // Ensure the keyframes the Skeleton needs exist (idempotent).
  (function injectStyles() {
    if (document.getElementById('lh-today-styles')) return;
    const el = document.createElement('style');
    el.id = 'lh-today-styles';
    el.textContent =
      '@keyframes lhshimmer{0%{background-position:100% 0}100%{background-position:-100% 0}}' +
      '.lh-stat-card{transition:box-shadow .15s ease, transform .15s ease}' +
      '.lh-stat-card:hover{box-shadow:var(--shadow);transform:translateY(-1px)}' +
      '.lh-draft-item:focus-visible,.lh-stat-card:focus-visible{outline:2px solid var(--primary);outline-offset:2px}';
    document.head.appendChild(el);
  })();

  // ════════════════════════════ HOME ════════════════════════════
  function StatCard({ label, value, href, hint, accent, loading }) {
    return (
      <a href={href} className="lh-stat-card" style={{ textDecoration: 'none', display: 'block',
        ...card, padding: '16px 18px',
        borderLeft: `3px solid ${accent ? 'var(--coral-2)' : 'var(--primary)'}` }}>
        <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
          letterSpacing: '0.06em' }}>{label}</div>
        {loading
          ? <Skeleton h={30} w={64} style={{ margin: '6px 0 2px' }} />
          : <div className="num" style={{ fontSize: 30, fontWeight: 600, color: 'var(--ink)' }}>{value}</div>}
        {hint && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{hint}</div>}
      </a>
    );
  }

  function HomePage({ toast }) {
    const { data, loading, error, reload } = useApi('/api/dashboard', { pollMs: 10000 });
    useEvents(() => reload());
    useEffect(() => { if (error) toast.show(`Couldn't refresh dashboard: ${error}`, 'error'); }, [error]);

    const d = data || {};
    const cal = d.calibration || {};
    const jobs = Array.isArray(d.jobs) ? d.jobs : [];
    const running = jobs.filter((j) => j && j.status === 'running');
    const review = jobs.filter((j) => j && (j.status === 'review' || j.status === 'staged'));
    const alerts = Array.isArray(d.alerts) ? d.alerts : [];
    const digest = Array.isArray(d.digest) ? d.digest : [];
    const firstLoad = loading && !data;

    return (
      <div>
        <PageHeader title={d.greeting || 'Good morning'}
          subtitle={d.date || new Date().toLocaleDateString(undefined,
            { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })} />

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 18 }}>
          <StatCard label="Running now" value={running.length} href="#jobs" loading={firstLoad} />
          <StatCard label="Awaiting approval" value={review.length} href="#drafts"
            accent={review.length > 0} loading={firstLoad} />
          <StatCard label="Calibration (Brier)"
            value={cal.brier != null ? Number(cal.brier).toFixed(3) : '—'}
            href="#positions" hint="lower is better" loading={firstLoad} />
        </div>

        {firstLoad && <div style={{ ...card, padding: '20px 24px', marginBottom: 18 }}>
          <Skeleton h={12} w={90} />
          <Skeleton h={24} w="70%" style={{ margin: '12px 0 8px' }} />
          <Skeleton h={14} w="90%" />
        </div>}

        {!firstLoad && d.lead && <div style={{ ...card, padding: '20px 24px', marginBottom: 18 }}>
          <div className="small-caps" style={{ color: 'var(--coral-2)' }}>Lead finding</div>
          <h2 style={{ fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 24,
            margin: '8px 0', color: 'var(--ink)' }}>{d.lead.title}</h2>
          {d.lead.dek && <p style={{ fontFamily: 'var(--serif)', fontSize: 15, lineHeight: 1.55,
            color: 'var(--ink-2)', margin: 0 }}>{d.lead.dek}</p>}
          {d.lead.wep && <div style={{ marginTop: 12 }}>
            <ConfidencePill phrase={d.lead.wep.phrase} band={d.lead.wep.band} />
          </div>}
        </div>}

        {!firstLoad && !d.lead && <div style={{ ...card, padding: '20px 24px', marginBottom: 18,
          fontFamily: 'var(--serif)', fontSize: 14, color: 'var(--ink-2)' }}>
          <div className="small-caps" style={{ color: 'var(--coral-2)' }}>Lead finding</div>
          <div style={{ marginTop: 8 }}>No headline yet today. When a job surfaces something worth your
            attention, it will appear here. <a href="#jobs" style={{ color: 'var(--primary)' }}>Start a job →</a></div>
        </div>}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 16 }}>
          <div style={{ ...card, padding: '16px 20px' }}>
            <div className="small-caps">Alerts</div>
            {firstLoad && <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Skeleton h={14} /><Skeleton h={14} w="80%" /></div>}
            {!firstLoad && alerts.length === 0 && <div style={{ fontSize: 13, color: 'var(--muted)',
              marginTop: 8 }}>Nothing needs your attention.</div>}
            {!firstLoad && alerts.map((a, i) => (
              <div key={i} style={{ marginTop: 10 }}>
                <div className="num" style={{ fontSize: 10, color: 'var(--coral-2)',
                  letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 700 }}>{a.kind}</div>
                <div style={{ fontFamily: 'var(--serif)', fontSize: 13.5, color: 'var(--ink)' }}>{a.text}</div>
              </div>
            ))}
          </div>
          <div style={{ ...card, padding: '16px 20px' }}>
            <div className="small-caps">Topic activity — last 24h</div>
            {firstLoad && <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Skeleton h={14} /><Skeleton h={14} w="85%" /><Skeleton h={14} w="60%" /></div>}
            {!firstLoad && digest.length === 0 && <div style={{ fontSize: 13, color: 'var(--muted)',
              marginTop: 8 }}>No topic activity yet.{' '}
              <a href="#topics" style={{ color: 'var(--primary)' }}>Add a topic to watch →</a></div>}
            {!firstLoad && digest.map((item, i) => (
              <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid var(--rule-soft)' }}>
                <div style={{ fontWeight: 700, fontSize: 11, color: 'var(--primary)',
                  letterSpacing: '0.06em' }}>{String(item.topic || '').toUpperCase()}</div>
                <div style={{ fontFamily: 'var(--serif)', fontSize: 13.5, marginTop: 3 }}>{item.delta}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ════════════════════════════ JOBS ════════════════════════════
  const JOB_MODES = ['Deep-Dive', 'Monitor', 'QUC', 'Debate', 'Digest'];
  const JOB_DEPTHS = ['Scan', 'Standard', 'Thorough', 'Exhaustive'];

  function JobsPage({ toast }) {
    const { data, loading, error, reload } = useApi('/api/jobs', { pollMs: 10000 });
    const [showNew, setShowNew] = useState(false);
    const [selId, setSelId] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    useEvents((name) => { if (name && name.indexOf('job.') === 0) reload(); });
    useEffect(() => { if (error) toast.show(`Jobs failed to load: ${error}`, 'error'); }, [error]);

    const jobs = (data && Array.isArray(data.jobs)) ? data.jobs : [];

    useEffect(() => {
      if (selId == null) { setDetail(null); return; }
      let live = true;
      setDetailLoading(true);
      apiGet(`/api/jobs/${selId}`)
        .then((d) => { if (live) setDetail(d); })
        .catch((e) => { if (live) { setDetail(null); toast.show(e.message, 'error'); } })
        .finally(() => { if (live) setDetailLoading(false); });
      return () => { live = false; };
    }, [selId]);

    async function act(id, verb, e) {
      if (e) e.stopPropagation();
      try {
        await apiPost(`/api/jobs/${id}/${verb}`);
        reload();
        if (selId === id) apiGet(`/api/jobs/${id}`).then(setDetail).catch(() => {});
        toast.show(`Job ${id} ${verb}${verb.endsWith('e') ? 'd' : 'ed'}`, 'success');
      } catch (err) { toast.show(err.message, 'error'); }
    }

    function jobTopic(r) { return (r.metadata && r.metadata.topic) || r.topic || '—'; }
    function jobProgress(r) {
      const p = (r.metadata && typeof r.metadata.progress === 'number') ? r.metadata.progress : 0;
      return Math.max(0, Math.min(1, p));
    }

    const columns = [
      { key: 'id', label: 'ID', render: (r) => <span className="num">{r.id}</span> },
      { key: 'mode', label: 'Mode', render: (r) => r.mode || '—' },
      { key: 'topic', label: 'Topic', render: jobTopic },
      { key: 'status', label: 'Status', render: (r) => <StatusPill status={r.status} /> },
      { key: 'progress', label: 'Progress', render: (r) => {
        const p = jobProgress(r);
        return <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Bar value={p} max={1} />
          <span className="num" style={{ fontSize: 11, color: 'var(--muted)' }}>{Math.round(p * 100)}%</span>
        </div>;
      } },
      { key: 'act', label: 'Actions', render: (r) => (
        <div style={{ display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
          {r.status === 'running'
            ? <Btn size="sm" kind="ghost" aria-label={`Pause job ${r.id}`} onClick={(e) => act(r.id, 'pause', e)}>Pause</Btn>
            : (r.status === 'paused'
              ? <Btn size="sm" kind="ghost" aria-label={`Resume job ${r.id}`} onClick={(e) => act(r.id, 'resume', e)}>Resume</Btn>
              : null)}
          {r.status !== 'cancelled' && r.status !== 'done' && r.status !== 'completed' &&
            <Btn size="sm" kind="danger" aria-label={`Cancel job ${r.id}`} onClick={(e) => act(r.id, 'cancel', e)}>Cancel</Btn>}
        </div>
      ) },
    ];

    const rows = jobs.map((j) => ({ ...j, _key: j.id }));

    return (
      <div>
        <PageHeader title="Jobs" subtitle={loading && !data ? 'Loading…' : `${jobs.length} total`}
          actions={<Btn onClick={() => setShowNew(true)}>+ New job</Btn>} />

        {loading && !data && (
          <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
            {[0, 1, 2, 3].map((i) => (
              <div key={i} style={{ display: 'flex', gap: 16, alignItems: 'center',
                padding: '13px 16px', borderTop: i ? '1px solid var(--rule-soft)' : 'none' }}>
                <Skeleton h={14} w={28} /><Skeleton h={14} w={80} />
                <Skeleton h={14} w={160} /><Skeleton h={14} w={70} />
                <Skeleton h={8} w={120} />
              </div>
            ))}
          </div>
        )}

        {error && !data && <ErrorBox message={error} />}

        {!(loading && !data) && (
          <DataTable columns={columns} rows={rows} activeRow={selId}
            onRow={(r) => setSelId(r.id)}
            empty={<EmptyState title="No jobs yet" icon="⚓"
              hint="Start a research run from a topic, or create one here."
              action={<Btn onClick={() => setShowNew(true)}>+ New job</Btn>} />} />
        )}

        {selId != null && (
          <SidePane title={detail ? (jobTopic(detail) !== '—' ? jobTopic(detail) : `Job ${selId}`) : `Job ${selId}`}
            subtitle={detail ? `${detail.mode || 'job'} · ${detail.status || ''}` : 'Loading…'}
            onClose={() => setSelId(null)}
            footer={detail && (detail.status === 'running' || detail.status === 'paused') ? (
              <div style={{ display: 'flex', gap: 8 }}>
                {detail.status === 'running'
                  ? <Btn kind="ghost" onClick={() => act(detail.id, 'pause')}>Pause</Btn>
                  : <Btn kind="ghost" onClick={() => act(detail.id, 'resume')}>Resume</Btn>}
                <Btn kind="danger" onClick={() => act(detail.id, 'cancel')}>Cancel</Btn>
              </div>
            ) : null}>
            {detailLoading && !detail && <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Skeleton h={14} /><Skeleton h={14} w="80%" /><Skeleton h={14} w="60%" /></div>}
            {detail && <JobDetail job={detail} />}
            {!detailLoading && !detail && <div style={{ color: 'var(--muted)', fontSize: 13 }}>
              Couldn't load this job.</div>}
          </SidePane>
        )}

        {showNew && <NewJobModal toast={toast} onClose={() => setShowNew(false)}
          onCreated={() => { setShowNew(false); reload(); toast.show('Job queued', 'success'); }} />}
      </div>
    );
  }

  function JobDetail({ job }) {
    const meta = job.metadata || {};
    const calls = Array.isArray(job.model_calls) ? job.model_calls : [];
    const p = (typeof meta.progress === 'number') ? Math.max(0, Math.min(1, meta.progress)) : null;
    return (
      <div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 14 }}>
          <StatusPill status={job.status} />
          {p != null && <div style={{ display: 'flex', gap: 8, alignItems: 'center', flex: 1 }}>
            <Bar value={p} max={1} />
            <span className="num" style={{ fontSize: 11, color: 'var(--muted)' }}>{Math.round(p * 100)}%</span>
          </div>}
        </div>

        <div className="small-caps" style={{ marginBottom: 4 }}>Metadata</div>
        <Row k="ID" v={job.id} />
        <Row k="Mode" v={job.mode} />
        <Row k="Depth" v={meta.depth || job.depth} />
        <Row k="Topic" v={meta.topic || job.topic} />
        <Row k="Status" v={job.status} />
        {job.created_at && <Row k="Created" v={job.created_at} />}
        {job.updated_at && <Row k="Updated" v={job.updated_at} />}
        {meta.step && <Row k="Step" v={meta.step} />}
        {job.error && <Row k="Error" v={job.error} />}

        <div className="small-caps" style={{ margin: '18px 0 6px' }}>
          Model calls ({calls.length})</div>
        {calls.length === 0 && <div style={{ fontSize: 12.5, color: 'var(--muted)' }}>
          No model calls recorded yet.</div>}
        {calls.map((c, i) => (
          <div key={c.id || i} style={{ padding: '8px 0', borderBottom: '1px solid var(--rule-soft)',
            fontSize: 12.5 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
              <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{c.model || c.name || `call ${i + 1}`}</span>
              {c.tokens != null && <span className="num" style={{ color: 'var(--muted)' }}>
                {c.tokens} tok</span>}
            </div>
            {(c.purpose || c.role) && <div style={{ color: 'var(--ink-2)', marginTop: 2 }}>
              {c.purpose || c.role}</div>}
            {c.cost_usd != null && <div className="num" style={{ color: 'var(--muted)', marginTop: 2 }}>
              ${Number(c.cost_usd).toFixed(4)}</div>}
          </div>
        ))}
      </div>
    );
  }

  function NewJobModal({ onClose, onCreated, toast }) {
    const [mode, setMode] = useState('Deep-Dive');
    const [topic, setTopic] = useState('');
    const [depth, setDepth] = useState('Standard');
    const [busy, setBusy] = useState(false);
    const inputRef = useRef(null);
    useEffect(() => { if (inputRef.current) inputRef.current.focus(); }, []);

    async function submit(e) {
      if (e) e.preventDefault();
      if (!topic.trim()) { toast.show('Give the job a topic first.', 'info'); return; }
      setBusy(true);
      try { await apiPost('/api/jobs', { mode, topic: topic.trim(), depth }); onCreated(); }
      catch (err) { toast.show(err.message, 'error'); setBusy(false); }
    }

    return (
      <Modal title="New job" onClose={onClose}>
        <form onSubmit={submit}>
          <Field label="Topic" htmlFor="nj-topic">
            <input id="nj-topic" ref={inputRef} value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="What should Lighthouse research?" style={inputStyle} />
          </Field>
          <Field label="Mode" htmlFor="nj-mode">
            <select id="nj-mode" value={mode} onChange={(e) => setMode(e.target.value)} style={inputStyle}>
              {JOB_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </Field>
          <Field label="Depth" htmlFor="nj-depth">
            <select id="nj-depth" value={depth} onChange={(e) => setDepth(e.target.value)} style={inputStyle}>
              {JOB_DEPTHS.map((dp) => <option key={dp} value={dp}>{dp}</option>)}
            </select>
          </Field>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
            <Btn kind="ghost" type="button" onClick={onClose}>Cancel</Btn>
            <Btn type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create'}</Btn>
          </div>
        </form>
      </Modal>
    );
  }

  // ════════════════════════════ DRAFTS ════════════════════════════
  const DRAFT_GROUPS = ['staged', 'published', 'rejected'];
  const GROUP_LABEL = { staged: 'Awaiting approval', published: 'Published', rejected: 'Rejected' };

  function DraftsPage({ toast }) {
    const { data, loading, error, reload } = useApi('/api/drafts', { pollMs: 10000 });
    const [selId, setSelId] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [rejecting, setRejecting] = useState(false);
    const [busy, setBusy] = useState(false);
    useEvents((name) => { if (name && name.indexOf('draft.') === 0) reload(); });
    useEffect(() => { if (error) toast.show(`Drafts failed to load: ${error}`, 'error'); }, [error]);

    const drafts = (data && Array.isArray(data.drafts)) ? data.drafts : [];
    const staged = drafts.filter((d) => d && d.status === 'staged');

    useEffect(() => {
      if (selId == null) { setDetail(null); return; }
      let live = true;
      setDetailLoading(true);
      apiGet(`/api/drafts/${selId}`)
        .then((d) => { if (live) setDetail(d); })
        .catch((e) => { if (live) { setDetail(null); toast.show(e.message, 'error'); } })
        .finally(() => { if (live) setDetailLoading(false); });
      return () => { live = false; };
    }, [selId]);

    async function approve(id) {
      setBusy(true);
      try {
        await apiPost(`/api/drafts/${id}/approve`);
        toast.show('Approved & published', 'success');
        reload(); setSelId(null);
      } catch (e) { toast.show(e.message, 'error'); }
      finally { setBusy(false); }
    }

    async function reject(id, reason) {
      setBusy(true);
      try {
        await apiPost(`/api/drafts/${id}/reject`, { reason });
        toast.show('Draft rejected', 'info');
        reload(); setRejecting(false); setSelId(null);
      } catch (e) { toast.show(e.message, 'error'); }
      finally { setBusy(false); }
    }

    const firstLoad = loading && !data;

    return (
      <div>
        <PageHeader title="Drafts"
          subtitle={firstLoad ? 'Loading…' : `${staged.length} awaiting your approval`} />

        {firstLoad && <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 16 }}>
          <div style={{ ...card, padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <Skeleton h={14} w={120} /><Skeleton h={14} /><Skeleton h={14} w="80%" />
          </div>
          <div style={{ ...card, padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Skeleton h={12} w={90} /><Skeleton h={24} w="70%" /><Skeleton h={14} /><Skeleton h={14} w="85%" />
          </div>
        </div>}

        {error && !data && <ErrorBox message={error} />}

        {!firstLoad && drafts.length === 0 && (
          <EmptyState title="No drafts yet" icon="✎"
            hint="When a research job finishes, its draft lands here for your approval."
            action={<Btn onClick={() => { window.location.hash = 'jobs'; }}>Go to Jobs</Btn>} />
        )}

        {!firstLoad && drafts.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 16 }}>
            <div style={{ ...card, padding: 8, alignSelf: 'start' }}>
              {DRAFT_GROUPS.map((group) => {
                const items = drafts.filter((d) => d && d.status === group);
                if (!items.length) return null;
                return (
                  <div key={group} style={{ marginBottom: 4 }}>
                    <div className="small-caps" style={{ padding: '8px 8px 4px' }}>
                      {GROUP_LABEL[group]} ({items.length})</div>
                    {items.map((d) => (
                      <div key={d.id} role="button" tabIndex={0} className="lh-draft-item"
                        aria-pressed={selId === d.id}
                        onClick={() => setSelId(d.id)}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelId(d.id); } }}
                        style={{ padding: '8px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 13,
                          background: selId === d.id ? 'var(--rule-soft)' : 'transparent',
                          fontFamily: 'var(--serif)', color: 'var(--ink)', marginBottom: 1 }}>
                        {d.title || `Draft ${d.id}`}
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>

            <div style={{ ...card, padding: '20px 24px', minHeight: 320 }}>
              {selId == null && <EmptyDraftReader />}
              {selId != null && detailLoading && !detail && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <Skeleton h={12} w={90} /><Skeleton h={24} w="70%" />
                  <Skeleton h={14} /><Skeleton h={14} w="90%" /><Skeleton h={14} w="80%" />
                </div>
              )}
              {selId != null && !detailLoading && !detail && (
                <div style={{ color: 'var(--muted)', fontSize: 13 }}>Couldn't load this draft.</div>
              )}
              {detail && <DraftReader draft={detail} busy={busy}
                onApprove={() => approve(detail.id)}
                onReject={() => setRejecting(true)} />}
            </div>
          </div>
        )}

        {rejecting && detail && <RejectModal toast={toast} busy={busy}
          onClose={() => setRejecting(false)}
          onReject={(reason) => reject(detail.id, reason)} />}
      </div>
    );
  }

  function EmptyDraftReader() {
    return (
      <div style={{ textAlign: 'center', color: 'var(--muted)', padding: '60px 16px' }}>
        <div style={{ fontSize: 28, opacity: 0.5, marginBottom: 8 }}>✎</div>
        <div style={{ fontFamily: 'var(--serif)', fontSize: 15, color: 'var(--ink-2)' }}>
          Select a draft to read it</div>
        <div style={{ fontSize: 12.5, marginTop: 4 }}>
          Approve to publish, or reject with a one-line reason.</div>
      </div>
    );
  }

  function DraftReader({ draft, busy, onApprove, onReject }) {
    const sources = draft.source_count != null ? draft.source_count
      : (Array.isArray(draft.sources) ? draft.sources.length : null);
    return (
      <div>
        {draft.topic && <div className="small-caps" style={{ color: 'var(--coral-2)' }}>{draft.topic}</div>}
        <h2 style={{ fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 22,
          margin: '6px 0 12px', color: 'var(--ink)' }}>{draft.title || `Draft ${draft.id}`}</h2>

        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
          <ConfidencePill phrase={draft.wep_phrase} band={draft.wep_band} />
          {sources != null && <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>
            <span className="num">{sources}</span> source{sources === 1 ? '' : 's'}</span>}
          <StatusPill status={draft.status} />
        </div>

        {draft.body_html
          ? <div style={{ fontFamily: 'var(--serif)', fontSize: 15, lineHeight: 1.6, color: 'var(--ink-2)' }}
              dangerouslySetInnerHTML={{ __html: draft.body_html }} />
          : <div style={{ fontSize: 13, color: 'var(--muted)' }}>This draft has no body content.</div>}

        {draft.status === 'staged' && (
          <div style={{ display: 'flex', gap: 10, marginTop: 20,
            borderTop: '1px solid var(--rule)', paddingTop: 16 }}>
            <Btn kind="success" disabled={busy} onClick={onApprove}>
              {busy ? 'Working…' : 'Approve'}</Btn>
            <Btn kind="danger" disabled={busy} onClick={onReject}>Reject</Btn>
          </div>
        )}
        {draft.status === 'rejected' && (draft.reject_reason || draft.reason) && (
          <div style={{ marginTop: 16, fontSize: 12.5, color: 'var(--coral-2)',
            borderTop: '1px solid var(--rule)', paddingTop: 14 }}>
            Rejected: {draft.reject_reason || draft.reason}</div>
        )}
      </div>
    );
  }

  function RejectModal({ onClose, onReject, busy, toast }) {
    const [reason, setReason] = useState('');
    const inputRef = useRef(null);
    useEffect(() => { if (inputRef.current) inputRef.current.focus(); }, []);
    function submit(e) {
      if (e) e.preventDefault();
      if (!reason.trim()) { toast.show('A one-line reason helps the next draft.', 'info'); return; }
      onReject(reason.trim());
    }
    return (
      <Modal title="Reject draft" onClose={onClose}>
        <form onSubmit={submit}>
          <Field label="Reason (one line)" htmlFor="rj-reason">
            <input id="rj-reason" ref={inputRef} value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. sources too thin" style={inputStyle} />
          </Field>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
            <Btn kind="ghost" type="button" onClick={onClose}>Cancel</Btn>
            <Btn kind="danger" type="submit" disabled={busy}>{busy ? 'Rejecting…' : 'Reject'}</Btn>
          </div>
        </form>
      </Modal>
    );
  }

  Object.assign(window, { HomePage, JobsPage, DraftsPage });
})();
