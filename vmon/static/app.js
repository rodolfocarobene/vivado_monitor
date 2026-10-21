// vmon frontend: vanilla ES module, no dependencies. Data contract: SPEC.md (JSON API).
// Rendering is keyed patching (by firmware id / node id), never whole-page innerHTML,
// so expansion, scroll and CSS animations survive the ~1 s state updates.

/* ------------------------------------------------------------------ config */
// Single place to extend look & wording: status -> icon/color/label, severity -> color/label.
const ICON = {
  done: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" style="fill:var(--ok)"/><path d="M7.5 12.5l3 3 6-6.5" style="fill:none;stroke:var(--on-accent);stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round"/></svg>',
  running: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9.5" style="fill:var(--bg);stroke:var(--line-dim);stroke-width:2"/><g class="spin"><path d="M12 2.5a9.5 9.5 0 0 1 9.5 9.5" style="fill:none;stroke:var(--accent);stroke-width:2.6;stroke-linecap:round"/></g><circle cx="12" cy="12" r="3" style="fill:var(--accent)"/></svg>',
  pending: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" style="fill:var(--bg);stroke:var(--queued);stroke-width:2"/></svg>',
  queued: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" style="fill:var(--bg);stroke:var(--queued);stroke-width:2;stroke-dasharray:3 3"/><circle cx="12" cy="12" r="2" style="fill:var(--queued)"/></svg>',
  failed: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" style="fill:var(--err)"/><path d="M8.5 8.5l7 7M15.5 8.5l-7 7" style="fill:none;stroke:var(--on-status);stroke-width:2.2;stroke-linecap:round"/></svg>',
  skipped: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" style="fill:var(--bg);stroke:var(--queued);stroke-width:2"/><path d="M8 12h8" style="stroke:var(--queued);stroke-width:2;stroke-linecap:round"/></svg>',
  stopped: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" style="fill:var(--stopped)"/><path d="M9.5 8v8M14.5 8v8" style="fill:none;stroke:var(--on-accent);stroke-width:2.4;stroke-linecap:round"/></svg>',
};
const STATUS = {
  pending: { icon: ICON.pending, label: 'Pending' }, queued: { icon: ICON.queued, label: 'Queued' },
  running: { icon: ICON.running, label: 'Running' }, done: { icon: ICON.done, label: 'Done' },
  failed: { icon: ICON.failed, label: 'Failed' }, skipped: { icon: ICON.skipped, label: 'Skipped' },
  stopped: { icon: ICON.stopped, label: 'Stopped' }, idle: { icon: ICON.pending, label: 'Idle' },
};
const statusInfo = (s) => STATUS[s] || STATUS.pending;
// "Done" only says the flow ran to the end; when final timing failed, the outcome is what matters.
const outcomeOf = (fw) => (fw.status === 'done' && fw.timing && fw.timing.final && fw.timing.met === false
  ? { key: 'done-fail', label: 'Timing not met', pill: 'Finished, timing not met' }
  : { key: fw.status, label: statusInfo(fw.status).label, pill: fw.status });
// order = display order; cls maps to .sev-* in style.css
const SEVERITIES = [
  { key: 'error', short: 'E', label: 'Errors', cls: 'sev-error', var: '--err' },
  { key: 'critical', short: 'CW', label: 'Critical warnings', cls: 'sev-critical', var: '--crit' },
  { key: 'warning', short: 'W', label: 'Warnings', cls: 'sev-warning', var: '--warn' },
  { key: 'info', short: 'I', label: 'Info', cls: 'sev-info', var: '--info' },
];
const sevInfo = (k) => SEVERITIES.find((s) => s.key === k) || SEVERITIES[3];
const ALERT_ICON = {
  error: '<svg viewBox="0 0 20 20" class="aicon"><circle cx="10" cy="10" r="9" style="fill:var(--err)"/><path d="M10 5.5v5.5M10 13.6v.9" style="stroke:var(--on-status);stroke-width:2;stroke-linecap:round"/></svg>',
  warning: '<svg viewBox="0 0 20 20" class="aicon"><path d="M10 2L19 18H1z" style="fill:var(--warn);stroke:var(--warn);stroke-width:1.5;stroke-linejoin:round"/><path d="M10 8v4.5M10 14.6v.8" style="stroke:var(--on-accent);stroke-width:2;stroke-linecap:round"/></svg>',
};
const alertIcon = (lvl) => ALERT_ICON[lvl] || ALERT_ICON.warning;
const TIMING_FIELDS = [['wns', 'WNS'], ['tns', 'TNS'], ['whs', 'WHS'], ['ths', 'THS']];
const NO_FETCH = new Set(['pending', 'queued', 'skipped']);
const CHEV = '<svg class="chev" viewBox="0 0 16 16"><path d="M6 3.5l4.5 4.5L6 12.5" style="fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" fill="currentColor"/></svg>';
const SUN = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';

/* ------------------------------------------------------------------ helpers */
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const nowS = () => Date.now() / 1000;
const lsGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } };

function fmtDur(s) {
  if (s == null || !isFinite(s)) return '—';
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (s < 3600) return `${m}m ${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
}
function fmtClock(t) {
  if (t == null) return '—';
  const d = new Date(t * 1000), n = new Date();
  const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  return d.toDateString() === n.toDateString() ? hm : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${hm}`;
}
const DOC_ICON = '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2.5h4.5V7M13.5 2.5L7.5 8.5M12 9.5v3a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3"/></svg>';
// Docs link: opens in a new tab; data-act="doc" lets the click handler ignore it so cards don't toggle.
const docBtn = (url, what = 'documentation') => (url ? `<a class="docbtn" data-act="doc" href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="Open ${esc(what)} (new tab)" aria-label="Open ${esc(what)}">${DOC_ICON}<span>docs</span></a>` : '');
const fmtNs = (v) => (v == null ? '—' : v.toFixed(3));
const fmtMem = (mb) => (mb == null ? '' : mb > 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`);
const fmtNum = (n) => (n >= 10000 ? `${(n / 1000).toFixed(1)}k` : String(n));

function setHTML(el, html) { if (el._h !== html) { el._h = html; el.innerHTML = html; } }
function setText(el, t) { if (el._t !== t) { el._t = t; el.textContent = t; } }
function setAttr(el, k, v) { if (el.getAttribute(k) !== String(v)) el.setAttribute(k, v); }
function h(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }

// Keyed list patching: reuse elements by key, create missing, reorder, drop stale.
function patchList(container, items, keyOf, create, update) {
  const existing = new Map();
  for (const ch of container.children) if (ch._key !== undefined) existing.set(ch._key, ch);
  const seen = new Set();
  items.forEach((it, i) => {
    const k = keyOf(it);
    let el = existing.get(k);
    if (!el) { el = create(it); el._key = k; }
    update(el, it);
    const at = container.children[i];
    if (at !== el) container.insertBefore(el, at || null);
    seen.add(k);
  });
  for (const [k, el] of existing) if (!seen.has(k)) el.remove();
}

// Carried timing: metric value kept from an earlier summary because the latest one lacks it.
const carriedOf = (t, k) => (t && t.carried && t.carried[k]) || null;
const carriedTip = (c) => `from ${c.label || 'an earlier summary'} (not in the latest summary)`;
// Node label; a predicted number (expected phase not started yet) is muted + italic.
function labelHTML(n) {
  const L = esc(n.label);
  if (!n.number_predicted || !n.number) return L;
  const re = new RegExp(`(^|\\s)(${String(n.number).replace(/\./g, '\\.')})(?=\\s|$)`);
  return L.replace(re, '$1<span class="pnum" title="predicted number">$2</span>');
}

function walk(nodes, fn) { for (const n of nodes || []) { fn(n); walk(n.children, fn); } }

/* ------------------------------------------------------------------ state */
const params = new URLSearchParams(location.search);
const MOCK = params.get('mock') === '1' || params.get('mock') === 'true';
let state = { firmwares: [] };
let selected = lsGet('vmon.tab');
let firstLoad = true;
const ui = {
  open: new Map(),        // `${fw}|${node}` -> bool (explicit user choice)
  tab: new Map(),         // node key -> details tab
  flow: new Map(),        // fw id -> selected flow id
  det: new Map(),         // node key -> fetched details state
  sel: new Map(),         // fw id -> {id, follow}: selected top-level stage in the left column
  view: new Map(),        // fw id -> 'flow' | 'messages'
  mv: new Map(),          // fw id -> messages (triage) view state
  auto: new Map(),        // fw id -> {keys:Set auto-opened node keys, dismissed:Set, sig}: follow-live auto-expansion
  rsel: new Map(),        // node key -> path of the report shown in the Reports tab
  paths: new Map(),       // `${fw}|${report path}` -> worst-paths table state (filters, expanded rows, fetched data)
};
let hashOpen = new Set();
let hashTab = new Map();
let hashFw = null;
let hashScroll = null, hashShift = null, hashDebug = null;
let hashFx = null; // #fx=cur,a1: pre-open failure log excerpts (screenshots/debug)
let hashSel = null, hashSelPending = false, hashView = null, hashMsg = null, hashExcerpt = false;
let hashPth = []; // #pth=0,3: pre-expand those worst-path rows (screenshots/debug)

function parseHash() {
  const p = new URLSearchParams(location.hash.replace(/^#/, ''));
  hashOpen = new Set((p.get('expand') || '').split(',').filter(Boolean));
  hashTab = new Map();
  for (const t of (p.get('tab') || '').split(',').filter(Boolean)) {
    const i = t.lastIndexOf(':');
    if (i > 0) hashTab.set(t.slice(0, i), t.slice(i + 1));
  }
  hashFw = p.get('fw'); hashFx = p.get('fx') ? new Set(p.get('fx').split(',')) : null;
  hashSel = p.get('sel'); hashSelPending = !!hashSel;
  hashScroll = p.get('scroll') != null ? +p.get('scroll') : null; hashDebug = p.get('debug'); hashShift = p.get('shift') != null ? +p.get('shift') : null; hashView = p.get('view'); hashMsg = p.get('msg'); hashExcerpt = p.get('excerpt') === '1';
  hashPth = (p.get('pth') || '').split(',').filter(Boolean).map(Number);
  if (p.get('theme')) applyTheme(p.get('theme'));
  if (p.get('popover') === 'notif' && typeof openPop === 'function') openPop();
  if (p.get('popover') === 'explore' && typeof openExplore === 'function') openExplore(p.get('path'));
}

const keyOf = (fw, n) => `${fw.id}|${n.id}`;
const autoOf = (fw) => { let a = ui.auto.get(fw.id); if (!a) { a = { keys: new Set(), dismissed: new Set(), sig: null }; ui.auto.set(fw.id, a); } return a; };
const isOpen = (fw, n) => (ui.open.has(keyOf(fw, n)) ? ui.open.get(keyOf(fw, n)) : (autoOf(fw).keys.has(keyOf(fw, n)) || hashOpen.has(n.id)));
const curFw = () => state.firmwares.find((f) => f.id === selected);
const curView = (fw) => ui.view.get(fw.id) || (hashView === 'messages' || hashView === 'timing' ? hashView : 'flow');

// Forget open-state, chosen details tab and fetched data of a node and all its descendants,
// so that reopening it looks freshly opened.
function resetNode(fw, n, withSelf = true) {
  walk(withSelf ? [n] : n.children, (x) => {
    const k = keyOf(fw, x);
    ui.open.delete(k); ui.tab.delete(k); ui.det.delete(k); autoOf(fw).keys.delete(k);
    hashOpen.delete(x.id); hashTab.delete(x.id);
  });
}

/* ------------------------------------------------------------------ API (real + mock) */
const mock = { base: null, logs: {}, tick: 0, rules: {}, files: {} };

async function jget(url) {
  if (MOCK) return syncJson(url); // sync on purpose: deterministic headless screenshots
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

function shiftTimes(o, d) {
  if (Array.isArray(o)) { o.forEach((x) => shiftTimes(x, d)); return o; }
  if (o && typeof o === 'object') {
    for (const k of Object.keys(o)) {
      if (['started_at', 'ended_at', 'updated_at', 'generated_at', 't', 'mtime', 'expected_end'].includes(k) && typeof o[k] === 'number') o[k] += d;
      else shiftTimes(o[k], d);
    }
  }
  return o;
}

const strHash = (s) => { let x = 0; for (const c of s) x = (x * 31 + c.charCodeAt(0)) >>> 0; return x; };

const q = encodeURIComponent;

// Per-node messages: groups come from /api/triage (importance order), instances from /api/messages.
// All four severities on purpose: every message counted on a step (incl. info) must be reachable.
const SEV_ALL = 'error,critical,warning,info';
async function apiMessages(fw, node) {
  if (!MOCK) {
    const [msgs, tri] = await Promise.all([
      jget(`/api/messages?fw=${q(fw.id)}&node=${q(node.id)}&sev=${SEV_ALL}&limit=2000`),
      jget(`/api/triage?fw=${q(fw.id)}&node=${q(node.id)}&sev=${SEV_ALL}&include_muted=1&limit=500`).catch(() => null),
    ]);
    if (tri && tri.groups) msgs.groups = tri.groups;
    return msgs;
  }
  const d = await mockMessagesFile(fw);
  const isRoot = !node.id.includes('/') || node.kind === 'step';
  const groups = mockTriage(fw, { muted: true, sev: SEV_ALL }).groups.filter((g) => isRoot || strHash(node.id + g.id) % 3 === 0 || g.severity === 'error');
  const ids = new Set(groups.map((g) => g.id));
  return { node_id: node.id, groups, items: d.items.filter((m) => ids.has(m.id)) };
}

// Firmware-wide triage (Messages view).
async function apiTriage(fw, { q: text = '', muted = false, sev = SEV_ALL } = {}) {
  if (!MOCK) return jget(`/api/triage?fw=${q(fw.id)}&sev=${q(sev)}&include_muted=${muted ? 1 : 0}&limit=500${text ? `&q=${q(text)}` : ''}`);
  return mockTriage(fw, { q: text, muted, sev });
}
async function apiInstances(fw, id) {
  if (!MOCK) return jget(`/api/messages?fw=${q(fw.id)}&id=${q(id)}&limit=200`);
  const d = await mockMessagesFile(fw);
  return { node_id: '', groups: [], items: d.items.filter((m) => m.id === id).slice(0, 200) };
}
async function apiLogAround(fw, log, line) {
  if (!MOCK) return jget(`/api/log?fw=${q(fw.id)}&log=${q(log)}&around=${line}&context=30`);
  return mockLogAround(fw, log, line);
}
async function apiMsgRule(fw, id, priority) {
  if (!MOCK) {
    const r = await fetch('/api/msgrule', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, priority }) });
    if (!r.ok) throw new Error(await r.text() || r.status);
    return;
  }
  mock.rules[`${fw.id}|${id}`] = priority;
}
async function apiSettings(interval) {
  if (!MOCK) {
    const r = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ interval }) });
    if (!r.ok) throw new Error(await r.text() || r.status);
    return;
  }
  state.settings = { interval };
}

async function apiReportRaw(fw, path) {
  if (MOCK) return (await jget('mock/report_raw.txt.json')).text;
  const r = await fetch(`/api/report?fw=${encodeURIComponent(fw.id)}&path=${encodeURIComponent(path)}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.text();
}

async function apiLog(fw, node) {
  if (!MOCK) return jget(`/api/log?fw=${encodeURIComponent(fw.id)}&node=${encodeURIComponent(node.id)}&tail=300`);
  const name = fw.name;
  if (!mock.logs[name]) {
    try { mock.logs[name] = await jget(`mock/log_${name}.json`); } catch { mock.logs[name] = await jget('mock/log_default.json'); }
  }
  return mock.logs[name];
}

// Mock endpoints mirror the real ones (shapes per SPEC.md v2); data lives in mock/*.json.
async function mockFile(name, fallback) {
  if (!mock.files[name]) { try { mock.files[name] = await jget(`mock/${name}.json`); } catch { mock.files[name] = fallback ? await jget(`mock/${fallback}.json`) : { groups: [], items: [] }; } }
  return mock.files[name];
}
function mockFileSync(name, fallback) {
  if (!mock.files[name]) { try { mock.files[name] = syncJson(`mock/${name}.json`); } catch { mock.files[name] = syncJson(`mock/${fallback}.json`); } }
  return mock.files[name];
}
const mockMessagesFile = (fw) => mockFile(`messages_${fw.name}`, 'messages_default');
function mockTriage(fw, { q: text = '', muted = false, sev = 'error,critical,warning' } = {}) {
  const want = new Set(sev.split(','));
  const d = mockFileSync(`triage_${fw.name}`, 'triage_default');
  const ql = text.trim().toLowerCase();
  const groups = d.groups.map((g) => {
    const r = mock.rules[`${fw.id}|${g.id}`];
    if (r === undefined) return { ...g };
    return { ...g, user_priority: r, score: g.score + (r === 'high' ? 4 : 0) };
  }).filter((g) => (muted || (g.user_priority !== 'mute' && g.priority !== 'mute' || g.user_priority === 'high'))
    && want.has(g.severity) && (!ql || `${g.id} ${g.text}`.toLowerCase().includes(ql)));
  groups.sort((a, b) => b.score - a.score);
  return { baseline: d.baseline, groups };
}
const mockTop = (fw) => mockTriage(fw).groups.filter((g) => ['error', 'critical', 'warning'].includes(g.severity)).slice(0, 5);
function mockLogAround(fw, log, line) {
  let fail = null;
  for (const f of fw.flows || []) walk(f.stages, (n) => {
    if (n.failure && n.failure.line === line) fail = n.failure;
    (n.attempts || []).forEach((a) => { if (a.failure && a.failure.line === line) fail = a.failure; });
  });
  if (fail) {
    const noise = ['Phase 4.1 Global Iteration 0', 'Time (s): cpu = 00:04:12 ; elapsed = 00:02:31 . Memory (MB): peak = 7245.3 ; gain = 12.0', 'Router Utilization Summary', '  Global Vertical Routing Utilization    = 31.2 %', 'Phase 4.2 Global Iteration 1', 'Number of Nodes with overlaps = 18294', 'Phase 4.2.1 Update Timing', 'Phase 4.2.2 Resolve XTalk'];
    const pre = Array.from({ length: 24 }, (_, i) => noise[i % noise.length]);
    const post = ['Vivado exited abnormally.', '', '# Wrote log to runme.log'];
    const lines = [...pre, ...(fail.details || []), ...post];
    const start = line - pre.length;
    return { path: log || fail.log, start_line: start, end_line: start + lines.length - 1, lines };
  }
  const d = mockFileSync(`messages_${fw.name}`, 'messages_default');
  const hit = d.items.find((m) => m.line === line);
  const pool = ['Phase 1.2 IO Placement/ Clock Placement/ Build Placer Device', 'INFO: [Timing 38-35] Done setting XDC timing constraints.', 'Time (s): cpu = 00:00:12 ; elapsed = 00:00:09 . Memory (MB): peak = 3050.2 ; gain = 0.0',
    'Starting Placer Task', 'INFO: [Project 1-570] Preparing netlist for logic optimization', 'Phase 1.1 Placer Initialization Netlist Sorting | Checksum: 1a2b3c4d', 'Netlist sorting complete.', 'Parsing XDC File [/path/to/lockin.xdc]'];
  const lines = []; const start = Math.max(1, line - 30);
  for (let n = start; n <= line + 30; n++) lines.push(n === line && hit ? `${hit.severity === 'critical' ? 'CRITICAL WARNING' : hit.severity.toUpperCase()}: [${hit.id}] ${hit.text}` : pool[strHash(String(n)) % pool.length]);
  return { path: log || '/path/to/runme.log', start_line: start, end_line: line + 30, lines };
}

/* ------------------------------------------------------------------ alerts */
function fwAlerts(fw) {
  const seen = new Set(); const out = [];
  const add = (a, nid) => {
    const al = { ...a, node_id: a.node_id || nid || null };
    const k = `${al.code}|${al.node_id}|${al.message}`;
    if (!seen.has(k)) { seen.add(k); out.push(al); }
  };
  (fw.alerts || []).forEach((a) => add(a));
  for (const f of fw.flows || []) walk(f.stages, (n) => (n.alerts || []).forEach((a) => add(a, n.id)));
  return out.sort((a, b) => (b.level === 'error') - (a.level === 'error'));
}
const topLevel = (alerts) => (alerts.some((a) => a.level === 'error') ? 'error' : alerts.length ? 'warning' : '');
const nodeLevel = (n) => topLevel(n.alerts || []);

