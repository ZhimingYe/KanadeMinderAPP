// ── Security helpers ───────────────────────────────────────────────────────────
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ── Tab switching ──────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
  });
});

// ── Hierarchy helpers ──────────────────────────────────────────────────────────
function orderedWithDepth(tasks) {
  const ids = new Set(tasks.map(t => t.id));
  const byParent = {};
  tasks.forEach(t => {
    const pid = (t.parent_id != null && ids.has(t.parent_id)) ? t.parent_id : null;
    (byParent[pid] = byParent[pid] || []).push(t);
  });
  const result = [];
  const visited = new Set();
  function visit(pid, depth) {
    (byParent[pid] || []).forEach(t => {
      if (t.id != null && visited.has(t.id)) return;
      if (t.id != null) visited.add(t.id);
      result.push({ task: t, depth });
      if (t.id != null) visit(t.id, depth + 1);
    });
  }
  visit(null, 0);
  // Force-add any tasks not reachable from roots (e.g. cycles) as top-level
  tasks.forEach(t => {
    if (t.id != null && !visited.has(t.id)) {
      visited.add(t.id);
      result.push({ task: t, depth: 0 });
    }
  });
  return result;
}

// ── Task helpers ───────────────────────────────────────────────────────────────
function formatDeadline(dl) {
  if (!dl) return null;
  const d = new Date(dl);
  const now = new Date();
  if (d < now) {
    const diffMs = now - d;
    const diffH = Math.floor(diffMs / 3600000);
    const diffD = Math.floor(diffH / 24);
    const age = diffD >= 1 ? diffD + 'd' : diffH + 'h';
    return {
      text: d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) + ' (' + age + ' overdue)',
      cls: 'overdue-dl',
    };
  }
  if (d.toDateString() === now.toDateString()) {
    const minsLeft = Math.floor((d - now) / 60000);
    const remaining = minsLeft < 60
      ? minsLeft + 'min'
      : Math.floor(minsLeft / 60) + 'h ' + (minsLeft % 60) + 'min';
    return {
      text: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' (' + remaining + ' left)',
      cls: 'today-dl',
    };
  }
  return { text: d.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' }), cls: '' };
}

function buildTaskItem(task, depth = 0) {
  const badge = `<span class="badge p${task.priority}">P${task.priority}</span>`;
  const prefix = depth > 0 ? '<span class="subtask-indent">└─</span> ' : '';
  let nameHtml = escapeHtml(task.name);
  if (task.recurrence) nameHtml += `<span class="recur"> ↻ ${escapeHtml(task.recurrence)}</span>`;
  const dlInfo = formatDeadline(task.deadline);
  const dlHtml = dlInfo ? `<span class="dl ${dlInfo.cls}">${dlInfo.text}</span>` : '';
  const pl = depth > 0 ? ` style="padding-left:${depth * 14}px"` : '';
  return `<div class="task-item"${pl}>${badge}<span class="task-name">${prefix}${nameHtml}${dlHtml}</span></div>`;
}

