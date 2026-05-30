// app.jsx — production Lighthouse dashboard shell. Mounts into #root.
// Owns: 7-item sidebar, hash router, command palette (Cmd-K), shortcut
// overlay (?), React error boundary, light/dark theme toggle, live-region
// toasts from the SSE channel, and the page background. All page components
// (HomePage … SettingsPage) and primitives/hooks come from sibling files
// hung on window.* (no bundler — one shared browser global scope).
//
// The whole file is wrapped in an IIFE so its top-level declarations
// (the React-hook destructure, App, AppSidebar, …) stay function-scoped and
// do NOT collide with the identical `const {useState}=React` in app-lib.jsx
// when the browser executes every <script> in the same global scope.

(function () {
const { useState, useEffect, useCallback, useRef } = React;

// Monochrome line-icon set (Feather-style, viewBox 0 0 24 24). Each entry is
// the inner SVG markup; NavIcon wraps it so icons inherit currentColor and
// stay crisp at any size. No emoji, no external icon dependency.
const NAV_ICONS = {
  info:        '<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
  research:    '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  library:     '<path d="M4 19.5V5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-1.5z"/><line x1="9" y1="3" x2="9" y2="21"/>',
  watch:       '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/>',
  track:       '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
  activity:    '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  system:      '<path d="M2 3h20v14H2z"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  sandbox:     '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M9 4v5"/><path d="M9 20v-5"/>',
  settings:    '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
  pause:       '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
  play:        '<path d="M7 5l12 7-12 7V5z"/>',
  sun:         '<circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="4.2" y1="4.2" x2="5.6" y2="5.6"/><line x1="18.4" y1="18.4" x2="19.8" y2="19.8"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="4.2" y1="19.8" x2="5.6" y2="18.4"/><line x1="18.4" y1="5.6" x2="19.8" y2="4.2"/>',
  moon:        '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',
  alert:       '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  pin:         '<path d="M9 4h6l-1 6 3 3v2H7v-2l3-3-1-6z"/><line x1="12" y1="15" x2="12" y2="21"/>',
};

function NavIcon({ name, size = 16 }) {
  const inner = NAV_ICONS[name] || NAV_ICONS.info;
  return React.createElement('svg', {
    width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round',
    strokeLinejoin: 'round', 'aria-hidden': 'true',
    dangerouslySetInnerHTML: { __html: inner },
  });
}
window.NavIcon = NavIcon;

// Nav: Research (the landing page) leads, then the artifact-centric working
// pages. Library surfaces drafts awaiting review (staged counter). Track shows
// overdue positions; Activity shows in-flight runs. Info sits at the end near
// Health. Page ids are stable internal keys; labels are user-facing.
const APP_PAGES = [
  { id: 'research',  label: 'Research',  icon: 'research',  group: 'Work',   counter: 'jobs_running',  get C() { return window.ResearchPage; } },
  { id: 'library',   label: 'Library',   icon: 'library',   group: 'Work',   counter: 'drafts_staged', get C() { return window.LibraryPage; } },
  { id: 'watch',     label: 'Watch',     icon: 'watch',     group: 'Work',   get C() { return window.WatchPage; } },
  { id: 'track',     label: 'Track',     icon: 'track',     group: 'Work',   counter: 'positions_overdue', get C() { return window.TrackPage; } },
  { id: 'activity',  label: 'Activity',  icon: 'activity',  group: 'Work',   counter: 'jobs_running',  get C() { return window.ActivityPage; } },
  { id: 'sandbox',   label: 'Sandbox',   icon: 'sandbox',   group: 'System', get C() { return window.SandboxPage; } },
  { id: 'health',    label: 'Health',    icon: 'system',    group: 'System', get C() { return window.HealthPage; } },
  { id: 'info',      label: 'Info',      icon: 'info',      group: 'System', get C() { return window.InfoPage; } },
  { id: 'settings',  label: 'Settings',  icon: 'settings',  group: 'System', get C() { return window.SettingsPage; } },
];

// Research is always the landing page; an explicit #hash always wins.
function currentPage() {
  const raw = (window.location.hash || '').replace('#', '').replace('/', '');
  if (raw && APP_PAGES.find((p) => p.id === raw)) return raw;
  return 'research';
}

// ── Dark theme: a deep-navy variant of the coastal palette, injected as a
// data-theme override block so the <head> <style> stays untouched. ─────────
const DARK_CSS = `
[data-theme="dark"] {
  --paper: #0a1f33;
  --paper-2: #0c2540;
  --card: #102d4a;
  --ink: #e7f1fa;
  --ink-2: #a9c6e0;
  --primary: #4ec3f7;
  --primary-dark: #0288d1;
  --sea: #4ec3f7;
  --sky: #4ec3f7;
  --sky-soft: #16395c;
  --sand: #ffd54f;
  --sand-2: #3a3618;
  --coral: #4ec3f7;
  --coral-2: #4ec3f7;
  --green: #06d6a0;
  --green-dark: #2fe0b6;
  --muted: #7fa3c4;
  --rule: #1d3f63;
  --rule-soft: #16334f;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.35);
  --shadow: 0 1px 3px rgba(0,0,0,0.4), 0 4px 12px rgba(0,0,0,0.35);
  --shadow-lg: 0 4px 8px rgba(0,0,0,0.45), 0 12px 32px rgba(0,0,0,0.45);
}
html[data-theme="dark"], [data-theme="dark"] body { background: #061322; }
[data-theme="dark"] .lh-page {
  background: linear-gradient(180deg, #0a1f33 0%, #08182a 100%);
}
[data-theme="dark"] .lh-side {
  box-shadow: 1px 0 0 var(--rule), 2px 0 8px rgba(0,0,0,0.4);
}
`;

// Inject the extra CSS (active bar + fade + tier chips) once.
(function ensureAppCSS() {
  if (typeof document === 'undefined') return;
  if (document.getElementById('lh-app-extra-css')) return;
  const el = document.createElement('style');
  el.id = 'lh-app-extra-css';
  el.textContent = `
/* Sidebar nav links — flex row with icon + label + badge */
.lh-nav a {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
}
/* Active left-accent bar */
.lh-nav a.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 3px;
  border-radius: 0 2px 2px 0;
  background: var(--primary);
}

/* Page fade-in */
@keyframes lh-fade-in {
  from { opacity: 0; transform: translateY(5px); }
  to   { opacity: 1; transform: translateY(0); }
}
.lh-main-content {
  animation: lh-fade-in .15s ease;
}

/* Governor tier chip */
.lh-tier-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 10.5px;
  font-weight: 700;
  font-family: var(--mono, monospace);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.lh-tier-green       { background: rgba(6,214,160,0.15);  color: var(--green-dark, #06d6a0); }
.lh-tier-warn        { background: rgba(255,213,79,0.2);   color: #9e7b00; }
.lh-tier-degrade     { background: rgba(255,152,100,0.2);  color: #bf5820; }
.lh-tier-local_only  { background: rgba(106,138,166,0.15); color: var(--muted, #6a8aa6); }
.lh-tier-drain       { background: rgba(255,213,79,0.2);   color: #9e7b00; }
.lh-tier-tripped     { background: rgba(220,60,60,0.15);   color: #c03030; }
.lh-tier-unknown     { background: rgba(106,138,166,0.12); color: var(--muted, #6a8aa6); }

/* Command palette input reset */
.lh-palette-input:focus { outline: none; }
`;
  document.head && document.head.appendChild(el);
})();

function tierChipClass(tier) {
  if (!tier || tier === '—') return 'lh-tier-chip lh-tier-unknown';
  const t = String(tier).toLowerCase().replace(/[^a-z_]/g, '_');
  return `lh-tier-chip lh-tier-${t}`;
}

// Map internal governor tier keys to plain status words a first-timer reads:
// healthy → "OK", reduced/throttled → "Slow", anything stopped → "Problem".
function tierStatusWord(tier) {
  if (!tier || tier === '—') return '—';
  const t = String(tier).toLowerCase();
  if (t === 'green' || t === 'ok' || t === 'healthy') return 'OK';
  if (t === 'tripped' || t === 'error' || t === 'down') return 'Problem';
  if (t === 'local_only') return 'Offline';
  // warn / degrade / drain / reduced → the machine is fine but Lighthouse eased off
  return 'Slow';
}
window.tierStatusWord = tierStatusWord;

function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('lh-theme') || 'light'; } catch (e) { return 'light'; }
  });
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('lh-theme', theme); } catch (e) {}
  }, [theme]);
  const toggle = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), []);
  return { theme, toggle };
}

