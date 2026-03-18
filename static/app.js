/**
 * HR Intelligence Platform frontend.
 * Enforces the auth shell, scope-aware UX, and banner-based LLM connection flow.
 */

const state = {
  sessionId: localStorage.getItem("hr_session_id") || "",
  isLoading: false,
  showToolCalls: localStorage.getItem("hr_show_tool_calls") !== "false",
  provider: localStorage.getItem("hr_provider") || "",
  model: localStorage.getItem("hr_model") || "",
  baseUrl: localStorage.getItem("hr_base_url") || "",
  providerOptions: [],
  authRequired: true,
  devSsoEnabled: false,
  authProviders: [],
  user: null,
  accessProfile: null,
};

const $ = (id) => document.getElementById(id);
const authShell = $("authShell");
const authButtons = $("authButtons");
const authNote = $("authNote");
const appLayout = $("appLayout");
const llmModal = $("llmModal");
const llmModalBackdrop = $("llmModalBackdrop");
const closeLlmModalBtn = $("closeLlmModal");
const providerSelect = $("providerSelect");
const modelInput = $("modelInput");
const baseUrlLabel = $("baseUrlLabel");
const baseUrlInput = $("baseUrlInput");
const apiKeyInput = $("apiKeyInput");
const showToolCalls = $("showToolCalls");
const chatInput = $("chatInput");
const sendBtn = $("sendBtn");
const sendIcon = $("sendIcon");
const loadingIcon = $("loadingIcon");
const messagesEl = $("messages");
const emptyState = $("emptyState");
const kpiStrip = $("kpiStrip");
const dbStatus = $("dbStatus");
const dbCaption = $("dbCaption");
const examplesEl = $("examples");
const historyList = $("historyList");
const newChatBtn = $("newChatBtn");
const menuToggle = $("menuToggle");
const sidebar = $("sidebar");
const toast = $("toast");
const topbarSub = $("topbarSub");
const scopePill = $("scopePill");
const connectLlmBtn = $("connectLlmBtn");
const userBadge = $("userBadge");
const logoutBtn = $("logoutBtn");
const suggestionGrid = document.querySelector(".suggestion-grid");
const metricExamplesEl = $("metricExamples");

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

  await revealApp();
})();

function wireUiEvents() {
  providerSelect.addEventListener("change", onProviderChange);
  modelInput.addEventListener("input", () => {
    state.model = modelInput.value.trim();
    localStorage.setItem("hr_model", state.model);
    updateConnectionButton();
    updateTopbarSub();
  });
  baseUrlInput.addEventListener("input", () => {
    state.baseUrl = baseUrlInput.value.trim();
    localStorage.setItem("hr_base_url", state.baseUrl);
  });
  showToolCalls.addEventListener("change", () => {
    state.showToolCalls = showToolCalls.checked;
    localStorage.setItem("hr_show_tool_calls", String(state.showToolCalls));
  });
  chatInput.addEventListener("input", onInputChange);
  chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  });
  sendBtn.addEventListener("click", handleSend);
  newChatBtn.addEventListener("click", newConversation);
  menuToggle.addEventListener("click", () => sidebar.classList.toggle("open"));
  logoutBtn.addEventListener("click", logout);
  connectLlmBtn.addEventListener("click", openLlmModal);
  closeLlmModalBtn.addEventListener("click", closeLlmModal);
  llmModalBackdrop.addEventListener("click", closeLlmModal);

  document.addEventListener("click", (event) => {
    if (window.innerWidth <= 768 && !sidebar.contains(event.target) && !menuToggle.contains(event.target)) {
      sidebar.classList.remove("open");
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeLlmModal();
    }
  });
}

async function loadRuntimeConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error("Could not load runtime config");

    const config = await response.json();
    state.providerOptions = config.provider_options || [];

    providerSelect.innerHTML = state.providerOptions
      .map((option) => `<option value="${escAttr(option.id)}">${escHtml(option.label)}</option>`)
      .join("");

    state.provider = state.provider || config.default_provider || "anthropic";
    state.model = state.model || defaultModelForProvider(config, state.provider);
    state.baseUrl = state.baseUrl || defaultBaseUrlForProvider(config, state.provider);

    providerSelect.value = state.provider;
    modelInput.value = state.model;
    baseUrlInput.value = state.baseUrl;
    syncProviderFields();
    updateConnectionButton();
    updateTopbarSub();
  } catch (error) {
    showToast(error.message || "Could not load app configuration.", true);
  }
}

