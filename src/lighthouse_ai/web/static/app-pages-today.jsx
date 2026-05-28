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

  // Budget progress bar that shifts green → amber → red
  function BudgetBar({ label, used, cap, unit }) {
    if (cap == null || cap === 0) return null;
    const pct = Math.min(1, used / cap);
    const color = pct >= 0.85 ? 'var(--coral-2)' : pct >= 0.60 ? 'var(--sand)' : 'var(--green)';
    return (
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between',
          fontSize: 11, color: 'var(--muted)', marginBottom: 4,
        }}>
          <span style={{ textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>{label}</span>
          <span className="num">{used != null ? used : '?'}{unit ? ` ${unit}` : ''} / {cap}{unit ? ` ${unit}` : ''}</span>
        </div>
        <div style={{
          height: 7, borderRadius: 99, background: 'var(--rule-soft)', overflow: 'hidden',
        }}>
          <div style={{
            height: '100%', width: `${Math.round(pct * 100)}%`,
            background: color, borderRadius: 99, transition: 'width .4s ease',
          }} />
        </div>
      </div>
    );
  }

  // Mode badge — small colored pill
  function ModeBadge({ mode }) {
    const MAP = {
      'Deep-Dive': { bg: '#e3f2fd', color: 'var(--ink-2)' },
      'Monitor':   { bg: '#e8f5e9', color: '#2e7d32' },
      'QUC':       { bg: '#fff8e1', color: '#795548' },
      'Debate':    { bg: '#fce4ec', color: '#880e4f' },
      'Digest':    { bg: 'var(--rule-soft)', color: 'var(--muted)' },
    };
    const s = MAP[mode] || MAP['Digest'];
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center',
        padding: '2px 8px', borderRadius: 99, fontSize: 11, fontWeight: 700,
        background: s.bg, color: s.color, letterSpacing: '0.04em',
        textTransform: 'uppercase', whiteSpace: 'nowrap',
      }}>{mode || 'Job'}</span>
    );
  }

  // Alert strip (warn / info / error variants)
  function AlertStrip({ alerts }) {
    if (!alerts || alerts.length === 0) return null;
    const kindColor = (k) => {
      if (k === 'error' || k === 'budget') return { bg: '#fff3f3', border: 'var(--coral-2)', text: 'var(--coral-2)' };
      if (k === 'warn' || k === 'warning') return { bg: '#fff8e1', border: 'var(--sand)', text: '#795548' };
      return { bg: 'var(--sky-soft)', border: 'var(--primary)', text: 'var(--ink-2)' };
    };
    return (
      <div style={{ marginBottom: GAP, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {alerts.map((a, i) => {
          const c = kindColor(a.kind);
          return (
            <div key={i} role="alert" style={{
              display: 'flex', alignItems: 'flex-start', gap: 10,
              padding: '10px 14px', borderRadius: 'var(--radius-sm)',
              background: c.bg, borderLeft: `3px solid ${c.border}`,
            }}>
              <span style={{
                fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
                textTransform: 'uppercase', color: c.border, flexShrink: 0, paddingTop: 1,
              }}>{a.kind || 'alert'}</span>
              <span style={{ fontSize: 13, color: c.text, lineHeight: 1.45 }}>{a.text}</span>
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
    const { data, loading, error, reload } = useApi('/api/dashboard', { pollMs: 12000 });
    useEvents(() => reload());
    useEffect(() => {
      if (error) toast.show(`Dashboard error: ${error}`, 'error');
    }, [error]);

    const d = data || {};
    const cal = d.calibration || {};
    const jobs = Array.isArray(d.jobs) ? d.jobs : [];
    const alerts = Array.isArray(d.alerts) ? d.alerts : [];
    const digest = Array.isArray(d.digest) ? d.digest : [];
    const budget = d.budget || {};
    const cloud = budget.cloud || {};
    const tokens = budget.tokens || {};
    const running = jobs.filter((j) => j && j.status === 'running');
    const firstLoad = loading && !data;

    const dateLabel = d.date || new Date().toLocaleDateString(undefined, {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
    });

    const brier = cal.brier != null ? Number(cal.brier).toFixed(3) : null;

    return (
      <div style={{ padding: PAD, maxWidth: 1100 }}>
        <PageHeader
          title={d.greeting || 'Lighthouse'}
          subtitle={dateLabel}
        />

        {/* Alert strip — appears if anything needs attention */}
        <AlertStrip alerts={alerts} />

        {/* Two-column layout: left = lead + calibration, right = jobs + digest */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)',
          gap: GAP,
          alignItems: 'start',
        }}>
          {/* ── LEFT COLUMN ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: GAP }}>

            {/* Lead story card */}
            {firstLoad && (
              <div className="card" style={{ padding: '20px 24px' }}>
                <Skeleton h={10} w={80} />
                <Skeleton h={28} w="75%" style={{ margin: '12px 0 8px' }} />
                <Skeleton h={14} />
                <Skeleton h={14} w="88%" style={{ marginTop: 4 }} />
                <Skeleton h={22} w={110} style={{ marginTop: 14, borderRadius: 99 }} />
              </div>
            )}

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
                    fontFamily: 'var(--serif)', fontSize: 15, lineHeight: 1.6,
                    color: 'var(--ink-2)', margin: '0 0 14px',
                  }}>{d.lead.dek}</p>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  {d.lead.wep && (
                    <ConfidencePill phrase={d.lead.wep.phrase || d.lead.wep} band={d.lead.wep.band} />
                  )}
                  {d.lead.sources != null && (
                    <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                      <span className="num">{d.lead.sources}</span> source{d.lead.sources === 1 ? '' : 's'}
                    </span>
                  )}
                  {d.lead.duration && (
                    <span style={{ fontSize: 12, color: 'var(--muted)' }}>{d.lead.duration}</span>
                  )}
                </div>
                <div style={{ marginTop: 16 }}>
                  <a href="#drafts" style={{
                    display: 'inline-flex', alignItems: 'center', gap: 5,
                    padding: '7px 16px', borderRadius: 'var(--radius-sm)',
                    background: 'var(--primary)', color: '#fff',
                    textDecoration: 'none', fontSize: 13, fontWeight: 600,
                  }}>Open draft</a>
                </div>
              </div>
            )}

            {!firstLoad && !d.lead && (
              <div className="card" style={{
                padding: '28px 26px', textAlign: 'center',
                borderTop: '3px solid var(--rule)',
              }}>
                <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.4 }}>&#128270;</div>
                <div style={{
                  fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
                  color: 'var(--ink)', marginBottom: 8,
                }}>Nothing in the spotlight yet</div>
                <p style={{
                  fontSize: 13.5, color: 'var(--ink-2)', lineHeight: 1.55,
                  maxWidth: 300, margin: '0 auto 18px',
                }}>
                  When Lighthouse surfaces a notable finding, it will appear here
                  as your lead story.
                </p>
                <a href="#jobs" style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '8px 18px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--primary)', color: '#fff',
                  textDecoration: 'none', fontSize: 13, fontWeight: 600,
                }}>Start first research job</a>
              </div>
            )}

            {/* Calibration panel */}
            <div className="card" style={{ padding: '20px 24px' }}>
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                marginBottom: 14,
              }}>
                <div className="small-caps" style={{ color: 'var(--muted)' }}>Calibration</div>
                <span style={{
                  fontSize: 11, color: 'var(--muted)', padding: '2px 8px',
                  background: 'var(--rule-soft)', borderRadius: 99,
                }} title="Brier 0.0 = perfect, 0.25 = random chance">
                  0.0 = perfect &middot; 0.25 = random
                </span>
              </div>

              <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end', marginBottom: 16 }}>
                <div>
                  <div style={{
                    fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase',
                    letterSpacing: '0.06em', marginBottom: 2,
                  }}>Brier score</div>
                  {firstLoad
                    ? <Skeleton h={36} w={80} />
                    : (
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                        <span className="num" style={{
                          fontSize: 36, fontWeight: 700,
                          color: brier != null && Number(brier) < 0.15 ? 'var(--green-dark)' : 'var(--ink)',
                        }}>{brier != null ? brier : '—'}</span>
                        <span style={{ fontSize: 12, color: 'var(--muted)' }}>lower = better</span>
                      </div>
                    )}
                </div>

                <div style={{ display: 'flex', gap: 18 }}>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>Resolved</div>
                    {firstLoad
                      ? <Skeleton h={22} w={40} />
                      : <span className="num" style={{ fontSize: 22, fontWeight: 600, color: 'var(--ink)' }}>{cal.resolved ?? '—'}</span>}
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>Pending</div>
                    {firstLoad
                      ? <Skeleton h={22} w={40} />
                      : <span className="num" style={{ fontSize: 22, fontWeight: 600, color: 'var(--ink)' }}>{cal.pending ?? '—'}</span>}
                  </div>
                </div>
              </div>

              {/* Sparkline placeholder — filled later if trend data exists */}
              {Array.isArray(cal.trend) && cal.trend.length > 1 ? (
                <div style={{ height: 40 }}>
                  {/* Inline SVG sparkline */}
                  {(function () {
                    const vals = cal.trend.map(Number);
                    const mn = Math.min(...vals);
                    const mx = Math.max(...vals) || 0.25;
                    const W = 260, H = 36;
                    const pts = vals.map((v, i) => {
                      const x = (i / (vals.length - 1)) * W;
                      const y = H - ((v - mn) / ((mx - mn) || 1)) * H;
                      return `${x},${y}`;
                    }).join(' ');
                    return (
                      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ overflow: 'visible' }}>
                        <polyline points={pts} fill="none" stroke="var(--sky)" strokeWidth="2"
                          strokeLinejoin="round" strokeLinecap="round" />
                      </svg>
                    );
                  })()}
                </div>
              ) : (
                <div style={{
                  height: 36, borderRadius: 'var(--radius-sm)',
                  background: 'var(--rule-soft)', display: 'flex',
                  alignItems: 'center', justifyContent: 'center',
                  fontSize: 11, color: 'var(--muted)',
                }}>Trend will appear as positions resolve</div>
              )}
            </div>

            {/* Budget bars */}
            {!firstLoad && (cloud.cap || tokens.cap) && (
              <div className="card" style={{ padding: '16px 22px' }}>
                <div className="small-caps" style={{ color: 'var(--muted)', marginBottom: 12 }}>Budget</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {cloud.cap && (
                    <BudgetBar label="Cloud spend" used={cloud.used} cap={cloud.cap} unit={cloud.period || ''} />
                  )}
                  {tokens.cap && (
                    <BudgetBar label="Tokens" used={tokens.used} cap={tokens.cap} unit={tokens.unit || ''} />
                  )}
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
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                marginBottom: 14,
              }}>
                <div className="small-caps" style={{ color: 'var(--muted)' }}>
                  Active jobs{running.length > 0 ? ` (${running.length})` : ''}
                </div>
                <a href="#jobs" style={{
                  fontSize: 12, color: 'var(--primary)', textDecoration: 'none', fontWeight: 600,
                }}>View all</a>
              </div>

              {firstLoad && (
                <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 4 }}>
                  {[0, 1, 2].map((i) => (
                    <div key={i} style={{
                      flexShrink: 0, width: 180, background: 'var(--paper)',
                      borderRadius: 'var(--radius)', padding: '12px 14px',
                    }}>
                      <Skeleton h={12} w="70%" />
                      <Skeleton h={10} w="55%" style={{ marginTop: 6 }} />
                      <Skeleton h={6} style={{ marginTop: 10, borderRadius: 99 }} />
                    </div>
                  ))}
                </div>
              )}

              {!firstLoad && running.length === 0 && (
                <div style={{ textAlign: 'center', padding: '24px 0' }}>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>
                    No jobs running right now
                  </div>
                  <a href="#jobs" style={{
                    display: 'inline-flex', alignItems: 'center', padding: '7px 16px',
                    borderRadius: 'var(--radius-sm)', background: 'var(--primary)',
                    color: '#fff', textDecoration: 'none', fontSize: 13, fontWeight: 600,
                  }}>New research</a>
                </div>
              )}

              {!firstLoad && running.length > 0 && (
                <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 6 }}>
                  {running.map((j) => {
                    const topic = (j.metadata && j.metadata.topic) || j.topic || `Job ${j.id}`;
                    const progress = typeof j.progress === 'number' ? Math.max(0, Math.min(1, j.progress)) : 0;
                    const pct = Math.round(progress * 100);
                    const eta = j.eta || (j.metadata && j.metadata.eta);
                    return (
                      <a key={j.id} href="#jobs" className="lh-job-card" style={{
                        flexShrink: 0, width: 190, textDecoration: 'none',
                        background: 'var(--paper)', borderRadius: 'var(--radius)',
                        padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8,
                        border: '1px solid var(--rule-soft)',
                      }}>
                        <div style={{
                          fontSize: 13, fontWeight: 600, color: 'var(--ink)',
                          display: '-webkit-box', WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical', overflow: 'hidden', lineHeight: 1.4,
                        }}>{topic}</div>
                        <ModeBadge mode={j.mode} />
                        <div>
                          <div style={{
                            height: 5, borderRadius: 99, background: 'var(--rule-soft)',
                            overflow: 'hidden', marginBottom: 4,
                          }}>
                            <div style={{
                              height: '100%', width: `${pct}%`,
                              background: 'var(--primary)', borderRadius: 99,
                              transition: 'width .4s ease',
                            }} />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--muted)' }}>
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

            {/* Monitor digest stream */}
            <div className="card" style={{ padding: '18px 22px' }}>
              <div className="small-caps" style={{ color: 'var(--muted)', marginBottom: 14 }}>
                Topic updates — last 24 h
              </div>

              {firstLoad && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} style={{ borderBottom: '1px solid var(--rule-soft)', paddingBottom: 12 }}>
                      <Skeleton h={10} w={120} />
                      <Skeleton h={14} style={{ marginTop: 6 }} />
                      <Skeleton h={14} w="80%" style={{ marginTop: 3 }} />
                    </div>
                  ))}
                </div>
              )}

              {!firstLoad && digest.length === 0 && (
                <div style={{ textAlign: 'center', padding: '20px 0' }}>
                  <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                    No topic activity yet.{' '}
                    <a href="#topics" style={{ color: 'var(--primary)' }}>Add a monitor topic</a>
                  </div>
                </div>
              )}

              {!firstLoad && digest.map((item, i) => (
                <div key={i} style={{
                  padding: '11px 0',
                  borderBottom: i < digest.length - 1 ? '1px solid var(--rule-soft)' : 'none',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 4 }}>
                    <span style={{
                      fontSize: 10, fontWeight: 700, color: 'var(--primary)',
                      textTransform: 'uppercase', letterSpacing: '0.07em',
                    }}>{String(item.topic || '').toUpperCase()}</span>
                    {item.wep && (
                      <ConfidencePill phrase={item.wep.phrase || item.wep} band={item.wep.band} />
                    )}
                  </div>
                  <div style={{
                    fontFamily: 'var(--serif)', fontSize: 13.5, color: 'var(--ink-2)',
                    lineHeight: 1.5,
                  }}>{item.delta}</div>
                  {item.srcs != null && (
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 3 }}>
                      <span className="num">{item.srcs}</span> source{item.srcs === 1 ? '' : 's'}
                    </div>
                  )}
                </div>
              ))}
            </div>

          </div>
        </div>
      </div>
    );
  }

  // ════════════════════════════ JOBS PAGE ══════════════════════════════════
  const JOB_MODES = ['Deep-Dive', 'QUC', 'Monitor', 'Debate', 'Digest'];
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

  function JobsPage({ toast }) {
    const { data, loading, error, reload } = useApi('/api/jobs', { pollMs: 10000 });
    const [tab, setTab] = useState('all');
    const [showNew, setShowNew] = useState(false);
    const [selId, setSelId] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);

    useEvents((name) => { if (name && name.indexOf('job.') === 0) reload(); });
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

    async function act(id, verb, e) {
      if (e) e.stopPropagation();
      try {
        await apiPost(`/api/jobs/${id}/${verb}`);
        reload();
        if (selId === id) apiGet(`/api/jobs/${id}`).then(setDetail).catch(() => {});
        toast.show(`Job ${verb}${verb.endsWith('e') ? 'd' : 'ed'}`, 'success');
      } catch (err) { toast.show(err.message, 'error'); }
    }

    const firstLoad = loading && !data;

    const tabs = JOBS_TABS.map((t) => ({ ...t, count: tabCounts[t.key] }));

    return (
      <div style={{ padding: PAD, maxWidth: 1100 }}>
        <PageHeader
          title="Research jobs"
          subtitle={firstLoad ? 'Loading…' : `${allJobs.length} total`}
          actions={
            <Btn onClick={() => setShowNew(true)} aria-label="Start a new research job">
              + New research
            </Btn>
          }
        />

        {/* Tab filter */}
        <div style={{ marginBottom: GAP }}>
          <TabBar
            tabs={tabs}
            active={tab}
            onChange={(k) => { setTab(k); setSelId(null); }}
          />
        </div>

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
            title={tab === 'all' ? 'No research jobs yet' : `No ${tab} jobs`}
            hint={
              tab === 'all'
                ? 'Lighthouse researches topics, monitors signals, and drafts findings for you.'
                : `You have no jobs in the "${tab}" state right now.`
            }
            action={
              tab === 'all'
                ? <Btn onClick={() => setShowNew(true)}>Start your first research job</Btn>
                : null
            }
          />
        )}

        {!firstLoad && visibleJobs.length > 0 && (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            {/* Table header */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 100px 110px 140px 90px',
              gap: 12, padding: '10px 18px',
              background: 'var(--paper)', borderBottom: '1px solid var(--rule)',
            }}>
              {['Topic', 'Mode', 'Status', 'Progress', 'ETA'].map((h) => (
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
              return (
                <div
                  key={j.id}
                  role="button"
                  tabIndex={0}
                  aria-pressed={isActive}
                  aria-label={`Job: ${topic}`}
                  className="lh-row-btn"
                  onClick={() => setSelId(isActive ? null : j.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelId(isActive ? null : j.id); } }}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 100px 110px 140px 90px',
                    gap: 12, padding: '13px 18px', alignItems: 'center',
                    borderTop: idx > 0 ? '1px solid var(--rule-soft)' : 'none',
                    background: isActive ? 'var(--sky-soft)' : 'var(--card)',
                  }}
                >
                  <div style={{
                    fontSize: 14, fontWeight: 600, color: 'var(--ink)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }} title={topic}>{topic}</div>
                  <div><ModeBadge mode={j.mode} /></div>
                  <div><StatusPill status={j.status} /></div>
                  <div>
                    <div style={{
                      height: 5, borderRadius: 99, background: 'var(--rule-soft)',
                      overflow: 'hidden', marginBottom: 3,
                    }}>
                      <div style={{
                        height: '100%', width: `${pct}%`,
                        background: j.status === 'done' || j.status === 'completed'
                          ? 'var(--green)' : 'var(--primary)',
                        borderRadius: 99, transition: 'width .4s',
                      }} />
                    </div>
                    <span className="num" style={{ fontSize: 10, color: 'var(--muted)' }}>{pct}%</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>{eta || '—'}</div>
                </div>
              );
            })}
          </div>
        )}

        {/* Detail side pane */}
        {selId != null && (
          <SidePane
            title={detail ? jobTopic(detail) : `Job ${selId}`}
            subtitle={detail ? `${detail.mode || ''} · ${detail.status || ''}` : 'Loading…'}
            onClose={() => setSelId(null)}
            footer={detail && (detail.status === 'running' || detail.status === 'paused' || detail.status === 'review' || detail.status === 'staged') ? (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {(detail.status === 'review' || detail.status === 'staged') && (
                  <>
                    <Btn kind="success" onClick={() => act(detail.id, 'approve')}>Approve</Btn>
                    <Btn kind="danger" onClick={() => act(detail.id, 'reject')}>Reject</Btn>
                  </>
                )}
                {detail.status === 'running' && (
                  <Btn kind="ghost" onClick={() => act(detail.id, 'pause')}>Pause</Btn>
                )}
                {detail.status === 'paused' && (
                  <Btn kind="ghost" onClick={() => act(detail.id, 'resume')}>Resume</Btn>
                )}
                {detail.status !== 'cancelled' && detail.status !== 'done' && detail.status !== 'completed' && (
                  <Btn kind="danger" onClick={() => act(detail.id, 'cancel')}>Cancel</Btn>
                )}
              </div>
            ) : null}
          >
            {detailLoading && !detail && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <Skeleton h={14} /><Skeleton h={14} w="80%" /><Skeleton h={14} w="60%" />
              </div>
            )}
            {detail && <JobDetail job={detail} />}
            {!detailLoading && !detail && (
              <div style={{ color: 'var(--muted)', fontSize: 13 }}>Could not load this job.</div>
            )}
          </SidePane>
        )}

        {showNew && (
          <NewJobModal
            toast={toast}
            onClose={() => setShowNew(false)}
            onCreated={() => { setShowNew(false); reload(); toast.show('Research job queued', 'success'); }}
          />
        )}
      </div>
    );
  }

  function JobDetail({ job }) {
    const meta = job.metadata || {};
    const calls = Array.isArray(job.model_calls) ? job.model_calls : [];
    const p = typeof meta.progress === 'number' ? Math.max(0, Math.min(1, meta.progress)) : null;
    const topic = jobTopic(job);
    return (
      <div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 18 }}>
          <StatusPill status={job.status} />
          <ModeBadge mode={job.mode} />
        </div>

        {p != null && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', fontSize: 11,
              color: 'var(--muted)', marginBottom: 5,
            }}>
              <span>Progress</span>
              <span className="num">{Math.round(p * 100)}%</span>
            </div>
            <div style={{ height: 8, borderRadius: 99, background: 'var(--rule-soft)', overflow: 'hidden' }}>
              <div style={{
                height: '100%', width: `${Math.round(p * 100)}%`,
                background: 'var(--primary)', borderRadius: 99, transition: 'width .4s',
              }} />
            </div>
          </div>
        )}

        <div className="small-caps" style={{ color: 'var(--muted)', marginBottom: 8 }}>Details</div>
        <LocalRow k="ID" v={job.id} />
        <LocalRow k="Topic" v={topic !== `Job ${job.id}` ? topic : '—'} />
        <LocalRow k="Mode" v={job.mode} />
        <LocalRow k="Depth" v={meta.depth || job.depth} />
        <LocalRow k="Status" v={job.status} />
        {job.created_at && <LocalRow k="Created" v={new Date(job.created_at).toLocaleString()} />}
        {job.updated_at && <LocalRow k="Updated" v={new Date(job.updated_at).toLocaleString()} />}
        {meta.step && <LocalRow k="Step" v={meta.step} />}
        {job.budget != null && <LocalRow k="Budget" v={`$${Number(job.budget).toFixed(4)}`} />}
        {job.error && <LocalRow k="Error" v={job.error} />}

        {calls.length > 0 && (
          <div>
            <div className="small-caps" style={{ color: 'var(--muted)', margin: '18px 0 8px' }}>
              Model calls ({calls.length})
            </div>
            {calls.map((c, i) => (
              <div key={c.id || i} style={{
                padding: '9px 0', borderBottom: '1px solid var(--rule-soft)', fontSize: 12.5,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                  <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{c.model || c.name || `Call ${i + 1}`}</span>
                  {c.tokens != null && (
                    <span className="num" style={{ color: 'var(--muted)' }}>{c.tokens} tok</span>
                  )}
                </div>
                {(c.purpose || c.role) && (
                  <div style={{ color: 'var(--ink-2)', marginTop: 2 }}>{c.purpose || c.role}</div>
                )}
                {c.cost_usd != null && (
                  <div className="num" style={{ color: 'var(--muted)', marginTop: 2 }}>
                    ${Number(c.cost_usd).toFixed(4)}
                  </div>
                )}
              </div>
            ))}
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
    const inputRef = useRef(null);
    useEffect(() => { if (inputRef.current) inputRef.current.focus(); }, []);

    async function submit(e) {
      if (e) e.preventDefault();
      if (!topic.trim()) { toast.show('Enter a topic first.', 'info'); return; }
      setBusy(true);
      try {
        await apiPost('/api/jobs', { mode, topic: topic.trim(), depth, sources });
        onCreated();
      } catch (err) {
        toast.show(err.message, 'error');
        setBusy(false);
      }
    }

    const modeDescriptions = {
      'Deep-Dive': 'Full research report with citations',
      'QUC':       'Quick answer with key sources',
      'Monitor':   'Ongoing topic surveillance',
      'Debate':    'Steelman multiple perspectives',
      'Digest':    'Curated summary of recent items',
    };

    return (
      <Modal title="New research job" onClose={onClose}>
        <form onSubmit={submit}>
          <LocalField label="Topic" htmlFor="nj-topic">
            <input
              id="nj-topic"
              ref={inputRef}
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="What should Lighthouse research?"
              style={inputStyle}
              aria-label="Research topic"
            />
          </LocalField>

          <LocalField label="Mode" htmlFor="nj-mode">
            <select
              id="nj-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              style={inputStyle}
              aria-label="Research mode"
            >
              {JOB_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            {modeDescriptions[mode] && (
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                {modeDescriptions[mode]}
              </div>
            )}
          </LocalField>

          <LocalField label="Depth" htmlFor="nj-depth">
            <select
              id="nj-depth"
              value={depth}
              onChange={(e) => setDepth(e.target.value)}
              style={inputStyle}
              aria-label="Research depth"
            >
              {JOB_DEPTHS.map((dp) => <option key={dp} value={dp}>{dp}</option>)}
            </select>
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
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--muted)' }}>
              <span>1</span><span>20</span>
            </div>
          </LocalField>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}>
            <Btn kind="ghost" type="button" onClick={onClose}>Cancel</Btn>
            <Btn type="submit" disabled={busy}>{busy ? 'Creating…' : 'Start research'}</Btn>
          </div>
        </form>
      </Modal>
    );
  }

  // ════════════════════════════ DRAFTS PAGE ════════════════════════════════
  const DRAFTS_TABS = [
    { key: 'staged',   label: 'Staged' },
    { key: 'approved', label: 'Approved' },
    { key: 'all',      label: 'All' },
  ];

  function DraftsPage({ toast }) {
    const { data, loading, error, reload } = useApi('/api/drafts', { pollMs: 10000 });
    const [tab, setTab] = useState('staged');
    const [selId, setSelId] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [rejecting, setRejecting] = useState(false);
    const [busy, setBusy] = useState(false);

    useEvents((name) => { if (name && name.indexOf('draft.') === 0) reload(); });
    useEffect(() => { if (error) toast.show(`Drafts failed to load: ${error}`, 'error'); }, [error]);

    const drafts = (data && Array.isArray(data.drafts)) ? data.drafts : [];
    const staged   = drafts.filter((d) => d && d.status === 'staged');
    const approved = drafts.filter((d) => d && (d.status === 'approved' || d.status === 'published'));

    const tabCounts = {
      staged:   staged.length,
      approved: approved.length,
      all:      drafts.length,
    };

    const visibleDrafts = tab === 'staged' ? staged
      : tab === 'approved' ? approved
      : drafts;

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
        toast.show('Draft approved and published', 'success');
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

    const tabs = DRAFTS_TABS.map((t) => ({ ...t, count: tabCounts[t.key] }));

    return (
      <div style={{ padding: PAD, maxWidth: 1100 }}>
        <PageHeader
          title="Drafts"
          subtitle={
            firstLoad ? 'Loading…'
              : staged.length === 0 ? 'No drafts awaiting review'
              : `${staged.length} awaiting your review`
          }
        />

        {/* Tab filter */}
        <div style={{ marginBottom: GAP }}>
          <TabBar
            tabs={tabs}
            active={tab}
            onChange={(k) => { setTab(k); setSelId(null); }}
          />
        </div>

        {/* Loading skeleton */}
        {firstLoad && (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            {[0, 1, 2, 3].map((i) => (
              <div key={i} style={{
                display: 'grid',
                gridTemplateColumns: '1fr 120px 80px 80px',
                gap: 12, padding: '14px 18px',
                borderTop: i ? '1px solid var(--rule-soft)' : 'none',
                alignItems: 'center',
              }}>
                <div>
                  <Skeleton h={14} w="65%" />
                  <Skeleton h={11} w="45%" style={{ marginTop: 5 }} />
                </div>
                <Skeleton h={20} w={100} r={99} />
                <Skeleton h={20} w={60} r={99} />
                <Skeleton h={12} w={60} />
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
            title={
              tab === 'staged' ? 'No drafts awaiting review'
                : tab === 'approved' ? 'No approved drafts yet'
                : 'No drafts yet'
            }
            hint={
              tab === 'staged'
                ? 'Research in progress will appear here once a job produces a draft for your approval.'
                : tab === 'approved'
                ? 'Approve a staged draft to see it here.'
                : 'When a research job finishes, its draft lands here.'
            }
            action={
              tab !== 'approved'
                ? <Btn onClick={() => { window.location.hash = 'jobs'; }}>Go to Jobs</Btn>
                : null
            }
          />
        )}

        {!firstLoad && visibleDrafts.length > 0 && (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            {/* Table header */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 130px 90px 90px 100px',
              gap: 12, padding: '10px 18px',
              background: 'var(--paper)', borderBottom: '1px solid var(--rule)',
            }}>
              {['Title / Topic', 'Confidence', 'Sources', 'Status', 'Created'].map((h) => (
                <div key={h} style={{
                  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
                  textTransform: 'uppercase', letterSpacing: '0.07em',
                }}>{h}</div>
              ))}
            </div>

            {visibleDrafts.map((d, idx) => {
              const isActive = selId === d.id;
              const title = d.title || `Draft ${d.id}`;
              const created = d.created_at
                ? new Date(d.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                : '—';
              const srcs = d.source_count != null ? d.source_count
                : Array.isArray(d.sources) ? d.sources.length : null;
              return (
                <div
                  key={d.id}
                  role="button"
                  tabIndex={0}
                  aria-pressed={isActive}
                  aria-label={`Draft: ${title}`}
                  className="lh-row-btn"
                  onClick={() => setSelId(isActive ? null : d.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelId(isActive ? null : d.id); } }}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 130px 90px 90px 100px',
                    gap: 12, padding: '13px 18px', alignItems: 'center',
                    borderTop: idx > 0 ? '1px solid var(--rule-soft)' : 'none',
                    background: isActive ? 'var(--sky-soft)' : 'var(--card)',
                  }}
                >
                  <div>
                    <div style={{
                      fontSize: 13.5, fontWeight: 600, color: 'var(--ink)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }} title={title}>{title}</div>
                    {d.topic && (
                      <div style={{
                        fontSize: 11, color: 'var(--muted)', marginTop: 2,
                        textTransform: 'uppercase', letterSpacing: '0.05em',
                      }}>{d.topic}</div>
                    )}
                  </div>
                  <div>
                    <ConfidencePill phrase={d.wep_phrase} band={d.wep_band} />
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--ink-2)' }}>
                    {srcs != null ? <span><span className="num">{srcs}</span> src{srcs === 1 ? '' : 's'}</span> : '—'}
                  </div>
                  <div><StatusPill status={d.status} /></div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>{created}</div>
                </div>
              );
            })}
          </div>
        )}

        {/* Detail side pane */}
        {selId != null && (
          <SidePane
            title={detail ? (detail.title || `Draft ${selId}`) : `Draft ${selId}`}
            subtitle={detail ? `${detail.topic || ''} · ${detail.status || ''}` : 'Loading…'}
            onClose={() => { setSelId(null); setRejecting(false); }}
            footer={detail && detail.status === 'staged' ? (
              <div style={{ display: 'flex', gap: 8 }}>
                <Btn kind="success" disabled={busy} onClick={() => approve(detail.id)} aria-label="Approve this draft">
                  {busy ? 'Working…' : 'Approve'}
                </Btn>
                <Btn kind="danger" disabled={busy} onClick={() => setRejecting(true)} aria-label="Reject this draft">
                  Reject
                </Btn>
              </div>
            ) : null}
          >
            {detailLoading && !detail && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Skeleton h={12} w={90} />
                <Skeleton h={24} w="70%" />
                <Skeleton h={14} />
                <Skeleton h={14} w="90%" />
                <Skeleton h={14} w="80%" />
              </div>
            )}
            {detail && <DraftReader draft={detail} />}
            {!detailLoading && !detail && (
              <div style={{ color: 'var(--muted)', fontSize: 13 }}>Could not load this draft.</div>
            )}
          </SidePane>
        )}

        {rejecting && detail && (
          <RejectModal
            toast={toast}
            busy={busy}
            onClose={() => setRejecting(false)}
            onReject={(reason) => reject(detail.id, reason)}
          />
        )}
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
            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8,
          }}>{draft.topic}</div>
        )}

        <h2 style={{
          fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 21,
          margin: '0 0 14px', color: 'var(--ink)', lineHeight: 1.3,
        }}>{draft.title || `Draft ${draft.id}`}</h2>

        {/* Metadata chips */}
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 10,
          alignItems: 'center', marginBottom: 18,
          paddingBottom: 14, borderBottom: '1px solid var(--rule-soft)',
        }}>
          <ConfidencePill phrase={draft.wep_phrase} band={draft.wep_band} />
          <StatusPill status={draft.status} />
          {sources != null && (
            <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>
              <span className="num">{sources}</span> source{sources === 1 ? '' : 's'}
            </span>
          )}
          {confidence != null && (
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>
              Confidence: <span className="num">{confidence}</span>
            </span>
          )}
          {draft.mode && <ModeBadge mode={draft.mode} />}
        </div>

        {/* Body */}
        {draft.body_html ? (
          <div
            className="lh-body-html"
            style={{
              fontFamily: 'var(--serif)', fontSize: 15, lineHeight: 1.65,
              color: 'var(--ink-2)',
            }}
            dangerouslySetInnerHTML={{ __html: draft.body_html }}
          />
        ) : (
          <div style={{ fontSize: 13, color: 'var(--muted)', fontStyle: 'italic' }}>
            This draft has no body content.
          </div>
        )}

        {/* Reject reason */}
        {draft.status === 'rejected' && (draft.reject_reason || draft.reason) && (
          <div style={{
            marginTop: 20, fontSize: 12.5, color: 'var(--coral-2)',
            borderTop: '1px solid var(--rule)', paddingTop: 14,
          }}>
            Rejected: {draft.reject_reason || draft.reason}
          </div>
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
      if (!reason.trim()) { toast.show('A brief reason helps improve the next draft.', 'info'); return; }
      onReject(reason.trim());
    }

    return (
      <Modal title="Reject draft" onClose={onClose}>
        <form onSubmit={submit}>
          <LocalField label="Reason" htmlFor="rj-reason">
            <input
              id="rj-reason"
              ref={inputRef}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. sources too thin, off-topic"
              style={inputStyle}
              aria-label="Rejection reason"
            />
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
              One line. This guides the next research attempt.
            </div>
          </LocalField>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
            <Btn kind="ghost" type="button" onClick={onClose}>Cancel</Btn>
            <Btn kind="danger" type="submit" disabled={busy}>{busy ? 'Rejecting…' : 'Reject draft'}</Btn>
          </div>
        </form>
      </Modal>
    );
  }

  Object.assign(window, { HomePage, JobsPage, DraftsPage });
})();
