// app-lib.jsx — production fetch helpers, hooks, and shared UI primitives
// for the real Lighthouse dashboard (as opposed to the design-canvas handoff).
// Loaded via babel-standalone; everything is hung on window.* because there is
// no module bundler — all <script type="text/babel"> share one global scope.
//
// FROZEN global names (other agents depend on these exactly):
//   apiGet apiPost apiPatch apiDelete useApi useEvents useToast
//   Toast PageHeader EmptyState Loading Skeleton ErrorBox Btn DataTable
//   ConfidencePill StatusPill Bar SidePane Modal Field Row Metric card
//   BrierScore WepBar ProgressRing  (new in polish pass)

const { useState, useEffect, useRef, useCallback, useLayoutEffect } = React;

// ── Mode display names ──────────────────────────────────────────────────────
// Internal mode ids (sent to / stored by the backend) are kept stable; these
// are the user-facing labels shown in the UI. Unknown ids pass through as-is.
window.MODE_LABELS = {
  'Deep-Dive': 'Deep Research',
  'QUC': 'Quick Answer',
  'Monitor': 'Event Monitor',
  'Debate': 'Debate',
  'Digest': 'Digest',
};
window.modeLabel = function modeLabel(mode) {
  if (!mode) return 'Job';
  return window.MODE_LABELS[mode] || mode;
};

// ── Inject styles for things CSS-vars can't express (shimmer, focus, anim) ──
(function injectLibStyles() {
  if (document.getElementById('lh-lib-styles')) return;
  const el = document.createElement('style');
  el.id = 'lh-lib-styles';
  el.textContent = `
    @keyframes lh-shimmer { 0% { background-position: -480px 0; } 100% { background-position: 480px 0; } }
    @keyframes lh-fade-in { from { opacity: 0; } to { opacity: 1; } }
    @keyframes lh-toast-in { from { opacity: 0; transform: translateX(24px); } to { opacity: 1; transform: translateX(0); } }
    @keyframes lh-pane-in { from { transform: translateX(24px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes lh-modal-in { from { transform: translateY(12px) scale(0.98); opacity: 0; } to { transform: translateY(0) scale(1); opacity: 1; } }
    @keyframes lh-spin { to { transform: rotate(360deg); } }
    @keyframes lh-btn-spin { to { transform: rotate(360deg); } }
    @keyframes lh-slide-up { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    @keyframes lh-toast-prog { from { width: 100%; } to { width: 0%; } }
    .lh-skel {
      background: linear-gradient(90deg, var(--rule-soft) 25%, var(--rule) 37%, var(--rule-soft) 63%);
      background-size: 960px 100%; animation: lh-shimmer 1.4s ease infinite; border-radius: var(--radius-sm);
    }
    .lh-btn { transition: background .15s ease, box-shadow .15s ease, opacity .15s ease, transform .05s ease; }
    .lh-btn:hover:not(:disabled) { filter: brightness(1.04); }
    .lh-btn:active:not(:disabled) { transform: translateY(1px); }
    .lh-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .lh-tab { transition: color .12s ease, border-color .12s ease; }
    .lh-tab:hover { color: var(--primary) !important; }
    .lh-row-hover:hover { background: var(--rule-soft) !important; transition: background .1s ease; }
    .lh-focusable:focus-visible, .lh-btn:focus-visible, .lh-tab:focus-visible {
      outline: 2px solid var(--primary); outline-offset: 2px; border-radius: var(--radius-sm);
    }
    .lh-overlay { animation: lh-fade-in .12s ease; }
    .lh-scrim { position: fixed; inset: 0; background: rgba(10,42,68,0.28); z-index: 800; }
    .lh-truncate-2 {
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }
    .lh-slide-up { animation: lh-slide-up .18s ease; }
    .lh-toast-bar {
      position: absolute; bottom: 0; left: 0; height: 3px;
      background: rgba(255,255,255,0.35); border-radius: 0 0 var(--radius-sm) var(--radius-sm);
      animation: lh-toast-prog 3.5s linear forwards;
    }
  `;
  document.head.appendChild(el);
})();