async function loadAuthConfig() {
  try {
    const response = await fetch("/api/auth/config");
    if (!response.ok) throw new Error("Could not load auth configuration");

    const config = await response.json();
    state.authRequired = config.auth_required;
    state.devSsoEnabled = config.dev_sso_enabled;
    state.authProviders = config.providers || [];
    renderAuthButtons();
  } catch (error) {
    showToast(error.message || "Could not load auth settings.", true);
  }
}

async function loadAuthSession() {
  try {
    const response = await fetch("/api/auth/session");
    if (!response.ok) throw new Error("Could not load auth session");

    const payload = await response.json();
    state.user = payload.user || null;
    syncAuthUi();
  } catch (error) {
    showToast(error.message || "Could not load auth session.", true);
  }
}

async function loadAccessSummary() {
  try {
    const response = await fetch("/api/me/access");
    if (!response.ok) {
      if (response.status === 401) {
        handleUnauthorized();
        return false;
      }
      throw new Error("Could not load access profile");
    }

    const payload = await response.json();
    state.user = payload.user || state.user;
    state.accessProfile = payload.access_profile || null;
    syncAuthUi();
    syncScopeUi();
    renderScopedPrompts();
    updateTopbarSub();
    return true;
  } catch (error) {
    showToast(error.message || "Could not load access profile.", true);
    return false;
  }
}

function renderAuthButtons() {
  authButtons.innerHTML = state.authProviders.map((provider) => `
    <button class="auth-btn" data-provider="${escAttr(provider.id)}">
      <span class="auth-btn-provider">
        <span class="auth-provider-badge">${escHtml(provider.label.slice(0, 2).toUpperCase())}</span>
        <span>Continue with ${escHtml(provider.label)}</span>
      </span>
      <span>&rarr;</span>
    </button>
  `).join("");

  authButtons.querySelectorAll(".auth-btn").forEach((button) => {
    button.addEventListener("click", () => loginWithProvider(button.dataset.provider));
  });

  authNote.textContent = state.devSsoEnabled
    ? "Local dev SSO mode is enabled. These buttons create a secure local session cookie so you can test role-based access now."
    : "Connect a real OIDC or SAML provider next. The sign-in shell is ready to sit on top of the governed HR experience.";
}

async function loginWithProvider(provider) {
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    const payload = await response.json();
    state.user = payload.user || null;
    syncAuthUi();
    await revealApp();
    showToast(`Signed in with ${payload.user?.provider || provider}`);
  } catch (error) {
    showToast(error.message || "Sign-in failed.", true);
  }
}

async function logout() {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
  state.user = null;
  state.accessProfile = null;
  state.sessionId = "";
  localStorage.removeItem("hr_session_id");
  resetConversationUi();
  syncAuthUi();
  syncScopeUi();
  showAuthShell();
}

function syncAuthUi() {
  if (state.user) {
    const role = state.accessProfile?.role || state.user.role || "User";
    userBadge.textContent = `${state.user.name} | ${role}`;
    userBadge.classList.remove("hidden");
    logoutBtn.classList.remove("hidden");
  } else {
    userBadge.textContent = "";
    userBadge.classList.add("hidden");
    logoutBtn.classList.add("hidden");
  }
}

function syncScopeUi() {
  if (state.accessProfile) {
    const departments = state.accessProfile.allowed_departments || [];
    scopePill.textContent = departments.length
      ? `Business Units | ${departments.join(", ")}`
      : "Business Units | Enterprise";
    scopePill.classList.remove("hidden");
  } else {
    scopePill.textContent = "";
    scopePill.classList.add("hidden");
  }
}

function showAuthShell() {
  closeLlmModal();
  authShell.classList.remove("hidden");
  appLayout.classList.add("hidden");
}