/* ------------------------------------------------------------------ failures and attempts (SPEC v5) */
const CRASH_RE = /signal|segmentation|license|memory|killed|abnormal|crash/i;
const failKind = (f) => (f && (f.hs_err || CRASH_RE.test(f.reason || '')) ? 'Crashed' : 'Failed');
function deepestFailed(n) {
  let cur = n, last = null;
  for (;;) { const c = (cur.children || []).find((x) => x.status === 'failed'); if (!c) return last; last = cur = c; }
}
const failWhere = (n) => { const d = deepestFailed(n); return (d || n).label.replace(/^Phase\s+/, ''); };
const attemptsOf = (n) => (n.attempts && n.attempts.length >= 2 ? n.attempts : []);
const latestAttempt = (n) => { const a = attemptsOf(n); return a.length ? a[a.length - 1] : null; };
function attTags(n) {
  const la = latestAttempt(n);
  if (!la) return '';
  return `<small class="att" title="${attemptsOf(n).length} attempts; counts and children are from the latest">attempt ${la.n}</small>${la.mode === 'resume' ? '<small class="att res" title="Resumed from a checkpoint in a separate Vivado session">resumed</small>' : ''}`;
}
const ATT_ICON = {
  done: ICON.done, running: ICON.running, failed: ICON.failed, stopped: ICON.stopped,
};
const fx = new Map(); // `${fw}|${node}|${attempt}` -> {line, data, fresh}: opened "log around failure" excerpts
const fxKey = (fw, n, tag) => `${fw.id}|${n.id}|${tag}`;
function copyBtn(text, what) { return `<button class="copybtn" data-act="copy" data-copy="${esc(text)}" title="Copy ${esc(what)}">copy</button>`; }
function failureHTML(f, fw, n, tag, where) {
  const key = fxKey(fw, n, tag);
  const ex = fx.get(key);
  const lines = (f.details || []).map((d) => `<div>${esc(d)}</div>`).join('');
  const acts = [];
  if (f.line != null) acts.push(`<button class="fbtn${ex ? ' on' : ''}" data-act="fail-log" data-key="${esc(key)}" data-log="${esc(f.log || '')}" data-line="${f.line}">${ex ? 'Hide log' : 'View log'} around line ${f.line}</button>`);
  if (f.log && f.line == null) acts.push(`<span class="fpath mono" title="Log file">${esc(f.log)}</span>`);
  const hs = f.hs_err ? `<div class="fhs"><span class="k">hs_err</span><span class="mono fpath" title="${esc(f.hs_err)}">${esc(f.hs_err)}</span>${copyBtn(f.hs_err, 'hs_err path')}</div>` : '';
  return `<div class="fbox"><div class="fb-h">${ICON.failed}<b>${failKind(f)}</b><span class="fb-reason">${esc(f.reason || 'Error')}</span>${where ? `<span class="fb-where">in ${esc(where)}</span>` : ''}</div>${lines ? `<div class="fb-lines mono">${lines}</div>` : ''}${acts.length ? `<div class="fb-act">${acts.join('')}</div>` : ''}${hs}${ex ? `<div class="fb-exc">${excerptHTML(ex, { id: key })}</div>` : ''}</div>`;
}
function attemptsHTML(n, fw) {
  const as = attemptsOf(n);
  if (!as.length) return '';
  const cur = as[as.length - 1];
  const rows = as.map((a) => {
    const isCur = a === cur;
    const f = a.failure;
    const when = `${a.started_at ? fmtClock(a.started_at) : '—'} → ${a.ended_at ? fmtClock(a.ended_at) : a.status === 'running' ? 'now' : '—'}`;
    const live = a.status === 'running' && a.started_at && !a.ended_at;
    const dur = live ? `<span data-start="${a.started_at}">${fmtDur(nowS() - a.started_at)}</span>` : a.started_at && a.ended_at ? fmtDur(a.ended_at - a.started_at) : '';
    const open = f && fx.has(`open|${fw.id}|${n.id}|${a.n}`);
    return `<div class="arow${isCur ? ' cur' : ' old'}" data-status="${esc(a.status)}"><div class="a-ic">${(ATT_ICON[a.status] || ICON.pending)}</div>
      <div class="a-main"><div class="a-h"><b>Attempt ${a.n}</b><span class="a-mode">${a.mode === 'resume' ? 'resumed' : a.mode === 'external' ? 'outside project flow (inferred from files)' : 'project run'}</span>${isCur ? '<span class="a-now">latest</span>' : ''}<span class="a-time num">${when}${dur ? ` · ${dur}` : ''}</span></div>
      ${a.log_missing ? '<div class="a-sum a-muted">log no longer available</div>' : a.summary ? `<div class="a-sum">${esc(a.summary)}</div>` : ''}
      ${a.checkpoint ? `<div class="a-cp mono" title="${esc(a.checkpoint)}">from ${esc(a.checkpoint.split('/').pop())}</div>` : ''}
      ${f ? `<div class="a-fail"><b>${failKind(f)}:</b> ${esc(f.reason || 'Error')}${(f.details || f.hs_err) ? ` <button class="fbtn sm" data-act="att-toggle" data-key="open|${esc(fw.id)}|${esc(n.id)}|${a.n}">${open ? 'hide details' : 'details'}</button>` : ''}</div>${open ? failureHTML(f, fw, n, `a${a.n}`, '') : ''}` : ''}
      </div></div>`;
  }).join('');
  return `<div class="attempts"><div class="att-h">Attempts<small>${as.length}</small></div>${rows}</div>`;
}

function findPath(fw, id) {
  for (const f of fw.flows || []) {
    const chain = [];
    const rec = (nodes) => { for (const n of nodes) { chain.push(n); if (n.id === id) return true; if (rec(n.children || [])) return true; chain.pop(); } return false; };
    if (rec(f.stages)) return { flow: f, chain: [...chain] };
  }
  return null;
}

// Switch to the Flow view, select the node's stage and open the chain down to the node.
function gotoNode(fw, id) {
  const hit = id && findPath(fw, id);
  if (!hit) { window.scrollTo({ top: 0, behavior: 'smooth' }); return; }
  ui.flow.set(fw.id, hit.flow.id);
  ui.view.set(fw.id, 'flow');
  ui.sel.set(fw.id, { id: hit.chain[0].id, follow: false });
  hit.chain.forEach((n, i) => {
    ui.open.set(keyOf(fw, n), true);
    if (i < hit.chain.length - 1) ui.tab.set(keyOf(fw, n), 'flow');
  });
  render();
  const root = hit.chain.length === 1 ? mainEl.querySelector('.stagedetail') : null;
  const el = root || [...mainEl.querySelectorAll('.detail .node')].find((e) => e._node && e._node.id === id);
  if (el) {
    setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);
    el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 2200);
  }
}

/* ------------------------------------------------------------------ notifications */
// Driven by Firmware.events. Settings persist in localStorage; the in-app log works even
// without browser permission.
const BASE_TITLE = document.title;
const PAGE_T = MOCK ? nowS() - 7200 : nowS();   // mock: pretend we loaded 2 h ago so seeded events show up
const EVENT_KINDS = [['step_done', 'Step finished'], ['step_failed', 'Step failed'], ['run_done', 'Run finished'], ['run_failed', 'Run failed']];
const ALERT_CODES = [['timing_fail', 'Timing not met'], ['critical_warning', 'Critical warnings'], ['error', 'Errors'], ['drc', 'DRC issues'],
  ['unrouted', 'Unrouted nets'], ['util_high', 'High utilization'], ['stalled', 'Stalled build'], ['route_not_converging', 'Router not converging'], ['process_gone', 'Vivado process gone'], ['other', 'Other alerts']];
const CODE_ALIAS = { utilization: 'util_high', step_failed: 'step_failed' };
const ALERT_NAME = { timing_fail: 'Timing', critical_warning: 'Critical warnings', error: 'Errors', drc: 'DRC', unrouted: 'Unrouted nets',
  util_high: 'Utilization', utilization: 'Utilization', stalled: 'Stalled', route_not_converging: 'Router', process_gone: 'Process gone', step_failed: 'Step failed' };
const alertName = (a) => ALERT_NAME[a.code] || (a.code ? a.code.replace(/_/g, ' ') : a.level);
const NOTIF_DEFAULTS = {
  kinds: { step_done: false, step_failed: true, run_done: true, run_failed: true },
  codes: { timing_fail: true, critical_warning: true, error: true, drc: true, unrouted: true, util_high: true, stalled: true, route_not_converging: true, process_gone: true, other: true },
};
const notif = { cfg: NOTIF_DEFAULTS, log: [], seen: new Set(), open: false };
try {
  const sv = JSON.parse(lsGet('vmon.notif') || 'null');
  if (sv) notif.cfg = { kinds: { ...NOTIF_DEFAULTS.kinds, ...sv.kinds }, codes: { ...NOTIF_DEFAULTS.codes, ...sv.codes } };
} catch { /* defaults */ }
const saveNotif = () => lsSet('vmon.notif', JSON.stringify(notif.cfg));

function eventWanted(ev) {
  if (ev.kind === 'step_started') return false;
  if (ev.kind === 'alert') {
    const c = CODE_ALIAS[ev.code] || ev.code;
    return !!notif.cfg.codes[ALERT_CODES.some(([k]) => k === c) ? c : 'other'];
  }
  return !!notif.cfg.kinds[ev.kind];
}

function eventBody(fw, ev) {
  const hit = ev.node_id && findPath(fw, ev.node_id);
  const step = hit ? (hit.chain.find((n) => n.kind === 'step') || hit.chain[0]).label : '';
  const msg = ev.message || '';
  return step && !msg.startsWith(step) ? `${step}: ${msg}` : msg;
}

const liveEl = $('#sr-live');
let liveT = null;
function announce(text) { // polite, batched: several events in one poll are read as one message
  clearTimeout(liveT);
  liveEl._q = (liveEl._q || []).concat(text);
  liveT = setTimeout(() => { liveEl.textContent = liveEl._q.join(' '); liveEl._q = []; }, 400);
}

function processEvents() {
  let added = false;
  for (const fw of state.firmwares) {
    for (const ev of fw.events || []) {
      const key = `${fw.id}|${ev.t}|${ev.kind}|${ev.node_id}`;
      if (notif.seen.has(key)) continue;
      notif.seen.add(key);
      if (ev.t < PAGE_T || !eventWanted(ev)) continue;
      const entry = { fw: fw.id, fwName: fw.name, t: ev.t, level: ev.level, title: `vmon · ${fw.name} — ${ev.title}`, evTitle: ev.title, body: eventBody(fw, ev), node_id: ev.node_id, read: false };
      notif.log.unshift(entry); added = true; announce(`${fw.name}: ${ev.title}. ${entry.body}`);
      if ('Notification' in window && Notification.permission === 'granted') {
        try {
          const n = new Notification(entry.title, { body: entry.body, tag: key });
          n.onclick = () => { window.focus(); openEntry(entry); n.close(); };
        } catch { /* ignore */ }
      }
    }
  }
  if (notif.log.length > 100) notif.log.length = 100;
  if (added) { syncBell(); if (notif.open) renderPop(); }
}

function checkAlerts() {
  processEvents();
  const anyErr = state.firmwares.some((fw) => fw.status === 'running' && fwAlerts(fw).some((a) => a.level === 'error'));
  const t = (anyErr ? '⚠ ' : '') + BASE_TITLE;
  if (document.title !== t) document.title = t;
}

function openEntry(e) {
  if (!state.firmwares.some((f) => f.id === e.fw)) return;
  selected = e.fw; lsSet('vmon.tab', selected);
  closePop();
  const fw = curFw();
  if (e.node_id) gotoNode(fw, e.node_id); else { ui.view.set(fw.id, 'flow'); render(); }
}

/* ------------------------------------------------------------------ rendering: tabs */
const tabsEl = $('#tabs');
const mainEl = $('#main');

// Fade the strip edge where more tabs are hidden, so a clipped firmware tab reads as "scroll for more".
function syncTabsOverflow() {
  const more = tabsEl.scrollWidth - tabsEl.clientWidth;
  tabsEl.dataset.more = more <= 1 ? '' : [tabsEl.scrollLeft > 1 ? 'left' : '', tabsEl.scrollLeft < more - 1 ? 'right' : ''].join(' ').trim();
}
tabsEl.addEventListener('scroll', syncTabsOverflow, { passive: true });
window.addEventListener('resize', syncTabsOverflow);

function createTab(fw) {
  const el = h('div', 'tab', '<span class="sdot"></span><span class="t-main"><span class="t-name"></span><span class="t-sub"></span></span><span class="abadge" hidden></span><button class="t-x" title="Stop watching (Delete)" aria-hidden="true" tabindex="-1"><svg viewBox="0 0 12 12" width="10" height="10"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button>');
  el.setAttribute('role', 'tab'); el.tabIndex = -1;
  el._r = { dot: $('.sdot', el), name: $('.t-name', el), sub: $('.t-sub', el), ab: $('.abadge', el), x: $('.t-x', el) };
  el.dataset.act = 'tab';
  return el;
}
function updateTab(el, fw) {
  const r = el._r;
  const oc = outcomeOf(fw);
  setAttr(r.dot, 'data-status', oc.key);
  setText(r.name, fw.name);
  let sub;
  if (fw.status === 'running') {
    const cur = fw.current ? esc(fw.current.label) : 'running';
    sub = `${cur} · <span data-start="${fw.started_at ?? ''}">${fmtDur(fw.started_at ? nowS() - fw.started_at : fw.elapsed_s)}</span>${fw.resources ? ` · <span class="t-res" title="Vivado CPU / RSS">${Math.round(fw.resources.cpu_pct)}% · ${fmtMem(fw.resources.rss_mb)}</span>` : ''}`;
  } else sub = `${oc.label} · ${fmtDur(fw.elapsed_s)}`;
  if (fw.attempt && fw.attempt.n > 1) sub = `<span class="t-att">attempt ${fw.attempt.n}</span> · ${sub}`;
  setHTML(r.sub, sub);
  const al = fwAlerts(fw); const lvl = topLevel(al);
  r.ab.hidden = !al.length; setText(r.ab, String(al.length)); setAttr(r.ab, 'data-level', lvl || 'warning');
  el.classList.toggle('active', fw.id === selected); setAttr(el, 'aria-selected', String(fw.id === selected));
  el.tabIndex = fw.id === selected ? 0 : -1; // roving tabindex: one tab stop for the whole strip
  setAttr(el, 'aria-keyshortcuts', fw.live ? '' : 'Delete');
  r.x.hidden = !!fw.live;
  el.title = fw.path || fw.name;
}

/* ------------------------------------------------------------------ rendering: firmware header */
function latestHistory(fw) {
  let best = null;
  const flow = fw.flows.find((f) => f.id === ui.flow.get(fw.id)) || fw.flows[0];
  walk(flow ? flow.stages : [], (n) => { if (n.timing && n.timing.history && n.timing.history.length) best = n; });
  // prefer the last top-level stage with history, falling back to deepest-last
  if (flow) for (const s of [...flow.stages].reverse()) {
    let found = null; walk([s], (n) => { if (!found && n.timing && n.timing.history && n.timing.history.length) found = n; });
    if (found) return found;
  }
  return best;
}