// ── API helpers ─────────────────────────────────────────────────────────
async function apiGet(path) {
  const res = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail || ''; } catch (e) { /* non-JSON */ }
    throw new Error(detail || `${path} → ${res.status}`);
  }
  return res.json();
}
async function apiSend(path, method, body) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body != null ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail || ''; } catch (e) { /* non-JSON */ }
    throw new Error(detail || `${path} → ${res.status}`);
  }
  if (res.status === 204) return null;
  try { return await res.json(); } catch (e) { return null; }
}
const apiPost = (p, b) => apiSend(p, 'POST', b);
const apiPatch = (p, b) => apiSend(p, 'PATCH', b);
const apiDelete = (p) => apiSend(p, 'DELETE');

// ── useApi: fetch + poll + manual refresh ───────────────────────────────
function useApi(path, { pollMs = 0, deps = [] } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(async () => {
    try {
      const d = await apiGet(path);
      if (!alive.current) return;
      setData(d); setError(null);
    } catch (e) {
      if (alive.current) setError(e.message || String(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    setLoading(true);
    load();
    if (pollMs > 0) {
      const id = setInterval(load, pollMs);
      return () => clearInterval(id);
    }
  }, [load, pollMs, ...deps]); // eslint-disable-line
  return { data, error, loading, reload: load };
}

// ── useEvents: subscribe to the SSE channel with auto-reconnect ──────────
const SSE_EVENTS = [
  'job.progress', 'job.status', 'draft.staged', 'draft.approved',
  'draft.rejected', 'position.resolved', 'audit.appended',
  'governor.tier', 'governor.tripped',
];
function useEvents(onEvent) {
  const cb = useRef(onEvent);
  useLayoutEffect(() => { cb.current = onEvent; });
  useEffect(() => {
    let es = null, retry = null, closed = false, backoff = 1000;
    const connect = () => {
      if (closed) return;
      try {
        es = new EventSource('/api/events');
      } catch (e) { return; /* SSE unsupported; pages fall back to polling */ }
      es.onopen = () => { backoff = 1000; };
      SSE_EVENTS.forEach((name) => {
        es.addEventListener(name, (e) => {
          let data = {};
          try { data = e.data ? JSON.parse(e.data) : {}; } catch (err) { /* keep {} */ }
          try { if (cb.current) cb.current(name, data); } catch (err) { /* swallow */ }
        });
      });
      es.onerror = () => {
        if (closed) return;
        try { es.close(); } catch (err) { /* noop */ }
        retry = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 15000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      if (es) { try { es.close(); } catch (err) { /* noop */ } }
    };
  }, []);
}

// ── useToast: top-right ephemeral message ────────────────────────────────
function useToast() {
  const [toast, setToast] = useState(null);
  const timer = useRef(null);
  const show = useCallback((msg, kind = 'info') => {
    if (timer.current) clearTimeout(timer.current);
    setToast({ msg, kind, _id: Date.now() });
    timer.current = setTimeout(() => setToast(null), 3500);
  }, []);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  return { toast, show };
}
function Toast({ toast }) {
  if (!toast) return null;
  const kind = toast.kind || 'info';
  const bg = kind === 'error' ? '#c62828'
    : kind === 'success' ? 'var(--green-dark)'
    : 'var(--primary-dark)';
  return (
    <div
      role="status"
      aria-live="polite"
      key={toast._id}
      style={{
        position: 'fixed', top: 18, right: 18, zIndex: 999,
        background: bg, color: '#fff', padding: '10px 40px 10px 16px',
        borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-lg)',
        fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 500, maxWidth: 360,
        animation: 'lh-toast-in .22s cubic-bezier(0.22,1,0.36,1)',
        overflow: 'hidden', position: 'fixed',
      }}
    >
      {toast.msg}
      <button
        type="button"
        onClick={() => {/* dismiss is handled by timer; button is cosmetic close */}}
        aria-label="Dismiss"
        style={{
          position: 'absolute', top: 8, right: 10,
          background: 'none', border: 'none', cursor: 'pointer',
          color: 'rgba(255,255,255,0.8)', fontSize: 16, lineHeight: 1, padding: 2,
        }}
      >×</button>
      <div className="lh-toast-bar" key={`bar-${toast._id}`} />
    </div>
  );
}

// ── Layout primitives ────────────────────────────────────────────────────
const card = {
  background: 'var(--card)', border: '1px solid var(--rule)',
  borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-sm)',
};

function PageHeader({ title, subtitle, actions, tabs, activeTab, onTab, breadcrumb }) {
  return (
    <header style={{ marginBottom: 18 }}>
      {breadcrumb && (
        <div style={{
          fontFamily: 'var(--sans)', fontSize: 11.5, color: 'var(--muted)',
          marginBottom: 6, letterSpacing: '0.01em',
        }}>
          {breadcrumb}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1 style={{ fontFamily: 'var(--serif)', fontWeight: 700, fontSize: 26,
            margin: 0, color: 'var(--ink)', lineHeight: 1.15 }}>{title}</h1>
          {subtitle && <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 3 }}>{subtitle}</div>}
        </div>
        {actions && <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>{actions}</div>}
      </div>
      {tabs && tabs.length > 0 && (
        <div role="tablist" style={{ display: 'flex', gap: 4, marginTop: 14,
          borderBottom: '1px solid var(--rule)' }}>
          {tabs.map((t) => {
            const on = activeTab === t;
            return (
              <button key={t} className="lh-tab" role="tab" aria-selected={on}
                onClick={() => onTab && onTab(t)}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                  padding: '8px 14px', color: on ? 'var(--primary)' : 'var(--muted)',
                  borderBottom: on ? '2px solid var(--primary)' : '2px solid transparent',
                  marginBottom: -1,
                  transition: 'color .12s ease, border-color .12s ease',
                }}>{t}</button>
            );
          })}
        </div>
      )}
    </header>
  );
}