async function revealApp() {
  const accessLoaded = await loadAccessSummary();
  if (!accessLoaded && state.authRequired) {
    return;
  }

  authShell.classList.add("hidden");
  appLayout.classList.remove("hidden");
  await loadStats();
  await loadHistory();
  onInputChange();
}

async function loadStats() {
  try {
    const response = await fetch("/api/stats");
    if (!response.ok) {
      if (response.status === 401) {
        handleUnauthorized();
        return;
      }
      throw new Error("DB unreachable");
    }

    const stats = await response.json();
    state.accessProfile = stats.access_profile || state.accessProfile;
    syncAuthUi();
    syncScopeUi();
    renderScopedPrompts();
    updateTopbarSub();

    dbStatus.className = "status-pill ok";
    dbStatus.textContent = "Connected";
    dbCaption.textContent = buildDbCaption(stats);
    kpiStrip.innerHTML = buildKpiStrip(stats);
  } catch {
    dbStatus.className = "status-pill error";
    dbStatus.textContent = "DB unavailable";
    dbCaption.textContent = "Run: python setup_db.py";
    kpiStrip.innerHTML = "";
  }
}

function buildDbCaption(stats) {
  const metrics = normalizeMetrics(stats.allowed_metrics);
  const departments = (stats.allowed_departments || []).length
    ? stats.allowed_departments.join(", ")
    : "Enterprise";
  const metricsLabel = metrics.length ? metrics.join(", ") : "scoped metrics";
  return `Business Units | ${departments} | ${metricsLabel}`;
}

function buildKpiStrip(stats) {
  const cards = [];
  const allowedMetrics = new Set(normalizeMetrics(stats.allowed_metrics));
  const canSeeHeadcount = allowedMetrics.has("all") || allowedMetrics.has("headcount");
  const canSeeAttrition = allowedMetrics.has("all") || allowedMetrics.has("attrition");
  const departments = stats.allowed_departments || [];

  cards.push(scopeSummaryCard(departments));
  cards.push(kpiCard("Business Unit Count", departments.length ? String(departments.length) : "Enterprise", ""));

  if (canSeeHeadcount) {
    cards.push(kpiCard("Headcount", Number(stats.total_employees || 0).toLocaleString(), "accent"));
    cards.push(kpiCard("Active", Number(stats.active_employees || 0).toLocaleString(), "success"));
  }

  if (canSeeAttrition) {
    cards.push(kpiCard("Attrited", Number(stats.attrited_employees || 0).toLocaleString(), "danger"));
    cards.push(kpiCard("Attrition Rate", `${stats.attrition_rate_pct || 0}%`, (stats.attrition_rate_pct || 0) > 15 ? "danger" : "accent"));
  }

  if (allowedMetrics.has("all")) {
    cards.push(kpiCard("Data Columns", String((stats.columns || []).length), ""));
  }

  return cards.join("");
}

function kpiCard(label, value, cls) {
  return `<div class="kpi-card">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value ${cls}">${value}</div>
  </div>`;
}

function scopeSummaryCard(departments) {
  const label = departments.length ? departments.join(", ") : "Enterprise";
  return `<div class="kpi-card scope-summary-card">
    <div class="kpi-label">Business Units</div>
    <div class="kpi-value accent scope-summary-value">${escHtml(label)}</div>
  </div>`;
}

function renderScopedPrompts() {
  const profile = state.accessProfile;
  const scopeName = profile?.scope_name || "my scope";
  const departments = profile?.allowed_departments || [];
  const hasAllMetrics = (profile?.allowed_metrics || []).includes("all");
  const allowed = new Set(normalizeMetrics(profile?.allowed_metrics || []));
  const prompts = [];

  prompts.push(`What is the headcount for ${scopeName}?`);
  prompts.push(`Generate an active headcount report for ${scopeName}`);

  if (hasAllMetrics || allowed.has("attrition")) {
    prompts.push(`What is the attrition rate for ${scopeName}?`);
    prompts.push(`Show attrition by department for ${scopeName}`);
    prompts.push(`Generate an attrition report for ${scopeName}`);
  }
  if (hasAllMetrics || allowed.has("policy")) {
    prompts.push("Which HR access policy applies to my role?");
  }
  if (hasAllMetrics || allowed.has("tenure")) {
    prompts.push(`What does tenure look like in ${scopeName}?`);
  }
  if (hasAllMetrics || allowed.has("satisfaction")) {
    prompts.push(`Are there satisfaction risks in ${scopeName}?`);
  }

  if (departments.length === 1) {
    prompts[0] = `What is the headcount for ${departments[0]}?`;
  }

  const uniquePrompts = prompts.slice(0, 5);
  renderPromptButtons(examplesEl, "example-btn", uniquePrompts);
  renderPromptButtons(suggestionGrid, "suggestion-card", uniquePrompts.slice(0, 4), true);
  renderMetricExamples(profile);
}

