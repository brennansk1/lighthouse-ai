// Tweaks app: wraps the design canvas and exposes font controls.
// Persists via the host EDITMODE block in Home Variations.html.

const { DesignCanvas: DC_T, DCSection: DCSec_T, DCArtboard: DCArt_T } = window;
const { HomeA: HA_T, HomeB: HB_T, HomeC: HC_T } = window;
const { useTweaks, TweaksPanel, TweakSection, TweakSelect, TweakSlider, TweakRadio, TweakButton } = window;
const { IconCtx, ICON_VARIANTS, LighthouseMark: LH_PREVIEW } = window;

const SERIF_OPTIONS = [
  { value: 'Source Serif 4', label: 'Source Serif 4' },
  { value: 'Lora', label: 'Lora' },
  { value: 'EB Garamond', label: 'EB Garamond' },
  { value: 'Spectral', label: 'Spectral' },
  { value: 'Crimson Pro', label: 'Crimson Pro' },
  { value: 'Libre Caslon Text', label: 'Libre Caslon' },
  { value: 'Cormorant Garamond', label: 'Cormorant' },
  { value: 'Playfair Display', label: 'Playfair Display' },
  { value: 'Newsreader', label: 'Newsreader' },
];

const SANS_OPTIONS = [
  { value: 'Inter', label: 'Inter' },
  { value: 'Inter Tight', label: 'Inter Tight' },
  { value: 'Work Sans', label: 'Work Sans' },
  { value: 'DM Sans', label: 'DM Sans' },
  { value: 'IBM Plex Sans', label: 'IBM Plex Sans' },
  { value: 'Manrope', label: 'Manrope' },
  { value: 'Public Sans', label: 'Public Sans' },
  { value: 'Space Grotesk', label: 'Space Grotesk' },
];

const MONO_OPTIONS = [
  { value: 'JetBrains Mono', label: 'JetBrains Mono' },
  { value: 'IBM Plex Mono', label: 'IBM Plex Mono' },
  { value: 'Fira Code', label: 'Fira Code' },
  { value: 'Space Mono', label: 'Space Mono' },
  { value: 'Geist Mono', label: 'Geist Mono' },
];

const DEFAULTS = window.TWEAK_DEFAULTS;

function App() {
  const [t, setTweak] = useTweaks(DEFAULTS);

  // Apply tweaks live by overriding CSS variables on :root
  React.useEffect(() => {
    const r = document.documentElement.style;
    r.setProperty('--serif', `'${t.serifFamily}', Georgia, serif`);
    r.setProperty('--sans',  `'${t.sansFamily}', system-ui, sans-serif`);
    r.setProperty('--mono',  `'${t.monoFamily}', ui-monospace, monospace`);
    r.setProperty('--scale', String(t.scale));
  }, [t.serifFamily, t.sansFamily, t.monoFamily, t.scale]);

  // Inject a font-scale stylesheet that multiplies all rendered sizes via zoom
  // (kept tiny — only applied to .lh-page contents, leaves canvas chrome alone)
  const scaleStyle = `
    .lh-page { font-size: calc(16px * ${t.scale}); zoom: ${t.scale}; }
  `;

  return (
    <IconCtx.Provider value={t.iconStyle || 'capecod'}>
      <style>{scaleStyle}</style>
      <DC_T title="Lighthouse — Home" subtitle="Three directions for the dashboard landing page. Pick one and I'll build the full 15-page app from it.">
        <DCSec_T id="home" title="Home page · variations" subtitle="Same data, three visual languages. Tweak fonts via the panel — try a few combinations before committing.">
          <DCArt_T id="a" label="A · Captain's bridge" width={1440} height={900}><HA_T /></DCArt_T>
          <DCArt_T id="b" label="B · Watch console" width={1440} height={900}><HB_T /></DCArt_T>
          <DCArt_T id="c" label="C · Quiet harbor" width={1440} height={900}><HC_T /></DCArt_T>
        </DCSec_T>
      </DC_T>

      <TweaksPanel title="Tweaks · Typography">
        <TweakSection label="Lighthouse icon" />
        <TweakSelect
          label="Style"
          value={t.iconStyle || 'capecod'}
          options={Object.entries(ICON_VARIANTS).map(([value, label]) => ({ value, label }))}
          onChange={(v) => setTweak('iconStyle', v)}
        />
        {/* preview row — 5 icons at fixed size */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', padding: '6px 4px 10px', gap: 4 }}>
          {Object.keys(ICON_VARIANTS).map((v) => {
            const selected = (t.iconStyle || 'capecod') === v;
            return (
              <button
                key={v}
                type="button"
                onClick={() => setTweak('iconStyle', v)}
                title={ICON_VARIANTS[v]}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
                  padding: '6px 4px',
                  background: selected ? 'rgba(2,136,209,0.12)' : 'transparent',
                  border: selected ? '1.5px solid #0288d1' : '1.5px solid transparent',
                  borderRadius: 6, cursor: 'pointer', flex: 1, minWidth: 0,
                }}
              >
                <LH_PREVIEW size={28} variant={v} />
                <span style={{ fontSize: 9, color: '#0a2a44', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>
                  {v}
                </span>
              </button>
            );
          })}
        </div>

        <TweakSection label="Body & display serif" />
        <TweakSelect
          label="Serif"
          value={t.serifFamily}
          options={SERIF_OPTIONS}
          onChange={(v) => setTweak('serifFamily', v)}
        />

        <TweakSection label="UI sans" />
        <TweakSelect
          label="Sans"
          value={t.sansFamily}
          options={SANS_OPTIONS}
          onChange={(v) => setTweak('sansFamily', v)}
        />

        <TweakSection label="Numeric & code mono" />
        <TweakSelect
          label="Mono"
          value={t.monoFamily}
          options={MONO_OPTIONS}
          onChange={(v) => setTweak('monoFamily', v)}
        />

        <TweakSection label="Scale" />
        <TweakSlider
          label="Type scale"
          value={t.scale}
          min={0.85}
          max={1.15}
          step={0.01}
          onChange={(v) => setTweak('scale', v)}
        />

        <TweakSection label="Quick combos" />
        <TweakButton
          label="Editorial (default)"
          onClick={() => setTweak({ serifFamily: 'Source Serif 4', sansFamily: 'Inter', monoFamily: 'JetBrains Mono', scale: 1.0 })}
        />
        <TweakButton
          secondary
          label="Newspaper · Caslon + Plex"
          onClick={() => setTweak({ serifFamily: 'Libre Caslon Text', sansFamily: 'IBM Plex Sans', monoFamily: 'IBM Plex Mono', scale: 1.0 })}
        />
        <TweakButton
          secondary
          label="Modern · Newsreader + Grotesk"
          onClick={() => setTweak({ serifFamily: 'Newsreader', sansFamily: 'Space Grotesk', monoFamily: 'Space Mono', scale: 1.0 })}
        />
        <TweakButton
          secondary
          label="Classical · Garamond + Manrope"
          onClick={() => setTweak({ serifFamily: 'EB Garamond', sansFamily: 'Manrope', monoFamily: 'Fira Code', scale: 1.04 })}
        />
        <TweakButton
          secondary
          label="High-contrast · Playfair + DM"
          onClick={() => setTweak({ serifFamily: 'Playfair Display', sansFamily: 'DM Sans', monoFamily: 'JetBrains Mono', scale: 0.98 })}
        />
      </TweaksPanel>
    </IconCtx.Provider>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