function spark(vals, w, h2, o = {}) {
  vals = vals.filter((v) => v != null);
  if (!vals.length) return '';
  const lo = Math.min(...vals, 0), hi = Math.max(...vals, 0), span = hi - lo || 1, pad = 3;
  const X = (i) => (vals.length === 1 ? w / 2 : pad + (i * (w - 2 * pad)) / (vals.length - 1));
  const Y = (v) => pad + (1 - (v - lo) / span) * (h2 - 2 * pad);
  const last = vals[vals.length - 1];
  const bad = o.warn ? 'var(--warn)' : 'var(--err)';
  const col = last >= 0 ? 'var(--ok)' : bad;
  const pts = vals.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
  const dots = o.dots ? vals.map((v, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="2.4" style="fill:${v >= 0 ? 'var(--ok)' : bad}"/>`).join('') : `<circle cx="${X(vals.length - 1).toFixed(1)}" cy="${Y(last).toFixed(1)}" r="2.6" style="fill:${col}"/>`;
  const attrs = o.fluid ? `viewBox="0 0 ${w} ${h2}" preserveAspectRatio="none" width="100%" height="${h2}"` : `viewBox="0 0 ${w} ${h2}" width="${w}" height="${h2}"`;
  return `<svg class="${o.fluid ? 'bigspark' : 'spark'}" ${attrs}><line x1="0" x2="${w}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" style="stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3;opacity:.6;vector-effect:non-scaling-stroke"/>`
    + (vals.length > 1 ? `<polyline points="${pts}" style="fill:none;stroke:${col};stroke-width:2;stroke-linejoin:round;stroke-linecap:round;vector-effect:non-scaling-stroke"/>` : '')
    + (o.fluid ? '' : dots) + '</svg>';
}

// Severity rule: red/"NOT MET" only for FINAL failing timing; non-final failures are amber ("failing for now").
function timingLevel(t) {
  if (!t || t.met == null) return 'unknown';
  if (t.met) return t.final ? 'ok' : 'track';
  return t.final ? 'fail' : 'warn';
}
// A build that crashed or was stopped never produced final timing: its last estimate is history, not a verdict.
function fwTimingLevel(fw) {
  const tl = timingLevel(fw.timing);
  return tl === 'warn' && ['failed', 'stopped'].includes(fw.status) ? 'halted' : tl;
}
function timingBadge(t, tl = timingLevel(t)) {
  if (tl === 'halted') return ['INCOMPLETE', ''];
  if (tl === 'ok') return ['MET', 'met'];
  if (tl === 'track') return ['ON TRACK', 'met'];
  if (tl === 'fail') return ['NOT MET', 'notmet'];
  if (tl === 'warn') return [/intermediate/i.test(t.stage || t.label || '') ? 'FAILING (intermediate)' : 'FAILING (estimate)', 'warnb'];
  return ['UNKNOWN', ''];
}
function cellClass(key, v) {
  if (v == null) return 'nil';
  if (key === 'tns' || key === 'ths') return v < 0 ? 'neg' : 'pos';
  return v < 0 ? 'neg' : 'pos';
}

function timingFrom(fw) {
  const t = fw.timing; if (!t) return null;
  let found = null;
  for (const f of fw.flows || []) walk(f.stages, (n) => { if (n.timing && n.timing.label === t.label && n.timing.wns === t.wns) found = n; });
  return found;
}

function timingCardHTML(fw) {
  const t = fw.timing;
  const tl = fwTimingLevel(fw);
  const [bl, bc] = timingBadge(t, tl);
  const badge = `<span class="met-badge ${bc}">${bl}</span>`;
  const cells = TIMING_FIELDS.map(([k, lbl]) => {
    const c = carriedOf(t, k);
    return `<div class="tc-cell${c ? ' carried' : ''}"${c ? ` title="${esc(carriedTip(c))}"` : ''}><div class="k">${lbl}${c ? '<i class="ctag">stale</i>' : ''}</div><div class="v num ${cellClass(k, t ? t[k] : null)}">${fmtNs(t ? t[k] : null)}</div></div>`;
  }).join('');
  const hn = latestHistory(fw);
  const sp = hn ? `<span title="WNS history · ${esc(hn.label)}">${spark(hn.timing.history.map((x) => x.wns), 110, 30, { warn: tl !== 'fail' })}</span>` : '';
  const from = timingFrom(fw);
  const stage = t ? (t.stage || t.label || '') : '';
  const src = t ? `${t.source === 'report' ? 'Report' : 'Log'} · ${esc(t.label || '')}${from ? ' · ' + esc(from.label) : ''}` : 'No timing data yet';
  const stageRow = t ? `<div class="tc-stage"><b>${esc(stage)}</b><span class="fin ${t.final ? 'is' : ''}">${t.final ? 'final' : 'not final'}</span></div>` : '';
  const nums = `${t && t.wns != null && t.wns < 0 ? `WNS ${fmtNs(t.wns)} ns` : ''}${t && t.whs != null && t.whs < 0 ? `${t.wns != null && t.wns < 0 ? ', ' : ''}WHS ${fmtNs(t.whs)} ns` : ''}`;
  const verdict = tl === 'fail' ? `<div class="tc-verdict">Final timing fails${from ? ' at <b>' + esc(from.label) + '</b>' : ''}${nums ? ' — ' + nums : ''}</div>`
    : tl === 'warn' ? `<div class="tc-verdict soft">Failing for now${nums ? ': ' + nums : ''} — later steps may still fix it</div>`
    : tl === 'halted' ? `<div class="tc-verdict soft">Build ${fw.status === 'stopped' ? 'stopped' : 'failed'} before final timing${nums ? '; last estimate ' + nums : ''}</div>` : '';
  const pc = t && t.report && t.path_counts && t.path_counts.total ? t.path_counts : null;
  const plural = (n, w) => `${fmtInt(n)} ${w}${n === 1 ? '' : 's'}`;
  const pathLine = !pc ? '' : pc.failing
    ? `<div class="tc-paths bad"><b>${plural(pc.failing, 'failing path')}</b> in ${plural(pc.failing_clocks, 'clock')} <button class="linkbtn" data-act="paths-open" data-failing="1">view →</button></div>`
    : `<div class="tc-paths">Worst slack: setup <b class="num ${slackCls(pc.worst_setup)}">${fmtSlack(pc.worst_setup)}</b> · hold <b class="num ${slackCls(pc.worst_hold)}">${fmtSlack(pc.worst_hold)}</b> <button class="linkbtn" data-act="paths-open">view paths →</button></div>`;
  return { tl, html: `<div class="tc-top"><span class="tc-title">Timing · ns</span>${badge}</div>${stageRow}${verdict}${pathLine}<div class="tc-grid">${cells}</div><div class="tc-foot"><span class="src" title="${src}">${src}</span>${sp}</div>` };
}

function countsHTML(c) {
  return `<div class="counts">${SEVERITIES.map((s) => {
    const v = (c && c[s.key]) || 0;
    return `<span class="cbadge ${s.cls}${v === 0 ? ' zero' : ''}" title="${s.label}"><b>${fmtNum(v)}</b><small>${s.short}</small></span>`;
  }).join('')}</div>`;
}

let head = null;
let infoOpen = lsGet('vmon.infoOpen') === '1'; // closed by default: keeps the stage flow above the fold
function buildView() {
  mainEl.innerHTML = '';
  head = h('section', 'fw-head', `
    <div class="fwl">
      <div class="fw-title"><h1></h1><span class="pill"></span>
        <div class="seg viewseg" role="group" aria-label="View"><button data-act="view" data-view="flow" title="Flow (f)">Flow</button><button data-act="view" data-view="messages" title="Messages (m)">Messages</button><button data-act="view" data-view="timing" title="Timing (t)">Timing</button></div></div>
      <div class="fw-path mono"></div>
      <div class="fw-attempt" hidden></div>
      <div class="now">
        <div class="cur"></div>
        <div class="now-run">
          <div class="kv"><div class="k">Elapsed</div><div class="v num el"></div></div>
          <div class="now-bar"><div class="eprog" hidden><i></i></div><span class="est" hidden></span></div>
          <div class="kv eta-wrap"><div class="k etak">Expected end</div><div class="v num eta"></div><div class="sub2 etasub"></div></div>
        </div>
      </div>
      <div class="fw-meta">
        <div class="kv counts-wrap"><div class="k">Messages</div><div class="cnt"></div></div>
        <div class="kv started-wrap"><div class="k">Started</div><div class="v sm num st"></div></div>
        <div class="kv res-wrap"><div class="k">Vivado</div><div class="v sm num res"></div></div>
      </div>
      <div class="topissues" hidden></div>
    </div>
    <div class="cards"><div class="timing-card"></div><div class="util-card"></div></div>
    <div class="fwinfo" hidden><button class="infotoggle" data-act="info-toggle" aria-expanded="true" title="Show or hide build info">Build info${CHEV}</button><div class="info-grid"></div></div>`);
  head._r = { name: $('h1', head), pill: $('.pill', head), path: $('.fw-path', head), att: $('.fw-attempt', head), el: $('.el', head), cur: $('.cur', head), est: $('.est', head), eprog: $('.eprog', head), epbar: $('.eprog i', head), cnt: $('.cnt', head), tc: $('.timing-card', head), uc: $('.util-card', head), res: $('.res', head), resWrap: $('.res-wrap', head), st: $('.st', head), stWrap: $('.started-wrap', head), eta: $('.eta', head), etak: $('.etak', head), etasub: $('.etasub', head), etaWrap: $('.eta-wrap', head), info: $('.fwinfo', head), infoTog: $('.infotoggle', head), infoGrid: $('.info-grid', head), top: $('.topissues', head), seg: $('.viewseg', head) };
  const banner = h('div', 'banner');
  const segWrap = h('div', 'segwrap');
  const split = h('div', 'split', `
    <aside class="stagecol"><div class="sl-head"><span>Stages</span><button class="followbtn" data-act="follow" title="Keep the running stage selected">follow live</button></div><div class="stagelist"></div></aside>
    <section class="detail"></section>`);
  const mv = h('section', 'msgview', `
    <div class="mv-bar"><div class="mv-chips"></div><input class="mv-q" type="search" placeholder="Search id or text…" spellcheck="false" autocomplete="off"></div>
    <div class="mv-hint" hidden></div>
    <div class="mv-list"></div>`);
  mv.hidden = true;
  const tv = h('section', 'tview');
  tv.hidden = true;
  mainEl.append(head, banner, segWrap, split, mv, tv);
  mainEl._r = { banner, seg: segWrap, split, stages: $('.stagelist', split), detail: $('.detail', split), followBtn: $('.followbtn', split), mv, mvChips: $('.mv-chips', mv), mvQ: $('.mv-q', mv), mvHint: $('.mv-hint', mv), mvList: $('.mv-list', mv), tv, fwId: null, selId: null, selFlow: null, detEl: null };
}

// Red is kept for a device that is actually over capacity; high-but-fitting utilization is a warning, not a failure.
const utilClass = (pct) => (pct == null ? '' : pct > 100 ? 'over' : pct >= 90 ? 'crit' : pct >= 80 ? 'warn' : '');
const UTIL_BADGE = { over: ['OVER CAPACITY', 'notmet'], crit: ['VERY HIGH', 'critb'], warn: ['HIGH', 'warnb'] };
function utilCardHTML(fw) {
  const u = fw.utilization;
  if (!u || !(u.rows || []).length) return '<div class="tc-top"><span class="tc-title">Utilization</span></div><div class="uc-none">No utilization report yet — shown after placement</div>';
  const step = String(u.step || '').split('/').pop().replace(/_design$/, '').replace(/_/g, ' ');
  const src = `Report · ${step ? step.charAt(0).toUpperCase() + step.slice(1) + ' · ' : ''}${u.label || u.report || ''}`;
  const rows = u.rows.map((r) => {
    const pct = r.pct ?? (r.available ? (r.used / r.available) * 100 : null);
    const cls = utilClass(pct);
    return `<div class="uc-row" title="${esc(r.name)}: ${fmtVal(r.used)} of ${fmtVal(r.available)}"><span class="un">${esc(r.name)}</span><div class="ubar ${cls}"><i style="width:${Math.min(100, pct || 0)}%"></i></div><span class="uv num">${fmtNum(r.used)}<span class="dim"> / ${fmtNum(r.available)}</span></span><span class="up num ${cls}">${pct == null ? '—' : pct.toFixed(pct < 10 ? 1 : 0) + '%'}</span></div>`;
  }).join('');
  const worst = Math.max(...u.rows.map((r) => r.pct ?? 0));
  const wb = UTIL_BADGE[utilClass(worst)];
  return `<div class="tc-top"><span class="tc-title">Utilization</span>${wb ? `<span class="met-badge ${wb[1]}">${wb[0]}</span>` : ''}</div><div class="uc-rows">${rows}</div><div class="tc-foot"><span class="src" title="${esc(src)}">${esc(src)}</span></div>`;
}

function topIssuesHTML(fw) {
  const all = fw.top_messages || [];
  const tm = all.slice(0, TOP_ISSUES_SHOWN);
  if (!tm.length) return '';
  const more = all.length > tm.length ? `<button class="linkbtn ti-more" data-act="view" data-view="messages">all messages →</button>` : '';
  return `<div class="ti-h">Top issues${more}</div>${tm.map((g) => `<div class="ti" data-act="topissue" data-id="${esc(g.id)}" title="${esc(g.text)}"><span class="spill ${sevInfo(g.severity).cls}">${esc(SEV_WORD[g.severity] || g.severity)}</span><span class="gid mono">${esc(g.id)}</span><span class="ti-t">${esc(g.text)}</span>${g.new ? '<span class="ntag">NEW</span>' : ''}<span class="ti-c mono">${fmtNum(g.count)}</span></div>`).join('')}`;
}
const TOP_ISSUES_SHOWN = 3;
const SEV_WORD = { error: 'ERROR', critical: 'CRITICAL', warning: 'WARNING', info: 'INFO' };

const ETA_METHOD = { 'previous build': 'based on previous build', 'catalog weights': 'rough estimate' };
function etaParts(fw) {
  const e = fw.eta;
  if (fw.status !== 'running' || !e || e.expected_end == null) return null;
  const rem = e.expected_end - nowS();
  const how = [ETA_METHOD[e.method] || e.method, e.confidence === 'low' ? 'low confidence' : ''].filter(Boolean).join(' · ');
  return { clock: fmtClock(e.expected_end), end: e.expected_end, how, inTxt: rem > 30 ? `in ${fmtDur(rem)}` : 'any moment now' };
}
const endedAt = (fw) => (fw.started_at && fw.elapsed_s != null ? fw.started_at + fw.elapsed_s : fw.updated_at);

function infoHTML(fw) {
  const i = { ...(fw.info || {}) };
  if (!i.vivado_version) i.vivado_version = fw.vivado_version;
  const cell = (k, v, cls = '') => `<div class="ic ${cls}"><div class="k">${esc(k)}</div><div class="v" title="${esc(v)}">${esc(v)}</div></div>`;
  const has = (v) => v != null && v !== '';
  const out = [['Part', i.part], ['Board', i.board], ['Top', i.top], ['Vivado', i.vivado_version], ['Host', i.host], ['Synth strategy', i.strategy_synth],
    ['Impl strategy', i.strategy_impl], ['Jobs', i.jobs]].filter(([, v]) => has(v)).map(([k, v]) => cell(k, v));
  const dirs = Object.entries(i.directives || {}).filter(([, v]) => has(v));
  if (dirs.length) out.push(`<div class="ic wide"><div class="k">Directives</div><div class="v dirs">${dirs.map(([k, v]) => `<span class="dchip" title="${esc(k)} -directive ${esc(v)}"><i>${esc(k.replace(/_design$/, ''))}</i>${esc(v)}</span>`).join('')}</div></div>`);
  if (has(i.project)) out.push(cell('Project', i.project, 'wide mono'));
  return out.join('');
}

function attemptLineHTML(a) {
  const parts = [`<b>Attempt ${a.n}</b>`];
  if (a.mode === 'resume') parts.push(`resumed${a.resumed_from ? ` from ${esc(String(a.resumed_from).replace(/_design$/, ''))} checkpoint` : ''}`);
  else if (a.mode === 'external') parts.push(`outside project flow (inferred from files)${a.resumed_from ? `, after ${esc(String(a.resumed_from).replace(/_design$/, ''))} checkpoint` : ''}`);
  else parts.push('restarted');
  if (a.previous_failure) parts.push(`<span class="prev">previous attempt ${CRASH_RE.test(a.previous_failure) ? 'crashed' : 'failed'}: ${esc(a.previous_failure)}</span>`);
  return `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg><span>${parts.join(' · ')}</span>`;
}
function renderHeader(fw) {
  const r = head._r;
  setText(r.name, fw.name);
  const oc = outcomeOf(fw);
  setAttr(r.pill, 'data-status', oc.key);
  setText(r.pill, oc.pill + (fw.kind === 'log' ? ' · log' : ''));
  setText(r.path, fw.path || '');
  const at = fw.attempt && fw.attempt.n > 1 ? fw.attempt : null;
  r.att.hidden = !at;
  setHTML(r.att, at ? attemptLineHTML(at) : '');
  const running = fw.status === 'running' && fw.started_at;
  r.el.dataset.start = running ? fw.started_at : '';
  if (!running) delete r.el.dataset.start;
  setText(r.el, fmtDur(running ? nowS() - fw.started_at : fw.elapsed_s));
  r.cur.hidden = !fw.current; // without a current step the status pill already says it all
  setText(r.cur, fw.current ? fw.current.label : '');
  r.resWrap.hidden = !fw.resources;
  if (fw.resources) { r.res.title = 'Vivado process CPU (100% = one core) and resident memory'; setText(r.res, `${Math.round(fw.resources.cpu_pct)}% · ${fmtMem(fw.resources.rss_mb)}`); }
  setHTML(r.cnt, countsHTML(fw.counts));
  const fin = ['done', 'failed', 'stopped'].includes(fw.status);
  r.stWrap.hidden = !fw.started_at; setText(r.st, fmtClock(fw.started_at));
  const ep = etaParts(fw);
  r.etaWrap.hidden = !(ep || (fin && endedAt(fw)));
  if (ep) {
    setText(r.etak, 'Expected end'); setText(r.eta, `~${ep.clock}`);
    setHTML(r.etasub, `<span data-end="${ep.end}">${ep.inTxt}</span>${ep.how ? ` · <span class="how">${esc(ep.how)}</span>` : ''}`);
    r.etaWrap.title = 'Estimated finish time' + (ep.how ? ` (${ep.how}${fw.eta.confidence ? `, ${fw.eta.confidence} confidence` : ''})` : '');
  } else if (fin && endedAt(fw)) { setText(r.etak, 'Ended'); setText(r.eta, fmtClock(endedAt(fw))); setHTML(r.etasub, ''); r.etaWrap.title = ''; }
  const ih = infoHTML(fw);
  r.info.hidden = !ih; setHTML(r.infoGrid, ih);
  r.info.classList.toggle('closed', !infoOpen); setAttr(r.infoTog, 'aria-expanded', String(infoOpen));
  const pe = fw.progress_estimate;
  r.eprog.hidden = r.est.hidden = pe == null;
  if (pe != null) { r.epbar.style.width = `${Math.round(pe * 100)}%`; setText(r.est, `${['failed', 'stopped'].includes(fw.status) ? 'reached ' : ''}~${Math.round(pe * 100)}%`); r.eprog.title = r.est.title = 'Estimated share of the whole flow completed, from step weights'; setAttr(r.eprog, 'data-status', fw.status); }
  setAttr(head, 'data-health', fw.health || topLevel(fwAlerts(fw)) || 'ok');
  const tc = timingCardHTML(fw);
  setAttr(r.tc, 'data-tl', tc.tl);
  setHTML(r.tc, tc.html);
  setHTML(r.uc, utilCardHTML(fw));
  const ti = topIssuesHTML(fw);
  r.top.hidden = !ti; setHTML(r.top, ti);
  const view = curView(fw);
  for (const b of r.seg.children) { b.classList.toggle('on', b.dataset.view === view); setAttr(b, 'aria-pressed', String(b.dataset.view === view)); if (b.dataset.view === 'timing') b.hidden = !hasTimingView(fw) && view !== 'timing'; }
}

/* ------------------------------------------------------------------ rendering: flow nodes */
function createNode() {
  const el = h('div', 'node', `
    <div class="rail"><span class="nicon"></span></div>
    <div class="main">
      <div class="card" data-act="toggle" role="button" tabindex="0">
        <div class="crow"><div class="label"></div><div class="badges"></div><span class="chipwrap"></span><span class="docwrap"></span><div class="meta"></div>${CHEV}</div>
        <div class="desc"></div>
        <div class="rchips"></div>
        <div class="prog"><i></i></div>
      </div>
      <div class="body"><div class="bodyin"></div></div>
    </div>`);
  el._r = { icon: $('.nicon', el), label: $('.label', el), badges: $('.badges', el), chip: $('.chipwrap', el), doc: $('.docwrap', el), meta: $('.meta', el), desc: $('.desc', el), rchips: $('.rchips', el), prog: $('.prog', el), bar: $('.prog i', el), bodyin: $('.bodyin', el), panel: null };
  return el;
}

function badgesHTML(c) {
  return SEVERITIES.map((s) => {
    const v = c && c[s.key];
    return v ? `<span class="badge ${s.cls}" title="${s.label}">${fmtNum(v)}<i>${s.short}</i></span>` : '';
  }).join('');
}

function chipHTML(t) {
  if (!t || t.wns == null) return t ? `<span class="chip nil" title="${esc(t.label)}">WNS —</span>` : '';
  const bad = t.met === false || t.wns < 0 || (t.whs != null && t.whs < 0);
  const cls = bad ? (t.final ? 'notmet' : 'softbad') : t.met === true ? 'met' : 'nil';
  const mark = bad ? (t.final ? '✗' : '~') : t.met === true ? '✓' : '';
  const sign = t.wns > 0 ? '+' : '';
  const cw = carriedOf(t, 'wns'), ch = carriedOf(t, 'whs');
  const whsTxt = t.whs != null && t.whs < 0 ? ` · WHS ${t.whs.toFixed(3)}` : '';
  const whsPart = whsTxt ? (ch ? `<span class="carried" title="WHS ${esc(carriedTip(ch))}">${whsTxt}</span>` : whsTxt) : '';
  const tip = `${t.stage || t.label} · ${t.final ? 'final' : 'not final (estimate / intermediate)'} (${t.source})${whsTxt}${cw ? `\nWNS ${carriedTip(cw)}` : ''}${ch && whsTxt ? `\nWHS ${carriedTip(ch)}` : ''}`;
  return `<span class="chip ${cls}${cw ? ' carried' : ''}" title="${esc(tip)}">WNS ${sign}${t.wns.toFixed(3)} ${mark}${whsPart}${cw ? '<i class="ctag">stale</i>' : ''}</span>`;
}

function updateNode(el, n, fw, depth) {
  const r = el._r;
  el._node = n; el._fw = fw; el._depth = depth;
  const lvl = nodeLevel(n);
  setAttr(el, 'data-status', n.status);
  setAttr(el, 'data-kind', n.kind);
  if (r.icon._s !== n.status) { r.icon._s = n.status; r.icon.innerHTML = statusInfo(n.status).icon; r.icon.title = statusInfo(n.status).label; }
  const kindTag = el._detail ? `<small class="st">${statusInfo(n.status).label}</small>` : ['group', 'run', 'task', 'command'].includes(n.kind) ? `<small>${n.kind}</small>` : '';
  setHTML(r.label, `${lvl ? alertIcon(lvl) : ''}${labelHTML(n)}${kindTag}${n.optional ? '<small class="opt">optional</small>' : ''}${attTags(n)}`);
  r.label.title = n.description ? `${n.label} — ${n.description}` : n.label;
  const showDesc = n.description && n.status !== 'done' && (n.status === 'pending' || n.status === 'queued' || n.status === 'running');
  r.desc.hidden = !showDesc; setText(r.desc, showDesc ? n.description : '');
  setHTML(r.rchips, (n.reports || []).map((rp) => `<span class="rchip${rp.stale ? ' stale' : ''}${(rp.alerts || []).length ? ' alerted' : ''}" data-act="rchip" data-path="${esc(rp.path || '')}" title="${esc(rp.path || '')}${rp.stale ? ' (stale: from a previous run)' : ''}">${esc(rp.label || rp.name)}${rp.stale ? '<i>stale</i>' : ''}</span>`).join(''));
  r.rchips.hidden = !(n.reports || []).length;
  setAttr(el, 'data-alert', lvl); setAttr(el, 'data-expected', n.expected ? '1' : '0'); setAttr(el, 'data-optional', n.optional ? '1' : '0');
  setHTML(r.badges, badgesHTML(n.counts));
  setHTML(r.chip, chipHTML(n.timing));
  setHTML(r.doc, docBtn(n.doc_url, `${n.label} documentation`));
  const running = n.status === 'running' && n.started_at;
  const el_s = running ? nowS() - n.started_at : n.elapsed_s;
  const mem = n.peak_mem_mb != null ? `<span class="mem" title="Peak memory">${fmtMem(n.peak_mem_mb)}</span>` : '';
  const dur = el_s != null ? `<span ${running ? `data-start="${n.started_at}"` : ''}>${fmtDur(el_s)}</span>` : '';
  setHTML(r.meta, `${mem}${dur}`);
  const p = n.progress;
  r.prog.hidden = !(p && p.total);
  if (p && p.total) { const pc = Math.min(100, Math.round((p.done / p.total) * 100)); r.bar.style.width = `${pc}%`; r.prog.title = `${p.done}/${p.total}`; }
  syncBody(el, n, fw, depth);
}

/* ---- master column: compact stage items; detail column: the selected stage as a forced-open node */
function createStage() {
  const el = h('div', 'node stg', `
    <div class="rail"><span class="nicon"></span></div>
    <div class="main">
      <div class="card" data-act="select" role="button" tabindex="0">
        <div class="crow"><div class="label"></div><span class="docwrap"></span><div class="meta"></div></div>
        <div class="srow"><div class="badges"></div><span class="chipwrap"></span><span class="cvwrap"></span><span class="attwrap"></span></div>
        <div class="fstrip" hidden></div>
        <div class="prog"><i></i></div>
      </div>
    </div>`);
  el._r = { card: $('.card', el), icon: $('.nicon', el), label: $('.label', el), badges: $('.badges', el), chip: $('.chipwrap', el), doc: $('.docwrap', el), meta: $('.meta', el), prog: $('.prog', el), bar: $('.prog i', el), srow: $('.srow', el), att: $('.attwrap', el), fstrip: $('.fstrip', el), cv: $('.cvwrap', el) };
  return el;
}

function updateStage(el, n, fw, isSel) {
  const r = el._r;
  el._node = n; el._fw = fw;
  const lvl = nodeLevel(n);
  setAttr(el, 'data-status', n.status);
  setAttr(el, 'data-alert', lvl);
  setAttr(el, 'data-expected', n.expected ? '1' : '0');
  setAttr(el, 'data-optional', n.optional ? '1' : '0');
  el.classList.toggle('sel', isSel);
  setAttr(r.card, 'aria-pressed', String(isSel));
  if (r.icon._s !== n.status) { r.icon._s = n.status; r.icon.innerHTML = statusInfo(n.status).icon; r.icon.title = statusInfo(n.status).label; }
  setHTML(r.label, `${lvl ? alertIcon(lvl) : ''}${labelHTML(n)}${n.optional ? '<small class="opt">optional</small>' : ''}`);
  r.label.title = n.description ? `${n.label} — ${n.description}` : n.label;
  setHTML(r.att, attTags(n));
  const fl = n.status === 'failed' && n.failure;
  r.fstrip.hidden = !fl;
  setHTML(r.fstrip, fl ? `<b>${failKind(n.failure)}:</b> ${esc(n.failure.reason || 'Error')} in ${esc(failWhere(n))}` : '');
  setHTML(r.badges, badgesHTML(n.counts));
  setHTML(r.chip, chipHTML(n.timing));
  const cvs = n.status === 'running' && n.convergence ? overlapSpark(n.convergence) : '';
  setHTML(r.cv, cvs ? `<span class="cvchip" title="Router overlaps (log scale) · ${esc((n.convergence.trend || 'collecting').toUpperCase())}">${cvs}</span>` : '');
  setHTML(r.doc, docBtn(n.doc_url, `${n.label} documentation`));
  r.srow.hidden = !r.badges.innerHTML && !r.chip.innerHTML && !r.att.innerHTML && !cvs;
  const running = n.status === 'running' && n.started_at;
  const el_s = running ? nowS() - n.started_at : n.elapsed_s;
  setHTML(r.meta, el_s != null ? `<span ${running ? `data-start="${n.started_at}"` : ''}>${fmtDur(el_s)}</span>` : '');
  const p = n.progress;
  r.prog.hidden = !(p && p.total);
  if (p && p.total) { r.bar.style.width = `${Math.min(100, Math.round((p.done / p.total) * 100))}%`; r.prog.title = `${p.done}/${p.total}`; }
}

function createDetail() {
  const el = createNode();
  el.classList.add('stagedetail');
  el._force = true; el._detail = true;
  const card = $('.card', el);
  for (const a of ['data-act', 'tabindex', 'role']) card.removeAttribute(a);
  const fb = h('div', 'dfail');
  const at = h('div', 'dattempts');
  const al = h('div', 'dalerts');
  for (const x of [fb, at, al]) $('.main', el).insertBefore(x, $('.body', el));
  el._r.alerts = al; el._r.dfail = fb; el._r.dattempts = at;
  return el;
}

function renderDetail(el, n, fw) {
  updateNode(el, n, fw, 0);
  if (hashFx) {
    const fl = [['cur', n.failure]]; attemptsOf(n).forEach((a) => fl.push([`a${a.n}`, a.failure]));
    for (const [tag, f] of fl) {
      if (!f || !hashFx.has(tag)) continue;
      hashFx.delete(tag);
      if (tag !== 'cur') fx.set(`open|${fw.id}|${n.id}|${tag.slice(1)}`, true);
      const ex = { line: f.line, data: null, fresh: true }; fx.set(fxKey(fw, n, tag), ex);
      apiLogAround(fw, f.log, f.line).then((d) => { ex.data = d; }).catch(() => {}).finally(() => render());
    }
    if (!hashFx.size) hashFx = null;
  }
  const failing = n.status === 'failed' && n.failure;
  const fbox = failing ? failureHTML(n.failure, fw, n, 'cur', failWhere(n)) : '';
  if (el._r.dfail._h !== fbox) { setHTML(el._r.dfail, fbox); scrollExcerpts(el._r.dfail); }
  const atl = attemptsHTML(n, fw);
  if (el._r.dattempts._h !== atl) { setHTML(el._r.dattempts, atl); scrollExcerpts(el._r.dattempts); }
  setHTML(el._r.alerts, ''); // the firmware banner above already lists these; the stage card keeps its alert icon
}

function scrollExcerpts(root) {
  for (const e of root.querySelectorAll('.logbox.exc')) {
    const ex = fx.get(e.dataset.k); const t = e.querySelector('.target');
    if (ex && ex.fresh && t) { e.scrollTop = t.offsetTop - e.clientHeight / 2 + t.offsetHeight / 2; ex.fresh = false; }
  }
}

// Running stage, else first failed, else stopped, else last done, else first.
function autoStage(stages) {
  return stages.find((s) => s.status === 'running') || stages.find((s) => s.status === 'failed') || stages.find((s) => s.status === 'stopped')
    || [...stages].reverse().find((s) => s.status === 'done') || stages[0];
}

function renderFlowView(fw, flow) {
  const v = mainEl._r;
  const stages = flow.stages;
  let sel = ui.sel.get(fw.id);
  if (!sel) { sel = { id: null, follow: true }; ui.sel.set(fw.id, sel); }
  if (hashSelPending && stages.some((s) => s.id === hashSel)) { sel.id = hashSel; sel.follow = false; hashSelPending = false; }
  const selStage = (!sel.follow && stages.find((s) => s.id === sel.id)) || autoStage(stages);
  v.followBtn.classList.toggle('on', sel.follow);
  setAttr(v.followBtn, 'aria-pressed', String(sel.follow));
  setText(v.followBtn, 'follow live'); // same text in both states: the switch shows the state, the button never changes width
  setAttr(v.followBtn, 'title', sel.follow ? (fw.status === 'running' ? 'Following the running stage — click to stop and stay on this stage' : 'Nothing running — showing the latest stage; it will follow when a step runs. Click to pin this stage') : 'Click to jump to the running stage and keep following it');
  patchList(v.stages, stages, (n) => n.id, createStage, (e, n) => updateStage(e, n, fw, n.id === selStage.id));
  if (v.selId !== selStage.id || v.selFlow !== flow.id || !v.detEl) {
    const prev = v.selId && v.selFlow === flow.id && stages.find((s) => s.id === v.selId);
    if (prev) resetNode(fw, prev);
    v.selId = selStage.id; v.selFlow = flow.id;
    v.detail.innerHTML = '';
    v.detEl = createDetail();
    v.detail.appendChild(v.detEl);
  }
  if (sel.follow && fw.status === 'running' && selStage.status === 'running') followExpand(fw, selStage, v);
  renderDetail(v.detEl, selStage, fw);
  if (v.scrollTo) { const id = v.scrollTo; v.scrollTo = null; setTimeout(() => scrollRunningIntoView(id), 420); }
}

/* ---- follow live: keep the running chain of the selected stage expanded */
let lastUserScroll = 0;
for (const evn of ['wheel', 'touchmove', 'keydown', 'mousedown']) window.addEventListener(evn, () => { lastUserScroll = Date.now(); }, { passive: true, capture: true });
window.addEventListener('scroll', () => { if (!programmaticScroll) lastUserScroll = Date.now(); }, { passive: true });
let programmaticScroll = false;

function runningChain(stage) {
  const chain = [stage];
  for (let n = stage; ;) { const k = (n.children || []).find((c) => c.status === 'running'); if (!k) break; chain.push(k); n = k; }
  return chain;
}

// Auto-opened nodes are tracked apart from ui.open (explicit user choices), so they can be collapsed
// again when no longer running without ever touching what the user opened.
function followExpand(fw, stage, v) {
  const a = autoOf(fw);
  const chain = runningChain(stage);
  const sig = chain.map((n) => n.id).join('>');
  if (a.sig !== sig) { a.dismissed.clear(); const first = a.sig === null; a.sig = sig; if (!first || chain.length > 1) v.scrollTo = chain[chain.length - 1].id; }
  const want = new Set(chain.slice(1).map((n) => keyOf(fw, n)).filter((k) => !a.dismissed.has(k)));
  for (const k of [...a.keys]) if (!want.has(k)) { a.keys.delete(k); ui.tab.delete(k); }
  for (const k of want) if (!ui.open.has(k)) a.keys.add(k);
}

function scrollRunningIntoView(id) {
  if (Date.now() - lastUserScroll < 5000) return;
  const el = [...mainEl.querySelectorAll('.detail .node')].find((e) => e._node && e._node.id === id);
  if (!el) return;
  const r = el.getBoundingClientRect();
  const top = stickTop(); const bottom = window.innerHeight - 20;
  if (r.top >= top && r.bottom <= bottom) return;
  programmaticScroll = true;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  setTimeout(() => { programmaticScroll = false; }, 900);
}

/* ---- expanded body: details tabs (Flow / Messages / Log / Timing) */
function availableTabs(n) {
  const tabs = [];
  if (n.children && n.children.length) tabs.push(['flow', `Steps<small>${n.children.length}</small>`]);
  if (!NO_FETCH.has(n.status)) { tabs.push(['messages', 'Messages']); tabs.push(['log', 'Log']); }
  if (n.reports && n.reports.length) tabs.push(['reports', `Reports<small>${n.reports.length}</small>`]);
  if (n.timing && ((n.timing.history && n.timing.history.length) || n.timing.report)) tabs.push(['timing', `Timing<small>${(n.timing.history || []).length || ''}</small>`]);
  const cv = convOf(n);
  if (cv) tabs.push(['convergence', `Convergence<small>${cv.conv.iterations.length}</small>`]);
  return tabs;
}

function activeTab(fw, n, tabs) {
  const k = keyOf(fw, n);
  const want = ui.tab.get(k) || hashTab.get(n.id);
  const ids = tabs.map((t) => t[0]);
  if (want && ids.includes(want)) return want;
  return ids[0] || null;
}

function syncBody(el, n, fw, depth) {
  const r = el._r;
  const open = el._force || isOpen(fw, n);
  el.classList.toggle('open', open);
  const card = el.querySelector(':scope > .main > .card');
  if (card && card.getAttribute('role') === 'button') setAttr(card, 'aria-expanded', String(open));
  if (open) {
    clearTimeout(el._clearT); el._clearT = null;
    if (!r.panel) {
      r.panel = h('div', 'panel', '<div class="dtabs"></div><div class="pane pane-flow sub"></div><div class="pane pane-messages"></div><div class="pane pane-log"></div><div class="pane pane-reports"></div><div class="pane pane-timing"></div><div class="pane pane-convergence"></div>');
      r.bodyin.appendChild(r.panel);
      r.tabs = $('.dtabs', r.panel);
      r.panes = { flow: $('.pane-flow', r.panel), messages: $('.pane-messages', r.panel), log: $('.pane-log', r.panel), reports: $('.pane-reports', r.panel), timing: $('.pane-timing', r.panel), convergence: $('.pane-convergence', r.panel) };
    }
    const tabs = availableTabs(n);
    const act = activeTab(fw, n, tabs);
    setHTML(r.tabs, tabs.map(([id, lbl]) => `<button class="dtab${id === act ? ' on' : ''}" data-act="dtab" data-tab="${id}">${lbl}</button>`).join(''));
    for (const [id, pane] of Object.entries(r.panes)) pane.hidden = id !== act;
    if (!act) {
      setHTML(r.panes.flow, `<div class="none">${n.status === 'skipped' ? 'Skipped — no data.' : 'Not started yet.'}</div>`);
      r.panes.flow.hidden = false;
      return;
    }
    if (act === 'flow') {
      if (r.panes.flow.firstChild && r.panes.flow.firstChild._isNone) r.panes.flow.innerHTML = '';
      patchList(r.panes.flow, n.children, (c) => c.id, createNode, (e, c) => updateNode(e, c, fw, depth + 1));
    } else if (act === 'messages') ensureMessages(el, n, fw);
    else if (act === 'log') ensureLog(el, n, fw);
    else if (act === 'reports') renderReports(r.panes.reports, n, keyOf(fw, n), fw);
    else if (act === 'timing') renderTiming(r.panes.timing, n, fw);
    else if (act === 'convergence') renderConvergence(r.panes.convergence, n);
  } else if (r.panel && !el._clearT) {
    el._clearT = setTimeout(() => {
      el._clearT = null;
      if (!el.classList.contains('open')) { r.bodyin.innerHTML = ''; r.panel = null; }
    }, 350);
  }
}

/* ---- details: messages */
const detOf = (k) => { let d = ui.det.get(k); if (!d) { d = { sev: new Set(SEVERITIES.map((s) => s.key)), openG: new Set(), msgs: null, msgSig: null, log: null, logSig: null, busy: {} }; ui.det.set(k, d); } return d; };
const nodeSig = (n) => `${n.status}|${JSON.stringify(n.counts)}`;

function ensureMessages(el, n, fw) {
  const d = detOf(keyOf(fw, n));
  const pane = el._r.panes.messages;
  const sig = nodeSig(n);
  if (d.msgs) renderMessages(pane, d, el);
  else setHTML(pane, '<div class="none">Loading…</div>');
  if (d.msgSig !== sig && !d.busy.msgs) {
    d.busy.msgs = true;
    apiMessages(fw, n).then((res) => { d.msgs = res; d.msgSig = sig; }).catch((e) => { d.msgs = { groups: [], items: [], error: String(e) }; })
      .finally(() => { d.busy.msgs = false; if (el.isConnected && el._r.panel) renderMessages(el._r.panes.messages, d, el); });
  }
}

function renderMessages(pane, d, el) {
  const m = d.msgs;
  if (!m) return;
  if (m.error) { setHTML(pane, `<div class="none">Could not load messages (${esc(m.error)})</div>`); return; }
  const tot = {};
  for (const g of m.groups) tot[g.severity] = (tot[g.severity] || 0) + g.count;
  const chips = SEVERITIES.map((s) => `<button class="fchip ${s.cls}${d.sev.has(s.key) ? ' on' : ''}" data-act="sev" data-sev="${s.key}">${s.label}<b>${tot[s.key] || 0}</b></button>`).join('');
  const order = (s) => SEVERITIES.findIndex((x) => x.key === s);
  const scored = m.groups.some((g) => g.score != null);
  const groups = m.groups.filter((g) => d.sev.has(g.severity)).sort((a, b) => (scored ? (b.score ?? 0) - (a.score ?? 0) : 0) || order(a.severity) - order(b.severity) || b.count - a.count);
  let body = groups.map((g) => {
    const open = d.openG.has(g.id);
    let inst = '';
    if (open) {
      const items = m.items.filter((x) => x.id === g.id);
      inst = `<div class="inst">${items.slice(0, 60).map((x) => `<div><span class="ln">L${x.line}</span>${esc(x.text)}</div>`).join('')}${g.count > items.length || items.length > 60 ? `<div class="more">${g.count} total · showing ${Math.min(60, items.length)} (first line ${g.first_line}, last ${g.last_line})</div>` : ''}</div>`;
    }
    return `<div class="grp-h${open ? ' open' : ''}" data-act="grp" data-gid="${esc(g.id)}"><span class="sevd ${sevInfo(g.severity).cls}" style="background:var(${sevInfo(g.severity).var})"></span><span class="gid">${esc(g.id || '—')}</span><span class="gtxt" title="${esc(g.text)}${(g.reasons || []).length ? '\n' + esc(g.reasons.join(' · ')) : ''}">${esc(g.text)}</span>${g.new ? '<span class="ntag">NEW</span>' : ''}${docBtn(g.doc_url, `${g.id} documentation`)}<span class="gcnt ${sevInfo(g.severity).cls}" style="background:none">${g.count}</span></div>${inst}`;
  }).join('');
  if (!m.groups.length) body = '<div class="none">No messages for this step.</div>';
  else if (!groups.length) body = '<div class="none">No messages match the selected severities.</div>';
  const scroller = pane.querySelector('.groups');
  const st = scroller ? scroller.scrollTop : 0;
  const html = `<div class="chips">${chips}</div><div class="groups">${body}</div>`;
  if (pane._h !== html) {
    setHTML(pane, html);
    const ns = pane.querySelector('.groups');
    if (ns && st) ns.scrollTop = st;
  }
}

/* ---- details: log */
function ensureLog(el, n, fw, force) {
  const d = detOf(keyOf(fw, n));
  const pane = el._r.panes.log;
  if (d.log) renderLog(pane, d, n);
  else setHTML(pane, '<div class="none">Loading…</div>');
  const sig = n.status;
  if ((force || d.logSig !== sig || !d.log) && !d.busy.log) {
    d.busy.log = true;
    apiLog(fw, n).then((res) => { d.log = res; d.logSig = sig; }).catch((e) => { d.log = { lines: [], error: String(e) }; })
      .finally(() => { d.busy.log = false; if (el.isConnected && el._r.panel) renderLog(el._r.panes.log, d, n); });
  }
}

const LOG_RULES = [[/^CRITICAL WARNING/, 'critical'], [/\bERROR:/, 'error'], [/^ERROR/, 'error'], [/\bWARNING:/, 'warning'], [/^(Phase |Starting |Command:|Ending )/, 'phase']];
function renderLog(pane, d, n) {
  const L = d.log;
  if (!L) return;
  if (L.error) { setHTML(pane, `<div class="none">Could not load log (${esc(L.error)})</div>`); return; }
  const sig = `${L.end_line}|${L.lines.length}|${L.path}`;
  if (pane._sig === sig) return;
  pane._sig = sig;
  const old = pane.querySelector('.logbox');
  const stick = !old || old.scrollHeight - old.scrollTop - old.clientHeight < 40;
  const keep = old ? old.scrollTop : 0;
  const start = L.start_line ?? 1;
  const rows = L.lines.map((t, i) => {
    let cls = '';
    for (const [re, c] of LOG_RULES) if (re.test(t)) { cls = c; break; }
    return `<div class="l ${cls}"><span class="ln">${start + i}</span><span>${esc(t)}</span></div>`;
  }).join('');
  const live = n.status === 'running' ? '<span class="live-tag"> · live</span>' : '';
  pane._h = null;
  pane.innerHTML = `<div class="logpath">${esc(L.path || '')} · lines ${start}–${L.end_line ?? start + L.lines.length - 1}${live}</div><div class="logbox">${rows || '<div class="none" style="padding:8px 12px">(empty)</div>'}</div>`;
  const box = pane.querySelector('.logbox');
  box.scrollTop = stick ? box.scrollHeight : keep;
}

/* ---- details: reports. REPORT_RENDERERS is keyed by report.kind; unknown kinds use renderGeneric. */
const prettyKey = (k) => String(k).replace(/_/g, ' ').replace(/\b(w|c|pct)$/i, (m) => ({ w: '(W)', c: '(°C)', pct: '(%)' }[m.toLowerCase()]));
function fmtVal(v, key = '') {
  if (v == null) return '—';
  if (typeof v === 'number') {
    if (/_w$/.test(key)) return `${v.toFixed(3)} W`;
    if (/_c$/.test(key)) return `${v.toFixed(1)} °C`;
    if (/pct|util/.test(key)) return `${v.toFixed(1)}%`;
    return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toFixed(3);
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  return esc(v);
}
function renderGeneric(v, key = '') {
  if (v == null || typeof v !== 'object') return fmtVal(v, key);
  if (Array.isArray(v)) {
    if (!v.length) return '—';
    if (typeof v[0] !== 'object') return v.map((x) => fmtVal(x)).join(', ');
    const cols = [...new Set(v.flatMap((o) => Object.keys(o)))];
    return `<table class="hist gen"><thead><tr>${cols.map((c) => `<th>${esc(prettyKey(c))}</th>`).join('')}</tr></thead><tbody>${v.map((o) => `<tr>${cols.map((c) => `<td>${renderGeneric(o[c], c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }
  return `<table class="kv-table">${Object.entries(v).map(([k, x]) => `<tr><th>${esc(prettyKey(k))}</th><td>${renderGeneric(x, k)}</td></tr>`).join('')}</table>`;
}
function statGrid(sm, bad) {
  const prim = Object.entries(sm).filter(([, v]) => v == null || typeof v !== 'object');
  const rest = Object.fromEntries(Object.entries(sm).filter(([, v]) => v != null && typeof v === 'object'));
  return `<div class="stats">${prim.map(([k, v]) => `<div class="stat${bad && bad(k, v) ? ' bad' : ''}"><div class="k">${esc(prettyKey(k))}</div><div class="v num">${fmtVal(v, k)}</div></div>`).join('')}</div>${Object.keys(rest).length ? renderGeneric(rest) : ''}`;
}
const REPORT_RENDERERS = {
  utilization(sm) {
    const rows = sm.rows || sm.resources || sm.table || (Array.isArray(sm) ? sm : null);
    if (!rows) return renderGeneric(sm);
    return `<table class="util">${rows.map((r) => {
      const name = r.name ?? r.resource; const used = r.used; const avail = r.available ?? r.total;
      const pct = r.pct ?? r.percent ?? r.util ?? (avail ? (used / avail) * 100 : null);
      const cls = utilClass(pct);
      return `<tr><th>${esc(name)}</th><td class="num">${fmtVal(used)} <span class="dim">/ ${fmtVal(avail)}</span></td><td class="barcell"><div class="ubar ${cls}"><i style="width:${Math.min(100, pct || 0)}%"></i></div></td><td class="num pc ${cls}">${pct == null ? '—' : pct.toFixed(1) + '%'}</td></tr>`;
    }).join('')}</table>`;
  },
  drc(sm) {
    const c = sm.counts || {};
    const chips = SEVERITIES.map((s) => `<span class="badge ${s.cls}${c[s.key] ? '' : ' zero'}">${c[s.key] || 0}<i>${s.short}</i></span>`).join(' ');
    const rules = sm.rules || sm.top || [];
    const tbl = rules.length ? `<table class="hist gen"><thead><tr><th>Rule</th><th>Severity</th><th>Count</th><th style="text-align:left">Message</th></tr></thead><tbody>${rules.slice(0, 10).map((r) => `<tr><td class="mono">${esc(r.id)}</td><td><span class="badge ${sevInfo(r.severity).cls}">${esc(r.severity)}</span></td><td>${r.count}</td><td style="text-align:left;font-family:var(--sans)">${esc(r.message || r.text || '')}</td></tr>`).join('')}</tbody></table>` : '';
    return `<div class="chips">${chips}</div>${tbl}`;
  },
  timing_summary(sm) {
    const cells = TIMING_FIELDS.map(([k, l]) => `<div class="stat ${sm[k] != null && sm[k] < 0 ? 'bad' : ''}"><div class="k">${l}</div><div class="v num ${cellClass(k, sm[k])}">${fmtNs(sm[k])}</div></div>`).join('');
    const cl = sm.clocks || [];
    const tbl = cl.length ? `<table class="hist gen"><thead><tr><th>Clock</th><th>Period</th><th>WNS</th><th>TNS</th><th>WHS</th><th>THS</th></tr></thead><tbody>${cl.map((c) => {
      const fail = [c.wns, c.tns, c.whs, c.ths].some((x) => x != null && x < 0);
      return `<tr class="${fail ? 'failrow' : ''}"><td class="mono">${esc(c.name)}</td><td>${c.period != null ? fmtNs(c.period) : '—'}</td>${['wns', 'tns', 'whs', 'ths'].map((k) => `<td class="${c[k] != null && c[k] < 0 ? 'neg' : ''}">${fmtNs(c[k])}</td>`).join('')}</tr>`;
    }).join('')}</tbody></table>` : '';
    const extra = Object.fromEntries(Object.entries(sm).filter(([k, v]) => !['wns', 'tns', 'whs', 'ths', 'clocks'].includes(k) && (v == null || typeof v !== 'object')));
    return `<div class="stats">${cells}</div>${tbl}${Object.keys(extra).length ? renderGeneric(extra) : ''}`;
  },
  power: (sm) => statGrid(sm),
  route_status: (sm) => statGrid(sm, (k, v) => /unrouted|error/.test(k) && v > 0),
};
REPORT_RENDERERS.methodology = REPORT_RENDERERS.drc;

function renderReports(pane, n, key, fw) {
  const reps = n.reports || [];
  // one report at a time: the chip clicked on the card, else one with alerts, else the first
  let cur = reps.findIndex((rp) => rp.path === ui.rsel.get(key));
  if (cur < 0) cur = Math.max(0, reps.findIndex((rp) => (rp.alerts || []).length && !rp.stale));
  const bar = reps.length > 1 ? `<div class="rsel">${reps.map((rp, i) => `<button class="rchip${i === cur ? ' on' : ''}${rp.stale ? ' stale' : ''}${(rp.alerts || []).length ? ' alerted' : ''}" data-act="rsel" data-path="${esc(rp.path || '')}" title="${esc(rp.path || '')}">${esc(rp.label || rp.name)}${rp.stale ? '<i>stale</i>' : ''}</button>`).join('')}</div>` : '';
  const html = reps.map((rp, i) => {
    if (i !== cur) return '';
    const fn = REPORT_RENDERERS[rp.kind] || renderGeneric;
    let body;
    try { body = rp.summary == null ? '<div class="none">No summary available.</div>' : fn(rp.summary); } catch (e) { body = renderGeneric(rp.summary); }
    const al = (rp.alerts || []).map((a) => `<div class="alert lvl-${esc(a.level)} small">${alertIcon(a.level)}<span class="amsg">${esc(a.message)}</span></div>`).join('');
    const age = rp.mtime ? `${fmtDur(nowS() - rp.mtime)} ago` : '';
    const soft = rp.kind === 'timing_summary' && n.timing && !n.timing.final;
    if (rp.kind === 'timing_summary' && rp.summary && rp.summary.path_counts) body += `<div class="paths-sec">${pathsHTML(fw, rp.path, rp.mtime, 'r')}</div>`;
    return `<section class="report${rp.stale ? ' stale' : ''}${soft ? ' soft' : ''}"><header><b>${esc(rp.label || rp.name)}</b><span class="kind">${esc(rp.name)}</span><span class="kind">${esc(rp.kind)}</span>${rp.stale ? '<span class="stag">stale</span>' : ''}<span class="age">${age}</span>${docBtn(rp.doc_url, `${rp.label || rp.name} documentation`)}<button class="rawbtn" data-act="raw" data-i="${i}">raw</button></header>${al}${body}</section>`;
  }).join('');
  setHTML(pane, html ? bar + html : '<div class="none">No reports yet.</div>');
}

function showModal(title, text) {
  let m = $('#modal');
  if (!m) { m = h('div', 'modal'); m.id = 'modal'; document.body.appendChild(m); m.addEventListener('click', (e) => { if (e.target === m || e.target.closest('.mclose')) m.hidden = true; }); }
  m.innerHTML = `<div class="mbox" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="mhead"><b>${esc(title)}</b><button class="mclose icon-btn" aria-label="Close">✕</button></div><pre>${esc(text)}</pre></div>`;
  m._ret = document.activeElement;
  m.hidden = false;
  $('.mclose', m).focus();
}

/* ---- details: timing history */
function renderTiming(pane, n, fw) {
  const t = n.timing;
  const hist = (t && t.history) || [];
  const cls = (k, v) => (v == null ? '' : v < 0 ? 'neg' : 'pos');
  const rows = hist.map((x) => `<tr><td>${esc(x.label)}</td>${TIMING_FIELDS.map(([k]) => `<td class="${cls(k, x[k])}">${fmtNs(x[k])}</td>`).join('')}<td>${x.line ?? ''}</td></tr>`).join('');
  const cur = t ? `<tr><td><b>Latest</b> · ${esc(t.source)}</td>${TIMING_FIELDS.map(([k]) => {
    const c = carriedOf(t, k);
    return `<td class="${cls(k, t[k])}${c ? ' carried' : ''}"${c ? ` title="${esc(carriedTip(c))}"` : ''}><b>${fmtNs(t[k])}</b>${c ? '<i class="ctag">stale</i>' : ''}</td>`;
  }).join('')}<td></td></tr>` : '';
  setHTML(pane, `<div class="pane-t${t && !t.final ? ' soft' : ''}">${t ? `<div class="pt-stage">${esc(t.stage || t.label || '')} · ${t.final ? 'final' : 'not final (estimate / intermediate)'}</div>` : ''}${spark(hist.map((x) => x.wns), 600, 56, { fluid: true, dots: true, warn: !(t && t.final) })}<table class="hist"><thead><tr><th>Summary</th><th>WNS</th><th>TNS</th><th>WHS</th><th>THS</th><th>Line</th></tr></thead><tbody>${rows}${cur}</tbody></table>${t && t.report && reportOf(fw, t.report) ? `<div class="paths-sec">${pathsHTML(fw, t.report, reportOf(fw, t.report).mtime, 't')}</div>` : ''}</div>`);
}

/* ------------------------------------------------------------------ messages (triage) view */
const MUTE_SVG = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M22 9l-6 6M16 9l6 6"/></svg>';

function mvOf(fw) {
  let m = ui.mv.get(fw.id);
  if (!m) {
    m = { sev: new Set(['error', 'critical', 'warning']), newOnly: false, muted: false, q: '', open: new Set(), data: null, sig: null, busy: false, rev: 0, inst: {}, exc: {}, focus: null, autoExc: false, qT: null };
    if (hashMsg) { m.open.add(hashMsg); m.focus = hashMsg; m.autoExc = hashExcerpt ? hashMsg : false; }
    ui.mv.set(fw.id, m);
  }
  return m;
}
const isCurMv = (fw) => { const c = curFw(); return c && c.id === fw.id && curView(c) === 'messages'; };

function ensureTriage(fw) {
  const m = mvOf(fw);
  const sevReq = SEVERITIES.map((x) => x.key).filter((k) => m.sev.has(k)).join(',') || SEV_ALL;
  const sig = `${JSON.stringify(fw.counts)}|${fw.status}|${m.muted}|${m.q}|${m.rev}|${sevReq}`;
  if (m.sig === sig || m.busy) return;
  m.busy = true; m.sig = sig;
  apiTriage(fw, { q: m.q, muted: m.muted, sev: sevReq })
    .then((r) => { m.data = r; })
    .catch((e) => { m.data = { baseline: true, groups: [], error: String(e.message || e) }; })
    .finally(() => { m.busy = false; if (isCurMv(fw)) { renderMsgView(fw); ensureTriage(fw); } });
}

function ensureInst(fw, g) {
  const m = mvOf(fw);
  if (m.inst[g.id]) return;
  m.inst[g.id] = { items: null };
  apiInstances(fw, g.id)
    .then((r) => { m.inst[g.id] = { items: r.items || [] }; })
    .catch((e) => { m.inst[g.id] = { items: [], error: String(e.message || e) }; })
    .finally(() => {
      const first = (m.inst[g.id].items || [])[0];
      if (m.autoExc === g.id && first) { m.autoExc = false; loadExcerpt(fw, g, first.line); } else if (isCurMv(fw)) renderMsgView(fw);
    });
}

function loadExcerpt(fw, g, line) {
  const m = mvOf(fw);
  if (m.exc[g.id] && m.exc[g.id].line === line) { delete m.exc[g.id]; renderMsgView(fw); return; }
  const ex = m.exc[g.id] = { line, data: null, fresh: true };
  renderMsgView(fw);
  apiLogAround(fw, g.log, line)
    .then((d) => { ex.data = d; })
    .catch((e) => { ex.data = { lines: [], error: String(e.message || e) }; })
    .finally(() => { if (isCurMv(fw)) renderMsgView(fw); });
}

function excerptHTML(ex, g) {
  const d = ex.data;
  if (!d) return '<div class="exc-load">Loading log excerpt…</div>';
  if (d.error) return `<div class="exc-load">Could not load excerpt (${esc(d.error)})</div>`;
  const start = d.start_line ?? 1;
  const rows = d.lines.map((t, i) => {
    let cls = '';
    for (const [re, c] of LOG_RULES) if (re.test(t)) { cls = c; break; }
    return `<div class="l ${cls}${start + i === ex.line ? ' target' : ''}"><span class="ln">${start + i}</span><span>${esc(t)}</span></div>`;
  }).join('');
  return `<div class="logbox exc" data-k="${esc(g.id)}" title="${esc(d.path || '')}">${rows}</div>`;
}

function msgRowHTML(fw, m, g) {
  const open = m.open.has(g.id);
  const sv = sevInfo(g.severity);
  const up = g.user_priority;
  const muted = up === 'mute' || g.priority === 'mute';
  const delta = g.delta > 0 ? `<em class="delta up" title="${g.delta} more than in the previous build">↑${fmtNum(g.delta)}</em>` : g.delta < 0 ? `<em class="delta down" title="${-g.delta} fewer than in the previous build">↓${fmtNum(-g.delta)}</em>` : '';
  const acts = `<span class="mact"><button class="ib${up === 'high' ? ' on' : ''}" data-act="mv-rule" data-id="${esc(g.id)}" data-pri="${up === 'high' ? '' : 'high'}" title="${up === 'high' ? 'Marked important — click to reset' : 'Mark important'}">★</button><button class="ib${up === 'mute' ? ' on' : ''}" data-act="mv-rule" data-id="${esc(g.id)}" data-pri="${up === 'mute' ? '' : 'mute'}" title="${up === 'mute' ? 'Muted — click to unmute' : 'Mute this message'}">${MUTE_SVG}</button>${up ? `<button class="ib txt" data-act="mv-rule" data-id="${esc(g.id)}" data-pri="" title="Remove your rule for ${esc(g.id)}">reset</button>` : ''}</span>`;
  const steps = (g.nodes || []).map((n) => `<span class="stepchip" data-act="mv-step" data-node="${esc(n.node_id)}" title="Show ${esc(n.label)} in the flow">${esc(n.label)}</span>`).join('');
  const reasons = (g.reasons || []).map((r) => `<span class="rtag">${esc(r)}</span>`).join('');
  let det = '';
  if (open) {
    const inst = m.inst[g.id];
    let list;
    if (!inst || !inst.items) list = '<div class="none">Loading instances…</div>';
    else if (inst.error) list = `<div class="none">Could not load instances (${esc(inst.error)})</div>`;
    else {
      const ex = m.exc[g.id];
      list = `<div class="mr-ih">${inst.items.length}${g.count > inst.items.length ? ` of ${fmtNum(g.count)}` : ''} instances · click a line to see the log around it${g.log ? ` · <span class="mono">${esc(g.log)}</span>` : ''}</div><div class="mi">${inst.items.map((x) => `<div class="ir${ex && ex.line === x.line ? ' on' : ''}" data-act="mv-line" data-id="${esc(g.id)}" data-line="${x.line}"><span class="ln">L${x.line}</span><span class="it">${esc(x.text)}</span></div>${ex && ex.line === x.line ? excerptHTML(ex, g) : ''}`).join('')}</div>`;
    }
    det = `<div class="mr-detail"><div class="mr-full">${esc(g.text)}</div>${list}</div>`;
  }
  return `<div class="mrow${open ? ' open' : ''}${muted ? ' muted' : ''}" data-gid="${esc(g.id)}">
    <div class="mr-main" data-act="mv-row" data-id="${esc(g.id)}">
      <span class="spill ${sv.cls}">${SEV_WORD[g.severity] || esc(g.severity)}</span>
      <span class="gid mono">${esc(g.id)}</span>
      <span class="mcount mono">${fmtNum(g.count)}${delta}</span>
      ${g.new ? '<span class="ntag">NEW</span>' : '<span class="ntag ph"></span>'}
      <span class="mtxt">${esc(g.text)}</span>${docBtn(g.doc_url, `${g.id} documentation`)}${acts}${CHEV}
    </div>
    <div class="mr-sub">${steps}${reasons}<span class="score mono" title="Triage score: severity, matching rules and keywords, rarity, and whether the message is new since the last build. Higher sorts first.">triage ${g.score != null ? g.score.toFixed(1) : '—'}</span></div>
    ${det}
  </div>`;
}

function renderMsgView(fw) {
  const v = mainEl._r; const m = mvOf(fw);
  const data = m.data;
  const all = (data && data.groups) || [];
  const tot = {};
  for (const g of all) tot[g.severity] = (tot[g.severity] || 0) + g.count;
  const nNew = all.filter((g) => g.new).length;
  const chips = SEVERITIES.map((s) => `<button class="fchip ${s.cls}${m.sev.has(s.key) ? ' on' : ''}" data-act="mv-sev" data-sev="${s.key}" title="${m.sev.has(s.key) ? 'Hide' : 'Load and show'} ${s.label.toLowerCase()}">${s.label}<b>${fmtNum(m.sev.has(s.key) || tot[s.key] != null ? tot[s.key] || 0 : (fw.counts || {})[s.key] || 0)}</b></button>`).join('')
    + `<button class="fchip neutral${m.newOnly ? ' on' : ''}" data-act="mv-new" title="Only messages not seen in the previous build">New only<b>${nNew}</b></button>`
    + `<button class="fchip neutral${m.muted ? ' on' : ''}" data-act="mv-muted" title="Include muted messages">Show muted</button>`;
  const ql = m.q.trim().toLowerCase();
  const groups = all.filter((g) => m.sev.has(g.severity) && (!m.newOnly || g.new) && (!ql || `${g.id} ${g.text}`.toLowerCase().includes(ql)))
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  setHTML(v.mvChips, `${chips}<span class="mv-n">${groups.length} of ${all.length} message types</span>`);
  v.mvHint.hidden = !(data && data.baseline === false);
  setText(v.mvHint, 'Novelty tracking is not active yet: "new since last build" tags and deltas will be available after the first completed build.');
  let body;
  if (!data) body = '<div class="none">Loading…</div>';
  else if (data.error) body = `<div class="none">Could not load messages (${esc(data.error)})</div>`;
  else if (!all.length) body = '<div class="none">No messages yet.</div>';
  else if (!groups.length) body = '<div class="none">No messages match the current filters.</div>';
  else body = groups.map((g) => msgRowHTML(fw, m, g)).join('');
  const list = v.mvList;
  const saved = new Map([...list.querySelectorAll('.exc')].map((e) => [e.dataset.k, e.scrollTop]));
  if (list._h !== body) {
    setHTML(list, body);
    for (const e of list.querySelectorAll('.exc')) {
      const ex = m.exc[e.dataset.k]; const t = e.querySelector('.target');
      if (ex && ex.fresh && t) { e.scrollTop = t.offsetTop - e.clientHeight / 2 + t.offsetHeight / 2; ex.fresh = false; } else if (saved.has(e.dataset.k)) e.scrollTop = saved.get(e.dataset.k);
    }
  }
  for (const g of groups) if (m.open.has(g.id)) ensureInst(fw, g);
  if (m.focus && data) {
    const row = [...list.querySelectorAll('.mrow')].find((e) => e.dataset.gid === m.focus);
    if (row) { setTimeout(() => row.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60); row.classList.add('flash'); setTimeout(() => row.classList.remove('flash'), 2200); }
    m.focus = null;
  }
}

/* ------------------------------------------------------------------ sticky summary bar */
// Compact always-visible status, shown (via IntersectionObserver) once the big header has scrolled out of view.
const sumEl = $('#sumbar');
const topbarEl = $('.topbar');
sumEl.innerHTML = `<div class="sum-in">
  <div class="sm-id"><i class="sdot"></i><b class="sm-name"></b><span class="pill sm-pill"></span><span class="sm-att" hidden></span></div>
  <div class="sm-cur"></div><div class="sm-time"></div><div class="sm-counts"></div><div class="sm-tim"></div><div class="sm-util"></div><div class="sm-al" data-act="sumtop"></div>
  <div class="sm-strip"></div></div>`;
const sr = { dot: $('.sdot', sumEl), name: $('.sm-name', sumEl), pill: $('.sm-pill', sumEl), att: $('.sm-att', sumEl), cur: $('.sm-cur', sumEl), time: $('.sm-time', sumEl), counts: $('.sm-counts', sumEl), tim: $('.sm-tim', sumEl), util: $('.sm-util', sumEl), al: $('.sm-al', sumEl), strip: $('.sm-strip', sumEl) };
let sumShown = false, headIO = null;

function stickTop() { return topbarEl.offsetHeight + (sumShown ? sumEl.offsetHeight : 0) + 12; }
function syncOffsets() {
  const root = document.documentElement.style;
  root.setProperty('--topbar-h', `${topbarEl.offsetHeight}px`);
  root.setProperty('--stick-top', `${stickTop()}px`);
}
function setSumShown(on) {
  sumShown = on;
  sumEl.classList.toggle('show', on);
  sumEl.setAttribute('aria-hidden', String(!on));
  syncOffsets();
}
function observeHead() {
  if (headIO) { headIO.disconnect(); headIO = null; }
  if (!head || typeof IntersectionObserver === 'undefined') return;
  headIO = new IntersectionObserver((es) => { const e = es[es.length - 1]; setSumShown(!e.isIntersecting && e.boundingClientRect.top < 0); },
    { rootMargin: `-${topbarEl.offsetHeight}px 0px 0px 0px`, threshold: 0 });
  headIO.observe(head);
}
if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => { syncOffsets(); if (head) observeHead(); }).observe(topbarEl);

function renderSummary(fw, flow) {
  const oc = outcomeOf(fw);
  setAttr(sr.dot, 'data-status', oc.key);
  setText(sr.name, fw.name);
  setAttr(sr.pill, 'data-status', oc.key); setText(sr.pill, oc.pill);
  const sat = fw.attempt && fw.attempt.n > 1 ? fw.attempt : null;
  sr.att.hidden = !sat; setText(sr.att, sat ? `att. ${sat.n}` : '');
  sr.att.title = sat ? `Attempt ${sat.n}${sat.mode === 'resume' ? ' (resumed from a checkpoint)' : ''}` : '';
  setText(sr.cur, fw.current ? fw.current.label : fw.status === 'done' ? 'finished' : fw.status === 'failed' ? 'failed' : fw.status);
  sr.cur.title = fw.current ? `Current: ${fw.current.label}` : '';
  const running = fw.status === 'running' && fw.started_at;
  const ep = etaParts(fw);
  const fin = ['done', 'failed', 'stopped'].includes(fw.status);
  setHTML(sr.time, `<span class="num" ${running ? `data-start="${fw.started_at}"` : ''}>${fmtDur(running ? nowS() - fw.started_at : fw.elapsed_s)}</span>${ep ? `<span class="sm-eta" title="${esc(ep.how)}">ETA ~${ep.clock} <span data-end="${ep.end}">${ep.inTxt}</span></span>` : fin && endedAt(fw) ? `<span class="sm-eta">ended ${fmtClock(endedAt(fw))}</span>` : ''}`);
  setHTML(sr.counts, badgesHTML(fw.counts));
  const t = fw.timing; const tl = fwTimingLevel(fw);
  const tv = (k, l) => {
    const c = carriedOf(t, k);
    return t && t[k] != null ? `<span class="${t[k] < 0 ? 'neg' : 'pos'}${c ? ' carried' : ''}"${c ? ` title="${esc(l + ' ' + carriedTip(c))}"` : ''}>${l} ${t[k] > 0 ? '+' : ''}${fmtNs(t[k])}${c ? '<i class="ctag">stale</i>' : ''}</span>` : `<span class="nil">${l} —</span>`;
  };
  sr.tim.dataset.tl = tl;
  setAttr(sr.tim, 'data-tl', tl);
  setHTML(sr.tim, t ? `<i class="tdot"></i>${tv('wns', 'WNS')}${tv('whs', 'WHS')}` : '<span class="nil">timing —</span>');
  sr.tim.title = t ? `${timingBadge(t, tl)[0]} · ${t.stage || t.label || ''}${t.final ? ' · final' : ' · not final'}` : 'No timing data yet';
  sr.tim.title += t && t.carried ? Object.entries(t.carried).map(([k, c]) => `\n${k.toUpperCase()} ${carriedTip(c)}`).join('') : '';
  const rows = (fw.utilization && fw.utilization.rows) || [];
  const worst = rows.reduce((b, r) => { const p = r.pct ?? (r.available ? (r.used / r.available) * 100 : 0); return p > (b ? b.p : -1) ? { p, n: r.name } : b; }, null);
  sr.util.hidden = !worst;
  if (worst) { setAttr(sr.util, 'data-lv', utilClass(worst.p) || 'ok'); setHTML(sr.util, `util <b class="num">${worst.p.toFixed(0)}%</b> <small>${esc(worst.n)}</small>`); sr.util.title = `Highest utilization: ${worst.n} ${worst.p.toFixed(1)}%`; }
  const als = fwAlerts(fw); const lvl = topLevel(als) || (fw.health && fw.health !== 'ok' ? fw.health : '');
  setAttr(sr.al, 'data-lv', lvl || 'ok');
  setHTML(sr.al, lvl ? `${alertIcon(lvl === 'error' ? 'error' : 'warning')}<b class="num">${als.length}</b>` : '<span class="okmark">✓ no alerts</span>');
  sr.al.title = als.length ? `${als.length} alert${als.length === 1 ? '' : 's'} — click to scroll up` : 'No alerts';
  const stages = flow ? flow.stages : [];
  const selId = mainEl._r && mainEl._r.selId;
  patchList(sr.strip, stages, (n) => n.id, () => { const b = h('button', 'sdotb'); b.dataset.act = 'sumstage'; return b; }, (b, n) => {
    setAttr(b, 'data-status', n.status); setAttr(b, 'data-alert', nodeLevel(n)); setAttr(b, 'data-id', n.id);
    b.classList.toggle('sel', n.id === selId);
    setAttr(b, 'title', `${n.label} · ${statusInfo(n.status).label}`); setAttr(b, 'aria-label', `${n.label}, ${statusInfo(n.status).label}`);
  });
  syncOffsets();
}
function hideSummary() { if (headIO) { headIO.disconnect(); headIO = null; } setSumShown(false); }

/* ------------------------------------------------------------------ render root */
function render() {
  const fws = state.firmwares;
  if (!selected || !fws.some((f) => f.id === selected)) {
    selected = null;
    if (hashFw) { const f = fws.find((x) => x.name === hashFw || x.id === hashFw); if (f) selected = f.id; }
    if (!selected && firstLoad) { const sv = lsGet('vmon.tab'); if (sv && fws.some((f) => f.id === sv)) selected = sv; }
    if (!selected) { const run = fws.find((f) => f.status === 'running'); selected = (run || fws[0] || {}).id || null; }
  }
  if (fws.length) firstLoad = false;
  patchList(tabsEl, fws, (f) => f.id, createTab, updateTab);
  syncTabsOverflow();

  const fw = curFw();
  if (!fw) {
    mainEl._r = null; head = null; hideSummary();
    if (!mainEl.querySelector('.empty:not(.loading)')) mainEl.innerHTML = '<div class="empty"><h2>No firmware runs yet</h2><p>Start a Vivado build, or enter a <code>.runs</code> directory, <code>.xpr</code> or log path above.</p></div>';
    return;
  }
  if (!mainEl._r) { buildView(); observeHead(); }
  const v = mainEl._r;
  if (v.fwId !== fw.id) { v.fwId = fw.id; v.stages.innerHTML = ''; v.detail.innerHTML = ''; v.detEl = null; v.selId = null; v.mvList._h = null; v.mvList.innerHTML = ''; v.tv._h = null; v.tv.innerHTML = ''; v.mvQ.value = mvOf(fw).q; }
  renderHeader(fw);
  const als = fwAlerts(fw);
  setHTML(v.banner, als.length ? `<div class="alerts${topLevel(als) === 'error' ? '' : ' compact'}" data-level="${topLevel(als)}"><div class="al-h">${als.filter((a) => a.level === 'error').length} error${als.filter((a) => a.level === 'error').length === 1 ? '' : 's'}, ${als.filter((a) => a.level !== 'error').length} warning${als.filter((a) => a.level !== 'error').length === 1 ? '' : 's'} need attention</div>${als.map((a) => {
    const pn = a.node_id && findPath(fw, a.node_id);
    const where = pn ? pn.chain.map((n) => n.label).slice(-2).join(' / ') : '';
    return `<div class="alert lvl-${esc(a.level)}" data-act="goto" data-node="${esc(a.node_id || '')}">${alertIcon(a.level)}<span class="acode" title="${esc(a.code || a.level)}">${esc(alertName(a))}</span><span class="amsg">${esc(a.message)}</span>${where ? `<span class="awhere">${esc(where)}</span>` : ''}</div>`;
  }).join('')}</div>` : '');

  const view = curView(fw);
  v.split.hidden = view !== 'flow'; v.mv.hidden = view !== 'messages'; v.tv.hidden = view !== 'timing';
  // flow selector (only when several flows)
  const flow = fw.flows.find((f) => f.id === ui.flow.get(fw.id)) || fw.flows[0];
  if (fw.flows.length > 1) {
    setHTML(v.seg, `<div class="seg">${fw.flows.map((f) => `<button class="${f === flow ? 'on' : ''}" data-act="flow" data-flow="${esc(f.id)}">${esc(f.label)}</button>`).join('')}</div>`);
  } else setHTML(v.seg, '');
  if (view === 'messages') { renderMsgView(fw); ensureTriage(fw); renderSummary(fw, flow); afterRender(); return; }
  if (view === 'timing') { renderTimingView(fw); renderSummary(fw, flow); afterRender(); return; }
  if (!flow || !flow.stages.length) { v.stages.innerHTML = ''; v.detail.innerHTML = '<div class="empty"><p>No flow data yet.</p></div>'; v.detEl = null; v.selId = null; renderSummary(fw, flow); afterRender(); return; }
  renderFlowView(fw, flow);
  renderSummary(fw, flow);
  afterRender();
}

// #scroll=N (screenshots/debug): scroll once after the first render and show the summary bar without animation.
// #shift=N: headless Firefox screenshots ignore the scroll offset, so emulate "scrolled by N px" with a transform.
function afterRender() {
  if (hashShift != null) {
    const y = hashShift; hashShift = null;
    sumEl.dataset.instant = '1';
    for (const e of [tabsEl, mainEl]) e.style.transform = `translateY(-${y}px)`;
    setSumShown(true);
  }
  if (hashScroll == null) return;
  const y = hashScroll; hashScroll = null;
  sumEl.dataset.instant = '1';
  window.scrollTo(0, y);
  const hb = head.getBoundingClientRect();
  setSumShown(hb.bottom < topbarEl.offsetHeight);
  if (hashDebug === 'overflow') debugOverflow();
}
function debugOverflow() {
  const W = document.documentElement.clientWidth; const bad = [];
  for (const e of document.querySelectorAll('body *')) { const r = e.getBoundingClientRect(); if (r.right > W + 0.5 && r.width) bad.push(`${e.tagName}.${(e.className && e.className.baseVal === undefined ? e.className : '').toString().slice(0, 40)} right=${r.right.toFixed(1)}`); }
  const pre = h('pre'); pre.style.cssText = 'position:fixed;top:0;left:0;z-index:99;background:#000;color:#0f0;font-size:11px;max-width:100%;overflow:hidden;margin:0';
  pre.textContent = `W=${W} scrollW=${document.documentElement.scrollWidth}\n${bad.slice(0, 25).join('\n')}`; document.body.appendChild(pre);
}

function setState(s) {
  state = s;
  render();
  checkAlerts();
  updateMeters(s.system);
  syncIntervalSelect();
  tickUpdated();
}

/* ------------------------------------------------------------------ events */
document.addEventListener('click', async (ev) => {
  const t = ev.target.closest('[data-act]');
  if (!t) return;
  const act = t.dataset.act;
  if (act === 'doc') return; // plain link: open in new tab, never toggles the card around it
  const nodeEl = t.closest('.node');
  if (act === 'tab') {
    const el = t.closest('.tab');
    if (ev.target.closest('.t-x')) {
      const fw = state.firmwares.find((f) => f.id === el._key);
      if (!fw) return;
      try { if (!MOCK) await fetch(`/api/firmware?fw=${encodeURIComponent(fw.id)}`, { method: 'DELETE' }); } catch { /* ignore */ }
      state = { ...state, firmwares: state.firmwares.filter((f) => f.id !== fw.id) };
      if (selected === fw.id) selected = null;
      render();
      toast(`Stopped watching ${fw.name}. Add it again with Watch or Explore.`);
      return;
    }
    selected = el._key; lsSet('vmon.tab', selected); render();
  } else if (act === 'toggle' && nodeEl) {
    const k = keyOf(nodeEl._fw, nodeEl._node);
    const au = autoOf(nodeEl._fw); const sl = ui.sel.get(nodeEl._fw.id);
    if (isOpen(nodeEl._fw, nodeEl._node)) {
      if (sl && sl.follow && nodeEl._node.status === 'running') au.dismissed.add(k); // respect a manual collapse until the running node changes
      resetNode(nodeEl._fw, nodeEl._node); // closing forgets everything below
    } else { ui.open.set(k, true); au.dismissed.delete(k); }
    render();
  } else if (act === 'dtab' && nodeEl) {
    ui.tab.set(keyOf(nodeEl._fw, nodeEl._node), t.dataset.tab); render();
  } else if (act === 'sev' && nodeEl) {
    const d = detOf(keyOf(nodeEl._fw, nodeEl._node));
    d.sev.has(t.dataset.sev) ? d.sev.delete(t.dataset.sev) : d.sev.add(t.dataset.sev);
    renderMessages(nodeEl._r.panes.messages, d, nodeEl);
  } else if (act === 'grp' && nodeEl) {
    const d = detOf(keyOf(nodeEl._fw, nodeEl._node));
    const gid = t.dataset.gid;
    d.openG.has(gid) ? d.openG.delete(gid) : d.openG.add(gid);
    renderMessages(nodeEl._r.panes.messages, d, nodeEl);
  } else if (act === 'fail-log') {
    const k = t.dataset.key; const fw = curFw();
    if (fx.has(k)) { fx.delete(k); render(); return; }
    const ex = { line: +t.dataset.line, data: null, fresh: true };
    fx.set(k, ex); render();
    apiLogAround(fw, t.dataset.log, ex.line).then((d) => { ex.data = d; }).catch((e) => { ex.data = { lines: [], error: String(e.message || e) }; }).finally(() => render());
  } else if (act === 'att-toggle') {
    const k = t.dataset.key;
    fx.has(k) ? fx.delete(k) : fx.set(k, true);
    render();
  } else if (act === 'copy') {
    const txt = t.dataset.copy;
    try { await navigator.clipboard.writeText(txt); toast('Copied'); } catch {
      const ta = document.createElement('textarea'); ta.value = txt; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); toast('Copied'); } catch { toast('Copy failed'); }
      ta.remove();
    }
  } else if (act === 'goto') {
    gotoNode(curFw(), t.dataset.node);
  } else if (act === 'rchip' && nodeEl) {
    const k = keyOf(nodeEl._fw, nodeEl._node);
    ui.open.set(k, true); ui.tab.set(k, 'reports'); ui.rsel.set(k, t.dataset.path); render();
  } else if (act === 'rsel' && nodeEl) {
    ui.rsel.set(keyOf(nodeEl._fw, nodeEl._node), t.dataset.path); render();
  } else if (act === 'raw' && nodeEl) {
    const rp = nodeEl._node.reports[+t.dataset.i];
    try { showModal(rp.name + ' — ' + rp.path, await apiReportRaw(nodeEl._fw, rp.path)); } catch (e) { toast('Could not load report: ' + e.message); }
  } else if (act === 'pth-row' || act === 'pth-type' || act === 'pth-fail') {
    const st = ui.paths.get(t.dataset.key); if (!st) return;
    if (act === 'pth-row') { const i = +t.dataset.i; st.open.has(i) ? st.open.delete(i) : st.open.add(i); }
    else if (act === 'pth-type') st.type = t.dataset.v;
    else st.failing = !st.failing;
    render();
  } else if (act === 'paths-open') {
    const fw = curFw(); if (!fw) return;
    if (fw.timing && fw.timing.report) { const st = pstOf(fw, fw.timing.report); st.failing = !!t.dataset.failing; if (st.failing) st.type = 'all'; }
    ui.view.set(fw.id, 'timing'); render();
    const el = $('.tv-sec .paths-h', mainEl); if (el) setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
  } else if (act === 'flow') {
    ui.flow.set(curFw().id, t.dataset.flow); mainEl._r.stages.innerHTML = ''; mainEl._r.selId = null; render();
  } else if (act === 'select') {
    const el = t.closest('.stg');
    ui.sel.set(el._fw.id, { id: el._node.id, follow: false }); render();
  } else if (act === 'follow') {
    const fw = curFw(); const cur = ui.sel.get(fw.id);
    if (cur && cur.follow) ui.sel.set(fw.id, { id: mainEl._r.selId, follow: false }); // toggle off: pin the stage being shown
    else ui.sel.set(fw.id, { id: null, follow: true });
    render();
  } else if (act === 'info-toggle') {
    infoOpen = !infoOpen; lsSet('vmon.infoOpen', infoOpen ? '1' : '0'); renderHeader(curFw()); syncOffsets();
  } else if (act === 'sumstage') {
    const fw = curFw(); ui.sel.set(fw.id, { id: t.dataset.id, follow: false }); ui.view.set(fw.id, 'flow'); render();
    const sp = mainEl._r.split.getBoundingClientRect().top + window.scrollY - stickTop() + 6;
    window.scrollTo({ top: Math.max(0, sp), behavior: 'smooth' });
  } else if (act === 'sumtop') {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } else if (act === 'view') {
    ui.view.set(curFw().id, t.dataset.view); render();
  } else if (act === 'topissue') {
    const fw = curFw(); const m = mvOf(fw);
    m.open.add(t.dataset.id); m.focus = t.dataset.id; ui.view.set(fw.id, 'messages'); render();
  } else if (act.startsWith('mv-')) {
    mvAction(act, t);
  } else if (act === 'explore') {
    openExplore();
  } else if (act === 'pop-toggle') {
    notif.open ? closePop() : openPop();
  } else if (act === 'perm') {
    try { await Notification.requestPermission(); } catch { /* ignore */ }
    syncBell(); renderPop();
  } else if (act === 'ntest') {
    try { new Notification('vmon · test — Notifications work', { body: 'route_design: WNS -0.123 ns (post-route)' }); } catch { /* ignore */ }
  } else if (act === 'nlog') {
    const e = notif.log[+t.dataset.i]; if (e) openEntry(e);
  } else if (act === 'nclear') {
    notif.log = []; syncBell(); renderPop();
  }
});

function mvAction(act, t) {
  const fw = curFw(); if (!fw) return;
  const m = mvOf(fw);
  const id = t.dataset.id;
  const grp = () => ((m.data && m.data.groups) || []).find((g) => g.id === id);
  if (act === 'mv-sev') { m.sev.has(t.dataset.sev) ? m.sev.delete(t.dataset.sev) : m.sev.add(t.dataset.sev); renderMsgView(fw); ensureTriage(fw); }
  else if (act === 'mv-new') { m.newOnly = !m.newOnly; renderMsgView(fw); }
  else if (act === 'mv-muted') { m.muted = !m.muted; renderMsgView(fw); ensureTriage(fw); }
  else if (act === 'mv-row') {
    if (m.open.has(id)) { m.open.delete(id); delete m.exc[id]; } else m.open.add(id);
    renderMsgView(fw);
  } else if (act === 'mv-line') { const g = grp(); if (g) loadExcerpt(fw, g, +t.dataset.line); }
  else if (act === 'mv-step') gotoNode(fw, t.dataset.node);
  else if (act === 'mv-rule') {
    apiMsgRule(fw, id, t.dataset.pri || null).then(() => { m.rev++; if (MOCK) { fw.top_messages = mockTop(fw); render(); } else ensureTriage(fw); })
      .catch((e) => toast('Could not save rule: ' + e.message));
  }
}

document.addEventListener('input', (ev) => {
  if (!ev.target.classList.contains('mv-q')) return;
  const fw = curFw(); if (!fw) return;
  const m = mvOf(fw);
  m.q = ev.target.value;
  renderMsgView(fw);                                   // instant client-side filter
  clearTimeout(m.qT); m.qT = setTimeout(() => ensureTriage(fw), 350); // then ask the server too
});

function closeModal() {
  const m = $('#modal'); if (!m || m.hidden) return false;
  m.hidden = true; if (m._ret && m._ret.isConnected) m._ret.focus();
  return true;
}
const SHORTCUTS = `1-9   switch firmware tab
f     Flow view
m     Messages view
t     Timing view (when available)
j / k next / previous stage
n     jump to the next alert
c     collapse all expanded steps
Esc   close dialog or popover
?     this help`;
let alertCursor = -1;
function moveStage(fw, d) {
  const list = [...mainEl._r.stages.querySelectorAll('.stg')].filter((e) => e._node);
  if (!list.length) return;
  const i = list.findIndex((e) => e._node.id === mainEl._r.selId);
  const nx = list[Math.max(0, Math.min(list.length - 1, (i < 0 ? 0 : i + d)))];
  ui.sel.set(fw.id, { id: nx._node.id, follow: false }); render();
  nx.scrollIntoView({ block: 'nearest' });
}
document.addEventListener('keydown', (ev) => {
  const tag = (ev.target.tagName || '').toLowerCase();
  const role = ev.target.getAttribute && ev.target.getAttribute('role');
  if ((ev.key === 'Enter' || ev.key === ' ') && (role === 'button' || role === 'tab') && tag !== 'button') { ev.preventDefault(); ev.target.click(); return; }
  if (role === 'tab' && ['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Delete'].includes(ev.key)) {
    const tabs = [...tabsEl.querySelectorAll('.tab')]; const i = tabs.indexOf(ev.target);
    if (ev.key === 'Delete') { if (!ev.target._r.x.hidden) ev.target._r.x.click(); ev.preventDefault(); return; }
    const j = ev.key === 'Home' ? 0 : ev.key === 'End' ? tabs.length - 1 : (i + (ev.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    ev.preventDefault(); tabs[j].click(); const nt = [...tabsEl.querySelectorAll('.tab')][j]; if (nt) nt.focus();
    return;
  }
  if (ev.key === 'Escape') { if (closeModal()) return; if (notif.open) { closePop(); notifyBtn.focus(); } return; }
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || ev.ctrlKey || ev.metaKey || ev.altKey || (xp.el && !xp.el.hidden)) return;
  const fw = curFw();
  if (/^[1-9]$/.test(ev.key)) {
    const f = state.firmwares[+ev.key - 1];
    if (f) { selected = f.id; lsSet('vmon.tab', selected); render(); }
  } else if (ev.key === '?') {
    showModal('Keyboard shortcuts', SHORTCUTS);
  } else if (!fw || !mainEl._r) {
    return;
  } else if (ev.key === 'f' || ev.key === 'm' || (ev.key === 't' && hasTimingView(fw))) {
    ui.view.set(fw.id, { f: 'flow', m: 'messages', t: 'timing' }[ev.key]); render();
  } else if ((ev.key === 'j' || ev.key === 'k') && curView(fw) === 'flow') {
    moveStage(fw, ev.key === 'j' ? 1 : -1);
  } else if (ev.key === 'n') {
    const al = fwAlerts(fw).filter((a) => a.node_id);
    if (!al.length) { toast('No alerts to jump to'); return; }
    alertCursor = (alertCursor + 1) % al.length;
    gotoNode(fw, al[alertCursor].node_id);
  } else if (ev.key === 'c') {
    ui.open.clear(); ui.tab.clear(); hashOpen.clear(); render();
  }
});
window.addEventListener('hashchange', () => { parseHash(); ui.open.clear(); render(); });

// client-side ticking of elapsed times
setInterval(() => {
  const t = nowS();
  for (const e of document.querySelectorAll('[data-start]')) {
    const s = parseFloat(e.dataset.start);
    if (s) { const txt = fmtDur(t - s); if (e.textContent !== txt) { e.textContent = txt; if (e._t !== undefined) e._t = txt; } }
  }
  for (const e of document.querySelectorAll('[data-end]')) {
    const rem = parseFloat(e.dataset.end) - t;
    const txt = rem > 30 ? `in ${fmtDur(rem)}` : 'any moment now';
    if (e.textContent !== txt) e.textContent = txt;
  }
}, 1000);

// running logs auto-refresh
setInterval(() => {
  for (const el of document.querySelectorAll('.node.open')) {
    const n = el._node, fw = el._fw;
    if (!n || n.status !== 'running' || !el._r.panel) continue;
    if (activeTab(fw, n, availableTabs(n)) === 'log') ensureLog(el, n, fw, true);
  }
}, 2000);

/* ------------------------------------------------------------------ top bar */
const connEl = $('#conn');
function setConn(st, text) {
  const was = connEl.dataset.state;
  setAttr(connEl, 'data-state', st); setText($('span', connEl), text); document.body.dataset.conn = st;
  if (st === 'down' && was !== 'down') announce('Connection to the vmon backend lost. Showing the last known state; retrying.');
  else if (st === 'live' && was === 'down') announce('Reconnected to the vmon backend.');
}

function applyTheme(th) {
  document.documentElement.setAttribute('data-theme', th);
  $('#theme-btn').innerHTML = th === 'dark' ? SUN : MOON;
}
{
  const pref = lsGet('vmon.theme') || 'dark';
  applyTheme(pref);
  $('#theme-btn').addEventListener('click', () => {
    const nx = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(nx); lsSet('vmon.theme', nx);
  });
}

function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 3500);
}
$('#watch-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const inp = $('#watch-input'); const path = inp.value.trim();
  if (!path) return;
  if (MOCK) { toast('Mock mode: watch ignored'); return; }
  try {
    const r = await fetch('/api/watch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
    if (!r.ok) throw new Error(await r.text() || r.status);
    inp.value = ''; toast('Watching ' + path); poll();
  } catch (e) { toast('Watch failed: ' + e.message); }
});


/* ------------------------------------------------------------------ explore: modal file browser (GET /api/browse) */
const XI = {
  folder: '<path d="M2.5 6.5a2 2 0 0 1 2-2h4l2 2.2h9a2 2 0 0 1 2 2v8.3a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2z"/>',
  file: '<path d="M6 3h8l5 5v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/>',
};
const XKIND = {
  runs: { cls: 'k-runs', tag: '.runs', tip: 'Vivado runs directory', icon: XI.folder + '<path d="M10 11.5v5l4-2.5z" fill="currentColor"/>' },
  run: { cls: 'k-run', tag: 'run', tip: 'Vivado run directory (runme.log / gen_run.xml)', icon: XI.folder + '<circle cx="12" cy="14.2" r="2.2"/>' },
  xpr: { cls: 'k-xpr', tag: '.xpr', tip: 'Vivado project file', icon: XI.file + '<path d="M9 13h6M9 16.5h4"/>' },
  project_dir: { cls: 'k-proj', tag: 'project', tip: 'Directory with a Vivado project', icon: XI.folder + '<path d="M12 10.5l1.2 2.4 2.6.4-1.9 1.8.5 2.6-2.4-1.3-2.4 1.3.5-2.6-1.9-1.8 2.6-.4z" fill="currentColor" stroke="none"/>' },
  log: { cls: 'k-log', tag: 'log', tip: 'Vivado log file', icon: XI.file + '<path d="M9 12.5h6M9 15.5h6M9 18h3.5"/>' },
};
const WATCHABLE = new Set(['runs', 'run', 'xpr', 'project_dir', 'log']);
const xIcon = (e) => { const k = XKIND[e.kind]; return `<svg class="xi ${k ? k.cls : e.type === 'dir' ? 'k-dir' : 'k-file'}" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round">${k ? k.icon : e.type === 'dir' ? XI.folder : XI.file}</svg>`; };
const xp = { el: null, path: null, parent: null, home: null, entries: [], recent: [], sel: null, filter: '', editing: false, busy: false, error: null, curKind: null, pendingSel: null, reqId: 0 };

async function apiBrowse(path) {
  if (!MOCK) {
    const r = await fetch(`/api/browse${path ? `?path=${q(path)}` : ''}`, { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status === 403 ? 'Permission denied' : r.status === 404 ? 'No such directory' : (await r.text()) || r.status);
    return r.json();
  }
  if (!mock.browse) mock.browse = syncJson('mock/browse.json');
  const b = mock.browse; const p = (path || b.home).replace(/\/+$/, '') || '/';
  const entries = b.dirs[p];
  if (!entries) throw new Error('No such directory');
  const parent = p === '/' ? null : p.slice(0, p.lastIndexOf('/')) || '/';
  return { path: p, parent, home: b.home, entries, recent: b.recent };
}

function buildExplore() {
  const el = h('div', 'modal explore', `
    <div class="xbox" role="dialog" aria-label="Explore folders">
      <div class="xhead"><b>Explore</b><span class="xhint">Pick a Vivado <code>.runs</code> dir, run, <code>.xpr</code> project or log to watch</span><button class="mclose icon-btn" data-xact="close" title="Close (Esc)">✕</button></div>
      <div class="xbar">
        <button class="xnav" data-xact="up" title="Parent folder (Backspace)" aria-label="Parent folder"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V6M6 11l6-6 6 6"/></svg></button>
        <div class="xpath" data-xact="edit" title="Click to type a path (Ctrl+L)"><div class="crumbs"></div><input class="xpath-in" type="text" spellcheck="false" autocomplete="off" hidden></div>
        <input class="xfilter" type="search" placeholder="Filter…" spellcheck="false" autocomplete="off" aria-label="Filter entries">
      </div>
      <div class="xbody">
        <nav class="xside"></nav>
        <div class="xlist" role="listbox" tabindex="-1"></div>
      </div>
      <div class="xfoot"><span class="xsel mono"></span><button class="xcancel" data-xact="close">Cancel</button><button class="primary xwatch" data-xact="watch" disabled>Watch</button></div>
    </div>`);
  el.hidden = true; el.id = 'explore';
  document.body.appendChild(el);
  xp.el = el;
  xp.r = { crumbs: $('.crumbs', el), pathBox: $('.xpath', el), pathIn: $('.xpath-in', el), filter: $('.xfilter', el), side: $('.xside', el), list: $('.xlist', el), sel: $('.xsel', el), watch: $('.xwatch', el) };
  el.addEventListener('mousedown', (ev) => { if (ev.target === el) closeExplore(); });
  el.addEventListener('click', (ev) => {
    const t = ev.target.closest('[data-xact]');
    if (t) {
      const a = t.dataset.xact;
      if (a === 'close') closeExplore();
      else if (a === 'up') { if (xp.parent) exploreGo(xp.parent); }
      else if (a === 'watch') exploreWatch();
      else if (a === 'go') exploreGo(t.dataset.path);
      else if (a === 'recent') exploreRecent(t.dataset.path);
      else if (a === 'edit' && !ev.target.closest('.xseg')) exploreEdit(true);
      return;
    }
    const row = ev.target.closest('.xrow');
    if (row) { xp.sel = row.dataset.path; renderExplore(); xp.r.filter.focus(); }
  });
  el.addEventListener('dblclick', (ev) => { const row = ev.target.closest('.xrow'); if (row) exploreOpen(row.dataset.path); });
  xp.r.filter.addEventListener('input', () => { xp.filter = xp.r.filter.value; const v = exploreVisible(); if (!v.some((e) => e.path === xp.sel)) xp.sel = v.length && xp.filter ? v[0].path : null; renderExplore(); });
  xp.r.pathIn.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); const v = xp.r.pathIn.value.trim(); exploreEdit(false); if (v) exploreGo(v); }
    else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); exploreEdit(false); }
  });
  xp.r.pathIn.addEventListener('blur', () => { if (xp.editing) exploreEdit(false); });
  el.addEventListener('keydown', exploreKey);
}

