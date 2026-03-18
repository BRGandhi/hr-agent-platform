/**
 * HR Intelligence Platform - Vanilla JS frontend
 * Includes an auth gate plus provider-agnostic model selection.
 */

const state = {
  sessionId: localStorage.getItem('hr_session_id') || '',
  isLoading: false,
  showToolCalls: localStorage.getItem('hr_show_tool_calls') !== 'false',
  provider: localStorage.getItem('hr_provider') || '',
  model: localStorage.getItem('hr_model') || '',
  baseUrl: localStorage.getItem('hr_base_url') || '',
  providerOptions: [],
  authRequired: true,
  devSsoEnabled: false,
  authProviders: [],
  user: null,
};

const $ = (id) => document.getElementById(id);
const authShell = $('authShell');
const authButtons = $('authButtons');
const authNote = $('authNote');
const appLayout = $('appLayout');
const apiKeyInput = $('apiKeyInput');
const providerSelect = $('providerSelect');
const modelInput = $('modelInput');
const baseUrlInput = $('baseUrlInput');
const showToolCalls = $('showToolCalls');
const chatInput = $('chatInput');
const sendBtn = $('sendBtn');
const sendIcon = $('sendIcon');
const loadingIcon = $('loadingIcon');
const messagesEl = $('messages');
const emptyState = $('emptyState');
const kpiStrip = $('kpiStrip');
const dbStatus = $('dbStatus');
const dbCaption = $('dbCaption');
const newChatBtn = $('newChatBtn');
const menuToggle = $('menuToggle');
const sidebar = $('sidebar');
const toast = $('toast');
const topbarSub = $('topbarSub');
const userBadge = $('userBadge');
const logoutBtn = $('logoutBtn');

(async function init() {
  showToolCalls.checked = state.showToolCalls;
  wireUiEvents();

  await loadRuntimeConfig();
  await loadAuthConfig();
  await loadAuthSession();

  if (state.authRequired && !state.user) {
    showAuthShell();
    return;
  }

  revealApp();
})();

function wireUiEvents() {
  providerSelect.addEventListener('change', onProviderChange);
  modelInput.addEventListener('input', () => {
    state.model = modelInput.value.trim();
    localStorage.setItem('hr_model', state.model);
    updateTopbarSub();
  });
  baseUrlInput.addEventListener('input', () => {
    state.baseUrl = baseUrlInput.value.trim();
    localStorage.setItem('hr_base_url', state.baseUrl);
  });
  showToolCalls.addEventListener('change', () => {
    state.showToolCalls = showToolCalls.checked;
    localStorage.setItem('hr_show_tool_calls', String(state.showToolCalls));
  });
  chatInput.addEventListener('input', onInputChange);
  chatInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  });
  sendBtn.addEventListener('click', handleSend);
  newChatBtn.addEventListener('click', newConversation);
  menuToggle.addEventListener('click', () => sidebar.classList.toggle('open'));
  logoutBtn.addEventListener('click', logout);

  document.querySelectorAll('.example-btn, .suggestion-card').forEach((button) => {
    button.addEventListener('click', () => {
      const question = button.dataset.q;
      if (question) {
        chatInput.value = question;
        onInputChange();
        handleSend();
      }
    });
  });

  document.addEventListener('click', (event) => {
    if (window.innerWidth <= 768 && !sidebar.contains(event.target) && !menuToggle.contains(event.target)) {
      sidebar.classList.remove('open');
    }
  });
}

async function loadRuntimeConfig() {
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error('Could not load runtime config');
    const config = await response.json();
    state.providerOptions = config.provider_options || [];

    providerSelect.innerHTML = state.providerOptions
      .map((option) => `<option value="${escAttr(option.id)}">${escHtml(option.label)}</option>`)
      .join('');

    state.provider = state.provider || config.default_provider || 'anthropic';
    state.model = state.model || (
      state.provider === 'anthropic'
        ? (config.default_model || '')
        : (config.default_openai_compat_model || '')
    );
    state.baseUrl = state.baseUrl || (
      state.provider === 'anthropic'
        ? ''
        : (config.default_openai_compat_base_url || '')
    );

    providerSelect.value = state.provider;
    modelInput.value = state.model;
    baseUrlInput.value = state.baseUrl;
    syncProviderFields();
    updateTopbarSub();
  } catch (error) {
    showToast(error.message || 'Could not load app configuration.', true);
  }
}