function renderMetricExamples(profile) {
  if (!metricExamplesEl) return;

  const hasAllMetrics = (profile?.allowed_metrics || []).includes("all");
  const allowed = new Set(normalizeMetrics(profile?.allowed_metrics || []));
  const metrics = [];

  if (hasAllMetrics || allowed.has("headcount")) {
    metrics.push("Headcount");
    metrics.push("Active workforce");
    metrics.push("Department mix");
  }
  if (hasAllMetrics || allowed.has("attrition")) {
    metrics.push("Attrition rate");
    metrics.push("Attrited employee roster");
    metrics.push("Attrition by department");
  }
  if (hasAllMetrics || allowed.has("tenure")) {
    metrics.push("Tenure mix");
  }
  if (hasAllMetrics || allowed.has("satisfaction")) {
    metrics.push("Satisfaction pulse");
  }
  if (hasAllMetrics || allowed.has("compensation")) {
    metrics.push("Compensation bands");
  }
  if (hasAllMetrics || allowed.has("policy")) {
    metrics.push("Access policy guidance");
  }

  metricExamplesEl.innerHTML = metrics.map((metric) => `<div class="metric-chip">${escHtml(metric)}</div>`).join("");
}

function renderPromptButtons(container, className, prompts, rich = false) {
  if (!container) return;

  if (rich) {
    container.innerHTML = prompts.map((prompt) => `
      <button class="${className}" data-q="${escAttr(prompt)}">
        <span class="suggestion-icon">${suggestionIcon(prompt)}</span>
        <span>${escHtml(prompt)}</span>
      </button>
    `).join("");
  } else {
    container.innerHTML = prompts.map((prompt) => `
      <button class="${className}" data-q="${escAttr(prompt)}">${escHtml(prompt)}</button>
    `).join("");
  }

  container.querySelectorAll(`[data-q]`).forEach((button) => {
    button.addEventListener("click", () => {
      const question = button.dataset.q;
      if (!question) return;
      chatInput.value = question;
      onInputChange();
      handleSend();
    });
  });
}

function suggestionIcon(prompt) {
  const lowered = prompt.toLowerCase();
  if (lowered.includes("report")) return "Report";
  if (lowered.includes("policy")) return "Policy";
  if (lowered.includes("attrition")) return "Risk";
  if (lowered.includes("tenure")) return "Trend";
  if (lowered.includes("satisfaction")) return "Pulse";
  return "KPI";
}

function onProviderChange() {
  state.provider = providerSelect.value;
  localStorage.setItem("hr_provider", state.provider);

  const providerOption = getProviderOption(state.provider);
  state.model = providerOption?.model_placeholder || "";
  state.baseUrl = state.provider === "anthropic" ? "" : (providerOption?.base_url_placeholder || "");

  modelInput.value = state.model;
  baseUrlInput.value = state.baseUrl;
  localStorage.setItem("hr_model", state.model);
  localStorage.setItem("hr_base_url", state.baseUrl);
  syncProviderFields();
  updateConnectionButton();
  updateTopbarSub();
}

function syncProviderFields() {
  const providerOption = getProviderOption(state.provider);
  modelInput.placeholder = providerOption?.model_placeholder || "Model name";
  baseUrlInput.placeholder = providerOption?.base_url_placeholder || "Base URL";
  apiKeyInput.placeholder = providerOption?.api_key_placeholder || "Credential";

  const showBaseUrl = state.provider !== "anthropic";
  baseUrlLabel.style.display = showBaseUrl ? "block" : "none";
  baseUrlInput.style.display = showBaseUrl ? "block" : "none";
}