function EmptyState({ icon = '◌', title, hint, action, cta }) {
  return (
    <div style={{
      ...card,
      padding: '52px 28px',
      textAlign: 'center',
      color: 'var(--muted)',
      background: 'linear-gradient(135deg, var(--card) 0%, rgba(2,136,209,0.02) 100%)',
    }}>
      <div aria-hidden="true" style={{ fontSize: 40, marginBottom: 12, opacity: 0.3, lineHeight: 1 }}>{icon}</div>
      <div style={{ fontFamily: 'var(--serif)', fontSize: 17, color: 'var(--ink-2)', fontWeight: 600 }}>{title}</div>
      {hint && <div style={{ fontSize: 13, marginTop: 7, lineHeight: 1.55, color: 'var(--muted)', maxWidth: '36ch', margin: '7px auto 0' }}>{hint}</div>}
      {(action || cta) && (
        <div style={{ marginTop: 20, display: 'flex', justifyContent: 'center', gap: 8 }}>
          {action}
          {cta}
        </div>
      )}
    </div>
  );
}

function Loading({ label = 'Loading…' }) {
  return (
    <div role="status" aria-live="polite"
      style={{ padding: 40, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        gap: 10, color: 'var(--muted)', fontFamily: 'var(--sans)', fontSize: 13 }}>
      <span aria-hidden="true" style={{
        width: 18, height: 18, border: '2px solid var(--rule)',
        borderTopColor: 'var(--primary)', borderRadius: '50%',
        display: 'inline-block', animation: 'lh-spin .7s linear infinite',
      }} />
      <span>{label}</span>
    </div>
  );
}

