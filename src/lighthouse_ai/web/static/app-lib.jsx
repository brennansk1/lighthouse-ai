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
  'job.progress', 'job.status', 'job.step', 'synthesis.token',
  'draft.staged', 'draft.approved',
  'draft.rejected', 'position.resolved', 'audit.appended',
  'governor.tier', 'governor.tripped',
  'chat.token', 'chat.turn',
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
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="#c62828" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
          style={{ flexShrink: 0 }}>
          <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
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
        color: 'var(--muted)', marginLeft: 4 }}>accuracy</span>
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

// ── JobTrace: "watch the deep research happen" live process viewer ─────────
//
// Consumes the Zone-A contract:
//   GET /api/jobs/{id}/trace → {job_id, status, pct, events:[{seq,ts,phase,
//     kind,label,pct,data}, ...]}  (poll-safe; empty for unknown jobs)
//   SSE 'job.step' → {job_id, seq, phase, kind, label, pct, data}
//
// Live streaming: useEvents appends each job.step (matched by job_id), deduped
// by seq, merged with the polled backlog into one sorted-unique list. Polling
// (2s) is the fallback/backlog source and relaxes once the job is terminal.
// Post-hoc review: the very same path renders a completed job's persisted
// trace, plus a "View artifact" button and (when a draft_id is known) the
// entity graph + contradictions / known-unknowns summary.

(function injectTraceStyles() {
  if (document.getElementById('lh-trace-styles')) return;
  const el = document.createElement('style');
  el.id = 'lh-trace-styles';
  el.textContent = `
    @keyframes lh-trace-pulse {
      0%,100% { box-shadow: 0 0 0 0 rgba(2,136,209,0.32); }
      50%     { box-shadow: 0 0 0 6px rgba(2,136,209,0); }
    }
    @keyframes lh-trace-beam { to { transform: rotate(360deg); } }
    .lh-trace-active-dot { animation: lh-trace-pulse 1.6s ease-in-out infinite; }
  `;
  document.head.appendChild(el);
})();

// Monochrome line-icon set (matches the NavIcon house style: 24×24, no fill,
// stroke=currentColor) so the trace reads professionally — no emoji anywhere.
const TRACE_ICONS = {
  framing: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.2"/>',
  sources: '<line x1="5" y1="7" x2="19" y2="7"/><line x1="5" y1="12" x2="19" y2="12"/><line x1="5" y1="17" x2="13" y2="17"/>',
  retrieval: '<circle cx="11" cy="11" r="6.5"/><line x1="20" y1="20" x2="16" y2="16"/>',
  drafting: '<path d="M14 3v5h5"/><path d="M7 3h7l5 5v11a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/>',
  verification: '<path d="M12 3l7 3v5c0 4.5-3 7.2-7 8.4C8 18.2 5 15.5 5 11V6z"/><path d="M9 11.6l2 2 4-4.3"/>',
  synthesis: '<path d="M12 4l8 4.2-8 4.2-8-4.2z"/><path d="M4 13l8 4.2 8-4.2"/>',
  done: '<circle cx="12" cy="12" r="8.5"/><path d="M8.4 12.3l2.5 2.4 4.7-5"/>',
  round: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4v4h-4"/>',
  contradiction: '<path d="M12 4l8.5 15h-17z"/><line x1="12" y1="10" x2="12" y2="14"/><circle cx="12" cy="16.6" r="0.5" fill="currentColor" stroke="none"/>',
  known_unknown: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 0 1 4.7 1c0 1.6-2.1 2-2.3 3.4"/><circle cx="12" cy="16.6" r="0.5" fill="currentColor" stroke="none"/>',
  coverage: '<line x1="6" y1="20" x2="6" y2="13"/><line x1="12" y1="20" x2="12" y2="7"/><line x1="18" y1="20" x2="18" y2="11"/>',
  checkpoint: '<path d="M6 21V4"/><path d="M6 5h10l-2 3 2 3H6"/>',
  node: '<circle cx="7" cy="7" r="2.2"/><circle cx="17" cy="17" r="2.2"/><path d="M9 7h4a4 4 0 0 1 4 4v4"/>',
};