// ── Error boundary: one crashing page shows a friendly fallback. ───────────
class PageBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) {
    console.error('Page crashed:', error, info);
  }
  componentDidUpdate(prev) {
    if (prev.pageKey !== this.props.pageKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error) {
      const BtnComp = window.Btn;
      return (
        <div role="alert" style={{ ...window.card, padding: '40px 28px', maxWidth: 560,
          margin: '40px auto', textAlign: 'center' }}>
          <div style={{ marginBottom: 10, opacity: 0.6, display: 'flex', justifyContent: 'center' }}>
            <NavIcon name="alert" size={30} />
          </div>
          <div style={{ fontFamily: 'var(--serif)', fontSize: 19, color: 'var(--ink)' }}>
            This page hit a snag.
          </div>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 8, lineHeight: 1.5 }}>
            {String((this.state.error && this.state.error.message) || this.state.error)}
          </div>
          <div style={{ marginTop: 20 }}>
            {BtnComp
              ? <BtnComp kind="ghost" onClick={() => this.setState({ error: null })}>Try again</BtnComp>
              : <button className="btn-ghost" onClick={() => this.setState({ error: null })}>Try again</button>}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Sidebar ─────────────────────────────────────────────────────────────
// Global pause: stops all 24/7 background work (scheduled monitors, calibration,
// backups, job dispatch) so the user can use their machine for something else.
// Reflects + toggles supervisor_state via /api/control,/api/pause,/api/resume.
function GlobalPauseButton() {
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(() => {
    if (!window.apiGet) return;
    window.apiGet('/api/control')
      .then((d) => setPaused(!!(d && d.paused)))
      .catch(() => {});
  }, []);
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);
  const toggle = async () => {
    setBusy(true);
    try {
      if (paused) { await window.apiPost('/api/resume'); setPaused(false); }
      else { await window.apiPost('/api/pause', { hard: false }); setPaused(true); }
    } catch (e) { /* surface nothing fatal; refresh reflects truth */ }
    finally { setBusy(false); refresh(); }
  };
  return (
    <button onClick={toggle} disabled={busy} className="btn-ghost"
      style={{ width: '100%', padding: '6px 8px', fontSize: 11.5, marginBottom: 8,
        fontWeight: 600, display: 'inline-flex', alignItems: 'center',
        justifyContent: 'center', gap: 6,
        color: paused ? '#1a7f4b' : 'var(--ink)',
        borderColor: paused ? '#1a7f4b' : undefined }}
      title={paused
        ? 'Background work is paused — click to resume'
        : 'Pause all background work to free up your machine'}
      aria-pressed={paused}>
      <NavIcon name={paused ? 'play' : 'pause'} size={13} />
      <span>{paused ? 'Resume' : 'Pause all work'}</span>
    </button>
  );
}