function getProviderOption(providerId) {
  return state.providerOptions.find((option) => option.id === providerId);
}

function openLlmModal() {
  llmModal.classList.remove("hidden");
}

function closeLlmModal() {
  llmModal.classList.add("hidden");
}

function updateConnectionButton() {
  const label = providerLabel(state.provider);
  const modelLabel = state.model || "Select model";
  connectLlmBtn.textContent = `${label} | ${truncate(modelLabel, 22)}`;
}

function updateTopbarSub() {
  const departments = state.accessProfile?.allowed_departments || [];
  const scope = departments.length ? departments.join(", ") : "Enterprise";
  const role = state.accessProfile?.role || "Authorized user";
  const provider = providerLabel(state.provider);
  const model = state.model || "model not selected";
  topbarSub.textContent = `${role} | ${scope} | HR-only insights | ${provider} | ${model}`;
}

function providerLabel(provider) {
  return provider === "anthropic" ? "Anthropic" : "OpenAI-compatible";
}

function onInputChange() {
  chatInput.style.height = "auto";
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

  chatInput.value = "";
  chatInput.style.height = "auto";
  sendBtn.disabled = true;
  if (emptyState) emptyState.style.display = "none";

  let thread = messagesEl.querySelector(".msg-thread");
  if (!thread) {
    thread = document.createElement("div");
    thread.className = "msg-thread";
    messagesEl.appendChild(thread);
  }

  appendUserMsg(thread, text);
  const assistantRow = createAssistantPlaceholder(thread);
  const contentWrap = assistantRow.querySelector(".msg-content");

  setLoading(true);

  try {
    await streamChat(payload, contentWrap);
  } catch (error) {
    appendErrorBubble(contentWrap, error.message || "An error occurred.");
  } finally {
    const typing = contentWrap.querySelector(".bubble-typing");
    if (typing) typing.remove();
    setLoading(false);
  }
}

async function streamChat(payload, contentWrap) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    if (response.status === 401) {
      handleUnauthorized();
      throw new Error("Please sign in to continue.");
    }
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const typingEl = document.createElement("div");
  typingEl.className = "bubble-typing";
  typingEl.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
  contentWrap.appendChild(typingEl);
  scrollToBottom();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (!raw) continue;

      let event;
      try {
        event = JSON.parse(raw);
      } catch {
        continue;
      }

      switch (event.type) {
        case "session":
          state.sessionId = event.session_id;
          localStorage.setItem("hr_session_id", event.session_id);
          break;
        case "tool_call":
          if (state.showToolCalls) {
            typingEl.remove();
            contentWrap.appendChild(buildToolCard(event));
            contentWrap.appendChild(typingEl);
            scrollToBottom();
          }
          break;
        case "tool_result":
          if (event.table_data) {
            typingEl.remove();
            contentWrap.appendChild(buildTableCard(event.title || "Query Preview", event.table_data));
            contentWrap.appendChild(typingEl);
            scrollToBottom();
          }
          break;
        case "chart":
          typingEl.remove();
          contentWrap.appendChild(buildChartCard(event));
          contentWrap.appendChild(typingEl);
          scrollToBottom();
          break;
        case "final_text":
          typingEl.remove();
          if (event.text) {
            contentWrap.appendChild(buildMarkdownBubble(event.text));
            scrollToBottom();
          }
          break;
        case "error":
          typingEl.remove();
          appendErrorBubble(contentWrap, event.message);
          break;
        case "done":
          typingEl.remove();
          await loadHistory();
          scrollToBottom();
          break;
        default:
          break;
      }
    }
  }
}

function appendUserMsg(thread, text) {
  const row = document.createElement("div");
  row.className = "msg-row user";
  row.innerHTML = `
    <div class="msg-content">
      <div class="bubble-user">${escHtml(text)}</div>
    </div>
    <div class="avatar user">You</div>
  `;
  thread.appendChild(row);
  scrollToBottom();
}

function createAssistantPlaceholder(thread) {
  const row = document.createElement("div");
  row.className = "msg-row assistant";
  row.innerHTML = `
    <div class="avatar ai">${coffeeLogoMarkup()}</div>
    <div class="msg-content"></div>
  `;
  thread.appendChild(row);
  return row;
}

