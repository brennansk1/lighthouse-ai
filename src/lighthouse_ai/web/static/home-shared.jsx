// Shared components for all 3 Home variations.
// Lighthouse mark, sidebar nav, faint background, mock data.

const NAV = [
  { group: 'Today', items: [
    { id: 'home', label: 'Home', active: true },
    { id: 'jobs', label: 'Jobs', count: 4 },
    { id: 'drafts', label: 'Drafts', count: 2 },
  ]},
  { group: 'Library', items: [
    { id: 'topics', label: 'Topics', count: 14 },
    { id: 'sources', label: 'Sources' },
    { id: 'positions', label: 'Positions', count: 312 },
    { id: 'hypotheses', label: 'Hypotheses', count: 9 },
  ]},
  { group: 'Instruments', items: [
    { id: 'calibration', label: 'Calibration' },
    { id: 'governor', label: 'Governor' },
    { id: 'storage', label: 'Storage' },
    { id: 'skills', label: 'Skills', count: 47 },
    { id: 'perspectives', label: 'Perspectives' },
  ]},
  { group: 'System', items: [
    { id: 'doctor', label: 'Doctor' },
    { id: 'audit', label: 'Audit' },
    { id: 'settings', label: 'Settings' },
  ]},
];

// Context — which lighthouse silhouette to use across the app.
// Tweaks panel sets it; LighthouseMark reads it.
const IconCtx = React.createContext('capecod');

// Five lighthouse styles, all in the seaside (blue/navy/black) palette.
// Each is rendered inside a 40×56 viewBox so sizes are interchangeable.
const ICON_VARIANTS = {
  capecod: 'Cape Cod (Nauset)',
  striped: 'Striped (Hatteras)',
  slim:    'Slim tower (Portland Head)',
  pier:    'Pier light (Brant Point)',
  modern:  'Modern geometric',
};

function IconCapeCod({ withBeam, beamRotating }) {
  return (
    <>
      {withBeam && (
        <g style={{ transformOrigin: '20px 16px', animation: beamRotating ? 'beam 6s ease-in-out infinite' : 'none' }}>
          <path d="M20 16 L4 4 L4 28 Z" fill="var(--sand)" opacity="0.55" />
        </g>
      )}
      <path d="M7 53 L33 53 L31 49 L9 49 Z" fill="var(--ink)" />
      <path d="M11 49 L29 49 L25.5 23 L14.5 23 Z" fill="#ffffff" stroke="var(--ink)" strokeWidth="0.6" strokeLinejoin="round" />
      <rect x="13.5" y="20.5" width="13" height="2.6" fill="#ffffff" stroke="var(--ink)" strokeWidth="0.5" />
      <rect x="13" y="19.2" width="14" height="1.4" fill="var(--ink)" />
      <rect x="14.5" y="13" width="11" height="6.2" fill="var(--coral)" stroke="var(--ink)" strokeWidth="0.5" />
      <line x1="17.5" y1="13.5" x2="17.5" y2="18.8" stroke="var(--ink)" strokeWidth="0.4" />
      <line x1="20" y1="13.5"   x2="20"   y2="18.8" stroke="var(--ink)" strokeWidth="0.4" />
      <line x1="22.5" y1="13.5" x2="22.5" y2="18.8" stroke="var(--ink)" strokeWidth="0.4" />
      <rect x="15.5" y="14" width="9" height="4" fill="var(--sand)" opacity="0.55" />
      <path d="M14 13 Q20 7 26 13 Z" fill="var(--ink)" />
      <rect x="19.6" y="4.5" width="0.8" height="3" fill="var(--ink)" />
      <circle cx="20" cy="4" r="1.1" fill="var(--ink)" />
    </>
  );
}

