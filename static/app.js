/**
 * HR Intelligence Platform — Vanilla JS Frontend
 * Communicates with FastAPI backend via SSE (Server-Sent Events).
 */

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  sessionId: localStorage.getItem('hr_session_id') || '',
  isLoading: false,
  showToolCalls: true,
  messageCount: 0,
};

// ── DOM refs ───────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const apiKeyInput   = $('apiKeyInput');
const showToolCalls = $('showToolCalls');
const chatInput     = $('chatInput');
const sendBtn       = $('sendBtn');
const sendIcon      = $('sendIcon');
const loadingIcon   = $('loadingIcon');
const messagesEl    = $('messages');
const emptyState    = $('emptyState');
const kpiStrip      = $('kpiStrip');
const dbStatus      = $('dbStatus');
const dbCaption     = $('dbCaption');
const newChatBtn    = $('newChatBtn');
const menuToggle    = $('menuToggle');
const sidebar       = $('sidebar');
const toast         = $('toast');

// ── Init ──────────────────────────────────────────────────────────────────
(async function init() {
  // Restore API key
  apiKeyInput.value = localStorage.getItem('hr_api_key') || '';

  // Load DB stats
  await loadStats();

  // Wire events
  apiKeyInput.addEventListener('input', () => {
    localStorage.setItem('hr_api_key', apiKeyInput.value.trim());
  });

  showToolCalls.addEventListener('change', () => {
    state.showToolCalls = showToolCalls.checked;
  });

  chatInput.addEventListener('input', onInputChange);
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  sendBtn.addEventListener('click', handleSend);
  newChatBtn.addEventListener('click', newConversation);
  menuToggle.addEventListener('click', () => sidebar.classList.toggle('open'));

  // Example / suggestion buttons
  document.querySelectorAll('.example-btn, .suggestion-card').forEach((btn) => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.q;
      if (q) { chatInput.value = q; onInputChange(); handleSend(); }
    });
  });

  // Close sidebar on outside click (mobile)
  document.addEventListener('click', (e) => {
    if (window.innerWidth <= 768 && !sidebar.contains(e.target) && !menuToggle.contains(e.target)) {
      sidebar.classList.remove('open');
    }
  });
})();

// ── Load DB stats ─────────────────────────────────────────────────────────
async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) throw new Error('DB unreachable');
    const stats = await res.json();

    dbStatus.className = 'status-pill ok';
    dbStatus.textContent = '● hr_data.db connected';
    dbCaption.textContent = `${stats.total_employees.toLocaleString()} employees · ${stats.attrition_rate_pct}% attrition`;

    // Build KPI cards
    const danger = stats.attrition_rate_pct > 15 ? 'danger' : 'accent';
    kpiStrip.innerHTML = `
      ${kpiCard('Total Employees', stats.total_employees.toLocaleString(), 'accent')}
      ${kpiCard('Attrited', stats.attrited_employees.toLocaleString(), 'danger')}
      ${kpiCard('Active', stats.active_employees.toLocaleString(), 'success')}
      ${kpiCard('Attrition Rate', stats.attrition_rate_pct + '%', danger)}
      ${kpiCard('Data Columns', (stats.columns || []).length, '')}
    `;
  } catch {
    dbStatus.className = 'status-pill error';
    dbStatus.textContent = '✕ hr_data.db not found';
    dbCaption.textContent = 'Run: python setup_db.py';
  }
}

function kpiCard(label, value, cls) {
  return `<div class="kpi-card">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value ${cls}">${value}</div>
  </div>`;
}

// ── Input handling ─────────────────────────────────────────────────────────
function onInputChange() {
  // Auto-resize textarea
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
  // Enable/disable send button
  sendBtn.disabled = !chatInput.value.trim() || state.isLoading;
}

