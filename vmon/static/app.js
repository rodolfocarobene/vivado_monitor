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
let ctabs = []; // comparison tabs (shown after the firmware tabs): {cmp, key, fwA, a, fwB, b, label, title, tab, data, error, busy}
let selectedCmp = null; // key of the comparison tab being shown, null = the firmware tab
let firstLoad = true;
const ui = {
  open: new Map(),        // `${fw}|${node}` -> bool (explicit user choice)
  flow: new Map(),        // fw id -> selected flow id
  det: new Map(),         // node key -> fetched details state
  sel: new Map(),         // fw id -> {id, follow}: selected top-level stage in the left column
  view: new Map(),        // fw id -> 'flow' | 'messages'
  mv: new Map(),          // fw id -> messages (triage) view state
  rowSel: new Map(),      // stage key -> id of the outline row the user pinned (absent: the running / failed row is auto-selected)
  insTab: new Map(),      // stage key -> inspector tab, kept while moving between rows
  rsel: new Map(),        // node key -> path of the report shown in the Reports tab
  paths: new Map(),       // `${fw}|${report path}` -> worst-paths table state (filters, expanded rows, fetched data)
};
let hashOpen = new Set();
let hashTab = new Map();
let hashFw = null;
let hashScroll = null, hashShift = null, hashDebug = null;
let hashFx = null; // #fx=cur,a1: pre-open failure log excerpts (screenshots/debug)
let hashSel = null, hashSelPending = false, hashView = null, hashMsg = null, hashExcerpt = false;
let hashRulesDemo = false; // #rulesdemo=1 (mock): open the import preview with a canned file (screenshots)
let hashPclk = false; // #pclk=1: also open the "Clock & required" table of those rows
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
  hashPclk = p.get('pclk') === '1'; hashRulesDemo = p.get('rulesdemo') === '1';
  hashPth = (p.get('pth') || '').split(',').filter(Boolean).map(Number);
  if (p.get('cmp') && typeof addCmpTab === 'function') {
    const [x, y] = p.get('cmp').split(',').map((k) => [k.slice(0, k.indexOf(':')), k.slice(k.indexOf(':') + 1)]);
    if (x && y && x[0] && y[0]) selectCmp(addCmpTab(x[0], x[1], y[0], y[1]).key);
  }
  if (p.get('page') === 'history' && typeof hist !== 'undefined') { hist.on = true; hist.fwName = p.get('hfw'); hist.cmpHash = (p.get('hcmp') || '').split(',').filter(Boolean); if (p.get('hdone')) hist.done = p.get('hdone') === '1'; if (p.get('hmsg')) hist.cmpTab = p.get('hmsg'); }
  if (p.get('theme')) applyTheme(p.get('theme'));
  if (p.get('popover') === 'notif' && typeof openPop === 'function') openPop();
  if (p.get('popover') === 'explore' && typeof openExplore === 'function') openExplore(p.get('path'));
}

const keyOf = (fw, n) => `${fw.id}|${n.id}`;
const curFw = () => state.firmwares.find((f) => f.id === selected);
// Remote firmwares (host set) go stale when their vmon cannot be reached: kept, but not live. Never an error colour.
const remoteOf = (fw) => (fw.host && (state.remotes || []).find((r) => r.name === fw.host)) || null;
const staleRemote = (fw) => { const r = remoteOf(fw); return r && !r.online ? r : null; };
const fwLabel = (fw) => (fw.host ? `${fw.name} · ${fw.host}` : fw.name);
const staleText = (r) => `${r.name} unreachable${r.last_ok ? ` · last update ${fmtClock(r.last_ok)}` : ''}`;
const curView = (fw) => ui.view.get(fw.id) || (hashView === 'messages' || hashView === 'timing' ? hashView : 'flow');