function IconStriped({ withBeam, beamRotating }) {
  // Cape-Hatteras-style straight cylinder with horizontal navy bands.
  return (
    <>
      {withBeam && (
        <g style={{ transformOrigin: '20px 12px', animation: beamRotating ? 'beam 6s ease-in-out infinite' : 'none' }}>
          <path d="M20 12 L4 0 L4 24 Z" fill="var(--sand)" opacity="0.55" />
        </g>
      )}
      {/* plinth */}
      <rect x="10" y="50" width="20" height="3" fill="var(--ink)" />
      <rect x="11" y="48" width="18" height="2" fill="var(--ink)" />
      {/* cylinder body — straight, not tapered */}
      <rect x="13" y="14" width="14" height="34" fill="#ffffff" stroke="var(--ink)" strokeWidth="0.6" />
      {/* navy bands */}
      <rect x="13" y="20" width="14" height="5" fill="var(--ink)" />
      <rect x="13" y="32" width="14" height="5" fill="var(--ink)" />
      <rect x="13" y="44" width="14" height="4" fill="var(--ink)" />
      {/* gallery + lantern */}
      <rect x="12" y="12" width="16" height="2" fill="var(--ink)" />
      <rect x="14.5" y="6" width="11" height="6" fill="var(--coral)" stroke="var(--ink)" strokeWidth="0.5" />
      <rect x="15.5" y="7" width="9" height="4" fill="var(--sand)" opacity="0.55" />
      {/* dome */}
      <path d="M14 6 Q20 1 26 6 Z" fill="var(--ink)" />
      <circle cx="20" cy="0.5" r="1" fill="var(--ink)" />
    </>
  );
}

function IconSlim({ withBeam, beamRotating }) {
  // Slim, steeply-tapered tower with an attached keeper's cottage at the base.
  return (
    <>
      {withBeam && (
        <g style={{ transformOrigin: '22px 14px', animation: beamRotating ? 'beam 6s ease-in-out infinite' : 'none' }}>
          <path d="M22 14 L6 2 L6 26 Z" fill="var(--sand)" opacity="0.55" />
        </g>
      )}
      {/* keeper's cottage — attached at base, left side */}
      <path d="M2 41 L13 41 L9 36 L6 36 Z" fill="var(--ink)" />
      <rect x="3" y="41" width="9" height="10" fill="#ffffff" stroke="var(--ink)" strokeWidth="0.6" />
      <rect x="5.5" y="44" width="2.5" height="3" fill="var(--ink)" />
      <rect x="9" y="44" width="2.5" height="3" fill="var(--ink)" />
      {/* plinth */}
      <path d="M14 52 L30 52 L28 49 L16 49 Z" fill="var(--ink)" />
      {/* steeply-tapered tower */}
      <path d="M16 49 L28 49 L24 17 L20 17 Z" fill="#ffffff" stroke="var(--ink)" strokeWidth="0.6" strokeLinejoin="round" />
      {/* gallery */}
      <rect x="17.5" y="15" width="9" height="1.4" fill="var(--ink)" />
      <rect x="18" y="16.4" width="8" height="1.5" fill="#ffffff" stroke="var(--ink)" strokeWidth="0.4" />
      {/* lantern */}
      <rect x="19" y="9" width="7" height="6" fill="var(--coral)" stroke="var(--ink)" strokeWidth="0.5" />
      <rect x="19.7" y="10" width="5.5" height="4" fill="var(--sand)" opacity="0.55" />
      <line x1="20.7" y1="9.5" x2="20.7" y2="14.5" stroke="var(--ink)" strokeWidth="0.3" />
      <line x1="22.5" y1="9.5" x2="22.5" y2="14.5" stroke="var(--ink)" strokeWidth="0.3" />
      <line x1="24.3" y1="9.5" x2="24.3" y2="14.5" stroke="var(--ink)" strokeWidth="0.3" />
      {/* dome */}
      <path d="M18.5 9 Q22.5 4 26.5 9 Z" fill="var(--ink)" />
      <rect x="22.1" y="1.5" width="0.8" height="3" fill="var(--ink)" />
      <circle cx="22.5" cy="1" r="1" fill="var(--ink)" />
    </>
  );
}