function renderTasks(tasks) {
  const now = new Date();
  const active = tasks.filter(t => t.status !== 'done');

  // Build a set of all active task IDs so we can identify children
  const allIds = new Set(active.map(t => t.id).filter(id => id != null));
  const activeById = new Map(active.filter(t => t.id != null).map(t => [t.id, t]));
  const isRoot = t => {
    if (t.parent_id == null || !allIds.has(t.parent_id)) return true;
    // Follow parent chain to detect cycles; treat cycle members as roots
    const seen = new Set();
    if (t.id != null) seen.add(t.id);
    let pid = t.parent_id;
    while (pid != null && allIds.has(pid)) {
      if (seen.has(pid)) return true;
      seen.add(pid);
      const p = activeById.get(pid);
      if (!p) break;
      pid = p.parent_id;
    }
    return false;
  };

  // Only root tasks determine section placement; children follow their parent
  const overdue  = active.filter(t => t.deadline && new Date(t.deadline) < now && isRoot(t));
  const dueToday = active.filter(t => {
    if (!t.deadline || !isRoot(t)) return false;
    const d = new Date(t.deadline);
    return d >= now && d.toDateString() === now.toDateString();
  });
  const upcoming = active.filter(t => {
    if (!t.deadline || !isRoot(t)) return false;
    const d = new Date(t.deadline);
    return d.toDateString() !== now.toDateString() && d > now;
  });
  const noDl = active.filter(t => !t.deadline && isRoot(t));

  // Build child lookup from ALL active tasks so children render under their parent
  const byParent = {};
  active.forEach(t => {
    const pid = (t.parent_id != null && allIds.has(t.parent_id)) ? t.parent_id : null;
    (byParent[pid] = byParent[pid] || []).push(t);
  });

  function renderSectionWithChildren(rootTasks) {
    const result = [];
    const visited = new Set();
    function visit(task, depth) {
      if (task.id != null && visited.has(task.id)) return;
      if (task.id != null) visited.add(task.id);
      result.push(buildTaskItem(task, depth));
      if (task.id != null) {
        (byParent[task.id] || []).forEach(child => visit(child, depth + 1));
      }
    }
    rootTasks.forEach(t => visit(t, 0));
    return result.join('');
  }

  let html = '';
  if (overdue.length)  html += `<div class="section-header overdue">Overdue (${overdue.length})</div>`  + renderSectionWithChildren(overdue);
  if (dueToday.length) html += `<div class="section-header due-today">Due Today (${dueToday.length})</div>` + renderSectionWithChildren(dueToday);
  if (upcoming.length) html += `<div class="section-header upcoming">Upcoming (${upcoming.length})</div>` + renderSectionWithChildren(upcoming);
  if (noDl.length)     html += `<div class="section-header no-dl">No Deadline (${noDl.length})</div>`  + renderSectionWithChildren(noDl);
  if (!html) html = '<div id="tasks-empty">No active tasks.</div>';

  document.getElementById('tasks-list').innerHTML = html;
}

function updateSyncStatus(msg) {
  document.getElementById('sync-status').textContent = msg;
}

// ── Settings Button ────────────────────────────────────────────────────────────
document.getElementById('settings-btn').addEventListener('click', async () => {
  if (window.isPyWebView) {
    // Desktop mode: wait for API then call Python
    try {
      // Wait for pywebviewReady promise if it exists
      if (window.pywebviewReady) {
        await window.pywebviewReady;
      }
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_settings_window) {
        const result = await window.pywebview.api.open_settings_window();
        if (!result || !result.success) {
          console.error('Failed to open settings:', result ? result.error : 'Unknown error');
        }
      } else {
        alert('Settings API not ready yet. Please try again.');
      }
    } catch (e) {
      console.error('Error opening settings:', e);
      alert('Error opening settings: ' + e.message);
    }
  } else {
    // Web mode: open settings in a new window/tab
    // This would require a separate settings page URL
    alert('Settings are only available in the desktop app. Please use: kanademinder config init');
  }
});

async function fetchTasks() {
  try {
    const res = await fetch('/api/tasks');
    const tasks = await res.json();
    // Check if we got an error response
    if (tasks && tasks.error) {
      console.error('fetchTasks error:', tasks.error);
      updateSyncStatus('Sync failed: ' + tasks.error);
      return;
    }
    // Check if tasks is actually an array
    if (!Array.isArray(tasks)) {
      console.error('fetchTasks: expected array, got', typeof tasks, tasks);
      updateSyncStatus('Sync failed: invalid response');
      return;
    }
    renderTasks(tasks);
    updateSyncStatus('Last sync: ' + new Date().toLocaleTimeString());
  } catch (e) {
    console.error('fetchTasks exception:', e);
    updateSyncStatus('Sync failed: ' + e.message);
  }
}

// ── Suggestion ─────────────────────────────────────────────────────────────────
const suggestionEl = document.getElementById('suggestion-text');
let _suggestionInFlight = false;

async function fetchSuggestion() {
  if (_suggestionInFlight) return;
  _suggestionInFlight = true;
  suggestionEl.className = 'muted';
  suggestionEl.textContent = 'Thinking…';
  try {
    const res = await fetch('/api/suggestion');
    const data = await res.json();
    if (data.error) {
      suggestionEl.textContent = 'Error: ' + data.error;
    } else if (data.suggestion) {
      suggestionEl.className = '';
      suggestionEl.textContent = data.suggestion;
    } else {
      suggestionEl.className = 'muted';
      suggestionEl.textContent = 'No active tasks.';
    }
  } catch (e) {
    suggestionEl.className = 'muted';
    suggestionEl.textContent = 'Could not load suggestion.';
  } finally {
    _suggestionInFlight = false;
  }
}

document.getElementById('refresh-suggestion').addEventListener('click', fetchSuggestion);