function buildToolCard(event) {
  const card = document.createElement("div");
  card.className = "tool-card";

  const explanation = event.explanation ? ` - ${event.explanation.slice(0, 90)}` : "";
  const chevronId = `chev-${Math.random().toString(36).slice(2)}`;
  const bodyId = `body-${Math.random().toString(36).slice(2)}`;

  let bodyContent = "<p class=\"label\">Inputs</p><pre>No details</pre>";
  if (event.sql) {
    bodyContent = `<p class="label">SQL Query</p><pre>${escHtml(event.sql)}</pre>`;
  } else if (event.inputs && Object.keys(event.inputs).length) {
    bodyContent = `<p class="label">Inputs</p><pre>${escHtml(JSON.stringify(event.inputs, null, 2))}</pre>`;
  }

  card.innerHTML = `
    <div class="tool-card-header" onclick="toggleToolCard('${bodyId}', '${chevronId}')">
      <span class="tool-badge">Tool | ${escHtml(event.name || "tool")}</span>
      <span class="tool-explanation">${escHtml(explanation)}</span>
      <svg id="${chevronId}" class="tool-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
    </div>
    <div id="${bodyId}" class="tool-card-body">${bodyContent}</div>
  `;
  return card;
}

function buildChartCard(event) {
  const card = document.createElement("div");
  card.className = "chart-card";
  const chartId = `chart-${Math.random().toString(36).slice(2)}`;

  if (event.title) {
    const title = document.createElement("div");
    title.className = "chart-title";
    title.textContent = event.title;
    card.appendChild(title);
  }

  const container = document.createElement("div");
  container.className = "chart-container";
  container.id = chartId;
  card.appendChild(container);

  requestAnimationFrame(() => {
    if (typeof Plotly === "undefined") {
      container.textContent = "(Plotly not loaded - chart unavailable)";
      return;
    }

    try {
      const fig = JSON.parse(event.chart_json);
      const layout = Object.assign({
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: "Inter, sans-serif", size: 12, color: "#475569" },
        margin: { t: 20, r: 16, b: 40, l: 40 },
        showlegend: true,
        legend: { orientation: "h", y: -0.25 },
      }, fig.layout || {});
      Plotly.newPlot(chartId, fig.data || [], layout, { responsive: true, displayModeBar: false });
    } catch (error) {
      container.textContent = `Chart render error: ${error.message}`;
    }
  });

  return card;
}