async function loadAuthConfig() {
  try {
    const response = await fetch('/api/auth/config');
    if (!response.ok) throw new Error('Could not load auth configuration');
    const config = await response.json();
    state.authRequired = config.auth_required;
    state.devSsoEnabled = config.dev_sso_enabled;
    state.authProviders = config.providers || [];
    renderAuthButtons();
  } catch (error) {
    showToast(error.message || 'Could not load auth settings.', true);
  }
}

async function loadAuthSession() {
  try {
    const response = await fetch('/api/auth/session');
    if (!response.ok) throw new Error('Could not load auth session');
    const payload = await response.json();
    state.user = payload.user || null;
    syncAuthUi();
  } catch (error) {
    showToast(error.message || 'Could not load auth session.', true);
  }
}

function renderAuthButtons() {
  authButtons.innerHTML = state.authProviders.map((provider) => `
    <button class="auth-btn" data-provider="${escAttr(provider.id)}">
      <span class="auth-btn-provider">
        <span class="auth-provider-badge">${escHtml(provider.label.slice(0, 2).toUpperCase())}</span>
        <span>Continue with ${escHtml(provider.label)}</span>
      </span>
      <span>→</span>
    </button>
  `).join('');

  authButtons.querySelectorAll('.auth-btn').forEach((button) => {
    button.addEventListener('click', () => loginWithProvider(button.dataset.provider));
  });

  authNote.textContent = state.devSsoEnabled
    ? 'Local dev SSO mode is enabled. These buttons create a secure local session cookie so you can test the sign-in flow now.'
    : 'Connect a real OIDC / SAML provider next. The sign-in shell is ready to sit on top of the app.';
}

async function loginWithProvider(provider) {
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    const payload = await response.json();
    state.user = payload.user || null;
    syncAuthUi();
    revealApp();
    showToast(`Signed in with ${payload.user?.provider || provider}`);
  } catch (error) {
    showToast(error.message || 'Sign-in failed.', true);
  }
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {});
  state.user = null;
  state.sessionId = '';
  localStorage.removeItem('hr_session_id');
  const thread = messagesEl.querySelector('.msg-thread');
  if (thread) thread.remove();
  if (emptyState) emptyState.style.display = '';
  syncAuthUi();
  showAuthShell();
}

function syncAuthUi() {
  if (state.user) {
    userBadge.textContent = `${state.user.name} · ${state.user.provider}`;
    userBadge.classList.remove('hidden');
    logoutBtn.classList.remove('hidden');
  } else {
    userBadge.classList.add('hidden');
    logoutBtn.classList.add('hidden');
    userBadge.textContent = '';
  }
}

function showAuthShell() {
  authShell.classList.remove('hidden');
  appLayout.classList.add('hidden');
}

async function revealApp() {
  authShell.classList.add('hidden');
  appLayout.classList.remove('hidden');
  await loadStats();
  onInputChange();
}

async function loadStats() {
  try {
    const response = await fetch('/api/stats');
    if (!response.ok) {
      if (response.status === 401) {
        state.user = null;
        syncAuthUi();
        showAuthShell();
        return;
      }
      throw new Error('DB unreachable');
    }

    const stats = await response.json();
    dbStatus.className = 'status-pill ok';
    dbStatus.textContent = 'Connected';
    dbCaption.textContent = `${stats.total_employees.toLocaleString()} employees · ${stats.attrition_rate_pct}% attrition`;

    const danger = stats.attrition_rate_pct > 15 ? 'danger' : 'accent';
    kpiStrip.innerHTML = `
      ${kpiCard('Total Employees', stats.total_employees.toLocaleString(), 'accent')}
      ${kpiCard('Attrited', stats.attrited_employees.toLocaleString(), 'danger')}
      ${kpiCard('Active', stats.active_employees.toLocaleString(), 'success')}
      ${kpiCard('Attrition Rate', `${stats.attrition_rate_pct}%`, danger)}
      ${kpiCard('Data Columns', (stats.columns || []).length, '')}
    `;
  } catch {
    dbStatus.className = 'status-pill error';
    dbStatus.textContent = 'DB unavailable';
    dbCaption.textContent = 'Run: python setup_db.py';
  }
}

function kpiCard(label, value, cls) {
  return `<div class="kpi-card">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value ${cls}">${value}</div>
  </div>`;
}