function AppSidebar({ active, counters, theme, onToggleTheme, onHelp }) {
  const tier = counters.tier || '—';

  return (
    <aside className="lh-side">
      <div className="lh-brand">
        <window.LighthouseMark size={26} />
        <div>
          <div className="word">Lighthouse</div>
          <div className="sub">Research instrument</div>
        </div>
      </div>

      <nav className="lh-nav" aria-label="Primary">
        {APP_PAGES.map((p, i) => {
          const count = p.counter ? counters[p.counter] : null;
          const isActive = p.id === active;
          const showGroup = p.group && (i === 0 || APP_PAGES[i - 1].group !== p.group);
          return (
            <React.Fragment key={p.id}>
              {showGroup ? (
                <div className="lh-nav-group" aria-hidden="true" style={{
                  fontSize: 9.5, fontWeight: 700, letterSpacing: '0.08em',
                  textTransform: 'uppercase', color: 'var(--muted)',
                  padding: '10px 0 4px 8px', opacity: 0.7 }}>{p.group}</div>
              ) : null}
              <a href={`#${p.id}`} className={isActive ? 'active' : ''}
                aria-current={isActive ? 'page' : undefined}>
                {/* Icon cell — fixed width so labels align */}
                <span aria-hidden="true" style={{ width: 18, display: 'inline-flex',
                  justifyContent: 'center', flexShrink: 0 }}>
                  <NavIcon name={p.icon} />
                </span>
                {/* Label — expands to fill available space */}
                <span style={{ flex: 1 }}>{p.label}</span>
                {/* Count badge — stays on the right */}
                {count ? <span className="count">{count}</span> : null}
              </a>
            </React.Fragment>
          );
        })}
      </nav>

      <div className="lh-foot">
        {/* Your-computer status chip — plain word, not the internal tier key */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'center',
          gap: '4px 8px', marginBottom: 10 }}>
          <span style={{ fontSize: 10.5, color: 'var(--muted)', fontFamily: 'var(--sans)',
            textTransform: 'uppercase', letterSpacing: '0.05em' }}>Computer</span>
          <span className={tierChipClass(tier)}
            title="How smoothly Lighthouse is running on your computer">
            {tierStatusWord(tier)}
          </span>
        </div>

        {/* Theme toggle + help shortcut */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          <button onClick={onToggleTheme} className="btn-ghost"
            style={{ flex: 1, padding: '5px 8px', fontSize: 11.5,
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
            aria-label="Toggle light or dark theme" aria-pressed={theme === 'dark'}>
            <NavIcon name={theme === 'dark' ? 'moon' : 'sun'} size={13} />
            <span>{theme === 'dark' ? 'Dark' : 'Light'}</span>
          </button>
          <button onClick={onHelp} className="btn-ghost"
            style={{ padding: '5px 10px', fontSize: 11.5 }}
            aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">?</button>
        </div>

        {/* Global pause — free up the machine */}
        <GlobalPauseButton />

        {/* Version / identity line */}
        <div style={{ fontSize: 10, color: 'var(--muted)', textAlign: 'center',
          opacity: 0.7, letterSpacing: '0.02em' }}>
          v0.1.0 · local-first
        </div>
      </div>
    </aside>
  );
}

// ── Command palette (Cmd-K): fuzzy page jump. ──────────────────────────────
function fuzzy(query, label) {
  const q = query.toLowerCase().replace(/\s+/g, '');
  const l = label.toLowerCase();
  if (!q) return true;
  if (l.includes(q)) return true;
  let i = 0;
  for (const ch of l) { if (ch === q[i]) i++; if (i === q.length) return true; }
  return i === q.length;
}

function CommandPalette({ open, onClose, onGo }) {
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef(null);

  // Reset state and auto-focus + select-all when opening
  useEffect(() => {
    if (open) {
      setQ('');
      setSel(0);
      // Defer focus until after the render so the input is in the DOM
      requestAnimationFrame(() => {
        if (inputRef.current) {
          inputRef.current.focus();
          inputRef.current.select();
        }
      });
    }
  }, [open]);

  const matches = APP_PAGES.filter((p) => fuzzy(q, p.label));
  useEffect(() => { setSel(0); }, [q]);

  if (!open) return null;

  const commit = (id) => { if (id) { onGo(id); } onClose(); };
  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, matches.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); commit(matches[sel] && matches[sel].id); }
    else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
  };

  return (
    <div onClick={onClose} role="presentation" style={{ position: 'fixed', inset: 0, zIndex: 600,
      background: 'rgba(10,42,68,0.3)', display: 'flex', justifyContent: 'center', paddingTop: 120 }}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true"
        aria-label="Command palette" style={{ ...window.card, width: 420, height: 'fit-content',
        boxShadow: 'var(--shadow-lg)', overflow: 'hidden' }}>
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Go to page…"
          aria-label="Search pages"
          className="lh-palette-input"
          style={{ width: '100%', border: 'none', padding: '14px 16px', fontSize: 15,
            fontFamily: 'var(--sans)', outline: 'none', color: 'var(--ink)',
            background: 'var(--card)', boxSizing: 'border-box' }}
        />
        <div style={{ borderTop: '1px solid var(--rule)' }} role="listbox">
          {matches.length === 0 && (
            <div style={{ padding: '12px 16px', fontSize: 13, color: 'var(--muted)',
              fontFamily: 'var(--sans)' }}>No matches</div>
          )}
          {matches.map((p, i) => (
            <div key={p.id} role="option" aria-selected={i === sel}
              onMouseEnter={() => setSel(i)} onClick={() => commit(p.id)}
              style={{ padding: '10px 16px', cursor: 'pointer', fontSize: 13,
                fontFamily: 'var(--sans)', color: 'var(--ink)',
                background: i === sel ? 'var(--rule-soft)' : 'transparent',
                display: 'flex', alignItems: 'center', gap: 10 }}>
              <span aria-hidden="true" style={{ opacity: 0.75, width: 20,
                display: 'inline-flex', justifyContent: 'center', flexShrink: 0 }}>
                <NavIcon name={p.icon} /></span>
              <span style={{ flex: 1 }}>{p.label}</span>
            </div>
          ))}
        </div>
        {/* Keyboard hint row */}
        <div style={{ padding: '6px 16px 8px', borderTop: '1px solid var(--rule-soft)',
          fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--sans)', letterSpacing: '0.01em' }}>
          ↑↓ navigate · Enter jump · Esc close
        </div>
      </div>
    </div>
  );
}

