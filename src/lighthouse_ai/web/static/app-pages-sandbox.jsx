// app-pages-sandbox.jsx — the Sandbox tab.
//
// The Sandbox is the secured place where your uploaded data and the assistant's
// analysis artifacts live. Two zones: "Your uploads" (read-only to the
// assistant) and "Assistant workspace" (analysis results). Every file is
// security-scanned on the way in; a configurable size limit keeps it bounded
// and the oldest unpinned items are removed first when it fills.
//
// Reads /api/sandbox (items + usage + breakdown), uploads via
// /api/sandbox/upload, pins/deletes, and sets the size via /api/sandbox/config.
// Pure babel-standalone JSX — primitives come from window.* (app-lib.jsx).

const SB_ZONE_LABEL = { uploads: 'Your uploads', workspace: 'Results' };
const SB_VERDICT = {
  admit: { label: 'Scanned · clean', color: '#1a7f4b', bg: '#e6f4ec' },
  quarantine: { label: 'Quarantined', color: '#8a5a00', bg: '#fbeecf' },
  reject: { label: 'Blocked', color: '#a12d2d', bg: '#f7e0e0' },
};

function sbFmtBytes(n) {
  if (n == null) return '—';
  if (n < 1024) return n + ' B';
  const u = ['KB', 'MB', 'GB', 'TB'];
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(v < 10 ? 1 : 0) + ' ' + u[i];
}

function SbBadge({ text, color, bg, title }) {
  return (
    <span title={title} style={{
      display: 'inline-block', padding: '1px 8px', borderRadius: 999,
      fontSize: 11, fontWeight: 600, color: color || 'var(--ink)',
      background: bg || 'var(--paper-2, #eee)', whiteSpace: 'nowrap',
    }}>{text}</span>
  );
}

// Horizontal stacked bar for a {key,count,bytes}[] breakdown.
function SbBreakdownBar({ title, rows, colorFor }) {
  const total = rows.reduce((a, r) => a + (r.bytes || 0), 0) || 1;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{title}</div>
      <div style={{ display: 'flex', height: 14, borderRadius: 6, overflow: 'hidden',
        background: 'var(--paper-2,#eee)' }}>
        {rows.map((r, i) => (
          <div key={r.key} title={`${r.key}: ${r.count} · ${sbFmtBytes(r.bytes)}`}
            style={{ width: `${Math.max(2, (r.bytes / total) * 100)}%`,
              background: colorFor(r.key, i) }} />
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 5 }}>
        {rows.map((r, i) => (
          <span key={r.key} style={{ fontSize: 11, color: 'var(--ink-2,#666)' }}>
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2,
              background: colorFor(r.key, i), marginRight: 4 }} />
            {r.key} ({r.count})
          </span>
        ))}
      </div>
    </div>
  );
}

const SB_PALETTE = ['#3b6ea5', '#5aa17f', '#c08552', '#8a6fb0', '#b05a7a', '#5a8aa0', '#9a9a5a'];

