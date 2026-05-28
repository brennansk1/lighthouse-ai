// app-lib.jsx — production fetch helpers, hooks, and shared UI primitives
// for the real Lighthouse dashboard (as opposed to the design-canvas handoff).
// Loaded via babel-standalone; everything is hung on window.* because there is
// no module bundler — all <script type="text/babel"> share one global scope.
//
// FROZEN global names (other agents depend on these exactly):
//   apiGet apiPost apiPatch apiDelete useApi useEvents useToast
//   Toast PageHeader EmptyState Loading Skeleton ErrorBox Btn DataTable
//   ConfidencePill StatusPill Bar SidePane Modal Field Row Metric card

const { useState, useEffect, useRef, useCallback, useLayoutEffect } = React;

// ── Inject styles for things CSS-vars can't express (shimmer, focus, anim) ──
(function injectLibStyles() {
  if (document.getElementById('lh-lib-styles')) return;
  const el = document.createElement('style');
  el.id = 'lh-lib-styles';
  el.textContent = `
    @keyframes lh-shimmer { 0% { background-position: -480px 0; } 100% { background-position: 480px 0; } }
    @keyframes lh-fade-in { from { opacity: 0; } to { opacity: 1; } }
    @keyframes lh-toast-in { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
    @keyframes lh-pane-in { from { transform: translateX(24px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes lh-modal-in { from { transform: translateY(12px) scale(0.98); opacity: 0; } to { transform: translateY(0) scale(1); opacity: 1; } }
    @keyframes lh-spin { to { transform: rotate(360deg); } }
    .lh-skel {
      background: linear-gradient(90deg, var(--rule-soft) 25%, var(--rule) 37%, var(--rule-soft) 63%);
      background-size: 960px 100%; animation: lh-shimmer 1.4s ease infinite; border-radius: var(--radius-sm);
    }
    .lh-btn { transition: background .15s ease, box-shadow .15s ease, opacity .15s ease, transform .05s ease; }
    .lh-btn:hover:not(:disabled) { filter: brightness(1.04); }
    .lh-btn:active:not(:disabled) { transform: translateY(1px); }
    .lh-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .lh-tab { transition: color .12s ease, border-color .12s ease; }
    .lh-row-hover:hover { background: var(--rule-soft) !important; }
    .lh-focusable:focus-visible, .lh-btn:focus-visible, .lh-tab:focus-visible {
      outline: 2px solid var(--primary); outline-offset: 2px; border-radius: var(--radius-sm);
    }
    .lh-overlay { animation: lh-fade-in .12s ease; }
    .lh-scrim { position: fixed; inset: 0; background: rgba(10,42,68,0.28); z-index: 800; }
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
  const bg = kind === 'error' ? 'var(--coral-2)'
    : kind === 'success' ? 'var(--green-dark)'
    : 'var(--primary-dark)';
  return (
    <div
      role="status"
      aria-live="polite"
      key={toast._id}
      className="lh-overlay"
      style={{
        position: 'fixed', top: 18, right: 18, zIndex: 999,
        background: bg, color: '#fff', padding: '10px 16px',
        borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-lg)',
        fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 500, maxWidth: 360,
        animation: 'lh-toast-in .18s ease',
      }}
    >
      {toast.msg}
    </div>
  );
}

// ── Layout primitives ────────────────────────────────────────────────────
const card = {
  background: 'var(--card)', border: '1px solid var(--rule)',
  borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-sm)',
};

function PageHeader({ title, subtitle, actions, tabs, activeTab, onTab }) {
  return (
    <header style={{ marginBottom: 18 }}>
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
                }}>{t}</button>
            );
          })}
        </div>
      )}
    </header>
  );
}

function EmptyState({ icon = '◌', title, hint, action }) {
  return (
    <div style={{ ...card, padding: '48px 24px', textAlign: 'center', color: 'var(--muted)' }}>
      <div aria-hidden="true" style={{ fontSize: 32, marginBottom: 8, opacity: 0.5 }}>{icon}</div>
      <div style={{ fontFamily: 'var(--serif)', fontSize: 16, color: 'var(--ink-2)' }}>{title}</div>
      {hint && <div style={{ fontSize: 13, marginTop: 6, lineHeight: 1.5 }}>{hint}</div>}
      {action && <div style={{ marginTop: 16 }}>{action}</div>}
    </div>
  );
}

function Loading({ label = 'Loading…' }) {
  return (
    <div role="status" aria-live="polite"
      style={{ padding: 40, display: 'flex', alignItems: 'center', justifyContent: 'center',
        gap: 10, color: 'var(--muted)', fontFamily: 'var(--sans)', fontSize: 13 }}>
      <span aria-hidden="true" style={{
        width: 14, height: 14, border: '2px solid var(--rule)',
        borderTopColor: 'var(--primary)', borderRadius: '50%',
        display: 'inline-block', animation: 'lh-spin .7s linear infinite',
      }} />
      {label}
    </div>
  );
}

function Skeleton({ rows = 3 }) {
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

function ErrorBox({ message, onRetry }) {
  return (
    <div role="alert" style={{ ...card, padding: 16, borderLeft: '4px solid var(--coral-2)',
      color: 'var(--coral-2)', fontFamily: 'var(--sans)', fontSize: 13,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <span>{message || 'Something went wrong.'}</span>
      {onRetry && (
        <Btn kind="ghost" size="sm" onClick={onRetry} aria-label="Retry">Retry</Btn>
      )}
    </div>
  );
}

function Btn({ children, onClick, kind = 'primary', size = 'md', style, ...rest }) {
  const base = {
    cursor: 'pointer', fontFamily: 'var(--sans)', fontWeight: 600,
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
  return (
    <button type="button" className="lh-btn" onClick={onClick}
      style={{ ...base, ...(kinds[kind] || kinds.primary), ...style }} {...rest}>
      {children}
    </button>
  );
}

function DataTable({ columns, rows, onRow, activeRow, empty }) {
  const cols = columns || [];
  if (!rows || rows.length === 0) return empty || null;
  return (
    <div style={{ ...card, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--sans)' }}>
        <thead>
          <tr style={{ background: 'var(--rule-soft)' }}>
            {cols.map((c) => (
              <th key={c.key} scope="col" style={{ textAlign: 'left', padding: '9px 14px',
                fontSize: 10.5, fontWeight: 700, letterSpacing: '0.06em',
                textTransform: 'uppercase', color: 'var(--muted)' }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const key = (r && r._key != null) ? r._key : i;
            const active = activeRow != null && activeRow === key;
            const clickable = !!onRow;
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
                  background: active ? 'var(--rule-soft)' : 'transparent',
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
  const p = (phrase || '').toString();
  const klass = !p ? 'even'
    : /certain|very likely|highly likely/i.test(p) ? 'high'
    : /likely/i.test(p) ? 'likely'
    : /unlikely|remote|improbable/i.test(p) ? 'unlikely'
    : 'even';
  return (
    <span className={`wep ${klass}`} title={band != null ? `confidence ${band}` : undefined}>
      {p || 'unrated'}
    </span>
  );
}

function StatusPill({ status }) {
  const s = (status || '').toString();
  const map = {
    running: 'running', active: 'running', published: 'running',
    queued: 'queued', pending: 'queued',
    review: 'review', staged: 'review',
    paused: 'paused', rejected: 'paused', cancelled: 'paused',
    failed: 'review', done: 'paused', completed: 'paused',
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

function SidePane({ title, onClose, children }) {
  const ref = useRef(null);
  useFocusTrap(ref, onClose);
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
          padding: '16px 20px', borderBottom: '1px solid var(--rule)' }}>
          <h2 style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
            margin: 0, color: 'var(--ink)' }}>{title}</h2>
          <button type="button" className="lh-btn lh-focusable" onClick={onClose} aria-label="Close panel"
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20,
              lineHeight: 1, color: 'var(--muted)', padding: 4 }}>×</button>
        </div>
        <div style={{ padding: 20, overflow: 'auto', flex: 1 }}>{children}</div>
      </aside>
    </React.Fragment>
  );
}

function Modal({ title, onClose, children }) {
  const ref = useRef(null);
  useFocusTrap(ref, onClose);
  return (
    <div className="lh-scrim lh-overlay" onClick={onClose}
      style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        padding: '8vh 16px', overflow: 'auto', zIndex: 900 }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title || 'Dialog'} tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{ ...card, width: 460, maxWidth: '100%', boxShadow: 'var(--shadow-lg)',
          animation: 'lh-modal-in .18s ease', outline: 'none' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 20px', borderBottom: '1px solid var(--rule)' }}>
          <h2 style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 700,
            margin: 0, color: 'var(--ink)' }}>{title}</h2>
          <button type="button" className="lh-btn lh-focusable" onClick={onClose} aria-label="Close dialog"
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20,
              lineHeight: 1, color: 'var(--muted)', padding: 4 }}>×</button>
        </div>
        <div style={{ padding: 20 }}>{children}</div>
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

Object.assign(window, {
  apiGet, apiPost, apiPatch, apiDelete, useApi, useEvents, useToast,
  Toast, PageHeader, EmptyState, Loading, Skeleton, ErrorBox, Btn, DataTable,
  ConfidencePill, StatusPill, Bar, SidePane, Modal, Field, Row, Metric, card,
});