// Forget open-state, pinned row, inspector tab and fetched data of a node and all its descendants,
// so that reopening it looks freshly opened.
function resetNode(fw, n, withSelf = true) {
  walk(withSelf ? [n] : n.children, (x) => {
    const k = keyOf(fw, x);
    ui.open.delete(k); ui.rowSel.delete(k); ui.insTab.delete(k); ui.det.delete(k);
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
      if (['started_at', 'ended_at', 'updated_at', 'generated_at', 't', 'mtime', 'last_ok', 'expected_end', 'low_end', 'high_end'].includes(k) && typeof o[k] === 'number') o[k] += d;
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
  if (fw.host) throw new Error(`message rules are per machine: set them on ${fw.host}`);
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
// Alerts and hints dismissed from the attention list, per build (a new build of the firmware shows its alerts again). The key leaves out
// the message, so an alert whose numbers change (WNS -0.12 -> -0.10) stays dismissed.
const alertKey = (a) => `${a.level}|${a.code || ''}|${a.node_id || ''}`;
const dismissed = (() => { try { return new Map(Object.entries(JSON.parse(lsGet('vmon.alDismissed') || '{}')).map(([k, v]) => [k, new Set(v)])); } catch { return new Map(); } })();
function dismissedOf(fw) {
  const k = `${fw.id}@${fw.started_at ?? ''}`;
  if (!dismissed.has(k)) dismissed.set(k, new Set());
  return dismissed.get(k);
}
function saveDismissed() {
  const keep = [...dismissed].filter(([, set]) => set.size).slice(-50);   // bounded: old builds fall off
  lsSet('vmon.alDismissed', JSON.stringify(Object.fromEntries(keep.map(([k, set]) => [k, [...set]]))));
}
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
      ${a.checkpoint ? `<div class="a-cp mono" title="${esc(a.checkpoint)}">from ${esc(a.checkpoint.split(/[\\/]/).pop())}</div>` : ''}
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
  hit.chain.slice(0, -1).forEach((n) => ui.open.set(keyOf(fw, n), true));
  ui.rowSel.set(keyOf(fw, hit.chain[0]), id);
  render();
  const el = hit.chain.length === 1 ? mainEl.querySelector('.stagedetail > .main > .card') : [...mainEl.querySelectorAll('.orow')].find((e) => e._node && e._node.id === id);
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
  ['unrouted', 'Unrouted nets'], ['util_high', 'High utilization'], ['stalled', 'Stalled build'], ['route_not_converging', 'Router not converging'], ['congestion', 'Congestion'], ['process_gone', 'Vivado process gone'], ['other', 'Other alerts']];
const CODE_ALIAS = { utilization: 'util_high', step_failed: 'step_failed' };
const ALERT_NAME = { timing_fail: 'Timing', critical_warning: 'Critical warnings', error: 'Errors', drc: 'DRC', unrouted: 'Unrouted nets',
  util_high: 'Utilization', utilization: 'Utilization', stalled: 'Stalled', route_not_converging: 'Router', congestion: 'Congestion', process_gone: 'Process gone', step_failed: 'Step failed' };
const alertName = (a) => ALERT_NAME[a.code] || (a.code ? a.code.replace(/_/g, ' ') : a.level);
const NOTIF_DEFAULTS = {
  kinds: { step_done: false, step_failed: true, run_done: true, run_failed: true },
  codes: { timing_fail: true, critical_warning: true, error: true, drc: true, unrouted: true, util_high: true, stalled: true, route_not_converging: true, congestion: true, process_gone: true, other: true },
};
const notif = { cfg: NOTIF_DEFAULTS, log: [], seen: new Set(), open: false, out: null, outErr: false, testing: false };
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
      const entry = { fw: fw.id, fwName: fwLabel(fw), t: ev.t, level: ev.level, title: `vmon · ${fw.name} — ${ev.title}`, evTitle: ev.title, body: eventBody(fw, ev), node_id: ev.node_id, read: false };
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
  hist.on = false; selectCmp(null); selected = e.fw; lsSet('vmon.tab', selected);
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
  const el = h('div', 'tab', '<span class="sdot"></span><span class="t-main"><span class="t-name"></span><span class="t-sub"></span></span><span class="hbadge" hidden></span><span class="abadge" hidden></span><button class="t-x" title="Stop watching (Delete)" aria-hidden="true" tabindex="-1"><svg viewBox="0 0 12 12" width="10" height="10"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button>');
  el.setAttribute('role', 'tab'); el.tabIndex = -1;
  el._r = { dot: $('.sdot', el), name: $('.t-name', el), sub: $('.t-sub', el), ab: $('.abadge', el), host: $('.hbadge', el), x: $('.t-x', el) };
  el.dataset.act = 'tab';
  return el;
}
function updateTab(el, fw) {
  const r = el._r;
  const oc = outcomeOf(fw);
  const stale = staleRemote(fw);
  setAttr(r.dot, 'data-status', stale ? 'stale' : oc.key);
  setAttr(el, 'data-stale', stale ? '1' : '0');
  setText(r.name, fw.name);
  r.host.hidden = !fw.host; setText(r.host, fw.host || '');
  let sub;
  if (stale) sub = `unreachable${stale.last_ok ? ` · ${fmtClock(stale.last_ok)}` : ''}`;
  else if (fw.status === 'running') {
    const cur = fw.current ? esc(fw.current.label) : 'running';
    sub = `${cur} · <span data-start="${fw.started_at ?? ''}">${fmtDur(fw.started_at ? nowS() - fw.started_at : fw.elapsed_s)}</span>${fw.resources ? ` · <span class="t-res" title="Vivado CPU / RSS">${Math.round(fw.resources.cpu_pct)}% · ${fmtMem(fw.resources.rss_mb)}</span>` : ''}`;
  } else sub = `${oc.label} · ${fmtDur(fw.elapsed_s)}`;
  if (fw.attempt && fw.attempt.n > 1) sub = `<span class="t-att">attempt ${fw.attempt.n}</span> · ${sub}`;
  setHTML(r.sub, sub);
  const al = fwAlerts(fw); const lvl = topLevel(al);
  r.ab.hidden = !al.length; setText(r.ab, String(al.length)); setAttr(r.ab, 'data-level', lvl || 'warning');
  const on = fw.id === selected && !shownCmpTab();
  el.classList.toggle('active', on); setAttr(el, 'aria-selected', String(on));
  el.tabIndex = on ? 0 : -1; // roving tabindex: one tab stop for the whole strip
  setAttr(el, 'aria-keyshortcuts', fw.live ? '' : 'Delete');
  r.x.hidden = !!fw.live;
  el.title = `${fw.host ? `${fw.host}: ` : ''}${fw.path || fw.name}`;
}

const CMP_ICON = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 5.5h9M9 3l2.5 2.5L9 8M13.5 10.5h-9M7 8l-2.5 2.5L7 13"/></svg>';
function createCmpTab() {
  const el = h('div', 'tab ctab', `<span class="cmpic">${CMP_ICON}</span><span class="t-main"><span class="t-name"></span><span class="t-sub"></span></span><button class="t-x" title="Close the comparison (Delete)" aria-hidden="true" tabindex="-1"><svg viewBox="0 0 12 12" width="10" height="10"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button>`);
  el.setAttribute('role', 'tab'); el.tabIndex = -1;
  el._r = { name: $('.t-name', el), sub: $('.t-sub', el), x: $('.t-x', el) };
  el.dataset.act = 'tab';
  return el;
}
function updateCmpTab(el, t) {
  const on = t.key === selectedCmp && !hist.on;
  setText(el._r.name, t.label); setText(el._r.sub, cmpHasLive(t) ? 'comparison · live' : 'comparison');
  if (on && !el.classList.contains('active')) el.scrollIntoView({ block: 'nearest', inline: 'nearest' }); // it was just opened or picked
  el.classList.toggle('active', on); setAttr(el, 'aria-selected', String(on));
  el.tabIndex = on ? 0 : -1;
  setAttr(el, 'aria-keyshortcuts', 'Delete');
  el.title = t.title;
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

let head = null;
let infoOpen = lsGet('vmon.infoOpen') === '1'; // closed by default: keeps the stage flow above the fold
function buildView() {
  mainEl.innerHTML = '';
  head = h('section', 'fw-head hero', `
    <div class="hero-top">
      <div class="hero-id">
        <div class="fw-title"><h1></h1><span class="pill"></span>
          <div class="seg viewseg" role="group" aria-label="View"><button data-act="view" data-view="flow" title="Flow (f)">Flow</button><button data-act="view" data-view="messages" title="Messages (m)">Messages</button><button data-act="view" data-view="timing" title="Timing (t)">Timing</button></div>
        </div>
        <div class="fw-path mono"></div>
        <div class="fw-host" hidden></div>
        <div class="fw-attempt" hidden></div>
      </div>
      <div class="hero-actions">
        <button type="button" class="hx-chip fw-cmpbtn" data-act="fw-compare" hidden>Compare</button>
        <button type="button" class="hx-chip hinfo-btn" data-act="info-toggle" aria-expanded="false" title="Show or hide build info">Build info${CHEV}</button>
        <div class="hmenuwrap" hidden>
          <button type="button" class="hx-chip hmore" data-act="hero-menu" aria-haspopup="menu" aria-expanded="false" aria-label="More actions" title="Export this build"><svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"><circle cx="3.5" cy="8" r="1.4"/><circle cx="8" cy="8" r="1.4"/><circle cx="12.5" cy="8" r="1.4"/></svg></button>
          <div class="hmenu" role="menu" hidden><button type="button" role="menuitem" data-act="hexp" data-format="md" title="Download a Markdown summary of this build">Export summary (Markdown)</button><a role="menuitem" data-act="hexp" data-format="html" target="_blank" rel="noopener" title="Open a printable HTML summary of this build in a new tab">Open printable HTML</a></div>
        </div>
      </div>
    </div>
    <div class="verdict" data-tone="ok"><i class="vdot"></i><span class="vtext"></span></div>
    <div class="strip"></div>
    <div class="tiles"></div>
    <div class="attn"></div>
    <div class="fwinfo" hidden><div class="info-grid"></div></div>`);
  head._r = { name: $('h1', head), pill: $('.pill', head), path: $('.fw-path', head), host: $('.fw-host', head), att: $('.fw-attempt', head), verdict: $('.verdict', head), vtext: $('.vtext', head), strip: $('.strip', head), tiles: $('.tiles', head), attn: $('.attn', head), info: $('.fwinfo', head), infoGrid: $('.info-grid', head), infoBtn: $('.hinfo-btn', head), menuWrap: $('.hmenuwrap', head), menu: $('.hmenu', head), menuBtn: $('.hmore', head), seg: $('.viewseg', head), cmp: $('.fw-cmpbtn', head) };
  // The stage list is a permanent left rail (sticky beside everything else), so the right column never repeats it.
  const rail = h('aside', 'stagecol', `<div class="sl-head"><span>Stages</span></div><div class="segwrap"></div><div class="stagelist"></div>`);
  setAttr(rail, 'aria-label', 'Stages');
  const split = h('div', 'split', '<section class="detail"></section>');
  const mv = h('section', 'msgview', `
    <div class="mv-bar"><div class="mv-chips"></div><input class="mv-q" type="search" placeholder="Search id or text…" spellcheck="false" autocomplete="off">
      <span class="mv-rules"><button class="mv-btn" data-act="mv-export" title="Download your ★ and mute rules as a file to share">Export rules</button><button class="mv-btn" data-act="mv-import" title="Load a rules file from a teammate or another machine, with a preview first">Import rules…</button><input class="mv-file" type="file" accept=".json,application/json" hidden aria-label="Message rules file"></span></div>
    <div class="mv-hint" hidden></div>
    <div class="mv-list"></div>`);
  mv.hidden = true;
  const tv = h('section', 'tview');
  tv.hidden = true;
  mainEl.classList.add('railed');
  mainEl.append(rail, head, split, mv, tv);
  mainEl._r = { rail, seg: $('.segwrap', rail), split, stages: $('.stagelist', rail), detail: $('.detail', split), followBtn: $('#follow-btn'), mv, mvChips: $('.mv-chips', mv), mvQ: $('.mv-q', mv), mvHint: $('.mv-hint', mv), mvList: $('.mv-list', mv), tv, fwId: null, selId: null, selFlow: null, detEl: null };
}

function etaParts(fw) {
  const e = fw.eta;
  if (fw.status !== 'running' || !e || e.expected_end == null) return null;
  const rem = e.expected_end - nowS();
  const hist = e.method === 'history';
  const band = e.low_end != null && e.high_end != null ? `${fmtClock(e.low_end)}–${fmtClock(e.high_end)}` : '';
  const src = hist ? `${e.builds} build${e.builds === 1 ? '' : 's'}` : e.method === 'catalog weights' ? 'rough estimate' : e.method || '';
  const how = [src, e.confidence === 'low' ? 'low confidence' : ''].filter(Boolean).join(' · ');
  const tip = (hist ? `Median of per-phase and per-step durations of ${e.builds} previous build${e.builds === 1 ? '' : 's'}; ` : 'No usable build history: catalog weights scaled by progress; ')
    + (band ? (e.builds >= 3 ? 'the range is the 10th to 90th percentile of those builds' : 'the range is widened around the few builds seen') : '')
    + `. Confidence: ${e.confidence || 'low'}.`;
  return { clock: fmtClock(e.expected_end), end: e.expected_end, band, how, tip, inTxt: rem > 30 ? `in ${fmtDur(rem)}` : 'any moment now' };
}
const endedAt = (fw) => (fw.started_at && fw.elapsed_s != null ? fw.started_at + fw.elapsed_s : fw.updated_at);

function infoHTML(fw) {
  const i = { ...(fw.info || {}) };
  if (!i.vivado_version) i.vivado_version = fw.vivado_version;
  const cell = (k, v, cls = '') => `<div class="ic ${cls}"><div class="k">${esc(k)}</div><div class="v" title="${esc(v)}">${esc(v)}</div></div>`;
  const has = (v) => v != null && v !== '';
  const out = [['Part', i.part], ['Board', i.board], ['Top', i.top], ['Vivado', i.catalog_version ? `${i.vivado_version} (catalog ${i.catalog_version})` : i.vivado_version], ['Host', i.host], ['Synth strategy', i.strategy_synth],
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
/* ------------------------------------------------------------------ hero band: verdict, build strip, metric tiles, one attention list */
const TOP_ISSUES_SHOWN = 3;
const ATTN_SHOWN = 3;
const SEV_WORD = { error: 'ERROR', critical: 'CRITICAL', warning: 'WARNING', info: 'INFO' };
const HINT_WORD = { warning: 'CHECK', info: 'TIP' };
const shortStage = (n) => n.id.split('/').pop().replace(/_design$/, '').replace(/^write_/, '');
const STAGE_VERB = { synth: 'Synthesizing', init: 'Initializing', opt: 'Optimizing', place: 'Placing', phys_opt: 'Physically optimizing', route: 'Routing', bitstream: 'Writing bitstream' };
const STRIP_GUESS_S = 60;   // width of a pending stage with no expected_s and nothing to compare with
const fwFinished = (fw) => ['done', 'failed', 'stopped'].includes(fw.status);
let attnAll = false, heroMenu = false;
const fixOpen = new Set();   // attention rows whose Fix is unfolded, kept across re-renders

// One segment per top-level stage, sized by real time: what a stage took, or is taking, else what history says it
// should take (expected_s). A running stage is projected to max(elapsed, expected).
function stripSegs(flow) {
  const t = nowS();
  const segs = flow.stages.map((n) => {
    const o = { n, s: shortStage(n), dur: null, el: null, est: false, frac: null };
    const started = n.started_at && n.status !== 'pending';
    if (n.status === 'running' && started) {
      o.el = Math.max(0, t - n.started_at);
      o.dur = Math.max(o.el, n.expected_s || 0);
      const p = n.progress && n.progress.total ? n.progress.done / n.progress.total : null;
      if (!n.expected_s && p > 0.05) o.dur = Math.max(o.el, o.el / p);
      o.frac = Math.min(0.99, o.el / (o.dur || 1));
    } else if (n.elapsed_s != null && n.status !== 'pending') o.dur = n.elapsed_s;
    else { o.est = true; o.dur = n.expected_s; }
    return o;
  });
  const known = segs.filter((o) => o.dur != null).map((o) => o.dur).sort((a, b) => a - b);
  const guess = known.length ? Math.max(5, known[Math.floor(known.length / 2)] * 0.5) : STRIP_GUESS_S;
  for (const o of segs) { if (o.dur == null) { o.dur = guess; o.guess = true; } }
  return segs;
}

function stripHTML(fw, flow) {
  if (!flow || !flow.stages.length) return '';
  const segs = stripSegs(flow);
  const total = segs.reduce((a, o) => a + o.dur, 0) || 1;
  const sel = mainEl._r && mainEl._r.selId;
  const ep = etaParts(fw), pe = fw.progress_estimate;
  const body = segs.map((o) => {
    const n = o.n, lv = nodeLevel(n), running = n.status === 'running';
    const pct = running && o.frac != null ? Math.round(o.frac * 100) : null;
    const fill = running ? `<i class="pfill" style="width:${pct != null ? pct : 40}%"></i>${pct != null ? `<i class="pnow" style="left:${pct}%"><b>now</b></i>` : ''}` : '';
    const time = running ? `${pct != null ? pct + '% · ' : ''}${fmtDur(o.el)}` : o.est ? `${o.guess ? '' : '~'}${fmtDur(o.dur)}` : fmtDur(o.dur);
    const why = o.est ? (o.guess ? ' · no history, rough guess' : ' · expected duration') : '';
    return `<button type="button" class="pseg${n.id === sel ? ' sel' : ''}" data-act="hero-stage" data-id="${esc(n.id)}" data-status="${esc(n.status)}" style="flex-grow:${Math.max(o.dur, total * 0.06).toFixed(1)}" title="${esc(n.label)} · ${esc(statusInfo(n.status).label)}${why}" aria-label="${esc(n.label)}, ${esc(statusInfo(n.status).label)}">`
      + `<span class="pbar${o.est ? ' est' : ''}">${fill}</span>`
      + `<span class="pcap"><b>${lv ? `<em class="pwarn" data-lv="${lv}"></em>` : ''}<span class="pname">${esc(o.s)}</span></b><small class="num${o.est ? ' est' : ''}">${time}</small></span></button>`;
  }).join('');
  const endTxt = ep ? `<span class="pend" title="${esc(ep.tip)}"><small>ETA</small><b class="num">~${ep.clock}</b></span>` : fwFinished(fw) && endedAt(fw) ? `<span class="pend"><small>ended</small><b class="num">${fmtClock(endedAt(fw))}</b></span>` : '';
  const head = `<div class="ph"><span class="pt">Build progress</span>${pe != null ? `<span class="pp num">${Math.round(pe * 100)}% of the flow</span>` : ''}<span class="pk"><i class="d done"></i>done<i class="d run"></i>running<i class="d pend"></i>expected</span></div>`;
  return `${head}<div class="prow"><div class="pseglist">${body}</div>${endTxt}</div>`;
}

// One sentence: is it OK, and when is it done. Timing wording follows the severity rule (red only for final failures)
// and never promises that later steps may fix a build that has no later steps.
function verdictOf(fw, flow) {
  const t = fw.timing, tl = fwTimingLevel(fw), fin = fwFinished(fw);
  const parts = []; let tone = 'ok';
  const stages = flow ? flow.stages : [];
  const run = stages.find((n) => n.status === 'running');
  const bad = stages.find((n) => n.status === 'failed');
  const ep = etaParts(fw);
  if (fw.status === 'running') {
    parts.push(`<b>${esc(run ? STAGE_VERB[shortStage(run)] || run.label : 'Running')}</b>`);
    parts.push(ep ? `expected to finish <b class="num">~${ep.clock}</b> <span class="vd-dim">(<span data-end="${ep.end}">${ep.inTxt}</span>)</span>` : '<span class="vd-dim">no finish estimate yet</span>');
    tone = 'run';
  } else if (fw.status === 'done') {
    parts.push(`<b>Finished</b>${endedAt(fw) ? ` at <span class="num">${fmtClock(endedAt(fw))}</span>` : ''}${fw.elapsed_s != null ? ` in <span class="num">${fmtDur(fw.elapsed_s)}</span>` : ''}`);
  } else if (fw.status === 'failed') {
    parts.push(`<b>Failed</b>${bad ? ` in ${esc(bad.label)}` : ''}${fw.elapsed_s != null ? ` <span class="vd-dim">after ${fmtDur(fw.elapsed_s)}</span>` : ''}`); tone = 'err';
  } else if (fw.status === 'stopped') {
    parts.push(`<b>Stopped</b>${fw.elapsed_s != null ? ` <span class="vd-dim">after ${fmtDur(fw.elapsed_s)}</span>` : ''}`); tone = 'warn';
  } else if (fw.status === 'queued') parts.push('<b>Queued</b> <span class="vd-dim">waiting to start</span>');
  else if (fw.status === 'idle') parts.push('<b>Idle</b> <span class="vd-dim">no build running</span>');
  else parts.push(`<b>${esc(statusInfo(fw.status).label)}</b>`);
  if (t && t.wns != null) {
    const w = fmtNs(Math.abs(t.wns)), hls = fw.kind === 'hls';
    if (tl === 'fail') { parts.push(`<span class="vd-bad">timing not met, WNS ${fmtNs(t.wns)} ns</span>`); tone = 'err'; }
    else if (tl === 'warn') {
      const txt = hls ? `estimated timing fails by ${w} ns` : fin ? `timing failing by ${w} ns (last estimate, no final report)` : `timing failing by ${w} ns (estimate)`;
      parts.push(`<span class="vd-warn">${txt}</span>`);
      if (tone === 'ok') tone = 'warn'; else if (tone === 'run') tone = 'runwarn';
    } else if (tl === 'halted') parts.push(`<span class="vd-dim">last timing estimate ${fmtNs(t.wns)} ns, no final timing</span>`);
    else if (tl === 'ok') parts.push('<span class="vd-ok">timing met</span>');
    else if (tl === 'track') parts.push(`<span class="vd-ok">${fin ? 'timing met (estimate)' : 'timing on track'}</span>`);
  } else if (fw.status === 'running') parts.push('<span class="vd-dim">no timing data yet</span>');
  if (fw.counts && fw.counts.error) { parts.push(`<span class="vd-bad">${fmtNum(fw.counts.error)} error${fw.counts.error === 1 ? '' : 's'}</span>`); tone = 'err'; }
  if (fw.kind === 'log') parts.push('<span class="vd-dim">log only, steps inferred</span>');
  return { tone, html: parts.join('<i class="vsep">·</i>') };
}

// Red is kept for a device that is actually over capacity; high-but-fitting utilization is a warning, not a failure.
const utilClass = (pct) => (pct == null ? '' : pct > 100 ? 'over' : pct >= 90 ? 'crit' : pct >= 80 ? 'warn' : '');
const UTIL_BADGE = { over: ['OVER CAPACITY', 'notmet'], crit: ['VERY HIGH', 'critb'], warn: ['HIGH', 'warnb'] };
function tilesHTML(fw) {
  const t = fw.timing, tl = fwTimingLevel(fw);
  const out = [];
  const hn = latestHistory(fw);
  const sp = hn && hn.timing.history.length > 1 ? spark(hn.timing.history.map((x) => x.wns), 64, 26, { warn: tl !== 'fail' }) : '';
  const wcls = t && t.wns != null ? (t.wns < 0 ? (tl === 'fail' ? 'neg' : tl === 'halted' ? 'dim' : 'soft') : 'pos') : 'nil';
  const badge = !t ? '' : t.final ? '<span class="tbadge final">FINAL</span>' : tl === 'halted' ? '<span class="tbadge">INCOMPLETE</span>' : '<span class="tbadge est">ESTIMATE</span>';
  const stale = (k) => (carriedOf(t, k) ? ' <i class="ctag">stale</i>' : '');
  out.push(`<button type="button" class="tile t-timing" data-tl="${tl}" data-act="view" data-view="timing" title="${esc(t ? `${timingBadge(t, tl)[0]} · ${t.stage || t.label || ''}${t.final ? ' · final' : ' · not final'}. ` : '')}Open the timing view">`
    + `<div class="tk"><span>WNS</span>${badge}</div>`
    + `<div class="tv"><b class="num ${wcls}">${t ? fmtSigned(t.wns, 3) : '—'}</b><small>ns</small>${sp ? `<span class="tspark" title="WNS history · ${esc(hn.label)}">${sp}</span>` : ''}</div>`
    + `<div class="ts num">${t ? `<span>TNS ${fmtNs(t.tns)}</span><span>WHS ${fmtSigned(t.whs, 3)}${stale('whs')}</span>` : 'No timing data yet'}</div></button>`);
  const rows = ((fw.utilization && fw.utilization.rows) || []).map((r) => ({ ...r, p: r.pct ?? (r.available ? (r.used / r.available) * 100 : 0) })).sort((a, b) => b.p - a.p);
  if (rows.length) {
    const w = rows[0], wc = utilClass(w.p), ub = UTIL_BADGE[wc];
    out.push(`<div class="tile t-util" data-lv="${wc || 'ok'}"><div class="tk"><span>Utilization</span>${ub ? `<span class="tbadge ${ub[1]}">${ub[0]}</span>` : ''}</div>`
      + `<div class="tv"><b class="num ${wc}">${w.p.toFixed(w.p < 10 ? 1 : 0)}%</b><small>${esc(w.name)}</small></div>`
      + `<div class="mbars">${rows.slice(0, 3).map((r) => `<div class="mb" title="${esc(r.name)}: ${fmtVal(r.used)} of ${fmtVal(r.available)}"><span>${esc(r.name)}</span><div class="ubar ${utilClass(r.p)}"><i style="width:${Math.min(100, r.p)}%"></i></div><span class="num">${r.p.toFixed(0)}%</span></div>`).join('')}</div></div>`);
  } else out.push(`<div class="tile t-util"><div class="tk"><span>Utilization</span></div><div class="tv"><b class="num nil">—</b></div><div class="ts">${fw.kind === 'hls' ? 'After C synthesis' : 'Shown after placement'}</div></div>`);
  const running = fw.status === 'running' && fw.started_at && !staleRemote(fw);
  const ep = etaParts(fw), pe = fw.progress_estimate;
  out.push(`<div class="tile t-time"><div class="tk"><span>Elapsed</span>${pe != null ? `<span class="tbadge" title="Estimated share of the whole flow completed, from step weights">${['failed', 'stopped'].includes(fw.status) ? 'reached ' : ''}~${Math.round(pe * 100)}%</span>` : ''}</div>`
    + `<div class="tv"><b class="num" ${running ? `data-start="${fw.started_at}"` : ''}>${fmtDur(running ? nowS() - fw.started_at : fw.elapsed_s)}</b></div>`
    + (pe != null ? `<div class="eprog" data-status="${esc(fw.status)}"><i style="width:${Math.round(pe * 100)}%"></i></div>` : '')
    + `<div class="ts num">${fw.started_at ? `<span>started ${fmtClock(fw.started_at)}</span>` : ''}${ep ? `<span data-end="${ep.end}">${ep.inTxt}</span>` : ''}</div></div>`);
  const c = fw.counts || {};
  out.push(`<button type="button" class="tile t-msgs" data-act="view" data-view="messages" title="Open the messages view"><div class="tk"><span>Messages</span></div>`
    + `<div class="mcs">${SEVERITIES.map((s) => `<span class="mc ${(c[s.key] || 0) ? s.cls : 'zero'}" title="${s.label}"><b class="num">${fmtNum(c[s.key] || 0)}</b><small>${s.short}</small></span>`).join('')}</div>`
    + `<div class="stack">${SEVERITIES.map((s) => (c[s.key] ? `<i style="flex-grow:${Math.sqrt(c[s.key]).toFixed(2)};background:var(${s.var})"></i>` : '')).join('')}</div>`
    + `<div class="ts">${fw.resources ? `<span title="Vivado process CPU (100% = one core) and resident memory">Vivado ${Math.round(fw.resources.cpu_pct)}% · ${fmtMem(fw.resources.rss_mb)}</span>` : '<span>by severity</span>'}</div></button>`);
  return out.join('');
}

// Needs attention: alerts, top message groups and suggested actions in one list, de-duplicated. A hint that explains an
// alert (same step, id starts with the alert code) becomes that row's Fix; a message group already quoted by an alert's
// text is folded into that row.
const SEV_RANK = { error: 0, critical: 1, warning: 2, tip: 3 };
function attentionItems(fw) {
  const items = [];
  const hints = fw.hints || [];
  const msgs = (fw.top_messages || []).slice(0, TOP_ISSUES_SHOWN);
  const usedH = new Set(), usedM = new Set();
  const stepOf = (nid) => { const pn = nid && findPath(fw, nid); return pn ? pn.chain[pn.chain.length - 1].label : ''; };
  for (const a of fwAlerts(fw)) {
    const hint = hints.find((x) => !usedH.has(x.id) && a.code && x.node_id === a.node_id && x.id.startsWith(a.code));
    if (hint) usedH.add(hint.id);
    const g = msgs.find((m) => a.message.includes(m.id));
    if (g) usedM.add(g.id);
    items.push({ key: alertKey(a), sev: a.level === 'error' ? 'error' : a.code === 'critical_warning' ? 'critical' : 'warning', title: alertName(a), desc: a.message, step: stepOf(a.node_id), node: a.node_id, hint, msg: g });
  }
  for (const m of msgs) {
    if (usedM.has(m.id)) continue;
    const more = (m.nodes || []).length > 1 ? ` +${m.nodes.length - 1}` : '';
    items.push({ key: `msg|${m.id}`, sev: m.severity === 'error' ? 'error' : m.severity === 'critical' ? 'critical' : 'warning', title: m.id, desc: m.text, step: m.nodes && m.nodes[0] ? m.nodes[0].label + more : '', msgId: m.id, count: m.count, isNew: m.new, mono: true });
  }
  for (const x of hints) if (!usedH.has(x.id)) items.push({ key: `hint|${x.id}`, sev: x.severity === 'warning' ? 'warning' : 'tip', title: x.title, desc: x.text, step: stepOf(x.node_id), node: x.node_id, hint: x });
  return items.map((it, i) => ({ ...it, i })).sort((a, b) => SEV_RANK[a.sev] - SEV_RANK[b.sev] || a.i - b.i);
}
function fixBodyHTML(hn) {
  const acts = (hn.actions || []).map((a) => `<li class="hact"><span class="hat">${esc(a.text)}</span>${a.doc_url ? docBtn(a.doc_url, `${hn.title} documentation`) : ''}${a.command ? `<div class="hcmd"><code class="mono">${esc(a.command)}</code>${copyBtn(a.command, 'command')}</div>` : ''}</li>`).join('');
  return `<div class="afix-body"><div class="hint-x">${esc(hn.text)}</div>${hn.evidence ? `<div class="hint-ev mono">${esc(hn.evidence)}</div>` : ''}${acts ? `<ul class="hacts">${acts}</ul>` : ''}</div>`;
}
const X_SVG = '<svg viewBox="0 0 12 12" width="10" height="10"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
function attentionHTML(fw) {
  const all = attentionItems(fw);
  if (!all.length) return '';
  const gone = dismissedOf(fw);
  const shown = all.filter((x) => !gone.has(x.key));
  const nGone = all.length - shown.length;
  const chip = (sev, one, many) => { const n = all.filter((x) => x.sev === sev).length; return n ? `<span class="asum" data-sev="${sev}">${n} ${n === 1 ? one : many}</span>` : ''; };
  const head = `<div class="attn-h"><span class="attn-t">Needs attention</span><span class="attn-n num" title="Dismissed items stay counted">${all.length}</span>${chip('error', 'error', 'errors')}${chip('critical', 'critical', 'critical')}${chip('warning', 'warning', 'warnings')}${chip('tip', 'tip', 'tips')}`
    + `${nGone ? `<button class="al-restore" data-act="al-restore" title="Show the dismissed items again">${nGone} dismissed · show</button>` : ''}<button class="linkbtn attn-all" data-act="view" data-view="messages">all messages →</button></div>`;
  if (!shown.length) return head;
  const vis = attnAll ? shown : shown.slice(0, ATTN_SHOWN);
  const rows = vis.map((x) => {
    const open = fixOpen.has(x.key);
    const act = x.msgId ? `data-act="topissue" data-id="${esc(x.msgId)}"` : `data-act="goto" data-node="${esc(x.node || '')}"`;
    const idChip = x.msg ? `<span class="aid mono">${esc(x.msg.id)} ×${fmtNum(x.msg.count)}</span>` : '';
    return `<div class="arow" data-sev="${x.sev}" data-key="${esc(x.key)}" ${act}>`
      + `<span class="asev">${SEV_WORD[x.sev] || 'TIP'}</span>`
      + `<div class="atxt"><b class="atitle${x.mono ? ' mono' : ''}">${esc(x.title)}</b>${x.count ? `<span class="acount mono">×${fmtNum(x.count)}</span>` : ''}${x.isNew ? '<span class="ntag">NEW</span>' : ''}${idChip}<span class="adesc" title="${esc(x.desc)}">${esc(x.desc)}</span></div>`
      + `${x.step ? `<span class="astep" title="Step this belongs to">${esc(x.step)}</span>` : ''}`
      + `${x.hint ? `<button type="button" class="afix" data-act="fix-toggle" data-key="${esc(x.key)}" aria-expanded="${open}" title="Suggested actions for this">Fix${CHEV}</button>` : '<span class="afix-ph"></span>'}`
      + `<button type="button" class="al-x" data-act="al-dismiss" data-key="${esc(x.key)}" title="Dismiss (it stays counted)" aria-label="Dismiss">${X_SVG}</button>`
      + `${x.hint && open ? fixBodyHTML(x.hint) : ''}</div>`;
  }).join('');
  const more = shown.length > ATTN_SHOWN ? `<button type="button" class="linkbtn attn-more" data-act="attn-more" aria-expanded="${attnAll}">${attnAll ? 'Show fewer' : `Show ${shown.length - ATTN_SHOWN} more`}</button>` : '';
  return `${head}<div class="alist">${rows}</div>${more}`;
}

// The stage detail does not repeat the fix: it points at the hero row, which owns the explanation and the commands.
const hintRowKey = (fw, hintId) => { const it = attentionItems(fw).find((x) => x.hint && x.hint.id === hintId); return it ? it.key : null; };
function stageHintsHTML(fw, n) {
  const hs = (fw.hints || []).filter((x) => x.node_id === n.id);
  if (!hs.length) return '';
  return `<div class="hintlinks">${hs.map((x) => { const k = (x.actions || []).length; return `<button type="button" class="hlink" data-act="hint-goto" data-hint="${esc(x.id)}" data-sev="${esc(x.severity)}"><span class="hpill">${HINT_WORD[x.severity] || 'TIP'}</span><b class="hint-t">${esc(x.title)}</b><span class="hlk-n">${k} suggested action${k === 1 ? '' : 's'} → Needs attention</span></button>`; }).join('')}</div>`;
}
function hintGoto(fw, hintId) {
  const key = hintRowKey(fw, hintId);
  if (!key) return;
  dismissedOf(fw).delete(key); saveDismissed();
  fixOpen.add(key); attnAll = true;
  render();
  const row = [...mainEl.querySelectorAll('.arow')].find((e) => e.dataset.key === key);
  if (!row) return;
  row.classList.add('flash'); setTimeout(() => row.classList.remove('flash'), 2200);
  window.scrollTo({ top: Math.max(0, row.getBoundingClientRect().top + window.scrollY - topbarEl.offsetHeight - 24), behavior: 'smooth' });
}

function renderHeader(fw) {
  const r = head._r;
  const flow = fw.flows.find((f) => f.id === ui.flow.get(fw.id)) || fw.flows[0];
  setText(r.name, fw.name);
  const oc = outcomeOf(fw);
  const stale = staleRemote(fw);
  setAttr(r.pill, 'data-status', stale ? 'stale' : oc.key);
  setText(r.pill, oc.pill + (fw.kind === 'log' ? ' · log' : fw.kind === 'hls' ? ' · HLS' : '') + (stale ? ' · stale' : ''));
  setText(r.path, fw.path || '');
  r.host.hidden = !fw.host; setAttr(r.host, 'data-stale', stale ? '1' : '0');
  setText(r.host, fw.host ? (stale ? staleText(stale) : `on ${fw.host}`) : '');
  const at = fw.attempt && fw.attempt.n > 1 ? fw.attempt : null;
  r.att.hidden = !at;
  setHTML(r.att, at ? attemptLineHTML(at) : '');
  const vd = verdictOf(fw, flow);
  setAttr(r.verdict, 'data-tone', vd.tone);
  setHTML(r.vtext, vd.html);
  setHTML(r.strip, stripHTML(fw, flow));
  setHTML(r.tiles, tilesHTML(fw));
  setHTML(r.attn, attentionHTML(fw));
  r.attn.hidden = !r.attn.innerHTML;
  const ih = infoHTML(fw);
  r.infoBtn.hidden = !ih;
  r.info.hidden = !ih || !infoOpen; setHTML(r.infoGrid, ih);
  r.infoBtn.classList.toggle('on', infoOpen); setAttr(r.infoBtn, 'aria-expanded', String(infoOpen));
  r.cmp.hidden = fw.started_at == null;
  setAttr(r.cmp, 'title', HX_FINISHED.has(fw.status) ? 'Compare the latest recorded build of this firmware with another build' : 'Compare this run as it is now (provisional) with a recorded build');
  const canExp = fwFinished(fw) && fw.started_at != null;
  r.menuWrap.hidden = !canExp;
  if (canExp) for (const c of r.menu.children) { const build = String(Math.floor(fw.started_at)); c.dataset.fw = fw.id; c.dataset.build = build; if (c.tagName === 'A') c.href = summaryUrl(fw.id, build, 'html', false); }
  r.menu.hidden = !(heroMenu && canExp); setAttr(r.menuBtn, 'aria-expanded', String(heroMenu && canExp));
  setAttr(head, 'data-health', fw.health || topLevel(fwAlerts(fw)) || 'ok');
  const view = curView(fw);
  for (const b of r.seg.children) { b.classList.toggle('on', b.dataset.view === view); setAttr(b, 'aria-pressed', String(b.dataset.view === view)); if (b.dataset.view === 'timing') b.hidden = !hasTimingView(fw) && view !== 'timing'; }
}
document.addEventListener('click', (e) => { if (heroMenu && !e.target.closest('.hmore') && head && curFw()) { heroMenu = false; renderHeader(curFw()); } });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && heroMenu && head && curFw()) { heroMenu = false; renderHeader(curFw()); head._r.menuBtn.focus(); } });

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
  setHTML(r.chip, chipHTML(n.timing) + congChip(n.congestion));
  setHTML(r.doc, docBtn(n.doc_url, `${n.label} documentation`));
  const running = n.status === 'running' && n.started_at;
  const el_s = running ? nowS() - n.started_at : n.elapsed_s;
  const mem = n.peak_mem_mb != null ? `<span class="mem" title="Peak memory">${fmtMem(n.peak_mem_mb)}</span>` : '';
  const dur = el_s != null ? `<span ${running ? `data-start="${n.started_at}"` : ''}>${fmtDur(el_s)}</span>` : '';
  setHTML(r.meta, `${mem}${dur}`);
  const p = n.progress;
  r.prog.hidden = !(p && p.total);
  if (p && p.total) { const pc = Math.min(100, Math.round((p.done / p.total) * 100)); r.bar.style.width = `${pc}%`; r.prog.title = `${p.done}/${p.total}`; }
  if (el._detail) renderStageBody(el, n, fw);
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
  setHTML(r.chip, chipHTML(n.timing) + congChip(n.congestion));
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
  const hn = h('div', 'dhints');
  for (const x of [fb, at, hn, al]) $('.main', el).insertBefore(x, $('.body', el));
  el._r.alerts = al; el._r.dfail = fb; el._r.dattempts = at; el._r.dhints = hn;
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
  const hh = stageHintsHTML(fw, n);
  if (el._r.dhints._h !== hh) setHTML(el._r.dhints, hh);
  setHTML(el._r.alerts, ''); // the hero's attention list already lists these; the stage card keeps its alert icon
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

// Narrow windows have no room for rail + detail side by side: the stage list becomes the tree, with the selected
// stage's detail (steps, tabs, messages) hosted directly under its own card.
const narrowMQ = window.matchMedia('(max-width: 1000px)');
function placeDetail(v) {
  const host = narrowMQ.matches ? v.stages.querySelector(':scope > .stg.sel > .main') : v.split;
  if (host && v.detail.parentElement !== host) host.appendChild(v.detail);
}
narrowMQ.addEventListener('change', () => { if (mainEl._r) render(); });

function renderStageList(fw, flow) {
  const v = mainEl._r;
  const stages = flow.stages;
  let sel = ui.sel.get(fw.id);
  if (!sel) { sel = { id: null, follow: true }; ui.sel.set(fw.id, sel); }
  if (hashSelPending && stages.some((s) => s.id === hashSel)) { sel.id = hashSel; sel.follow = false; hashSelPending = false; }
  const selStage = (!sel.follow && stages.find((s) => s.id === sel.id)) || autoStage(stages);
  v.followBtn.hidden = false;
  v.followBtn.classList.toggle('on', sel.follow);
  setAttr(v.followBtn, 'aria-pressed', String(sel.follow));
  setText(v.followBtn, 'follow live'); // same text in both states: the switch shows the state, the button never changes width
  setAttr(v.followBtn, 'title', sel.follow ? (fw.status === 'running' ? 'Following the running stage — click to stop and stay on this stage' : 'Nothing running — showing the latest stage; it will follow when a step runs. Click to pin this stage') : 'Click to jump to the running stage and keep following it');
  patchList(v.stages, stages, (n) => n.id, createStage, (e, n) => updateStage(e, n, fw, n.id === selStage.id));
  return selStage;
}

function renderFlowView(fw, flow) {
  const v = mainEl._r;
  const stages = flow.stages;
  const selStage = renderStageList(fw, flow); // also creates the selection state on first render
  if (v.selId !== selStage.id || v.selFlow !== flow.id || !v.detEl) {
    const prev = v.selId && v.selFlow === flow.id && stages.find((s) => s.id === v.selId);
    if (prev) resetNode(fw, prev);
    v.selId = selStage.id; v.selFlow = flow.id;
    v.detail.innerHTML = '';
    v.detEl = createDetail();
    v.detail.appendChild(v.detEl);
  }
  renderDetail(v.detEl, selStage, fw);
  placeDetail(v);
}

/* ---- stage detail: the phase timeline (one flat outline, a Gantt bar per row on the step's time axis) and the single
   inspector below it. Rows are patched in place by node id, so keyboard focus, scroll and the open inspector survive polls. */
const OUTLINE_GUESS_S = 20;   // bar length of an unstarted leaf with no expected_s and no finished phase to compare with
const isOpenStatus = (n) => n.status === 'pending' || n.status === 'queued' || n.status === 'running';

function runningChain(stage) {
  const chain = [stage];
  for (let n = stage; ;) { const k = (n.children || []).find((c) => c.status === 'running'); if (!k) break; chain.push(k); n = k; }
  return chain;
}

function chainTo(n, id) {
  if (n.id === id) return [n];
  for (const c of n.children || []) { const p = chainTo(c, id); if (p) return [n, ...p]; }
  return null;
}

// The row shown in the inspector: the one the user pinned, else the running leaf, else the deepest failed node, else the step.
function pickRow(fw, stage) {
  const pin = ui.rowSel.get(keyOf(fw, stage));
  if (pin && chainTo(stage, pin)) return pin;
  if (stage.status === 'running') return runningChain(stage).pop().id;
  return (stage.status === 'failed' && deepestFailed(stage) || stage).id;
}

// Visible rows, depth first. A row opens by the user's choice, else because it is an ancestor of the selected row or a
// hash `expand` target; collapsed rows hide their subtree.
function outlineRows(fw, stage, selId) {
  const anc = new Set((chainTo(stage, selId) || []).slice(0, -1).map((x) => x.id));
  const rows = [];
  (function go(n, depth) {
    const kids = (n.children || []).length;
    const k = keyOf(fw, n);
    const open = !!kids && (depth === 0 || (ui.open.has(k) ? ui.open.get(k) : anc.has(n.id) || hashOpen.has(n.id)));
    rows.push({ n, depth, kids, open });
    if (open) for (const c of n.children) go(c, depth + 1);
  }(stage, 0));
  return rows;
}

// Time span of every node on the step's axis. e = actual end (null if not finished), pe = end of what is predicted.
// Unstarted nodes are placed after their predecessor (children of a parallel node all at its start), sized by expected_s.
function timelineLayout(stage, now) {
  const leaves = [];
  walk(stage.children, (x) => { if (!(x.children || []).length && x.status === 'done' && x.elapsed_s != null) leaves.push(x.elapsed_s); });
  const guess = leaves.length ? leaves.reduce((a, b) => a + b, 0) / leaves.length : OUTLINE_GUESS_S;
  const spans = new Map();
  function lay(n, cursor, predict) {
    const kids = n.children || [];
    const started = n.started_at != null;
    const s = started ? n.started_at : cursor;
    let end = s;
    for (const c of kids) end = Math.max(end, lay(c, n.parallel ? s : Math.max(end, s), isOpenStatus(n)));
    let e = null;
    if (started) e = n.status === 'running' ? now : n.ended_at ?? (n.elapsed_s != null ? s + n.elapsed_s : Math.max(end, s));
    else if (n.elapsed_s != null) e = s + n.elapsed_s;
    let pe;
    if (e != null) pe = n.status === 'running' ? Math.max(now, n.expected_s != null ? s + n.expected_s : now, end) : e;
    else if (!predict || n.status === 'skipped') { spans.set(n.id, null); return s; }
    else pe = Math.max(s + (n.expected_s != null ? n.expected_s : kids.length ? 0 : guess), end);
    spans.set(n.id, { s, e, pe, running: n.status === 'running' && started });
    return pe;
  }
  lay(stage, stage.started_at != null ? stage.started_at : now, isOpenStatus(stage));
  const root = spans.get(stage.id);
  const t0 = root ? root.s : now;
  let last = t0;
  for (const sp of spans.values()) if (sp) last = Math.max(last, sp.pe);
  return { spans, t0, total: Math.max(last - t0, 1), now };
}

function ganttHTML(n, L) {
  const sp = L.spans.get(n.id);
  if (!sp) return '';
  const pc = (t) => Math.max(0, Math.min(100, ((t - L.t0) / L.total) * 100));
  const kind = (n.children || []).length ? 'par' : 'leaf';
  const left = pc(sp.s);
  if (sp.e == null) return `<i class="gb pred ${kind}" style="left:${left}%;width:${Math.max(pc(sp.pe) - left, 0.8)}%" title="${n.expected_s != null ? `expected about ${fmtDur(n.expected_s)}` : 'no history for this phase: rough guess'}"></i>`;
  const w = Math.max(pc(sp.e) - left, 0.5);
  const bar = `<i class="gb ${kind} st-${n.status}${sp.running ? ' run' : ''}" style="left:${left}%;width:${w}%"></i>`;
  return sp.pe > sp.e + 0.5 ? `${bar}<i class="gb ext ${kind}" style="left:${left + w}%;width:${Math.max(pc(sp.pe) - left - w, 0)}%" title="expected end"></i>` : bar;
}

function axisHTML(L, tree) {
  // as many evenly spaced ticks as fit the gantt column, at least ~90px apart, so the last label never touches the one before it
  const w = (tree && tree.querySelector('.ogantt') ? tree.querySelector('.ogantt').clientWidth : 0) || 300;
  const n = Math.max(1, Math.min(4, Math.floor(w / 110)));
  const ticks = Array.from({ length: n + 1 }, (_, i) => i / n).map((f) => `<span style="left:${f * 100}%">${fmtDur(Math.round(L.total * f))}</span>`).join('');
  return `<div class="oh-name">Phase</div><div class="oh-chips">Messages</div><div class="oh-gantt">${ticks}</div><div class="oh-t">Time</div><div class="oh-m">Peak mem</div>`;
}

function createRow() {
  const el = h('div', 'orow', `<div class="oname"><span class="ochev" data-act="otog"></span><span class="odot"></span><span class="olbl"></span></div><div class="ochips"></div><div class="ogantt"></div><div class="otime num"></div><div class="omem num"></div>`);
  el.setAttribute('role', 'treeitem'); el.setAttribute('data-act', 'osel'); el.tabIndex = -1;
  el._r = { name: $('.oname', el), chev: $('.ochev', el), dot: $('.odot', el), label: $('.olbl', el), chips: $('.ochips', el), gantt: $('.ogantt', el), time: $('.otime', el), mem: $('.omem', el) };
  return el;
}

function updateRow(el, row, L, selId, tabId) {
  const { n } = row;
  const r = el._r;
  const root = row.depth === 0;
  const isSel = n.id === selId;
  el._node = n; el._open = row.open; el._kids = row.kids;
  setAttr(el, 'data-status', n.status); setAttr(el, 'data-kind', n.kind);
  setAttr(el, 'aria-level', row.depth + 1); setAttr(el, 'aria-selected', String(isSel));
  if (row.kids) setAttr(el, 'aria-expanded', String(row.open)); else el.removeAttribute('aria-expanded');
  setAttr(el, 'tabindex', n.id === tabId ? 0 : -1);
  el.classList.toggle('sel', isSel); el.classList.toggle('root', root);
  if (el._d !== row.depth) { el._d = row.depth; r.name.style.paddingLeft = `${row.depth * 16}px`; }
  const chev = row.kids && !root;   // the step itself is always open
  r.chev.classList.toggle('open', row.open); r.chev.classList.toggle('none', !chev);
  setHTML(r.chev, chev ? CHEV : '');
  if (r.dot._s !== n.status) { r.dot._s = n.status; r.dot.innerHTML = statusInfo(n.status).icon; }
  const lvl = nodeLevel(n);
  setHTML(r.label, root ? '<b>Whole step</b><small>all phases</small>' : `${lvl ? alertIcon(lvl) : ''}${labelHTML(n)}${n.optional ? '<small>optional</small>' : ''}${n.kind === 'task' ? '<small>task</small>' : ''}`);
  r.label.title = n.description || n.label;
  setHTML(r.chips, badgesHTML(n.counts));
  setHTML(r.gantt, ganttHTML(n, L));
  const running = n.status === 'running' && n.started_at;
  const dur = running ? nowS() - n.started_at : n.elapsed_s;
  setHTML(r.time, dur != null ? `<span ${running ? `data-start="${n.started_at}"` : ''}>${fmtDur(dur)}</span>` : n.expected_s != null && isOpenStatus(n) ? `<span class="pt" title="expected duration">~${fmtDur(n.expected_s)}</span>` : '');
  setHTML(r.mem, n.peak_mem_mb != null ? fmtMem(n.peak_mem_mb) : '');
}

function createStageBody(el) {
  const r = el._r;
  el._ol = h('div', 'olwrap', `<div class="oaxis" aria-hidden="true"></div><div class="otree" role="tree"></div>
    <div class="olegend"><span><i class="lg done"></i>completed</span><span><i class="lg run"></i>running</span><span><i class="lg pred"></i>expected</span><span><i class="lg now"></i>now</span></div>`);
  el._tree = $('.otree', el._ol);
  el._tree.addEventListener('keydown', onTreeKey);
  const ins = h('div', 'node insp', `<div class="ihead"></div><div class="dtabs itabs"></div>${['messages', 'log', 'reports', 'timing', 'congestion', 'convergence', 'none'].map((k) => `<div class="pane pane-${k}"></div>`).join('')}`);
  ins._r = { panel: true, tabs: $('.itabs', ins), panes: {} };
  for (const k of ['messages', 'log', 'reports', 'timing', 'congestion', 'convergence']) ins._r.panes[k] = $(`.pane-${k}`, ins);
  el._ins = ins;
  r.bodyin.append(el._ol, ins);
}

function renderStageBody(el, n, fw) {
  el.classList.add('open');
  if (!el._ol) createStageBody(el);
  const now = nowS();
  const selId = pickRow(fw, n);
  const L = timelineLayout(n, now);
  const rows = outlineRows(fw, n, selId);
  const tree = el._tree;
  const tabId = (rows.find((x) => x.n.id === selId) || rows[0]).n.id;   // the one row in the tab order
  const focused = tree.contains(document.activeElement) ? document.activeElement._key : null;
  setAttr(tree, 'aria-label', `Phases of ${n.label}`);
  tree.style.setProperty('--now', `${Math.max(0, Math.min(100, ((now - L.t0) / L.total) * 100))}%`);
  setAttr(tree, 'data-live', n.status === 'running' ? '1' : '0');
  patchList(tree, rows, (x) => x.n.id, createRow, (e, x) => updateRow(e, x, L, selId, tabId));
  setHTML($('.oaxis', el._ol), axisHTML(L, tree));
  if (focused && !tree.contains(document.activeElement)) { const f = [...tree.children].find((c) => c._key === focused); if (f) f.focus({ preventScroll: true }); }   // a row moved in the list
  if (tree._sel !== selId) {   // the auto-selected row moved on: keep it in view inside the outline, never scrolling the page
    tree._sel = selId;
    const se = tree.querySelector('.orow.sel');
    if (se && (se.offsetTop < tree.scrollTop || se.offsetTop + se.offsetHeight > tree.scrollTop + tree.clientHeight)) tree.scrollTop = Math.max(0, se.offsetTop - tree.clientHeight / 2);
  }
  renderInspector(el._ins, fw, n, selId);
}

function renderInspector(ins, fw, stage, selId) {
  const chain = chainTo(stage, selId) || [stage];
  const sel = chain[chain.length - 1];
  const rk = keyOf(fw, sel);
  ins._fw = fw; ins._node = sel; ins._stage = stage;
  if (ins._rk !== rk) { ins._rk = rk; for (const p of Object.values(ins._r.panes)) { p._sig = null; p._h = null; } }
  const crumbs = chain.map((x, i) => `<span${x === sel ? ' class="cur"' : ''}>${i === 0 ? esc(x.label) : labelHTML(x)}</span>`).join('<i>›</i>');
  const running = sel.status === 'running' && sel.started_at;
  const dur = running ? nowS() - sel.started_at : sel.elapsed_s;
  setHTML($('.ihead', ins), `<span class="ilab">Inspecting</span><span class="icrumbs">${crumbs}</span><span class="ist" data-status="${sel.status}">${statusInfo(sel.status).label}</span><span class="ibadges">${badgesHTML(sel.counts)}</span><span class="idur num">${dur != null ? `<span ${running ? `data-start="${sel.started_at}"` : ''}>${fmtDur(dur)}</span>` : sel.expected_s != null && isOpenStatus(sel) ? `<span title="expected duration">~${fmtDur(sel.expected_s)}</span>` : ''}${sel.peak_mem_mb != null ? `<span class="mem">${fmtMem(sel.peak_mem_mb)}</span>` : ''}</span>`);
  const tabs = availableTabs(sel);
  const want = ui.insTab.get(keyOf(fw, stage)) || hashTab.get(sel.id);
  const act = tabs.some((t) => t[0] === want) ? want : (tabs[0] && tabs[0][0]) || null;
  ins._tab = act;
  patchList(ins._r.tabs, tabs, (t) => t[0], ([id]) => { const b = h('button', 'dtab'); b.dataset.act = 'dtab'; b.dataset.tab = id; return b; },
    (b, [id, label]) => { b.classList.toggle('on', id === act); setAttr(b, 'aria-pressed', String(id === act)); setHTML(b, label); });
  for (const [id, pane] of Object.entries(ins._r.panes)) pane.hidden = id !== act;
  const none = $('.pane-none', ins);
  none.hidden = !!act;
  if (!act) {
    setHTML(none, `<div class="none">${sel.status === 'skipped' ? 'Skipped, no data.' : sel.started_at ? 'No log data for this phase yet.' : `Not started yet${sel.expected_s != null ? `, expected about ${fmtDur(sel.expected_s)}` : ''}.`}</div>`);
  } else if (act === 'messages') ensureMessages(ins, sel, fw);
  else if (act === 'log') ensureLog(ins, sel, fw);
  else if (act === 'reports') renderReports(ins._r.panes.reports, sel, rk, fw);
  else if (act === 'timing') renderTiming(ins._r.panes.timing, sel, fw);
  else if (act === 'congestion') renderCongestion(ins._r.panes.congestion, sel);
  else if (act === 'convergence') renderConvergence(ins._r.panes.convergence, sel);
}

// Pin a row. The rows open only because of the old selection (its ancestors) would fold away, so their state is kept.
function selectRow(el, id) {
  for (const r of el._tree.children) if (r._kids && r._d > 0) ui.open.set(keyOf(el._fw, r._node), r._open);
  ui.rowSel.set(keyOf(el._fw, el._node), id);
  render();
}

// Tree keyboard: Up/Down/Home/End move, Left/Right collapse/expand (or go to the parent / first child), Enter/Space select.
function onTreeKey(ev) {
  const row = ev.target.closest('.orow');
  if (!row || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const rows = [...ev.currentTarget.children];
  const i = rows.indexOf(row);
  const go = (j) => { const t = rows[Math.max(0, Math.min(rows.length - 1, j))]; if (t) t.focus(); };
  const el = row.closest('.stagedetail');
  if (ev.key === 'ArrowDown') go(i + 1);
  else if (ev.key === 'ArrowUp') go(i - 1);
  else if (ev.key === 'Home') go(0);
  else if (ev.key === 'End') go(rows.length - 1);
  else if (ev.key === 'ArrowRight') {
    if (row._kids && !row._open) { ui.open.set(keyOf(el._fw, row._node), true); render(); } else if (row._kids) go(i + 1);
  } else if (ev.key === 'ArrowLeft') {
    if (row._kids && row._open && i > 0) { ui.open.set(keyOf(el._fw, row._node), false); render(); } else { const d = +row.getAttribute('aria-level'); let j = i - 1; while (j > 0 && +rows[j].getAttribute('aria-level') >= d) j--; if (i > 0) go(j); }
  } else if (ev.key === 'Enter' || ev.key === ' ') selectRow(el, row._node.id); else return;
  ev.preventDefault();
}

/* ---- inspector tabs: only those that apply to the selected row */
function availableTabs(n) {
  const tabs = [];
  if (!NO_FETCH.has(n.status)) { tabs.push(['messages', 'Messages']); tabs.push(['log', 'Log']); }
  if (n.reports && n.reports.length) tabs.push(['reports', `Reports<small>${n.reports.length}</small>`]);
  if (n.timing && ((n.timing.history && n.timing.history.length) || n.timing.report)) tabs.push(['timing', `Timing<small>${(n.timing.history || []).length || ''}</small>`]);
  if (n.congestion) tabs.push(['congestion', `Congestion<small>L${n.congestion.max_level}</small>`]);
  const cv = convOf(n);
  if (cv) tabs.push(['convergence', `Convergence<small>${cv.conv.iterations.length}</small>`]);
  return tabs;
}


/* ---- details: messages */
const detOf = (k) => { let d = ui.det.get(k); if (!d) { d = { sev: new Set(SEVERITIES.map((s) => s.key)), openG: new Set(), msgs: null, msgSig: null, log: null, logSig: null, busy: {} }; ui.det.set(k, d); } return d; };
const nodeSig = (n) => `${n.status}|${JSON.stringify(n.counts)}`;

// The inspector shows one row at a time: a fetch that comes back after the selection moved on must not paint into it.
const sameRow = (el, fw, n) => el._node && keyOf(el._fw, el._node) === keyOf(fw, n);
function ensureMessages(el, n, fw) {
  const d = detOf(keyOf(fw, n));
  const pane = el._r.panes.messages;
  const sig = nodeSig(n);
  if (d.msgs) renderMessages(pane, d, el);
  else setHTML(pane, '<div class="none">Loading…</div>');
  if (d.msgSig !== sig && !d.busy.msgs) {
    d.busy.msgs = true;
    apiMessages(fw, n).then((res) => { d.msgs = res; d.msgSig = sig; }).catch((e) => { d.msgs = { groups: [], items: [], error: String(e) }; })
      .finally(() => { d.busy.msgs = false; if (el.isConnected && sameRow(el, fw, n)) renderMessages(el._r.panes.messages, d, el); });
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
      .finally(() => { d.busy.log = false; if (el.isConnected && sameRow(el, fw, n)) renderLog(el._r.panes.log, d, n); });
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
REPORT_RENDERERS.hls_csynth = (sm) => {   // Vitis HLS csynth.xml: clock estimate, latency, resources, loops
  const { resources, loops, ...rest } = sm;
  return `${statGrid(rest, (k, v) => k === 'slack_ns' && v < 0)}${resources && resources.length ? REPORT_RENDERERS.utilization({ rows: resources }) : ''}${loops && loops.length ? renderGeneric(loops) : ''}`;
};

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
  if (hashRulesDemo && MOCK && data) { hashRulesDemo = false; rulesDemo(fw); }
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
  setHTML(sr.time, `<span class="num" ${running ? `data-start="${fw.started_at}"` : ''}>${fmtDur(running ? nowS() - fw.started_at : fw.elapsed_s)}</span>${ep ? `<span class="sm-eta" title="${esc(ep.tip)}">ETA ~${ep.clock}${ep.band ? ` (${ep.band})` : ''} <span data-end="${ep.end}">${ep.inTxt}</span></span>` : fin && endedAt(fw) ? `<span class="sm-eta">ended ${fmtClock(endedAt(fw))}</span>` : ''}`);
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
  $('#follow-btn').hidden = true; // shown again by renderStageList, when there are stages to follow
  patchList(tabsEl, [...fws, ...ctabs], (it) => (it.cmp ? it.key : it.id), (it) => (it.cmp ? createCmpTab() : createTab(it)), (el, it) => (it.cmp ? updateCmpTab(el, it) : updateTab(el, it)));
  syncTabsOverflow();
  if (syncHistoryPage()) return;

  const fw = curFw();
  if (!fw) {
    mainEl._r = null; head = null; hideSummary();
    if (!mainEl.querySelector('.empty:not(.loading)')) mainEl.innerHTML = '<div class="empty"><h2>No firmware runs yet</h2><p>Start a Vivado build, or pick a <code>.runs</code> directory, <code>.xpr</code> or log with Explore above.</p></div>';
    return;
  }
  if (!mainEl._r) { buildView(); observeHead(); }
  const v = mainEl._r;
  if (v.fwId !== fw.id) { v.fwId = fw.id; v.stages.innerHTML = ''; v.detail.innerHTML = ''; v.detEl = null; v.selId = null; v.mvList._h = null; v.mvList.innerHTML = ''; v.tv._h = null; v.tv.innerHTML = ''; v.mvQ.value = mvOf(fw).q; }
  renderHeader(fw);
  const view = curView(fw);
  v.split.hidden = view !== 'flow'; v.mv.hidden = view !== 'messages'; v.tv.hidden = view !== 'timing';
  v.detail.hidden = view !== 'flow'; // may live inside the stage list on narrow windows
  mainEl.dataset.view = view;
  // flow selector (only when several flows)
  const flow = fw.flows.find((f) => f.id === ui.flow.get(fw.id)) || fw.flows[0];
  if (fw.flows.length > 1) {
    setHTML(v.seg, `<div class="seg">${fw.flows.map((f) => `<button class="${f === flow ? 'on' : ''}" data-act="flow" data-flow="${esc(f.id)}">${esc(f.label)}</button>`).join('')}</div>`);
  } else setHTML(v.seg, '');
  const hasStages = flow && flow.stages.length;
  if (!hasStages) v.stages.innerHTML = '';
  if (view !== 'flow' && hasStages) renderStageList(fw, flow);
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
  renderRemotes(s.remotes);
  syncIntervalSelect();
  tickUpdated();
}

/* ------------------------------------------------------------------ events */
// ---- reveal: opening something that ends below the window scrolls just enough to show it whole, never pushing
// the control that opened it under the sticky bars. Watches the region briefly, since logs and messages load async;
// a wheel or touch scroll by the user cancels it.
const css = (v) => (window.CSS && CSS.escape ? CSS.escape(v) : String(v).replace(/["\\]/g, '\\$&'));
const nodeCard = (n) => n && n.querySelector(':scope > .main > .card');
function revealFinder(act, t, nodeEl) {
  const d = t.dataset;
  if (['dtab', 'rchip', 'rsel', 'att-toggle', 'fail-log'].includes(act) && nodeEl) return () => ({ ctrl: nodeCard(nodeEl) || nodeEl, region: nodeEl });
  if (act === 'info-toggle') return () => { const r = $('.fwinfo', mainEl); return r && { ctrl: r, region: r }; };
  if (act === 'fix-toggle') return () => { const c = mainEl.querySelector(`.arow[data-key="${css(d.key)}"]`); return c && { ctrl: c, region: c }; };
  const q = (sel) => mainEl.querySelector(sel);
  if (act === 'mv-row') return () => { const c = q(`[data-act="mv-row"][data-id="${css(d.id)}"]`); return c && { ctrl: c, region: c.closest('.mrow') || c }; };
  if (act === 'grp') return () => { const c = q(`[data-act="grp"][data-gid="${css(d.gid)}"]`); return c && { ctrl: c, region: c.parentElement }; };
  if (act === 'pth-row') {
    return () => {
      const c = q(`[data-act="pth-row"][data-key="${css(d.key)}"][data-i="${css(d.i)}"]`);
      if (!c) return null;
      const nx = c.nextElementSibling;
      return { ctrl: c, region: nx && !nx.dataset.act ? nx : c };
    };
  }
  return null;
}
let revealJob = null;
function revealOpened(find) {
  if (revealJob) revealJob.stop();
  let stopped = false; let observed = null;
  const ro = new ResizeObserver(() => requestAnimationFrame(step));
  const job = { stop() { stopped = true; ro.disconnect(); window.removeEventListener('wheel', job.stop); window.removeEventListener('touchmove', job.stop); } };
  function step() {
    if (stopped) return;
    const f = find();
    if (!f || !f.region || !f.region.isConnected) return;
    if (observed !== f.region) { if (observed) ro.unobserve(observed); ro.observe(f.region); observed = f.region; }
    const d = Math.min(f.region.getBoundingClientRect().bottom - (window.innerHeight - 16), f.ctrl.getBoundingClientRect().top - stickTop() - 8);
    if (d > 4) window.scrollBy({ top: d, behavior: 'smooth' });
  }
  window.addEventListener('wheel', job.stop, { passive: true }); window.addEventListener('touchmove', job.stop, { passive: true });
  setTimeout(job.stop, 2500);
  revealJob = job;
  requestAnimationFrame(() => requestAnimationFrame(step));
}

document.addEventListener('click', async (ev) => {
  const t = ev.target.closest('[data-act]');
  if (!t) return;
  const act = t.dataset.act;
  if (act === 'doc') return; // plain link: open in new tab, never toggles the card around it
  const nodeEl = t.closest('.node');
  const rf = revealFinder(act, t, nodeEl);
  if (rf) setTimeout(() => revealOpened(rf), 0); // after this handler has re-rendered
  if (act === 'tab') {
    const el = t.closest('.tab');
    if (ev.target.closest('.t-x') && el._key.startsWith('cmp:')) { closeCmp(el._key); return; }
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
    hist.on = false;
    if (el._key.startsWith('cmp:')) { selectCmp(el._key); window.scrollTo(0, 0); } else { selectCmp(null); selected = el._key; lsSet('vmon.tab', selected); }
    render();
  } else if (act === 'history' || act === 'history-close') {
    setHistory(act === 'history' ? !hist.on : false);
  } else if (act === 'hsort') {
    hist.asc = !hist.asc; render();
  } else if (act === 'hpick') {
    hxPick(ev, t);
  } else if (act === 'hclear') {
    hist.pick = []; renderHistory();
  } else if (act === 'hcompare') {
    startCompare(hist.pick);
  } else if (act === 'hprev') {
    const b = hist.data.builds.find((x) => x.fw_id === t.dataset.fw && x.build === t.dataset.build), p = b && previousOf(b);
    if (p) startCompare([{ fw: p.fw_id, build: p.build }, { fw: b.fw_id, build: b.build }]);
  } else if (act === 'hcmp-close') {
    setHistory(true);
  } else if (act === 'hcmptab') {
    const c = shownCmpTab();
    if (c) { c.tab = t.dataset.tab; persistCmp(); render(); }
  } else if (act === 'cmp-open-fw') {
    openFirmware(t.dataset.fw);
  } else if (act === 'fw-compare') {
    const f = curFw();
    if (f) openHistoryFor(f);
  } else if (act === 'hrep') {
    openHistoryReport(t);
  } else if (act === 'hexp') {
    if (t.dataset.format === 'md') { ev.preventDefault(); exportMarkdown(t.dataset.fw, t.dataset.build); }
    else if (MOCK) { ev.preventDefault(); window.open(mockSummaryUrl(t.dataset.fw, t.dataset.build, 'html'), '_blank', 'noopener'); }
  } else if (act === 'hexp-copy') {
    try { await navigator.clipboard.writeText(await summaryText(t.dataset.fw, t.dataset.build)); toast('Markdown summary copied'); }
    catch (e) { toast(`Could not copy the summary: ${e.message}`); }
  } else if (act === 'hbit') {
    if (t.getAttribute('aria-disabled') === 'true') ev.preventDefault();
    else if (MOCK) { ev.preventDefault(); toast('Mock mode: download disabled'); }
  } else if (act === 'hrow' || act === 'hopen') {
    if (act === 'hrow' && ev.target.closest('a, button, input, label')) return;
    openFromHistory(t.dataset.fw, t.dataset.project, t.dataset.name);
  } else if (act === 'osel' && nodeEl) {
    selectRow(nodeEl, t._node.id);   // a manual selection is pinned
  } else if (act === 'otog' && nodeEl) {
    const row = t.closest('.orow');
    ui.open.set(keyOf(nodeEl._fw, row._node), !row._open); render();
  } else if (act === 'dtab' && nodeEl) {
    ui.insTab.set(keyOf(nodeEl._fw, nodeEl._stage), t.dataset.tab); render();
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
  } else if (act === 'al-dismiss') {
    const fw = curFw(); dismissedOf(fw).add(t.dataset.key); saveDismissed(); render();
  } else if (act === 'al-restore') {
    const fw = curFw(); dismissedOf(fw).clear(); saveDismissed(); render();
  } else if (act === 'goto') {
    gotoNode(curFw(), t.dataset.node);
  } else if (act === 'rchip' && nodeEl) {
    const k = keyOf(nodeEl._fw, nodeEl._node);
    ui.rowSel.set(k, nodeEl._node.id); ui.insTab.set(k, 'reports'); ui.rsel.set(k, t.dataset.path); render();
  } else if (act === 'rsel' && nodeEl) {
    ui.rsel.set(keyOf(nodeEl._fw, nodeEl._node), t.dataset.path); render();
  } else if (act === 'raw' && nodeEl) {
    const rp = nodeEl._node.reports[+t.dataset.i];
    try { showModal(rp.name + ' — ' + rp.path, await apiReportRaw(nodeEl._fw, rp.path)); } catch (e) { toast('Could not load report: ' + e.message); }
  } else if (act === 'pth-clk') {
    const st = ui.paths.get(t.dataset.key); if (!st) return;
    const i = +t.dataset.i; st.clk.has(i) ? st.clk.delete(i) : st.clk.add(i);
    render();
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
    ui.sel.set(el._fw.id, { id: el._node.id, follow: false }); ui.view.set(el._fw.id, 'flow'); render();
  } else if (act === 'follow') {
    const fw = curFw(); const cur = ui.sel.get(fw.id);
    if (cur && cur.follow) ui.sel.set(fw.id, { id: mainEl._r.selId, follow: false }); // toggle off: pin the stage being shown
    else { ui.sel.set(fw.id, { id: null, follow: true }); for (const f of fw.flows || []) for (const s of f.stages) resetNode(fw, s); }   // following again: unpin the row and forget manual opens too
    render();
  } else if (act === 'fix-toggle') {
    fixOpen.has(t.dataset.key) ? fixOpen.delete(t.dataset.key) : fixOpen.add(t.dataset.key); renderHeader(curFw());
  } else if (act === 'attn-more') {
    attnAll = !attnAll; renderHeader(curFw());
  } else if (act === 'hero-menu') {
    heroMenu = !heroMenu; renderHeader(curFw());
  } else if (act === 'hero-stage') {
    const fw = curFw(); ui.sel.set(fw.id, { id: t.dataset.id, follow: false }); ui.view.set(fw.id, 'flow'); render();
  } else if (act === 'hint-goto') {
    hintGoto(curFw(), t.dataset.hint);
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
  } else if (act === 'outtest') {
    sendOutTest();
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
  else if (act === 'mv-export') exportRules(fw);
  else if (act === 'mv-import') { if (fw.host) toast(`Message rules are per machine: import them on ${fw.host}`); else $('.mv-file', mainEl).click(); }
  else if (act === 'mv-rule') {
    apiMsgRule(fw, id, t.dataset.pri || null).then(() => { m.rev++; if (MOCK) { fw.top_messages = mockTop(fw); render(); } else ensureTriage(fw); })
      .catch((e) => toast('Could not save rule: ' + e.message));
  }
}

/* ---- message rules: export, and import with a preview (merge / replace) */
const RULE_PRIORITIES = ['critical', 'high', 'medium', 'low', 'mute'];
const MAX_RULES_FILE = 2e6;
const rd = { fw: null, data: null, mode: 'merge', keep: false, sum: null, err: null, busy: false, seq: 0, ret: null, el: null };
const priLabel = (p) => (p === 'high' ? '★ high' : p);

const mockRulesCurrent = (fw) => Object.fromEntries(Object.entries(mock.rules).filter(([k, v]) => v && k.startsWith(`${fw.id}|`)).map(([k, v]) => [k.slice(fw.id.length + 1), v]));
function mockRulesImport(fw, data, mode, keep, dry) {
  const legacy = data && typeof data === 'object' && !Array.isArray(data) && !('format' in data);
  if (!legacy && !(data && data.format === 'vmon-message-rules' && data.version === 1 && data.rules && typeof data.rules === 'object')) throw new Error('not a vmon message rules file (format vmon-message-rules, version 1)');
  const rules = {}, invalid = [];
  for (const [id, spec] of Object.entries(legacy ? data : data.rules)) {
    const pri = legacy && typeof spec === 'string' ? spec : spec && spec.priority;
    if (!id.trim() || id.length > 200) invalid.push({ id, error: 'bad id' });
    else if (!RULE_PRIORITIES.includes(pri)) invalid.push({ id, error: `priority must be one of ${RULE_PRIORITIES.join(', ')}` });
    else rules[id] = pri;
  }
  const cur = mockRulesCurrent(fw);
  const s = { mode, dry_run: dry, applied: false, added: [], changed: [], removed: [], unchanged: 0, kept_mine: 0, invalid };
  for (const [id, pri] of Object.entries(rules).sort()) {
    if (!(id in cur)) s.added.push({ id, priority: pri });
    else if (cur[id] === pri) s.unchanged++;
    else if (keep && mode === 'merge') s.kept_mine++;
    else s.changed.push({ id, from: cur[id], to: pri });
  }
  if (mode === 'replace') s.removed = Object.entries(cur).filter(([id]) => !(id in rules)).map(([id, priority]) => ({ id, priority })).sort((a, b) => a.id.localeCompare(b.id));
  if (!dry && !invalid.length) {
    s.applied = true;
    for (const x of s.added) mock.rules[`${fw.id}|${x.id}`] = x.priority;
    for (const x of s.changed) mock.rules[`${fw.id}|${x.id}`] = x.to;
    for (const x of s.removed) delete mock.rules[`${fw.id}|${x.id}`];
  }
  return s;
}
async function apiRulesImport(fw, data, mode, keep, dry) {
  if (MOCK) return mockRulesImport(fw, data, mode, keep, dry);
  const r = await fetch('/api/msgrules/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, dry_run: dry, keep_mine: keep, data }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}

async function exportRules(fw) {
  if (fw.host) { toast(`Message rules are per machine: export them on ${fw.host}`); return; }
  try {
    if (MOCK) {
      const rules = Object.fromEntries(Object.entries(mockRulesCurrent(fw)).map(([k, v]) => [k, { priority: v }]));
      const doc = { format: 'vmon-message-rules', version: 1, exported_at: Math.round(nowS()), exported_by: '', rules };
      saveBlob(new Blob([JSON.stringify(doc, null, 1)], { type: 'application/json' }), `vmon_message_rules_${new Date().toISOString().slice(0, 10)}.json`);
      toast('Mock mode: saved the mock rules file');
      return;
    }
    const r = await fetch('/api/msgrules/export', { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status);
    const name = ((r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/) || [])[1] || 'vmon_message_rules.json';
    saveBlob(await r.blob(), name);
    toast(`Saved ${name}`);
  } catch (e) { toast(`Could not export the rules: ${e.message}`); }
}

function rdList(title, items, line) {
  if (!items.length) return '';
  const shown = items.slice(0, 200).map((x) => `<li>${line(x)}</li>`).join('');
  return `<section class="rd-sec"><h3>${title} <b>${items.length}</b></h3><ul class="rd-list">${shown}${items.length > 200 ? `<li class="rd-more">and ${items.length - 200} more</li>` : ''}</ul></section>`;
}
function rulesDialogHTML() {
  const s = rd.sum, replace = rd.mode === 'replace';
  const pri = (p) => `<span class="rd-pri ${p === 'mute' ? 'mute' : p === 'high' ? 'star' : ''}">${esc(priLabel(p))}</span>`;
  let body;
  if (rd.err) body = `<div class="rd-err" role="alert">${esc(rd.err)}</div>`;
  else if (!s) body = '<div class="none">Checking the file…</div>';
  else {
    const change = s.added.length + s.changed.length + s.removed.length;
    body = `<p class="rd-sum" aria-live="polite">${s.added.length} added · ${s.changed.length} changed${replace ? ` · ${s.removed.length} removed` : ''} · ${s.unchanged} unchanged${s.kept_mine ? ` · ${s.kept_mine} kept as yours` : ''}${s.invalid.length ? ` · <span class="bad">${s.invalid.length} invalid</span>` : ''}</p>`
      + (replace ? `<p class="rd-warn">Replace discards your current rules that are not in this file${s.removed.length ? ` (${s.removed.length} below)` : ''}. Export first if you want a backup.</p>` : '')
      + (s.invalid.length ? '<p class="rd-warn">The file has invalid entries. Fix them (or ask the sender) before importing; nothing is applied until it is clean.</p>' : '')
      + rdList('Invalid', s.invalid, (x) => `<span class="mono">${esc(x.id || '(empty id)')}</span> <span class="rd-why">${esc(x.error)}</span>`)
      + rdList('Added', s.added, (x) => `<span class="mono">${esc(x.id)}</span> ${pri(x.priority)}`)
      + rdList('Changed', s.changed, (x) => `<span class="mono">${esc(x.id)}</span> ${pri(x.from)} <span aria-label="to">→</span> ${pri(x.to)}`)
      + rdList('Removed', s.removed, (x) => `<span class="mono">${esc(x.id)}</span> ${pri(x.priority)}`)
      + (change || s.invalid.length ? '' : '<div class="none">Nothing to change: this file matches your rules.</div>');
  }
  const can = rd.sum && !rd.err && !rd.sum.invalid.length && (rd.sum.added.length + rd.sum.changed.length + rd.sum.removed.length) > 0 && !rd.busy;
  return `<div class="mbox rbox" role="dialog" aria-modal="true" aria-labelledby="rd-title">
    <div class="mhead"><b id="rd-title">Import message rules</b><button class="icon-btn" data-rd="cancel" aria-label="Close">✕</button></div>
    <div class="rd-opts"><label><input type="radio" name="rd-mode" value="merge" ${replace ? '' : 'checked'}> Merge <small>keep your other rules; the file wins on conflicts</small></label>
      <label class="${replace ? 'sel-replace' : ''}"><input type="radio" name="rd-mode" value="replace" ${replace ? 'checked' : ''}> Replace <small>discard your current rules, use only this file</small></label>
      <label class="rd-keep"><input type="checkbox" data-rd="keep" ${rd.keep ? 'checked' : ''} ${replace ? 'disabled' : ''}> Keep my priority when both define a message</label></div>
    <div class="rd-body">${body}</div>
    <div class="rd-foot"><button class="mv-btn" data-rd="cancel">Cancel</button><button class="mv-btn primary${replace ? ' danger' : ''}" data-rd="apply" ${can ? '' : 'disabled'}>${rd.busy ? 'Applying…' : replace ? 'Replace my rules' : 'Apply'}</button></div></div>`;
}
function renderRules() {
  const el = rd.el; if (!el) return;
  const key = document.activeElement && el.contains(document.activeElement) ? document.activeElement.dataset.rd || document.activeElement.value : null;
  el.innerHTML = rulesDialogHTML();
  if (key) { const t = [...el.querySelectorAll('[data-rd],[name="rd-mode"]')].find((x) => (x.dataset.rd || x.value) === key && !x.disabled); if (t) t.focus(); }
}
async function previewRules() {
  const seq = ++rd.seq; rd.sum = null; rd.err = null; renderRules();
  try {
    const s = await apiRulesImport(rd.fw, rd.data, rd.mode, rd.keep, true);
    if (seq === rd.seq) { rd.sum = s; renderRules(); }
  } catch (e) { if (seq === rd.seq) { rd.err = e.message; renderRules(); } }
}
function openRules(fw, data) {
  if (!rd.el) {
    const el = rd.el = h('div', 'modal'); el.id = 'rules-dialog'; document.body.appendChild(el);
    el.addEventListener('click', (e) => { const b = e.target.closest('[data-rd]'); if (e.target === el || (b && b.dataset.rd === 'cancel')) closeRules(); else if (b && b.dataset.rd === 'apply') applyRules(); });
    el.addEventListener('change', (e) => {
      if (e.target.name === 'rd-mode') { rd.mode = e.target.value; previewRules(); }
      else if (e.target.dataset.rd === 'keep') { rd.keep = e.target.checked; previewRules(); }
    });
    el.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const f = [...el.querySelectorAll('button:not([disabled]),input:not([disabled])')];
      if (!f.length) return;
      const i = f.indexOf(document.activeElement);
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); } else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
    });
  }
  Object.assign(rd, { fw, data, mode: 'merge', keep: false, busy: false, ret: document.activeElement });
  rd.el.hidden = false;
  previewRules();
  $('[data-rd="cancel"]', rd.el).focus();
}
function closeRules() {
  if (!rd.el || rd.el.hidden) return false;
  rd.el.hidden = true; rd.seq++;
  if (rd.ret && rd.ret.isConnected) rd.ret.focus();
  return true;
}
async function applyRules() {
  if (rd.busy || !rd.sum) return;
  const { fw, mode } = rd;
  rd.busy = true; renderRules();
  try {
    const s = await apiRulesImport(fw, rd.data, mode, rd.keep, false);
    closeRules();
    toast(`Rules imported: ${s.added.length} added, ${s.changed.length} changed${mode === 'replace' ? `, ${s.removed.length} removed` : ''}`);
    for (const m of ui.mv.values()) m.rev++;
    if (MOCK) { for (const f of state.firmwares) f.top_messages = mockTop(f); render(); } else ensureTriage(fw);
  } catch (e) { rd.busy = false; renderRules(); toast(`Import failed: ${e.message}`); }
}
document.addEventListener('change', async (ev) => {
  if (!ev.target.classList.contains('mv-file')) return;
  const file = ev.target.files[0]; ev.target.value = '';
  const fw = curFw(); if (!file || !fw) return;
  if (file.size > MAX_RULES_FILE) { toast('That file is too large to be a rules file (over 2 MB)'); return; }
  try { openRules(fw, JSON.parse(await file.text())); } catch { toast('That file is not valid JSON'); }
});
function rulesDemo(fw) {       // mock + #rulesdemo=1: current rules and a canned file that shows every kind of line
  const ids = mockTriage(fw, { sev: SEV_ALL }).groups.map((g) => g.id);
  [[0, 'high'], [1, 'mute'], [2, 'high'], [3, 'mute']].forEach(([i, p]) => { if (ids[i]) mock.rules[`${fw.id}|${ids[i]}`] = p; });
  const rules = { [ids[0]]: { priority: 'high' }, [ids[1]]: { priority: 'high', note: 'now matters' }, [ids[2]]: { priority: 'mute' },
    [ids[4] || 'Synth 8-6014']: { priority: 'mute' }, [ids[5] || 'Place 30-574']: { priority: 'high' }, 'Bad 1-1': { priority: 'pin' } };
  openRules(fw, { format: 'vmon-message-rules', version: 1, exported_at: 1760000000, exported_by: '', rules });
}

for (const [type, on] of [['mouseover', true], ['mouseout', false], ['focusin', true], ['focusout', false]]) document.addEventListener(type, (ev) => pathHover(ev, on));
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
h     Build history (again, or Esc, to leave; Esc also closes a comparison)
j / k next / previous stage
n     jump to the next alert
c     collapse all expanded steps
Esc   close dialog or popover
?     this help`;
let alertCursor = -1;
function collapseOutline(fw) {   // every row below the step; the selected row stays in the inspector
  ui.open.clear();
  const st = mainEl._r.detEl && mainEl._r.detEl._node;
  if (st) walk(st.children, (x) => { if ((x.children || []).length) ui.open.set(keyOf(fw, x), false); });
}
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
  if (ev.key === 'Escape') { if (closeRules() || closeModal()) return; if (notif.open) { closePop(); notifyBtn.focus(); } else if (hist.on && !(xp.el && !xp.el.hidden)) setHistory(false); return; }
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || ev.ctrlKey || ev.metaKey || ev.altKey || (xp.el && !xp.el.hidden)) return;
  const fw = curFw();
  if (/^[1-9]$/.test(ev.key)) {
    const f = state.firmwares[+ev.key - 1];
    if (f) { hist.on = false; selectCmp(null); selected = f.id; lsSet('vmon.tab', selected); render(); }
  } else if (ev.key === '?') {
    showModal('Keyboard shortcuts', SHORTCUTS);
  } else if (ev.key === 'h') {
    setHistory(!hist.on);
  } else if (hist.on) {
    return;
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
    collapseOutline(fw); hashOpen.clear(); render();
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
  for (const el of document.querySelectorAll('.node.insp')) {
    if (el._node && el._node.status === 'running' && el._tab === 'log') ensureLog(el, el._node, el._fw, true);
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
const xp = { el: null, path: null, parent: null, home: null, drives: false, entries: [], recent: [], sel: null, filter: '', editing: false, busy: false, error: null, curKind: null, pendingSel: null, reqId: 0 };

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
  const trimmed = path.replace(/[\\/]+$/, '');
  const i = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));
  const parent = i > 0 ? trimmed.slice(0, i) : '/';
  exploreGo(/^[A-Za-z]:$/.test(parent) ? parent + '\\' : parent, null, path);
}

async function exploreGo(path, kind = null, selectPath = null) {
  const id = ++xp.reqId;
  xp.busy = true; renderExplore();
  try {
    const d = await apiBrowse(path);
    if (id !== xp.reqId) return;
    Object.assign(xp, { path: d.path, parent: d.parent, home: d.home, drives: !!d.drives, entries: d.entries || [], recent: d.recent || xp.recent, error: null, curKind: kind, sel: selectPath, filter: '' });
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
  await watchAndOpen(t.path);
}

// Windows paths (C:\x, C:/x, \\server\share) compare case-insensitively and with one separator
const isWinPath = (x) => /^([A-Za-z]:|\\\\)/.test(x);
const normPath = (x) => { const s = String(x || '').replace(/[\\/]+$/, ''); return isWinPath(s) ? s.replace(/\//g, '\\').toLowerCase() : s; };
const fwForPath = (path) => {
  const base = normPath(path).replace(/\.(xpr|log)$/, '');
  return state.firmwares.find((f) => normPath(f.path) === normPath(path) || normPath(f.path).startsWith(base) || normPath(path).startsWith(normPath(f.path)));
};
function openFirmware(id) { hist.on = false; selectCmp(null); selected = id; lsSet('vmon.tab', selected); render(); window.scrollTo({ top: 0 }); }
// Watch a path (POST /api/watch), wait for its firmware to show up in the state, then switch to its tab.
async function watchAndOpen(path) {
  const before = new Set(state.firmwares.map((f) => f.id));
  try {
    const r = await fetch('/api/watch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
    if (!r.ok) throw new Error((await r.text()) || r.status);
  } catch (e) { toast('Could not open: ' + e.message); return false; }
  toast('Opening ' + path);
  for (let i = 0; i < 14; i++) {
    await poll();
    const hit = state.firmwares.find((f) => !before.has(f.id)) || fwForPath(path);
    if (hit) { openFirmware(hit.id); return true; }
    await new Promise((res) => setTimeout(res, 700));
  }
  toast('The project did not load: ' + path);
  return false;
}
// A history row opens its project in the standard view: its tab if loaded, else the project is watched again.
// The view always shows the project's current (latest) build, since the run directory is reused by every build.
async function openFromHistory(fwId, project, name) {
  const remote = fwId.includes('~'); // its project path is on another machine: never match it against local paths
  const loaded = state.firmwares.find((f) => f.id === fwId) || (!remote && project && fwForPath(project));
  if (loaded) { openFirmware(loaded.id); return; }
  if (remote) { toast(`${name} is not loaded on ${fwId.split('~')[0]}: open it there`); return; }
  if (!project) { toast(`No project path recorded for ${name}`); return; }
  if (MOCK) { toast(`Mock mode: would open ${project}`); return; }
  await watchAndOpen(project);
}

// Breadcrumb segments [{label, path}] for /posix/paths, C:\drive\paths and \\server\share\paths (the drive list is "::drives")
const X_DRIVES = '::drives';
function xCrumbs(path) {
  const p = path || '/';
  if (p === X_DRIVES) return [{ label: 'This PC', path: X_DRIVES }];
  if (!isWinPath(p)) { let acc = ''; return [{ label: '/', path: '/' }].concat(p.split('/').filter(Boolean).map((s) => ({ label: s, path: (acc += '/' + s) }))); }
  const m = p.match(/^[A-Za-z]:|^\\\\[^\\/]+[\\/][^\\/]+/);
  const root = m[0].replace(/\//g, '\\') + '\\';
  let acc = root;
  const out = (xp.drives ? [{ label: 'This PC', path: X_DRIVES }] : []).concat([{ label: root, path: root }]);
  for (const s of p.slice(m[0].length).split(/[\\/]/).filter(Boolean)) { acc += (acc.endsWith('\\') ? '' : '\\') + s; out.push({ label: s, path: acc }); }
  return out;
}

function renderExplore() {
  const r = xp.r;
  // breadcrumb
  const segs = xCrumbs(xp.path).map((c, i) => `${i ? '<span class="xsep">›</span>' : ''}<button class="xseg" data-xact="go" data-path="${esc(c.path)}" title="${esc(c.path)}">${esc(c.label)}</button>`);
  setHTML(r.crumbs, segs.join(''));
  r.crumbs.scrollLeft = r.crumbs.scrollWidth;
  // sidebar
  const home = xp.home;
  const place = (icon, label, path, act = 'go') => `<button class="xplace${xp.path === path ? ' on' : ''}" data-xact="${act}" data-path="${esc(path)}" title="${esc(path)}">${icon}<span>${esc(label)}</span></button>`;
  const IC = (d) => `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const rec = (xp.recent || []).map((p) => `<button class="xplace recent${xp.sel === p ? ' on' : ''}" data-xact="recent" data-path="${esc(p)}" title="${esc(p)}">${IC(XI.folder)}<span>${esc(p.split(/[\\/]/).filter(Boolean).slice(-2).join('/'))}</span></button>`).join('');
  setHTML(r.side, `<div class="xsh">Places</div>${home ? place(IC('<path d="M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10"/>'), 'Home', home) : ''}${xp.drives ? place(IC('<rect x="3" y="5" width="18" height="11" rx="2"/><path d="M8 20h8M12 16v4"/>'), 'This PC', X_DRIVES) : place(IC('<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/>'), 'Root', '/')}<div class="xsh">Recent</div>${rec || '<div class="xnone">Nothing watched yet</div>'}`);
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
  setText(r.sel, tgt ? tgt.path : selE ? `${selE.path} — not watchable (open it, or pick a .runs / run / .xpr / log)` : xp.path === X_DRIVES ? 'This PC' : xp.path || '');
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
function openPop() { notif.open = true; popEl.hidden = false; renderPop(); loadOut(); }
// Server-side channels (read-only here; configured in ~/.config/vmon/flows.toml).
async function loadOut() {
  try { notif.out = await jget(MOCK ? 'mock/notify.json' : '/api/notify'); notif.outErr = false; } catch { notif.outErr = true; }
  renderPop();
}
function outState(c) {
  if (c.error) return ['err', `failed: ${c.error}`];
  if (!c.enabled) return ['off', 'off'];
  return c.configured ? ['ok', 'on'] : ['warn', 'not configured'];
}
function outHTML() {
  const o = notif.out;
  const rows = o ? o.channels.map((c) => { const [st, txt] = outState(c); return `<div class="no-row" data-st="${st}"><span class="no-dot"></span><b>${esc(c.label)}</b><code>${esc(c.target)}</code><span class="no-st">${esc(txt)}</span></div>`; }).join('')
    : `<div class="none">${notif.outErr ? 'Could not read the server-side settings.' : 'Loading…'}</div>`;
  const usable = o && o.enabled && o.channels.some((c) => c.enabled);
  const sum = o ? `<div class="no-sum">${o.enabled ? `Sends: ${esc(o.kinds.map((k) => k.replace(/_/g, ' ')).join(', ') || 'no step or run events')}; alerts ${esc(o.codes.join(', ') || 'none')} from ${esc(o.min_level)}.` : 'Master switch is off (<code>enabled = false</code>).'}</div>` : '';
  return `<div class="np-outhead"><b>Outside the browser</b><button class="rawbtn" data-act="outtest"${usable && !notif.testing ? '' : ' disabled'}>${notif.testing ? 'sending…' : 'send test'}</button></div>
    <div class="no-list">${rows}</div>${sum}
    <div class="no-hint">Set up in <code>~/.config/vmon/flows.toml</code> under <code>[notify]</code> (see docs/configuration.md).</div>`;
}
async function sendOutTest() {
  notif.testing = true; renderPop();
  try {
    let results;
    if (MOCK) results = notif.out.channels.filter((c) => c.enabled).map((c) => (c.configured ? { name: c.name, ok: true } : { name: c.name, ok: false, error: 'not configured' }));
    else {
      const r = await fetch('/api/notify/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      if (!r.ok) throw new Error(r.status);
      results = (await r.json()).results;
    }
    toast(results.length ? results.map((r) => `${r.name}: ${r.ok ? 'sent' : `failed (${r.error})`}`).join(' · ') : 'No channel is enabled');
  } catch (e) { toast(`Could not send the test: ${e.message}`); }
  notif.testing = false; await loadOut();
}
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
    : '<div class="none">Nothing yet. Events that match your settings below are collected here.</div>';
  const html = `<div class="np-head"><b>Notifications</b></div>
    <div class="np-loghead"><b>Recent</b>${notif.log.length ? '<button class="rawbtn" data-act="nclear">clear</button>' : ''}</div><div class="np-log">${log}</div>
    <div class="np-settings"><div class="np-loghead"><b>Settings</b></div>${permRow}
    <div class="np-cols"><div><div class="np-h">Notify me when a…</div>${EVENT_KINDS.map(([k, l]) => box('kinds', k, l)).join('')}</div>
    <div><div class="np-h">…or an alert of type</div>${ALERT_CODES.map(([k, l]) => box('codes', k, l)).join('')}</div></div>
    ${outHTML()}</div>`;
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
    cpu: { pct: sys.cpu_pct, txt: `${Math.round(sys.cpu_pct)}%`, tip: `CPU ${sys.cpu_pct.toFixed(1)}% busy across ${sys.cpu_count} logical CPUs${sys.load1 == null ? '' : `\nLoad average (1 min): ${sys.load1.toFixed(2)}`}` },
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

/* ---- remote vmon instances: one dot per host, only when some are configured */
const remEl = $('#remotes');
const fmtClockS = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
function remoteTip(r) {
  const lines = [`${r.name} · ${r.url}`, r.online ? `online · updated ${fmtClockS(r.last_ok)}` : `${r.error || 'unreachable'}${r.last_ok ? ` · last update ${fmtClockS(r.last_ok)}` : ''}`,
    `${r.firmwares} firmware${r.firmwares === 1 ? '' : 's'}`];
  const sys = r.system;
  if (sys && sys.cpu_pct != null) lines.push(`CPU ${Math.round(sys.cpu_pct)}% · RAM ${gb(sys.mem_used_mb)}/${gb(sys.mem_total_mb)} GB${r.online ? '' : ' (last known)'}`);
  return lines.join('\n');
}
function renderRemotes(list) {
  list = list || [];
  remEl.hidden = !list.length;
  setHTML(remEl, list.map((r) => { const tip = remoteTip(r); return `<span class="rdot" tabindex="0" role="img" data-state="${r.online ? 'online' : 'offline'}" title="${esc(tip)}" aria-label="${esc(tip.replace(/\n/g, ', '))}"><i></i><span>${esc(r.name)}</span></span>`; }).join(''));
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
// Backend stand-in for Node.expected_s (history medians, else catalog weights): the mock state predates the field.
// Each step gets a typical duration; its unfinished phases share it by name, the rest equally.
const MOCK_STEP_S = { place_design: 300, phys_opt_design: 150, route_design: 900, write_bitstream: 80 };
const MOCK_PHASE_SHARE = { 'Global Placement': 0.3, 'Detail Placement': 0.15, 'Global Routing': 0.3 };
function mockExpected(fw) {
  const open = (n) => ['pending', 'queued', 'running'].includes(n.status);
  const fill = (n, total) => {
    const kids = (n.children || []).filter(open);
    const named = kids.reduce((t, k) => t + (MOCK_PHASE_SHARE[k.label.replace(/^Phase [\d.]+ /, '')] || 0), 0);
    for (const k of kids) {
      const share = MOCK_PHASE_SHARE[k.label.replace(/^Phase [\d.]+ /, '')] || Math.max(0.05, (1 - named) / Math.max(1, kids.filter((x) => !MOCK_PHASE_SHARE[x.label.replace(/^Phase [\d.]+ /, '')]).length));
      k.expected_s = Math.round(total * share);
    }
    for (const k of n.children || []) fill(k, k.expected_s || total * 0.4);
  };
  for (const flow of fw.flows) {
    for (const st of flow.stages) {
      if (!open(st) || !MOCK_STEP_S[st.id.split('/').pop()]) continue;
      st.expected_s = MOCK_STEP_S[st.id.split('/').pop()];
      fill(st, st.expected_s);
    }
  }
}
function startMock() {
  setConn('mock', 'mock data');
  const s = syncJson('mock/state.json');
  shiftTimes(s, nowS() - s.generated_at);
  // Remote demo firmwares are copies of local ones under a host (keeps mock/state.json small).
  for (const c of s.mock_remote_clones || []) {
    const src = s.firmwares.find((f) => f.id === c.from);
    if (src) { const { from, ...over } = c; s.firmwares.push({ ...JSON.parse(JSON.stringify(src)), ...over }); }
  }
  delete s.mock_remote_clones;
  for (const f of s.firmwares) { f.top_messages = mockTop(f); mockExpected(f); }
  if (params.get('remote') === 'off') for (const r of s.remotes) { r.online = false; r.error = 'connection refused'; r.last_ok -= 720; } // ?remote=off demos the unreachable state
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
  if (!s) { s = { key: k, type: 'all', failing: false, open: new Set(hashPth), clk: new Set(hashPclk ? hashPth : []), data: null, sig: null, busy: false, err: null }; ui.paths.set(k, s); }
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
// ---- expanded path: header, time bar, block chain, clock table
const nsOf = (v, d = 3) => (v == null ? '—' : `${v.toFixed(d)} ns`);
const instOf = (s) => (s.kind === 'net' ? '' : String(s.name || '').split('/').slice(0, -1).join('/'));
function commonPrefix(insts) {
  const lists = insts.filter(Boolean).map((i) => i.split('/'));
  if (!lists.length) return [];
  const max = Math.min(...lists.map((l) => l.length)) - 1; // always leave the leaf
  let n = 0;
  while (n < max && lists.every((l) => l[n] === lists[0][n])) n++;
  return lists[0].slice(0, n);
}
function leafName(inst, skip) {
  const rest = inst.split('/').slice(skip);
  return (rest.length > 2 ? '…/' : '') + rest.slice(-2).join('/');
}
function pathHead(p) {
  const stat = (k, v) => `<div class="pd-stat"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  const cells = Object.entries(p.cells || {}).map(([c, n]) => `${esc(c)}×${n}`).join(' ');
  const split = p.logic_delay == null ? '—' : `<b>${p.logic_delay.toFixed(3)}</b> logic (${p.logic_pct.toFixed(0)}%) · <b>${p.route_delay.toFixed(3)}</b> route (${p.route_pct.toFixed(0)}%)`;
  return `<div class="pd-top"><b class="num pd-sl ${slackCls(p.slack)}">${fmtSlack(p.slack)} ns</b><span class="pd-ok">${esc(p.status)}</span>
      <span class="ptype ${p.type}">${p.type}</span>${p.corner ? `<small>${esc(p.corner)}</small>` : ''}
      <span class="pd-clk mono" title="Path group ${esc(p.group || '—')}">${esc(p.from_clock || '—')}<i class="arr">→</i>${esc(p.to_clock || '—')}</span></div>
    <div class="pd-stats">${stat('Requirement', nsOf(p.requirement))}${stat('Data path', nsOf(p.data_delay))}${stat('Logic / route', split)}
      ${stat('Levels', `${p.levels ?? '—'}${cells ? ` <small>${cells}</small>` : ''}`)}${stat('Clock skew', nsOf(p.skew))}${stat('Uncertainty', nsOf(p.uncertainty))}</div>`;
}
function pathBar(steps, total) {
  const segs = steps.map((s, i) => (s.incr == null || s.incr <= 0 ? '' : `<i class="seg ${s.kind === 'net' ? 'net' : 'cell'}" style="flex:${Math.round(s.incr * 1000)} 1 0" data-s="${i}" tabindex="0" title="${esc(s.kind === 'net' ? `net · fo ${s.fanout}` : s.cell)} · ${s.incr.toFixed(3)} ns (${(100 * s.incr / total).toFixed(1)}%)"></i>`)).join('');
  return `<div class="pbar" role="group" aria-label="Where the data path delay goes"><div class="pbar-t">${segs}</div>
    <div class="pbar-l"><span><i class="sw cell"></i>cells</span><span><i class="sw net"></i>nets</span><span class="num">${total.toFixed(3)} ns</span></div></div>`;
}
function pathChain(p) {
  const st = p.steps, big = st.reduce((m, s, i) => ((s.incr || 0) > (st[m].incr || 0) ? i : m), 0);
  const pre = commonPrefix(st.map(instOf)), skip = pre.length;
  const last = st.length - 1, cap = p.capture || {}, hold = p.type === 'hold';
  const clk = (c, at, what) => (c ? `<span class="pb-cap" title="${esc(c)}">${esc(what)} ${esc(c)} ${at == null ? '' : `@ ${at.toFixed(3)}`}</span>` : '');
  const block = (s, i) => {
    const inst = instOf(s), end = s.kind === 'endpoint';
    const pins = end ? `→ ${esc(s.pin)}` : s.from_pin ? `${esc(s.from_pin)}→${esc(s.to_pin)}` : '';
    const delay = end ? (cap.setup_or_hold ? `${hold ? 'hold' : 'setup'} ${cap.setup_or_hold.incr.toFixed(3)} ns` : '') : `${s.incr.toFixed(3)} ns`;
    const cp = i === 0 ? clk((p.launch || {}).clock, (p.launch || {}).at, 'launch') : end ? clk(cap.clock, cap.required, 'capture') : '';
    return `<div class="pb${end ? ' end' : ''}${i === big ? ' max' : ''}" data-s="${i}" title="${esc(`${s.name || ''}\n${s.arc || ''}${i === big ? '\nlargest delay on this path' : ''}`.trim())}">
      ${cp}<b class="pb-t">${esc(s.cell)}</b><span class="pb-p mono">${pins}</span><span class="pb-n mono">${esc(leafName(inst, skip))}</span>
      <span class="pb-s mono">${esc(s.site || '')}</span><span class="pb-d num">${delay}</span></div>`;
  };
  const link = (s, i) => `<div class="pl${i === big ? ' max' : ''}" data-s="${i}" title="${esc(`${s.name || ''}\n${s.routing || ''}${i === big ? '\nlargest delay on this path' : ''}`.trim())}">
      <span class="pl-d num">${s.incr.toFixed(3)} ns</span><span class="pl-a" aria-hidden="true"></span>
      <span class="pl-f${s.fanout >= 32 ? ' hi' : ''}">fo ${s.fanout}${s.routing && s.routing !== 'routed' ? ` · ${esc(s.routing)}` : ''}</span></div>`;
  let html = '';
  for (let i = 0; i < st.length; i++) {
    if (st[i].kind === 'net') html += `<div class="pu">${link(st[i], i)}${st[i + 1] ? block(st[i + 1], i + 1) : ''}</div>`;
    else if (i === 0 || st[i - 1].kind !== 'net') html += `<div class="pu">${block(st[i], i)}</div>`;
  }
  return `<div class="pchain-w">${pre.length ? `<div class="pchain-p">in <code>${esc(pre.join('/'))}/</code></div>` : ''}<div class="pchain">${html}</div>${p.truncated ? `<div class="pchain-p">Path truncated after ${st.length} elements.</div>` : ''}</div>`;
}
function clockTable(p, s) {
  const c = p.capture, l = p.launch;
  if (!c) return '';
  const open = s.clk.has(p.id), hold = p.type === 'hold';
  const row = (k, v, extra = '') => (v == null ? '' : `<tr><th>${k}</th><td class="num">${v}</td><td class="mono">${extra}</td></tr>`);
  const n = (v) => (v == null ? null : v.toFixed(3));
  const edge = (x) => (x && x.clock ? `${esc(x.clock)} ${x.edge === 'fall' ? 'fall' : 'rise'}` : '');
  const check = c.setup_or_hold, cons = c.constraint;
  return `<div class="pclk"><button class="rchip pf${open ? ' on' : ''}" data-act="pth-clk" data-key="${esc(s.key)}" data-i="${p.id}" aria-expanded="${open}">Clock &amp; required</button>
    ${open ? `<table class="hist pclk-t"><tbody>${row('Source clock arrival', n(l && l.at), edge(l))}${row('Destination clock arrival', n(c.at), edge(c))}
      ${cons ? row(esc(cons.kind), n(cons.value), 'datapath only') : ''}${row('Clock pessimism', n(c.pessimism))}${row('Clock uncertainty', n(c.uncertainty))}
      ${check ? row(`${hold ? 'Hold' : 'Setup'} time`, n(check.incr), `${esc(check.cell)} ${esc(check.arc || '')}`) : ''}
      ${row('Required time', n(c.required == null ? null : Math.abs(c.required)))}${row('Arrival time', n(c.arrival == null ? null : Math.abs(c.arrival)))}${row('Slack', n(c.slack))}</tbody></table>` : ''}</div>`;
}
function pathDetail(p, s) {
  if (!p.steps || !p.steps.length) return `<div class="pd">${pathHead(p)}<div class="none">Path elements are not available for this report.</div></div>`;
  const total = p.steps.reduce((a, x) => a + (x.incr > 0 ? x.incr : 0), 0) || 1;
  return `<div class="pd">${pathHead(p)}${pathBar(p.steps, total)}${pathChain(p)}${clockTable(p, s)}</div>`;
}
// highlight the matching bar segment / block while one of them is hovered or focused
function pathHover(ev, on) {
  const t = ev.target.closest && ev.target.closest('.pd [data-s]');
  if (t) for (const e of t.closest('.pd').querySelectorAll(`[data-s="${t.dataset.s}"]`)) e.classList.toggle('hl', on);
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
      <td>${splitBar(p)}</td><td class="num sk">${p.skew == null ? '—' : p.skew.toFixed(3)}</td></tr>${open ? `<tr class="pdrow"><td colspan="7">${pathDetail(p, s)}</td></tr>` : ''}`;
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

// ---- congestion (place_design / route_design)
const CG_DIRS = ['north', 'south', 'east', 'west'];
const CG_SCALE = 8;                                             // bar full at level 8 (256x256 regions)
const cgCls = (v, cg) => (v >= cg.crit_level ? 'crit' : v >= cg.warn_level ? 'warn' : '');
function congChip(cg) {
  if (!cg || cg.level === 'ok') return '';
  return `<span class="chip ${cg.level === 'crit' ? 'cgcrit' : 'softbad'}" title="Congestion level ${cg.max_level} (warn from ${cg.warn_level}, high from ${cg.crit_level}). Levels of 5 and greater may impact timing closure.">CONG L${cg.max_level}</span>`;
}
function cgBar(v, cg, pct) {
  if (v == null) return '<span class="cg-cell nil">—</span>';
  return `<span class="cg-cell"><span class="cg-bar ${cgCls(v, cg)}"><i style="width:${Math.min(100, (v / CG_SCALE) * 100)}%"></i></span><span class="cg-txt"><b class="num">${v}</b>${pct != null ? `<small class="num">${pct}%</small>` : ''}</span></span>`;
}
function cgTable(title, note, rows, cg, withPct) {
  const heads = ['Global', 'Long', 'Short'].map((t) => `<span class="cg-h">${t}</span>`).join('');
  const body = CG_DIRS.filter((d) => rows[d]).map((d) => `<span class="cg-d">${d[0].toUpperCase() + d.slice(1)}</span>${['global', 'long', 'short'].map((k) => cgBar(rows[d][k], cg, withPct ? rows[d][k + '_pct'] : null)).join('')}`).join('');
  return `<div class="cg-sec"><div class="cg-title">${title}<small>${note}</small></div><div class="cg-grid"><span></span>${heads}${body}</div></div>`;
}
function cgFinal(rows, cg) {
  const body = CG_DIRS.filter((d) => rows[d]).map((d) => {
    const r = rows[d];
    return `<span class="cg-d">${d[0].toUpperCase() + d.slice(1)}</span><b class="num cg-pct">${r.max_pct.toFixed(1)}%</b>${cgBar(r.level, cg)}<small class="cg-reg">${r.congested ? 'regions' : 'none'}</small>`;
  }).join('');
  return `<div class="cg-sec"><div class="cg-title">Final routing<small>max congestion, effective level, congested regions</small></div><div class="cg-grid fin">${body}</div></div>`;
}
function renderCongestion(pane, n) {
  const cg = n.congestion;
  if (!cg) { setHTML(pane, '<div class="none">No congestion table seen yet.</div>'); return; }
  const lv = cg.level === 'ok' ? '' : cg.level;
  const advice = lv ? `Level ${cg.warn_level} or more may impact timing closure: look at the placement and the congested regions if timing fails.` : 'Below the level where Vivado warns about timing closure.';
  const hit = convOf(n);
  const spark = hit ? overlapSpark(hit.conv, 160, 34) : '';
  setHTML(pane, `<div class="cg-top"><span class="cg-lvl ${lv}">LEVEL ${cg.max_level}</span><span class="cg-note">${advice}</span></div>
    ${cg.placer ? cgTable('Placement estimate', 'region size as level (2^level tiles)', cg.placer, cg, false) : ''}
    ${cg.router_initial ? cgTable('Router initial estimate', 'level and % of tiles', cg.router_initial, cg, true) : ''}
    ${cg.router_final ? cgFinal(cg.router_final, cg) : ''}
    ${spark ? `<div class="cg-sec"><div class="cg-title">Router overlaps<small>per pass, log scale (see Convergence)</small></div><span class="cvchip">${spark}</span></div>` : ''}`);
}

/* ------------------------------------------------------------------ build history page (GET /api/history) */
const hist = { on: false, fw: null, fwName: null, asc: false, done: lsGet('vmon.histDone') === '1', pick: [], cmpTab: 'new', cmpHash: null, hintFor: null, latestOf: null, mockCmp: null, data: null, error: null, sig: null, reqId: 0, root: $('#history'), mock: null };
const HX_KIND = { timing_summary: 'Timing', utilization: 'Util', drc: 'DRC', methodology: 'Method', power: 'Power', route_status: 'Route', clock_utilization: 'Clocks', control_sets: 'Ctrl sets' };
const HX_RESULT = {
  met: { key: 'done', text: 'Finished, timing met' }, timing_not_met: { key: 'done-fail', text: 'Finished, timing not met' },
  failed: { key: 'failed', text: 'Failed' }, stopped: { key: 'stopped', text: 'Stopped' }, done: { key: 'idle', text: 'Finished' },
};
const HX_ICON = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 3.5v-.5a1 1 0 0 0-1-1h-6.5a1 1 0 0 0-1 1v6.5a1 1 0 0 0 1 1h.5"/></svg>';
const HX_UNFINISHED = new Set(['failed', 'stopped']);
const HX_FINISHED = new Set(['done', 'failed', 'stopped']);
const CMP_REFRESH_MS = 5000;
const HX_GONE = 'Replaced by a later build';

function setHistory(on) {
  if (on === hist.on) return;
  hist.on = on;
  if (on) { hist.fw = null; hist.sig = null; hist.pick = []; hist.hintFor = null; hist.latestOf = null; window.scrollTo(0, 0); }
  render();
  if (on) { const b = $('select', hist.root) || $('#history-btn'); if (b) b.focus(); }
}

// Returns true when the history page owns the content area (render() then skips the firmware view).
function syncHistoryPage() {
  const cmp = shownCmpTab();
  document.body.dataset.page = hist.on || cmp ? 'history' : '';
  const btn = $('#history-btn'); setAttr(btn, 'aria-pressed', String(hist.on));
  mainEl.hidden = hist.on || !!cmp; hist.root.hidden = !(hist.on || cmp);
  if (cmp) {
    if (!cmp.data && !cmp.error && !cmp.busy) loadCmp(cmp);
    renderCompare(cmp);
    return true;
  }
  if (!hist.on) return false;
  if (hist.fw === null) {
    const named = hist.fwName && state.firmwares.find((f) => f.name === hist.fwName || f.id === hist.fwName);
    hist.fw = named ? named.id : (hist.fwName === 'all' ? '' : selected || '');
  }
  const sig = state.firmwares.map((f) => `${f.id}:${f.status}`).join('|') + `#${hist.fw}`;
  if (sig !== hist.sig) { hist.sig = sig; loadHistory(); }
  renderHistory();
  return true;
}

async function loadHistory() {
  const id = ++hist.reqId, fwId = hist.fw;
  try {
    let d;
    if (MOCK) {
      mockHistory();
      d = { firmwares: hist.mock.firmwares, builds: hist.mock.builds.filter((b) => !fwId || b.fw_id === fwId) };
    } else d = await jget(`/api/history${fwId ? `?fw=${q(fwId)}` : ''}`);
    if (id !== hist.reqId) return;
    hist.data = d; hist.error = null;
    const listed = [...liveRows(), ...d.builds];             // picks survive a filter change while still listed
    hist.pick = hist.pick.filter((p) => listed.some((b) => hxSame(p, b)));
    if (hist.hintFor && !hist.pick.some((p) => hxSame(p, { fw_id: hist.hintFor.key.fw, build: hist.hintFor.key.build }))) hist.hintFor = null;
    if (hist.latestOf) {
      const latest = d.builds.filter((b) => b.fw_id === hist.latestOf).sort(hxOlderFirst).pop();
      hist.pick = latest ? [{ fw: latest.fw_id, build: latest.build }] : [];
      if (latest) hist.hintFor = { key: hist.pick[0], text: `${latest.firmware} (latest build)` };
      hist.latestOf = null;
    }
    if (hist.cmpHash) resolveHashCompare();
  } catch (e) { if (id !== hist.reqId) return; hist.error = String(e.message || e); }
  if (hist.on) renderHistory();
}

const fmtWhen = (t) => { if (t == null) return '—'; const d = new Date(t * 1000); return `${d.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' })} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })}`; };

function hxTiming(b) {
  const t = b.timing;
  if (!t || (t.wns == null && t.whs == null)) return '<span class="dim">—</span>';
  const cell = (k, v) => `<div title="${t.final ? 'Final result' : 'Not a final result'}"><i>${k}</i><span${t.final && v != null && v < 0 ? ' class="neg"' : ''}>${fmtSlack(v)}</span></div>`;
  return cell('WNS', t.wns) + cell('WHS', t.whs);
}
function hxUtil(b) {
  const u = b.utilization;
  if (!u) return '<span class="dim">—</span>';
  const rows = ['LUT', 'FF', 'BRAM', 'DSP'].filter((k) => u[k]);
  const worst = rows.reduce((w, k) => (w == null || u[k].pct > u[w].pct ? k : w), null);
  return rows.map((k) => {
    const p = u[k].pct, cls = k === worst && p >= 80 ? (p >= 90 ? ' class="u-crit"' : ' class="u-warn"') : '';
    return `<span title="${esc(k)}: ${fmtInt(u[k].used)} of ${fmtInt(u[k].available)}"><i>${k}</i><b${cls}>${p == null ? '—' : p.toFixed(p < 10 ? 1 : 0)}%</b></span>`;
  }).join('') || '<span class="dim">—</span>';
}
function hxLinks(b) {
  const art = b.artifacts || [];
  const at = (a) => `data-fw="${esc(b.fw_id)}" data-build="${esc(b.build)}" data-path="${esc(a.path)}"`;
  const reports = art.filter((a) => a.kind !== 'bitstream').map((a) => {
    const name = HX_KIND[a.kind] || a.label;
    const tip = a.current ? `Open ${a.label}${a.step ? ` (${a.step})` : ''}` : `${HX_GONE}: ${a.label}`;
    return `<button type="button" class="hx-chip" data-act="hrep" ${at(a)} data-label="${esc(a.label)}" title="${esc(tip)}"${a.current ? '' : ' aria-disabled="true"'}>${esc(name)}</button>`;
  }).join('');
  const bit = art.find((a) => a.kind === 'bitstream');
  let bitHTML = '';
  if (bit) {
    const href = `/api/history/artifact?fw=${q(b.fw_id)}&build=${q(b.build)}&path=${q(bit.path)}`;
    bitHTML = bit.current
      ? `<span class="hx-bitgrp"><a class="hx-chip bit" data-act="hbit" href="${esc(href)}" download title="Download ${esc(bit.path)} (${fmtMem(bit.size / 1048576)})">.bit</a><button type="button" class="hx-chip" data-act="copy" data-copy="${esc(bit.path)}" title="Copy the bitstream path" aria-label="Copy the bitstream path">${HX_ICON}</button></span>`
      : `<span class="hx-chip bit" data-act="hbit" aria-disabled="true" title="${HX_GONE}">.bit</span>`;
  } else bitHTML = '<span class="hx-chip bit" data-act="hbit" aria-disabled="true" title="No bitstream was recorded for this build">.bit</span>';
  return `<div class="links">${reports || '<span class="dim">no reports</span>'}<span class="hx-bit"><span class="hx-sep"></span>${bitHTML}</span></div>`;
}
// Summary export: MD downloads, HTML opens printable in a tab, the clipboard button copies the Markdown.
const summaryUrl = (fw, build, fmt, dl) => `/api/history/summary?fw=${q(fw)}&build=${q(build)}&format=${fmt}${dl ? '&download=1' : ''}`;
function hxExport(b) {
  const ds = `data-fw="${esc(b.fw_id)}" data-build="${esc(b.build)}"`;
  return `<div class="hx-exp" role="group" aria-label="Export build summary"><span class="dim">Summary</span>
    <a class="hx-chip" data-act="hexp" data-format="md" ${ds} href="${esc(summaryUrl(b.fw_id, b.build, 'md', true))}" download title="Download the Markdown summary of this build">MD</a>
    <a class="hx-chip" data-act="hexp" data-format="html" ${ds} href="${esc(summaryUrl(b.fw_id, b.build, 'html', false))}" target="_blank" rel="noopener" title="Open the printable HTML summary in a new tab">HTML</a>
    <button type="button" class="hx-chip" data-act="hexp-copy" ${ds} title="Copy the Markdown summary" aria-label="Copy the Markdown summary">${HX_ICON}Copy</button></div>`;
}
const MOCK_SUMMARY_FALLBACK = 'tp02_1759982000';
function mockSummaryUrl(fw, build, fmt) {
  const x = new XMLHttpRequest(), key = `${fw}_${build}`;
  x.open('GET', `mock/summary_${key}.${fmt}`, false); x.send();
  return `mock/summary_${x.status === 200 ? key : MOCK_SUMMARY_FALLBACK}.${fmt}`;
}
async function summaryText(fw, build) {
  const r = await fetch(MOCK ? mockSummaryUrl(fw, build, 'md') : summaryUrl(fw, build, 'md', false), { cache: 'no-store' });
  if (!r.ok) throw new Error('no recorded build to summarise');
  return r.text();
}
function saveBlob(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
async function exportMarkdown(fw, build) {
  try {
    const r = await fetch(MOCK ? mockSummaryUrl(fw, build, 'md') : summaryUrl(fw, build, 'md', true), { cache: 'no-store' });
    if (!r.ok) throw new Error('no recorded build to summarise yet');
    const name = ((r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/) || [])[1] || `${fw}_${build}_summary.md`;
    saveBlob(await r.blob(), name);
    toast(`Saved ${name}`);
  } catch (e) { toast(`Could not export the summary: ${e.message}`); }
}
// Unfinished firmwares as pinned "Live" rows: the same shape as a recorded build, built from the loaded state.
function liveRows() {
  if (hist.done) return [];
  return state.firmwares.filter((f) => !HX_FINISHED.has(f.status) && (!hist.fw || f.id === hist.fw)).map((f) => ({
    fw_id: f.id, build: 'live', live: { status: f.status }, firmware: f.name, host: f.host, project: f.path, started_at: f.started_at, duration_s: f.elapsed_s,
    part: (f.info || {}).part, strategy_impl: (f.info || {}).strategy_impl,
    timing: f.timing ? { wns: f.timing.wns, whs: f.timing.whs, final: false } : null,
    utilization: f.utilization ? Object.fromEntries(f.utilization.rows.filter((r) => ['LUT', 'FF', 'BRAM', 'DSP'].includes(r.name)).map((r) => [r.name, r])) : null,
  }));
}
function hxRow(b, loaded, hasPrev) {
  const res = b.live ? { key: b.live.status, text: statusInfo(b.live.status).label } : HX_RESULT[b.result] || HX_RESULT.done;
  const why = b.failure && b.failure.reason ? `${b.failure.step ? `${b.failure.step}: ` : ''}${b.failure.reason}` : '';
  const where = [b.part, b.strategy_impl].filter(Boolean).join(' · ');
  const tip = `Open ${b.firmware} in the standard view${loaded ? '' : ' (loads the project again)'}; it shows the project's latest build`;
  const ds = `data-fw="${esc(b.fw_id)}" data-project="${esc(b.project || '')}" data-name="${esc(b.firmware)}"`;
  const picked = hist.pick.some((p) => hxSame(p, b));
  const ck = `<input type="checkbox" data-act="hpick" data-fw="${esc(b.fw_id)}" data-build="${esc(b.build)}"${picked ? ' checked' : ''} aria-label="Select the ${esc(b.firmware)} build of ${esc(fmtWhen(b.started_at))} to compare">`;
  const prev = hasPrev ? `<button type="button" class="hx-chip hx-prev" data-act="hprev" data-fw="${esc(b.fw_id)}" data-build="${esc(b.build)}" title="Compare with the previous ${esc(b.firmware)} build">vs previous</button>` : '';
  const liveTag = b.live ? '<span class="livebadge" title="Current state of a build that has not finished: numbers are provisional">live</span>' : '';
  return `<tr class="go${picked ? ' picked' : ''}${b.live ? ' live' : ''}" data-act="hrow" ${ds} title="${esc(tip)}">
    <td class="pick" data-label="Compare">${ck}</td>
    <td class="when" data-label="Date">${fmtWhen(b.started_at)}${prev}</td>
    <td class="fw" data-label="Firmware"><button type="button" class="fwn hx-open" data-act="hopen" ${ds} title="${esc(tip)}">${esc(b.firmware)} <span aria-hidden="true">›</span></button>${liveTag}${b.host ? `<span class="hbadge" title="Built on ${esc(b.host)}">${esc(b.host)}</span>` : ''}${where ? `<span class="sub" title="${esc(where)}${b.vivado_version ? ` · Vivado ${esc(b.vivado_version)}` : ''}">${esc(where)}</span>` : ''}${b.project ? `<span class="sub path" title="${esc(b.project)}"><bdi>${esc(b.project)}</bdi></span>` : ''}</td>
    <td class="dur" data-label="Duration">${fmtDur(b.duration_s)}</td>
    <td class="res" data-label="Result"><span class="pill" data-status="${res.key}">${res.text}</span>${why ? `<span class="sub" title="${esc(why)}">${esc(why)}</span>` : ''}</td>
    <td class="tm" data-label="WNS / WHS">${hxTiming(b)}</td>
    <td class="ut" data-label="Utilization">${hxUtil(b)}</td>
    <td class="links-c" data-label="Reports">${b.live ? '<span class="dim">after it finishes</span>' : hxLinks(b) + hxExport(b)}</td></tr>`;
}

function renderHistory() {
  const d = hist.data;
  if (!d && !hist.error) { setHTML(hist.root, '<div class="hx-empty">Loading…</div>'); return; }
  const fws = [...(d ? d.firmwares : [])];
  for (const f of state.firmwares) if (!fws.some((x) => x.id === f.id)) fws.push({ id: f.id, name: f.name, host: f.host });
  const opts = `<option value=""${hist.fw ? '' : ' selected'}>All firmwares</option>` + fws.map((f) => `<option value="${esc(f.id)}"${f.id === hist.fw ? ' selected' : ''}>${esc(fwLabel(f))}</option>`).join('');
  const recorded = d ? d.builds.filter((b) => !hist.done || !HX_UNFINISHED.has(b.result)).sort((a, b) => (hist.asc ? 1 : -1) * ((a.started_at || 0) - (b.started_at || 0))) : [];
  const builds = [...(d ? liveRows() : []), ...recorded];
  const loaded = new Set(state.firmwares.map((f) => f.id));
  const arrow = hist.asc ? '↑' : '↓';
  let body;
  if (hist.error) body = `<div class="hx-empty">Could not load the history (${esc(hist.error)}).</div>`;
  else if (!builds.length && d.builds.length) body = '<div class="hx-empty">Every recorded build failed or was stopped. Untick Finished only to see them.</div>';
  else if (!builds.length) body = '<div class="hx-empty">No finished builds recorded yet. Builds are recorded when they finish.</div>';
  else body = `<table class="hx"><thead><tr><th class="pick"><span class="sr">Compare</span></th><th aria-sort="${hist.asc ? 'ascending' : 'descending'}"><button type="button" data-act="hsort" title="Sort by date">Date <span aria-hidden="true">${arrow}</span></button></th><th>Firmware</th><th>Duration</th><th>Result</th><th>WNS / WHS</th><th>Utilization</th><th>Reports</th></tr></thead><tbody>${builds.map((b) => hxRow(b, loaded.has(b.fw_id), !!previousOf(b))).join('')}</tbody></table>`;
  const focusId = document.activeElement && hist.root.contains(document.activeElement) && ['hx-fw', 'hx-done'].includes(document.activeElement.id) ? document.activeElement.id : null;
  const n = hist.pick.length;
  const hf = hist.hintFor;
  const hint = n === 0 ? 'Tick any two builds to compare them' : n === 1 ? (hf && hxSame(hist.pick[0], { fw_id: hf.key.fw, build: hf.key.build }) ? `Pick a build to compare with ${hf.text}` : 'Pick one more build') : '2 builds selected';
  const act = document.activeElement, keep = act && hist.root.contains(act) && act.dataset.act && act.dataset.build ? `[data-act="${act.dataset.act}"][data-build="${act.dataset.build}"][data-fw="${act.dataset.fw}"]` : null;
  setHTML(hist.root, `<div class="hx-head"><h1>Build history</h1><span class="hx-n">${builds.length} build${builds.length === 1 ? '' : 's'}</span>
    <div class="hx-tools"><span class="hx-hint" aria-live="polite">${hint}</span>${n ? '<button type="button" class="hx-back" data-act="hclear">Clear</button>' : ''}<button type="button" class="hx-go" data-act="hcompare"${n === 2 ? '' : ' disabled'} title="Compare the two selected builds">Compare</button><label class="hx-sel">Firmware <select id="hx-fw" aria-label="Filter by firmware">${opts}</select></label><label class="hx-sel hx-chk" title="Hide failed and stopped builds"><input type="checkbox" role="switch" id="hx-done"${hist.done ? ' checked' : ''}> Finished only</label><button type="button" class="hx-back" data-act="history-close" title="Back to the firmware (Esc)">Back</button></div></div>
    ${d && d.unreachable && d.unreachable.length ? `<div class="hx-note">Not included: ${esc(d.unreachable.join(', '))} unreachable</div>` : ''}<div class="hx-wrap">${body}</div>`);
  if (focusId) $('#' + focusId, hist.root).focus();
  else if (keep) { const k = $(keep, hist.root); if (k) k.focus(); }
}
hist.root.addEventListener('change', (ev) => {
  if (ev.target.id === 'hx-done') {
    hist.done = ev.target.checked; lsSet('vmon.histDone', hist.done ? '1' : '0');
    const shown = new Set(hist.data ? hist.data.builds.filter((b) => !hist.done || !HX_UNFINISHED.has(b.result)).map((b) => `${b.fw_id}|${b.build}`) : []);
    hist.pick = hist.pick.filter((p) => (p.build === 'live' ? !hist.done : shown.has(`${p.fw}|${p.build}`)));
    renderHistory();
    return;
  }
  if (ev.target.id !== 'hx-fw') return;
  hist.fw = ev.target.value; hist.sig = null; hist.data = null; render();
});

// Mock history and its precomputed diffs share one time offset (shifting also moves generated_at, so compute it once).
function mockHistory() {
  if (hist.mock) return;
  hist.mock = syncJson('mock/history.json'); hist.mockShift = nowS() - hist.mock.generated_at; shiftTimes(hist.mock, hist.mockShift);
}
/* ---- compare two builds, of one firmware or two (GET /api/history/compare; mock: mock/compare.json) */
const hxSame = (p, b) => p.fw === b.fw_id && p.build === b.build;
// A live build is always the newest.
const hxAge = (b) => (b.live ? Infinity : b.started_at || 0);
const hxOlderFirst = (x, y) => (hxAge(x) === hxAge(y) ? 0 : hxAge(x) < hxAge(y) ? -1 : 1);

const HX_HEAD_KEYS = ['build', 'fw_id', 'firmware', 'project', 'started_at', 'ended_at', 'duration_s', 'result', 'part', 'strategy_impl', 'vivado_version', 'counts'];
// Mock: header of a firmware's current state, as the server's live record would give it.
function mockLiveHead(fwId) {
  const f = state.firmwares.find((x) => x.id === fwId);
  if (!f) return null;
  return { build: 'live', fw_id: f.id, firmware: f.name, project: f.path, started_at: f.started_at, ended_at: null, duration_s: f.elapsed_s, result: 'done', part: (f.info || {}).part,
    strategy_impl: (f.info || {}).strategy_impl, vivado_version: f.vivado_version, counts: [f.counts.error, f.counts.critical, f.counts.warning, f.counts.info], live: { status: f.status, as_of: nowS() } };
}
// Mock: same-firmware diffs are precomputed; a cross-firmware or live pick reuses one of them under the picked builds' headers.
function mockCrossCompare(fw, a, fwB, b) {
  const builds = hist.mock.builds, head = (fwId, id) => {
    if (id === 'live') return mockLiveHead(fwId);
    const r = builds.find((x) => x.fw_id === fwId && x.build === id);
    return r && Object.fromEntries(HX_HEAD_KEYS.map((k) => [k, r[k]]));
  };
  const ha = head(fw, a), hb = head(fwB, b), base = hist.mockCmp['tp02|1759640000|1759982000']; // the one with timing on both sides
  if (!ha || !hb) return null;
  return { ...base, fw_id: fwB, firmware: hb.firmware, a: ha, b: hb, duration: { a: ha.duration_s, b: hb.duration_s, delta: hb.duration_s - ha.duration_s } };
}
/* ---- comparison tabs: one per open pair, kept after the firmware tabs and in localStorage */
const cmpKey = (fwA, a, fwB, b) => `cmp:${fwA}:${a},${fwB}:${b}`;
const shownCmpTab = () => (hist.on ? null : ctabs.find((t) => t.key === selectedCmp) || null); // the History page covers it
const cmpHasLive = (t) => t.a === 'live' || t.b === 'live';
function selectCmp(key) { selectedCmp = key; lsSet('vmon.cmp', key || ''); }
function persistCmp() {
  lsSet('vmon.cmptabs', JSON.stringify(ctabs.map(({ fwA, a, fwB, b, label, title, tab }) => ({ fwA, a, fwB, b, label, title, tab }))));
}
// Same firmware: "top · <date A> ↔ <date B>". Two projects: their names, or, when the names are equal, the first folder
// where their paths part ways (".../mux/top/top.runs" vs ".../mux/top_backup/top.runs" -> "top ↔ top_backup").
function divergingDirs(pa, pb) {
  const parts = (p) => String(p || '').split(/[\\/]/).filter(Boolean);
  const a = parts(pa), b = parts(pb);
  let i = 0;
  while (i < a.length - 1 && i < b.length - 1 && a[i] === b[i]) i++;
  return [a.length - 1 > i ? a[i] : null, b.length - 1 > i ? b[i] : null];
}
function cmpNames(ha, hb) {
  const [da, db] = divergingDirs(ha.project, hb.project);
  const when = (h) => (h.live ? 'live' : fmtClock(h.started_at));
  const side = (role, h) => `${role} · ${h.firmware}${h.live ? ' (live)' : ` · ${fmtWhen(h.started_at)}`}${h.project ? ` · ${h.project}` : ''}`;
  const label = ha.fw_id === hb.fw_id ? `${hb.firmware} · ${when(ha)} ↔ ${when(hb)}`
    : ha.firmware !== hb.firmware || !da || !db ? `${ha.firmware} ↔ ${hb.firmware}` : `${da} ↔ ${db}`;
  return { label, title: `${side('A', ha)}\n${side('B', hb)}` };
}
function addCmpTab(fwA, a, fwB, b, heads) {
  const key = cmpKey(fwA, a, fwB, b);
  let t = ctabs.find((x) => x.key === key);
  if (!t) {
    const name = (id) => (state.firmwares.find((f) => f.id === id) || {}).name || id;
    const nm = heads ? cmpNames(heads[0], heads[1]) : { label: `${name(fwA)} ↔ ${name(fwB)}`, title: `A · ${name(fwA)} · ${a}\nB · ${name(fwB)} · ${b}` };
    t = { cmp: true, key, fwA, a, fwB, b, ...nm, tab: hist.cmpTab, data: null, error: null, busy: false };
    ctabs.push(t);
    persistCmp();
  }
  return t;
}
function restoreCmpTabs() {
  let saved = [];
  try { saved = JSON.parse(lsGet('vmon.cmptabs') || '[]'); } catch { /* ignore */ }
  for (const s of Array.isArray(saved) ? saved : []) {
    if (![s.fwA, s.a, s.fwB, s.b].every((v) => typeof v === 'string' && v)) continue;
    const t = addCmpTab(s.fwA, s.a, s.fwB, s.b);
    if (typeof s.label === 'string') { t.label = s.label; t.title = String(s.title || s.label); }
    if (CMP_MSG_TABS.some(([k]) => k === s.tab)) t.tab = s.tab;
  }
  const sel = lsGet('vmon.cmp');
  selectedCmp = ctabs.some((t) => t.key === sel) ? sel : null;
}
function openCompare(fw, a, b, fwB = fw, heads) {
  const t = addCmpTab(fw, a, fwB, b, heads);
  hist.on = false; hist.pick = []; hist.hintFor = null;
  selectCmp(t.key); window.scrollTo(0, 0); render();
}
function closeCmp(key) {
  const i = ctabs.findIndex((t) => t.key === key);
  if (i < 0) return;
  ctabs.splice(i, 1);
  if (selectedCmp === key) selectCmp(null);
  persistCmp(); render();
}
// A live side is re-fetched while its tab is visible; a refresh that fails keeps the numbers already shown.
async function loadCmp(t, silent = false) {
  t.busy = true;
  try {
    if (MOCK) {
      mockHistory();
      hist.mockCmp = hist.mockCmp || shiftTimes(syncJson('mock/compare.json'), hist.mockShift);
      t.data = t.fwA === t.fwB && !cmpHasLive(t) ? hist.mockCmp[`${t.fwA}|${t.a}|${t.b}`] : mockCrossCompare(t.fwA, t.a, t.fwB, t.b);
      if (!t.data) throw new Error('no mock comparison for these builds');
    } else t.data = await jget(`/api/history/compare?fw=${q(t.fwA)}&a=${q(t.a)}&b=${q(t.b)}${t.fwA === t.fwB ? '' : `&fw_b=${q(t.fwB)}`}`);
    t.error = null;
    Object.assign(t, cmpNames(t.data.a, t.data.b));
    persistCmp();
  } catch (e) { if (!silent || !t.data) t.error = String(e.message || e); }
  t.busy = false;
  if (ctabs.includes(t)) render();
}
setInterval(() => {
  const t = shownCmpTab();
  if (t && cmpHasLive(t) && !t.busy && !document.hidden) loadCmp(t, true);
}, CMP_REFRESH_MS);
// Opens History with this firmware's live row (or, once finished, its latest recorded build) ticked, to pick the other side.
// Unfiltered: the other side is often another firmware id (the same project copied to another folder).
function openHistoryFor(fw) {
  const live = !HX_FINISHED.has(fw.status);
  Object.assign(hist, { on: true, fw: '', sig: null, data: null, pick: live ? [{ fw: fw.id, build: 'live' }] : [], latestOf: live ? null : fw.id,
    hintFor: live ? { key: { fw: fw.id, build: 'live' }, text: `${fw.name} (live)` } : null });
  window.scrollTo(0, 0); render();
}
// hcmp=<fwA>:<buildA>,<fwB>:<buildB> (any two firmwares); the older hcmp=<buildA>,<buildB> resolves to the first firmware that has both.
function resolveHashCompare() {
  const keys = hist.cmpHash || [], d = hist.data;
  hist.cmpHash = null;
  if (keys.length !== 2 || !d) return;
  if (keys.every((k) => k.includes(':'))) { startCompare(keys.map((k) => ({ fw: k.slice(0, k.indexOf(':')), build: k.slice(k.indexOf(':') + 1) }))); return; }
  const first = d.builds.find((x) => x.build === keys[0] && d.builds.some((y) => y.fw_id === x.fw_id && y.build === keys[1]));
  if (first) startCompare(keys.map((build) => ({ fw: first.fw_id, build })));
}
function startCompare(pairs) {
  const all = [...liveRows(), ...hist.data.builds];
  const two = pairs.map((p) => all.find((b) => hxSame(p, b))).filter(Boolean).sort(hxOlderFirst);
  if (two.length === 2) openCompare(two[0].fw_id, two[0].build, two[1].build, two[1].fw_id, two);
}
function previousOf(b) {
  const older = hist.data.builds.filter((x) => x.fw_id === b.fw_id && hxOlderFirst(x, b) < 0).sort(hxOlderFirst);
  return older[older.length - 1] || null;
}
function hxPick(ev, t) {
  const key = { fw: t.dataset.fw, build: t.dataset.build };
  const i = hist.pick.findIndex((p) => p.fw === key.fw && p.build === key.build);
  if (i >= 0) hist.pick.splice(i, 1);
  else if (hist.pick.length >= 2) { ev.preventDefault(); toast('Pick at most two builds. Untick one first.'); return; }
  else hist.pick.push(key);
  renderHistory();
}

const fmtSigned = (v, digits, unit = '') => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}${unit}`);
const fmtDurDelta = (v) => (v == null ? '—' : v === 0 ? '0s' : `${v > 0 ? '+' : '−'}${fmtDur(Math.abs(v))}`);
// Never Cry Wolf: a regression is amber; red only when the newer build's final timing is actually failing.
function deltaClass(delta, bValue, bFinal) {
  if (delta == null || delta === 0) return 'dz';
  if (delta > 0) return 'dg';
  return bFinal && bValue != null && bValue < 0 ? 'dr' : 'da';
}
const hxNum = (v, fmt) => (v == null ? '<span class="nil">—</span>' : fmt(v));

function cmpHeadCard(role, h, showFw) {
  const live = h.live && !HX_FINISHED.has(h.live.status) ? h.live : null;
  const res = live ? { key: live.status, text: statusInfo(live.status).label } : HX_RESULT[h.result] || HX_RESULT.done;
  const where = [h.part, h.strategy_impl].filter(Boolean).join(' · ');
  const name = state.firmwares.some((f) => f.id === h.fw_id) ? `<button type="button" class="cmp-fwl" data-act="cmp-open-fw" data-fw="${esc(h.fw_id)}" title="Open ${esc(h.firmware)}">${esc(h.firmware)}</button>` : esc(h.firmware);
  const asOf = h.live ? `<div class="cmp-live"><span class="livebadge">live</span> ${live ? esc(live.status) : 'finished'} · as of ${new Date(h.live.as_of * 1000).toLocaleTimeString([], { hour12: false })}</div>` : '';
  return `<div class="cmp-b"><div class="cmp-role">${role}</div>${showFw && h.firmware ? `<div class="cmp-fw">${name}</div>` : ''}<div class="cmp-when">${fmtWhen(h.started_at)}</div>${asOf}
    <div class="cmp-meta"><span class="pill" data-status="${res.key}">${res.text}</span><span class="mono">${fmtDur(h.duration_s)}</span></div>${where ? `<div class="cmp-sub" title="${esc(where)}">${esc(where)}</div>` : ''}${h.project ? `<div class="cmp-sub mono" title="${esc(h.project)}"><bdi>${esc(h.project)}</bdi></div>` : ''}</div>`;
}
function cmpTiming(c) {
  const t = c.timing, fin = t.final.b;
  const row = ([k, label]) => {
    const m = t.metrics[k];
    const val = (v, final) => (v == null ? '<span class="nil">—</span>' : `<span${final && v < 0 ? ' class="neg"' : ''}>${fmtSlack(v)}</span>`);
    return `<tr><th scope="row">${label}</th><td class="num">${val(m.a, t.final.a)}</td><td class="num">${val(m.b, fin)}</td><td class="num ${deltaClass(m.delta, m.b, fin)}">${fmtSigned(m.delta, 3)}</td></tr>`;
  };
  const clocks = t.clocks && t.clocks.length ? `<details class="cmp-clk"><summary>Per clock (${t.clocks.length})</summary><div class="ptable-wrap"><table class="cmp-t"><thead><tr><th>Clock</th><th>WNS A</th><th>WNS B</th><th>Δ</th><th>WHS A</th><th>WHS B</th><th>Δ</th></tr></thead><tbody>${t.clocks.map((k) => `<tr><th scope="row" class="mono" title="${esc(k.name)}">${esc(k.name)}</th>${['wns', 'whs'].map((m) => `<td class="num">${hxNum(k[m].a, fmtSlack)}</td><td class="num">${hxNum(k[m].b, fmtSlack)}</td><td class="num ${deltaClass(k[m].delta, k[m].b, fin)}">${fmtSigned(k[m].delta, 3)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>` : '';
  const note = !t.final.a || !t.final.b ? `<p class="cmp-note">${!t.final.a && !t.final.b ? 'Neither build has a final timing result.' : `Build ${t.final.a ? 'B' : 'A'} has no final timing result; its numbers are estimates.`}</p>` : '';
  return `<section class="cmp-card" aria-label="Timing"><h2>Timing <small>ns</small></h2><table class="cmp-t"><thead><tr><th></th><th>A</th><th>B</th><th>Δ</th></tr></thead><tbody>${TIMING_FIELDS.map(row).join('')}</tbody></table>${note}${clocks}</section>`;
}
function cmpUtil(c) {
  const rows = Object.entries(c.utilization);
  const body = rows.map(([k, u]) => `<tr><th scope="row">${esc(k)}</th><td class="num">${hxNum(u.pct.a, (v) => v.toFixed(1) + '%')}</td><td class="num">${hxNum(u.pct.b, (v) => v.toFixed(1) + '%')}</td><td class="num dz">${fmtSigned(u.pct.delta, 1, ' pp')}</td><td class="num used" title="Used: ${fmtInt(u.used.a)} → ${fmtInt(u.used.b)} of ${fmtInt(u.available)}">${fmtInt(u.used.a)} → ${fmtInt(u.used.b)}</td></tr>`).join('');
  return `<section class="cmp-card" aria-label="Utilization"><h2>Utilization</h2>${rows.length ? `<table class="cmp-t"><thead><tr><th></th><th>A</th><th>B</th><th>Δ</th><th>Used</th></tr></thead><tbody>${body}</tbody></table>` : '<p class="cmp-empty">No utilization was recorded for these builds.</p>'}</section>`;
}
function cmpSteps(c) {
  const max = Math.max(1, ...c.steps.flatMap((s) => [s.a || 0, s.b || 0]));
  const bar = (v, cls) => `<span class="cmp-bar ${cls}" style="width:${v == null ? 0 : Math.max(1.5, v / max * 100)}%"></span>`;
  const rows = c.steps.map((s) => `<li class="cmp-step"><span class="sn mono">${esc(s.step)}</span><span class="sb" aria-hidden="true">${bar(s.a, 'ba')}${bar(s.b, 'bb')}</span><span class="num sv">${hxNum(s.a, fmtDur)}</span><span class="num sv">${hxNum(s.b, fmtDur)}</span><span class="num sd">${fmtDurDelta(s.delta)}</span></li>`).join('');
  return `<section class="cmp-card wide" aria-label="Step durations"><h2>Step durations <small>A grey, B blue</small></h2>${c.steps.length ? `<ul class="cmp-steps"><li class="cmp-step hd" aria-hidden="true"><span>Step</span><span></span><span>A</span><span>B</span><span>Δ</span></li>${rows}</ul>` : '<p class="cmp-empty">No step durations were recorded for these builds.</p>'}</section>`;
}
const CMP_MSG_TABS = [['new', 'New'], ['removed', 'Removed'], ['changed', 'Changed']];
const CMP_MSG_EMPTY = {
  new: 'No new warnings or errors in the newer build.', removed: 'No warnings or errors disappeared in the newer build.',
  changed: 'No message changed its count between the two builds.',
};
function cmpMessages(c, tab) {
  const m = c.messages;
  const totals = ['error', 'critical', 'warning'].map((k) => { const s = sevInfo(k), p = m.totals[k]; return `<span class="cmp-tot"><span class="badge ${s.cls}"><i>${s.short}</i>${p.a == null ? '—' : p.a} → ${p.b == null ? '—' : p.b}</span></span>`; }).join('');
  const tabs = CMP_MSG_TABS.map(([k, label]) => `<button type="button" class="cmp-tab" data-act="hcmptab" data-tab="${k}" aria-pressed="${tab === k}">${label} <span class="num">${m.counts[k]}</span></button>`).join('');
  const missing = ['a', 'b'].filter((s) => !m.available[s]);
  let body;
  if (missing.length) body = `<p class="cmp-empty">Message detail was not recorded for build ${missing.join(' and ')} (stored before comparisons existed), so the lists cannot be compared. The totals above still come from the saved counts.</p>`;
  else if (!m[tab].length) body = `<p class="cmp-empty">${CMP_MSG_EMPTY[tab]}</p>`;
  else {
    const more = m.counts[tab] > m[tab].length ? `<p class="cmp-note">Showing ${m[tab].length} of ${m.counts[tab]}.</p>` : '';
    const count = (e) => (tab === 'new' ? `×${fmtInt(e.b)}` : tab === 'removed' ? `×${fmtInt(e.a)}` : `${fmtInt(e.a)} → ${fmtInt(e.b)} <b class="${e.delta > 0 ? 'da' : 'dg'}">${fmtSigned(e.delta, 0)}</b>`);
    body = `<ul class="cmp-msgs">${m[tab].map((e) => `<li><span class="badge ${sevInfo(e.severity).cls}">${esc(sevInfo(e.severity).short)}</span><span class="mid mono">${esc(e.id)}</span><span class="mtx" title="${esc(e.text)}">${esc(e.text)}</span><span class="num mc">${count(e)}</span></li>`).join('')}</ul>${more}`;
  }
  return `<section class="cmp-card wide" aria-label="Messages"><h2>Messages <small>warnings and worse</small></h2><div class="cmp-tots">${totals}</div><div class="cmp-tabs" role="group" aria-label="Message changes">${tabs}</div>${body}</section>`;
}
function renderCompare(t) {
  const c = t.data;
  const back = '<button type="button" class="hx-back" data-act="hcmp-close" title="Back to the build list">‹ Back to the list</button>';
  let body;
  if (t.error) body = `<div class="hx-empty">Could not compare these builds (${esc(t.error)}).</div>`;
  else if (!c) body = '<div class="hx-empty">Loading…</div>';
  else {
    const d = c.duration, differ = !!(c.a.firmware && c.b.firmware && (c.a.fw_id !== c.b.fw_id || c.a.project !== c.b.project));
    const note = c.a.live || c.b.live ? `<p class="cmp-note cmp-livenote">The live side is the build as it is now, so its numbers are provisional${cmpHasLive(t) ? `. It refreshes every ${CMP_REFRESH_MS / 1000} s while this tab is shown` : ''}.</p>` : '';
    body = `<div class="cmp-top">${cmpHeadCard('A · base (older)', c.a, differ)}<div class="cmp-mid" title="Duration change"><span class="num">${fmtDurDelta(d.delta)}</span><small>duration</small></div>${cmpHeadCard('B · newer', c.b, differ)}</div>${note}
      <div class="cmp-grid">${cmpTiming(c)}${cmpUtil(c)}${cmpSteps(c)}${cmpMessages(c, t.tab)}</div>`;
  }
  const act = document.activeElement, keep = act && hist.root.contains(act) && act.dataset.tab;
  setHTML(hist.root, `<div class="hx-head"><h1>Compare builds</h1><span class="hx-n">${c ? esc(c.a.firmware && c.a.firmware !== c.b.firmware ? `${c.a.firmware} ↔ ${c.b.firmware}` : c.firmware) : ''}</span><div class="hx-tools">${back}</div></div>${body}`);
  if (keep) { const n = $(`[data-tab="${keep}"]`, hist.root); if (n) n.focus(); }
}

async function openHistoryReport(t) {
  if (t.getAttribute('aria-disabled') === 'true') { toast(HX_GONE); return; }
  const { fw, build, path, label } = t.dataset;
  try {
    let text;
    if (MOCK) text = (await jget('mock/report_raw.txt.json')).text;
    else {
      const r = await fetch(`/api/history/report?fw=${q(fw)}&build=${q(build)}&path=${q(path)}`, { cache: 'no-store' });
      if (!r.ok) { let m = r.status; try { m = (await r.json()).error || m; } catch { /* plain text */ } throw new Error(m); }
      text = await r.text();
    }
    showModal(`${label} — ${path}`, text);
  } catch (e) { toast('Could not load report: ' + e.message); }
}

/* ------------------------------------------------------------------ boot */
restoreCmpTabs();
parseHash();
if (MOCK) startMock();
else {
  // ?snapshot=1: preload state synchronously so headless screenshots of real data aren't blank
  if (params.get('snapshot') === '1') { try { setState(syncJson('/api/state')); } catch (e) { console.error(e); } }
  connectSSE();
}
window.addEventListener('error', (e) => { document.title = 'ERR ' + e.message; const t = $('#toast'); t.textContent = 'JS error: ' + e.message + ' @' + e.lineno; t.hidden = false; });
window.addEventListener('unhandledrejection', (e) => { const t = $('#toast'); t.textContent = 'JS error: ' + (e.reason && e.reason.message); t.hidden = false; });