// Renders one trace icon by name. Mirrors NavIcon (stroke=currentColor) so the
// glyph inherits the surrounding text colour/tone.
function TraceIcon({ name, size = 14 }) {
  return React.createElement('svg', {
    width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round',
    strokeLinejoin: 'round', 'aria-hidden': 'true', style: { display: 'block' },
    dangerouslySetInnerHTML: { __html: TRACE_ICONS[name] || TRACE_ICONS.framing },
  });
}

// Phase → plain-language label + icon name. Ordered to match the backend
// vocabulary; labels read like steps a person would recognise, not jargon.
const TRACE_PHASES = [
  { key: 'framing',      label: 'Understanding the question', icon: 'framing' },
  { key: 'sources',      label: 'Choosing sources',           icon: 'sources' },
  { key: 'retrieval',    label: 'Gathering evidence',         icon: 'retrieval' },
  { key: 'drafting',     label: 'Reading & drafting',         icon: 'drafting' },
  { key: 'verification', label: 'Checking gaps & conflicts',  icon: 'verification' },
  { key: 'synthesis',    label: 'Writing it up',              icon: 'synthesis' },
  { key: 'done',         label: 'Finished',                   icon: 'done' },
];
const TRACE_PHASE_INDEX = TRACE_PHASES.reduce((m, p, i) => { m[p.key] = i; return m; }, {});

// kind → small chip (icon name + tone + plain-language text).
function traceKindChip(kind, data) {
  const d = data || {};
  switch (kind) {
    case 'section_drafted':
      return { icon: 'drafting', tone: 'var(--primary)',
        text: d.is_load_bearing ? 'answered a key question' : 'drafted a section' };
    case 'round':
      return { icon: 'round', tone: 'var(--primary)', text: 'drafting pass' };
    case 'skill_done':
    case 'sources_start':
      return { icon: 'retrieval', tone: 'var(--primary)', text: 'checked a source' };
    case 'contradiction':
      return { icon: 'contradiction', tone: 'var(--coral-2, #c62828)', text: 'found a conflict' };
    case 'known_unknown':
      return { icon: 'known_unknown', tone: '#d97706', text: 'open question' };
    case 'coverage':
      return { icon: 'coverage', tone: 'var(--green-dark)', text: 'coverage check' };
    case 'checkpoint':
      return { icon: 'checkpoint', tone: 'var(--muted)', text: 'progress saved' };
    case 'resumed':
      // A crashed multi-hour run picked up from its last checkpoint — an
      // info marker, not a fresh start.
      return { icon: 'checkpoint', tone: 'var(--primary)',
        text: d.nodes_done != null
          ? `resumed — ${d.nodes_done} done, ${d.pending != null ? d.pending : '?'} to go`
          : 'resumed from checkpoint' };
    case 'degraded':
      // Some LLM calls fell back to the mock (RAM too tight / model too big) —
      // the answer is partly synthetic. Amber, not red: the run completed, but
      // the user must know it wasn't fully real.
      return { icon: 'contradiction', tone: '#d97706',
        text: d.degraded != null
          ? `ran partly on the fallback (${d.degraded} call(s))`
          : 'ran partly on the fallback model' };
    case 'stalled':
      // The local model stopped responding and the run was aborted. This must
      // read as a hard stop, never an eternally-running job (incident 2026-06-10).
      // Failure red (#c62828) — matches .pill.failed; the coastal theme remaps
      // --coral-2 to navy, which would wrongly read as an ordinary accent here.
      return { icon: 'contradiction', tone: '#c62828',
        text: d.call ? `backend stalled on ${d.call} — stopped` : 'backend stalled — stopped' };
    case 'node':
      return { icon: 'node', tone: 'var(--primary)',
        text: d.depth != null ? `explored (level ${d.depth})` : 'explored a question' };
    case 'done':
      return { icon: 'done', tone: 'var(--green-dark)', text: 'complete' };
    case 'start':
    case 'framing':
      return { icon: 'framing', tone: 'var(--muted)', text: 'started' };
    case 'drafted':
      return { icon: 'drafting', tone: 'var(--primary)', text: 'draft ready' };
    default:
      return { icon: 'framing', tone: 'var(--muted)', text: kind || '' };
  }
}

