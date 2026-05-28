// HOME — Variation B · "Watch console"
// Instrument-panel feel. 3 columns. Rotating beam from logo. Live log ticker.
// Slightly denser. More "tradecraft."

const { LighthouseMark: LHMark_B, BackgroundLighthouse: BG_B, Sidebar: Sidebar_B, MOCK: MOCK_B } = window;

function GaugeArc({ used, cap, label, unit = '', size = 88 }) {
  const pct = Math.min(used / cap, 1);
  const r = size / 2 - 8;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - pct);
  const color = pct > 0.9 ? 'var(--coral)' : pct > 0.7 ? '#c79a2a' : 'var(--sea)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} stroke="var(--rule)" strokeWidth="4" fill="none" />
        <circle cx={size/2} cy={size/2} r={r} stroke={color} strokeWidth="4" fill="none"
                strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round" style={{ transition: 'stroke-dashoffset 0.6s ease' }} />
      </svg>
      <div style={{ marginTop: -size/2 - 14, fontFamily: 'var(--mono)', fontSize: 16, fontWeight: 600, color: 'var(--ink)' }}>{used}{unit && <span style={{ fontSize: 10, color: 'var(--muted)' }}>{unit}</span>}</div>
      <div style={{ marginTop: size/2 + 8, fontSize: 10, color: 'var(--muted)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>{label} · /{cap}{unit}</div>
    </div>
  );
}

function HBar({ label, value, max, color = 'var(--sea)', n }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: 11 }}>
        <span style={{ color: 'var(--ink-2)', fontFamily: 'var(--serif)', fontSize: 13 }}>{label}</span>
        <span><span className="num" style={{ fontWeight: 500, color: 'var(--ink)' }}>{value.toFixed(2)}</span> <span style={{ color: 'var(--muted)' }}>n={n}</span></span>
      </div>
      <div style={{ height: 5, background: 'var(--rule-soft)', borderRadius: 1, marginTop: 4 }}>
        <div style={{ width: `${(value / max) * 100}%`, height: '100%', background: color, borderRadius: 1 }} />
      </div>
    </div>
  );
}