function exploreVisible() {
  const f = xp.filter.trim().toLowerCase();
  return xp.entries.filter((e) => !f || e.name.toLowerCase().includes(f))
    .sort((a, b) => (a.type === 'dir' ? 0 : 1) - (b.type === 'dir' ? 0 : 1) || a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
}

function exploreKey(ev) {
  if (ev.target === xp.r.pathIn) return;
  const vis = exploreVisible();
  const i = vis.findIndex((e) => e.path === xp.sel);
  const move = (j) => { if (!vis.length) return; xp.sel = vis[Math.max(0, Math.min(vis.length - 1, j))].path; renderExplore(); const r = xp.r.list.querySelector('.xrow.sel'); if (r) r.scrollIntoView({ block: 'nearest' }); };
  if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); if (xp.filter) { xp.filter = ''; xp.r.filter.value = ''; renderExplore(); } else closeExplore(); }
  else if (ev.key === 'ArrowDown') { ev.preventDefault(); move(i + 1); }
  else if (ev.key === 'ArrowUp') { ev.preventDefault(); move(i < 0 ? vis.length - 1 : i - 1); }
  else if (ev.key === 'Home' && ev.target !== xp.r.filter) { ev.preventDefault(); move(0); }
  else if (ev.key === 'End' && ev.target !== xp.r.filter) { ev.preventDefault(); move(vis.length - 1); }
  else if (ev.key === 'Enter') {
    if (ev.target.closest('button') && ev.target.dataset.xact) return; // let a focused button activate itself
    ev.preventDefault();
    const e = vis[i >= 0 ? i : (xp.filter && vis.length ? 0 : -1)];
    if (e) exploreOpen(e.path); else if (exploreTarget()) exploreWatch();
  } else if (ev.key === 'Backspace' && !xp.r.filter.value && xp.parent) { ev.preventDefault(); exploreGo(xp.parent); }
  else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'l') { ev.preventDefault(); exploreEdit(true); }
  else if (ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey && ev.target !== xp.r.filter) { xp.r.filter.focus(); } // type-to-filter
}

