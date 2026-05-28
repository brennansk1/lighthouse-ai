// HOME — Variation A · "Captain's bridge"
// Editorial newspaper layout. Big serif lead. Tufte-style margin calibration.
// Calm density. Two-column main grid with sidenote rail.

const { LighthouseMark, BackgroundLighthouse, BackgroundPattern, Sidebar, MOCK } = window;

function Sparkline({ values, w = 200, h = 36, color = 'var(--ink)', accent = 'var(--coral)' }) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = w / (values.length - 1);
  const pts = values.map((v, i) => [i * stepX, h - ((v - min) / range) * (h - 4) - 2]);
  const d = pts.map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`)).join(' ');
  const last = pts[pts.length - 1];
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <path d={d} fill="none" stroke={color} strokeWidth="1.2" />
      <circle cx={last[0]} cy={last[1]} r="2.6" fill={accent} />
      {/* baseline */}
      <line x1="0" y1={h - 2} x2={w} y2={h - 2} stroke="var(--rule-soft)" strokeWidth="0.5" />
    </svg>
  );
}

function WepBadge({ phrase, klass = 'likely', band }) {
  return (
    <span className={`wep ${klass}`} title={band ? `band ${band}` : ''}>
      {phrase}
    </span>
  );
}

function JobRow({ j }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '70px 1fr 110px 120px 90px',
      gap: 14, padding: '14px 0',
      borderBottom: '1px solid var(--rule-soft)',
      alignItems: 'center',
    }}>
      <span className="num" style={{ fontSize: 11, color: 'var(--muted)' }}>#{j.id}</span>
      <div>
        <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 500, color: 'var(--ink)' }}>{j.topic}</div>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
          <span>{j.mode}</span> · <span>{j.depth}</span> · ETA <span className="num">{j.eta}</span>
        </div>
      </div>
      <span className={`pill ${j.status}`}><span className="dot"></span>{j.status}</span>
      <div>
        <div style={{ height: 4, background: 'var(--rule-soft)', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ width: `${j.progress * 100}%`, height: '100%', background: j.status === 'review' ? 'var(--coral)' : 'var(--sea)' }} />
        </div>
        <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4, fontFamily: 'var(--mono)' }}>{Math.round(j.progress * 100)}%</div>
      </div>
      <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
        <button style={btnGhost}>⏸</button>
        <button style={btnGhost}>↗</button>
      </div>
    </div>
  );
}

const btnGhost = {
  background: 'transparent', border: '1px solid var(--rule)', color: 'var(--ink-2)',
  fontSize: 11, padding: '3px 7px', borderRadius: 3, cursor: 'pointer', fontFamily: 'var(--sans)',
};

const glass = {
  background: 'rgba(255, 255, 255, 0.55)',
  backdropFilter: 'blur(14px) saturate(1.4)',
  WebkitBackdropFilter: 'blur(14px) saturate(1.4)',
  border: '1px solid rgba(255, 255, 255, 0.7)',
  borderRadius: 14,
  boxShadow: '0 1px 2px rgba(10,42,68,0.06), 0 8px 24px rgba(10,42,68,0.08)',
};

function HomeA() {
  const MOCK = window.useDashboard ? window.useDashboard() : window.MOCK;
  return (
    <div className="lh-page" style={{ display: 'flex', position: 'relative' }}>
      {/* nautical wave pattern background */}
      <BackgroundPattern />

      <Sidebar activeId="home" glass />

      <main style={{ flex: 1, padding: '32px 48px 28px', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 18 }}>

        {/* masthead — glass module */}
        <header style={{ ...glass, padding: '16px 22px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div className="small-caps">Daily Bulletin · Vol. 14 · No. 213</div>
            <div style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 13, color: 'var(--ink-2)', marginTop: 4 }}>
              {MOCK.date} · 09:47 local
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <div className="small-caps" style={{ color: 'var(--ink-2)' }}>Brier 30d</div>
            <Sparkline values={MOCK.calibration.trend} w={140} h={28} />
            <span className="num" style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)' }}>{MOCK.calibration.brier.toFixed(3)}</span>
            <span className="num" style={{ fontSize: 11, color: 'var(--green-dark)' }}>▼ {Math.abs(MOCK.calibration.delta).toFixed(3)}</span>
          </div>
        </header>

        {/* lead story — glass module */}
        <article style={{ display: 'grid', gridTemplateColumns: '1fr 240px', gap: 16 }}>
          <div style={{ ...glass, padding: '20px 24px' }}>
            <div className="small-caps" style={{ color: 'var(--coral-2)' }}>Lead finding · Job 14d-resolved</div>
            <h1 style={{
              fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 32, lineHeight: 1.15,
              color: 'var(--ink)', margin: '8px 0 10px', textWrap: 'balance',
            }}>{MOCK.lead.title}</h1>
            <p style={{ fontFamily: 'var(--serif)', fontSize: 15, lineHeight: 1.55, color: 'var(--ink-2)', maxWidth: 640, margin: 0 }}>
              {MOCK.lead.dek}
            </p>
            <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginTop: 14, flexWrap: 'wrap' }}>
              <WepBadge phrase={MOCK.lead.wep.phrase} klass={MOCK.lead.wep.class} band={MOCK.lead.wep.band} />
              <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>WEP band <span className="num">{MOCK.lead.wep.band}</span></span>
              <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>·</span>
              <span style={{ fontSize: 12, color: 'var(--ink-2)' }}><span className="num">{MOCK.lead.sources}</span> sources, <span className="num">{MOCK.lead.duration}</span></span>
              <span style={{ flex: 1 }} />
              <button className="btn-primary">Read draft →</button>
            </div>
          </div>

          {/* Alerts rail — glass module */}
          <aside style={{ ...glass, padding: '16px 18px' }}>
            <div className="small-caps">Alerts</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 8 }}>
              {MOCK.alerts.map((a, i) => (
                <div key={i} style={{ fontFamily: 'var(--serif)', fontSize: 13, lineHeight: 1.4, color: 'var(--ink)' }}>
                  <div className="num" style={{ fontSize: 10, color: a.kind === 'retraction' ? 'var(--coral-2)' : 'var(--primary)', letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 700 }}>
                    {a.kind}
                  </div>
                  <div>{a.text}</div>
                  {a.topic && <div style={{ fontStyle: 'italic', fontSize: 11.5, color: 'var(--ink-2)' }}>↳ {a.topic}</div>}
                </div>
              ))}
            </div>
          </aside>
        </article>

        {/* two-column body: active jobs / digest — each glass */}
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16, flex: 1, minHeight: 0 }}>
          <section style={{ ...glass, padding: '16px 22px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <h2 style={{ fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 18, margin: 0, color: 'var(--ink)' }}>Active jobs</h2>
              <span className="small-caps">{MOCK.jobs.length} in flight · 1 staged</span>
            </div>
            <div style={{ marginTop: 4 }}>
              {MOCK.jobs.map((j) => <JobRow key={j.id} j={j} />)}
            </div>
          </section>

          <section style={{ ...glass, padding: '16px 22px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <h2 style={{ fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 18, margin: 0, color: 'var(--ink)' }}>Topic deltas — last 24h</h2>
              <a href="#" onClick={(e) => e.preventDefault()} style={{ fontSize: 11, color: 'var(--primary)', textDecoration: 'none', fontWeight: 600 }}>All topics →</a>
            </div>
            <div style={{ marginTop: 4 }}>
              {MOCK.digest.map((d, i) => (
                <div key={i} style={{ padding: '12px 0', borderBottom: i === MOCK.digest.length - 1 ? 'none' : '1px solid rgba(212,226,237,0.6)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <div style={{ fontFamily: 'var(--sans)', fontWeight: 700, fontSize: 11, color: d.alarm ? 'var(--coral-2)' : 'var(--primary)', letterSpacing: '0.08em' }}>{d.topic.toUpperCase()}</div>
                    <span style={{ fontSize: 10, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>{d.srcs} src</span>
                  </div>
                  <div style={{ fontFamily: 'var(--serif)', fontSize: 13.5, lineHeight: 1.45, color: 'var(--ink)', marginTop: 4 }}>{d.delta}</div>
                  <div style={{ marginTop: 6 }}><WepBadge phrase={d.wep.phrase} klass={d.wep.class} /></div>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* bottom strip: calibration — glass */}
        <section style={{ ...glass, padding: '14px 22px', display: 'flex', gap: 28, alignItems: 'center' }}>
          <div style={{ flex: '0 0 180px' }}>
            <div className="small-caps">Calibration by domain</div>
            <div style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 12, color: 'var(--ink-2)', marginTop: 4 }}>
              Brier, lower is better. <span className="num">{MOCK.calibration.resolved}</span> resolved, <span className="num">{MOCK.calibration.pending}</span> pending.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 30, flex: 1 }}>
            {MOCK.calibration.domains.map((dom) => (
              <div key={dom.d}>
                <div style={{ fontFamily: 'var(--serif)', fontSize: 13, color: 'var(--ink-2)' }}>{dom.d}</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                  <span className="num" style={{ fontSize: 22, fontWeight: 600, color: 'var(--ink)' }}>{dom.brier.toFixed(2)}</span>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>n={dom.n}</span>
                </div>
                <div style={{ width: 90, height: 3, background: 'rgba(212,226,237,0.7)', borderRadius: 2, marginTop: 4, position: 'relative' }}>
                  <div style={{ position: 'absolute', left: `${Math.min(dom.brier / 0.35, 1) * 100}%`, top: -3, width: 2, height: 9, background: dom.brier < 0.20 ? 'var(--green-dark)' : dom.brier < 0.25 ? 'var(--primary)' : 'var(--coral)' }} />
                </div>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

window.HomeA = HomeA;