function SandboxPage() {
  const { data, loading, error, reload } = window.useApi('/api/sandbox', { pollMs: 0 });
  const cfg = window.useApi('/api/sandbox/config', { pollMs: 0 });
  const toast = window.useToast ? window.useToast() : { show: () => {} };
  const [busy, setBusy] = React.useState(false);
  const [zoneFilter, setZoneFilter] = React.useState('all');
  const fileRef = React.useRef(null);

  const items = (data && data.items) || [];
  const usage = (data && data.usage) || { used_bytes: 0, max_bytes: null, by_zone: {} };
  const breakdown = (data && data.breakdown) || { by_zone: [], by_type: [], by_source: [] };
  const pct = usage.max_bytes ? Math.min(100, (usage.used_bytes / usage.max_bytes) * 100) : null;
  const near = pct != null && pct >= 85;

  const shown = items.filter((it) => zoneFilter === 'all' || it.zone === zoneFilter);
  const colorFor = (_k, i) => SB_PALETTE[i % SB_PALETTE.length];

  async function onUpload(ev) {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    setBusy(true);
    try {
      const b64 = await new Promise((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(String(fr.result).split(',')[1] || '');
        fr.onerror = rej;
        fr.readAsDataURL(file);
      });
      const r = await window.apiPost('/api/sandbox/upload', {
        filename: file.name, content_base64: b64,
        content_type: file.type || null,
      });
      const v = SB_VERDICT[r.scan_verdict] || {};
      toast.show(`Added "${r.filename}" — ${v.label || r.scan_verdict}`, 'success');
      reload();
    } catch (e) {
      // 422 = security scan rejected; surface plainly.
      const msg = (e && e.message) || 'upload failed';
      toast.show(/422|reject/i.test(msg) ? 'File blocked by the security scan.' : msg, 'error');
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  async function onPin(it) {
    try { await window.apiPost(`/api/sandbox/${it.id}/pin`, { pinned: !it.pinned }); reload(); }
    catch (e) { toast.show((e && e.message) || 'pin failed', 'error'); }
  }
  async function onDelete(it) {
    if (!window.confirm(`Delete "${it.filename || it.id}"?`)) return;
    try { await window.apiDelete(`/api/sandbox/${it.id}`); reload(); }
    catch (e) { toast.show((e && e.message) || 'delete failed', 'error'); }
  }
  async function onSetLimit() {
    const cur = cfg.data && cfg.data.max_bytes;
    const def = cur == null ? '' : String(Math.round(cur / (1024 * 1024)));
    const raw = window.prompt('Sandbox size limit in MB (blank = unlimited):', def);
    if (raw === null) return;
    const mb = raw.trim() === '' ? null : parseInt(raw, 10);
    if (mb !== null && (isNaN(mb) || mb < 0)) { toast.show('Enter a number ≥ 0.', 'error'); return; }
    try {
      await window.apiPatch('/api/sandbox/config', { max_bytes: mb == null ? null : mb * 1024 * 1024 });
      toast.show('Size limit updated.', 'success');
      cfg.reload(); reload();
    } catch (e) { toast.show((e && e.message) || 'failed', 'error'); }
  }

  const Btn = window.Btn;
  const quarantined = items.filter((i) => i.scan_verdict === 'quarantine').length;

  return (
    <div>
      <window.PageHeader
        title="Data Sandbox"
        subtitle="Upload data for Lighthouse to analyze — every file is virus-scanned first."
        actions={
          <span style={{ display: 'flex', gap: 8 }}>
            <Btn kind="ghost" onClick={onSetLimit}>Size limit</Btn>
            <Btn kind="primary" loading={busy} onClick={() => fileRef.current && fileRef.current.click()}>
              Upload data
            </Btn>
            <input ref={fileRef} type="file" onChange={onUpload} style={{ display: 'none' }} />
          </span>
        }
      />

      {loading && <window.Loading />}
      {error && <div style={{ ...window.card, padding: 20, color: 'var(--danger,#a12d2d)' }}>
        Could not load the sandbox. <Btn kind="ghost" onClick={reload}>Retry</Btn></div>}

      {!loading && !error && (
        <React.Fragment>
          {/* Usage gauge */}
          <div style={{ ...window.card, padding: 18, marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
              <strong>Storage used</strong>
              <span style={{ color: near ? 'var(--danger,#a12d2d)' : 'var(--ink-2,#666)' }}>
                {sbFmtBytes(usage.used_bytes)}{usage.max_bytes != null
                  ? ` / ${sbFmtBytes(usage.max_bytes)}` : ' (no limit set)'}
              </span>
            </div>
            <div style={{ height: 12, borderRadius: 6, background: 'var(--paper-2,#eee)', overflow: 'hidden' }}>
              {pct != null && <div style={{ width: `${pct}%`, height: '100%',
                background: near ? 'var(--danger,#c0563f)' : 'var(--primary,#3b6ea5)' }} />}
            </div>
            {near && <div style={{ fontSize: 11, color: 'var(--danger,#a12d2d)', marginTop: 5 }}>
              Near the limit — oldest unpinned items are removed first. Pin anything you want to keep.</div>}
            <div style={{ display: 'flex', gap: 18, marginTop: 10, fontSize: 12, color: 'var(--ink-2,#666)' }}>
              <span>Your uploads: {sbFmtBytes((usage.by_zone || {}).uploads || 0)}</span>
              <span>Results: {sbFmtBytes((usage.by_zone || {}).workspace || 0)}</span>
              {quarantined > 0 && <span style={{ color: '#8a5a00' }}>{quarantined} quarantined</span>}
            </div>
          </div>

          {/* Breakdown viz */}
          {items.length > 0 && (
            <div style={{ ...window.card, padding: 18, marginBottom: 16 }}>
              <SbBreakdownBar title="By zone" rows={breakdown.by_zone} colorFor={colorFor} />
              <SbBreakdownBar title="By type" rows={breakdown.by_type} colorFor={colorFor} />
              <SbBreakdownBar title="By source" rows={breakdown.by_source} colorFor={colorFor} />
            </div>
          )}

          {/* Zone filter */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            {['all', 'uploads', 'workspace'].map((z) => (
              <Btn key={z} kind={zoneFilter === z ? 'primary' : 'ghost'} size="sm"
                onClick={() => setZoneFilter(z)}>
                {z === 'all' ? 'All' : SB_ZONE_LABEL[z]}
              </Btn>
            ))}
          </div>

          {/* File list */}
          {shown.length === 0 ? (
            <div style={{ ...window.card, padding: 40, textAlign: 'center', color: 'var(--ink-2,#666)' }}>
              {items.length === 0
                ? 'Nothing in the sandbox yet. Upload data to analyze it securely — every file is scanned first.'
                : 'No items in this zone.'}
            </div>
          ) : (
            <div style={{ ...window.card, padding: 0, overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ textAlign: 'left', background: 'var(--paper-2,#f4f4f4)' }}>
                    <th style={{ padding: '8px 12px' }}>Name</th>
                    <th style={{ padding: '8px 12px' }}>Zone</th>
                    <th style={{ padding: '8px 12px' }}>Type</th>
                    <th style={{ padding: '8px 12px' }}>Size</th>
                    <th style={{ padding: '8px 12px' }}>Source</th>
                    <th style={{ padding: '8px 12px' }}>Security</th>
                    <th style={{ padding: '8px 12px' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((it) => {
                    const v = SB_VERDICT[it.scan_verdict] || {};
                    return (
                      <tr key={it.id} style={{ borderTop: '1px solid var(--line,#eee)' }}>
                        <td style={{ padding: '8px 12px' }}>
                          {it.pinned && <span title="Pinned — never auto-removed" aria-label="Pinned"
                            style={{ marginRight: 5, display: 'inline-flex', verticalAlign: 'middle',
                              color: 'var(--primary)' }}>
                            <window.NavIcon name="pin" size={13} /></span>}
                          {it.filename || <em>untitled</em>}
                        </td>
                        <td style={{ padding: '8px 12px' }}>
                          <SbBadge text={SB_ZONE_LABEL[it.zone] || it.zone} />
                        </td>
                        <td style={{ padding: '8px 12px', color: 'var(--ink-2,#666)' }}>{it.preview_type || '—'}</td>
                        <td style={{ padding: '8px 12px' }}>{sbFmtBytes(it.size_bytes)}</td>
                        <td style={{ padding: '8px 12px', color: 'var(--ink-2,#666)' }}>{it.source}</td>
                        <td style={{ padding: '8px 12px' }}>
                          <SbBadge text={v.label || it.scan_verdict} color={v.color} bg={v.bg} />
                        </td>
                        <td style={{ padding: '8px 12px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                          <Btn kind="ghost" size="sm" onClick={() => onPin(it)}>
                            {it.pinned ? 'Unpin' : 'Pin'}</Btn>
                          <Btn kind="ghost" size="sm" onClick={() => onDelete(it)}>Delete</Btn>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <p style={{ fontSize: 11, color: 'var(--ink-2,#888)', marginTop: 12 }}>
            Every file is scanned on entry; blocked files are never stored. The assistant can read
            your uploads and write its analysis into its own workspace, but can never modify your
            uploads. Pinned items are protected from automatic cleanup.
          </p>
        </React.Fragment>
      )}
    </div>
  );
}

window.SandboxPage = SandboxPage;