// ── Shortcut overlay (?). ──────────────────────────────────────────────────
const SHORTCUTS = [
  ['⌘K / Ctrl-K', 'Open command palette'],
  ['?', 'Show this shortcut overlay'],
  ['Esc', 'Close palette / overlay'],
  ['↑ ↓ / Enter', 'Navigate & jump in palette'],
];

function ShortcutOverlay({ open, onClose }) {
  if (!open) return null;
  return (
    <div onClick={onClose} role="dialog" aria-modal="true" aria-label="Keyboard shortcuts"
      style={{ position: 'fixed', inset: 0, zIndex: 600, background: 'rgba(10,42,68,0.3)',
        display: 'flex', justifyContent: 'center', alignItems: 'flex-start', paddingTop: 140 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ ...window.card, width: 380,
        boxShadow: 'var(--shadow-lg)', padding: '18px 20px' }}>
        <div style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
          color: 'var(--ink)', marginBottom: 12 }}>Keyboard shortcuts</div>
        {SHORTCUTS.map(([k, d]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between',
            padding: '6px 0', fontSize: 13, fontFamily: 'var(--sans)', color: 'var(--ink-2)' }}>
            <span>{d}</span>
            <kbd className="num" style={{ background: 'var(--rule-soft)', padding: '2px 8px',
              borderRadius: 6, fontSize: 11.5, color: 'var(--ink)' }}>{k}</kbd>
          </div>
        ))}
      </div>
    </div>
  );
}