function IconPier({ withBeam, beamRotating }) {
  // Brant-Point-style stubby cylinder on pilings.
  return (
    <>
      {withBeam && (
        <g style={{ transformOrigin: '20px 22px', animation: beamRotating ? 'beam 6s ease-in-out infinite' : 'none' }}>
          <path d="M20 22 L4 12 L4 34 Z" fill="var(--sand)" opacity="0.55" />
        </g>
      )}
      {/* deck planks */}
      <rect x="6" y="51" width="28" height="1.4" fill="var(--ink)" />
      <rect x="5" y="49.5" width="30" height="1.6" fill="var(--ink)" opacity="0.7" />
      {/* pilings */}
      <rect x="8" y="49.5" width="1.4" height="6" fill="var(--ink)" />
      <rect x="13.5" y="49.5" width="1.4" height="6" fill="var(--ink)" />
      <rect x="25" y="49.5" width="1.4" height="6" fill="var(--ink)" />
      <rect x="30.5" y="49.5" width="1.4" height="6" fill="var(--ink)" />
      {/* stubby cylindrical tower */}
      <rect x="13" y="32" width="14" height="18" fill="#ffffff" stroke="var(--ink)" strokeWidth="0.6" />
      {/* one navy stripe across middle */}
      <rect x="13" y="40" width="14" height="3.5" fill="var(--ink)" />
      {/* gallery */}
      <rect x="12" y="30" width="16" height="2" fill="var(--ink)" />
      {/* lantern */}
      <rect x="14.5" y="22" width="11" height="8" fill="var(--coral)" stroke="var(--ink)" strokeWidth="0.5" />
      <rect x="15.5" y="23" width="9" height="6" fill="var(--sand)" opacity="0.55" />
      <line x1="17.5" y1="22.5" x2="17.5" y2="29.5" stroke="var(--ink)" strokeWidth="0.3" />
      <line x1="20" y1="22.5"   x2="20"   y2="29.5" stroke="var(--ink)" strokeWidth="0.3" />
      <line x1="22.5" y1="22.5" x2="22.5" y2="29.5" stroke="var(--ink)" strokeWidth="0.3" />
      {/* dome */}
      <path d="M14 22 Q20 16 26 22 Z" fill="var(--ink)" />
      <rect x="19.6" y="13" width="0.8" height="3" fill="var(--ink)" />
      <circle cx="20" cy="12.5" r="1.1" fill="var(--ink)" />
    </>
  );
}

function IconModern({ withBeam, beamRotating }) {
  // Bold geometric / friendly. Always shows three sunshine beams.
  return (
    <>
      {/* always-on geometric beams */}
      <g stroke="var(--sand)" strokeWidth="1.4" strokeLinecap="round" opacity="0.85" style={{
        transformOrigin: '20px 16px',
        animation: beamRotating ? 'beam 6s ease-in-out infinite' : 'none',
      }}>
        <line x1="20" y1="6" x2="20" y2="-1" />
        <line x1="14" y1="10" x2="6" y2="3" />
        <line x1="26" y1="10" x2="34" y2="3" />
      </g>
      {/* plinth */}
      <rect x="8" y="50" width="24" height="3" rx="1.2" fill="var(--ink)" />
      {/* bold tapered trapezoid tower */}
      <path d="M11 50 L29 50 L25 19 L15 19 Z" fill="var(--primary)" />
      {/* mid-band stripe */}
      <path d="M12.5 35 L27.5 35 L26.5 39 L13.5 39 Z" fill="var(--ink)" />
      {/* round porthole window */}
      <circle cx="20" cy="44" r="2.4" fill="var(--sand)" stroke="var(--ink)" strokeWidth="0.7" />
      {/* gallery */}
      <rect x="13" y="17" width="14" height="2.4" rx="0.8" fill="var(--ink)" />
      {/* lantern (rounded) */}
      <rect x="15" y="9" width="10" height="8" rx="1.5" fill="var(--ink)" />
      <circle cx="20" cy="13" r="2.4" fill="var(--sand)" />
      {/* dome */}
      <circle cx="20" cy="8" r="2" fill="var(--ink)" />
    </>
  );
}

const ICON_RENDERERS = {
  capecod: IconCapeCod,
  striped: IconStriped,
  slim:    IconSlim,
  pier:    IconPier,
  modern:  IconModern,
};