function exploreEdit(on) {
  xp.editing = on;
  const r = xp.r;
  r.pathIn.hidden = !on; r.crumbs.hidden = on;
  if (on) { r.pathIn.value = xp.path || ''; r.pathIn.focus(); r.pathIn.select(); } else if (!xp.el.hidden) r.filter.focus();
}

function exploreOpen(path) {
  const e = xp.entries.find((x) => x.path === path);
  if (!e) return;
  if (e.type === 'dir') exploreGo(e.path, e.kind);
  else if (WATCHABLE.has(e.kind)) { xp.sel = e.path; exploreWatch(); }
}

function exploreRecent(path) {
  // show the recent entry inside its parent, selected, as a file manager would
  const i = path.replace(/\/+$/, '').lastIndexOf('/');
  exploreGo(i > 0 ? path.slice(0, i) : '/', null, path);
}

async function exploreGo(path, kind = null, selectPath = null) {
  const id = ++xp.reqId;
  xp.busy = true; renderExplore();
  try {
    const d = await apiBrowse(path);
    if (id !== xp.reqId) return;
    Object.assign(xp, { path: d.path, parent: d.parent, home: d.home, entries: d.entries || [], recent: d.recent || xp.recent, error: null, curKind: kind, sel: selectPath, filter: '' });
    xp.r.filter.value = '';
    lsSet('vmon.browse', d.path);
  } catch (e) {
    if (id !== xp.reqId) return;
    xp.error = `Cannot open ${path}: ${e.message}`; xp.entries = [];
  }
  xp.busy = false; renderExplore();
  const r = xp.r.list.querySelector('.xrow.sel'); if (r) r.scrollIntoView({ block: 'nearest' }); else xp.r.list.scrollTop = 0;
}

