"""Web UI — single-page dashboard for the atrace analysis service.

Served at GET /ui  (and  GET /  → redirect)
No external dependencies; pure HTML + vanilla JS calling the local REST API.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TraceMind — Perfetto Analysis</title>
<style>
:root {
  --bg:        #0d1117;
  --surface:   #161b22;
  --surface2:  #21262d;
  --border:    #30363d;
  --text:      #e6edf3;
  --text2:     #8b949e;
  --accent:    #388bfd;
  --green:     #3fb950;
  --red:       #f85149;
  --yellow:    #d29922;
  --mono:      'SF Mono','Fira Code','Cascadia Code',monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,system-ui,sans-serif;
  font-size:14px;height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* ── Nav ── */
nav{background:var(--surface);border-bottom:1px solid var(--border);
  padding:0 18px;height:48px;display:flex;align-items:center;gap:14px;flex-shrink:0}
.logo{font-weight:700;font-size:16px;letter-spacing:-0.3px}
.logo em{color:var(--accent);font-style:normal}
.nav-sep{width:1px;height:20px;background:var(--border)}
.nav-hint{font-size:12px;color:var(--text2)}
.spacer{flex:1}
.nav-link{font-size:12px;color:var(--text2);text-decoration:none;padding:4px 8px;
  border-radius:5px;border:1px solid transparent}
.nav-link:hover{border-color:var(--border);color:var(--text)}
.status-pill{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text2);
  padding:3px 10px;border-radius:20px;background:var(--surface2);border:1px solid var(--border)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--green);flex-shrink:0}
.dot.off{background:var(--red)}

/* ── Layout ── */
.layout{display:flex;flex:1;overflow:hidden}

/* ── Sidebar ── */
aside{width:224px;background:var(--surface);border-right:1px solid var(--border);
  display:flex;flex-direction:column;flex-shrink:0;overflow:hidden}
.sidebar-hd{padding:12px 14px;border-bottom:1px solid var(--border);
  font-size:11px;font-weight:600;color:var(--text2);letter-spacing:.6px;text-transform:uppercase}
.session-list{flex:1;overflow-y:auto;padding:6px}
.session-item{padding:8px 10px;border-radius:6px;cursor:pointer;font-size:12px;
  color:var(--text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  transition:background .1s;border:1px solid transparent}
.session-item:hover{background:var(--surface2);color:var(--text)}
.session-item.active{background:rgba(56,139,253,.12);color:var(--accent);border-color:rgba(56,139,253,.35)}
.session-empty{padding:14px 10px;color:var(--text2);font-size:12px;text-align:center}
.sidebar-ft{padding:10px;border-top:1px solid var(--border);display:flex;flex-direction:column;gap:6px}

/* ── Main ── */
main{flex:1;overflow:hidden;display:flex;flex-direction:column}
.load-panel{padding:14px 18px;border-bottom:1px solid var(--border);
  display:flex;gap:10px;align-items:flex-end;flex-shrink:0;background:var(--surface)}
.field{display:flex;flex-direction:column;gap:4px}
.field label{font-size:11px;color:var(--text2);letter-spacing:.4px;text-transform:uppercase}
.inp{background:var(--surface2);border:1px solid var(--border);color:var(--text);
  padding:7px 11px;border-radius:6px;font-size:13px;font-family:var(--mono);
  transition:border-color .15s}
.inp:focus{outline:none;border-color:var(--accent)}
.inp::placeholder{color:var(--text2)}

/* ── Buttons ── */
button{cursor:pointer;border:none;border-radius:6px;font-size:13px;
  padding:7px 14px;font-weight:500;transition:opacity .1s;white-space:nowrap}
button:hover{opacity:.85}
button:disabled{opacity:.4;cursor:not-allowed}
.btn-primary{background:var(--accent);color:#fff}
.btn-ghost{background:var(--surface2);color:var(--text);border:1px solid var(--border)}
.btn-danger{background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.35)}
.btn-sm{padding:5px 11px;font-size:12px}

/* ── Tabs ── */
.tabs{display:flex;border-bottom:1px solid var(--border);padding:0 18px;
  flex-shrink:0;background:var(--surface);gap:2px}
.tab{padding:10px 14px;font-size:13px;color:var(--text2);cursor:pointer;
  border-bottom:2px solid transparent;transition:color .1s;user-select:none}
.tab:hover{color:var(--text)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}

/* ── Results ── */
.results{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:14px}

/* ── Cards ── */
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px}
.card-title{font-size:11px;font-weight:600;color:var(--text2);
  letter-spacing:.6px;text-transform:uppercase;margin-bottom:12px}

/* ── Metrics ── */
.metric-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px}
.metric{background:var(--surface2);border-radius:6px;padding:12px 14px}
.metric-label{font-size:11px;color:var(--text2);margin-bottom:5px}
.metric-value{font-size:22px;font-weight:700;font-family:var(--mono)}
.metric-value.good{color:var(--green)}
.metric-value.fair{color:var(--yellow)}
.metric-value.poor{color:var(--red)}

/* ── Verdict ── */
.verdict-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;
  border-radius:20px;font-size:12px;font-weight:700;letter-spacing:.4px;text-transform:uppercase}
.verdict-badge.excellent,.verdict-badge.good{background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.35)}
.verdict-badge.fair{background:rgba(210,153,34,.15);color:var(--yellow);border:1px solid rgba(210,153,34,.35)}
.verdict-badge.poor{background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.35)}

/* ── Table ── */
.tbl-wrap{overflow-x:auto}
.data-table{width:100%;border-collapse:collapse;font-size:12px;font-family:var(--mono)}
.data-table th{background:var(--surface2);color:var(--text2);padding:8px 11px;
  text-align:left;font-weight:600;border-bottom:1px solid var(--border);
  position:sticky;top:0;white-space:nowrap}
.data-table td{padding:7px 11px;border-bottom:1px solid rgba(48,54,61,.6);vertical-align:top}
.data-table tr:hover td{background:rgba(33,38,45,.6)}

/* ── SQL editor ── */
.sql-editor{width:100%;min-height:100px;background:var(--surface2);
  border:1px solid var(--border);color:var(--text);padding:11px;border-radius:6px;
  font-family:var(--mono);font-size:13px;resize:vertical}
.sql-editor:focus{outline:none;border-color:var(--accent)}

/* ── Progress steps ── */
.steps{display:flex;flex-direction:column;gap:7px}
.step{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--text2)}
.step.done{color:var(--text)}
.step-icon{width:20px;height:20px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:11px;flex-shrink:0}
.step-icon.pending{background:var(--surface2);border:1px solid var(--border)}
.step-icon.loading{background:rgba(56,139,253,.15);border:1px solid rgba(56,139,253,.4);animation:pulse 1s infinite}
.step-icon.done{background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.4)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* ── Misc ── */
.json-block{background:var(--surface2);border:1px solid var(--border);border-radius:6px;
  padding:12px;font-family:var(--mono);font-size:12px;overflow-x:auto;
  white-space:pre-wrap;word-break:break-word;line-height:1.6}
.err-box{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.35);
  color:var(--red);padding:11px 14px;border-radius:6px;font-size:13px}
.empty-state{text-align:center;padding:64px 20px;color:var(--text2)}
.empty-state .icon{font-size:44px;margin-bottom:12px}
.empty-state h3{font-size:16px;color:var(--text);margin-bottom:6px}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);
  border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite}
.spinner.lg{width:28px;height:28px;border-width:3px}
@keyframes spin{to{transform:rotate(360deg)}}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
</style>
</head>
<body>

<!-- ── Navbar ──────────────────────────────────────────────────────────── -->
<nav>
  <span class="logo">Trace<em>Mind</em></span>
  <span class="nav-sep"></span>
  <span class="nav-hint">Perfetto Analysis Dashboard</span>
  <span class="spacer"></span>
  <a class="nav-link" href="/docs" target="_blank">API Docs ↗</a>
  <div class="status-pill">
    <div class="dot off" id="status-dot"></div>
    <span id="status-text">Connecting…</span>
  </div>
</nav>

<div class="layout">

  <!-- ── Sidebar ──────────────────────────────────────────────────────── -->
  <aside>
    <div class="sidebar-hd">Loaded Traces</div>
    <div class="session-list" id="session-list">
      <div class="session-empty">No traces loaded yet</div>
    </div>
    <div class="sidebar-ft">
      <button class="btn-ghost btn-sm" onclick="refreshSessions()">↻ Refresh</button>
    </div>
  </aside>

  <!-- ── Main ─────────────────────────────────────────────────────────── -->
  <main>

    <!-- Row 1: Load existing trace + Analyze -->
    <div class="load-panel">
      <div class="field" style="flex:3">
        <label>Trace File Path</label>
        <input class="inp" id="trace-path" style="width:100%"
          placeholder="/private/tmp/atrace/com.example_trace.perfetto"
          onkeydown="if(event.key==='Enter') loadAndAnalyzeTrace()">
      </div>
      <div class="field" style="flex:1;min-width:180px">
        <label>Package / Process <span style="color:#f85149;font-size:10px">*必填</span></label>
        <input class="inp" id="process-input" style="width:100%"
          placeholder="com.example.app"
          oninput="syncPackageField(this.value)">
      </div>
      <button class="btn-ghost" onclick="document.getElementById('trace-file-input').click()"
        style="height:34px;align-self:flex-end">
        Choose File
      </button>
      <button class="btn-primary" onclick="loadAndAnalyzeTrace()"
        style="height:34px;align-self:flex-end;background:linear-gradient(135deg,#8957e5,#6e40c9)"
        title="加载 Trace 并用选中的 Playbook 自动分析">
        ⚡ Load + Analyze
      </button>
      <div id="load-spinner" style="display:none;align-self:flex-end;margin-bottom:7px">
        <span class="spinner"></span>
      </div>
      <input id="trace-file-input" type="file" accept=".perfetto,.pb,.pftrace,.trace,.bin"
        style="display:none" onchange="onTraceFilePicked(event)">
    </div>

    <!-- Row 2: Capture from device -->
    <div class="load-panel" style="border-top:1px solid rgba(48,54,61,.45);padding-top:10px;padding-bottom:4px">
      <div class="field" style="flex:2;min-width:200px">
        <label>Capture Package <span style="color:#f85149;font-size:10px">*必填</span></label>
        <input class="inp" id="capture-package" style="width:100%" placeholder="com.example.app"
          oninput="syncProcessField(this.value)">
      </div>
      <div class="field" style="width:150px">
        <label>Config Preset</label>
        <select class="inp" id="capture-preset" style="width:100%;padding:5px 8px;font-size:12px"
          onchange="onCapturePresetChanged(this.value)">
          <option value="">— 自定义 —</option>
        </select>
      </div>
      <div class="field" style="width:90px">
        <label>Duration(s)</label>
        <input class="inp" id="capture-duration" style="width:100%" type="number" min="1" max="300" value="8">
      </div>
      <div class="field" style="width:140px">
        <label>Device Serial</label>
        <input class="inp" id="capture-serial" style="width:100%" placeholder="auto-detect">
      </div>
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text2);margin-bottom:8px;cursor:pointer"
        title="采集时自动注入滑动手势">
        <input type="checkbox" id="capture-scroll" checked> Scroll
      </label>
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text2);margin-bottom:8px;cursor:pointer"
        title="先 force-stop 再启动应用 (冷启动场景)">
        <input type="checkbox" id="capture-cold-start"> Cold start
      </label>
      <button class="btn-ghost btn-sm" onclick="toggleScrollParams()" style="height:28px;align-self:flex-end;margin-bottom:8px"
        title="展开/收起滚动参数">▾ Scroll params</button>
    </div>
    <!-- Row 2b: Scroll params (collapsible) -->
    <div id="scroll-params-panel" class="load-panel" style="border-top:1px dashed rgba(48,54,61,.3);padding:6px 20px;display:none">
      <div class="field" style="width:80px">
        <label>Repeat</label>
        <input class="inp" id="capture-scroll-repeat" type="number" min="1" max="200" value="5" style="width:100%">
      </div>
      <div class="field" style="width:70px">
        <label>dy</label>
        <input class="inp" id="capture-scroll-dy" type="number" value="600" style="width:100%">
      </div>
      <div class="field" style="width:90px">
        <label>Speed(ms)</label>
        <input class="inp" id="capture-scroll-speed" type="number" min="1" max="5000" value="200" style="width:100%">
      </div>
      <div class="field" style="width:90px">
        <label>Pause(ms)</label>
        <input class="inp" id="capture-scroll-pause" type="number" min="0" max="10000" value="300" style="width:100%">
      </div>
      <div class="field" style="width:80px">
        <label>Start X</label>
        <input class="inp" id="capture-scroll-sx" type="number" value="540" style="width:100%">
      </div>
      <div class="field" style="width:80px">
        <label>Start Y</label>
        <input class="inp" id="capture-scroll-sy" type="number" value="1200" style="width:100%">
      </div>
    </div>
    <!-- Row 3: Capture action buttons -->
    <div class="load-panel" style="border-top:1px solid rgba(48,54,61,.45);padding-top:8px;padding-bottom:10px;gap:8px">
      <button class="btn-primary" onclick="captureTraceFromDevice()" style="height:34px">
        📱 Capture Only
      </button>
      <button class="btn-primary" onclick="captureAndAnalyzeFromTop()" style="height:34px;background:linear-gradient(135deg,#238636,#1a7f37)">
        🎯 Capture + Analyze
      </button>
      <button class="btn-ghost" onclick="refreshConnectedDevices()" style="height:34px">
        🔍 Devices
      </button>
      <span id="capture-status" style="font-size:12px;color:var(--text2);align-self:center"></span>
    </div>

    <!-- Empty state -->
    <div id="no-trace" class="empty-state" style="flex:1;overflow-y:auto">
      <div class="icon">📊</div>
      <h3>No trace selected</h3>
      <p>Enter a .perfetto file path above and click <strong>Load Trace</strong>,<br>
         or use <strong>Capture Trace</strong> to collect directly from device.</p>
      <div id="env-check-panel" style="display:none;margin-top:20px;text-align:left;max-width:640px;margin-left:auto;margin-right:auto"></div>
    </div>

    <!-- Trace content (hidden until a trace is selected) -->
    <div id="trace-content" style="display:none;flex:1;flex-direction:column;overflow:hidden">
      <div class="tabs" id="tab-bar">
        <div class="tab active" data-tab="overview">Overview</div>
        <div class="tab"        data-tab="sql">SQL Query</div>
        <div class="tab"        data-tab="ai">AI Chat</div>
        <div class="tab"        data-tab="startup">Startup</div>
        <div class="tab"        data-tab="jank">Jank</div>
        <div class="tab"        data-tab="scroll">Scroll</div>
      </div>
      <div class="results" id="results"></div>
    </div>

  </main>
</div>

<script>
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let currentTrace    = null;
let activeTab       = 'overview';
let currentSessionId = null;
let aiMessages      = [];
let aiSessionList   = [];
let aiEngineStatus  = null;  // {ready, engine, ...}
let playbookList    = [];    // [{name, scenario, description, builtin, custom}]
let selectedPlaybook = '';   // '' = no playbook (legacy auto-analyze)
let selectedPlaybookCapture = null; // capture config from selected playbook

// ── Bootstrap ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  document.getElementById('tab-bar').addEventListener('click', e => {
    const tab = e.target.dataset.tab;
    if (tab) switchTab(tab);
  });
  await checkHealth();
  await refreshSessions();
  await Promise.all([checkAIStatus(), checkEnv(), fetchPlaybooks()]);
});

// ── Health ──────────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const r = await fetch('/health');
    if (r.ok) {
      document.getElementById('status-dot').className = 'dot';
      document.getElementById('status-text').textContent = 'Connected';
    } else {
      setOffline();
    }
  } catch { setOffline(); }
}

function setOffline() {
  document.getElementById('status-dot').className = 'dot off';
  document.getElementById('status-text').textContent = 'Offline';
}

async function checkAIStatus() {
  try {
    const r = await fetch('/ai/status');
    aiEngineStatus = await r.json();
  } catch { aiEngineStatus = null; }
}

async function checkEnv() {
  try {
    const r = await fetch('/env-check');
    const data = await r.json();
    renderEnvCheck(data);
  } catch {}
}

async function fetchPlaybooks() {
  try {
    const r = await fetch('/ai/playbooks');
    const data = await r.json();
    playbookList = data.playbooks || [];
  } catch { playbookList = []; }
  populateCapturePresets();
}

function renderEnvCheck(data) {
  const panel = document.getElementById('env-check-panel');
  if (!panel) return;

  const tools = data.tools || {};
  const names = Object.keys(tools);
  const missing = data.missing || [];

  const rows = names.map(name => {
    const t = tools[name];
    const ok = t.installed;
    const dot = ok
      ? '<span style="color:var(--green);font-weight:700">✓</span>'
      : '<span style="color:var(--red);font-weight:700">✗</span>';
    const ver = ok ? `<span style="color:var(--text2);font-size:11px;font-family:var(--mono)">${esc(t.version || '')}</span>` : '';
    const purpose = `<span style="font-size:11px;color:var(--text2)">${esc(t.required_for || '')}</span>`;
    const installHtml = !ok
      ? `<details style="margin-top:4px"><summary style="font-size:11px;color:var(--accent);cursor:pointer">How to install</summary><pre style="margin:4px 0 0;font-size:11px;color:var(--text);white-space:pre-wrap;background:var(--surface2);padding:8px;border-radius:4px;border:1px solid var(--border)">${esc(t.install || '')}</pre></details>`
      : '';
    return `
      <div style="display:flex;align-items:flex-start;gap:8px;padding:8px 0;border-bottom:1px solid var(--border)">
        <span style="width:18px;text-align:center;flex-shrink:0;margin-top:2px">${dot}</span>
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:8px">
            <strong style="font-family:var(--mono);font-size:13px">${esc(name)}</strong>
            ${ver}
          </div>
          ${purpose}
          ${installHtml}
        </div>
      </div>`;
  }).join('');

  const title = missing.length
    ? `<div style="color:var(--yellow);font-size:12px;font-weight:600;margin-bottom:8px">⚠ ${missing.length} tool(s) not found</div>`
    : `<div style="color:var(--green);font-size:12px;font-weight:600;margin-bottom:8px">✓ All tools available</div>`;

  const ws = data.workspace || {};
  const wsInfo = `
    <div style="margin-top:10px;font-size:11px;color:var(--text2)">
      Workspace: <code style="font-family:var(--mono)">${esc(ws.repo_root || '?')}</code><br>
      mcp.json: ${ws.mcp_json?.exists ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--red)">✗</span>'}
      &nbsp; cli.json: ${ws.cli_json?.exists ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--red)">✗</span>'}
    </div>`;

  panel.innerHTML = `
    <div class="card" style="padding:14px">
      <div class="card-title">Environment Check</div>
      ${title}
      ${rows}
      ${wsInfo}
    </div>`;
  panel.style.display = '';
}

// ── Sessions ───────────────────────────────────────────────────────────────
async function refreshSessions() {
  try {
    const r    = await fetch('/sessions');
    const data = await r.json();
    renderSessionList(data.loaded_traces || []);
  } catch { /* sidebar stays as-is */ }
}

function renderSessionList(traces) {
  const el = document.getElementById('session-list');
  if (!traces.length) {
    el.innerHTML = '<div class="session-empty">No traces loaded yet</div>';
    return;
  }
  el.innerHTML = traces.map(t => {
    const name   = t.split('/').pop();
    const active = t === currentTrace ? ' active' : '';
    return `<div class="session-item${active}" title="${esc(t)}"
              onclick="selectTrace(${JSON.stringify(t)})">${esc(name)}</div>`;
  }).join('');
}

function selectTrace(path) {
  if (currentTrace !== path) {
    aiMessages = [];
    currentSessionId = null;
    aiSessionList = [];
  }
  currentTrace = path;
  document.getElementById('no-trace').style.display = 'none';
  const tc = document.getElementById('trace-content');
  tc.style.display    = 'flex';
  tc.style.flexDirection = 'column';
  tc.style.overflow   = 'hidden';
  refreshSessions();
  fetchAISessions();
  switchTab(activeTab);
}

// ── Load Trace ─────────────────────────────────────────────────────────────
async function loadTrace() {
  const path    = document.getElementById('trace-path').value.trim();
  const process = document.getElementById('process-input').value.trim() || null;
  if (!path) return;

  setLoading(true);
  try {
    const r = await fetch('/trace/load', {
      method:  'POST',
      headers: {'Content-Type':'application/json'},
      body:    JSON.stringify({trace_path: path, process_name: process}),
    });
    const data = await r.json();
    if (!r.ok) { showError(data.detail || JSON.stringify(data)); return; }
    await refreshSessions();
    selectTrace(path);
    renderOverview(data);
    activeTab = 'overview';
    activateTabEl('overview');
  } catch (e) { showError(String(e)); }
  finally { setLoading(false); }
}

async function loadAndAnalyzeTrace() {
  const path = document.getElementById('trace-path').value.trim();
  const process = document.getElementById('process-input').value.trim();
  if (!path) { alert('请输入 Trace 文件路径'); return; }
  if (!process) { alert('请输入应用包名 (Package / Process)'); return; }
  _syncProcess(process);

  setLoading(true);
  try {
    const r = await fetch('/trace/load', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({trace_path: path, process_name: process}),
    });
    const data = await r.json();
    if (!r.ok) { showError(data.detail || JSON.stringify(data)); return; }

    await refreshSessions();
    selectTrace(path);

    activeTab = 'ai';
    activateTabEl('ai');

    const pb = selectedPlaybook || document.getElementById('capture-preset')?.value || '';
    if (pb && !selectedPlaybook) {
      selectedPlaybook = pb;
      selectedPlaybookCapture = (playbookList.find(p => p.name === pb) || {}).capture || null;
    }
    const label = pb
      ? `⚡ Playbook 分析: ${pb} (${process})`
      : `⚡ 自动AI性能分析 (${process})`;
    aiMessages.push({role: 'user', text: label, source: 'auto'});
    renderAIPanel();

    if (pb) {
      await _streamAI(`/ai/playbooks/${encodeURIComponent(pb)}/analyze/stream`, {
        trace_path: path, process, layer_name_hint: null,
      });
    } else {
      await _streamAI('/ai/auto/stream', {
        trace_path: path, process, layer_name_hint: null,
      });
    }
  } catch (e) { showError(String(e)); }
  finally { setLoading(false); }
}

function onTraceFilePicked(event) {
  const file = event?.target?.files?.[0];
  if (!file) return;
  uploadTraceFile(file).finally(() => {
    // Reset input so selecting the same file again still triggers change event.
    event.target.value = '';
  });
}

async function uploadTraceFile(file) {
  const process = document.getElementById('process-input').value.trim() || null;
  if (!file) return;

  setLoading(true);
  try {
    const params = new URLSearchParams();
    params.set('filename', file.name || 'trace.perfetto');
    if (process) params.set('process_name', process);

    const r = await fetch(`/trace/upload?${params.toString()}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/octet-stream'},
      body: file,
    });
    const data = await r.json();
    if (!r.ok) {
      showError(data.detail || JSON.stringify(data));
      return;
    }

    const loadedPath = data.trace_path || '';
    if (loadedPath) {
      document.getElementById('trace-path').value = loadedPath;
    }
    await refreshSessions();
    selectTrace(loadedPath);
    renderOverview(data);
    activeTab = 'overview';
    activateTabEl('overview');
  } catch (e) {
    showError(String(e));
  } finally {
    setLoading(false);
  }
}

function setLoading(on) {
  document.getElementById('load-spinner').style.display = on ? '' : 'none';
}

// ── Field sync helpers ────────────────────────────────────────────────────────
function syncPackageField(v) {
  const el = document.getElementById('capture-package');
  if (el && !el.value.trim()) el.value = v;
}
function syncProcessField(v) {
  const el = document.getElementById('process-input');
  if (el && !el.value.trim()) el.value = v;
}
function toggleScrollParams() {
  const panel = document.getElementById('scroll-params-panel');
  if (panel) panel.style.display = panel.style.display === 'none' ? '' : 'none';
}

function onCapturePresetChanged(presetName) {
  if (!presetName) {
    selectedPlaybookCapture = null;
    return;
  }
  const info = playbookList.find(p => p.name === presetName);
  if (!info?.capture) return;
  const cap = info.capture;
  selectedPlaybookCapture = cap;
  const sp = cap.scroll_params || {};
  document.getElementById('capture-duration').value = cap.duration_s || 10;
  document.getElementById('capture-scroll').checked = !!cap.inject_scroll;
  document.getElementById('capture-cold-start').checked = !!cap.cold_start;
  if (Object.prototype.hasOwnProperty.call(sp, 'repeat')) {
    document.getElementById('capture-scroll-repeat').value = sp.repeat;
  }
  if (Object.prototype.hasOwnProperty.call(sp, 'dy')) {
    document.getElementById('capture-scroll-dy').value = sp.dy;
  }
  if (Object.prototype.hasOwnProperty.call(sp, 'duration_ms')) {
    document.getElementById('capture-scroll-speed').value = sp.duration_ms;
  }
  if (Object.prototype.hasOwnProperty.call(sp, 'pause_ms')) {
    document.getElementById('capture-scroll-pause').value = sp.pause_ms;
  }
  if (Object.prototype.hasOwnProperty.call(sp, 'start_x')) {
    document.getElementById('capture-scroll-sx').value = sp.start_x;
  }
  if (Object.prototype.hasOwnProperty.call(sp, 'start_y')) {
    document.getElementById('capture-scroll-sy').value = sp.start_y;
  }
  if (cap.inject_scroll) {
    document.getElementById('scroll-params-panel').style.display = '';
  }
}

function populateCapturePresets() {
  const sel = document.getElementById('capture-preset');
  if (!sel) return;
  const current = sel.value;
  const opts = playbookList.map(p => {
    const s = p.name === current ? ' selected' : '';
    const tag = p.custom ? ' [custom]' : '';
    return `<option value="${esc(p.name)}"${s}>${esc(p.name)} — ${esc((p.capture||{}).description||p.description||'').split('\\n')[0]}${tag}</option>`;
  }).join('');
  sel.innerHTML = `<option value="">— 自定义 —</option>${opts}`;
}

function _getCapturePayload() {
  const packageName = document.getElementById('capture-package').value.trim();
  if (!packageName) return null;
  const payload = {
    package: packageName,
    duration_seconds: Math.max(1, Math.min(300, Number(document.getElementById('capture-duration').value || 8))),
    serial: document.getElementById('capture-serial').value.trim() || null,
    inject_scroll: !!document.getElementById('capture-scroll').checked,
    cold_start: !!document.getElementById('capture-cold-start').checked,
    output_dir: '/tmp/atrace',
    scroll_repeat: Number(document.getElementById('capture-scroll-repeat').value || 5),
    scroll_dy: Number(document.getElementById('capture-scroll-dy').value || 600),
    scroll_duration_ms: Number(document.getElementById('capture-scroll-speed').value || 200),
    scroll_pause_ms: Number(document.getElementById('capture-scroll-pause').value || 300),
    scroll_start_x: Number(document.getElementById('capture-scroll-sx').value || 540),
    scroll_start_y: Number(document.getElementById('capture-scroll-sy').value || 1200),
  };
  const sp = selectedPlaybookCapture?.scroll_params;
  const cfg = selectedPlaybookCapture?.config;
  if (cfg && String(cfg).trim()) {
    payload.perfetto_config = String(cfg).trim();
  }
  if (sp && typeof sp === 'object') {
    if (Object.prototype.hasOwnProperty.call(sp, 'start_delay_seconds')) {
      payload.scroll_start_delay_seconds = Number(sp.start_delay_seconds);
    }
    if (Object.prototype.hasOwnProperty.call(sp, 'end_x')) {
      payload.scroll_end_x = Number(sp.end_x);
    }
    if (Object.prototype.hasOwnProperty.call(sp, 'end_y')) {
      payload.scroll_end_y = Number(sp.end_y);
    }
  }
  return payload;
}

// ── Device capture ───────────────────────────────────────────────────────────
async function captureTraceFromDevice() {
  const payload = _getCapturePayload();
  const statusEl = document.getElementById('capture-status');
  if (!payload) { statusEl.textContent = '请输入 Capture Package'; return; }

  const process = document.getElementById('process-input').value.trim() || payload.package;
  syncProcessField(payload.package);

  statusEl.innerHTML = '<span class="spinner"></span> Capturing…';
  try {
    const r = await fetch('/capture/trace', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (!r.ok || data.status === 'error') {
      statusEl.textContent = 'Capture failed';
      showError(data.detail || data.capture_result?.message || JSON.stringify(data));
      return;
    }
    const tracePath = data.trace_path;
    if (!tracePath) {
      statusEl.textContent = 'Capture done but no trace_path';
      showError(JSON.stringify(data, null, 2));
      return;
    }
    document.getElementById('trace-path').value = tracePath;
    document.getElementById('process-input').value = process;
    await refreshSessions();
    selectTrace(tracePath);
    activeTab = 'overview';
    activateTabEl('overview');
    if (data.overview && !data.overview.error) renderOverview(data.overview);
    else await fetchOverview();
    statusEl.textContent = 'Capture success';
  } catch (e) {
    statusEl.textContent = 'Capture failed';
    showError(String(e));
  }
}
//抓取trace并AI分析
async function captureAndAnalyzeFromTop() {
  const payload = _getCapturePayload();
  const statusEl = document.getElementById('capture-status');
  if (!payload) { statusEl.textContent = '请输入 Capture Package'; return; }

  const process = document.getElementById('process-input').value.trim() || payload.package;
  syncProcessField(payload.package);

  const pb = selectedPlaybook || document.getElementById('capture-preset')?.value || '';

  statusEl.innerHTML = '<span class="spinner"></span> Capturing…';
  try {
    //抓取内容
    const r = await fetch('/capture/trace', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (!r.ok || data.status === 'error') {
      statusEl.textContent = 'Capture failed';
      showError(data.detail || data.capture_result?.message || JSON.stringify(data));
      return;
    }
    const tracePath = data.trace_path;
    if (!tracePath) {
      statusEl.textContent = 'No trace_path returned';
      return;
    }
    document.getElementById('trace-path').value = tracePath;
    document.getElementById('process-input').value = process;
    currentTrace = tracePath;
    await refreshSessions();
    selectTrace(tracePath);

    statusEl.innerHTML = '<span class="spinner"></span> Analyzing…';
    activeTab = 'ai';
    activateTabEl('ai');

    if (!selectedPlaybook && pb) {
      selectedPlaybook = pb;
      selectedPlaybookCapture = (playbookList.find(p=>p.name===pb)||{}).capture || null;
    }

    const label = pb ? `🎯 Capture + Analyze: ${pb} (${process})` : `🎯 Capture + Auto Analyze (${process})`;
    aiMessages.push({role:'user', text: label, source:'auto'});
    aiMessages.push({role:'assistant', text:`✅ 采集完成: ${tracePath}\\n开始分析…`, source:'system'});
    renderAIPanel();

    if (pb) {
      await _streamAI(`/ai/playbooks/${encodeURIComponent(pb)}/analyze/stream`, {
        trace_path: tracePath, process, layer_name_hint: null,
      });
    } else {
      await _streamAI('/ai/auto/stream', {
        trace_path: tracePath, process, layer_name_hint: null,
      });
    }
    statusEl.textContent = 'Done';
  } catch (e) {
    statusEl.textContent = 'Failed';
    showError(String(e));
  }
}

async function refreshConnectedDevices() {
  const statusEl = document.getElementById('capture-status');
  statusEl.innerHTML = '<span class="spinner"></span> Querying devices…';
  console.log('[Devices] fetching /capture/devices …');
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    const r = await fetch('/capture/devices', {signal: controller.signal});
    clearTimeout(timer);
    console.log('[Devices] response status:', r.status);
    const data = await r.json();
    console.log('[Devices] response data:', JSON.stringify(data));
    if (!r.ok) {
      statusEl.textContent = 'Device query failed';
      showError(data.detail || JSON.stringify(data));
      return;
    }
    const devices = data.devices || [];
    if (!devices.length) {
      statusEl.textContent = 'No device connected';
      return;
    }
    const text = devices.map(d => {
      const model = d.model || '';
      const sdk = d.sdk ? ` (API ${d.sdk})` : '';
      return `${d.serial || '?'}${model ? ' · ' + model : ''}${sdk}`;
    }).join(', ');
    statusEl.textContent = `Devices: ${text}`;
    if (devices[0].serial && !document.getElementById('capture-serial').value.trim()) {
      document.getElementById('capture-serial').value = devices[0].serial;
    }
  } catch (e) {
    console.error('[Devices] error:', e);
    if (e.name === 'AbortError') {
      statusEl.textContent = 'Device query timeout (20s)';
      showError('adb device query timed out after 20 seconds. Check if adb is running and device is connected.');
    } else {
      statusEl.textContent = 'Device query failed';
      showError(String(e));
    }
  }
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function switchTab(tab) {
  activeTab = tab;
  activateTabEl(tab);
  if (!currentTrace) return;
  switch (tab) {
    case 'overview': fetchOverview();              break;
    case 'sql':      renderSQLPanel();             break;
    case 'ai':       renderAIPanel();              break;
    case 'startup':  renderAnalysisPanel('startup'); break;
    case 'jank':     renderAnalysisPanel('jank');    break;
    case 'scroll':   renderScrollPanel();           break;
  }
}

function activateTabEl(tab) {
  document.querySelectorAll('#tab-bar .tab').forEach(el => {
    el.classList.toggle('active', el.dataset.tab === tab);
  });
}

// ── Overview ───────────────────────────────────────────────────────────────
async function fetchOverview() {
  showSpinner('Loading overview…');
  try {
    const r    = await fetch(`/trace/${tid()}/overview`);
    const data = await r.json();
    if (!r.ok) { showError(data.detail); return; }
    renderOverview(data);
  } catch (e) { showError(String(e)); }
}

function renderOverview(data) {
  const procs = (data.processes || []).map(p =>
    `<tr>
      <td>${esc(p.name || p.cmdline || '?')}</td>
      <td>${p.pid ?? '—'}</td>
      <td>${p.thread_count ?? 0}</td>
    </tr>`).join('');

  setResults(`
    <div class="card">
      <div class="card-title">Trace Info</div>
      <div class="metric-grid">
        ${metric('Duration', ((data.duration_ms||0)/1000).toFixed(2)+'s')}
        ${metric('Slices', (data.total_slices||0).toLocaleString())}
        ${metric('Threads', data.total_threads||0)}
        ${metric('Processes', (data.processes||[]).length)}
      </div>
    </div>
    <div class="card">
      <div class="card-title">Process List</div>
      <div class="tbl-wrap">
        <table class="data-table">
          <thead><tr><th>Name</th><th>PID</th><th>Threads</th></tr></thead>
          <tbody>${procs || '<tr><td colspan="3" style="color:var(--text2)">—</td></tr>'}</tbody>
        </table>
      </div>
    </div>
    <div><button class="btn-danger btn-sm" onclick="unloadTrace()">✕ Unload Trace</button></div>
  `);
}

async function unloadTrace() {
  if (!currentTrace) return;
  await fetch(`/trace/${tid()}`, {method:'DELETE'});
  currentTrace = null;
  document.getElementById('trace-content').style.display = 'none';
  document.getElementById('no-trace').style.display = '';
  await refreshSessions();
}

// ── SQL ─────────────────────────────────────────────────────────────────────
function renderSQLPanel() {
  const defaultSQL =
    `SELECT name,\n       count(*) AS cnt,\n       round(avg(dur)/1e6, 2) AS avg_ms\nFROM   slice\nWHERE  name LIKE '%inflate%'\nGROUP  BY name\nORDER  BY cnt DESC\nLIMIT  20`;
  setResults(`
    <div class="card">
      <div class="card-title">PerfettoSQL</div>
      <textarea class="sql-editor" id="sql-input"
        placeholder="SELECT …">${esc(defaultSQL)}</textarea>
      <div class="row" style="margin-top:10px">
        <button class="btn-primary" onclick="runSQL()">▶ Execute</button>
        <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text2);cursor:pointer">
          <input type="checkbox" id="sql-summarize"> LLM summary
        </label>
        <span id="sql-status" style="font-size:12px;color:var(--text2)"></span>
      </div>
    </div>
    <div id="sql-results"></div>
  `);
}

async function runSQL() {
  const sql       = document.getElementById('sql-input')?.value?.trim();
  const summarize = document.getElementById('sql-summarize')?.checked;
  if (!sql || !currentTrace) return;

  const statusEl = document.getElementById('sql-status');
  statusEl.innerHTML = '<span class="spinner"></span>';
  document.getElementById('sql-results').innerHTML = '';

  try {
    const r    = await fetch(`/trace/${tid()}/sql`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sql, summarize, limit:500}),
    });
    const data = await r.json();
    if (!r.ok) {
      document.getElementById('sql-results').innerHTML =
        `<div class="err-box">${esc(data.detail)}</div>`;
      statusEl.textContent = 'Error';
      return;
    }
    const trunc = data.truncated ? ' (truncated at 500)' : '';
    statusEl.textContent = `${data.row_count} rows${trunc}`;
    document.getElementById('sql-results').innerHTML = summarize && data.summary
      ? `<div class="card"><div class="card-title">Summary</div>
           <pre class="json-block">${esc(JSON.stringify(data.summary, null, 2))}</pre></div>`
      : `<div class="card">${renderTable(data.rows)}</div>`;
  } catch (e) {
    document.getElementById('sql-results').innerHTML =
      `<div class="err-box">${esc(String(e))}</div>`;
    statusEl.textContent = 'Error';
  }
}

// ── AI Chat (with session history) ──────────────────────────────────────────

async function fetchAISessions() {
  if (!currentTrace) return;
  try {
    const r = await fetch(`/ai/sessions/${encodeURIComponent(currentTrace)}`);
    const data = await r.json();
    aiSessionList = data.sessions || [];
    if (aiSessionList.length && !currentSessionId) {
      await loadAISession(aiSessionList[0].session_id);
    }
  } catch { aiSessionList = []; }
}

async function loadAISession(sessionId) {
  currentSessionId = sessionId;
  try {
    const r = await fetch(`/ai/history/${sessionId}`);
    const data = await r.json();
    aiMessages = (data.messages || []).map(m => ({
      role: m.role, text: m.text, source: m.source || '', ts: m.ts || 0,
    }));
  } catch {
    aiMessages = [];
  }
  if (activeTab === 'ai') renderAIPanel();
}

function createNewAISession() {
  currentSessionId = null;
  aiMessages = [{
    role: 'assistant',
    text: '新会话已创建。你可以针对当前 trace 提问。',
    source: 'system',
  }];
  renderAIPanel();
}

function renderAIPanel() {
  if (!aiMessages.length && !currentSessionId) {
    aiMessages = [{
      role: 'assistant',
      text: '已连接 trace 上下文。你可以问我：\\n- 启动慢在哪里？\\n- 这段 trace 的 jank 根因是什么？\\n- 优先优化哪 3 个点？\\n\\n或点击 Auto Analyze 一键分析。',
      source: 'system',
    }];
  }

  const sessionOpts = aiSessionList.map(s => {
    const sel = s.session_id === currentSessionId ? ' selected' : '';
    const dt = new Date(s.last_ts * 1000);
    const label = dt.toLocaleTimeString() + ' (' + s.message_count + ' msgs)';
    return `<option value="${s.session_id}"${sel}>${esc(label)}</option>`;
  }).join('');

  const sessionBar = aiSessionList.length
    ? `<div class="row" style="margin-bottom:10px;gap:6px">
        <label style="font-size:11px;color:var(--text2)">Session:</label>
        <select class="inp" style="flex:1;padding:4px 8px;font-size:12px"
          onchange="loadAISession(this.value)">${sessionOpts}</select>
        <button class="btn-ghost btn-sm" onclick="createNewAISession()">+ New</button>
        <button class="btn-ghost btn-sm" onclick="fetchAISessions().then(()=>renderAIPanel())">↻</button>
       </div>`
    : `<div class="row" style="margin-bottom:10px">
        <span style="font-size:12px;color:var(--text2)">无历史会话</span>
        <button class="btn-ghost btn-sm" style="margin-left:auto" onclick="fetchAISessions().then(()=>renderAIPanel())">↻</button>
       </div>`;

  const engineBadge = aiEngineStatus
    ? (aiEngineStatus.ready
        ? '<span class="verdict-badge good" style="font-size:10px;padding:2px 8px">cursor-agent + MCP</span>'
        : '<span class="verdict-badge fair" style="font-size:10px;padding:2px 8px">local TraceAnalyzer</span>')
    : '<span style="font-size:10px;color:var(--text2)">checking…</span>';

  const pbOpts = playbookList.map(p => {
    const sel = p.name === selectedPlaybook ? ' selected' : '';
    const tag = p.custom ? ' [custom]' : '';
    return `<option value="${esc(p.name)}"${sel}>${esc(p.name)} — ${esc(p.description)}${tag}</option>`;
  }).join('');

  const pbSelector = `
    <div class="row" style="margin-bottom:8px;gap:6px;align-items:center;flex-wrap:wrap">
      <label style="font-size:11px;color:var(--text2);white-space:nowrap">Playbook:</label>
      <select class="inp" id="playbook-select" style="flex:1;min-width:160px;padding:4px 8px;font-size:12px"
        onchange="onPlaybookChanged(this.value)">
        <option value="">— 通用分析 (无场景) —</option>
        ${pbOpts}
      </select>
      <button class="btn-ghost btn-sm" onclick="openPlaybookEditor()" title="编辑 / 新建 Playbook">✎ Edit</button>
      <button class="btn-ghost btn-sm" onclick="fetchPlaybooks().then(()=>renderAIPanel())" title="刷新列表">↻</button>
    </div>`;

  setResults(`
    <div class="card" style="display:flex;flex-direction:column;flex:1;overflow:hidden">
      <div class="card-title" style="display:flex;align-items:center;gap:10px">
        AI Interactive Analysis
        ${engineBadge}
        <button class="btn-primary btn-sm" style="margin-left:auto" onclick="runAutoAnalyze()">⚡ Analyze Trace</button>
      </div>
      ${pbSelector}
      ${sessionBar}
      <div id="ai-thread" style="display:flex;flex-direction:column;gap:10px;flex:1;overflow-y:auto;padding-right:4px;min-height:180px;max-height:calc(100vh - 420px)">
        ${renderAIThread()}
      </div>
      <div style="margin-top:12px">
        <textarea class="sql-editor" id="ai-input" style="min-height:60px"
          placeholder="输入你的问题，例如：为什么这个 trace 启动慢？"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendAIMessage()}"></textarea>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="btn-primary" onclick="sendAIMessage()">Send</button>
        <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text2);cursor:pointer">
          <input type="checkbox" id="ai-include-context" checked> include context
        </label>
        <span id="ai-status" style="font-size:12px;color:var(--text2)"></span>
      </div>
    </div>
  `);

  const thread = document.getElementById('ai-thread');
  if (thread) thread.scrollTop = thread.scrollHeight;
}

function renderMd(text) {
  let s = esc(text);
  s = s.replace(/^## (.+)$/gm, '<strong style="font-size:14px;display:block;margin:8px 0 4px">$1</strong>');
  s = s.replace(/^### (.+)$/gm, '<strong style="font-size:13px;display:block;margin:6px 0 2px">$1</strong>');
  s = s.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
  s = s.replace(/`([^`]+)`/g, '<code style="background:rgba(56,139,253,.12);padding:1px 5px;border-radius:3px;font-family:var(--mono);font-size:12px">$1</code>');
  s = s.replace(/\\|(.+)\\|/g, (match) => {
    if (match.includes('---')) return '';
    const cells = match.split('|').filter(c => c.trim());
    if (!cells.length) return match;
    const tds = cells.map(c => `<td style="padding:3px 8px;border:1px solid var(--border)">${c.trim()}</td>`).join('');
    return `<tr>${tds}</tr>`;
  });
  return s;
}

function renderAIThread() {
  return aiMessages.map(m => {
    const isUser = m.role === 'user';
    const isSystem = m.role === 'system';
    const align = isUser ? 'flex-end' : 'flex-start';
    const bg = isUser ? 'rgba(56,139,253,.18)' : isSystem ? 'rgba(210,153,34,.08)' : 'var(--surface2)';
    const border = isUser ? 'rgba(56,139,253,.35)' : isSystem ? 'rgba(210,153,34,.25)' : 'var(--border)';
    const sourceLabel = m.source && m.source !== 'user'
      ? `<div style="font-size:10px;color:var(--text2);margin-bottom:3px;opacity:.7">${esc(m.source)}</div>`
      : '';
    const content = isUser ? esc(m.text) : renderMd(m.text);
    return `
      <div style="display:flex;justify-content:${align}">
        <div style="max-width:88%;background:${bg};border:1px solid ${border};border-radius:8px;padding:10px 12px">
          ${sourceLabel}
          <div style="white-space:pre-wrap;line-height:1.6;word-break:break-word">${content}</div>
        </div>
      </div>
    `;
  }).join('');
}

async function sendAIMessage() {
  const inputEl = document.getElementById('ai-input');
  const statusEl = document.getElementById('ai-status');
  const question = (inputEl?.value || '').trim();
  if (!question || !currentTrace) return;

  const process = _getProcess();
  if (!process) { alert('请输入应用包名 (Package)'); return; }
  _syncProcess(process);

  aiMessages.push({role: 'user', text: question, source: 'user'});
  inputEl.value = '';
  renderAIPanel();

  const includeContext = !!document.getElementById('ai-include-context')?.checked;
  const url = currentSessionId
    ? `/ai/chat/stream?session_id=${encodeURIComponent(currentSessionId)}`
    : '/ai/chat/stream';

  await _streamAI(url, {
    trace_path: currentTrace, question, process, include_context: includeContext,
  });
}

function _getProcess() {
  return document.getElementById('process-input')?.value?.trim()
    || document.getElementById('capture-package')?.value?.trim()
    || null;
}

function _syncProcess(process) {
  if (!process) return;
  const pi = document.getElementById('process-input');
  const cp = document.getElementById('capture-package');
  if (pi && !pi.value.trim()) pi.value = process;
  if (cp && !cp.value.trim()) cp.value = process;
}

function onPlaybookChanged(name) {
  selectedPlaybook = name;
  const info = name ? playbookList.find(p => p.name === name) : null;
  selectedPlaybookCapture = info?.capture || null;
  // Sync top capture preset selector
  const presetSel = document.getElementById('capture-preset');
  if (presetSel && name) {
    presetSel.value = name;
    onCapturePresetChanged(name);
  }
  renderAIPanel();
}

async function runAutoAnalyze() {
  if (!currentTrace) { alert('请先加载 Trace 文件'); return; }
  const process = _getProcess();
  if (!process) { alert('请输入应用包名 (Package)'); return; }
  _syncProcess(process);

  const layer = document.getElementById('layer-hint')?.value?.trim() || null;
  const pb = selectedPlaybook || '';

  const label = pb ? `⚡ Playbook 分析: ${pb} (${process})` : `⚡ 自动AI性能分析 (${process})`;
  aiMessages.push({role: 'user', text: label, source: 'auto'});
  renderAIPanel();

  if (pb) {
    await _streamAI(`/ai/playbooks/${encodeURIComponent(pb)}/analyze/stream`, {
      trace_path: currentTrace, process, layer_name_hint: layer,
    });
  } else {
    await _streamAI('/ai/auto/stream', {
      trace_path: currentTrace, process, layer_name_hint: layer,
    });
  }
}

async function _streamAI(url, payload) {
  const statusEl = document.getElementById('ai-status');
  if (statusEl) statusEl.innerHTML = '<span class="spinner"></span> agent working…';

  // Prepare a streaming assistant bubble
  const streamMsg = {role: 'assistant', text: '', source: 'cursor-agent', tools: []};
  aiMessages.push(streamMsg);
  _renderStreamBubble(streamMsg);

  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({detail: r.statusText}));
      streamMsg.text = err.detail || JSON.stringify(err);
      streamMsg.source = 'error';
      renderAIPanel();
      if (statusEl) statusEl.textContent = 'error';
      return;
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      const blocks = buf.split('\\n\\n');
      buf = blocks.pop();

      for (const block of blocks) {
        if (!block.trim()) continue;
        let event = '', dataStr = '';
        for (const line of block.split('\\n')) {
          if (line.startsWith('event: ')) event = line.slice(7).trim();
          if (line.startsWith('data: '))  dataStr = line.slice(6);
        }
        if (!event || !dataStr) continue;
        let d;
        try { d = JSON.parse(dataStr); } catch { continue; }

        if (event === 'init') {
          if (statusEl) statusEl.innerHTML = '<span class="spinner"></span> cursor agent connected';
        } else if (event === 'text') {
          streamMsg.text += d.text || '';
          _updateStreamText(streamMsg);
        } else if (event === 'tool_use') {
          streamMsg.tools.push({name: d.name, summary: d.summary, status: 'running'});
          _updateStreamTools(streamMsg);
          if (statusEl) statusEl.innerHTML = `<span class="spinner"></span> [${esc(d.name)}]`;
        } else if (event === 'tool_result') {
          const last = streamMsg.tools[streamMsg.tools.length - 1];
          if (last) { last.status = 'done'; last.preview = d.preview; }
          _updateStreamTools(streamMsg);
        } else if (event === 'done') {
          if (d.session_id) currentSessionId = d.session_id;
          streamMsg.source = d.source || 'cursor-agent';
          fetchAISessions();
          renderAIPanel();
          const dur = d.duration_ms ? `${(d.duration_ms / 1000).toFixed(1)}s` : '';
          if (statusEl) statusEl.textContent = `done ${dur}`;
        } else if (event === 'error') {
          streamMsg.text += '\\n\\n[error] ' + (d.message || JSON.stringify(d));
          streamMsg.source = 'error';
          renderAIPanel();
          if (statusEl) statusEl.textContent = 'error';
        }
      }
    }
  } catch (e) {
    streamMsg.text += '\\n\\n[error] ' + String(e);
    streamMsg.source = 'error';
    renderAIPanel();
    if (statusEl) statusEl.textContent = 'error';
  }
}

function _renderStreamBubble(msg) {
  const thread = document.getElementById('ai-thread');
  if (!thread) return;
  const bubble = document.createElement('div');
  bubble.id = 'stream-bubble';
  bubble.style.cssText = 'display:flex;justify-content:flex-start';
  bubble.innerHTML = `
    <div style="max-width:88%;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px 12px">
      <div style="font-size:10px;color:var(--text2);margin-bottom:3px;opacity:.7">cursor-agent <span class="spinner" style="width:10px;height:10px"></span></div>
      <div id="stream-tools" style="margin-bottom:6px"></div>
      <div id="stream-text" style="white-space:pre-wrap;line-height:1.6;word-break:break-word"></div>
    </div>`;
  thread.appendChild(bubble);
  thread.scrollTop = thread.scrollHeight;
}

function _updateStreamText(msg) {
  const el = document.getElementById('stream-text');
  if (el) el.innerHTML = renderMd(msg.text);
  const thread = document.getElementById('ai-thread');
  if (thread) thread.scrollTop = thread.scrollHeight;
}

function _updateStreamTools(msg) {
  const el = document.getElementById('stream-tools');
  if (!el) return;
  el.innerHTML = (msg.tools || []).map(t => {
    const icon = t.status === 'done' ? '✓' : '<span class="spinner" style="width:10px;height:10px;border-width:1.5px"></span>';
    const preview = t.preview ? `<div style="font-size:10px;color:var(--text2);margin-left:18px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:500px">${esc(t.preview)}</div>` : '';
    return `<div style="font-size:11px;color:var(--accent);display:flex;align-items:center;gap:4px;margin-bottom:2px">
      <span style="width:14px;text-align:center">${icon}</span>
      <span style="font-family:var(--mono)">${esc(t.name)}</span>
      <span style="color:var(--text2);font-size:10px">${esc(t.summary || '')}</span>
    </div>${preview}`;
  }).join('');
  const thread = document.getElementById('ai-thread');
  if (thread) thread.scrollTop = thread.scrollHeight;
}

// ── Analysis panels ─────────────────────────────────────────────────────────
const ANALYSIS_META = {
  startup: {
    title: 'Startup Analysis',
    desc:  'Top slow main-thread functions, bindApplication, Activity.onCreate, blocking Binder/GC/IO.',
  },
  jank: {
    title: 'Jank Smoke-check',
    desc:  'Frames > 16.6 ms threshold and long main-thread operations. Quick first-pass.',
  },
};

function renderAnalysisPanel(type) {
  const m = ANALYSIS_META[type];
  setResults(`
    <div class="card">
      <div class="card-title">${m.title}</div>
      <p style="color:var(--text2);font-size:13px;margin-bottom:14px">${m.desc}</p>
      <div class="row">
        <button class="btn-primary" onclick="runAnalysis('${type}')">▶ Run</button>
        <span id="analysis-status" style="font-size:12px;color:var(--text2)"></span>
      </div>
    </div>
    <div id="analysis-results"></div>
  `);
}

function renderScrollPanel() {
  setResults(`
    <div class="card">
      <div class="card-title">Scroll Performance Analysis</div>
      <p style="color:var(--text2);font-size:13px;margin-bottom:14px">
        Frame quality (jank types), P50/P90/P95/P99 duration, worst frames,
        main-thread hot slices, blocking Binder/GC/IO.
      </p>
      <div class="row">
        <input class="inp" id="layer-hint" style="width:280px"
          placeholder="Layer hint (optional, e.g. MainActivity)">
        <button class="btn-primary" onclick="runScrollStream()">▶ Run (streaming)</button>
        <button class="btn-ghost"   onclick="runAnalysis('scroll')">Run (batch)</button>
        <span id="analysis-status" style="font-size:12px;color:var(--text2)"></span>
      </div>
    </div>
    <div id="analysis-results">
      <div id="sse-progress" style="display:none" class="card">
        <div class="card-title">Progress</div>
        <div class="steps" id="progress-steps"></div>
      </div>
    </div>
  `);
}

async function runAnalysis(type) {
  if (!currentTrace) return;
  const statusEl = document.getElementById('analysis-status');
  if (statusEl) statusEl.innerHTML = '<span class="spinner"></span> Running…';

  const process = document.getElementById('process-input').value.trim() || null;
  const layer   = document.getElementById('layer-hint')?.value.trim() || null;
  const body    = type === 'scroll'
    ? {process, layer_name_hint: layer}
    : {process};

  try {
    const r    = await fetch(`/analyze/${tid()}/${type}`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) {
      document.getElementById('analysis-results').innerHTML =
        `<div class="err-box">${esc(data.detail)}</div>`;
      if (statusEl) statusEl.textContent = 'Error';
      return;
    }
    if (statusEl) statusEl.textContent = 'Done';
    document.getElementById('analysis-results').innerHTML =
      renderAnalysisResult(type, data);
  } catch (e) {
    document.getElementById('analysis-results').innerHTML =
      `<div class="err-box">${esc(String(e))}</div>`;
    if (statusEl) statusEl.textContent = 'Error';
  }
}

// ── SSE scroll stream ────────────────────────────────────────────────────────
const SSE_STEPS = ['frame_quality','frame_duration','worst_frames',
                   'main_thread_top','compose_slices','blocking_calls','verdict'];

async function runScrollStream() {
  if (!currentTrace) return;
  const process = document.getElementById('process-input').value.trim() || null;
  const layer   = document.getElementById('layer-hint')?.value.trim() || null;

  const progressEl = document.getElementById('sse-progress');
  progressEl.style.display = '';

  const stepState = Object.fromEntries(SSE_STEPS.map(s => [s, 'pending']));
  // Mark frame_quality as loading immediately
  stepState['frame_quality'] = 'loading';
  renderSteps(stepState);

  const statusEl = document.getElementById('analysis-status');
  if (statusEl) statusEl.innerHTML = '<span class="spinner"></span> Streaming…';

  const accumulated = {};
  try {
    const r = await fetch(`/analyze/${tid()}/scroll/stream`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({process, layer_name_hint: layer}),
    });
    const reader  = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      const blocks = buf.split('\\n\\n');
      buf = blocks.pop();

      for (const block of blocks) {
        if (!block.trim()) continue;
        let event = '', dataStr = '';
        for (const line of block.split('\\n')) {
          if (line.startsWith('event: ')) event    = line.slice(7).trim();
          if (line.startsWith('data: '))  dataStr  = line.slice(6);
        }
        if (!event) continue;
        try { accumulated[event] = JSON.parse(dataStr); } catch {}

        if (SSE_STEPS.includes(event)) {
          stepState[event] = 'done';
          const next = SSE_STEPS[SSE_STEPS.indexOf(event) + 1];
          if (next) stepState[next] = 'loading';
          renderSteps(stepState);
        }
        if (event === 'done') {
          progressEl.style.display = 'none';
          if (statusEl) statusEl.textContent = 'Done';
          document.getElementById('analysis-results').innerHTML =
            renderAnalysisResult('scroll', accumulated);
        }
        if (event === 'error') {
          progressEl.style.display = 'none';
          if (statusEl) statusEl.textContent = 'Error';
          document.getElementById('analysis-results').innerHTML =
            `<div class="err-box">${esc(accumulated.error?.message || 'Unknown error')}</div>`;
        }
      }
    }
  } catch (e) {
    progressEl.style.display = 'none';
    document.getElementById('analysis-results').innerHTML =
      `<div class="err-box">${esc(String(e))}</div>`;
    if (statusEl) statusEl.textContent = 'Error';
  }
}

function renderSteps(state) {
  document.getElementById('progress-steps').innerHTML = SSE_STEPS.map(s => {
    const st   = state[s];
    const icon = st === 'done' ? '✓' : st === 'loading' ? '…' : '○';
    return `<div class="step ${st === 'done' ? 'done' : ''}">
      <div class="step-icon ${st}">${icon}</div>
      <span>${s.replace(/_/g,' ')}</span>
    </div>`;
  }).join('');
}

// ── Analysis result renderers ────────────────────────────────────────────────
function renderAnalysisResult(type, data) {
  if (type === 'scroll')  return renderScrollResult(data);
  if (type === 'startup') return renderStartupResult(data);
  if (type === 'jank')    return renderJankResult(data);
  return `<div class="card"><pre class="json-block">${esc(JSON.stringify(data, null, 2))}</pre></div>`;
}

function renderScrollResult(d) {
  const verdict    = d.verdict || {};
  const assessment = (verdict.assessment || 'unknown').toLowerCase();
  const fd         = d.frame_duration || {};
  const fq         = d.frame_quality  || [];
  const worst      = d.worst_frames   || [];
  const mt         = d.main_thread_top || [];
  const blocking   = d.blocking_calls  || [];

  const pctClass = v =>
    typeof v === 'number' ? (v < 16.6 ? 'good' : v < 33.3 ? 'fair' : 'poor') : '';

  return `
    <div class="card">
      <div class="row">
        <div class="verdict-badge ${assessment}">${assessment.toUpperCase()}</div>
        <span style="font-size:13px;color:var(--text2)">${esc(verdict.summary || verdict.jank_rate || '')}</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Frame Duration (ms)</div>
      <div class="metric-grid">
        ${['p50','p90','p95','p99','max'].map(k => {
          const v = fd[k] ?? '—';
          return metric(k.toUpperCase(), typeof v === 'number' ? v.toFixed(1) : v, pctClass(v));
        }).join('')}
      </div>
    </div>

    ${fq.length ? `<div class="card"><div class="card-title">Frame Quality</div>${renderTable(fq)}</div>` : ''}
    ${worst.length ? `<div class="card"><div class="card-title">Worst Frames (top 10)</div>${renderTable(worst.slice(0,10))}</div>` : ''}
    ${mt.length ? `<div class="card"><div class="card-title">Main Thread Hot Slices</div>${renderTable(mt.slice(0,15))}</div>` : ''}
    ${blocking.length ? `<div class="card"><div class="card-title">Blocking Calls</div>${renderTable(blocking)}</div>` : ''}

    <div class="card">
      <div class="card-title">Raw Verdict</div>
      <pre class="json-block">${esc(JSON.stringify(verdict, null, 2))}</pre>
    </div>
  `;
}

function renderStartupResult(d) {
  const sections = [
    ['Top Main-thread Slices', d.top_main_thread || d.top_slices || []],
    ['Blocking Calls', d.blocking_calls || []],
  ].filter(([, rows]) => rows.length);

  return sections.length
    ? sections.map(([t, rows]) =>
        `<div class="card"><div class="card-title">${t}</div>${renderTable(rows)}</div>`
      ).join('')
    : `<div class="card"><pre class="json-block">${esc(JSON.stringify(d, null, 2))}</pre></div>`;
}

function renderJankResult(d) {
  const frames = d.janky_frames || d.jank_frames  || [];
  const ops    = d.long_operations || d.long_main_thread || [];
  if (!frames.length && !ops.length) {
    return `<div class="card"><pre class="json-block">${esc(JSON.stringify(d, null, 2))}</pre></div>`;
  }
  return `
    ${frames.length ? `<div class="card"><div class="card-title">Janky Frames</div>${renderTable(frames.slice(0,20))}</div>` : ''}
    ${ops.length    ? `<div class="card"><div class="card-title">Long Main-thread Ops</div>${renderTable(ops.slice(0,20))}</div>` : ''}
  `;
}

// ── Generic table ────────────────────────────────────────────────────────────
function renderTable(rows) {
  if (!rows || !rows.length)
    return '<p style="color:var(--text2);font-size:13px">No data</p>';
  const cols   = Object.keys(rows[0]);
  const header = cols.map(c => `<th>${esc(c)}</th>`).join('');
  const body   = rows.map(r =>
    `<tr>${cols.map(c => `<td>${fmtCell(r[c])}</td>`).join('')}</tr>`
  ).join('');
  return `<div class="tbl-wrap">
    <table class="data-table">
      <thead><tr>${header}</tr></thead>
      <tbody>${body}</tbody>
    </table></div>`;
}

function fmtCell(v) {
  if (v === null || v === undefined)
    return '<span style="color:var(--text2)">—</span>';
  if (typeof v === 'number')
    return v.toLocaleString(undefined, {maximumFractionDigits:3});
  if (typeof v === 'object')
    return `<pre style="margin:0;font-size:11px">${esc(JSON.stringify(v))}</pre>`;
  return esc(String(v));
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function metric(label, value, cls = '') {
  return `<div class="metric">
    <div class="metric-label">${label}</div>
    <div class="metric-value ${cls}">${value}</div>
  </div>`;
}

// ── Playbook Editor ──────────────────────────────────────────────────────────

async function openPlaybookEditor(editName) {
  const name = editName || selectedPlaybook || '';
  let yaml = '';
  let isBuiltin = false;
  let isNew = !name;

  if (name) {
    try {
      const r = await fetch(`/ai/playbooks/${encodeURIComponent(name)}/yaml`);
      const data = await r.json();
      yaml = data.yaml || '';
      isBuiltin = data.builtin && !data.custom;
    } catch (e) {
      yaml = `# Error loading: ${e}`;
    }
  } else {
    yaml = _playbookTemplate();
  }

  const overlay = document.createElement('div');
  overlay.id = 'pb-editor-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center';

  const title = isNew ? 'New Playbook' : (isBuiltin ? `${name} (built-in, read-only — save will create custom copy)` : `${name} (custom)`);

  overlay.innerHTML = `
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;width:min(90vw,900px);max-height:90vh;display:flex;flex-direction:column;overflow:hidden">
      <div style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px">
        <span style="font-weight:600;font-size:14px">Playbook Editor</span>
        <span style="font-size:12px;color:var(--text2)">${esc(title)}</span>
        <span style="flex:1"></span>
        <button class="btn-ghost btn-sm" onclick="document.getElementById('pb-editor-overlay')?.remove()">✕ Close</button>
      </div>
      <div style="padding:14px 18px;display:flex;gap:10px;align-items:center;border-bottom:1px solid var(--border)">
        <label style="font-size:12px;color:var(--text2);white-space:nowrap">Name:</label>
        <input class="inp" id="pb-editor-name" value="${esc(isNew ? 'my_analysis' : name)}" style="width:200px;padding:5px 10px;font-size:13px"
          ${isBuiltin ? '' : ''}>
        <span style="flex:1"></span>
        <button class="btn-primary btn-sm" onclick="savePlaybook()">💾 Save</button>
        ${!isNew && !isBuiltin ? '<button class="btn-danger btn-sm" onclick="deletePlaybook()">🗑 Delete</button>' : ''}
      </div>
      <textarea id="pb-editor-yaml" style="flex:1;min-height:400px;background:var(--bg);border:none;color:var(--text);padding:14px 18px;font-family:var(--mono);font-size:13px;resize:none;line-height:1.7;tab-size:2"
        spellcheck="false">${esc(yaml)}</textarea>
      <div id="pb-editor-status" style="padding:8px 18px;font-size:12px;color:var(--text2);border-top:1px solid var(--border)">
        Tab key inserts 2 spaces. Ctrl+S saves.
      </div>
    </div>`;

  document.body.appendChild(overlay);

  const ta = document.getElementById('pb-editor-yaml');
  ta?.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const s = ta.selectionStart, end = ta.selectionEnd;
      ta.value = ta.value.substring(0, s) + '  ' + ta.value.substring(end);
      ta.selectionStart = ta.selectionEnd = s + 2;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      savePlaybook();
    }
  });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.remove();
  });
}

async function savePlaybook() {
  const nameEl = document.getElementById('pb-editor-name');
  const yamlEl = document.getElementById('pb-editor-yaml');
  const statusEl = document.getElementById('pb-editor-status');
  if (!nameEl || !yamlEl) return;

  const name = nameEl.value.trim();
  if (!name) { statusEl.textContent = '❌ Name is required'; return; }

  statusEl.innerHTML = '<span class="spinner" style="width:12px;height:12px"></span> Saving…';

  try {
    const r = await fetch(`/ai/playbooks/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({yaml: yamlEl.value}),
    });
    const data = await r.json();
    if (r.ok) {
      statusEl.textContent = `✅ Saved: ${data.path || name}`;
      selectedPlaybook = name;
      await fetchPlaybooks();
      if (activeTab === 'ai') {
        setTimeout(() => {
          document.getElementById('pb-editor-overlay')?.remove();
          renderAIPanel();
        }, 800);
      }
    } else {
      statusEl.textContent = `❌ ${data.detail || JSON.stringify(data)}`;
    }
  } catch (e) {
    statusEl.textContent = `❌ ${String(e)}`;
  }
}

async function deletePlaybook() {
  const nameEl = document.getElementById('pb-editor-name');
  const statusEl = document.getElementById('pb-editor-status');
  if (!nameEl) return;
  const name = nameEl.value.trim();
  if (!confirm(`Delete custom playbook "${name}"?`)) return;

  try {
    const r = await fetch(`/ai/playbooks/${encodeURIComponent(name)}`, {method: 'DELETE'});
    const data = await r.json();
    if (r.ok) {
      statusEl.textContent = `✅ Deleted: ${name}`;
      if (selectedPlaybook === name) selectedPlaybook = '';
      await fetchPlaybooks();
      setTimeout(() => {
        document.getElementById('pb-editor-overlay')?.remove();
        if (activeTab === 'ai') renderAIPanel();
      }, 600);
    } else {
      statusEl.textContent = `❌ ${data.detail || JSON.stringify(data)}`;
    }
  } catch (e) {
    statusEl.textContent = `❌ ${String(e)}`;
  }
}

function _playbookTemplate() {
  return `name: my_analysis
description: |
  自定义分析场景描述。
  告诉 AI 这是什么类型的分析，关注哪些方面。
scenario: custom

capture:
  config: config.txtpb
  duration_s: 10
  description: 采集配置说明

tools_required:
  - name: load_trace
    purpose: 加载 trace 文件
  - name: trace_overview
    purpose: 获取 trace 概览

tools_recommended:
  - name: query_slices
    purpose: 按耗时查询函数调用
  - name: execute_sql
    purpose: 自定义 SQL 查询
  - name: slice_children
    purpose: 下钻子调用
  - name: call_chain
    purpose: 调用链分析

initial_steps:
  - 调用 load_trace 加载 trace 文件
  - 调用 trace_overview 了解 trace 基本信息
  - 根据 trace 内容选择合适的分析工具

strategy:
  focus_areas:
    - "在这里添加你关注的分析方向"
    - "例如：主线程耗时函数 Top-10"

  sql_patterns:
    example_query: |
      SELECT s.name, s.dur/1e6 AS dur_ms
      FROM slice s
      JOIN thread_track tt ON s.track_id = tt.id
      JOIN thread t ON tt.utid = t.utid
      WHERE t.is_main_thread = 1
      ORDER BY s.dur DESC LIMIT 20

  drill_down_hints:
    - "对耗时 > 16ms 的 slice 使用 slice_children 下钻"

  key_metrics:
    - "your_key_metric"

report_sections:
  - title: "关键发现"
    description: "3-5 条最重要的发现"
  - title: "详细分析"
    description: "分析链路和证据"
  - title: "优化建议"
    description: "P0/P1/P2 优先级"

thresholds:
  example_threshold_ms: 100
`;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function setResults(html) { document.getElementById('results').innerHTML = html; }

function showSpinner(msg = 'Loading…') {
  setResults(`<div class="empty-state">
    <span class="spinner lg"></span>
    <p style="margin-top:14px;color:var(--text2)">${msg}</p>
  </div>`);
}

function showError(msg) {
  setResults(`<div class="err-box">${esc(msg)}</div>`);
}

function tid() { return encodeURIComponent(currentTrace); }

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/ui", response_class=HTMLResponse, summary="Web UI dashboard")
@router.get("/", response_class=HTMLResponse, summary="Web UI dashboard (root redirect)")
def serve_ui() -> str:
    return _HTML