// ── Chat ───────────────────────────────────────────────────────────────────────
const messagesEl = document.getElementById('chat-messages');
const inputEl    = document.getElementById('chat-input');
const sendBtn    = document.getElementById('send-btn');

function appendMsg(role, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function buildChatTaskTable(tasks) {
  if (!tasks || tasks.length === 0) {
    const el = document.createElement('div');
    el.className = 'msg assistant';
    el.textContent = 'No active tasks.';
    return el;
  }
  const now = new Date();
  let rows = '';
  orderedWithDepth(tasks).forEach(({ task: t, depth }, i) => {
    const badge = `<span class="badge p${t.priority}">P${t.priority}</span>`;
    let dlHtml = '';
    if (t.deadline) {
      const d = new Date(t.deadline);
      if (d < now) {
        const diffH = Math.floor((now - d) / 3600000);
        const age = diffH >= 24 ? Math.floor(diffH / 24) + 'd' : diffH + 'h';
        dlHtml = `<span class="dl-overdue">⚠ overdue ${age}</span>`;
      } else if (d.toDateString() === now.toDateString()) {
        const minsLeft = Math.floor((d - now) / 60000);
        const rem = minsLeft < 60
          ? minsLeft + 'min'
          : Math.floor(minsLeft / 60) + 'h ' + (minsLeft % 60) + 'min';
        dlHtml = `<span class="dl-today">today ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} (${rem} left)</span>`;
      } else {
        dlHtml = `<span class="dl-normal">${d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}</span>`;
      }
    }
    const indentHtml = depth > 0 ? '<span class="subtask-indent">└─</span> ' : '';
    const nameCell = indentHtml + escapeHtml(t.name) + (t.recurrence ? ' <span style="color:#aaa;font-size:0.72rem">↻</span>' : '');
    const tdPl = depth > 0 ? ` style="padding-left:${depth * 14}px"` : '';
    const stCls   = 'st-' + escapeHtml(t.status);
    const stLabel = escapeHtml(t.status).replace('_', ' ');
    rows += `<tr>
      <td style="color:#aaa;font-size:0.72rem">${i + 1}</td>
      <td${tdPl}>${nameCell}${dlHtml}</td>
      <td>${badge}</td>
      <td style="color:#888;font-size:0.75rem">${escapeHtml(t.type)}</td>
      <td class="${stCls}">${stLabel}</td>
    </tr>`;
  });
  const wrapper = document.createElement('div');
  wrapper.className = 'msg assistant';
  wrapper.innerHTML = `<table class="chat-task-table">
    <thead><tr><th>#</th><th>Task</th><th>P</th><th>Type</th><th>Status</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
  return wrapper;
}

async function sendMessage() {
  const msg = inputEl.value.trim();
  if (!msg) return;
  inputEl.value = '';
  sendBtn.disabled = true;
  appendMsg('user', msg);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
    });
    const data = await res.json();
    if (data.error) {
      appendMsg('system', 'Error: ' + escapeHtml(data.error));
    } else if (data.is_query) {
      // Show preamble (if any) then a task table
      if (data.response) appendMsg('assistant', data.response);
      messagesEl.appendChild(buildChatTaskTable(data.tasks));
      messagesEl.scrollTop = messagesEl.scrollHeight;
      renderTasks(data.tasks);
    } else {
      appendMsg('assistant', data.response);
      if (data.tasks) renderTasks(data.tasks);
    }
  } catch (e) {
    appendMsg('system', 'Network error: ' + escapeHtml(e.message));
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
    fetchTasks();
    fetchSuggestion();
  }
}

sendBtn.addEventListener('click', sendMessage);
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage(); }
});

// ── Daemon ─────────────────────────────────────────────────────────────────────
const tickBtn = document.getElementById('tick-btn');

function renderNotifications(notifications, lastTick) {
  if (lastTick) {
    const d = new Date(lastTick);
    const diffMs  = Date.now() - d;
    const diffMin = Math.floor(diffMs / 60000);
    const ago = diffMin < 1 ? 'just now' : diffMin + ' min ago';
    document.getElementById('last-tick').textContent = 'Last tick: ' + ago + ' (' + d.toLocaleTimeString() + ')';
  }
  if (!notifications || notifications.length === 0) {
    document.getElementById('notif-list').innerHTML =
      '<span id="daemon-empty">No notifications (no pending tasks, or EOD suppression active).</span>';
    return;
  }
  const html = notifications.map(n => `
    <div class="notif-card">
      <div class="notif-title">${escapeHtml(n.title)}</div>
      <div class="notif-body">${escapeHtml(n.body)}</div>
    </div>`).join('');
  document.getElementById('notif-list').innerHTML = html;
}

async function fetchDaemonStatus() {
  try {
    const res = await fetch('/api/daemon/status');
    const data = await res.json();
    // Check for error response
    if (data && data.error) {
      console.error('fetchDaemonStatus error:', data.error);
      return;
    }
    if (data.last_tick || data.last_notifications) {
      renderNotifications(data.last_notifications, data.last_tick);
    }
  } catch (e) {
    console.error('fetchDaemonStatus exception:', e);
  }
}

// Add "View Report" button if it doesn't exist
let viewReportBtn = document.getElementById('view-report-btn');
let reportHint = document.getElementById('report-hint');
if (!viewReportBtn) {
  // Create button container
  const btnContainer = document.createElement('div');
  btnContainer.style.marginBottom = '1.2rem';
  btnContainer.style.display = 'flex';
  btnContainer.style.alignItems = 'baseline';
  btnContainer.style.gap = '0.5rem';
  btnContainer.style.flexWrap = 'wrap';

  // Move tick-btn into container
  tickBtn.parentNode.insertBefore(btnContainer, tickBtn);
  btnContainer.appendChild(tickBtn);

  // Create View Report button with same style as tick-btn
  viewReportBtn = document.createElement('button');
  viewReportBtn.id = 'view-report-btn';
  viewReportBtn.textContent = 'View Report';
  viewReportBtn.className = 'btn btn-secondary';
  viewReportBtn.style.display = 'none';
  btnContainer.appendChild(viewReportBtn);

  // Create subscription hint
  reportHint = document.createElement('span');
  reportHint.id = 'report-hint';
  reportHint.innerHTML = '(static snapshot — <a href="/api/report" target="_blank" style="color:inherit">~/.kanademinder/summary.html</a>)';
  reportHint.style.fontSize = '0.75rem';
  reportHint.style.color = '#888';
  reportHint.style.lineHeight = '1';
  reportHint.style.display = 'none';
  btnContainer.appendChild(reportHint);
}

let lastHtmlReport = null;

viewReportBtn.addEventListener('click', async () => {
  if (!lastHtmlReport) return;
  // In pywebview mode, open a new window with the report
  if (window.isPyWebView && window.pywebview && window.pywebview.api) {
    try {
      const result = await window.pywebview.api.open_report_window();
      if (!result.success) {
        alert('Error: ' + result.error);
      }
    } catch (e) {
      console.error('Failed to open report window:', e);
      // Fallback: open in new browser tab
      const blob = new Blob([lastHtmlReport], { type: 'text/html' });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
    }
  } else {
    // Web mode: open in new tab
    const blob = new Blob([lastHtmlReport], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
  }
});

tickBtn.addEventListener('click', async () => {
  tickBtn.disabled = true;
  tickBtn.textContent = 'Running…';
  try {
    const res = await fetch('/api/daemon/tick', { method: 'POST' });
    const data = await res.json();
    if (data.error) {
      document.getElementById('notif-list').innerHTML =
        `<span style="color:#c0392b">Error: ${escapeHtml(data.error)}</span>`;
    } else {
      renderNotifications(data.notifications, data.tick_time);
      // Store HTML report and show View Report button + hint
      if (data.html_report) {
        lastHtmlReport = data.html_report;
        viewReportBtn.style.display = 'inline-block';
        if (reportHint) {
          const p = data.report_path || '~/.kanademinder/summary.html';
          reportHint.innerHTML = `(static snapshot — <a href="/api/report" target="_blank" style="color:inherit">${escapeHtml(p)}</a>)`;
          reportHint.style.display = 'inline';
        }
      }
    }
    fetchTasks();
  } catch (e) {
    document.getElementById('notif-list').innerHTML =
      `<span style="color:#c0392b">Network error: ${escapeHtml(e.message)}</span>`;
  } finally {
    tickBtn.disabled = false;
    tickBtn.textContent = 'Run Tick Now';
  }
});

// ── Init ───────────────────────────────────────────────────────────────────────
fetchTasks();
fetchSuggestion();
fetchDaemonStatus();
setInterval(fetchTasks, 30000);
setInterval(fetchSuggestion, 300000); // refresh suggestion every 5 min