// LighthouseMark — picks the variant from context (or explicit prop override).
function LighthouseMark({ size = 28, withBeam = false, beamRotating = false, opacity = 1, variant }) {
  const ctxVariant = React.useContext(IconCtx);
  const v = variant || ctxVariant || 'capecod';
  const Renderer = ICON_RENDERERS[v] || IconCapeCod;
  return (
    <svg width={size} height={size * (56/40)} viewBox="0 0 40 56" fill="none"
      role="img" aria-label="Lighthouse" style={{ opacity, flexShrink: 0 }}>
      <Renderer withBeam={withBeam} beamRotating={beamRotating} />
    </svg>
  );
}

// Big faint background — coastal illustration PNG, feathered into the page
function BackgroundLighthouse({ opacity = 0.18, x = '30%', y = '0%', scale = 1, rotate = 0 }) {
  return (
    <img
      src="assets/coastal-bg.png"
      alt=""
      style={{
        position: 'absolute', left: x, top: y,
        width: `${Math.round(72 * scale)}%`, height: 'auto',
        opacity, pointerEvents: 'none',
        transform: `rotate(${rotate}deg)`,
        // feather edges into the page background so there's no hard cut
        WebkitMaskImage:
          'radial-gradient(ellipse 70% 80% at 65% 50%, black 35%, transparent 85%)',
        maskImage:
          'radial-gradient(ellipse 70% 80% at 65% 50%, black 35%, transparent 85%)',
        userSelect: 'none',
      }}
      draggable={false}
    />
  );
}

function Sidebar({ activeId = 'home', glass = false }) {
  const glassStyles = glass ? {
    background: 'rgba(255, 255, 255, 0.55)',
    backdropFilter: 'blur(14px) saturate(1.4)',
    WebkitBackdropFilter: 'blur(14px) saturate(1.4)',
    borderRight: '1px solid rgba(255,255,255,0.7)',
    boxShadow: '1px 0 0 rgba(255,255,255,0.6), 4px 0 14px rgba(10,42,68,0.08)',
  } : {};
  return (
    <aside className="lh-side" style={glassStyles}>
      <div className="lh-brand">
        <LighthouseMark size={26} />
        <div>
          <div className="word">Lighthouse</div>
          <div className="sub">Research instrument</div>
        </div>
      </div>
      <div className="lh-nav">
        {NAV.map((g) => (
          <React.Fragment key={g.group}>
            <div className="group">{g.group}</div>
            {g.items.map((it) => (
              <a key={it.id} href="#" className={it.id === activeId ? 'active' : ''} onClick={(e) => e.preventDefault()}>
                <span>{it.label}</span>
                {it.count != null && <span className="count">{it.count}</span>}
              </a>
            ))}
          </React.Fragment>
        ))}
      </div>
      <div className="lh-foot">
        <div className="row"><span>Tier</span><span className="num">T3 · M-series</span></div>
        <div className="row"><span>Model</span><span className="num">qwen3-32b · local</span></div>
        <div className="row"><span>Uptime</span><span className="num">14d 03h</span></div>
      </div>
    </aside>
  );
}

