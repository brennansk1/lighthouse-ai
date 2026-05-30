// app-pages-today.jsx — professional Home · Jobs · Drafts for the Lighthouse
// dashboard. Static React (UMD + babel-standalone), one shared browser scope,
// no imports. Defines HomePage / JobsPage / DraftsPage and hangs them on
// window at the end. Uses the global primitives from app-lib.jsx.

(function () {
  const { useState, useEffect, useRef, useCallback } = React;

  // ── private style constants ──────────────────────────────────────────────
  const inputStyle = {
    fontFamily: 'var(--sans)', fontSize: 13, padding: '8px 10px',
    border: '1px solid var(--rule)', borderRadius: 'var(--radius-sm)',
    color: 'var(--ink)', background: 'var(--card)', width: '100%',
    outline: 'none', boxSizing: 'border-box',
  };

  const PAD = 28;   // page-level padding (px)
  const GAP = 18;   // section gap (px)

  // ── inject keyframes + utility classes once ──────────────────────────────
  (function injectStyles() {
    if (document.getElementById('lh-today-styles')) return;
    const el = document.createElement('style');
    el.id = 'lh-today-styles';
    el.textContent = [
      '@keyframes lhshimmer{0%{background-position:100% 0}100%{background-position:-100% 0}}',
      '.lh-hover{transition:box-shadow .15s,transform .15s}',
      '.lh-hover:hover{box-shadow:var(--shadow);transform:translateY(-1px)}',
      '.lh-row-btn{cursor:pointer;transition:background .1s}',
      '.lh-row-btn:hover{background:var(--paper)!important}',
      '.lh-row-btn:focus-visible{outline:2px solid var(--primary);outline-offset:-2px}',
      '.lh-tab{border:none;background:none;cursor:pointer;font-family:var(--sans);font-size:13px;',
        'font-weight:600;padding:7px 14px;border-radius:var(--radius-sm);color:var(--muted);transition:color .15s,background .15s}',
      '.lh-tab:hover{color:var(--ink);background:var(--rule-soft)}',
      '.lh-tab.active{color:var(--primary);background:var(--sky-soft)}',
      '.lh-draft-item{cursor:pointer;transition:background .1s}',
      '.lh-draft-item:hover{background:var(--paper)!important}',
      '.lh-draft-item:focus-visible{outline:2px solid var(--primary);outline-offset:-2px}',
      '.lh-job-card{transition:box-shadow .15s,transform .15s;cursor:pointer}',
      '.lh-job-card:hover{box-shadow:var(--shadow);transform:translateY(-1px)}',
      '.lh-body-html h1,.lh-body-html h2,.lh-body-html h3{font-family:var(--serif);color:var(--ink);margin-top:1.4em}',
      '.lh-body-html p{line-height:1.65;margin:0.75em 0}',
      '.lh-body-html a{color:var(--primary)}',
      '.lh-body-html blockquote{border-left:3px solid var(--sky);margin:1em 0;padding:0.5em 1em;color:var(--ink-2)}',
      '.lh-body-html code{font-family:var(--mono);font-size:0.9em;background:var(--rule-soft);padding:2px 5px;border-radius:4px}',
      '.lh-alert-strip{display:flex;flex-direction:column;gap:8px;margin-bottom:18px}',
      '.lh-alert-row{display:flex;align-items:flex-start;gap:10px;padding:10px 14px;border-radius:var(--radius-sm)}',
      '.lh-mode-radio{display:flex;flex-direction:column;gap:8px}',
      '.lh-mode-card{border:2px solid var(--rule);border-radius:var(--radius-sm);padding:10px 14px;cursor:pointer;transition:border-color .12s,background .12s}',
      '.lh-mode-card.selected{border-color:var(--primary);background:var(--sky-soft)}',
      '.lh-mode-card:hover:not(.selected){border-color:var(--sky);background:var(--paper)}',
      '.lh-progress{appearance:none;-webkit-appearance:none;height:6px;border-radius:99px;border:none;width:100%;overflow:hidden}',
      '.lh-progress::-webkit-progress-bar{background:var(--rule-soft);border-radius:99px}',
      '.lh-progress::-webkit-progress-value{background:var(--primary);border-radius:99px;transition:width .4s ease}',
      '.lh-progress::-moz-progress-bar{background:var(--primary);border-radius:99px}',
      '.lh-split{display:flex;gap:24px;align-items:flex-start}',
      '.lh-split-list{flex:0 0 40%;min-width:0;overflow:hidden}',
      '.lh-split-reader{flex:1 1 0%;min-width:0;position:sticky;top:24px}',
      '.lh-reader-footer{position:sticky;bottom:0;background:var(--card);border-top:1px solid var(--rule-soft);padding:12px 18px;display:flex;gap:8px;justify-content:flex-end}',
      '.lh-stop-btn{border:none;background:none;cursor:pointer;font-size:11px;font-weight:700;color:var(--coral-2);padding:3px 8px;border-radius:var(--radius-sm);transition:background .1s}',
      '.lh-stop-btn:hover{background:#fff3f3}',
      '.lh-jobs-split{display:flex;gap:24px;align-items:flex-start}',
      '.lh-jobs-table{flex:1 1 0%;min-width:0}',
      '.lh-jobs-pane{flex:0 0 320px;position:sticky;top:24px}',
    ].join('');
    document.head.appendChild(el);
  })();

  // ── tiny private helpers ─────────────────────────────────────────────────

  function LocalField({ label, children, htmlFor }) {
    return (
      <div style={{ marginBottom: 14 }}>
        {label && (
          <label htmlFor={htmlFor} style={{
            display: 'block', fontSize: 11, fontWeight: 700,
            color: 'var(--muted)', marginBottom: 5,
            textTransform: 'uppercase', letterSpacing: '0.07em',
          }}>{label}</label>
        )}
        {children}
      </div>
    );
  }

  function LocalRow({ k, v }) {
    return (
      <div style={{
        display: 'flex', justifyContent: 'space-between', gap: 16,
        padding: '6px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 13,
      }}>
        <span style={{ color: 'var(--muted)', flexShrink: 0 }}>{k}</span>
        <span className="num" style={{
          color: 'var(--ink)', fontWeight: 500,
          textAlign: 'right', wordBreak: 'break-all',
        }}>{v == null ? '—' : String(v)}</span>
      </div>
    );
  }

  // Relative time helper
  function relTime(isoStr) {
    if (!isoStr) return '—';
    const ms = Date.now() - new Date(isoStr).getTime();
    const s = Math.floor(ms / 1000);
    if (s < 60) return 'just now';
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  }

  // Budget progress bar that shifts green → amber → red
  function BudgetBar({ label, used, cap, unit, suffix }) {
    if (cap == null || cap === 0) return null;
    const pct = Math.min(1, (used || 0) / cap);
    const color = pct >= 0.85 ? 'var(--coral-2)' : pct >= 0.60 ? 'var(--sand)' : 'var(--green)';
    const pctRounded = Math.round(pct * 100);
    const formatNum = (n) => {
      if (n == null) return '?';
      if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
      if (n >= 1000) return `${(n / 1000).toFixed(0)}k`;
      return String(n);
    };
    return (
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between',
          fontSize: 11, color: 'var(--muted)', marginBottom: 4,
        }}>
          <span style={{ textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>{label}</span>
          <span className="num">
            {formatNum(used)}{suffix || (unit ? ` ${unit}` : '')} / {formatNum(cap)}{suffix || (unit ? ` ${unit}` : '')}
          </span>
        </div>
        <div style={{
          height: 7, borderRadius: 99, background: 'var(--rule-soft)', overflow: 'hidden',
        }}>
          <div style={{
            height: '100%', width: `${pctRounded}%`,
            background: color, borderRadius: 99, transition: 'width .4s ease',
          }} />
        </div>
      </div>
    );
  }

  // Mode badge — small colored pill. Keys are the stable internal mode ids;
  // MODE_LABELS maps them to the user-facing names shown in the UI.
  function ModeBadge({ mode }) {
    const MAP = {
      'Deep-Dive': { bg: '#e3f2fd', color: 'var(--ink-2)', border: 'var(--primary)' },
      'Monitor':   { bg: '#e8f5e9', color: '#2e7d32',      border: 'var(--green)' },
      'QUC':       { bg: '#fff8e1', color: '#795548',      border: 'var(--sand)' },
      'Debate':    { bg: '#fce4ec', color: '#880e4f',      border: '#f48fb1' },
      'Digest':    { bg: 'var(--rule-soft)', color: 'var(--muted)', border: 'var(--rule)' },
    };
    const s = MAP[mode] || MAP['Digest'];
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center',
        padding: '2px 8px', borderRadius: 99, fontSize: 11, fontWeight: 700,
        background: s.bg, color: s.color, letterSpacing: '0.04em',
        textTransform: 'uppercase', whiteSpace: 'nowrap',
      }}>{window.modeLabel ? window.modeLabel(mode) : (mode || 'Job')}</span>
    );
  }

  // Mode left border color
  function modeBorderColor(mode) {
    const MAP = {
      'Deep-Dive': 'var(--primary)',
      'Monitor':   'var(--green)',
      'QUC':       'var(--sand)',
      'Debate':    '#f48fb1',
      'Digest':    'var(--muted)',
    };
    return MAP[mode] || 'var(--rule)';
  }

  // Brier score color (lower = better)
  function brierColor(val) {
    if (val == null) return 'var(--ink)';
    const n = Number(val);
    if (n < 0.10) return 'var(--green-dark)';
    if (n < 0.20) return '#00897b'; // teal
    if (n < 0.25) return 'var(--sand)';
    return 'var(--coral-2)';
  }

  // Alert strip (collapsible, dismissible)
  function AlertStrip({ alerts }) {
    const [dismissed, setDismissed] = useState([]);
    const [collapsed, setCollapsed] = useState(false);

    if (!alerts || alerts.length === 0) return null;
    const visible = alerts.filter((_, i) => !dismissed.includes(i));
    if (visible.length === 0) return null;

    const kindStyle = (k) => {
      if (k === 'budget') return { bg: '#fff8e1', border: 'var(--sand)', text: '#795548' };
      if (k === 'error')  return { bg: '#fff3f3', border: 'var(--coral-2)', text: 'var(--coral-2)' };
      return { bg: 'var(--sky-soft)', border: 'var(--primary)', text: 'var(--ink-2)' };
    };

    return (
      <div className="lh-alert-strip" role="region" aria-label="Alerts">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => setCollapsed((c) => !c)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand alerts' : 'Collapse alerts'}
            style={{
              border: 'none', background: 'none', cursor: 'pointer',
              fontSize: 11, fontWeight: 700, color: 'var(--muted)',
              textTransform: 'uppercase', letterSpacing: '0.06em', padding: 0,
              display: 'flex', alignItems: 'center', gap: 4,
            }}
          >
            {collapsed ? '▶' : '▼'} {visible.length} alert{visible.length !== 1 ? 's' : ''}
          </button>
        </div>
        {!collapsed && visible.map((a, vi) => {
          const origIdx = alerts.indexOf(a);
          const c = kindStyle(a.kind);
          return (
            <div
              key={origIdx}
              role="alert"
              className="lh-alert-row"
              style={{ background: c.bg, borderLeft: `3px solid ${c.border}` }}
            >
              <span style={{
                fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
                textTransform: 'uppercase', color: c.border, flexShrink: 0, paddingTop: 1,
              }}>{a.kind || 'info'}</span>
              <span style={{ fontSize: 13, color: c.text, lineHeight: 1.45, flex: 1 }}>
                {a.topic && <strong style={{ marginRight: 4 }}>{a.topic}:</strong>}
                {a.text}
              </span>
              <button
                onClick={() => setDismissed((d) => [...d, origIdx])}
                aria-label="Dismiss alert"
                style={{
                  border: 'none', background: 'none', cursor: 'pointer',
                  fontSize: 16, color: 'var(--muted)', lineHeight: 1, padding: '0 2px', flexShrink: 0,
                }}
              >&times;</button>
            </div>
          );
        })}
      </div>
    );
  }

  // Tab bar component
  function TabBar({ tabs, active, onChange }) {
    return (
      <div style={{
        display: 'flex', gap: 4, background: 'var(--rule-soft)',
        padding: 4, borderRadius: 'var(--radius-sm)', alignSelf: 'flex-start',
      }} role="tablist">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={active === t.key}
            aria-label={`${t.label} tab${t.count != null ? `, ${t.count} items` : ''}`}
            className={`lh-tab${active === t.key ? ' active' : ''}`}
            onClick={() => onChange(t.key)}
          >
            {t.label}{t.count != null ? ` (${t.count})` : ''}
          </button>
        ))}
      </div>
    );
  }

  // ════════════════════════════ HOME PAGE ══════════════════════════════════
  function HomePage({ toast }) {
    const { data, loading, error, reload } = useApi('/api/dashboard', { pollMs: 30000 });
    useEvents(() => reload());
    useEffect(() => {
      if (error) toast.show(`Dashboard error: ${error}`, 'error');
    }, [error]);

    const d = data || {};
    const cal = d.calibration || {};
    const jobs = Array.isArray(d.jobs) ? d.jobs : [];
    const alerts = Array.isArray(d.alerts) ? d.alerts : [];
    const digest = Array.isArray(d.digest) ? d.digest.slice(0, 8) : [];
    const budget = d.budget || {};
    const cloud = budget.cloud || {};
    const tokens = budget.tokens || {};
    const running = jobs.filter((j) => j && (j.status === 'running' || j.status === 'paused'));
    const firstLoad = loading && !data;

    const dateLabel = d.date || new Date().toLocaleDateString(undefined, {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
    });

    const brierVal = cal.brier != null ? Number(cal.brier) : null;
    const brierStr = brierVal != null ? brierVal.toFixed(3) : null;

    // Stop job handler
    const [stoppingId, setStoppingId] = useState(null);
    async function stopJob(id, e) {
      e.preventDefault();
      e.stopPropagation();
      setStoppingId(id);
      try {
        await apiPost(`/api/jobs/${id}/cancel`);
        reload();
        toast.show('Job stopped', 'info');
      } catch (err) {
        toast.show(err.message, 'error');
      } finally {
        setStoppingId(null);
      }
    }

    return (
      <div style={{ padding: PAD, maxWidth: 1100 }}>
        <PageHeader
          title={d.greeting || 'Lighthouse'}
          subtitle={dateLabel}
        />

        {/* Alert strip */}
        <AlertStrip alerts={alerts} />

        {/* Two-column layout */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)',
          gap: GAP,
          alignItems: 'start',
        }}>

          {/* ── LEFT COLUMN ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: GAP }}>

            {/* Lead story card — skeleton */}
            {firstLoad && (
              <div className="card" style={{ padding: '22px 26px' }}>
                <Skeleton h={10} w={80} />
                <Skeleton h={28} w="75%" style={{ margin: '12px 0 8px' }} />
                <Skeleton h={14} />
                <Skeleton h={14} w="88%" style={{ marginTop: 4 }} />
                <Skeleton h={22} w={110} style={{ marginTop: 14, borderRadius: 99 }} />
              </div>
            )}

            {/* Lead story — data */}
            {!firstLoad && d.lead && (
              <div className="card lh-hover" style={{
                padding: '22px 26px',
                borderTop: '3px solid var(--primary)',
              }}>
                <div className="small-caps" style={{
                  color: 'var(--primary)', marginBottom: 10, fontSize: 10,
                }}>Lead finding</div>
                <h2 style={{
                  fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 22,
                  margin: '0 0 10px', color: 'var(--ink)', lineHeight: 1.3,
                }}>{d.lead.title}</h2>
                {d.lead.dek && (
                  <p style={{
                    fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 14,
                    lineHeight: 1.6, color: 'var(--ink-2)', margin: '0 0 14px',
                  }}>{d.lead.dek}</p>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
                  {d.lead.wep && (
                    <ConfidencePill phrase={d.lead.wep.phrase || d.lead.wep} band={d.lead.wep.band} />
                  )}
                  {d.lead.sources != null && (
                    <span style={{
                      fontSize: 12, color: 'var(--muted)',
                      background: 'var(--rule-soft)', padding: '2px 8px',
                      borderRadius: 99,
                    }}>
                      <span className="num">{d.lead.sources}</span> source{d.lead.sources === 1 ? '' : 's'}
                    </span>
                  )}
                  {d.lead.duration && (
                    <span style={{
                      fontSize: 12, color: 'var(--muted)',
                      background: 'var(--rule-soft)', padding: '2px 8px',
                      borderRadius: 99,
                    }}>{d.lead.duration}</span>
                  )}
                  {d.lead.topic && (
                    <span style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                      {d.lead.topic}
                    </span>
                  )}
                </div>
                <a href="#drafts" style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '7px 16px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--primary)', color: '#fff',
                  textDecoration: 'none', fontSize: 13, fontWeight: 600,
                }} aria-label="Open the lead draft">Open draft →</a>
              </div>
            )}

            {/* Lead story — empty */}
            {!firstLoad && !d.lead && (
              <div className="card" style={{
                padding: '32px 26px', textAlign: 'center',
                borderTop: '3px solid var(--rule)',
              }}>
                <div style={{ fontSize: 36, marginBottom: 14, opacity: 0.35 }}>&#128270;</div>
                <div style={{
                  fontFamily: 'var(--serif)', fontSize: 18, fontWeight: 700,
                  color: 'var(--ink)', marginBottom: 10,
                }}>Your research will appear here</div>
                <p style={{
                  fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.6,
                  maxWidth: 300, margin: '0 auto 20px',
                }}>
                  Your research will appear here when a draft is ready for review.
                </p>
                <a href="#jobs" style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '8px 20px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--primary)', color: '#fff',
                  textDecoration: 'none', fontSize: 13, fontWeight: 600,
                }} aria-label="Navigate to jobs to start research">Start research →</a>
              </div>
            )}

            {/* Calibration panel */}
            <div className="card" style={{ padding: '20px 24px' }}>
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16,
              }}>
                <div className="small-caps" style={{ color: 'var(--muted)' }}>Calibration</div>
                <span style={{
                  fontSize: 11, color: 'var(--muted)', padding: '2px 8px',
                  background: 'var(--rule-soft)', borderRadius: 99,
                }}>0.0 = perfect &middot; 0.25 = random</span>
              </div>

              {firstLoad ? (
                <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end', marginBottom: 16 }}>
                  <Skeleton h={40} w={80} />
                  <Skeleton h={22} w={40} />
                  <Skeleton h={22} w={40} />
                </div>
              ) : (
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 28, marginBottom: 16, flexWrap: 'wrap' }}>
                  <div>
                    <div style={{
                      fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                      letterSpacing: '0.06em', marginBottom: 2,
                    }}>Brier score</div>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                      <span className="num" style={{
                        fontSize: 40, fontWeight: 700, lineHeight: 1,
                        color: brierColor(brierVal),
                      }}>{brierStr != null ? brierStr : '—'}</span>
                      <span style={{ fontSize: 11, color: 'var(--muted)' }}>lower is better</span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 20 }}>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>Resolved</div>
                      <span className="num" style={{ fontSize: 22, fontWeight: 600, color: 'var(--ink)' }}>
                        {cal.resolved ?? '—'}
                      </span>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>Pending</div>
                      <span className="num" style={{ fontSize: 22, fontWeight: 600, color: 'var(--ink)' }}>
                        {cal.pending ?? '—'}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Sparkline — 10px height, 160px wide as spec */}
              {Array.isArray(cal.trend) && cal.trend.length > 1 ? (
                (function () {
                  const vals = cal.trend.map(Number);
                  const mn = Math.min(...vals);
                  const mx = Math.max(...vals) || 0.25;
                  const W = 160, H = 10;
                  const pts = vals.map((v, i) => {
                    const x = (i / (vals.length - 1)) * W;
                    const y = H - ((v - mn) / ((mx - mn) || 1)) * H;
                    return `${x.toFixed(1)},${y.toFixed(1)}`;
                  }).join(' ');
                  return (
                    <div style={{ marginTop: 4 }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                        Brier trend ({vals.length} periods)
                      </div>
                      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ overflow: 'visible', display: 'block' }}>
                        <polyline points={pts} fill="none" stroke="var(--sky)" strokeWidth="1.5"
                          strokeLinejoin="round" strokeLinecap="round" />
                      </svg>
                    </div>
                  );
                })()
              ) : !firstLoad ? (
                <div style={{ fontSize: 11, color: 'var(--muted)', fontStyle: 'italic', marginTop: 4 }}>
                  Tracking begins after your first resolved position.
                </div>
              ) : null}

              {/* Domains */}
              {!firstLoad && Array.isArray(cal.domains) && cal.domains.length > 0 && (
                <div style={{ marginTop: 14 }}>
                  <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Top domains</div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {cal.domains.map((dom, i) => (
                      <span key={i} style={{
                        fontSize: 11, background: 'var(--rule-soft)', color: 'var(--muted)',
                        padding: '2px 8px', borderRadius: 99,
                      }}>{dom}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Budget bars */}
            {!firstLoad && (cloud.cap || tokens.cap) && (
              <div className="card" style={{ padding: '16px 22px' }}>
                <div className="small-caps" style={{ color: 'var(--muted)', marginBottom: 12 }}>Budget</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {cloud.cap ? (
                    <BudgetBar
                      label="Cloud budget"
                      used={cloud.used}
                      cap={cloud.cap}
                      suffix={cloud.period ? ` / ${cloud.period}` : ''}
                    />
                  ) : null}
                  {tokens.cap ? (
                    <BudgetBar
                      label="Token budget"
                      used={tokens.used}
                      cap={tokens.cap}
                      unit={tokens.unit || ''}
                      suffix={tokens.unit ? ` ${tokens.unit} / ${tokens.period || 'mo'}` : ''}
                    />
                  ) : null}
                </div>
                {budget.tier && (
                  <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
                    Tier: <span className="num" style={{ color: 'var(--ink)' }}>{budget.tier}</span>
                  </div>
                )}
              </div>
            )}

          </div>

          {/* ── RIGHT COLUMN ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: GAP }}>

            {/* Active jobs strip */}
            <div className="card" style={{ padding: '18px 22px' }}>
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14,
              }}>
                <div className="small-caps" style={{ color: 'var(--muted)' }}>
                  Active jobs{running.length > 0 ? ` (${running.length})` : ''}
                </div>
                <a href="#jobs" style={{
                  fontSize: 12, color: 'var(--primary)', textDecoration: 'none', fontWeight: 600,
                }} aria-label="View all jobs">View all</a>
              </div>

              {firstLoad && (
                <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 4 }}>
                  {[0, 1, 2].map((i) => (
                    <div key={i} style={{
                      flexShrink: 0, width: 200, background: 'var(--paper)',
                      borderRadius: 'var(--radius)', padding: '14px 16px',
                    }}>
                      <Skeleton h={13} w="70%" />
                      <Skeleton h={10} w="55%" style={{ marginTop: 8 }} />
                      <Skeleton h={6} style={{ marginTop: 12, borderRadius: 99 }} />
                    </div>
                  ))}
                </div>
              )}

              {!firstLoad && running.length === 0 && (
                <div style={{ textAlign: 'center', padding: '24px 0' }}>
                  <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 14 }}>
                    No jobs running right now
                  </div>
                  <a href="#jobs" style={{
                    display: 'inline-flex', alignItems: 'center', padding: '7px 18px',
                    borderRadius: 'var(--radius-sm)', background: 'var(--primary)',
                    color: '#fff', textDecoration: 'none', fontSize: 13, fontWeight: 600,
                  }} aria-label="Start new research">New research</a>
                </div>
              )}

              {!firstLoad && running.length > 0 && (
                <div style={{ display: 'flex', gap: 14, overflowX: 'auto', paddingBottom: 8 }}>
                  {running.map((j) => {
                    const topic = (j.metadata && j.metadata.topic) || j.topic || `Job ${j.id}`;
                    const progress = typeof j.progress === 'number' ? Math.max(0, Math.min(1, j.progress)) : 0;
                    const pct = Math.round(progress * 100);
                    const eta = j.eta || (j.metadata && j.metadata.eta);
                    const borderColor = modeBorderColor(j.mode);
                    const stopping = stoppingId === j.id;
                    return (
                      <a
                        key={j.id}
                        href="#jobs"
                        className="lh-job-card"
                        aria-label={`${topic} — ${j.mode} job, ${pct}% complete`}
                        style={{
                          flexShrink: 0, minWidth: 200, textDecoration: 'none',
                          background: 'var(--paper)', borderRadius: 'var(--radius)',
                          padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8,
                          border: '1px solid var(--rule-soft)',
                          borderLeft: `4px solid ${borderColor}`,
                        }}
                      >
                        <div className="lh-truncate-2" style={{
                          fontSize: 13, fontWeight: 600, color: 'var(--ink)', lineHeight: 1.4,
                        }}>{topic}</div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <ModeBadge mode={j.mode} />
                          <button
                            onClick={(e) => stopJob(j.id, e)}
                            disabled={stopping}
                            aria-label={`Stop job: ${topic}`}
                            className="lh-stop-btn"
                          >
                            {stopping ? '…' : '⏹ Stop'}
                          </button>
                        </div>
                        <div>
                          <progress
                            className="lh-progress"
                            value={pct}
                            max={100}
                            aria-label={`${pct}% complete`}
                            style={{ width: '100%' }}
                          />
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--muted)', marginTop: 3 }}>
                            <span className="num">{pct}%</span>
                            {eta && <span>{eta}</span>}
                          </div>
                        </div>
                      </a>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Digest stream */}
            <div className="card" style={{ padding: '18px 22px' }}>
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14,
              }}>
                <div className="small-caps" style={{ color: 'var(--muted)' }}>Digest stream</div>
              </div>

              {firstLoad && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} style={{ borderBottom: '1px solid var(--rule-soft)', paddingBottom: 12 }}>
                      <Skeleton h={10} w={100} />
                      <Skeleton h={14} style={{ marginTop: 6 }} />
                      <Skeleton h={14} w="80%" style={{ marginTop: 3 }} />
                    </div>
                  ))}
                </div>
              )}

              {!firstLoad && digest.length === 0 && (
                <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--muted)', fontSize: 13 }}>
                  No digest items yet.
                </div>
              )}

              {!firstLoad && digest.map((item, i) => (
                <div key={i} style={{
                  padding: '11px 0',
                  borderBottom: i < digest.length - 1 ? '1px solid var(--rule-soft)' : 'none',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 4 }}>
                    <strong style={{
                      fontSize: 12.5, color: 'var(--ink)',
                    }}>{item.topic || 'Topic'}</strong>
                    {item.wep && (
                      <ConfidencePill phrase={item.wep.phrase || item.wep} band={item.wep.band} />
                    )}
                  </div>
                  {item.delta && (
                    <div style={{
                      fontFamily: 'var(--serif)', fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.5,
                    }}>{item.delta}</div>
                  )}
                  {item.srcs != null && (
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 3 }}>
                      <span className="num">{item.srcs}</span> source{item.srcs === 1 ? '' : 's'}
                    </div>
                  )}
                </div>
              ))}

              {!firstLoad && (
                <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--rule-soft)' }}>
                  <a href="#topics" style={{ fontSize: 12, color: 'var(--primary)', textDecoration: 'none', fontWeight: 600 }}>
                    View all in Topics →
                  </a>
                </div>
              )}
            </div>

          </div>
        </div>
      </div>
    );
  }

  // ════════════════════════════ JOBS PAGE ══════════════════════════════════
  const JOB_MODES = [
    { key: 'Deep-Dive', label: 'Deep Research', desc: 'Full research report with citations and analysis.' },
    { key: 'QUC',       label: 'Quick Answer',  desc: 'Quick answer with key sources, fast turnaround.' },
    { key: 'Monitor',   label: 'Event Monitor', desc: 'Watch a live, time-bounded event over time.' },
    { key: 'Debate',    label: 'Debate',        desc: 'Steelman multiple perspectives on a question.' },
    { key: 'Digest',    label: 'Digest',        desc: 'Curated summary of recent items on a theme.' },
  ];
  const JOB_DEPTHS = ['Quick', 'Standard', 'Thorough'];
  const JOBS_TABS = [
    { key: 'all',     label: 'All' },
    { key: 'running', label: 'Running' },
    { key: 'review',  label: 'Review' },
    { key: 'done',    label: 'Done' },
  ];

  function jobTopic(r) { return (r.metadata && r.metadata.topic) || r.topic || `Job ${r.id}`; }
  function jobProgress(r) {
    const p = typeof r.progress === 'number' ? r.progress
      : (r.metadata && typeof r.metadata.progress === 'number') ? r.metadata.progress : 0;
    return Math.max(0, Math.min(1, p));
  }

  const JOB_EMPTY = {
    all:     { title: 'No research jobs yet', hint: 'Start a new job to kick off your first research workflow.' },
    running: { title: 'No active jobs', hint: 'No jobs running right now — start one with New Research.' },
    review:  { title: 'No drafts awaiting review', hint: 'Completed jobs will stage drafts here for your approval.' },
    done:    { title: 'No completed jobs yet', hint: 'Finished and cancelled jobs will appear here.' },
  };

  function JobsPage({ toast }) {
    const { data, loading, error, reload } = useApi('/api/jobs', { pollMs: 10000 });
    const [tab, setTab] = useState('all');
    const [showNew, setShowNew] = useState(false);
    const [selId, setSelId] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [actionBusy, setActionBusy] = useState(null);
    const [watchId, setWatchId] = useState(null);

    // job.step is high-frequency; the trace viewer consumes it directly, so we
    // skip a full job-list reload on it and only refresh on lifecycle events.
    useEvents((name) => { if (name && name.indexOf('job.') === 0 && name !== 'job.step') reload(); });
    useEffect(() => { if (error) toast.show(`Jobs failed to load: ${error}`, 'error'); }, [error]);

    const allJobs = (data && Array.isArray(data.jobs)) ? data.jobs : [];

    const tabCounts = {
      all:     allJobs.length,
      running: allJobs.filter((j) => j.status === 'running' || j.status === 'paused').length,
      review:  allJobs.filter((j) => j.status === 'review' || j.status === 'staged').length,
      done:    allJobs.filter((j) => j.status === 'done' || j.status === 'completed' || j.status === 'cancelled').length,
    };

    const visibleJobs = allJobs.filter((j) => {
      if (tab === 'all') return true;
      if (tab === 'running') return j.status === 'running' || j.status === 'paused';
      if (tab === 'review') return j.status === 'review' || j.status === 'staged';
      if (tab === 'done') return j.status === 'done' || j.status === 'completed' || j.status === 'cancelled';
      return true;
    });

    // Load job detail when selection changes
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

    async function act(id, verb) {
      setActionBusy(verb);
      try {
        await apiPost(`/api/jobs/${id}/${verb}`);
        reload();
        apiGet(`/api/jobs/${id}`).then(setDetail).catch(() => {});
        toast.show(`Job ${verb}${verb.endsWith('e') ? 'd' : 'ed'}`, 'success');
      } catch (err) {
        toast.show(err.message, 'error');
      } finally {
        setActionBusy(null);
      }
    }

    const firstLoad = loading && !data;
    const tabs = JOBS_TABS.map((t) => ({ ...t, count: tabCounts[t.key] }));
    const emptyInfo = JOB_EMPTY[tab] || JOB_EMPTY.all;
    const hasPane = selId != null;

    return (
      <div style={{ padding: PAD, maxWidth: 1200 }}>
        <PageHeader
          title="Research jobs"
          subtitle={firstLoad ? 'Loading…' : `${allJobs.length} total`}
          actions={
            <Btn onClick={() => setShowNew(true)} aria-label="Start a new research job">
              + New research
            </Btn>
          }
        />

        <div style={{ marginBottom: GAP }}>
          <TabBar
            tabs={tabs}
            active={tab}
            onChange={(k) => { setTab(k); setSelId(null); }}
          />
        </div>

        {/* Split layout: table + pane */}
        <div className="lh-jobs-split">
          <div className="lh-jobs-table">

            {/* Loading skeleton */}
            {firstLoad && (
              <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                {[0, 1, 2, 3, 4].map((i) => (
                  <div key={i} style={{
                    display: 'flex', gap: 16, alignItems: 'center',
                    padding: '14px 18px',
                    borderTop: i ? '1px solid var(--rule-soft)' : 'none',
                  }}>
                    <Skeleton h={14} w={200} />
                    <Skeleton h={20} w={70} r={99} />
                    <Skeleton h={20} w={80} r={99} />
                    <Skeleton h={6} w={120} r={99} style={{ marginLeft: 'auto' }} />
                  </div>
                ))}
              </div>
            )}

            {error && !data && (
              <ErrorBox message={error} action={<Btn kind="ghost" onClick={reload}>Retry</Btn>} />
            )}

            {!firstLoad && visibleJobs.length === 0 && (
              <EmptyState
                icon="&#128270;"
                title={emptyInfo.title}
                hint={emptyInfo.hint}
                action={
                  tab === 'all'
                    ? <Btn onClick={() => setShowNew(true)} aria-label="Start first research job">Start your first research job</Btn>
                    : null
                }
              />
            )}

            {!firstLoad && visibleJobs.length > 0 && (
              <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                {/* Table header */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 110px 120px 130px 80px 90px',
                  gap: 10, padding: '10px 18px',
                  background: 'var(--paper)', borderBottom: '1px solid var(--rule)',
                }}>
                  {['Topic', 'Mode', 'Status', 'Progress', 'ETA', 'Created'].map((h) => (
                    <div key={h} style={{
                      fontSize: 10, fontWeight: 700, color: 'var(--muted)',
                      textTransform: 'uppercase', letterSpacing: '0.07em',
                    }}>{h}</div>
                  ))}
                </div>

                {visibleJobs.map((j, idx) => {
                  const topic = jobTopic(j);
                  const p = jobProgress(j);
                  const pct = Math.round(p * 100);
                  const eta = j.eta || (j.metadata && j.metadata.eta);
                  const isActive = selId === j.id;
                  const created = relTime(j.created_at);
                  return (
                    <div
                      key={j.id}
                      role="button"
                      tabIndex={0}
                      aria-pressed={isActive}
                      aria-label={`Job: ${topic}, ${j.status}`}
                      className="lh-row-btn"
                      onClick={() => setSelId(isActive ? null : j.id)}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelId(isActive ? null : j.id); } }}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 110px 120px 130px 80px 90px',
                        gap: 10, padding: '13px 18px', alignItems: 'center',
                        borderTop: idx > 0 ? '1px solid var(--rule-soft)' : 'none',
                        background: isActive ? 'var(--sky-soft)' : 'var(--card)',
                        borderLeft: isActive ? `3px solid var(--primary)` : '3px solid transparent',
                      }}
                    >
                      <div style={{
                        fontSize: 14, fontWeight: 600, color: 'var(--ink)',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }} title={topic}>{topic}</div>
                      <div><ModeBadge mode={j.mode} /></div>
                      <div><StatusPill status={j.status} /></div>
                      <div>
                        <progress
                          className="lh-progress"
                          value={pct}
                          max={100}
                          aria-label={`${pct}%`}
                          style={{ width: '100%' }}
                        />
                        <span className="num" style={{ fontSize: 10, color: 'var(--muted)' }}>{pct}%</span>
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--muted)' }}>{eta || '—'}</div>
                      <div style={{ fontSize: 12, color: 'var(--muted)' }}>{created}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Side pane — inline split (not modal) */}
          {hasPane && (
            <div className="lh-jobs-pane card" style={{ padding: 0, overflow: 'hidden' }}>
              {/* Pane header */}
              <div style={{
                padding: '14px 18px', borderBottom: '1px solid var(--rule-soft)',
                display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
              }}>
                <div>
                  {detailLoading && !detail
                    ? <Skeleton h={16} w={160} />
                    : <div style={{
                        fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 16,
                        color: 'var(--ink)', lineHeight: 1.3,
                      }}>{detail ? jobTopic(detail) : `Job ${selId}`}</div>
                  }
                  {detail && (
                    <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--muted)', marginTop: 4 }}>
                      {detail.id}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => setSelId(null)}
                  aria-label="Close job details"
                  style={{
                    border: 'none', background: 'none', cursor: 'pointer',
                    fontSize: 18, color: 'var(--muted)', lineHeight: 1, padding: '0 2px',
                  }}
                >&times;</button>
              </div>

              {/* Pane body */}
              <div style={{ padding: '16px 18px', overflowY: 'auto', maxHeight: 'calc(80vh - 120px)' }}>
                {detailLoading && !detail && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <Skeleton h={14} /><Skeleton h={14} w="80%" /><Skeleton h={14} w="60%" />
                    <Skeleton h={14} w="90%" style={{ marginTop: 8 }} />
                  </div>
                )}
                {!detailLoading && !detail && (
                  <div style={{ color: 'var(--muted)', fontSize: 13 }}>Could not load this job.</div>
                )}
                {detail && <JobDetail job={detail} />}
              </div>

              {/* Pane footer — actions */}
              {detail && (
                <div style={{
                  padding: '12px 18px', borderTop: '1px solid var(--rule-soft)',
                  display: 'flex', gap: 8, flexWrap: 'wrap', background: 'var(--card)',
                }}>
                  <Btn
                    kind="ghost"
                    icon="◎"
                    aria-label="Watch this job's research process live"
                    onClick={() => setWatchId(detail.id)}
                  >Watch live</Btn>
                  {(detail.status === 'review' || detail.status === 'staged') && (
                    <>
                      <Btn
                        kind="success"
                        disabled={actionBusy != null}
                        aria-label="Approve this job"
                        onClick={() => act(detail.id, 'approve')}
                      >{actionBusy === 'approve' ? 'Approving…' : 'Approve'}</Btn>
                      <Btn
                        kind="danger"
                        disabled={actionBusy != null}
                        aria-label="Reject this job"
                        onClick={() => act(detail.id, 'reject')}
                      >{actionBusy === 'reject' ? 'Rejecting…' : 'Reject'}</Btn>
                    </>
                  )}
                  {detail.status === 'running' && (
                    <Btn
                      kind="ghost"
                      disabled={actionBusy != null}
                      aria-label="Pause this job"
                      onClick={() => act(detail.id, 'pause')}
                    >{actionBusy === 'pause' ? 'Pausing…' : 'Pause'}</Btn>
                  )}
                  {detail.status === 'paused' && (
                    <Btn
                      kind="ghost"
                      disabled={actionBusy != null}
                      aria-label="Resume this job"
                      onClick={() => act(detail.id, 'resume')}
                    >{actionBusy === 'resume' ? 'Resuming…' : 'Resume'}</Btn>
                  )}
                  {(detail.status === 'running' || detail.status === 'paused') && (
                    <Btn
                      kind="danger"
                      disabled={actionBusy != null}
                      aria-label="Cancel this job"
                      onClick={() => act(detail.id, 'cancel')}
                    >{actionBusy === 'cancel' ? 'Cancelling…' : 'Cancel'}</Btn>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* New Research modal */}
        {showNew && (
          <NewJobModal
            toast={toast}
            onClose={() => setShowNew(false)}
            onCreated={() => { setShowNew(false); reload(); toast.show('Research job queued', 'success'); }}
          />
        )}

        {/* Live research-process trace */}
        {watchId && window.JobTrace && (
          <SidePane title="Live research trace" onClose={() => setWatchId(null)}>
            <window.JobTrace jobId={watchId} onClose={() => setWatchId(null)} />
          </SidePane>
        )}
      </div>
    );
  }

  function JobDetail({ job }) {
    const meta = job.metadata || {};
    const p = jobProgress(job);
    const topic = jobTopic(job);
    const modeInfo = JOB_MODES.find((m) => m.key === job.mode);

    return (
      <div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
          <StatusPill status={job.status} />
          <ModeBadge mode={job.mode} />
        </div>

        {modeInfo && (
          <div style={{
            fontSize: 12, color: 'var(--ink-2)', marginBottom: 16,
            padding: '8px 12px', background: 'var(--paper)', borderRadius: 'var(--radius-sm)',
            borderLeft: `3px solid ${modeBorderColor(job.mode)}`,
          }}>
            {modeInfo.desc}
          </div>
        )}

        <div style={{ marginBottom: 18 }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between', fontSize: 11,
            color: 'var(--muted)', marginBottom: 5,
          }}>
            <span style={{ textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Progress</span>
            <span className="num">{Math.round(p * 100)}%</span>
          </div>
          <progress
            className="lh-progress"
            value={Math.round(p * 100)}
            max={100}
            aria-label={`${Math.round(p * 100)}% complete`}
            style={{ width: '100%', height: 8 }}
          />
        </div>

        <div className="small-caps" style={{ color: 'var(--muted)', marginBottom: 8 }}>Details</div>
        <LocalRow k="Topic" v={topic !== `Job ${job.id}` ? topic : '—'} />
        <LocalRow k="Mode" v={job.mode || '—'} />
        <LocalRow k="Depth" v={meta.depth || job.depth || '—'} />
        <LocalRow k="Sources" v={meta.sources != null ? meta.sources : '—'} />
        {job.created_at && <LocalRow k="Created" v={new Date(job.created_at).toLocaleString()} />}
        {job.updated_at && <LocalRow k="Updated" v={new Date(job.updated_at).toLocaleString()} />}
        {meta.step && <LocalRow k="Step" v={meta.step} />}
        {job.budget != null && <LocalRow k="Budget" v={`$${Number(job.budget).toFixed(4)}`} />}
        {job.error && (
          <div style={{
            marginTop: 10, padding: '8px 12px', borderRadius: 'var(--radius-sm)',
            background: '#fff3f3', border: '1px solid var(--coral-2)',
            fontSize: 12, color: 'var(--coral-2)',
          }}>
            <strong>Error:</strong> {job.error}
          </div>
        )}
      </div>
    );
  }

  // Radio-card mode selector for new job modal
  function ModeRadio({ value, onChange }) {
    return (
      <div className="lh-mode-radio" role="radiogroup" aria-label="Research mode">
        {JOB_MODES.map((m) => (
          <div
            key={m.key}
            role="radio"
            aria-checked={value === m.key}
            tabIndex={0}
            className={`lh-mode-card${value === m.key ? ' selected' : ''}`}
            onClick={() => onChange(m.key)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onChange(m.key); } }}
            aria-label={`${m.label}: ${m.desc}`}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--ink)' }}>{m.label}</span>
              <span style={{
                width: 14, height: 14, borderRadius: '50%',
                border: `2px solid ${value === m.key ? 'var(--primary)' : 'var(--rule)'}`,
                background: value === m.key ? 'var(--primary)' : 'transparent',
                flexShrink: 0, transition: 'border-color .12s, background .12s',
              }} />
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{m.desc}</div>
          </div>
        ))}
      </div>
    );
  }

  // ── Research Plan Preview (inside NewJobModal) ───────────────────────────

  function QuestionTypeChip({ type }) {
    const COLOR_MAP = {
      comparative:       { bg: '#e3f2fd', color: '#1565c0' },
      causal_explanation:{ bg: '#fce4ec', color: '#880e4f' },
      predictive:        { bg: '#e8f5e9', color: '#2e7d32' },
      evaluative:        { bg: '#fff8e1', color: '#795548' },
      descriptive:       { bg: '#f3e5f5', color: '#6a1b9a' },
      normative:         { bg: '#fbe9e7', color: '#bf360c' },
    };
    const s = COLOR_MAP[type] || { bg: 'var(--rule-soft)', color: 'var(--muted)' };
    return (
      <span style={{
        display: 'inline-block', padding: '2px 10px', borderRadius: 99,
        fontSize: 11, fontWeight: 700, letterSpacing: '0.04em',
        background: s.bg, color: s.color, textTransform: 'uppercase',
      }}>{(type || 'unknown').replace(/_/g, ' ')}</span>
    );
  }

  function PlanPreview({ plan, onUpdate }) {
    // plan: { question_type, critique, framings, chosen_label, sub_questions, load_bearing }
    const [subQs, setSubQs] = useState(plan.sub_questions || []);
    const [editIdx, setEditIdx] = useState(null);
    const [editVal, setEditVal] = useState('');
    const [chosenLabel, setChosenLabel] = useState(plan.chosen_label);
    const [collapsed, setCollapsed] = useState(false);

    const loadBearing = new Set(plan.load_bearing || []);
    const critiqueNotes = (plan.critique && plan.critique.notes) || [];

    // Derive warnings from critique flags
    const warnings = [];
    if (plan.critique) {
      if (plan.critique.is_compound) warnings.push('Compound question — consider splitting into sub-questions.');
      if (plan.critique.has_presupposition) warnings.push('Contains a presupposition that may need examination.');
      if (plan.critique.is_underspecified) warnings.push('Underspecified — clarifying details may improve results.');
      if (plan.critique.implicit_utility) warnings.push('Implicit value judgment detected.');
    }
    critiqueNotes.forEach((n) => { if (!warnings.includes(n)) warnings.push(n); });

    function startEdit(i) {
      setEditIdx(i);
      setEditVal(subQs[i]);
    }

    function commitEdit(i) {
      const next = subQs.slice();
      next[i] = editVal.trim() || subQs[i];
      setSubQs(next);
      setEditIdx(null);
      onUpdate({ sub_questions: next, chosen_label: chosenLabel });
    }

    function removeQ(i) {
      const next = subQs.filter((_, j) => j !== i);
      setSubQs(next);
      onUpdate({ sub_questions: next, chosen_label: chosenLabel });
    }

    function addQ() {
      const next = [...subQs, ''];
      setSubQs(next);
      setEditIdx(next.length - 1);
      setEditVal('');
    }

    function chooseFraming(label) {
      setChosenLabel(label);
      onUpdate({ sub_questions: subQs, chosen_label: label });
    }

    const chosenFraming = plan.framings.find((f) => f.label === chosenLabel) || plan.framings[0];
    const altFramings = plan.framings.filter((f) => f.label !== chosenLabel);

    return (
      <div style={{
        marginTop: 14, border: '1px solid var(--sky)', borderRadius: 'var(--radius-sm)',
        background: 'var(--sky-soft)', overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '10px 14px', borderBottom: '1px solid var(--rule-soft)',
          background: 'var(--card)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink)' }}>&#10003; Research Plan</span>
            <QuestionTypeChip type={plan.question_type} />
          </div>
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-expanded={!collapsed}
            style={{
              border: 'none', background: 'none', cursor: 'pointer',
              fontSize: 11, color: 'var(--muted)', fontWeight: 600,
              fontFamily: 'var(--sans)', padding: '2px 6px',
            }}
          >{collapsed ? 'Show plan' : 'Hide plan'}</button>
        </div>

        {!collapsed && (
          <div style={{ padding: '12px 14px' }}>
            {/* Critique warnings */}
            {warnings.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 12 }}>
                {warnings.map((w, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'flex-start', gap: 6,
                    padding: '5px 10px', borderRadius: 'var(--radius-sm)',
                    background: '#fff8e1', border: '1px solid var(--sand)',
                    fontSize: 11.5, color: '#795548', lineHeight: 1.4,
                  }}>
                    <span style={{ flexShrink: 0, fontWeight: 700 }}>&#9888;</span>
                    <span>{w}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Sub-questions */}
            <div style={{ marginBottom: 12 }}>
              <div style={{
                fontSize: 10, fontWeight: 700, color: 'var(--muted)',
                textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6,
              }}>Sub-questions</div>
              {subQs.map((q, i) => {
                const isLB = loadBearing.has(q);
                return (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '5px 0',
                    borderBottom: i < subQs.length - 1 ? '1px solid var(--rule-soft)' : 'none',
                  }}>
                    <span style={{ flexShrink: 0, fontSize: 12 }} title="Load-bearing question">
                      {isLB ? '🎯' : '  '}
                    </span>
                    {editIdx === i ? (
                      <input
                        autoFocus
                        value={editVal}
                        onChange={(e) => setEditVal(e.target.value)}
                        onBlur={() => commitEdit(i)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') { e.preventDefault(); commitEdit(i); }
                          if (e.key === 'Escape') { setEditIdx(null); }
                        }}
                        style={{ ...inputStyle, flex: 1, fontSize: 12, padding: '3px 6px' }}
                        aria-label={`Edit sub-question ${i + 1}`}
                      />
                    ) : (
                      <span style={{ flex: 1, fontSize: 12.5, color: 'var(--ink)', lineHeight: 1.4 }}>{q || '​'}</span>
                    )}
                    <button
                      type="button"
                      title="Edit"
                      onClick={() => startEdit(i)}
                      style={{
                        border: 'none', background: 'none', cursor: 'pointer',
                        fontSize: 11, color: 'var(--muted)', padding: '1px 4px',
                        borderRadius: 3, flexShrink: 0,
                      }}
                      aria-label={`Edit sub-question ${i + 1}`}
                    >&#9998;</button>
                    <button
                      type="button"
                      title="Remove"
                      onClick={() => removeQ(i)}
                      style={{
                        border: 'none', background: 'none', cursor: 'pointer',
                        fontSize: 13, color: 'var(--muted)', padding: '1px 4px',
                        borderRadius: 3, flexShrink: 0,
                      }}
                      aria-label={`Remove sub-question ${i + 1}`}
                    >&times;</button>
                  </div>
                );
              })}
              <button
                type="button"
                onClick={addQ}
                style={{
                  marginTop: 6, border: '1px dashed var(--rule)', borderRadius: 'var(--radius-sm)',
                  background: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--primary)',
                  padding: '4px 10px', fontFamily: 'var(--sans)', width: '100%', textAlign: 'left',
                }}
                aria-label="Add sub-question"
              >+ Add sub-question</button>
            </div>

            {/* Chosen framing */}
            {chosenFraming && (
              <div>
                <div style={{
                  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
                  textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6,
                }}>Frame</div>
                <div style={{
                  padding: '8px 12px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--card)', border: '1px solid var(--primary)',
                  fontSize: 12.5, color: 'var(--ink)', marginBottom: 8, lineHeight: 1.4,
                }}>
                  <span style={{ fontWeight: 700, color: 'var(--primary)', marginRight: 4 }}>{chosenFraming.label} —</span>
                  {chosenFraming.statement}
                  {chosenFraming.rationale && (
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, fontStyle: 'italic' }}>
                      {chosenFraming.rationale}
                    </div>
                  )}
                </div>
                {altFramings.length > 0 && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {altFramings.map((f) => (
                      <button
                        key={f.label}
                        type="button"
                        onClick={() => chooseFraming(f.label)}
                        title={f.statement}
                        style={{
                          border: '1px solid var(--rule)', borderRadius: 99,
                          background: 'var(--card)', cursor: 'pointer',
                          fontSize: 11, color: 'var(--ink-2)', padding: '3px 10px',
                          fontFamily: 'var(--sans)', transition: 'border-color .1s',
                        }}
                        aria-label={`Switch to framing ${f.label}: ${f.statement}`}
                      >{f.label} — {f.statement.length > 40 ? f.statement.slice(0, 40) + '…' : f.statement}</button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  function NewJobModal({ onClose, onCreated, toast }) {
    const [mode, setMode] = useState('Deep-Dive');
    const [topic, setTopic] = useState('');
    const [depth, setDepth] = useState('Standard');
    const [sources, setSources] = useState(10);
    const [busy, setBusy] = useState(false);
    const [planBusy, setPlanBusy] = useState(false);
    const [plan, setPlan] = useState(null);
    const [planMods, setPlanMods] = useState(null); // user edits to the plan
    const textRef = useRef(null);
    useEffect(() => { if (textRef.current) textRef.current.focus(); }, []);

    async function previewPlan() {
      if (!topic.trim()) { toast.show('Enter a topic first.', 'info'); return; }
      setPlanBusy(true);
      try {
        const result = await apiPost('/api/research/plan', { question: topic.trim() });
        setPlan(result);
        setPlanMods({ sub_questions: result.sub_questions, chosen_label: result.chosen_label });
      } catch (err) {
        toast.show(`Plan preview failed: ${err.message}`, 'error');
      } finally {
        setPlanBusy(false);
      }
    }

    async function submit(e) {
      if (e) e.preventDefault();
      if (!topic.trim()) { toast.show('Enter a topic first.', 'info'); return; }
      setBusy(true);
      try {
        const metadata = planMods ? { research_plan: planMods } : undefined;
        await apiPost('/api/jobs', { mode, topic: topic.trim(), depth, sources, ...(metadata ? { metadata } : {}) });
        onCreated();
      } catch (err) {
        toast.show(err.message, 'error');
        setBusy(false);
      }
    }

    return (
      <Modal title="New research job" onClose={onClose}>
        <form onSubmit={submit}>
          <LocalField label="Topic" htmlFor="nj-topic">
            <textarea
              id="nj-topic"
              ref={textRef}
              rows={3}
              value={topic}
              onChange={(e) => { setTopic(e.target.value); setPlan(null); setPlanMods(null); }}
              placeholder="What should Lighthouse research?"
              style={{ ...inputStyle, resize: 'vertical', minHeight: 72 }}
              aria-label="Research topic"
            />
          </LocalField>

          {/* Preview Plan button — shown when there is a topic but no plan yet */}
          {!plan && (
            <div style={{ marginBottom: 14 }}>
              <button
                type="button"
                disabled={planBusy || !topic.trim()}
                onClick={previewPlan}
                aria-label="Preview research plan"
                style={{
                  border: `1px solid var(--primary)`, borderRadius: 'var(--radius-sm)',
                  background: planBusy ? 'var(--sky-soft)' : 'var(--card)',
                  color: 'var(--primary)', cursor: planBusy || !topic.trim() ? 'not-allowed' : 'pointer',
                  fontSize: 12, fontWeight: 600, padding: '6px 14px',
                  fontFamily: 'var(--sans)', opacity: !topic.trim() ? 0.5 : 1,
                  transition: 'background .12s',
                }}
              >{planBusy ? 'Analysing…' : 'Preview Plan →'}</button>
            </div>
          )}

          {/* Plan preview panel */}
          {plan && (
            <PlanPreview
              plan={plan}
              onUpdate={(mods) => setPlanMods(mods)}
            />
          )}

          <LocalField label="Mode" style={{ marginTop: plan ? 14 : 0 }}>
            <ModeRadio value={mode} onChange={setMode} />
          </LocalField>

          <LocalField label="Depth" htmlFor="nj-depth">
            <div style={{ display: 'flex', gap: 8 }} role="group" aria-label="Research depth">
              {JOB_DEPTHS.map((dp) => (
                <button
                  key={dp}
                  type="button"
                  aria-pressed={depth === dp}
                  onClick={() => setDepth(dp)}
                  style={{
                    flex: 1, padding: '7px 0', border: `2px solid ${depth === dp ? 'var(--primary)' : 'var(--rule)'}`,
                    borderRadius: 'var(--radius-sm)', background: depth === dp ? 'var(--sky-soft)' : 'var(--card)',
                    color: depth === dp ? 'var(--primary)' : 'var(--ink)', fontWeight: 600, fontSize: 13,
                    cursor: 'pointer', transition: 'border-color .12s, background .12s',
                    fontFamily: 'var(--sans)',
                  }}
                >{dp}</button>
              ))}
            </div>
          </LocalField>

          <LocalField label={`Sources to consult: ${sources}`} htmlFor="nj-sources">
            <input
              id="nj-sources"
              type="range"
              min={1}
              max={20}
              value={sources}
              onChange={(e) => setSources(Number(e.target.value))}
              style={{ width: '100%', accentColor: 'var(--primary)' }}
              aria-label={`Source count: ${sources}`}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
              <span>1</span>
              <span className="num" style={{ fontWeight: 700, color: 'var(--ink)' }}>{sources}</span>
              <span>20</span>
            </div>
          </LocalField>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 22 }}>
            <Btn kind="ghost" type="button" onClick={onClose} aria-label="Cancel new job">Cancel</Btn>
            <Btn type="submit" disabled={busy} aria-label={busy ? 'Starting research' : 'Start research'}>
              {busy ? 'Starting…' : 'Start research'}
            </Btn>
          </div>
        </form>
      </Modal>
    );
  }

  // ════════════════════════════ DRAFTS PAGE ════════════════════════════════
  const DRAFTS_TABS = [
    { key: 'staged',   label: 'Staged' },
    { key: 'approved', label: 'Approved' },
    { key: 'rejected', label: 'Rejected' },
    { key: 'all',      label: 'All' },
  ];

  const DRAFTS_EMPTY = {
    staged:   { title: 'No drafts awaiting review', hint: 'Research in progress will stage a draft here when ready for your approval.' },
    approved: { title: 'No approved drafts yet', hint: 'Approve a staged draft to see it here.' },
    rejected: { title: 'No rejected drafts', hint: 'Rejected drafts will be archived here.' },
    all:      { title: 'No drafts yet', hint: 'When a research job finishes, its draft lands here.' },
  };

  function DraftsPage({ toast }) {
    const { data, loading, error, reload } = useApi('/api/drafts', { pollMs: 10000 });
    const [tab, setTab] = useState('staged');
    const [selId, setSelId] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [busy, setBusy] = useState(null);

    useEvents((name) => { if (name && name.indexOf('draft.') === 0) reload(); });
    useEffect(() => { if (error) toast.show(`Drafts failed to load: ${error}`, 'error'); }, [error]);

    const drafts = (data && Array.isArray(data.drafts)) ? data.drafts : [];
    const staged   = drafts.filter((d) => d && d.status === 'staged');
    const approved = drafts.filter((d) => d && (d.status === 'approved' || d.status === 'published'));
    const rejected = drafts.filter((d) => d && d.status === 'rejected');

    const tabCounts = {
      staged:   staged.length,
      approved: approved.length,
      rejected: rejected.length,
      all:      drafts.length,
    };

    const visibleDrafts = tab === 'staged'   ? staged
      : tab === 'approved' ? approved
      : tab === 'rejected' ? rejected
      : drafts;

    // Load draft detail when selection changes
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
      setBusy('approve');
      try {
        await apiPost(`/api/drafts/${id}/approve`);
        toast.show('Draft approved', 'success');
        setSelId(null);
        reload();
        setTab('approved');
      } catch (e) {
        toast.show(e.message, 'error');
      } finally {
        setBusy(null);
      }
    }

    async function reject(id) {
      setBusy('reject');
      try {
        await apiPost(`/api/drafts/${id}/reject`);
        toast.show('Draft rejected', 'info');
        setSelId(null);
        reload();
        setTab('all');
      } catch (e) {
        toast.show(e.message, 'error');
      } finally {
        setBusy(null);
      }
    }

    function exportDraft(id) {
      window.open(`/api/drafts/${id}`, '_blank');
    }

    const firstLoad = loading && !data;
    const tabs = DRAFTS_TABS.map((t) => ({ ...t, count: tabCounts[t.key] }));
    const emptyInfo = DRAFTS_EMPTY[tab] || DRAFTS_EMPTY.all;

    return (
      <div style={{ padding: PAD, maxWidth: 1200 }}>
        <PageHeader
          title="Drafts"
          subtitle={
            firstLoad ? 'Loading…'
              : staged.length === 0 ? 'Nothing awaiting review'
              : `${staged.length} awaiting review`
          }
          actions={selId != null ? (
            <Btn
              kind="ghost"
              onClick={() => exportDraft(selId)}
              aria-label="Export selected draft"
            >Export…</Btn>
          ) : null}
        />

        <div style={{ marginBottom: GAP }}>
          <TabBar
            tabs={tabs}
            active={tab}
            onChange={(k) => { setTab(k); setSelId(null); }}
          />
        </div>

        {/* Split layout */}
        <div className="lh-split">
          {/* Draft list — 40% */}
          <div className="lh-split-list">

            {firstLoad && (
              <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} style={{
                    padding: '14px 18px',
                    borderTop: i ? '1px solid var(--rule-soft)' : 'none',
                  }}>
                    <Skeleton h={14} w="65%" />
                    <Skeleton h={11} w="40%" style={{ marginTop: 6 }} />
                    <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                      <Skeleton h={18} w={80} r={99} />
                      <Skeleton h={18} w={50} r={99} />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {error && !data && (
              <ErrorBox message={error} action={<Btn kind="ghost" onClick={reload}>Retry</Btn>} />
            )}

            {!firstLoad && visibleDrafts.length === 0 && (
              <EmptyState
                icon="&#9998;"
                title={emptyInfo.title}
                hint={emptyInfo.hint}
                action={
                  tab !== 'approved' && tab !== 'rejected'
                    ? <Btn onClick={() => { window.location.hash = 'jobs'; }} aria-label="Go to jobs page">Go to Jobs</Btn>
                    : null
                }
              />
            )}

            {!firstLoad && visibleDrafts.length > 0 && (
              <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                {visibleDrafts.map((d, idx) => {
                  const isActive = selId === d.id;
                  const title = d.title || `Draft ${d.id}`;
                  const srcs = d.source_count != null ? d.source_count
                    : Array.isArray(d.sources) ? d.sources.length : null;
                  const created = d.created_at
                    ? new Date(d.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                    : '—';
                  return (
                    <div
                      key={d.id}
                      role="button"
                      tabIndex={0}
                      aria-pressed={isActive}
                      aria-label={`Draft: ${title}`}
                      className="lh-draft-item"
                      onClick={() => setSelId(isActive ? null : d.id)}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelId(isActive ? null : d.id); } }}
                      style={{
                        padding: '14px 18px',
                        borderTop: idx > 0 ? '1px solid var(--rule-soft)' : 'none',
                        background: isActive ? 'var(--sky-soft)' : 'var(--card)',
                        borderLeft: isActive ? '3px solid var(--primary)' : '3px solid transparent',
                      }}
                    >
                      <div style={{
                        fontFamily: 'var(--serif)', fontSize: 14, fontWeight: 600,
                        color: 'var(--ink)', lineHeight: 1.35,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }} title={title}>{title}</div>
                      {d.topic && (
                        <div style={{
                          fontSize: 11, color: 'var(--muted)', marginTop: 3,
                          textTransform: 'uppercase', letterSpacing: '0.06em',
                        }}>{d.topic}</div>
                      )}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                        <ConfidencePill phrase={d.wep_phrase} band={d.wep_band} />
                        {srcs != null && (
                          <span style={{
                            fontSize: 11, color: 'var(--muted)',
                            background: 'var(--rule-soft)', padding: '2px 6px', borderRadius: 99,
                          }}>
                            <span className="num">{srcs}</span> src{srcs === 1 ? '' : 's'}
                          </span>
                        )}
                        <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 'auto' }}>{created}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Reader pane — 60% */}
          {selId != null && (
            <div className="lh-split-reader card" style={{ padding: 0, overflow: 'hidden' }}>
              {/* Reader body */}
              <div style={{ padding: '20px 24px', overflowY: 'auto', maxHeight: 'calc(80vh - 80px)' }}>

                {detailLoading && !detail && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <Skeleton h={10} w={80} />
                    <Skeleton h={24} w="70%" />
                    <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                      <Skeleton h={20} w={90} r={99} />
                      <Skeleton h={20} w={60} r={99} />
                    </div>
                    <Skeleton h={14} style={{ marginTop: 12 }} />
                    <Skeleton h={14} w="95%" />
                    <Skeleton h={14} w="88%" />
                    <Skeleton h={14} w="92%" />
                    <Skeleton h={14} w="80%" />
                  </div>
                )}

                {!detailLoading && !detail && (
                  <div style={{ color: 'var(--muted)', fontSize: 13, textAlign: 'center', padding: '40px 0' }}>
                    Could not load this draft.
                  </div>
                )}

                {detail && <DraftReader draft={detail} />}
              </div>

              {/* Sticky footer — approve / reject for staged */}
              {detail && detail.status === 'staged' && (
                <div className="lh-reader-footer">
                  <Btn
                    kind="ghost"
                    disabled={busy != null}
                    aria-label="Reject this draft"
                    onClick={() => reject(detail.id)}
                  >{busy === 'reject' ? 'Rejecting…' : 'Reject'}</Btn>
                  <Btn
                    disabled={busy != null}
                    aria-label="Approve this draft"
                    onClick={() => approve(detail.id)}
                  >{busy === 'approve' ? 'Approving…' : 'Approve'}</Btn>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Evidence Table (inside DraftReader) ────────────────────────────────

  function EntailmentBadge({ score }) {
    if (score == null) {
      return (
        <span style={{
          fontSize: 11, background: 'var(--rule-soft)', color: 'var(--muted)',
          padding: '2px 7px', borderRadius: 99, fontWeight: 600,
        }}>?</span>
      );
    }
    const supported = score >= 0.5;
    return (
      <span style={{
        fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 99,
        background: supported ? '#e8f5e9' : '#fff8e1',
        color: supported ? 'var(--green-dark)' : '#795548',
      }}>{supported ? '✓ supported' : '✗ uncertain'}</span>
    );
  }

  function EvidenceTable({ draft }) {
    // Parse [N] citation markers from body_html
    const citations = Array.isArray(draft.citations) ? draft.citations : [];
    const sourceCount = draft.source_count != null ? draft.source_count : 0;

    // Build rows from citations array if available; otherwise use a placeholder
    const hasCitationData = citations.length > 0;

    function buildCSV(rows) {
      const header = 'Source,Excerpt,Grade,Entailment\n';
      const body = rows.map((r) => {
        const esc = (v) => `"${String(v || '').replace(/"/g, '""')}"`;
        return [esc(r.source), esc(r.excerpt), esc(r.grade), esc(r.entailment)].join(',');
      }).join('\n');
      return header + body;
    }

    function downloadCSV(rows) {
      const csv = buildCSV(rows);
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `evidence-${draft.id || 'draft'}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }

    // Build table rows from citations metadata
    const rows = citations.map((c, i) => ({
      source: c.source || c.url || `[${i + 1}]`,
      excerpt: c.text ? c.text.slice(0, 80) + (c.text.length > 80 ? '…' : '') : '—',
      grade: c.grade || '—',
      entailment_score: c.entailment_score != null ? c.entailment_score : null,
      entailment: c.entailment_score != null
        ? (c.entailment_score >= 0.5 ? '✓ supported' : '✗ uncertain')
        : '?',
    }));

    return (
      <div style={{ marginTop: 28 }}>
        {/* Section header */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginBottom: 10,
        }}>
          <div style={{
            fontSize: 10, fontWeight: 700, color: 'var(--muted)',
            textTransform: 'uppercase', letterSpacing: '0.08em',
          }}>Evidence table</div>
          {rows.length > 0 && (
            <button
              type="button"
              onClick={() => downloadCSV(rows)}
              style={{
                border: '1px solid var(--rule)', borderRadius: 'var(--radius-sm)',
                background: 'var(--card)', cursor: 'pointer', fontSize: 11,
                color: 'var(--ink-2)', padding: '3px 10px', fontFamily: 'var(--sans)',
                fontWeight: 600,
              }}
              aria-label="Export evidence table as CSV"
            >Export CSV</button>
          )}
        </div>

        <div style={{
          border: '1px solid var(--rule)', borderRadius: 'var(--radius-sm)',
          overflow: 'hidden', background: 'var(--card)',
        }}>
          {/* Table header */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '100px 1fr 60px 120px',
            gap: 8, padding: '7px 12px',
            background: 'var(--paper)', borderBottom: '1px solid var(--rule)',
          }}>
            {['Source', 'Excerpt', 'Grade', 'Entailment'].map((h) => (
              <div key={h} style={{
                fontSize: 10, fontWeight: 700, color: 'var(--muted)',
                textTransform: 'uppercase', letterSpacing: '0.07em',
              }}>{h}</div>
            ))}
          </div>

          {/* Placeholder when no chunk data available yet */}
          {!hasCitationData && sourceCount > 0 && (
            <div style={{
              padding: '16px 14px', fontSize: 12.5, color: 'var(--muted)',
              fontStyle: 'italic', textAlign: 'center',
            }}>
              Citation analysis available after re-research
            </div>
          )}

          {/* No sources at all */}
          {!hasCitationData && sourceCount === 0 && (
            <div style={{
              padding: '16px 14px', fontSize: 12.5, color: 'var(--muted)',
              fontStyle: 'italic', textAlign: 'center',
            }}>
              No citations in this draft.
            </div>
          )}

          {/* Populated rows */}
          {rows.map((r, i) => (
            <div
              key={i}
              style={{
                display: 'grid', gridTemplateColumns: '100px 1fr 60px 120px',
                gap: 8, padding: '8px 12px', alignItems: 'start',
                borderTop: '1px solid var(--rule-soft)',
                background: i % 2 === 1 ? 'var(--paper)' : 'var(--card)',
              }}
            >
              <div style={{
                fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--mono)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }} title={r.source}>{r.source}</div>
              <div style={{
                fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.4,
                fontStyle: 'italic',
              }}>{r.excerpt}</div>
              <div style={{
                fontSize: 12, fontWeight: 700, color: 'var(--ink)',
                fontFamily: 'var(--mono)',
              }}>{r.grade}</div>
              <div><EntailmentBadge score={r.entailment_score} /></div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  function DraftReader({ draft }) {
    const sources = draft.source_count != null ? draft.source_count
      : Array.isArray(draft.sources) ? draft.sources.length : null;
    const confidence = draft.confidence != null ? Number(draft.confidence).toFixed(2) : null;

    return (
      <div>
        {draft.topic && (
          <div style={{
            fontSize: 10, fontWeight: 700, color: 'var(--primary)',
            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10,
          }}>{draft.topic}</div>
        )}

        <h2 style={{
          fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 20,
          margin: '0 0 14px', color: 'var(--ink)', lineHeight: 1.3,
        }}>{draft.title || `Draft ${draft.id}`}</h2>

        {/* Metadata row */}
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
          marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid var(--rule-soft)',
        }}>
          {(draft.wep_phrase || draft.wep_band) && (
            <ConfidencePill phrase={draft.wep_phrase} band={draft.wep_band} />
          )}
          {draft.status && <StatusPill status={draft.status} />}
          {sources != null && (
            <span style={{
              fontSize: 12, color: 'var(--ink-2)',
              background: 'var(--rule-soft)', padding: '2px 8px', borderRadius: 99,
            }}>
              <span className="num">{sources}</span> source{sources === 1 ? '' : 's'}
            </span>
          )}
          {confidence != null && (
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>
              Confidence <span className="num">{confidence}</span>
            </span>
          )}
          {draft.mode && <ModeBadge mode={draft.mode} />}
        </div>

        {/* Body HTML */}
        {draft.body_html ? (
          <div
            className="lh-body-html lh-prose"
            style={{
              fontFamily: 'var(--serif)', fontSize: 15, lineHeight: 1.65, color: 'var(--ink-2)',
            }}
            dangerouslySetInnerHTML={{ __html: draft.body_html }}
          />
        ) : (
          <div style={{ fontSize: 13, color: 'var(--muted)', fontStyle: 'italic' }}>
            This draft has no body content yet.
          </div>
        )}

        {/* Evidence table — shown when there is body content or sources */}
        {(draft.body_html || sources > 0) && (
          <EvidenceTable draft={draft} />
        )}

        {/* Rejection note */}
        {draft.status === 'rejected' && (draft.reject_reason || draft.reason) && (
          <div style={{
            marginTop: 24, fontSize: 12.5, color: 'var(--coral-2)',
            borderTop: '1px solid var(--rule)', paddingTop: 14,
          }}>
            <strong>Rejected:</strong> {draft.reject_reason || draft.reason}
          </div>
        )}
      </div>
    );
  }

  Object.assign(window, { HomePage, JobsPage, DraftsPage });
})();