function onProviderChange() {
  state.provider = providerSelect.value;
  localStorage.setItem('hr_provider', state.provider);

  const providerOption = getProviderOption(state.provider);
  state.model = providerOption?.model_placeholder || '';
  state.baseUrl = state.provider === 'anthropic' ? '' : (providerOption?.base_url_placeholder || '');

  modelInput.value = state.model;
  baseUrlInput.value = state.baseUrl;
  localStorage.setItem('hr_model', state.model);
  localStorage.setItem('hr_base_url', state.baseUrl);
  syncProviderFields();
  updateTopbarSub();
}

function syncProviderFields() {
  const providerOption = getProviderOption(state.provider);
  modelInput.placeholder = providerOption?.model_placeholder || 'Model name';
  baseUrlInput.placeholder = providerOption?.base_url_placeholder || 'Base URL';
  apiKeyInput.placeholder = providerOption?.api_key_placeholder || 'API key';
  baseUrlInput.style.display = state.provider === 'anthropic' ? 'none' : 'block';
}

function getProviderOption(providerId) {
  return state.providerOptions.find((option) => option.id === providerId);
}

function updateTopbarSub() {
  const providerLabel = state.provider === 'anthropic' ? 'Anthropic' : 'OpenAI-compatible';
  const modelLabel = state.model || 'model not selected';
  topbarSub.textContent = `Ask anything about your workforce · ${providerLabel} · ${modelLabel}`;
}

function onInputChange() {
  chatInput.style.height = 'auto';
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 120)}px`;
  sendBtn.disabled = !chatInput.value.trim() || state.isLoading;
}

async function handleSend() {
  if (state.authRequired && !state.user) {
    showAuthShell();
    return;
  }

  const text = chatInput.value.trim();
  if (!text || state.isLoading) return;

  const payload = {
    message: text,
    api_key: apiKeyInput.value.trim(),
    provider: state.provider,
    model: modelInput.value.trim(),
    base_url: baseUrlInput.value.trim(),
    session_id: state.sessionId,
  };

  chatInput.value = '';
  chatInput.style.height = 'auto';
  sendBtn.disabled = true;
  if (emptyState) emptyState.style.display = 'none';

  let thread = messagesEl.querySelector('.msg-thread');
  if (!thread) {
    thread = document.createElement('div');
    thread.className = 'msg-thread';
    messagesEl.appendChild(thread);
  }

  appendUserMsg(thread, text);
  const assistantRow = createAssistantPlaceholder(thread);
  const contentWrap = assistantRow.querySelector('.msg-content');

  setLoading(true);

  try {
    await streamChat(payload, contentWrap);
  } catch (error) {
    appendErrorBubble(contentWrap, error.message || 'An error occurred.');
  } finally {
    const typing = contentWrap.querySelector('.bubble-typing');
    if (typing) typing.remove();
    setLoading(false);
  }
}

async function streamChat(payload, contentWrap) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    if (response.status === 401) {
      state.user = null;
      syncAuthUi();
      showAuthShell();
      throw new Error('Please sign in to continue.');
    }
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

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
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const raw = line.slice(6).trim();
      if (!raw) continue;

      let event;
      try {
        event = JSON.parse(raw);
      } catch {
        continue;
      }

      switch (event.type) {
        case 'session':
          state.sessionId = event.session_id;
          localStorage.setItem('hr_session_id', event.session_id);
          break;
        case 'tool_call':
          if (state.showToolCalls) {
            typingEl.remove();
            contentWrap.appendChild(buildToolCard(event));
            contentWrap.appendChild(typingEl);
            scrollToBottom();
          }
          break;
        case 'tool_result':
          if (event.table_data) {
            typingEl.remove();
            contentWrap.appendChild(buildTableCard('Query Preview', event.table_data));
            contentWrap.appendChild(typingEl);
            scrollToBottom();
          }
          break;
        case 'chart':
          typingEl.remove();
          contentWrap.appendChild(buildChartCard(event));
          contentWrap.appendChild(typingEl);
          scrollToBottom();
          break;
        case 'final_text':
          typingEl.remove();
          if (event.text) {
            contentWrap.appendChild(buildMarkdownBubble(event.text));
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

  const explanation = event.explanation ? ` - ${event.explanation.slice(0, 90)}` : '';
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
      <span class="tool-badge">Tool · ${escHtml(event.name || 'tool')}</span>
      <span class="tool-explanation">${escHtml(explanation)}</span>
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

  requestAnimationFrame(() => {
    if (typeof Plotly === 'undefined') {
      container.textContent = '(Plotly not loaded - chart unavailable)';
      return;
    }

    try {
      const fig = JSON.parse(event.chart_json);
      const layout = Object.assign({
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { family: 'Inter, sans-serif', size: 12, color: '#475569' },
        margin: { t: 20, r: 16, b: 40, l: 40 },
        showlegend: true,
        legend: { orientation: 'h', y: -0.25 },
      }, fig.layout || {});
      Plotly.newPlot(chartId, fig.data || [], layout, { responsive: true, displayModeBar: false });
    } catch (error) {
      container.textContent = `Chart render error: ${error.message}`;
    }
  });

  return card;
}

function buildTableCard(title, rows) {
  const card = document.createElement('div');
  card.className = 'table-wrap';

  if (!Array.isArray(rows) || !rows.length) {
    card.innerHTML = '<div class="table-title">No rows returned</div>';
    return card;
  }

  const columns = Object.keys(rows[0]);
  const head = columns.map((column) => `<th>${escHtml(column)}</th>`).join('');
  const body = rows.map((row) => {
    const cells = columns.map((column) => `<td>${escHtml(formatCell(row[column]))}</td>`).join('');
    return `<tr>${cells}</tr>`;
  }).join('');

  card.innerHTML = `
    <div class="table-title">${escHtml(title)}</div>
    <div class="table-scroll">
      <table>
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
  return card;
}

