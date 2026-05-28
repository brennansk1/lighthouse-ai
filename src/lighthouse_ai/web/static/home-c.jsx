// HOME — Variation C · "Quiet harbor"
// Maximum restraint. A single editorial hero. Active jobs as a quiet ribbon.
// Faint, large lighthouse vector behind everything. Slow breathing animation.

const { LighthouseMark: LHMark_C, BackgroundLighthouse: BG_C, Sidebar: Sidebar_C, MOCK: MOCK_C } = window;

function DomDot({ d, brier, n }) {
  const color = brier < 0.20 ? '#1d6a3a' : brier < 0.25 ? 'var(--sea)' : 'var(--coral)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 64 }}>
      <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, marginBottom: 8 }} />
      <div style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--ink)', fontWeight: 500 }}>{brier.toFixed(2)}</div>
      <div style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>{d}</div>
    </div>
  );
}

function JobChip({ j }) {
  return (
    <div style={{
      flex: '1 1 0', minWidth: 0,
      padding: '14px 16px',
      borderLeft: '1px solid var(--rule)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span className={`pill ${j.status}`}><span className="dot"></span>{j.status}</span>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--muted)' }}>{j.mode}</span>
      </div>
      <div style={{ fontFamily: 'var(--serif)', fontSize: 13, lineHeight: 1.3, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
        {j.topic}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
        <div style={{ flex: 1, height: 2, background: 'var(--rule-soft)' }}>
          <div style={{ width: `${j.progress * 100}%`, height: '100%', background: j.status === 'review' ? 'var(--coral)' : 'var(--sea)' }} />
        </div>
        <span className="num" style={{ fontSize: 10, color: 'var(--muted)' }}>{j.eta}</span>
      </div>
    </div>
  );
}

function HomeC() {
  const MOCK = window.useDashboard ? window.useDashboard() : window.MOCK;
  return (
    <div className="lh-page" style={{ display: 'flex' }}>
      {/* very prominent but faint lighthouse vector, off-center right */}
      <BG_C opacity={0.22} x="18%" y="-6%" scale={1.15} />

      <Sidebar_C activeId="home" />

      <main style={{ flex: 1, padding: '40px 72px 28px', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>

        {/* date strip + minimal stats top-right */}
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div>
            <div className="small-caps">Today</div>
            <div style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 14, color: 'var(--muted)', marginTop: 2 }}>{MOCK_C.date}</div>
          </div>
          <div style={{ display: 'flex', gap: 32, alignItems: 'baseline' }}>
            <Stat n="3" label="running" />
            <Stat n="2" label="staged" />
            <Stat n="3" label="alerts" hot />
            <Stat n="0.183" label="Brier · 30d" mono />
          </div>
        </header>

        {/* hero centerpiece */}
        <section style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', maxWidth: 820, margin: '0 auto', padding: '40px 0', textAlign: 'left', animation: 'drift 8s ease-in-out infinite' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
            <div style={{ width: 28, height: 1, background: 'var(--coral)' }} />
            <span className="small-caps" style={{ color: 'var(--coral-2)' }}>The lead — resolved overnight</span>
          </div>

          <h1 style={{
            fontFamily: 'var(--serif)',
            fontWeight: 500,
            fontSize: 52,
            lineHeight: 1.08,
            letterSpacing: '-0.01em',
            color: 'var(--ink)',
            margin: '0 0 24px',
            textWrap: 'balance',
          }}>
            {MOCK_C.lead.title}
          </h1>

          <p style={{
            fontFamily: 'var(--serif)',
            fontSize: 18,
            lineHeight: 1.55,
            color: 'var(--ink-2)',
            margin: '0 0 26px',
            maxWidth: 680,
          }}>
            {MOCK_C.lead.dek}
          </p>

          <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap' }}>
            <span className={`wep ${MOCK_C.lead.wep.class}`} style={{ fontSize: 12, padding: '4px 10px' }}>
              {MOCK_C.lead.wep.phrase} · {MOCK_C.lead.wep.band}
            </span>
            <span style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 13, color: 'var(--muted)' }}>
              {MOCK_C.lead.topic} · <span className="num">{MOCK_C.lead.sources}</span> sources · <span className="num">{MOCK_C.lead.duration}</span> to resolution
            </span>
            <button className="btn-primary" style={{
              marginLeft: 'auto', padding: '12px 22px', fontSize: 14, borderRadius: 999,
            }}>Read the draft →</button>
          </div>
        </section>

        {/* spacer hairline */}
        <div className="hairline" style={{ marginTop: 8 }} />

        {/* quiet ribbon: 4 active jobs as horizontal chips */}
        <section style={{ display: 'flex', alignItems: 'stretch', borderBottom: '1px solid var(--rule)', minHeight: 96 }}>
          <div style={{ padding: '14px 16px 14px 0', width: 140 }}>
            <div className="small-caps">In flight</div>
            <div style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 12, color: 'var(--muted)', marginTop: 4, lineHeight: 1.4 }}>
              Four jobs underway. One staged for review.
            </div>
          </div>
          {MOCK_C.jobs.map((j) => <JobChip key={j.id} j={j} />)}
        </section>

        {/* bottom rail: calibration as a row of dots + a single quiet alert */}
        <section style={{ display: 'flex', alignItems: 'center', gap: 36, paddingTop: 18 }}>
          <div style={{ flex: '0 0 auto' }}>
            <div className="small-caps">Calibration</div>
            <div style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 11.5, color: 'var(--muted)', marginTop: 4 }}>
              Brier by domain, last 90d.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 28 }}>
            {MOCK_C.calibration.domains.map((d) => <DomDot key={d.d} d={d.d} brier={d.brier} n={d.n} />)}
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ width: 6, height: 6, borderRadius: 0, background: 'var(--coral)' }} />
            <div style={{ fontFamily: 'var(--serif)', fontSize: 13, color: 'var(--ink-2)' }}>
              <span className="num" style={{ color: 'var(--coral-2)' }}>2</span> sources retracted in last 24h <span style={{ color: 'var(--muted)' }}>·</span> <span style={{ fontStyle: 'italic' }}>mRNA cold-chain</span>
            </div>
            <a href="#" onClick={(e) => e.preventDefault()} style={{ fontSize: 12, color: 'var(--sea)', textDecoration: 'none', fontFamily: 'var(--serif)', fontStyle: 'italic' }}>review →</a>
          </div>
        </section>
      </main>
    </div>
  );
}

function Stat({ n, label, hot, mono }) {
  return (
    <div style={{ textAlign: 'right' }}>
      <div className={mono ? 'num' : ''} style={{ fontFamily: mono ? 'var(--mono)' : 'var(--serif)', fontSize: 22, fontWeight: 500, color: hot ? 'var(--coral-2)' : 'var(--ink)', lineHeight: 1 }}>{n}</div>
      <div style={{ fontSize: 10, color: 'var(--muted)', letterSpacing: '0.14em', textTransform: 'uppercase', marginTop: 5 }}>{label}</div>
    </div>
  );
}

window.HomeC = HomeC;