// ── Send message ───────────────────────────────────────────────────────────
async function handleSend() {
  const text = chatInput.value.trim();
  if (!text || state.isLoading) return;

  const apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    showToast('Please enter your Anthropic API key in the sidebar first.', true);
    return;
  }

  chatInput.value = '';
  chatInput.style.height = 'auto';
  sendBtn.disabled = true;

  // Hide empty state after first message
  if (emptyState) emptyState.style.display = 'none';

  // Ensure message thread exists
  let thread = messagesEl.querySelector('.msg-thread');
  if (!thread) {
    thread = document.createElement('div');
    thread.className = 'msg-thread';
    messagesEl.appendChild(thread);
  }

  // Append user message
  appendUserMsg(thread, text);

  // Create placeholder for assistant
  const assistantRow = createAssistantPlaceholder(thread);
  const contentWrap = assistantRow.querySelector('.msg-content');

  setLoading(true);
  state.messageCount++;

  try {
    await streamChat(text, apiKey, contentWrap);
  } catch (err) {
    appendErrorBubble(contentWrap, err.message || 'An error occurred.');
  } finally {
    // Remove typing indicator if still there
    const typing = contentWrap.querySelector('.bubble-typing');
    if (typing) typing.remove();
    setLoading(false);
  }
}

// ── SSE streaming ──────────────────────────────────────────────────────────
async function streamChat(message, apiKey, contentWrap) {
  const body = JSON.stringify({
    message,
    api_key: apiKey,
    session_id: state.sessionId,
  });

  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let textBubble = null; // the final text bubble element

  // Add typing indicator
  const typingEl = document.createElement('div');
  typingEl.className = 'bubble-typing';
  typingEl.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
  contentWrap.appendChild(typingEl);
  scrollToBottom();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop(); // keep incomplete line

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const raw = line.slice(6).trim();
      if (!raw) continue;

      let event;
      try { event = JSON.parse(raw); } catch { continue; }

      switch (event.type) {
        case 'session':
          state.sessionId = event.session_id;
          localStorage.setItem('hr_session_id', event.session_id);
          break;

        case 'tool_call':
          if (state.showToolCalls) {
            typingEl.remove();
            contentWrap.appendChild(buildToolCard(event));
            scrollToBottom();
            // Re-add typing indicator after tool card
            contentWrap.appendChild(typingEl);
          }
          break;

        case 'chart':
          typingEl.remove();
          contentWrap.appendChild(buildChartCard(event));
          scrollToBottom();
          contentWrap.appendChild(typingEl);
          break;

        case 'final_text':
          typingEl.remove();
          if (event.text) {
            textBubble = document.createElement('div');
            textBubble.className = 'bubble-ai';
            textBubble.textContent = event.text;
            contentWrap.appendChild(textBubble);
            scrollToBottom();
          }
          break;

        case 'error':
          typingEl.remove();
          appendErrorBubble(contentWrap, event.message);
          break;

        case 'done':
          typingEl.remove();
          scrollToBottom();
          break;
      }
    }
  }
}

// ── DOM builders ───────────────────────────────────────────────────────────
function appendUserMsg(thread, text) {
  const row = document.createElement('div');
  row.className = 'msg-row user';
  row.innerHTML = `
    <div class="msg-content">
      <div class="bubble-user">${escHtml(text)}</div>
    </div>
    <div class="avatar user">👤</div>
  `;
  thread.appendChild(row);
  scrollToBottom();
}

function createAssistantPlaceholder(thread) {
  const row = document.createElement('div');
  row.className = 'msg-row assistant';
  row.innerHTML = `
    <div class="avatar ai">🧠</div>
    <div class="msg-content"></div>
  `;
  thread.appendChild(row);
  return row;
}