function App() {
  const [page, setPage] = useState(currentPage());
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [counters, setCounters] = useState({});
  const { toast, show } = window.useToast();
  const { theme, toggle } = useTheme();

  useEffect(() => {
    const onHash = () => setPage(currentPage());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // Keyboard: Cmd-K / Ctrl-K palette, ? overlay, Esc closes both.
  useEffect(() => {
    const onKey = (e) => {
      const typing = /input|textarea|select/i.test(e.target.tagName) || e.target.isContentEditable;
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault(); setHelpOpen(false); setPaletteOpen((o) => !o);
      } else if (e.key === 'Escape') {
        setPaletteOpen(false); setHelpOpen(false);
      } else if (e.key === '?' && !typing) {
        e.preventDefault(); setPaletteOpen(false); setHelpOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Live region: surface a toast on draft.staged / governor.tripped.
  window.useEvents(useCallback((name, data) => {
    if (name === 'draft.staged') {
      show(`New draft staged${data && data.title ? `: ${data.title}` : ''}`, 'info');
    } else if (name === 'governor.tripped') {
      show(`Governor tripped${data && data.reason ? `: ${data.reason}` : ' — work paused'}`, 'error');
    }
  }, [show]));

  // Sidebar counters from a light poll of health + dashboard, every 10s.
  const refreshCounters = useCallback(async () => {
    try {
      const [dash, health, drafts, pos, escs] = await Promise.all([
        window.apiGet('/api/dashboard').catch(() => ({})),
        window.apiGet('/api/health').catch(() => ({})),
        window.apiGet('/api/drafts?status=staged').catch(() => ({ drafts: [] })),
        window.apiGet('/api/positions?overdue=true').catch(() => ({ positions: [] })),
        window.apiGet('/api/escalations?status=open').catch(() => ({ escalations: [] })),
      ]);
      const running = (dash.jobs || []).filter((j) => j.status === 'running').length;
      const tier = (health.hardware && health.hardware.tier) || '—';
      setCounters({
        jobs_running: running || null,
        drafts_staged: (drafts.drafts || []).length || null,
        positions_overdue: (pos.positions || []).length || null,
        escalations_open: (escs.escalations || []).length || null,
        tier,
      });
    } catch (e) { /* offline; leave counters blank */ }
  }, []);

  useEffect(() => {
    refreshCounters();
    const id = setInterval(refreshCounters, 10000);
    return () => clearInterval(id);
  }, [refreshCounters]);

  const pageDef = APP_PAGES.find((p) => p.id === page) || APP_PAGES[0];
  const PageComp = pageDef.C;
  const pageProps = { toast: { show } };

  return (
    <div className="lh-page" style={{ display: 'flex', minHeight: '100vh' }}>
      <style dangerouslySetInnerHTML={{ __html: DARK_CSS }} />
      <window.BackgroundPattern />
      <AppSidebar active={page} counters={counters} theme={theme}
        onToggleTheme={toggle} onHelp={() => setHelpOpen(true)} />
      {/* key={page} forces React to remount <main> on every navigation,
          which re-triggers the lh-main-content fade-in animation. */}
      <main key={page} className="lh-main-content"
        style={{ flex: 1, padding: '28px 36px', position: 'relative',
          overflow: 'auto', maxHeight: '100vh' }}>
        <PageBoundary pageKey={page}>
          {PageComp
            ? <PageComp {...pageProps} />
            : <window.LighthouseLoader fullscreen label="Starting Lighthouse…" />}
        </PageBoundary>
      </main>
      <div aria-live="polite" aria-atomic="true">
        <window.Toast toast={toast} />
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)}
        onGo={(id) => { window.location.hash = id; }} />
      <ShortcutOverlay open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
})();