function buildTableCard(title, rows) {
  const card = document.createElement("div");
  card.className = "table-wrap";

  if (!Array.isArray(rows) || !rows.length) {
    card.innerHTML = '<div class="table-title">No rows returned</div>';
    return card;
  }

  const columns = Object.keys(rows[0]);
  const head = columns.map((column) => `<th>${escHtml(column)}</th>`).join("");
  const body = rows.map((row) => {
    const cells = columns.map((column) => `<td>${escHtml(formatCell(row[column]))}</td>`).join("");
    return `<tr>${cells}</tr>`;
  }).join("");

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
  const bubble = document.createElement("div");
  bubble.className = "bubble-ai";
  bubble.innerHTML = markdownToHtml(text);
  return bubble;
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let inCodeBlock = false;
  let codeFence = [];
  let listType = null;
  let paragraph = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = null;
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.startsWith("```")) {
      flushParagraph();
      closeList();
      if (inCodeBlock) {
        html.push(`<pre><code>${escHtml(codeFence.join("\n"))}</code></pre>`);
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
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${renderInline(bulletMatch[1])}</li>`);
      continue;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
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
    html.push(`<pre><code>${escHtml(codeFence.join("\n"))}</code></pre>`);
  }

  return html.join("");
}

function renderInline(text) {
  let rendered = escHtml(text);
  rendered = rendered.replace(/`([^`]+)`/g, "<code>$1</code>");
  rendered = rendered.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return rendered;
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function appendErrorBubble(parent, message) {
  const el = document.createElement("div");
  el.style.cssText = "padding:10px 14px; background:#FEF2F2; border:1px solid #FECACA; border-radius:10px; color:#DC2626; font-size:13px;";
  el.textContent = `Warning: ${message}`;
  parent.appendChild(el);
  scrollToBottom();
}

window.toggleToolCard = function toggleToolCard(bodyId, chevronId) {
  const body = document.getElementById(bodyId);
  const chevron = document.getElementById(chevronId);
  if (!body || !chevron) return;
  body.classList.toggle("open");
  chevron.classList.toggle("open");
};

async function newConversation() {
  if (state.sessionId) {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    }).catch(() => {});
  }

  state.sessionId = "";
  localStorage.removeItem("hr_session_id");
  resetConversationUi();
  sidebar.classList.remove("open");
  await loadHistory();
}

function resetConversationUi() {
  const thread = messagesEl.querySelector(".msg-thread");
  if (thread) thread.remove();
  if (emptyState) emptyState.style.display = "";
}

function handleUnauthorized() {
  state.user = null;
  state.accessProfile = null;
  syncAuthUi();
  syncScopeUi();
  showAuthShell();
}

async function loadHistory() {
  if (!historyList) return;

  try {
    const response = await fetch("/api/me/history");
    if (!response.ok) {
      if (response.status === 401) {
        handleUnauthorized();
        return;
      }
      throw new Error("Could not load history");
    }

    const payload = await response.json();
    const questions = payload.questions || [];

    if (!questions.length) {
      historyList.innerHTML = '<div class="history-empty">No prior HR questions yet</div>';
      return;
    }

    historyList.innerHTML = questions.map((item) => `
      <button class="history-item" data-q="${escAttr(item.question)}">
        <span class="history-question">${escHtml(item.question)}</span>
        <span class="history-time">${escHtml(formatHistoryTime(item.created_at))}</span>
      </button>
    `).join("");

    historyList.querySelectorAll(".history-item").forEach((button) => {
      button.addEventListener("click", () => {
        chatInput.value = button.dataset.q || "";
        onInputChange();
        handleSend();
      });
    });
  } catch (error) {
    historyList.innerHTML = `<div class="history-empty">${escHtml(error.message || "Could not load history")}</div>`;
  }
}

function setLoading(loading) {
  state.isLoading = loading;
  chatInput.disabled = loading;
  sendBtn.disabled = loading || !chatInput.value.trim();

  if (loading) {
    sendIcon.classList.add("hidden");
    loadingIcon.classList.remove("hidden");
  } else {
    sendIcon.classList.remove("hidden");
    loadingIcon.classList.add("hidden");
    chatInput.disabled = false;
    chatInput.focus();
  }
}

function scrollToBottom() {
  messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "smooth" });
}

function escHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escAttr(value) {
  return escHtml(value);
}

function coffeeLogoMarkup() {
  return `
    <svg class="coffee-svg" viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <path class="coffee-steam" d="M22 14C19 18 19 21 22 25" />
      <path class="coffee-steam" d="M32 11C29 16 29 20 32 25" />
      <path class="coffee-steam" d="M42 14C39 18 39 21 42 25" />
      <path class="coffee-cup" d="M15 26H43V37C43 45 36 51 28 51H27C20 51 15 46 15 39V26Z" />
      <path class="coffee-handle" d="M43 29H47C51 29 54 32 54 36C54 40 51 43 47 43H43" />
      <path class="coffee-base" d="M18 55H45" />
    </svg>
  `;
}

function normalizeMetrics(metrics) {
  return (metrics || []).map((metric) => String(metric || "").toLowerCase());
}

function truncate(value, length) {
  if (!value || value.length <= length) return value;
  return `${value.slice(0, length - 1)}...`;
}

function formatHistoryTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recent";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function defaultModelForProvider(config, provider) {
  return provider === "anthropic"
    ? (config.default_model || "")
    : (config.default_openai_compat_model || "");
}

function defaultBaseUrlForProvider(config, provider) {
  return provider === "anthropic"
    ? ""
    : (config.default_openai_compat_base_url || "");
}

let toastTimer;
function showToast(message, isError = false) {
  toast.textContent = message;
  toast.className = `toast${isError ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.add("hidden");
  }, 4000);
}