function Skeleton({ rows = 3, height, width, style: styleProp, radius }) {
  // Single-item mode: height or width provided
  if (height != null || width != null) {
    return (
      <div className="lh-skel" style={{
        height: height || 14,
        width: width || '100%',
        borderRadius: radius || 'var(--radius-sm)',
        ...styleProp,
      }} />
    );
  }
  // Multi-row mode: legacy API
  const n = Math.max(1, rows | 0);
  return (
    <div style={{ ...card, padding: 16 }} role="status" aria-busy="true" aria-label="Loading content">
      <div className="lh-skel" style={{ height: 16, width: '38%', marginBottom: 16 }} />
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'center',
          marginBottom: i === n - 1 ? 0 : 12 }}>
          <div className="lh-skel" style={{ height: 12, flex: 1 }} />
          <div className="lh-skel" style={{ height: 12, width: '18%' }} />
          <div className="lh-skel" style={{ height: 12, width: '12%' }} />
        </div>
      ))}
    </div>
  );
}

// SkeletonGroup: realistic text loading with varied widths
function SkeletonGroup({ lines = 4, style: styleProp }) {
  const widths = ['92%', '78%', '85%', '60%', '88%', '72%', '95%', '65%'];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, ...styleProp }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="lh-skel" style={{ height: 13, width: widths[i % widths.length] }} />
      ))}
    </div>
  );
}