const TRACE_TERMINAL = ['review', 'done', 'completed', 'failed', 'cancelled', 'rejected', 'staged'];
function traceIsTerminal(status) {
  return TRACE_TERMINAL.indexOf((status || '').toString()) !== -1;
}

// Merge two event lists into a seq-sorted, seq-unique array (no mutation).
function traceMergeEvents(existing, incoming) {
  const bySeq = new Map();
  (existing || []).forEach((e) => { if (e && e.seq != null) bySeq.set(e.seq, e); });
  (incoming || []).forEach((e) => { if (e && e.seq != null && !bySeq.has(e.seq)) bySeq.set(e.seq, e); });
  return Array.from(bySeq.values()).sort((a, b) => (a.seq || 0) - (b.seq || 0));
}

// One step row in the vertical timeline.
function TraceStep({ ev, phaseIcon, active }) {
  const chip = traceKindChip(ev.kind, ev.data);
  const depth = ev.data && ev.data.depth != null ? Number(ev.data.depth) : null;
  const indent = depth != null && depth > 0 ? Math.min(depth, 6) * 14 : 0;
  // A stalled step is a hard failure — give the whole row alert styling so it
  // can never be mistaken for an in-progress step.
  const isAlert = ev.kind === 'stalled';
  return (
    <div className="lh-slide-up"
      role={isAlert ? 'alert' : undefined}
      style={{ display: 'flex', gap: 10, padding: isAlert ? '8px 10px' : '6px 0',
        alignItems: 'flex-start', marginLeft: indent,
        background: isAlert ? 'rgba(198,40,40,0.08)' : undefined,
        borderLeft: isAlert ? '3px solid #c62828' : undefined,
        borderRadius: isAlert ? 6 : undefined }}>
      <span
        className={active ? 'lh-trace-active-dot' : undefined}
        aria-hidden="true"
        style={{
          width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          color: active ? 'var(--primary)' : 'var(--muted)',
          lineHeight: 1, marginTop: 1,
          background: active ? 'rgba(2,136,209,0.12)' : 'var(--rule-soft)',
          border: `1px solid ${active ? 'var(--primary)' : 'var(--rule)'}`,
        }}><TraceIcon name={phaseIcon} size={13} /></span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: 'var(--sans)', fontSize: 13, color: 'var(--ink)',
          lineHeight: 1.4, wordBreak: 'break-word' }}>
          {ev.label || ev.kind || 'step'}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2,
          flexWrap: 'wrap' }}>
          <span style={{ fontFamily: 'var(--sans)', fontSize: 10.5, fontWeight: 600,
            color: chip.tone, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <TraceIcon name={chip.icon} size={12} />{chip.text}
          </span>
          {ev.data && ev.data.voi != null && (
            // Plain language for the priority score: "VOI" (value of
            // information) is internal optimization jargon.
            <span style={{ fontFamily: 'var(--mono, monospace)', fontSize: 10,
              color: 'var(--muted)' }}
              title="How much answering this question could change the conclusion">
              priority {Number(ev.data.voi).toFixed(2)}</span>
          )}
          {ev.data && ev.data.status && ev.kind === 'node' && (
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>· {ev.data.status}</span>
          )}
          {ev.data && ev.data.citations != null && ev.data.citations > 0 && (
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>· {ev.data.citations} cites</span>
          )}
        </div>
      </div>
    </div>
  );
}