function buildToolCard(event) {
  const card = document.createElement('div');
  card.className = 'tool-card';

  const expl = event.explanation ? ` — ${event.explanation.slice(0, 90)}` : '';
  const chevronId = `chev-${Math.random().toString(36).slice(2)}`;
  const bodyId = `body-${Math.random().toString(36).slice(2)}`;

  let bodyContent = '<p class="label">Inputs</p><pre>No details</pre>';
  if (event.sql) {
    bodyContent = `<p class="label">SQL Query</p><pre>${escHtml(event.sql)}</pre>`;
  } else if (event.inputs && Object.keys(event.inputs).length) {
    bodyContent = `<p class="label">Inputs</p><pre>${escHtml(JSON.stringify(event.inputs, null, 2))}</pre>`;
  }

  card.innerHTML = `
    <div class="tool-card-header" onclick="toggleToolCard('${bodyId}', '${chevronId}')">
      <span class="tool-badge">⚡ ${escHtml(event.name || 'tool')}</span>
      <span class="tool-explanation">${escHtml(expl)}</span>
      <svg id="${chevronId}" class="tool-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
    </div>
    <div id="${bodyId}" class="tool-card-body">${bodyContent}</div>
  `;
  return card;
}

function buildChartCard(event) {
  const card = document.createElement('div');
  card.className = 'chart-card';
  const chartId = `chart-${Math.random().toString(36).slice(2)}`;

  if (event.title) {
    const title = document.createElement('div');
    title.className = 'chart-title';
    title.textContent = event.title;
    card.appendChild(title);
  }

  const container = document.createElement('div');
  container.className = 'chart-container';
  container.id = chartId;
  card.appendChild(container);

  // Render Plotly chart after DOM insertion
  requestAnimationFrame(() => {
    if (typeof Plotly === 'undefined') {
      container.textContent = '(Plotly not loaded — chart unavailable)';
      return;
    }
    try {
      const fig = JSON.parse(event.chart_json);
      // Apply consistent layout overrides
      const layout = Object.assign({
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { family: 'Inter, sans-serif', size: 12, color: '#475569' },
        margin: { t: 20, r: 16, b: 40, l: 40 },
        showlegend: true,
        legend: { orientation: 'h', y: -0.25 },
      }, fig.layout || {});
      Plotly.newPlot(chartId, fig.data || [], layout, { responsive: true, displayModeBar: false });
    } catch (e) {
      container.textContent = `Chart render error: ${e.message}`;
    }
  });

  return card;
}

function appendErrorBubble(parent, msg) {
  const el = document.createElement('div');
  el.style.cssText = 'padding:10px 14px; background:#FEF2F2; border:1px solid #FECACA; border-radius:10px; color:#DC2626; font-size:13px;';
  el.textContent = `⚠ ${msg}`;
  parent.appendChild(el);
  scrollToBottom();
}

// ── Tool card toggle ───────────────────────────────────────────────────────
window.toggleToolCard = function(bodyId, chevronId) {
  const body = document.getElementById(bodyId);
  const chev = document.getElementById(chevronId);
  body.classList.toggle('open');
  chev.classList.toggle('open');
};

// ── New conversation ───────────────────────────────────────────────────────
async function newConversation() {
  if (state.sessionId) {
    await fetch('/api/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId }),
    }).catch(() => {});
  }
  state.sessionId = '';
  localStorage.removeItem('hr_session_id');
  state.messageCount = 0;

  // Restore empty state
  const thread = messagesEl.querySelector('.msg-thread');
  if (thread) thread.remove();
  if (emptyState) emptyState.style.display = '';

  sidebar.classList.remove('open');
}

// ── Loading state ─────────────────────────────────────────────────────────
function setLoading(loading) {
  state.isLoading = loading;
  chatInput.disabled = loading;
  sendBtn.disabled = loading || !chatInput.value.trim();

  if (loading) {
    sendIcon.classList.add('hidden');
    loadingIcon.classList.remove('hidden');
  } else {
    sendIcon.classList.remove('hidden');
    loadingIcon.classList.add('hidden');
    chatInput.disabled = false;
    chatInput.focus();
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────
function scrollToBottom() {
  messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

let toastTimer;
function showToast(msg, isError = false) {
  toast.textContent = msg;
  toast.className = `toast${isError ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.classList.add('hidden'); }, 4000);
}