function ErrorBox({ message, onRetry }) {
  return (
    <div role="alert" style={{
      ...card,
      padding: '14px 16px',
      borderLeft: '4px solid #c62828',
      color: 'var(--ink)',
      fontFamily: 'var(--sans)',
      fontSize: 14,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span aria-hidden="true" style={{ fontSize: 16, color: '#c62828', flexShrink: 0 }}>⚠</span>
        <span style={{ color: '#b71c1c' }}>{message || 'Something went wrong.'}</span>
      </div>
      {onRetry && (
        <Btn kind="ghost" size="sm" onClick={onRetry} aria-label="Retry" style={{ flexShrink: 0 }}>Retry</Btn>
      )}
    </div>
  );
}

function Btn({ children, onClick, kind = 'primary', size = 'md', style, loading: isLoading, icon, ...rest }) {
  const base = {
    cursor: isLoading ? 'wait' : 'pointer',
    fontFamily: 'var(--sans)', fontWeight: 600,
    fontSize: size === 'sm' ? 12 : 13, borderRadius: 'var(--radius-sm)',
    padding: size === 'sm' ? '5px 10px' : '8px 16px', border: '1px solid transparent',
    display: 'inline-flex', alignItems: 'center', gap: 6, lineHeight: 1.2,
    whiteSpace: 'nowrap',
  };
  const kinds = {
    primary: { background: 'var(--primary)', color: '#fff', boxShadow: 'var(--shadow-sm)' },
    ghost: { background: 'var(--card)', color: 'var(--primary)', borderColor: 'var(--rule)' },
    danger: { background: 'var(--card)', color: 'var(--coral-2)', borderColor: 'var(--coral-2)' },
    success: { background: 'var(--green-dark)', color: '#fff', boxShadow: 'var(--shadow-sm)' },
  };
  const spinSize = size === 'sm' ? 8 : 10;
  const spinColor = kind === 'primary' || kind === 'success' ? 'rgba(255,255,255,0.5)' : 'var(--rule)';
  const spinTopColor = kind === 'primary' || kind === 'success' ? '#fff' : 'var(--primary)';
  return (
    <button type="button" className="lh-btn" onClick={onClick} disabled={isLoading || rest.disabled}
      style={{ ...base, ...(kinds[kind] || kinds.primary), ...style }} {...rest}>
      {isLoading && (
        <span aria-hidden="true" style={{
          width: spinSize, height: spinSize,
          border: `2px solid ${spinColor}`,
          borderTopColor: spinTopColor,
          borderRadius: '50%',
          display: 'inline-block',
          animation: 'lh-btn-spin .65s linear infinite',
          flexShrink: 0,
        }} />
      )}
      {!isLoading && icon && <span aria-hidden="true" style={{ flexShrink: 0, lineHeight: 1 }}>{icon}</span>}
      {children}
    </button>
  );
}

function DataTable({ columns, rows, onRow, activeRow, empty, stickyHead }) {
  const cols = columns || [];
  if (!rows || rows.length === 0) return empty || null;
  return (
    <div style={{ ...card, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--sans)' }}>
        <thead style={stickyHead ? { position: 'sticky', top: 0, zIndex: 1 } : {}}>
          <tr style={{ background: 'var(--rule-soft)' }}>
            {cols.map((c) => (
              <th key={c.key} scope="col" style={{ textAlign: 'left', padding: '9px 14px',
                fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em',
                textTransform: 'uppercase', color: 'var(--muted)',
                background: 'var(--rule-soft)',
              }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const key = (r && r._key != null) ? r._key : i;
            const active = activeRow != null && activeRow === key;
            const clickable = !!onRow;
            const isEven = i % 2 === 1;
            return (
              <tr key={key}
                className={clickable ? 'lh-row-hover' : undefined}
                onClick={clickable ? () => onRow(r) : undefined}
                onKeyDown={clickable ? (e) => {
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRow(r); }
                } : undefined}
                tabIndex={clickable ? 0 : undefined}
                role={clickable ? 'button' : undefined}
                style={{ borderTop: '1px solid var(--rule-soft)',
                  cursor: clickable ? 'pointer' : 'default',
                  outline: 'none',
                  background: active ? 'var(--rule-soft)'
                    : isEven ? 'rgba(234,242,248,0.45)'
                    : 'transparent',
                  transition: 'background .12s ease' }}>
                {cols.map((c) => (
                  <td key={c.key} style={{ padding: '11px 14px', fontSize: 13,
                    color: 'var(--ink)', verticalAlign: 'middle' }}>
                    {c.render ? c.render(r) : (r ? r[c.key] : null)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ConfidencePill({ phrase, band }) {
  const p = (phrase || '').toString().toLowerCase().trim();
  let klass;
  if (!p) {
    klass = 'even';
  } else if (/almost certain|highly likely|very likely/.test(p)) {
    klass = 'high';
  } else if (/^likely$|^likely\b/.test(p)) {
    klass = 'likely';
  } else if (/even chance|roughly even/.test(p)) {
    klass = 'even';
  } else if (/almost no chance|remote/.test(p)) {
    klass = 'remote';
  } else if (/very unlikely|unlikely/.test(p)) {
    klass = 'unlikely';
  } else if (/certain|high/.test(p)) {
    klass = 'high';
  } else if (/likely/.test(p)) {
    klass = 'likely';
  } else if (/improbable/.test(p)) {
    klass = 'unlikely';
  } else {
    klass = 'even';
  }
  return (
    <span className={`wep ${klass}`} title={band != null ? `confidence ${band}` : undefined}>
      {phrase || 'unrated'}
    </span>
  );
}

function StatusPill({ status }) {
  const s = (status || '').toString();
  const map = {
    running: 'running', active: 'running', published: 'running',
    queued: 'queued', pending: 'queued',
    review: 'review', staged: 'review',
    paused: 'paused', cancelled: 'paused',
    done: 'done', completed: 'done',
    failed: 'failed', rejected: 'failed',
  };
  return (
    <span className={`pill ${map[s] || ''}`}>
      <span className="dot" aria-hidden="true" />{s || 'unknown'}
    </span>
  );
}

function Bar({ value, max, color = 'var(--primary)' }) {
  const v = Number(value) || 0;
  const m = Number(max) || 0;
  const pct = m > 0 ? Math.min(Math.max(v / m, 0), 1) * 100 : 0;
  return (
    <div role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={m || undefined}
      style={{ height: 8, background: 'var(--rule-soft)', borderRadius: 4,
        overflow: 'hidden', minWidth: 120 }}>
      <div style={{ width: `${pct}%`, height: '100%', background: color,
        transition: 'width .4s ease' }} />
    </div>
  );
}

// ── Focus trap shared by Modal + SidePane ─────────────────────────────────
function useFocusTrap(ref, onClose) {
  useEffect(() => {
    const node = ref.current;
    const prev = document.activeElement;
    const sel = 'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])';
    const focusFirst = () => {
      if (!node) return;
      const f = node.querySelector(sel);
      (f || node).focus();
    };
    focusFirst();
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); if (onClose) onClose(); return; }
      if (e.key !== 'Tab' || !node) return;
      const items = Array.prototype.slice.call(node.querySelectorAll(sel))
        .filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (items.length === 0) { e.preventDefault(); return; }
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      if (prev && prev.focus) { try { prev.focus(); } catch (e) { /* noop */ } }
    };
  }, [ref, onClose]);
}

function SidePane({ title, onClose, children, footer, actions }) {
  const ref = useRef(null);
  useFocusTrap(ref, onClose);
  const resolvedFooter = footer || (actions
    ? <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>{actions}</div>
    : null);
  return (
    <React.Fragment>
      <div className="lh-scrim lh-overlay" onClick={onClose} aria-hidden="true" />
      <aside ref={ref} role="dialog" aria-modal="true" aria-label={title || 'Details'} tabIndex={-1}
        style={{
          position: 'fixed', top: 0, right: 0, bottom: 0, width: 420, maxWidth: '90vw',
          background: 'var(--card)', borderLeft: '1px solid var(--rule)',
          boxShadow: 'var(--shadow-lg)', zIndex: 810, display: 'flex', flexDirection: 'column',
          animation: 'lh-pane-in .2s ease', outline: 'none',
        }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 20px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
          <h2 style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
            margin: 0, color: 'var(--ink)' }}>{title}</h2>
          <button type="button" className="lh-btn lh-focusable" onClick={onClose} aria-label="Close panel"
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20,
              lineHeight: 1, color: 'var(--muted)', padding: 4 }}>×</button>
        </div>
        <div style={{ padding: 20, overflow: 'auto', flex: 1 }}>{children}</div>
        {resolvedFooter && (
          <div style={{
            padding: '12px 20px', borderTop: '1px solid var(--rule)',
            background: 'var(--card)', flexShrink: 0,
          }}>
            {resolvedFooter}
          </div>
        )}
      </aside>
    </React.Fragment>
  );
}

function Modal({ title, onClose, children, size = 'md', footer }) {
  const ref = useRef(null);
  useFocusTrap(ref, onClose);
  const widthMap = { sm: 380, md: 460, lg: 600, xl: 800 };
  const w = widthMap[size] || widthMap.md;
  return (
    <div className="lh-overlay" onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 900,
        background: 'rgba(10,42,68,0.28)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        padding: '8vh 16px', overflow: 'auto',
      }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title || 'Dialog'} tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{
          ...card, width: w, maxWidth: '100%', boxShadow: 'var(--shadow-lg)',
          animation: 'lh-modal-in .18s ease', outline: 'none',
          display: 'flex', flexDirection: 'column',
        }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 20px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
          <h2 style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
            margin: 0, color: 'var(--ink)' }}>{title}</h2>
          <button type="button" className="lh-btn lh-focusable" onClick={onClose} aria-label="Close dialog"
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20,
              lineHeight: 1, color: 'var(--muted)', padding: 4 }}>×</button>
        </div>
        <div style={{ padding: 20, flex: 1 }}>{children}</div>
        {footer && (
          <div style={{
            padding: '12px 20px', borderTop: '1px solid var(--rule)',
            background: 'var(--card)', borderRadius: '0 0 var(--radius) var(--radius)', flexShrink: 0,
          }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: 'block', marginBottom: 14 }}>
      <div style={{ fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 700,
        letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)',
        marginBottom: 6 }}>{label}</div>
      {children}
    </label>
  );
}

function Row({ k, v }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16,
      padding: '8px 0', borderBottom: '1px solid var(--rule-soft)',
      fontFamily: 'var(--sans)', fontSize: 13 }}>
      <span style={{ color: 'var(--muted)' }}>{k}</span>
      <span style={{ color: 'var(--ink)', fontWeight: 500, textAlign: 'right',
        wordBreak: 'break-word' }}>{v == null || v === '' ? '—' : v}</span>
    </div>
  );
}