// Live tree for deep-tier (exhaustive) jobs, built from node/checkpoint events.
function TraceTree({ events }) {
  const nodes = events.filter((e) => e.kind === 'node');
  if (nodes.length === 0) return null;
  // Last-status-wins per question, preserving first-seen order.
  const order = [];
  const byQ = new Map();
  nodes.forEach((e) => {
    const q = (e.data && e.data.question) || e.label || `seq-${e.seq}`;
    if (!byQ.has(q)) order.push(q);
    byQ.set(q, e);
  });
  const statusTone = (s) => {
    const v = (s || '').toString().toLowerCase();
    if (v.indexOf('ground') !== -1) return 'var(--green-dark)';
    if (v.indexOf('prun') !== -1) return 'var(--muted)';
    if (v.indexOf('unknown') !== -1) return '#f57c00';
    return 'var(--primary)';
  };
  return (
    <details open style={{ marginTop: 14, ...card, padding: '10px 14px' }}>
      <summary style={{ cursor: 'pointer', fontFamily: 'var(--sans)', fontSize: 12,
        fontWeight: 700, color: 'var(--ink)', letterSpacing: '0.03em' }}>
        Research tree · {order.length} question{order.length === 1 ? '' : 's'}
      </summary>
      <div style={{ marginTop: 8 }}>
        {order.map((q) => {
          const e = byQ.get(q);
          const d = e.data || {};
          const depth = d.depth != null ? Math.min(Number(d.depth), 6) : 0;
          return (
            <div key={q} style={{ display: 'flex', gap: 6, alignItems: 'baseline',
              padding: '3px 0', marginLeft: depth * 16, fontSize: 12 }}>
              <span aria-hidden="true" style={{ color: statusTone(d.status), flexShrink: 0 }}>•</span>
              <span style={{ color: 'var(--ink)', flex: 1, minWidth: 0, wordBreak: 'break-word' }}>{q}</span>
              {d.status && <span style={{ fontSize: 10, color: statusTone(d.status),
                fontWeight: 600, flexShrink: 0 }}>{d.status}</span>}
              {d.voi != null && <span style={{ fontFamily: 'var(--mono, monospace)',
                fontSize: 10, color: 'var(--muted)', flexShrink: 0 }}>{Number(d.voi).toFixed(2)}</span>}
            </div>
          );
        })}
      </div>
    </details>
  );
}