function exploreTarget() {
  const e = xp.entries.find((x) => x.path === xp.sel);
  if (e) return WATCHABLE.has(e.kind) ? { path: e.path, kind: e.kind } : null;
  return xp.sel == null && WATCHABLE.has(xp.curKind) ? { path: xp.path, kind: xp.curKind } : null;
}

async function exploreWatch() {
  const t = exploreTarget(); if (!t) return;
  closeExplore();
  if (MOCK) { toast(`Mock mode: would watch ${t.path}`); return; }
  const before = new Set(state.firmwares.map((f) => f.id));
  try {
    const r = await fetch('/api/watch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: t.path }) });
    if (!r.ok) throw new Error((await r.text()) || r.status);
  } catch (e) { toast('Watch failed: ' + e.message); return; }
  toast('Watching ' + t.path);
  const norm = (x) => String(x || '').replace(/\/+$/, '');
  const base = norm(t.path).replace(/\.(xpr|log)$/, '');
  for (let i = 0; i < 14; i++) {
    await poll();
    const hit = state.firmwares.find((f) => !before.has(f.id)) || state.firmwares.find((f) => norm(f.path) === norm(t.path) || norm(f.path).startsWith(base) || norm(t.path).startsWith(norm(f.path)));
    if (hit) { selected = hit.id; lsSet('vmon.tab', selected); render(); return; }
    await new Promise((res) => setTimeout(res, 700));
  }
}

function renderExplore() {
  const r = xp.r;
  // breadcrumb
  const parts = (xp.path || '/').split('/').filter(Boolean);
  let acc = '';
  const segs = [`<button class="xseg" data-xact="go" data-path="/" title="/">/</button>`].concat(parts.map((p) => { acc += '/' + p; return `<span class="xsep">›</span><button class="xseg" data-xact="go" data-path="${esc(acc)}" title="${esc(acc)}">${esc(p)}</button>`; }));
  setHTML(r.crumbs, segs.join(''));
  r.crumbs.scrollLeft = r.crumbs.scrollWidth;
  // sidebar
  const home = xp.home;
  const place = (icon, label, path, act = 'go') => `<button class="xplace${xp.path === path ? ' on' : ''}" data-xact="${act}" data-path="${esc(path)}" title="${esc(path)}">${icon}<span>${esc(label)}</span></button>`;
  const IC = (d) => `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const rec = (xp.recent || []).map((p) => `<button class="xplace recent${xp.sel === p ? ' on' : ''}" data-xact="recent" data-path="${esc(p)}" title="${esc(p)}">${IC(XI.folder)}<span>${esc(p.split('/').filter(Boolean).slice(-2).join('/'))}</span></button>`).join('');
  setHTML(r.side, `<div class="xsh">Places</div>${home ? place(IC('<path d="M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10"/>'), 'Home', home) : ''}${place(IC('<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/>'), 'Root', '/')}<div class="xsh">Recent</div>${rec || '<div class="xnone">Nothing watched yet</div>'}`);
  // list
  const vis = exploreVisible();
  let body;
  if (xp.error) body = `<div class="xmsg err">${esc(xp.error)}</div>`;
  else if (xp.busy && !xp.entries.length) body = '<div class="xmsg">Loading…</div>';
  else if (!xp.entries.length) body = '<div class="xmsg">This folder is empty (only Vivado-relevant files are listed).</div>';
  else if (!vis.length) body = `<div class="xmsg">No entries match “${esc(xp.filter)}”.</div>`;
  else body = vis.map((e) => {
    const k = XKIND[e.kind];
    return `<div class="xrow${e.path === xp.sel ? ' sel' : ''}${k ? ' rel' : ''}" role="option" aria-selected="${e.path === xp.sel}" data-path="${esc(e.path)}" data-type="${e.type}">${xIcon(e)}<span class="xname">${esc(e.name)}</span>${k ? `<span class="xbadge ${k.cls}" title="${esc(k.tip)}">${k.tag}</span>` : ''}${e.live ? '<span class="xlive" title="A Vivado process is working here">live</span>' : ''}<span class="xmt num">${e.mtime ? fmtClock(e.mtime) : ''}</span></div>`;
  }).join('');
  setHTML(r.list, body);
  // footer
  const tgt = exploreTarget();
  r.watch.disabled = !tgt;
  const selE = xp.entries.find((x) => x.path === xp.sel);
  setText(r.sel, tgt ? tgt.path : selE ? `${selE.path} — not watchable (open it, or pick a .runs / run / .xpr / log)` : xp.path || '');
  r.sel.classList.toggle('ok', !!tgt);
  r.watch.title = tgt ? `Watch ${tgt.path}` : 'Select a .runs dir, run, .xpr, project folder or log';
}

function openExplore(startPath) {
  if (!xp.el) buildExplore();
  xp.el.hidden = false;
  closePop();
  exploreEdit(false);
  xp.r.filter.value = ''; xp.filter = '';
  exploreGo(startPath || lsGet('vmon.browse') || null).then(() => { if (xp.error && !startPath) exploreGo(null); });
  xp.r.filter.focus();
}
function closeExplore() { if (xp.el) { xp.reqId++; xp.el.hidden = true; xp.editing = false; } }

/* ---- notifications bell + popover (permission is only ever requested from the popover button) */
const notifyBtn = $('#notify-btn');
const popEl = $('#notif-pop');
const badgeEl = $('#bell-badge');
function syncBell() {
  const unread = notif.log.filter((e) => !e.read).length;
  badgeEl.hidden = !unread; setText(badgeEl, unread > 99 ? '99+' : String(unread));
  const p = 'Notification' in window ? Notification.permission : 'unsupported';
  notifyBtn.dataset.on = p === 'granted' ? '1' : '0';
  notifyBtn.title = unread ? `${unread} unread notification${unread === 1 ? '' : 's'}` : 'Notifications';
  notifyBtn.setAttribute('aria-label', notifyBtn.title);
}
function openPop() { notif.open = true; popEl.hidden = false; renderPop(); }
function closePop() {
  if (!notif.open) return;
  notif.open = false; popEl.hidden = true;
  notif.log.forEach((e) => { e.read = true; }); syncBell();
}
function fmtAgo(t) {
  const d = nowS() - t;
  return d < 60 ? 'just now' : `${fmtDur(d)} ago`;
}
function renderPop() {
  if (!notif.open) return;
  const sup = 'Notification' in window;
  const perm = sup ? Notification.permission : 'unsupported';
  const permRow = perm === 'granted' ? '<div class="np-perm ok"><span>Browser notifications are on</span><button class="rawbtn" data-act="ntest">send test</button></div>'
    : perm === 'denied' ? '<div class="np-perm bad"><span>Blocked by the browser. Allow notifications for this site in the address-bar settings.</span></div>'
    : perm === 'unsupported' ? '<div class="np-perm bad"><span>This browser does not support notifications. The log below still works.</span></div>'
    : '<div class="np-perm"><span>Get a desktop notification even when this tab is in the background.</span><button class="primary" data-act="perm">Enable browser notifications</button></div>';
  const box = (grp, k, lbl) => `<label class="np-opt"><input type="checkbox" data-grp="${grp}" data-k="${k}"${notif.cfg[grp][k] ? ' checked' : ''}><span>${lbl}</span>${grp === 'codes' && k !== 'other' ? `<code>${k}</code>` : ''}</label>`;
  const log = notif.log.length ? notif.log.map((e, i) => `<div class="nl lvl-${esc(e.level)}${e.read ? '' : ' unread'}" data-act="nlog" data-i="${i}"><span class="nl-dot"></span><div class="nl-b"><div class="nl-t">${esc(e.evTitle)}<span class="nl-fw">${esc(e.fwName)}</span><span class="nl-when" title="${new Date(e.t * 1000).toLocaleString()}">${new Date(e.t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })} · ${fmtAgo(e.t)}</span></div><div class="nl-m">${esc(e.body)}</div></div></div>`).join('')
    : '<div class="none">Nothing yet. Events that match your choices above are collected here.</div>';
  const html = `<div class="np-head"><b>Notifications</b></div>${permRow}
    <div class="np-cols"><div><div class="np-h">Notify me when a…</div>${EVENT_KINDS.map(([k, l]) => box('kinds', k, l)).join('')}</div>
    <div><div class="np-h">…or an alert of type</div>${ALERT_CODES.map(([k, l]) => box('codes', k, l)).join('')}</div></div>
    <div class="np-loghead"><b>Recent</b>${notif.log.length ? '<button class="rawbtn" data-act="nclear">clear</button>' : ''}</div><div class="np-log">${log}</div>`;
  if (popEl._h !== html) setHTML(popEl, html);
}
popEl.addEventListener('change', (ev) => {
  const c = ev.target; if (!c.dataset.grp) return;
  notif.cfg[c.dataset.grp][c.dataset.k] = c.checked; saveNotif();
});
document.addEventListener('mousedown', (ev) => { if (notif.open && !ev.target.closest('.bellwrap')) closePop(); });
syncBell();

/* ---- system meters, "updated … ago", update interval */
const meterEl = $('#meters');
const METERS = [['cpu', 'CPU'], ['ram', 'RAM'], ['swap', 'Swap']];
meterEl.innerHTML = METERS.map(([k, l]) => `<div class="meter" data-k="${k}"><span class="m-l">${l}</span><span class="m-bar"><i></i></span><span class="m-v num">—</span></div>`).join('');
const gb = (mb) => `${(mb / 1024).toFixed(mb >= 10240 ? 0 : 1)}`;
function updateMeters(sys) {
  meterEl.hidden = !sys;
  if (!sys) return;
  const rows = {
    cpu: { pct: sys.cpu_pct, txt: `${Math.round(sys.cpu_pct)}%`, tip: `CPU ${sys.cpu_pct.toFixed(1)}% busy across ${sys.cpu_count} logical CPUs\nLoad average (1 min): ${sys.load1.toFixed(2)}` },
    ram: { pct: sys.mem_total_mb ? (sys.mem_used_mb / sys.mem_total_mb) * 100 : 0, txt: `${gb(sys.mem_used_mb)}/${gb(sys.mem_total_mb)} GB`, tip: `RAM: ${(sys.mem_used_mb / 1024).toFixed(2)} GB used of ${(sys.mem_total_mb / 1024).toFixed(2)} GB (MemTotal − MemAvailable)` },
    swap: { pct: sys.swap_total_mb ? (sys.swap_used_mb / sys.swap_total_mb) * 100 : 0, txt: sys.swap_total_mb ? `${gb(sys.swap_used_mb)}/${gb(sys.swap_total_mb)} GB` : 'off', tip: sys.swap_total_mb ? `Swap: ${(sys.swap_used_mb / 1024).toFixed(2)} GB used of ${(sys.swap_total_mb / 1024).toFixed(2)} GB` : 'No swap configured' },
  };
  for (const el of meterEl.children) {
    const r = rows[el.dataset.k]; const p = Math.max(0, Math.min(100, r.pct));
    $('.m-bar i', el).style.width = `${p}%`;
    setText($('.m-v', el), r.txt);
    setAttr(el, 'data-level', p >= 90 ? 'crit' : p >= 80 ? 'warn' : 'ok');
    setAttr(el, 'title', `${r.tip}\n${p.toFixed(0)}% — amber above 80%, red above 90%`);
  }
}

const updatedEl = $('#updated');
const ivlEl = $('#ivl');
const curInterval = () => (state.settings && state.settings.interval) || 1;
function tickUpdated() {
  if (!state.generated_at) { setText(updatedEl, 'updated —'); return; }
  const age = Math.max(0, nowS() - state.generated_at);
  setText(updatedEl, `updated ${age < 10 ? age.toFixed(1) : Math.round(age)} s ago`);
  const stale = age > 3 * curInterval();
  setAttr(updatedEl, 'data-stale', stale ? '1' : '0');
  updatedEl.title = stale ? `No fresh data for more than 3 × the ${curInterval()} s interval — the backend may be busy or disconnected` : 'Time since the backend last produced a snapshot';
}
setInterval(tickUpdated, 200);
function syncIntervalSelect() {
  const iv = curInterval();
  if (document.activeElement === ivlEl) return;
  if (![...ivlEl.options].some((o) => +o.value === iv)) {
    const o = document.createElement('option'); o.value = iv; o.textContent = `${iv} s`;
    const at = [...ivlEl.options].find((x) => +x.value > iv); ivlEl.insertBefore(o, at || null);
  }
  ivlEl.value = String(iv);
}
ivlEl.addEventListener('change', async () => {
  try { await apiSettings(+ivlEl.value); toast(`Update interval set to ${ivlEl.value} s`); } catch (e) { toast('Could not set interval: ' + e.message); syncIntervalSelect(); }
});

/* ------------------------------------------------------------------ live transport */
let pollTimer = null;
async function poll() {
  try { setState(await jget('/api/state')); if (!es || es.readyState !== 1) setConn('polling', 'polling'); }
  catch { setConn('down', 'offline'); }
}
function startPolling() { if (!pollTimer) { poll(); pollTimer = setInterval(poll, 2000); } }
function stopPolling() { clearInterval(pollTimer); pollTimer = null; }

let es = null;
function connectSSE() {
  if (typeof EventSource === 'undefined') { startPolling(); return; }
  es = new EventSource('/api/events');
  es.onopen = () => { setConn('live', 'live'); };
  es.addEventListener('state', (ev) => {
    stopPolling(); setConn('live', 'live');
    try { setState(JSON.parse(ev.data)); } catch (e) { console.error('bad state', e); }
  });
  es.onerror = () => { setConn('down', 'reconnecting…'); startPolling(); }; // EventSource retries by itself
}

/* ------------------------------------------------------------------ mock mode */
function mockAdvance() {
  const fw = state.firmwares.find((f) => f.name === 'lockin');
  if (!fw) return;
  mock.tick++;
  const T = mock.tick;
  const stages = fw.flows[0].stages;
  const runningChain = () => {
    const chain = []; let list = stages;
    for (;;) { const k = list.find((c) => c.status === 'running'); if (!k) break; chain.push(k); list = k.children || []; }
    return chain;
  };
  const chain = runningChain();
  const w = Math.random() < 0.7 ? Math.ceil(Math.random() * 3) : 0;
  const inf = Math.random() < 0.5 ? 1 : 0;
  for (const nd of [...chain, { counts: fw.counts }]) { nd.counts.warning += w; nd.counts.info += inf; }
  const place = stages.find((s) => s.id === 'impl_1/place_design');
  if (T % 4 === 0 && place.status === 'running' && place.timing) {
    const last = place.timing.history[place.timing.history.length - 1];
    const wns = Math.min(0.02, +(last.wns + 0.011 + Math.random() * 0.01).toFixed(3));
    const tns = Math.min(0, +(last.tns * 0.8).toFixed(1));
    place.timing.history.push({ t: nowS(), line: last.line + 200, label: 'Estimated Timing Summary', wns, tns, whs: null, ths: null });
    Object.assign(place.timing, { wns, tns, met: wns >= 0 && tns >= 0 });
    fw.timing = place.timing;
    if (place.timing.met) { place.alerts = []; fw.alerts = fw.alerts.filter((a) => a.code !== 'timing_fail'); }
  }
  // every 8 ticks: finish the deepest running node and start the next expected one
  if (T % 8 === 0 && chain.length > 1) {
    const finish = (nd) => {
      nd.status = 'done'; nd.ended_at = nowS(); nd.elapsed_s = nd.started_at ? nowS() - nd.started_at : 5; nd.expected = false;
      if (stages.includes(nd)) fw.events.push({ t: nowS(), kind: 'step_done', level: 'info', code: null, node_id: nd.id, title: `${nd.label} finished`, message: `${nd.label} completed in ${fmtDur(nd.elapsed_s)}` });
    };
    const startFirst = (nd) => { nd.status = 'running'; nd.expected = false; nd.started_at = nowS(); const c = (nd.children || []).find((x) => x.status === 'pending'); if (c) startFirst(c); };
    for (let i = chain.length - 1; i >= 0; i--) {
      const nd = chain[i];
      finish(nd);
      const sibs = i > 0 ? chain[i - 1].children : stages;
      const nx = sibs[sibs.indexOf(nd) + 1];
      if (nx && nx.status === 'pending') { startFirst(nx); break; }
    }
    const nc = runningChain();
    if (nc.length) {
      fw.current = { node_id: nc[nc.length - 1].id, label: `${nc[0].label} / ${nc[nc.length - 1].label}` };
      place.progress.done = Math.min(place.progress.total, (place.children[0].children || []).filter((c) => c.status === 'done').length);
    }
  }
  fw.elapsed_s = nowS() - fw.started_at; fw.updated_at = nowS(); state.generated_at = nowS(); state.tick = T;
  const sys = state.system;
  const wob = (v, lo, hi, d) => Math.max(lo, Math.min(hi, v + (Math.random() - 0.5) * d));
  sys.cpu_pct = wob(sys.cpu_pct, 8, 98, 18); sys.load1 = wob(sys.load1, 0.5, 16, 0.8);
  sys.mem_used_mb = wob(sys.mem_used_mb, 12000, 31000, 400);
  fw.resources = { cpu_pct: wob(fw.resources.cpu_pct, 90, 420, 60), rss_mb: wob(fw.resources.rss_mb, 3800, 6200, 40) };
  const ev = (kind, level, code, node_id, title, message) => { fw.events.push({ t: nowS(), kind, level, code, node_id, title, message }); if (fw.events.length > 100) fw.events.shift(); };
  if (T % 11 === 0) {
    const pick = (T / 11) % 4;
    if (pick === 0) ev('alert', 'warning', 'critical_warning', 'impl_1/place_design', 'Critical warning', 'Vivado 12-4739: create_clock found no valid object');
    else if (pick === 1) ev('alert', 'warning', 'timing_fail', 'impl_1/place_design', 'Timing not met', `place_design: WNS ${place.timing ? place.timing.wns.toFixed(3) : '-0.100'} ns (estimated)`);
    else if (pick === 2) ev('alert', 'warning', 'utilization', 'impl_1/place_design', 'High utilization', 'DSP at 87% of device');
    else ev('alert', 'error', 'drc', 'impl_1/opt_design', 'DRC problem', 'DPIP-1: 2 DSP48E2 inputs not pipelined');
  }
  const lg = mock.logs.lockin;
  if (lg) {
    const pool = ['Phase 1.3 Build Placer Netlist Model', 'WARNING: [Place 46-29] Reduced number of nets for congestion estimation', 'INFO: [Timing 38-35] Done setting XDC timing constraints.', `Time (s): cpu = 00:00:${String(T % 60).padStart(2, '0')} ; elapsed = 00:00:${String(T % 60).padStart(2, '0')} . Memory (MB): peak = ${3050 + T}.2 ; gain = 0.0`];
    lg.lines.push(pool[T % pool.length]); if (lg.lines.length > 300) lg.lines.shift();
    lg.end_line = lg.start_line + lg.lines.length - 1;
  }
  setState(state);
}

// Sync XHR on purpose (mock only): data is ready before the window load event, which
// makes headless screenshots deterministic.
function syncJson(url) { const x = new XMLHttpRequest(); x.open('GET', url, false); x.send(); return JSON.parse(x.responseText); }
function startMock() {
  setConn('mock', 'mock data');
  const s = syncJson('mock/state.json');
  shiftTimes(s, nowS() - s.generated_at);
  for (const f of s.firmwares) f.top_messages = mockTop(f);
  mock.logs.lockin = syncJson('mock/log_lockin.json');
  setState(s);
  setInterval(mockAdvance, 1000);
}

/* ------------------------------------------------------------------ v6: worst paths, clocks, router convergence */
const fmtSlack = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(3)}`);
const fmtInt = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US'));
const slackCls = (v) => (v == null ? 'nil' : v < 0 ? 'neg' : v < 0.05 ? 'tight' : 'pos');
function shortPath(s) {
  if (!s) return '—';
  const parts = String(s).split('/');
  return parts.length <= 3 ? s : `…/${parts.slice(-2).join('/')}`;
}
function reportOf(fw, path) {
  let found = null;
  for (const f of fw.flows || []) walk(f.stages, (n) => { for (const r of n.reports || []) if (r.path === path) found = r; });
  return found;
}