function buildMarkdownBubble(text) {
  const bubble = document.createElement('div');
  bubble.className = 'bubble-ai';
  bubble.innerHTML = markdownToHtml(text);
  return bubble;
}

function markdownToHtml(markdown) {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
  const html = [];
  let inCodeBlock = false;
  let codeFence = [];
  let listType = null;
  let paragraph = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${renderInline(paragraph.join(' '))}</p>`);
    paragraph = [];
  };

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.startsWith('```')) {
      flushParagraph();
      closeList();
      if (inCodeBlock) {
        html.push(`<pre><code>${escHtml(codeFence.join('\n'))}</code></pre>`);
        codeFence = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeFence.push(rawLine);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }

    const bulletMatch = line.match(/^[-*]\s+(.*)$/);
    if (bulletMatch) {
      flushParagraph();
      if (listType !== 'ul') {
        closeList();
        html.push('<ul>');
        listType = 'ul';
      }
      html.push(`<li>${renderInline(bulletMatch[1])}</li>`);
      continue;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listType !== 'ol') {
        closeList();
        html.push('<ol>');
        listType = 'ol';
      }
      html.push(`<li>${renderInline(orderedMatch[1])}</li>`);
      continue;
    }

    closeList();
    paragraph.push(line.trim());
  }

  flushParagraph();
  closeList();

  if (inCodeBlock) {
    html.push(`<pre><code>${escHtml(codeFence.join('\n'))}</code></pre>`);
  }

  return html.join('');
}

function renderInline(text) {
  let rendered = escHtml(text);
  rendered = rendered.replace(/`([^`]+)`/g, '<code>$1</code>');
  rendered = rendered.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  return rendered;
}

function formatCell(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function appendErrorBubble(parent, message) {
  const el = document.createElement('div');
  el.style.cssText = 'padding:10px 14px; background:#FEF2F2; border:1px solid #FECACA; border-radius:10px; color:#DC2626; font-size:13px;';
  el.textContent = `Warning: ${message}`;
  parent.appendChild(el);
  scrollToBottom();
}

window.toggleToolCard = function(bodyId, chevronId) {
  const body = document.getElementById(bodyId);
  const chevron = document.getElementById(chevronId);
  body.classList.toggle('open');
  chevron.classList.toggle('open');
};

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
  const thread = messagesEl.querySelector('.msg-thread');
  if (thread) thread.remove();
  if (emptyState) emptyState.style.display = '';
  sidebar.classList.remove('open');
}

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

function scrollToBottom() {
  messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
}

function escHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escAttr(value) {
  return escHtml(value);
}

let toastTimer;
function showToast(message, isError = false) {
  toast.textContent = message;
  toast.className = `toast${isError ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.classList.add('hidden'); }, 4000);
}