// — Mock data shared across variations —
const MOCK = {
  date: 'Wednesday · 27 May 2026',
  greeting: 'Good morning, Ellis',
  lead: {
    title: 'Two preprints overturn the Hawking-Page transition timing in AdS₅ holography.',
    dek: 'A 14-day Bounded Deep-Dive resolved with three independent replications. The earlier consensus held since 2019. Confidence is unusually high — five sources at Tier-A, no contradicting evidence at Tier-B or better.',
    wep: { phrase: 'very likely', class: 'likely', band: '0.85–0.95' },
    topic: 'physics · holography',
    sources: 23,
    duration: '14d 02h',
  },
  jobs: [
    { id: '7f2a9c', mode: 'Deep-Dive', topic: 'EU AI Act — Article 6 amendments', status: 'running', progress: 0.62, eta: '~2h 14m', budget: 0.68, depth: 'Thorough' },
    { id: '3e8b41', mode: 'Monitor', topic: 'Federal Reserve discount-window data', status: 'running', progress: 0.34, eta: 'continuous', budget: 0.21, depth: 'Standard' },
    { id: 'a91d22', mode: 'Q-U-C', topic: 'What is the half-life of an ARM Cortex-M errata?', status: 'review', progress: 1.0, eta: 'staged', budget: 0.44, depth: 'Standard' },
    { id: '5c0f7e', mode: 'Debate', topic: 'Steelman: "RAG is a worse idea than fine-tuning."', status: 'queued', progress: 0, eta: 'after #7f2a', budget: 0, depth: 'Exhaustive' },
  ],
  digest: [
    { topic: 'EU AI Act', delta: 'New consolidated text published Tuesday. Article 6(2)(c) materially weakened.', wep: { phrase: 'highly likely', class: 'likely' }, srcs: 4 },
    { topic: 'mRNA cold-chain', delta: 'Three retractions propagated from PubMed; two affected your active hypothesis H-038.', wep: { phrase: 'certain', class: 'likely' }, srcs: 3, alarm: true },
    { topic: 'Logseq plugin API', delta: 'v0.10.13 ships breaking change to assets URI scheme. Migration note staged in #drafts.', wep: { phrase: 'likely', class: 'high' }, srcs: 2 },
    { topic: 'Carbon credit fraud', delta: 'Bloomberg + ProPublica investigations point to same broker. Position P-1142 advanced to evidence-rich.', wep: { phrase: 'likely', class: 'high' }, srcs: 7 },
  ],
  alerts: [
    { kind: 'retraction', text: '2 sources retracted in last 24h', topic: 'mRNA cold-chain' },
    { kind: 'budget', text: 'Monthly cloud budget at 71% on day 27/31' },
    { kind: 'resolution', text: '4 positions overdue for resolution', topic: 'fed-rate-cuts' },
  ],
  calibration: {
    brier: 0.183,
    delta: -0.014, // improving
    resolved: 312,
    pending: 41,
    domains: [
      { d: 'AI policy', brier: 0.14, n: 38 },
      { d: 'Physics', brier: 0.11, n: 22 },
      { d: 'Markets', brier: 0.27, n: 64 },
      { d: 'Bio',      brier: 0.18, n: 51 },
      { d: 'Law',      brier: 0.19, n: 47 },
    ],
    // 30-day Brier trajectory, lower-is-better
    trend: [0.22, 0.21, 0.23, 0.22, 0.20, 0.21, 0.19, 0.20, 0.22, 0.21,
            0.20, 0.19, 0.18, 0.19, 0.20, 0.19, 0.18, 0.17, 0.19, 0.18,
            0.17, 0.18, 0.17, 0.18, 0.16, 0.17, 0.18, 0.17, 0.19, 0.183],
  },
  budget: {
    cloud: { used: 17.42, cap: 40.00, period: 'month' },
    tokens: { used: 2.9, cap: 8, period: 'today', unit: 'M' },
    sandbox: { used: 11, cap: 24, period: 'today', unit: 'GB' },
  },
};