// ---- worst paths table (shared by the Timing view, the step Timing tab and the Reports tab)
const pstOf = (fw, path) => {
  const k = `${fw.id}|${path}`;
  let s = ui.paths.get(k);
  if (!s) { s = { key: k, type: 'all', failing: false, open: new Set(hashPth), data: null, sig: null, busy: false, err: null }; ui.paths.set(k, s); }
  return s;
};
async function apiPaths(fw, path) {
  if (MOCK) { const d = await jget('mock/paths.json'); return d[path] || d.default; }
  return jget(`/api/paths?fw=${q(fw.id)}&path=${q(path)}`);
}
function ensurePaths(fw, path, sig) {
  const s = pstOf(fw, path);
  if (s.busy || s.sig === sig) return s;
  s.busy = true;
  apiPaths(fw, path).then((d) => { s.data = d; s.err = null; s.sig = sig; })
    .catch((e) => { s.err = String(e.message || e); s.sig = sig; })
    .finally(() => { s.busy = false; render(); });
  return s;
}
function splitBar(p) {
  if (p.logic_pct == null) return '<span class="nil">—</span>';
  return `<span class="splitwrap" title="logic ${p.logic_delay.toFixed(3)} ns (${p.logic_pct.toFixed(0)}%) · route ${p.route_delay.toFixed(3)} ns (${p.route_pct.toFixed(0)}%)"><span class="splitbar"><i style="width:${Math.max(2, p.logic_pct).toFixed(1)}%"></i></span><small class="num">${p.logic_pct.toFixed(0)}/${p.route_pct.toFixed(0)}</small></span>`;
}
const clkPair = (p) => {
  const a = p.from_clock || p.source_clock, b = p.to_clock || p.dest_clock;
  if (!a && !b) return '<span class="nil">—</span>';
  return a === b || !b ? `<span class="mono" title="${esc(a || b)}">${esc(a || b)}</span>`
    : `<span class="mono" title="${esc(a)} → ${esc(b)}">${esc(a)}<i class="arr">→</i>${esc(b)}</span>`;
};
function pathDetail(p) {
  const kv = (k, v) => `<div class="pd-kv"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  const ns = (v) => (v == null ? '—' : `${v.toFixed(3)} ns`);
  const cells = Object.entries(p.cells || {}).map(([c, n]) => `${esc(c)}×${n}`).join(' ');
  return `<div class="pd">
    <div class="pd-names"><div><span class="k">Source</span><code>${esc(p.source || '—')}</code><small>${esc(p.source_clock || '')}</small></div>
    <div><span class="k">Destination</span><code>${esc(p.destination || '—')}</code><small>${esc(p.dest_clock || '')}</small></div></div>
    <div class="pd-grid">
      ${kv('Slack', `<b class="num ${slackCls(p.slack)}">${fmtSlack(p.slack)} ns</b> (${esc(p.status)})`)}
      ${kv('Type', `${esc(p.path_type || p.type)}${p.corner ? ` <small>(${esc(p.corner)})</small>` : ''}`)}
      ${kv('Path group', esc(p.group || '—'))}
      ${kv('Requirement', ns(p.requirement))}
      ${kv('Data path delay', ns(p.data_delay))}
      ${kv('Logic / route', p.logic_delay == null ? '—' : `${ns(p.logic_delay)} (${p.logic_pct.toFixed(1)}%) / ${ns(p.route_delay)} (${p.route_pct.toFixed(1)}%)`)}
      ${kv('Logic levels', `${p.levels ?? '—'}${cells ? ` <small>${cells}</small>` : ''}`)}
      ${kv('Clock path skew', ns(p.skew))}
      ${kv('Clock uncertainty', ns(p.uncertainty))}
      ${kv('From → to clock', `${esc(p.from_clock || '—')} → ${esc(p.to_clock || '—')}`)}
    </div></div>`;
}
function pathsHTML(fw, path, sig, anchor = '') {
  const s = ensurePaths(fw, path, sig);
  const rep = reportOf(fw, path);
  const head = `<div class="paths-h" id="paths-${esc(anchor)}"><b>Worst paths</b>`;
  if (!s.data) return `${head}</div><div class="none">${s.err ? `Could not load paths: ${esc(s.err)}` : 'Loading paths…'}</div>`;
  const c = s.data.counts || {};
  const all = s.data.paths || [];
  const shown = all.filter((p) => (s.type === 'all' || p.type === s.type) && (!s.failing || p.status === 'VIOLATED'));
  const chip = (act, val, label, on, extra = '') => `<button class="rchip pf${on ? ' on' : ''}${extra}" data-act="${act}" data-key="${esc(s.key)}" data-v="${val}">${label}</button>`;
  const info = `${c.shown ?? all.length} of ${fmtInt(c.total)} paths${c.capped ? ' (worst kept)' : ''}${c.failing ? ` · <span class="neg">${fmtInt(c.failing)} failing</span> (${c.setup_failing || 0} setup, ${c.hold_failing || 0} hold) in ${c.failing_clocks} clock${c.failing_clocks === 1 ? '' : 's'}` : ' · none failing'}`;
  const rows = shown.map((p) => {
    const open = s.open.has(p.id);
    return `<tr class="prow${p.status === 'VIOLATED' ? ' viol' : ''}${open ? ' open' : ''}" data-act="pth-row" data-key="${esc(s.key)}" data-i="${p.id}" title="Click for all fields">
      <td class="num sl ${slackCls(p.slack)}">${fmtSlack(p.slack)}</td><td><span class="ptype ${p.type}">${p.type}</span></td>
      <td class="clk">${clkPair(p)}</td>
      <td class="pn"><span class="mono" title="${esc(p.source || '')}">${esc(shortPath(p.source))}</span><i class="arr">→</i><span class="mono" title="${esc(p.destination || '')}">${esc(shortPath(p.destination))}</span></td>
      <td class="num lv" title="${esc(Object.entries(p.cells || {}).map(([k, n]) => `${k}×${n}`).join(' '))}">${p.levels ?? '—'}</td>
      <td>${splitBar(p)}</td><td class="num sk">${p.skew == null ? '—' : p.skew.toFixed(3)}</td></tr>${open ? `<tr class="pdrow"><td colspan="7">${pathDetail(p)}</td></tr>` : ''}`;
  }).join('');
  return `${head}<span class="paths-info">${info}</span></div>
    <div class="pfilters">${chip('pth-type', 'all', 'All', s.type === 'all')}${chip('pth-type', 'setup', 'Setup', s.type === 'setup')}${chip('pth-type', 'hold', 'Hold', s.type === 'hold')}${chip('pth-fail', '1', 'Failing only', s.failing, c.failing ? ' bad' : '')}</div>
    ${shown.length ? `<div class="ptable-wrap"><table class="hist paths"><thead><tr><th>Slack</th><th>Type</th><th>Clocks</th><th>Source → destination</th><th title="Logic levels">Lv</th><th title="Logic vs route delay (%)">Logic / route</th><th title="Clock path skew (ns)">Skew</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : `<div class="none">${s.failing ? 'No failing paths in this report.' : 'No paths match.'}</div>`}
    ${rep ? '' : ''}`;
}

// ---- Timing view (firmware level): clocks, stages, worst paths
function clockTrend(vals, labels) {
  const pts = vals.filter((v) => v != null);
  if (!pts.length) return '<span class="nil">—</span>';
  const tip = vals.map((v, i) => `${labels[i]}: ${v == null ? '—' : fmtSlack(v)}`).join('\n');
  return `<span title="${esc(tip)}">${spark(vals, 92, 24, { dots: false })}</span>`;
}
function deltaCell(cur, prev, bad) {
  if (cur == null || prev == null) return '<td class="num nil">—</td>';
  const d = cur - prev;
  if (Math.abs(d) < 0.0005) return '<td class="num nil">=</td>';
  const worse = d < 0;
  const cls = worse ? (bad ? 'dneg' : 'dwarn') : 'dpos';
  return `<td class="num ${cls}">${worse ? '▼' : '▲'} ${Math.abs(d).toFixed(3)}</td>`;
}
function clocksHTML(fw) {
  const ch = fw.clock_history;
  if (!ch || !ch.clocks.length) return '<div class="none">Per-clock numbers appear once Vivado writes a timing summary report, usually after place_design and route_design.</div>';
  const builds = ch.builds || [];
  const cur = builds.length ? builds[builds.length - 1] : null;
  const prev = builds.length > 1 ? builds[builds.length - 2] : null;
  const latestStage = (ch.stages || []).slice(-1)[0];
  const now = (cur && cur.per_clock) || (latestStage && latestStage.per_clock) || {};
  const periods = {};
  for (const c of (fw.timing && fw.timing.clocks) || []) periods[c.name] = c.period;
  const labels = builds.map((b) => b.label + (b.current ? ' (in progress)' : ''));
  const worse = ch.clocks.filter((n) => prev && now[n] && prev.per_clock[n] && now[n].wns < prev.per_clock[n].wns - 0.0005);
  const rows = ch.clocks.map((n) => {
    const a = now[n]; const b = prev && prev.per_clock[n];
    const isWorse = !!(a && b && a.wns < b.wns - 0.0005);
    const bad = !!(a && (a.wns < 0 || (a.whs != null && a.whs < 0)));
    const cls = isWorse ? (bad ? ' worse bad' : ' worse') : '';
    return `<tr class="${cls.trim()}"><td class="mono cn" title="${esc(n)}">${esc(n)}${isWorse ? '<i class="wtag">worse</i>' : ''}${a && !b && prev ? '<i class="ntag">new</i>' : ''}</td>
      <td class="num">${periods[n] != null ? fmtNs(periods[n]) : '—'}</td>
      <td class="num ${a ? cellClass('wns', a.wns) : 'nil'}">${a ? fmtSlack(a.wns) : '—'}</td><td class="num ${a ? cellClass('whs', a.whs) : 'nil'}">${a ? fmtSlack(a.whs) : '—'}</td>
      <td>${clockTrend(builds.map((x) => x.per_clock[n] && x.per_clock[n].wns), labels)}</td>
      ${deltaCell(a && a.wns, b && b.wns, bad)}${deltaCell(a && a.whs, b && b.whs, bad)}
      <td class="num ${a && a.failing ? 'neg' : 'nil'}">${a ? fmtInt(a.failing) : '—'}</td></tr>`;
  }).join('');
  const note = prev ? `Compared with the previous build (${esc(prev.label)}). ${worse.length ? `<b class="neg">${worse.length} clock${worse.length === 1 ? '' : 's'} got worse.</b>` : '<span class="pos">No clock got worse.</span>'}`
    : 'No previous build recorded yet; deltas appear after the next finished build.';
  const cur_note = cur && cur.current ? ` Latest values are from the ${esc(cur.stage || 'latest report')} of this build (in progress).` : '';
  let stages = '';
  if ((ch.stages || []).length >= 2) {
    const names = ch.clocks;
    stages = `<h3>Per stage <small>WNS in this build, by timing report</small></h3><div class="ptable-wrap"><table class="hist stagetbl"><thead><tr><th>Clock</th>${ch.stages.map((s) => `<th title="${esc(s.step)}">${esc(s.label)}</th>`).join('')}</tr></thead><tbody>${names.map((n) => `<tr><td class="mono cn" title="${esc(n)}">${esc(n)}</td>${ch.stages.map((s) => { const v = s.per_clock[n]; return `<td class="num ${v ? cellClass('wns', v.wns) : 'nil'}" title="${v ? `WHS ${fmtSlack(v.whs)} · failing ${v.failing}` : ''}">${v ? fmtSlack(v.wns) : '—'}</td>`; }).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  return `<div class="clk-note">${note}${cur_note}</div>
    <div class="ptable-wrap"><table class="hist clocks"><thead><tr><th>Clock</th><th>Period</th><th>WNS</th><th>WHS</th><th>WNS trend · ${builds.length} build${builds.length === 1 ? '' : 's'}</th><th>Δ WNS</th><th>Δ WHS</th><th title="Failing endpoints (setup + hold)">Fail</th></tr></thead><tbody>${rows}</tbody></table></div>${stages}`;
}
function timingViewHTML(fw) {
  const t = fw.timing;
  const rep = t && t.report ? reportOf(fw, t.report) : null;
  const paths = rep ? pathsHTML(fw, t.report, rep.mtime, 'tv') : '<div class="none">Worst paths appear once Vivado writes a timing summary report with path details, usually after route_design.</div>';
  return `<section class="tv-sec"><h3>Clocks <small>from timing summary reports</small></h3>${clocksHTML(fw)}</section>
    <section class="tv-sec">${rep ? '' : '<h3>Worst paths</h3>'}${paths}</section>`;
}
function renderTimingView(fw) {
  const v = mainEl._r;
  setHTML(v.tv, timingViewHTML(fw));
}
const hasTimingView = (fw) => !!(fw.clock_history || (fw.timing && fw.timing.report));

// ---- router convergence
const trendInfo = {
  converging: ['CONVERGING', 'ok', 'Overlaps are dropping (or already reached 0).'],
  stalled: ['STALLED', 'warn', 'Final overlaps barely decreased over the last iterations. If the router keeps this up, stopping the run early may save time.'],
  diverging: ['DIVERGING', 'err', 'Final overlaps increase from iteration to iteration. This run is unlikely to converge.'],
};
function convOf(n) {
  if (n.convergence && n.convergence.iterations.length) return { conv: n.convergence, from: null };
  const att = [...(n.attempts || [])].reverse().find((a) => a.convergence && a.convergence.iterations && a.convergence.iterations.length);
  return att ? { conv: att.convergence, from: att } : null;
}
const iterShort = (it, i) => { const m = /Global Iteration (\d+)/.exec(it.label || ''); return m ? `#${m[1]}` : /Initial/.test(it.label || '') ? 'init' : String(i); };
function overlapSpark(conv, w = 84, hh = 22) {
  const vals = (conv.iterations || []).flatMap((it) => it.overlaps || []);
  if (vals.length < 2) return '';
  const lg = (v) => Math.log10(Math.max(v, 0.5));
  const lo = lg(0.5), hi = Math.max(lg(Math.max(...vals)), lo + 1);
  const X = (i) => 2 + (i * (w - 4)) / (vals.length - 1);
  const Y = (v) => 2 + (1 - (lg(v) - lo) / (hi - lo)) * (hh - 4);
  const col = conv.trend === 'stalled' ? 'var(--warn)' : conv.trend === 'diverging' ? 'var(--err)' : 'var(--accent)';
  const pts = vals.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
  return `<svg class="cvspark" viewBox="0 0 ${w} ${hh}" width="${w}" height="${hh}"><polyline points="${pts}" style="fill:none;stroke:${col};stroke-width:1.6;stroke-linejoin:round;stroke-linecap:round"/><circle cx="${X(vals.length - 1).toFixed(1)}" cy="${Y(vals[vals.length - 1]).toFixed(1)}" r="2.3" style="fill:${col}"/></svg>`;
}
function convChartSVG(conv, running) {
  const its = conv.iterations;
  const N = its.length;
  const W = 880, H = 310, L = 58, R = 60, T = 14, B = 44;
  const pw = W - L - R, ph = H - T - B, band = pw / N;
  const X = (i) => L + band * (i + 0.5);
  const all = its.flatMap((it) => (it.overlaps && it.overlaps.length ? it.overlaps : [it.final_overlaps || 0]));
  const top = Math.max(1, Math.ceil(Math.log10(Math.max(10, ...all))));
  const floor = -0.55;                                       // log10 position of "0 overlaps"
  const lg = (v) => (v <= 0 ? floor : Math.log10(Math.max(v, 1)));
  const Y = (v) => T + ph * (1 - (lg(v) - floor) / (top - floor));
  let svg = `<svg class="cvsvg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Router overlaps per iteration">`;
  for (let d = 0; d <= top; d++) {
    const y = Y(10 ** d).toFixed(1);
    const lbl = d >= 3 ? `${10 ** (d - 3)}k` : String(10 ** d);
    svg += `<line class="gl" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text class="al" x="${L - 7}" y="${(+y + 4).toFixed(1)}" text-anchor="end">${lbl}</text>`;
  }
  svg += `<line class="gl base" x1="${L}" x2="${W - R}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}"/><text class="al" x="${L - 7}" y="${(Y(0) + 4).toFixed(1)}" text-anchor="end">0</text>`;
  svg += `<text class="at" transform="translate(12 ${T + ph / 2}) rotate(-90)" text-anchor="middle">nodes with overlaps (log)</text>`;
  // timing axis (right)
  const tv = its.flatMap((it) => [it.wns, it.whs]).filter((v) => v != null);
  let yt = null;
  if (tv.length) {
    let lo = Math.min(0, ...tv), hi = Math.max(0, ...tv);
    const pad = (hi - lo || 0.1) * 0.12; lo -= pad; hi += pad;
    yt = (v) => T + ph * (1 - (v - lo) / (hi - lo));
    const step = (() => { const raw = (hi - lo) / 4; const p = 10 ** Math.floor(Math.log10(raw)); return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) || raw; })();
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      if (Math.abs(v) < 1e-9) continue;
      svg += `<text class="al r" x="${W - R + 7}" y="${(yt(v) + 4).toFixed(1)}">${v.toFixed(Math.abs(step) < 0.1 ? 2 : 1)}</text>`;
    }
    svg += `<line class="zl" x1="${L}" x2="${W - R}" y1="${yt(0).toFixed(1)}" y2="${yt(0).toFixed(1)}"/><text class="al r z" x="${W - R + 7}" y="${(yt(0) + 4).toFixed(1)}">0 ns</text>`;
    svg += `<text class="at" transform="translate(${W - 8} ${T + ph / 2}) rotate(90)" text-anchor="middle">slack (ns)</text>`;
  }
  // bars + dots
  const bw = Math.min(46, band * 0.62);
  its.forEach((it, i) => {
    const live = running && i === N - 1;
    svg += `<rect class="cv-hit" data-i="${i}" x="${(L + band * i).toFixed(1)}" y="${T}" width="${band.toFixed(1)}" height="${ph}"/>`;
    const v = it.final_overlaps;
    if (v != null) {
      if (v === 0) svg += `<rect class="bar zero" x="${(X(i) - bw / 2).toFixed(1)}" y="${(Y(0) - 3).toFixed(1)}" width="${bw.toFixed(1)}" height="3" rx="1.5"/>`;
      else svg += `<rect class="bar${live ? ' live' : ''}" x="${(X(i) - bw / 2).toFixed(1)}" y="${Y(v).toFixed(1)}" width="${bw.toFixed(1)}" height="${(Y(0) - Y(v)).toFixed(1)}" rx="2"/>`;
    }
    const vals = it.overlaps || [];
    vals.forEach((o, k) => {
      const x = vals.length === 1 ? X(i) : X(i) - bw / 2 + 3 + ((bw - 6) * k) / (vals.length - 1);
      svg += `<circle class="dot" cx="${x.toFixed(1)}" cy="${Y(o).toFixed(1)}" r="2.1"/>`;
    });
  });
  // timing lines
  if (yt) {
    for (const [key, cls] of [['whs', 'whsl'], ['wns', 'wnsl']]) {
      const pts = its.map((it, i) => (it[key] == null ? null : [X(i), yt(it[key])])).filter(Boolean);
      if (pts.length > 1) svg += `<polyline class="tl ${cls}" points="${pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')}"/>`;
      for (const p of pts) svg += `<circle class="tp ${cls}" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3.2"/>`;
    }
  }
  // x labels
  const every = Math.max(1, Math.ceil(N / 16));
  its.forEach((it, i) => { if (i % every === 0 || i === N - 1) svg += `<text class="ax" x="${X(i).toFixed(1)}" y="${H - B + 16}" text-anchor="middle">${esc(iterShort(it, i))}</text>`; });
  svg += `<text class="at" x="${L + pw / 2}" y="${H - 6}" text-anchor="middle">router iteration${running ? ' (running)' : ''}</text></svg>`;
  return svg;
}
function renderConvergence(pane, n) {
  const hit = convOf(n);
  if (!pane._cv) {
    pane.innerHTML = '<div class="cv-head"></div><div class="cv-box"><div class="cv-svg"></div><div class="cv-tip" hidden></div></div><div class="cv-legend"></div>';
    const cv = pane._cv = { head: $('.cv-head', pane), svg: $('.cv-svg', pane), tip: $('.cv-tip', pane), legend: $('.cv-legend', pane), box: $('.cv-box', pane) };
    cv.box.addEventListener('mousemove', (ev) => {
      const r = ev.target.closest('.cv-hit');
      const conv = pane._conv;
      if (!r || !conv) { cv.tip.hidden = true; return; }
      const it = conv.iterations[+r.dataset.i];
      const f = (v) => (v == null ? '—' : fmtSlack(v));
      const ov = it.overlaps || [];
      const list = ov.length > 8 ? `${ov.slice(0, 4).map(fmtInt).join(' → ')} → … → ${ov.slice(-2).map(fmtInt).join(' → ')}` : ov.map(fmtInt).join(' → ');
      cv.tip.innerHTML = `<b>${esc(it.label)}</b><div>overlaps ${list || '—'} <small>(${ov.length} pass${ov.length === 1 ? '' : 'es'})</small></div><div>WNS <span class="${slackCls(it.wns)}">${f(it.wns)}</span> · TNS ${f(it.tns)}</div><div>WHS <span class="${slackCls(it.whs)}">${f(it.whs)}</span> · THS ${f(it.ths)}</div>`;
      cv.tip.hidden = false;
      const b = cv.box.getBoundingClientRect();
      const x = ev.clientX - b.left, y = ev.clientY - b.top;
      cv.tip.style.left = `${Math.min(Math.max(8, x + 14), b.width - cv.tip.offsetWidth - 8)}px`;
      cv.tip.style.top = `${Math.max(4, y - cv.tip.offsetHeight - 10)}px`;
    });
    cv.box.addEventListener('mouseleave', () => { cv.tip.hidden = true; });
  }
  const cv = pane._cv;
  if (!hit) { setHTML(cv.head, '<div class="none">No router iterations seen yet.</div>'); setHTML(cv.svg, ''); setHTML(cv.legend, ''); pane._conv = null; return; }
  const { conv, from } = hit;
  pane._conv = conv;
  const running = n.status === 'running' && !from;
  const [tl, tc, advice] = trendInfo[conv.trend] || ['COLLECTING', 'nil', 'A trend needs a few completed iterations.'];
  const last = conv.iterations[conv.iterations.length - 1];
  const finals = conv.iterations.map((it) => it.final_overlaps).filter((v) => v != null);
  const wnsIt = [...conv.iterations].reverse().find((it) => it.wns != null);
  setHTML(cv.head, `<div class="cv-top"><span class="trend ${tc}" title="${esc(advice)}">${tl}</span>
      <span class="cv-stat"><b class="num">${conv.iterations.length}</b> iteration${conv.iterations.length === 1 ? '' : 's'}</span>
      <span class="cv-stat">last overlaps <b class="num">${fmtInt(last.final_overlaps)}</b></span>
      ${finals.length > 1 ? `<span class="cv-stat">first <b class="num">${fmtInt(finals[0])}</b></span>` : ''}
      ${wnsIt ? `<span class="cv-stat">WNS <b class="num ${slackCls(wnsIt.wns)}">${fmtSlack(wnsIt.wns)}</b></span>` : ''}
      ${running ? '<span class="cv-live"><i></i>live</span>' : ''}</div>
      <div class="cv-advice ${tc}">${esc(advice)}</div>
      ${from ? `<div class="cv-from">From attempt ${from.n} (${esc(from.summary || from.status)}); the log of the current attempt is not available.</div>` : ''}`);
  setHTML(cv.svg, convChartSVG(conv, running));
  setHTML(cv.legend, '<span><i class="lg bar"></i>final overlaps per iteration (log scale)</span><span><i class="lg dot"></i>overlap passes inside the iteration, in order</span><span><i class="lg wns"></i>WNS</span><span><i class="lg whs"></i>WHS</span>');
}

/* ------------------------------------------------------------------ boot */
parseHash();
if (MOCK) startMock();
else {
  // ?snapshot=1: preload state synchronously so headless screenshots of real data aren't blank
  if (params.get('snapshot') === '1') { try { setState(syncJson('/api/state')); } catch (e) { console.error(e); } }
  connectSSE();
}
window.addEventListener('error', (e) => { document.title = 'ERR ' + e.message; const t = $('#toast'); t.textContent = 'JS error: ' + e.message + ' @' + e.lineno; t.hidden = false; });
window.addEventListener('unhandledrejection', (e) => { const t = $('#toast'); t.textContent = 'JS error: ' + (e.reason && e.reason.message); t.hidden = false; });
