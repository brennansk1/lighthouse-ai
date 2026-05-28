/* ========================================================================
   LIGHTHOUSE MARK — vector art (background + logo, with beam sweep)
   Shared between variations and the full app.
   ======================================================================== */

/**
 * <LighthouseMark size="160" beam mode="solid|line" tone="ink" />
 *   - mode "solid": filled silhouette + soft beam rays (matches style #1)
 *   - mode "line" : line-art version (alt for sidebar headers)
 *   - beam (bool) : animate a slow rotating beam underneath
 */
function LighthouseMark({ size = 160, mode = "solid", tone = "var(--navy)", beam = false, beamColor = "var(--beam)", opacity = 1 }) {
  const id = React.useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 200 200"
      xmlns="http://www.w3.org/2000/svg"
      style={{ opacity, display: 'block' }}
      aria-hidden="true"
    >
      <defs>
        <radialGradient id={`glow-${id}`} cx="50%" cy="38%" r="50%">
          <stop offset="0%"  stopColor={beamColor} stopOpacity="0.55" />
          <stop offset="60%" stopColor={beamColor} stopOpacity="0.06" />
          <stop offset="100%" stopColor={beamColor} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`beam-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={beamColor} stopOpacity="0.42" />
          <stop offset="100%" stopColor={beamColor} stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* radial halo */}
      {beam && <circle cx="100" cy="76" r="92" fill={`url(#glow-${id})`} />}

      {/* rotating beam cone */}
      {beam && (
        <g style={{ transformOrigin: '100px 76px', animation: 'beamSweep 9s linear infinite' }}>
          <path d="M100 76 L40 -10 L160 -10 Z" fill={`url(#beam-${id})`} />
        </g>
      )}

      {mode === 'solid' ? (
        <g fill={tone}>
          {/* base rocks */}
          <path d="M30 178 Q60 168 100 172 Q140 168 170 178 L170 188 L30 188 Z" opacity="0.85" />
          {/* lower tower (tapered) */}
          <path d="M82 174 L84 110 L116 110 L118 174 Z" />
          {/* gallery deck */}
          <rect x="78" y="106" width="44" height="6" />
          {/* lamp room */}
          <rect x="86" y="76" width="28" height="30" />
          {/* lamp glass — beacon red */}
          <rect x="89" y="80" width="22" height="20" fill="var(--beacon)" opacity="0.9" />
          {/* roof */}
          <path d="M82 76 L100 60 L118 76 Z" />
          {/* finial */}
          <rect x="98" y="50" width="4" height="12" />
          <circle cx="100" cy="48" r="3" />
          {/* stripe */}
          <rect x="84" y="138" width="32" height="10" fill="var(--paper)" opacity="0.5" />
          <rect x="83" y="158" width="34" height="10" fill="var(--paper)" opacity="0.5" />
        </g>
      ) : (
        <g fill="none" stroke={tone} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round">
          <path d="M30 178 Q60 168 100 172 Q140 168 170 178" opacity="0.6" />
          <path d="M82 174 L84 110 L116 110 L118 174 Z" />
          <line x1="84" y1="138" x2="116" y2="138" />
          <line x1="83" y1="158" x2="117" y2="158" />
          <rect x="78" y="106" width="44" height="6" />
          <rect x="86" y="76" width="28" height="30" />
          <rect x="89" y="80" width="22" height="20" stroke={tone === 'var(--navy)' ? 'var(--beacon)' : tone} fill="none" />
          <path d="M82 76 L100 60 L118 76 Z" />
          <line x1="100" y1="60" x2="100" y2="48" />
          <circle cx="100" cy="48" r="3" />
        </g>
      )}
    </svg>
  );
}

/**
 * Full-bleed background lighthouse — fixed, low opacity, parallaxes lightly
 * with scroll. Sits behind everything.
 */
function LighthouseBackground({ opacity = 0.045, side = 'right', beam = true }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        if (!ref.current) return;
        const y = window.scrollY || 0;
        ref.current.style.transform = `translateY(${y * 0.06}px)`;
      });
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => { window.removeEventListener('scroll', onScroll); cancelAnimationFrame(raf); };
  }, []);
  const style = {
    position: 'fixed',
    [side]: '-60px',
    bottom: '-40px',
    width: 'min(880px, 70vw)',
    height: 'min(880px, 70vw)',
    pointerEvents: 'none',
    opacity,
    zIndex: 0,
    filter: 'saturate(0.6)',
  };
  return (
    <div ref={ref} style={style}>
      <LighthouseMark size="100%" mode="solid" tone="var(--ink)" beam={beam} beamColor="var(--beam)" />
    </div>
  );
}

/* Beam sweep keyframes (kept here so any host page works) */
(function injectBeamCSS() {
  const id = '__lh_beam_kf';
  if (document.getElementById(id)) return;
  const s = document.createElement('style');
  s.id = id;
  s.textContent = `
    @keyframes beamSweep {
      0%   { transform: rotate(-40deg); }
      50%  { transform: rotate( 40deg); }
      100% { transform: rotate(-40deg); }
    }
    @keyframes beamSpin {
      from { transform: rotate(0deg); }
      to   { transform: rotate(360deg); }
    }
  `;
  document.head.appendChild(s);
})();

window.LighthouseMark = LighthouseMark;
window.LighthouseBackground = LighthouseBackground;