// Repeating SVG pattern — stylized water waves / nautical contour lines.
// Used as a full-bleed page background under the glass modules.
function BackgroundPattern({ opacity = 1 }) {
  return (
    <div
      aria-hidden="true"
      style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden',
        background: 'linear-gradient(160deg, #d6ecf8 0%, #c8e4f4 45%, #b8dcf0 100%)',
        opacity,
      }}
    >
      {/* gentle radial sunlight glow top-right */}
      <div style={{
        position: 'absolute', inset: 0,
        background: 'radial-gradient(ellipse 60% 50% at 80% 0%, rgba(255,213,79,0.32), transparent 70%)',
      }} />
      {/* repeating wave pattern */}
      <svg
        width="100%" height="100%"
        style={{ position: 'absolute', inset: 0 }}
        preserveAspectRatio="none"
      >
        <defs>
          <pattern id="lh-waves" x="0" y="0" width="240" height="120" patternUnits="userSpaceOnUse">
            <path d="M0,30 Q60,10 120,30 T240,30" stroke="#0288d1" strokeWidth="1.1" fill="none" opacity="0.18" />
            <path d="M0,60 Q60,40 120,60 T240,60" stroke="#0288d1" strokeWidth="1.1" fill="none" opacity="0.14" />
            <path d="M0,90 Q60,70 120,90 T240,90" stroke="#0288d1" strokeWidth="1.1" fill="none" opacity="0.18" />
            <path d="M0,15 Q60,5  120,15 T240,15" stroke="#01579b" strokeWidth="0.6" fill="none" opacity="0.10" />
            <path d="M0,45 Q60,35 120,45 T240,45" stroke="#01579b" strokeWidth="0.6" fill="none" opacity="0.10" />
            <path d="M0,75 Q60,65 120,75 T240,75" stroke="#01579b" strokeWidth="0.6" fill="none" opacity="0.10" />
            <path d="M0,105 Q60,95 120,105 T240,105" stroke="#01579b" strokeWidth="0.6" fill="none" opacity="0.10" />
          </pattern>
          {/* secondary dot grid like a chart */}
          <pattern id="lh-dots" x="0" y="0" width="40" height="40" patternUnits="userSpaceOnUse">
            <circle cx="20" cy="20" r="0.6" fill="#01579b" opacity="0.18" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#lh-dots)" />
        <rect width="100%" height="100%" fill="url(#lh-waves)" />
      </svg>
      {/* compass rose lower-right */}
      <svg
        width="240" height="240" viewBox="0 0 100 100"
        style={{ position: 'absolute', right: '4%', bottom: '6%', opacity: 0.10 }}
      >
        <g stroke="#01579b" strokeWidth="0.4" fill="none">
          <circle cx="50" cy="50" r="46" />
          <circle cx="50" cy="50" r="34" />
          <circle cx="50" cy="50" r="22" />
        </g>
        <g stroke="#01579b" strokeWidth="0.5" opacity="0.7">
          <line x1="50" y1="2"  x2="50" y2="98" />
          <line x1="2"  y1="50" x2="98" y2="50" />
          <line x1="16" y1="16" x2="84" y2="84" />
          <line x1="84" y1="16" x2="16" y2="84" />
        </g>
        <g fill="#01579b" opacity="0.6" fontFamily="'Playfair Display', serif" fontSize="6" fontStyle="italic" textAnchor="middle">
          <text x="50" y="10">N</text>
          <text x="92" y="52">E</text>
          <text x="50" y="96">S</text>
          <text x="8"  y="52">W</text>
        </g>
        {/* N arrow */}
        <path d="M50,14 L46,28 L50,24 L54,28 Z" fill="#0288d1" opacity="0.8" />
      </svg>
    </div>
  );
}

// ── live dashboard hook (Sprint 21) ───────────────────────────────────
//
// React side gets MOCK as the bootstrap value; once mounted, /api/dashboard
// is fetched and any fields the server populates overlay MOCK (deep-merge
// per key). On fetch failure we keep the previous value so the preview
// still renders offline. Variants opt into live data by shadowing the
// module-level MOCK with `const MOCK = window.useDashboard();` at the top
// of their component function.

function _deepMergeLive(base, overlay) {
  // Server may legitimately send null for sections it hasn't populated
  // yet — treat null as "use the MOCK fallback".
  if (overlay == null) return base;
  if (typeof overlay !== 'object' || Array.isArray(overlay)) return overlay;
  const out = Array.isArray(base) ? base.slice() : Object.assign({}, base);
  for (const k of Object.keys(overlay)) {
    out[k] = _deepMergeLive(base ? base[k] : undefined, overlay[k]);
  }
  return out;
}

function useDashboard(intervalMs = 10000) {
  const [data, setData] = React.useState(MOCK);
  React.useEffect(() => {
    let cancelled = false;
    let timer = null;
    async function load() {
      try {
        const res = await fetch('/api/dashboard');
        if (!res.ok) return;
        const body = await res.json();
        if (cancelled) return;
        setData(_deepMergeLive(MOCK, body));
      } catch (err) {
        // network/dev-server error — keep the last good data
      }
    }
    load();
    timer = setInterval(load, intervalMs);
    return () => { cancelled = true; if (timer) clearInterval(timer); };
  }, [intervalMs]);
  return data;
}

Object.assign(window, { LighthouseMark, BackgroundLighthouse, BackgroundPattern,
  Sidebar, NAV, MOCK, IconCtx, ICON_VARIANTS, useDashboard });