// Post-completion entity graph (top entities) + verification summary.
function TraceCompletion({ draftId, events }) {
  const { data: graph } = useApi(
    draftId ? `/api/graph/draft/${draftId}` : '/api/__noop_trace_graph__',
    { pollMs: 0, deps: [draftId] });
  const contradictions = events.filter((e) => e.kind === 'contradiction');
  const knownUnknowns = events.filter((e) => e.kind === 'known_unknown');
  const entities = (graph && Array.isArray(graph.entities)) ? graph.entities.slice(0, 12) : [];

  const hasSummary = entities.length > 0 || contradictions.length > 0 || knownUnknowns.length > 0;
  if (!hasSummary) return null;
  return (
    <div style={{ marginTop: 14 }}>
      {entities.length > 0 && (
        <div style={{ ...card, padding: '10px 14px', marginBottom: 10 }}>
          <div style={{ fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 700,
            letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--muted)',
            marginBottom: 8 }}>Key entities</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {entities.map((en, i) => (
              <span key={i} style={{ fontFamily: 'var(--sans)', fontSize: 12,
                padding: '3px 9px', borderRadius: 999, background: 'rgba(2,136,209,0.08)',
                border: '1px solid var(--rule)', color: 'var(--ink)' }}>
                {en.label}
                {en.weight > 1 && <span style={{ color: 'var(--muted)', marginLeft: 4 }}>×{en.weight}</span>}
              </span>
            ))}
          </div>
        </div>
      )}
      {contradictions.length > 0 && (
        <div style={{ ...card, padding: '10px 14px', marginBottom: 10,
          borderLeft: '3px solid var(--coral-2, #c62828)' }}>
          <div style={{ fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 700,
            letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--coral-2, #c62828)',
            marginBottom: 6, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <TraceIcon name="contradiction" size={13} />Conflicts found ({contradictions.length})</div>
          {contradictions.map((e) => (
            <div key={e.seq} style={{ fontSize: 12, color: 'var(--ink)', padding: '2px 0' }}>{e.label}</div>
          ))}
        </div>
      )}
      {knownUnknowns.length > 0 && (
        <div style={{ ...card, padding: '10px 14px', borderLeft: '3px solid #f57c00' }}>
          <div style={{ fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 700,
            letterSpacing: '0.05em', textTransform: 'uppercase', color: '#d97706',
            marginBottom: 6, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <TraceIcon name="known_unknown" size={13} />Open questions ({knownUnknowns.length})</div>
          {knownUnknowns.map((e) => (
            <div key={e.seq} style={{ fontSize: 12, color: 'var(--ink)', padding: '2px 0' }}>{e.label}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function JobTrace({ jobId, onClose }) {
  const [events, setEvents] = useState([]);
  const [started] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  // Backlog / poll fallback. Stays at 2s; effectively idle once terminal
  // because nothing changes (we simply stop merging new rows).
  const { data: job } = useApi(jobId ? `/api/jobs/${jobId}` : '/api/__noop_trace_job__',
    { pollMs: 4000, deps: [jobId] });
  const { data: trace, loading: traceLoading } = useApi(
    jobId ? `/api/jobs/${jobId}/trace` : '/api/__noop_trace__',
    { pollMs: 2000, deps: [jobId] });

  const status = (trace && trace.status) || (job && job.status) || 'queued';
  const terminal = traceIsTerminal(status);

  // Merge polled backlog into the live list.
  useEffect(() => {
    if (trace && Array.isArray(trace.events) && trace.events.length) {
      setEvents((prev) => traceMergeEvents(prev, trace.events));
    }
  }, [trace]);

  // Live synthesis text — synthesizer tokens streamed over SSE. Kept to the
  // most recent ~6000 chars; the staged artifact is the full record.
  const [liveText, setLiveText] = useState('');

  // Live SSE append — only for our job, deduped by seq.
  useEvents((name, data) => {
    if (!data || data.job_id !== jobId) return;
    if (name === 'synthesis.token' && data.token) {
      setLiveText((prev) => (prev + data.token).slice(-6000));
      return;
    }
    if (name !== 'job.step') return;
    setEvents((prev) => traceMergeEvents(prev, [{
      seq: data.seq, ts: data.ts, phase: data.phase, kind: data.kind,
      label: data.label, pct: data.pct, data: data.data || {},
    }]));
  });

  // Elapsed ticker — stop once terminal.
  useEffect(() => {
    if (terminal) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [terminal]);

  const pct = events.length ? Number(events[events.length - 1].pct) || 0
    : (trace && trace.pct) || 0;
  const meta = (job && job.metadata) || {};
  const topic = meta.topic || (job && job.topic) || jobId;
  const mode = window.modeLabel ? window.modeLabel(job && job.mode) : (job && job.mode);
  const draftId = (() => {
    const doneEv = events.find((e) => e.kind === 'done' && e.data && e.data.draft_id);
    if (doneEv) return doneEv.data.draft_id;
    return meta.draft_id || null;
  })();

  const elapsedMs = (terminal && job && job.updated_at
    ? Date.parse(job.updated_at) - (job.created_at ? Date.parse(job.created_at) : started)
    : now - started);
  const elapsed = (() => {
    const s = Math.max(0, Math.floor((elapsedMs || 0) / 1000));
    if (!isFinite(s)) return '—';
    const m = Math.floor(s / 60);
    return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
  })();

  // Group events by phase, in canonical phase order.
  const grouped = TRACE_PHASES.map((p) => ({
    phase: p,
    rows: events.filter((e) => e.phase === p.key),
  })).filter((g) => g.rows.length > 0);
  const lastSeq = events.length ? events[events.length - 1].seq : null;
  const isDeep = events.some((e) => e.kind === 'node');
  const initialLoading = traceLoading && events.length === 0 && !job;

  const done = terminal && (status === 'done' || status === 'completed'
    || status === 'review' || status === 'staged');

  return (
    <div style={{ animation: 'lh-fade-in .18s ease' }}>
      {/* Header — progress ring wrapped by a sweeping beam mark while working */}
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginBottom: 16 }}>
        <div style={{ position: 'relative', width: 56, height: 56, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {!terminal && (
            <div aria-hidden="true" style={{ position: 'absolute', inset: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              animation: 'lh-trace-beam 3.2s linear infinite', opacity: 0.65 }}>
              {window.LighthouseMark
                ? <window.LighthouseMark size={56} beamRotating={false} />
                : null}
            </div>
          )}
          <ProgressRing value={pct} max={100} size={48} stroke={4} />
          <span style={{ position: 'absolute', fontFamily: 'var(--sans)', fontSize: 12,
            fontWeight: 700, color: terminal ? 'var(--green-dark)' : 'var(--primary)' }}>
            {done && pct >= 100 ? '✓' : `${Math.round(pct)}%`}
          </span>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--serif)', fontSize: 15, fontWeight: 700,
            color: 'var(--ink)', lineHeight: 1.3, wordBreak: 'break-word' }}>{topic}</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 5,
            flexWrap: 'wrap' }}>
            <StatusPill status={status} />
            {mode && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{mode}</span>}
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>· {elapsed} elapsed</span>
          </div>
        </div>
      </div>

      {initialLoading && (
        window.LighthouseLoader
          ? <window.LighthouseLoader size={72} label="Opening the trace…" />
          : <Loading label="Opening the trace…" />
      )}

      {!initialLoading && events.length === 0 && (
        <EmptyState icon="◌" title={terminal ? 'No recorded steps' : 'Waiting for the first step…'}
          hint={terminal
            ? 'This run finished without a detailed process trace.'
            : 'The research process will stream here as the run progresses.'} />
      )}

      {/* Vertical phase-grouped timeline */}
      {grouped.map((g) => (
        <div key={g.phase.key} style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 4 }}>
            <span aria-hidden="true" style={{ color: 'var(--primary)', display: 'inline-flex' }}>
              <TraceIcon name={g.phase.icon} size={15} /></span>
            <span style={{ fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 700,
              letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)' }}>
              {g.phase.label}
            </span>
            <span style={{ flex: 1, height: 1, background: 'var(--rule-soft)' }} />
          </div>
          <div style={{ borderLeft: '2px solid var(--rule-soft)', paddingLeft: 12, marginLeft: 6 }}>
            {g.rows.map((ev) => (
              <TraceStep key={ev.seq} ev={ev} phaseIcon={g.phase.icon}
                active={!terminal && ev.seq === lastSeq} />
            ))}
          </div>
        </div>
      ))}

      {/* Deep-tier live tree */}
      {isDeep && <TraceTree events={events} />}

      {/* Live synthesis — the model's narrative as it is written. Replaced by
          the staged artifact once the run completes. */}
      {!terminal && liveText && (
        <div style={{ ...card, padding: '10px 14px', marginBottom: 12,
          borderLeft: '3px solid var(--primary)' }}>
          <div style={{ fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 700,
            letterSpacing: '0.05em', textTransform: 'uppercase',
            color: 'var(--muted)', marginBottom: 6 }}>
            Writing synthesis…
          </div>
          <div style={{ fontSize: 13, color: 'var(--ink)', lineHeight: 1.55,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            maxHeight: 220, overflowY: 'auto' }}>
            {liveText}
            <span aria-hidden="true" style={{ opacity: 0.6 }}>▌</span>
          </div>
        </div>
      )}

      {/* Post-completion review: artifact link, entity graph, verification */}
      {terminal && (
        <React.Fragment>
          <TraceCompletion draftId={draftId} events={events} />
          <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
            <Btn kind="primary" onClick={() => {
              window.location.hash = 'library';
              if (onClose) onClose();
            }}>View artifact</Btn>
            {onClose && <Btn kind="ghost" onClick={onClose}>Close</Btn>}
          </div>
        </React.Fragment>
      )}
    </div>
  );
}

Object.assign(window, {
  apiGet, apiPost, apiPatch, apiDelete, useApi, useEvents, useToast,
  Toast, PageHeader, EmptyState, Loading, Skeleton, SkeletonGroup, ErrorBox, Btn, DataTable,
  ConfidencePill, StatusPill, Bar, SidePane, Modal, Field, Row, Metric, card,
  BrierScore, WepBar, ProgressRing, JobTrace,
});