function Metric({ label, value, hint }) {
  return (
    <div style={{ ...card, padding: '16px 18px', minWidth: 120, flex: '1 1 0' }}>
      <div className="small-caps" style={{ color: 'var(--muted)' }}>{label}</div>
      <div className="num" style={{ fontSize: 26, fontWeight: 600, color: 'var(--ink)',
        marginTop: 6, lineHeight: 1.1 }}>{value == null || value === '' ? '—' : value}</div>
      {hint && <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

// ── BrierScore: numeric score colored by quality ─────────────────────────
function BrierScore({ score }) {
  const n = Number(score);
  const color = isNaN(n) ? 'var(--muted)'
    : n < 0.1 ? '#2e7d32'
    : n < 0.2 ? '#00695c'
    : n < 0.25 ? '#f57c00'
    : '#c62828';
  return (
    <span style={{ fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 600, color }}>
      {isNaN(n) ? '—' : n.toFixed(3)}
      <span style={{ fontFamily: 'var(--sans)', fontSize: 10, fontWeight: 500,
        color: 'var(--muted)', marginLeft: 4 }}>Brier</span>
    </span>
  );
}

// ── WepBar: horizontal probability bar ────────────────────────────────────
function WepBar({ probability }) {
  const p = Math.min(Math.max(Number(probability) || 0, 0), 1);
  const pct = Math.round(p * 100);
  // gradient: red (0) → amber (0.5) → green (1)
  const r = p < 0.5 ? 220 : Math.round(220 - (p - 0.5) * 2 * 180);
  const g = p < 0.5 ? Math.round(p * 2 * 210) : 210;
  const b = 40;
  const fillColor = `rgb(${r},${g},${b})`;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}
        style={{ flex: 1, height: 8, background: 'var(--rule-soft)', borderRadius: 4, overflow: 'hidden', minWidth: 80 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: fillColor, transition: 'width .4s ease' }} />
      </div>
      <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-2)', minWidth: 34, textAlign: 'right' }}>
        {pct}%
      </span>
    </div>
  );
}

// ── ProgressRing: SVG circle progress ring ────────────────────────────────
function ProgressRing({ value, max, size = 40, stroke = 4 }) {
  const v = Number(value) || 0;
  const m = Number(max) || 1;
  const pct = Math.min(Math.max(v / m, 0), 1);
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const dash = circ * pct;
  const center = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}
      role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={m}
      style={{ transform: 'rotate(-90deg)' }}>
      <circle cx={center} cy={center} r={r}
        fill="none" stroke="var(--rule-soft)" strokeWidth={stroke} />
      <circle cx={center} cy={center} r={r}
        fill="none" stroke="var(--primary)" strokeWidth={stroke}
        strokeDasharray={`${dash} ${circ}`}
        strokeLinecap="round"
        style={{ transition: 'stroke-dasharray .4s ease' }} />
    </svg>
  );
}

Object.assign(window, {
  apiGet, apiPost, apiPatch, apiDelete, useApi, useEvents, useToast,
  Toast, PageHeader, EmptyState, Loading, Skeleton, SkeletonGroup, ErrorBox, Btn, DataTable,
  ConfidencePill, StatusPill, Bar, SidePane, Modal, Field, Row, Metric, card,
  BrierScore, WepBar, ProgressRing,
});