// scrolling live log ticker — events stream
function LiveTicker() {
  const events = [
    { t: '09:47:12', src: 'gov', msg: 'budget snapshot · cloud 17.42 / 40.00 USD' },
    { t: '09:46:51', src: 'job-7f2a', msg: 'tool: web.fetch(eur-lex.europa.eu) → 200 · 14.2 KB' },
    { t: '09:46:39', src: 'rag', msg: 'rerank · 47 chunks → 8 · qwen3-reranker-0.6b' },
    { t: '09:46:18', src: 'job-3e8b', msg: 'monitor poll · fred:DTWEXM · no delta' },
    { t: '09:45:54', src: 'verifier', msg: 'positions overdue: 4 · 1 escalated to human' },
    { t: '09:45:30', src: 'job-7f2a', msg: 'wep band updated 0.65–0.80 → 0.70–0.85' },
    { t: '09:45:09', src: 'archiver', msg: 'wayback SPN2 saved · semanticscholar.org/p/4Z9k' },
    { t: '09:44:47', src: 'sandbox', msg: 'pdf scan ok · qpdf clean · oletools no macros' },
  ];
  return (
    <div style={{ background: 'var(--ink)', color: 'var(--paper-2)', borderRadius: 10, padding: '12px 14px', fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.6, height: 188, overflow: 'hidden', position: 'relative', boxShadow: 'var(--shadow)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ color: 'var(--sky)', letterSpacing: '0.12em', textTransform: 'uppercase', fontSize: 10 }}>Live · SSE</span>
        <span style={{ color: 'var(--sky)', opacity: 0.6 }}>▌</span>
      </div>
      <div style={{ animation: 'drift 6s ease-in-out infinite' }}>
        {events.map((e, i) => (
          <div key={i} style={{ display: 'flex', gap: 10, opacity: 1 - i * 0.08 }}>
            <span style={{ color: 'var(--sky)' }}>{e.t}</span>
            <span style={{ color: 'var(--sand)', minWidth: 70 }}>{e.src}</span>
            <span style={{ color: 'var(--paper)' }}>{e.msg}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function HomeB() {
  const MOCK = window.useDashboard ? window.useDashboard() : window.MOCK;
  return (
    <div className="lh-page" style={{ display: 'flex' }}>
      <BG_B opacity={0.12} x="20%" y="15%" scale={1} />

      <Sidebar_B activeId="home" />

      <main style={{ flex: 1, padding: '28px 40px 24px', position: 'relative', overflow: 'hidden' }}>

        {/* corner mark with rotating beam */}
        <div style={{ position: 'absolute', top: 24, right: 32, display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ position: 'relative', width: 40, height: 56 }}>
            <LHMark_B size={40} withBeam beamRotating />
          </div>
        </div>

        {/* top strip — greeting + lead summary in compact form */}
        <header>
          <div style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 13, color: 'var(--muted)' }}>{MOCK_B.date}</div>
          <h1 style={{ fontFamily: 'var(--serif)', fontWeight: 500, fontSize: 30, margin: '4px 0 0', color: 'var(--ink)' }}>{MOCK_B.greeting}.</h1>
          <p style={{ fontFamily: 'var(--serif)', fontSize: 14, color: 'var(--ink-2)', margin: '6px 0 0', maxWidth: 720 }}>
            <span className="num" style={{ color: 'var(--muted)' }}>2</span> drafts staged, <span className="num" style={{ color: 'var(--muted)' }}>3</span> jobs running, <span className="num" style={{ color: 'var(--coral-2)' }}>3</span> alerts. The lead finding overnight is below.
          </p>
        </header>

        <div className="hairline" style={{ margin: '18px 0' }} />

        {/* main grid: 3 columns */}
        <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.3fr 1fr', gap: 24, marginBottom: 18 }}>
          {/* col 1: lead finding */}
          <section className="card" style={{ padding: 18, borderLeft: '4px solid var(--sand)' }}>
            <div className="small-caps" style={{ color: 'var(--coral-2)' }}>Lead · #7f2a9c</div>
            <h2 style={{ fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 21, lineHeight: 1.2, margin: '8px 0 10px', color: 'var(--ink)', textWrap: 'balance' }}>
              {MOCK_B.lead.title}
            </h2>
            <p style={{ fontFamily: 'var(--serif)', fontSize: 13, lineHeight: 1.5, color: 'var(--ink-2)', margin: 0 }}>
              {MOCK_B.lead.dek}
            </p>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
              <span className={`wep ${MOCK_B.lead.wep.class}`}>{MOCK_B.lead.wep.phrase}</span>
              <span style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>{MOCK_B.lead.wep.band}</span>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>·</span>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}><span className="num">{MOCK_B.lead.sources}</span> sources</span>
            </div>
            <div style={{ marginTop: 14, display: 'flex', gap: 8 }}>
              <button className="btn-primary" style={{ fontSize: 12, padding: '6px 14px' }}>Read draft</button>
              <button className="btn-ghost" style={{ fontSize: 12, padding: '6px 12px' }}>Evidence chain</button>
            </div>
          </section>

          {/* col 2: active jobs as cards */}
          <section>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
              <h3 style={{ fontFamily: 'var(--serif)', fontWeight: 600, fontSize: 16, margin: 0, color: 'var(--ink)' }}>Active jobs</h3>
              <span className="small-caps">Live</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {MOCK_B.jobs.map((j) => (
                <div key={j.id} className="card" style={{ padding: '10px 14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                      <span className={`pill ${j.status}`} style={{ flex: '0 0 auto' }}><span className="dot"></span>{j.status}</span>
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--muted)' }}>{j.mode}</span>
                    </div>
                    <span className="num" style={{ fontSize: 10, color: 'var(--muted)' }}>#{j.id} · {j.eta}</span>
                  </div>
                  <div style={{ fontFamily: 'var(--serif)', fontSize: 13, color: 'var(--ink)', marginTop: 4, lineHeight: 1.3 }}>{j.topic}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                    <div style={{ flex: 1, height: 3, background: 'var(--rule-soft)', borderRadius: 1 }}>
                      <div style={{ width: `${j.progress * 100}%`, height: '100%', background: j.status === 'review' ? 'var(--coral)' : j.status === 'queued' ? 'var(--muted)' : 'var(--sea)', borderRadius: 1 }} />
                    </div>
                    <span className="num" style={{ fontSize: 10, color: 'var(--muted)' }}>budget {Math.round(j.budget * 100)}%</span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* col 3: alerts + governor */}
          <section>
            <h3 style={{ fontFamily: 'var(--serif)', fontWeight: 600, fontSize: 16, margin: '0 0 8px', color: 'var(--ink)' }}>Alerts</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {MOCK_B.alerts.map((a, i) => (
                <div key={i} className="card" style={{ display: 'flex', gap: 10, padding: '10px 12px', background: a.kind === 'retraction' ? 'rgba(10,25,41,0.06)' : 'var(--card)' }}>
                  <div style={{ width: 3, alignSelf: 'stretch', background: a.kind === 'retraction' ? 'var(--coral)' : a.kind === 'budget' ? 'var(--sand)' : 'var(--primary)', borderRadius: 2 }} />
                  <div>
                    <div className="small-caps" style={{ color: a.kind === 'retraction' ? 'var(--coral-2)' : 'var(--muted)' }}>{a.kind}</div>
                    <div style={{ fontFamily: 'var(--serif)', fontSize: 12.5, color: 'var(--ink-2)', marginTop: 2 }}>{a.text}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* bottom row: live ticker + governor gauges + calibration */}
        <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr 1fr', gap: 24 }}>
          <section>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
              <h3 style={{ fontFamily: 'var(--serif)', fontWeight: 600, fontSize: 16, margin: 0, color: 'var(--ink)' }}>Telemetry</h3>
              <span className="small-caps">runtime.log</span>
            </div>
            <LiveTicker />
          </section>

          <section>
            <h3 style={{ fontFamily: 'var(--serif)', fontWeight: 600, fontSize: 16, margin: '0 0 14px', color: 'var(--ink)' }}>Governor</h3>
            <div style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'flex-start', padding: '6px 0' }}>
              <GaugeArc used={MOCK_B.budget.cloud.used} cap={MOCK_B.budget.cloud.cap} label="cloud · USD" />
              <GaugeArc used={MOCK_B.budget.tokens.used} cap={MOCK_B.budget.tokens.cap} label="tokens · today" unit="M" />
              <GaugeArc used={MOCK_B.budget.sandbox.used} cap={MOCK_B.budget.sandbox.cap} label="sandbox" unit="GB" />
            </div>
          </section>

          <section>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <h3 style={{ fontFamily: 'var(--serif)', fontWeight: 600, fontSize: 16, margin: 0, color: 'var(--ink)' }}>Calibration</h3>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}><span className="num">{MOCK_B.calibration.brier.toFixed(3)}</span> <span style={{ color: '#1d6a3a' }} className="num">▼{Math.abs(MOCK_B.calibration.delta).toFixed(3)}</span></span>
            </div>
            {MOCK_B.calibration.domains.map((d) => (
              <HBar key={d.d} label={d.d} value={d.brier} max={0.35} n={d.n}
                    color={d.brier < 0.20 ? '#1d6a3a' : d.brier < 0.25 ? 'var(--sea)' : 'var(--coral)'} />
            ))}
          </section>
        </div>
      </main>
    </div>
  );
}

window.HomeB = HomeB;
