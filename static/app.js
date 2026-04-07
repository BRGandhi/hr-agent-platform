/**
 * HR Intelligence Platform frontend.
 * Enforces the auth shell, role-aware UX, and banner-based LLM connection flow.
 *
 * Security notes:
 * - API keys can be provided in the UI for the current browser session
 * - Server-side environment keys still work as the fallback path
 * - Auth modal is non-dismissible until authenticated
 */

const DEFAULT_SIDEBAR_SECTIONS = {
  topics: false,
  favorites: true,
  relevant: true,
  past: true,
};

function loadSidebarSections() {
  try {
    return { ...DEFAULT_SIDEBAR_SECTIONS, ...JSON.parse(localStorage.getItem("hr_sidebar_sections") || "{}") };
  } catch {
    return { ...DEFAULT_SIDEBAR_SECTIONS };
  }
}

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
  stats: null,
  lastTable: null,
  pendingTableContext: null,
  feedbackByMemory: {},
  activeTopic: "",
  activeDiveTopic: "",
  activeTopbarPanel: "",
  historyRequestToken: 0,
  sidebarSections: loadSidebarSections(),
  historySummary: {
    favoriteTopics: [],
    favoriteKpis: [],
    favoriteQuestions: [],
  },
  relevantHistoryItems: [],
  pastHistoryItems: [],
  starterPrompts: [],
};

const LEGACY_OPENAI_COMPAT_MODEL = "llama3.1:8b";
const LEGACY_OPENAI_COMPAT_BASE_URL = "http://localhost:11434/v1";
const TABLE_VISUAL_MAX_ROWS = 12;
const TABLE_VISUAL_MAX_COLUMNS = 4;
const SECTION_HEADING_HINTS = new Set([
  "analysis",
  "breakdown",
  "details",
  "highlights",
  "key takeaway",
  "key takeaways",
  "main takeaway",
  "main takeaways",
  "next step",
  "next steps",
  "observation",
  "observations",
  "recommendation",
  "recommendations",
  "risks",
  "summary",
  "what this means",
  "why it matters",
]);

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
const apiKeyLabel = $("apiKeyLabel");
const apiKeyInput = $("apiKeyInput");
const showToolCalls = $("showToolCalls");
const chatInput = $("chatInput");
const sendBtn = $("sendBtn");
const sendIcon = $("sendIcon");
const loadingIcon = $("loadingIcon");
const messagesEl = $("messages");
const emptyState = $("emptyState");
const dbStatus = $("dbStatus");
const dbCaption = $("dbCaption");
const examplesEl = $("examples");
const favoriteTopicsEl = $("favoriteTopics");
const favoriteChatsCaption = $("favoriteChatsCaption");
const relevantHistoryCaption = $("relevantHistoryCaption");
const relevantHistoryList = $("relevantHistoryList");
const pastHistoryCaption = $("pastHistoryCaption");
const pastHistoryList = $("pastHistoryList");
const newChatBtn = $("newChatBtn");
const menuToggle = $("menuToggle");
const sidebar = $("sidebar");
const toast = $("toast");
const topbarSub = $("topbarSub");
const topbarReveal = $("topbarReveal");
const connectLlmBtn = $("connectLlmBtn");
const userBadge = $("userBadge");
const logoutBtn = $("logoutBtn");
const llmModalNote = $("llmModalNote");
const centerKpiBoard = $("centerKpiBoard");
const metricExamplesEl = $("metricExamples");
const topicSuggestionsEl = $("topicSuggestions");

(async function init() {
  showToolCalls.checked = state.showToolCalls;
  wireUiEvents();
  renderSidebarSectionState();

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
    normalizeOpenAiCompatConnection({ notify: true });
    updateConnectionButton();
    updateTopbarSub();
  });
  baseUrlInput.addEventListener("input", () => {
    state.baseUrl = baseUrlInput.value.trim();
    localStorage.setItem("hr_base_url", state.baseUrl);
  });
  apiKeyInput.addEventListener("input", updateConnectionButton);
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
    if (handleDynamicButtonClick(event)) {
      return;
    }
    if (!event.target.closest(".topbar-chip") && !event.target.closest("#topbarReveal")) {
      closeTopbarReveal();
    }
    if (window.innerWidth <= 768 && !sidebar.contains(event.target) && !menuToggle.contains(event.target)) {
      sidebar.classList.remove("open");
    }
  });

  // Escape closes LLM modal only — auth modal is non-dismissible
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeLlmModal();
    }
  });
}

function renderSidebarSectionState() {
  document.querySelectorAll("[data-section-toggle]").forEach((button) => {
    const sectionId = button.dataset.sectionToggle || "";
    const collapsed = Boolean(state.sidebarSections?.[sectionId]);
    const body = document.querySelector(`[data-section-body="${sectionId}"]`);
    button.classList.toggle("collapsed", collapsed);
    button.setAttribute("aria-expanded", String(!collapsed));
    if (body) {
      body.classList.toggle("collapsed", collapsed);
    }
  });
}

function toggleSidebarSection(sectionId) {
  if (!sectionId) return;
  state.sidebarSections = {
    ...DEFAULT_SIDEBAR_SECTIONS,
    ...state.sidebarSections,
    [sectionId]: !state.sidebarSections?.[sectionId],
  };
  localStorage.setItem("hr_sidebar_sections", JSON.stringify(state.sidebarSections));
  renderSidebarSectionState();
}

function handleDynamicButtonClick(event) {
  const sectionToggle = event.target.closest("[data-section-toggle]");
  if (sectionToggle) {
    toggleSidebarSection(sectionToggle.dataset.sectionToggle || "");
    return true;
  }

  const memoryButton = event.target.closest("[data-memory-id][data-q]");
  if (memoryButton) {
    const memoryId = Number(memoryButton.dataset.memoryId || 0);
    if (!memoryId) return true;
    if (memoryButton.closest("#topbarReveal")) {
      closeTopbarReveal();
    }
    recallStoredInsight(memoryId, memoryButton.dataset.q || "").catch(() => {});
    return true;
  }

  const promptButton = event.target.closest("[data-q]");
  if (promptButton) {
    const question = promptButton.dataset.q;
    if (!question) return true;
    if (promptButton.closest("#topbarReveal")) {
      closeTopbarReveal();
    }
    chatInput.value = question;
    onInputChange();
    handleSend();
    return true;
  }

  const topbarChip = event.target.closest(".topbar-chip");
  if (topbarChip) {
    toggleTopbarReveal(topbarChip.dataset.topbarPanel || "");
    return true;
  }

  const diveTopicButton = event.target.closest(".sidebar-topic-chip");
  if (diveTopicButton && favoriteTopicsEl?.contains(diveTopicButton)) {
    toggleDiveTopic(diveTopicButton.dataset.topic || "");
    return true;
  }

  const topicButton = event.target.closest(".metric-chip");
  if (topicButton && metricExamplesEl?.contains(topicButton)) {
    toggleMetricTopic(topicButton.dataset.topic || "");
    return true;
  }

  const feedbackButton = event.target.closest(".feedback-btn");
  if (feedbackButton) {
    const bar = feedbackButton.closest(".feedback-bar");
    const vote = feedbackButton.dataset.vote;
    const memoryId = Number(bar?.dataset.memoryId || 0);
    if (!bar || !vote || !memoryId) return true;
    submitFeedback(memoryId, vote, bar);
    return true;
  }

  return false;
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
    migrateLegacyOpenAiCompatDefaults(config);

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

function migrateLegacyOpenAiCompatDefaults(config) {
  if (state.provider !== "openai-compatible") return;

  const nextModel = defaultModelForProvider(config, state.provider);
  const nextBaseUrl = defaultBaseUrlForProvider(config, state.provider);
  const targetModel = state.model || nextModel;
  const shouldReplaceModel = !state.model || state.model === LEGACY_OPENAI_COMPAT_MODEL;
  const shouldReplaceBaseUrl =
    !state.baseUrl
    || normalizeEndpointUrl(state.baseUrl) === normalizeEndpointUrl(LEGACY_OPENAI_COMPAT_BASE_URL)
    || (looksLikeHostedOpenAiModel(targetModel) && isLegacyLocalEndpoint(state.baseUrl));

  if (shouldReplaceModel && nextModel) {
    state.model = nextModel;
    localStorage.setItem("hr_model", state.model);
  }
  if (shouldReplaceBaseUrl && nextBaseUrl) {
    state.baseUrl = nextBaseUrl;
    localStorage.setItem("hr_base_url", state.baseUrl);
  }
}

function normalizeEndpointUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "").toLowerCase();
}

function isLegacyLocalEndpoint(value) {
  const normalized = normalizeEndpointUrl(value);
  return normalized.includes("localhost:11434") || normalized.includes("127.0.0.1:11434");
}

function looksLikeHostedOpenAiModel(model) {
  const normalized = String(model || "").trim().toLowerCase();
  return (
    normalized.startsWith("gpt-")
    || normalized.startsWith("o1")
    || normalized.startsWith("o3")
    || normalized.startsWith("o4")
    || normalized.startsWith("codex-")
  );
}

function normalizeOpenAiCompatConnection({ notify = false } = {}) {
  if (state.provider !== "openai-compatible") return false;

  const hostedBaseUrl = getProviderOption("openai-compatible")?.base_url_placeholder || "";
  if (!hostedBaseUrl || !looksLikeHostedOpenAiModel(state.model) || !isLegacyLocalEndpoint(state.baseUrl)) {
    return false;
  }

  state.baseUrl = hostedBaseUrl;
  baseUrlInput.value = state.baseUrl;
  localStorage.setItem("hr_base_url", state.baseUrl);

  if ((!state.model || state.model === LEGACY_OPENAI_COMPAT_MODEL) && getProviderOption("openai-compatible")?.model_placeholder) {
    state.model = getProviderOption("openai-compatible").model_placeholder;
    modelInput.value = state.model;
    localStorage.setItem("hr_model", state.model);
  }

  if (notify) {
    showToast("Switched Base URL to the OpenAI API for the selected GPT model.");
  }
  return true;
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
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "Could not load access profile");
    }

    const payload = await response.json();
    state.user = payload.user || state.user;
    state.accessProfile = payload.access_profile || null;
    syncAuthUi();
    syncScopeUi();
    renderStarterPrompts();
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
  return;
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
    state.stats = stats;
    state.accessProfile = stats.access_profile || state.accessProfile;
    syncAuthUi();
    syncScopeUi();
    renderStarterPrompts();
    updateTopbarSub();

    dbStatus.className = "status-pill ok";
    dbStatus.textContent = "Connected";
    dbCaption.textContent = buildDbCaption(stats);
  } catch {
    state.stats = null;
    dbStatus.className = "status-pill error";
    dbStatus.textContent = "DB unavailable";
    dbCaption.textContent = "Run: python setup_db.py";
  }
}

function buildDbCaption(stats) {
  const metrics = normalizeMetrics(stats.allowed_metrics);
  const departments = (stats.allowed_departments || []).length
    ? stats.allowed_departments.join(", ")
    : "Enterprise";
  const metricsLabel = metrics.length ? metrics.join(", ") : "approved HR measures";
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

function renderStarterPrompts() {
  const profile = state.accessProfile;
  const scopeName = profile?.scope_name || "my business units";
  const departments = profile?.allowed_departments || [];
  const hasAllMetrics = (profile?.allowed_metrics || []).includes("all");
  const allowed = new Set(normalizeMetrics(profile?.allowed_metrics || []));
  const prompts = [];

  prompts.push(`What is the total headcount for ${scopeName}?`);
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
    prompts[0] = `What is the total headcount for ${departments[0]}?`;
  }

  const uniquePrompts = prompts.slice(0, 5);
  state.starterPrompts = uniquePrompts;
  renderDiveBackIn();
  renderMetricExamples(profile);
}

function preferredTopicsFromHistory() {
  const favoriteTopics = Array.isArray(state.historySummary.favoriteTopics)
    ? state.historySummary.favoriteTopics
    : [];
  const favoriteKpis = Array.isArray(state.historySummary.favoriteKpis)
    ? state.historySummary.favoriteKpis
    : [];
  const combined = [...favoriteKpis, ...favoriteTopics];
  const unique = [];
  const seen = new Set();

  combined.forEach((item) => {
    const topic = String(item?.topic || "").trim();
    if (!topic || seen.has(topic)) return;
    seen.add(topic);
    unique.push(topic);
  });

  if (unique.length) return unique.slice(0, 5);

  const normalizedAllowed = normalizeMetrics(state.accessProfile?.allowed_metrics || []);
  if (normalizedAllowed.includes("all")) {
    return ["Headcount", "Attrition rate", "Compensation bands", "Satisfaction pulse", "Tenure mix"];
  }

  return Array.from(new Set(normalizeMetrics(state.accessProfile?.allowed_metrics || []).map((metric) => {
    const mapping = {
      "headcount": "Headcount",
      "attrition": "Attrition rate",
      "compensation": "Compensation bands",
      "performance": "Performance ratings",
      "satisfaction": "Satisfaction pulse",
      "tenure": "Tenure mix",
      "demographics": "Demographic mix",
      "policy": "Access policy guidance",
    };
    return mapping[metric] || "";
  }).filter(Boolean))).slice(0, 5);
}

function preferredQuestionsFromHistory() {
  return preferredQuestionItemsFromHistory().map((item) => item.question).slice(0, 5);
}

function isFeatureableHistoryQuestion(question) {
  const normalized = String(question || "").trim().toLowerCase();
  if (!normalized) return false;

  const thinFollowUps = new Set([
    "yes",
    "yes please",
    "yeah",
    "yep",
    "sure",
    "sure thing",
    "ok",
    "okay",
    "please",
    "go ahead",
    "do it",
    "sounds good",
    "no",
    "no thanks",
    "not now",
    "show me",
    "show that",
    "show it",
    "show those",
    "break it down",
    "drill down",
    "go deeper",
    "dig deeper",
    "more detail",
    "more details",
    "visualize it",
    "chart it",
    "plot it",
    "turn it into",
    "that one",
    "those ones",
  ]);
  if (thinFollowUps.has(normalized)) return false;
  if (/^(?:answer|respond to|explain|show)\s+question\s+\d+$/i.test(normalized)) return false;
  if (/^question\s+\d+$/i.test(normalized)) return false;

  const tokens = normalized.match(/[a-z0-9]+/g) || [];
  if (!normalized.endsWith("?") && tokens.length <= 3) return false;
  return true;
}

function preferredQuestionItemsFromHistory() {
  const favoriteQuestions = Array.isArray(state.historySummary.favoriteQuestions)
    ? state.historySummary.favoriteQuestions
    : [];
  const unique = [];
  const seen = new Set();

  favoriteQuestions.forEach((item) => {
    const question = String(item?.question || "").trim();
    const normalized = question.toLowerCase();
    if (!question || !isFeatureableHistoryQuestion(question) || seen.has(normalized)) return;
    seen.add(normalized);
    unique.push({
      ...item,
      question,
      topics: Array.isArray(item?.topics) ? item.topics : [],
    });
  });

  return unique.slice(0, 5);
}

function topicMetricKey(topic) {
  const normalized = String(topic || "").trim().toLowerCase();
  const mapping = {
    "headcount": "headcount",
    "active headcount": "headcount",
    "active workforce": "headcount",
    "department mix": "headcount",
    "attrition rate": "attrition",
    "attrited employee roster": "attrition",
    "attrition by department": "attrition",
    "tenure mix": "tenure",
    "promotion momentum": "tenure",
    "compensation bands": "compensation",
    "performance ratings": "performance",
    "satisfaction pulse": "satisfaction",
    "demographic mix": "demographics",
    "access policy guidance": "policy",
  };
  return mapping[normalized] || normalized;
}

function topicPromptKey(topic) {
  const normalized = String(topic || "").trim().toLowerCase();
  const mapping = {
    "active workforce": "active headcount",
  };
  return mapping[normalized] || normalized;
}

function filterHistoryItemsByTopic(items, topic) {
  const topicKey = topicMetricKey(topic);
  return items.filter((item) => {
    const itemTopics = Array.isArray(item?.topics) ? item.topics : [];
    return itemTopics.some((label) => topicMetricKey(label) === topicKey);
  });
}

function getActiveSidebarTopic(topics = preferredTopicsFromHistory()) {
  const activeTopic = topics.includes(state.activeDiveTopic) ? state.activeDiveTopic : "";
  state.activeDiveTopic = activeTopic;
  return activeTopic;
}

function renderMemoryButtons(container, className, items) {
  if (!container) return;
  container.innerHTML = items.map((item) => {
    const question = String(item?.question || "").trim();
    const memoryId = Number(item?.memory_id || 0);
    const summary = String(item?.insight_summary || "").trim();
    const title = summary || question;
    const memoryAttr = memoryId ? ` data-memory-id="${escAttr(String(memoryId))}"` : "";
    return `
      <button
        type="button"
        class="${className}"
        ${memoryAttr}
        data-q="${escAttr(question)}"
        title="${escAttr(title)}"
      >${escHtml(question)}</button>
    `;
  }).join("");
}

function renderDiveBackIn() {
  const topics = preferredTopicsFromHistory();
  const favoriteQuestionItems = preferredQuestionItemsFromHistory();
  const activeTopic = getActiveSidebarTopic(topics);

  if (favoriteTopicsEl) {
    favoriteTopicsEl.innerHTML = topics.length ? topics.map((topic) => `
      <button
        type="button"
        class="sidebar-topic-chip${activeTopic === topic ? " active" : ""}"
        data-topic="${escAttr(topic)}"
        title="Click to reveal questions around ${escAttr(topic)}"
      >${escHtml(topic)}</button>
    `).join("") : '<div class="history-empty">Your recurring HR topics will appear here.</div>';
  }

  const filteredItems = activeTopic
    ? filterHistoryItemsByTopic(favoriteQuestionItems, activeTopic)
    : favoriteQuestionItems;
  const questionItems = filteredItems;

  if (favoriteChatsCaption) {
    favoriteChatsCaption.textContent = activeTopic
      ? `Favorite chats related to ${activeTopic}.`
      : "The questions you revisit most often or marked helpful.";
  }

  if (!questionItems.length) {
    if (examplesEl) {
      examplesEl.innerHTML = activeTopic
        ? `<div class="history-empty">No favorite chats saved for ${escHtml(activeTopic)} yet.</div>`
        : '<div class="history-empty">Questions you revisit or rate helpful will appear here.</div>';
    }
  } else {
    renderMemoryButtons(
      examplesEl,
      "example-btn",
      questionItems.slice(0, 5),
    );
  }

  renderRelevantHistory(state.relevantHistoryItems, activeTopic);
  renderPastHistory(state.pastHistoryItems, activeTopic);
  renderCenterKpiBoard();
}

function hasHistoryKeyword(patterns) {
  const questions = (Array.isArray(state.historySummary.favoriteQuestions) ? state.historySummary.favoriteQuestions : [])
    .map((item) => String(item?.question || "").toLowerCase())
    .filter(Boolean);
  return questions.some((question) => patterns.some((pattern) => pattern.test(question)));
}

function preferredKpiFamilies() {
  const favoriteTopics = preferredTopicsFromHistory().map((topic) => topic.toLowerCase());
  const hasAllMetrics = normalizeMetrics(state.accessProfile?.allowed_metrics || []).includes("all");
  const allowed = new Set(normalizeMetrics(state.accessProfile?.allowed_metrics || []));
  const families = [];

  const wantsHeadcount = favoriteTopics.some((topic) => topic.includes("headcount") || topic.includes("workforce"))
    || hasHistoryKeyword([/\bheadcount\b/, /\bactive\b/, /\bworkforce\b/]);
  const wantsAttrition = favoriteTopics.some((topic) => topic.includes("attrition"))
    || hasHistoryKeyword([/\battrition\b/, /\battrited\b/, /\bleft\b/, /\brisk\b/]);
  const wantsPromotion = favoriteTopics.some((topic) => topic.includes("tenure") || topic.includes("compensation"))
    || hasHistoryKeyword([/\bpromotion\b/, /\bpromoted\b/, /\bsalary hike\b/, /\bhike\b/]);

  if ((hasAllMetrics || allowed.has("headcount")) && wantsHeadcount) families.push("headcount");
  if ((hasAllMetrics || allowed.has("attrition")) && wantsAttrition) families.push("attrition");
  if ((hasAllMetrics || allowed.has("tenure") || allowed.has("compensation") || allowed.has("performance")) && wantsPromotion) {
    families.push("promotion");
  }

  if (!families.includes("headcount") && (hasAllMetrics || allowed.has("headcount"))) families.push("headcount");
  if (!families.includes("attrition") && (hasAllMetrics || allowed.has("attrition"))) families.push("attrition");
  if (!families.includes("promotion") && (hasAllMetrics || allowed.has("tenure") || allowed.has("compensation") || allowed.has("performance"))) {
    families.push("promotion");
  }

  return families.slice(0, 3);
}

function requestedKpiFamilies() {
  const hasAllMetrics = normalizeMetrics(state.accessProfile?.allowed_metrics || []).includes("all");
  const allowed = new Set(normalizeMetrics(state.accessProfile?.allowed_metrics || []));
  const families = [];

  const askedHeadcount = hasHistoryKeyword([/\bheadcount\b/, /\bactive\b/, /\bworkforce\b/, /\bhead count\b/]);
  const askedAttrition = hasHistoryKeyword([/\battrition\b/, /\battrited\b/, /\bleft\b/, /\brisk\b/, /\bretention\b/]);
  const askedPromotion = hasHistoryKeyword([/\bpromotion\b/, /\bpromoted\b/, /\bsalary hike\b/, /\bhike\b/, /\bpromotion pool\b/]);

  if ((hasAllMetrics || allowed.has("headcount")) && askedHeadcount) families.push("headcount");
  if ((hasAllMetrics || allowed.has("attrition")) && askedAttrition) families.push("attrition");
  if ((hasAllMetrics || allowed.has("tenure") || allowed.has("compensation") || allowed.has("performance")) && askedPromotion) {
    families.push("promotion");
  }

  return families;
}

function buildCenterKpiCards() {
  if (!state.stats || !state.accessProfile) return [];

  const scopeName = state.accessProfile.scope_name || "my business units";
  const hasAllMetrics = normalizeMetrics(state.accessProfile?.allowed_metrics || []).includes("all");
  const allowed = new Set(normalizeMetrics(state.accessProfile?.allowed_metrics || []));
  const requestedFamilies = requestedKpiFamilies();
  const families = [];
  const cards = [];

  if (hasAllMetrics || allowed.has("headcount")) {
    families.push("headcount");
  }
  requestedFamilies.forEach((family) => {
    if (!families.includes(family)) {
      families.push(family);
    }
  });

  if (families.includes("headcount")) {
    cards.push({
      family: "Headcount",
      familyKey: "headcount",
      label: "Total headcount",
      value: Number(state.stats.total_employees || 0).toLocaleString(),
      note: "Employees across your business units",
      prompt: `What is the total headcount for ${scopeName}?`,
    });
  }

  if (requestedFamilies.includes("headcount")) {
    cards.push({
      family: "Headcount",
      familyKey: "headcount",
      label: "Active headcount",
      value: Number(state.stats.active_employees || 0).toLocaleString(),
      note: "Employees currently active",
      prompt: `What is the active headcount for ${scopeName}?`,
    });
  }

  if (families.includes("attrition")) {
    cards.push({
      family: "Attrition",
      familyKey: "attrition",
      label: "Attrition rate",
      value: `${state.stats.attrition_rate_pct || 0}%`,
      note: "Attrition across your business units",
      prompt: `What is the attrition rate for ${scopeName}?`,
      tone: Number(state.stats.attrition_rate_pct || 0) > 15 ? "danger" : "",
    });
  }

  const hasPromotionStats = [
    state.stats.promoted_last_year_employees,
    state.stats.avg_years_since_last_promotion,
  ].some((value) => value !== undefined && value !== null);

  if (families.includes("promotion") && hasPromotionStats) {
    cards.push(
      {
        family: "Promotion",
        familyKey: "promotion",
        label: "Promoted in last year",
        value: Number(state.stats.promoted_last_year_employees || 0).toLocaleString(),
        note: "Employees promoted within the past year",
        prompt: `How many employees in ${scopeName} were promoted in the last year?`,
        tone: "success",
      },
      {
        family: "Promotion",
        familyKey: "promotion",
        label: "Avg time to promotion",
        value: `${Number(state.stats.avg_years_since_last_promotion || 0).toFixed(1)} yrs`,
        note: "Estimated from current employee promotion records",
        prompt: `What is the average time to promotion in ${scopeName}?`,
      },
    );
  }

  return cards.slice(0, 6);
}

function centerPromptNote(topic, reuseCount = 1, feedbackScore = 0) {
  if (feedbackScore > 0) {
    return "A helpful question from prior HR work.";
  }
  if (reuseCount > 1) {
    return "A question you have revisited across prior chats.";
  }

  const topicKey = topicMetricKey(topic);
  const notes = {
    "headcount": "A workforce question shaped by your recent history.",
    "attrition": "Continue exploring recent attrition themes.",
    "tenure": "Extend a recent tenure or promotion thread.",
    "compensation": "Follow up on recent compensation questions.",
    "performance": "Continue a recent performance discussion.",
    "satisfaction": "Follow up on satisfaction and workforce risk.",
    "demographics": "Extend a recent demographic mix question.",
    "policy": "Review role-based access and guidance.",
  };
  return notes[topicKey] || "A recommended question based on your recent HR activity.";
}

function buildCenterPromptCards(existingCards = []) {
  const scopeName = state.accessProfile?.scope_name || "my business units";
  const hasAllMetrics = normalizeMetrics(state.accessProfile?.allowed_metrics || []).includes("all");
  const allowed = new Set(normalizeMetrics(state.accessProfile?.allowed_metrics || []));
  const prompts = [];
  const usedFamilies = new Set(existingCards.map((card) => card.familyKey || String(card.family || "").toLowerCase()));
  const usedQuestions = new Set(
    existingCards
      .map((card) => String(card.prompt || card.question || "").trim().toLowerCase())
      .filter(Boolean),
  );

  function pushPromptCard(label, question, note) {
    const normalizedQuestion = String(question || "").trim().toLowerCase();
    if (!normalizedQuestion || usedQuestions.has(normalizedQuestion)) return false;
    usedQuestions.add(normalizedQuestion);
    prompts.push({
      family: "Prompt",
      label: label || "Suggested next question",
      question,
      note,
      cta: "Ask this question",
      prompt: question,
    });
    return true;
  }

  preferredQuestionItemsFromHistory().forEach((item) => {
    const question = String(item?.question || "").trim();
    const topics = Array.isArray(item?.topics) ? item.topics.filter(Boolean) : [];
    const primaryTopic = topics[0] || "Suggested next question";
    const reuseCount = Number(item?.reuse_count || 1);
    const feedbackScore = Number(item?.feedback_score || 0);
    pushPromptCard(primaryTopic, question, centerPromptNote(primaryTopic, reuseCount, feedbackScore));
  });

  preferredTopicsFromHistory().forEach((topic) => {
    const topicQuestions = buildTopicQuestions(topic, state.accessProfile);
    const nextQuestion = topicQuestions.find((question) => !usedQuestions.has(String(question || "").trim().toLowerCase()));
    if (nextQuestion) {
      pushPromptCard(topic, nextQuestion, centerPromptNote(topic));
    }
  });

  if (!usedFamilies.has("headcount") && (hasAllMetrics || allowed.has("headcount"))) {
    pushPromptCard(
      "Headcount",
      `What is the total headcount for ${scopeName}?`,
      "Quick view of total headcount and department mix",
    );
  }
  if (!usedFamilies.has("attrition") && (hasAllMetrics || allowed.has("attrition"))) {
    pushPromptCard(
      "Attrition",
      `Show attrition by department for ${scopeName}`,
      "Spot attrition hotspots and department risk",
    );
  }
  if (!usedFamilies.has("promotion") && (hasAllMetrics || allowed.has("tenure") || allowed.has("compensation") || allowed.has("performance"))) {
    pushPromptCard(
      "Promotion",
      `Show employees with recent promotions in ${scopeName}`,
      "Review recent promotions and salary movement",
    );
  }

  const fallbackPrompts = [
    {
      label: "Suggested next question",
      question: `Generate an active headcount report for ${scopeName}`,
      note: "Open an employee-level active headcount report",
    },
    {
      label: "Suggested next question",
      question: `What is the attrition rate for ${scopeName}?`,
      note: "Check the current attrition baseline across your business units",
    },
    {
      label: "Suggested next question",
      question: `What is the average time to promotion in ${scopeName}?`,
      note: "Review promotion timing across your business units",
    },
  ];

  fallbackPrompts.forEach((item) => {
    pushPromptCard(item.label, item.question, item.note);
  });

  return prompts;
}

function renderCenterKpiBoard() {
  if (!centerKpiBoard) return;

  const cards = buildCenterKpiCards();
  const promptCards = buildCenterPromptCards(cards);
  const allCards = [...cards, ...promptCards].slice(0, 6);

  if (!allCards.length) {
    centerKpiBoard.innerHTML = "";
    return;
  }

  centerKpiBoard.innerHTML = allCards.map((card) => `
    <button type="button" class="empty-kpi-card${card.family === "Prompt" ? " prompt" : ""}" data-q="${escAttr(card.prompt)}">
      <span class="empty-kpi-family">${escHtml(card.family)}</span>
      <span class="empty-kpi-label">${escHtml(card.label)}</span>
      ${card.family === "Prompt"
        ? `<span class="empty-kpi-question">${escHtml(card.question || card.prompt)}</span>`
        : `<span class="empty-kpi-value ${escAttr(card.tone || "")}">${escHtml(card.value)}</span>`}
      <span class="empty-kpi-note">${escHtml(card.note)}</span>
      ${card.family === "Prompt"
        ? `<span class="empty-kpi-cta">${escHtml(card.cta || "Ask this question")}</span>`
        : ""}
    </button>
  `).join("");
}

function renderMetricExamples(profile) {
  if (!metricExamplesEl) return;

  const hasAllMetrics = (profile?.allowed_metrics || []).includes("all");
  const allowed = new Set(normalizeMetrics(profile?.allowed_metrics || []));
  const metrics = [];

  if (hasAllMetrics || allowed.has("headcount")) {
    metrics.push("Headcount");
    metrics.push("Active headcount");
    metrics.push("Department mix");
  }
  if (hasAllMetrics || allowed.has("attrition")) {
    metrics.push("Attrition rate");
    metrics.push("Attrited employee roster");
    metrics.push("Attrition by department");
  }
  if (hasAllMetrics || allowed.has("tenure")) {
    metrics.push("Tenure mix");
    metrics.push("Promotion momentum");
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

  clearActiveTopicSelection();
  metricExamplesEl.innerHTML = metrics.map((metric) => `
    <button
      class="metric-chip"
      type="button"
      data-topic="${escAttr(metric)}"
      aria-pressed="false"
    >${escHtml(metric)}</button>
  `).join("");
}

function clearActiveTopicSelection() {
  state.activeTopic = "";
  metricExamplesEl?.querySelectorAll(".metric-chip").forEach((chip) => {
    chip.classList.remove("active");
    chip.setAttribute("aria-pressed", "false");
  });
  clearTopicSuggestions();
}

function setActiveTopic(topic) {
  if (!topic) {
    clearActiveTopicSelection();
    return;
  }
  state.activeTopic = topic;
  metricExamplesEl?.querySelectorAll(".metric-chip").forEach((chip) => {
    const isActive = chip.dataset.topic === topic;
    chip.classList.toggle("active", isActive);
    chip.setAttribute("aria-pressed", String(isActive));
  });
  renderTopicSuggestions(topic, state.accessProfile);
}

function toggleMetricTopic(topic) {
  if (!topic) {
    clearActiveTopicSelection();
    return;
  }
  if (state.activeTopic === topic) {
    clearActiveTopicSelection();
    return;
  }
  setActiveTopic(topic);
}

function toggleDiveTopic(topic) {
  state.activeDiveTopic = state.activeDiveTopic === topic ? "" : topic;
  renderDiveBackIn();
  if (state.activeDiveTopic) {
    setActiveTopic(state.activeDiveTopic);
  } else {
    clearActiveTopicSelection();
  }
}

function clearTopicSuggestions() {
  if (!topicSuggestionsEl) return;
  topicSuggestionsEl.innerHTML = "";
  topicSuggestionsEl.classList.add("hidden");
}

function renderTopicSuggestions(topic, profile) {
  if (!topicSuggestionsEl) return;

  const prompts = buildTopicQuestions(topic, profile);
  if (!prompts.length) {
    clearTopicSuggestions();
    return;
  }

  topicSuggestionsEl.classList.remove("hidden");
  topicSuggestionsEl.innerHTML = `
    <div class="topic-suggestions-header">
      <div class="topic-suggestions-kicker">Topic Starters</div>
      <div class="topic-suggestions-title">${escHtml(topic)}</div>
      <div class="topic-suggestions-sub">Try one of these HR questions next.</div>
    </div>
    <div class="topic-suggestions-list"></div>
  `;
  renderPromptButtons(topicSuggestionsEl.querySelector(".topic-suggestions-list"), "topic-prompt-btn", prompts);
  topicSuggestionsEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function buildTopicQuestions(topic, profile) {
  const normalizedTopic = topicPromptKey(topic);
  const scopeName = profile?.scope_name || "my business units";
  const departments = profile?.allowed_departments || [];
  const primaryScope = departments.length === 1 ? departments[0] : scopeName;

  const templates = {
    "headcount": [
      `What is the total headcount for ${primaryScope}?`,
      `Show total headcount by department for ${scopeName}`,
      `Which job roles have the highest headcount in ${scopeName}?`,
      `Turn the headcount breakdown for ${scopeName} into a visualization`,
    ],
    "active headcount": [
      `What is the active headcount for ${scopeName}?`,
      `Generate an active headcount report for ${scopeName}`,
      `Show active headcount by department for ${scopeName}`,
      `Which teams in ${scopeName} have the largest active headcount?`,
    ],
    "department mix": [
      `What is the department mix for ${scopeName}?`,
      `Show department share of headcount for ${scopeName}`,
      `Which departments have the largest share of headcount in ${scopeName}?`,
      `Create a chart of the department mix for ${scopeName}`,
    ],
    "attrition rate": [
      `What is the attrition rate for ${scopeName}?`,
      `Show attrition rate by department for ${scopeName}`,
      `Which teams in ${scopeName} have the highest attrition risk?`,
      `Create a visualization of attrition by department for ${scopeName}`,
    ],
    "attrited employee roster": [
      `Generate an attrition report for ${scopeName}`,
      `Show the attrited employee roster for ${scopeName}`,
      `Which job roles appear most often in the attrited employee roster for ${scopeName}?`,
      `Turn the attrited employee roster summary for ${scopeName} into a chart`,
    ],
    "attrition by department": [
      `Show attrition by department for ${scopeName}`,
      `Which department has the highest attrition in ${scopeName}?`,
      `Create a visualization of attrition by department for ${scopeName}`,
      `Compare headcount and attrition by department for ${scopeName}`,
    ],
    "tenure mix": [
      `What does tenure look like in ${scopeName}?`,
      `Show tenure mix by department for ${scopeName}`,
      `Which teams in ${scopeName} have the shortest average tenure?`,
      `Visualize the tenure mix for ${scopeName}`,
    ],
    "promotion momentum": [
      `Show employees with recent promotions in ${scopeName}`,
      `How many employees in ${scopeName} were promoted in the last year?`,
      `Which departments in ${scopeName} have the longest time since promotion?`,
      `Compare salary hikes and years since promotion for ${scopeName}`,
    ],
    "satisfaction pulse": [
      `Are there satisfaction risks in ${scopeName}?`,
      `Show job satisfaction by department for ${scopeName}`,
      `Which groups in ${scopeName} have the lowest work-life balance scores?`,
      `Create a satisfaction visualization for ${scopeName}`,
    ],
    "compensation bands": [
      `Show compensation bands for ${scopeName}`,
      `Which departments in ${scopeName} skew toward higher compensation bands?`,
      `Visualize compensation bands for ${scopeName}`,
      `Compare compensation bands and attrition for ${scopeName}`,
    ],
    "performance ratings": [
      `Show performance ratings for ${scopeName}`,
      `Which teams in ${scopeName} have the strongest performance ratings?`,
      `Visualize the performance rating mix for ${scopeName}`,
      `Compare performance ratings and attrition for ${scopeName}`,
    ],
    "demographic mix": [
      `What does the demographic mix look like in ${scopeName}?`,
      `Show age and gender mix by department for ${scopeName}`,
      `Which demographic groups are most represented in ${scopeName}?`,
      `Visualize the demographic mix for ${scopeName}`,
    ],
    "access policy guidance": [
      "Which HR access policy applies to my role?",
      "What data domains can I access in this platform?",
      "Which HR document tags are available to my role?",
      "Summarize the access rules for my role in this platform",
    ],
  };

  return templates[normalizedTopic] || [];
}

function renderPromptButtons(container, className, prompts, rich = false) {
  if (!container) return;

  if (rich) {
    container.innerHTML = prompts.map((prompt) => `
      <button type="button" class="${className}" data-q="${escAttr(prompt)}">
        <span class="suggestion-icon">${suggestionIcon(prompt)}</span>
        <span>${escHtml(prompt)}</span>
      </button>
    `).join("");
  } else {
    container.innerHTML = prompts.map((prompt) => `
      <button type="button" class="${className}" data-q="${escAttr(prompt)}">${escHtml(prompt)}</button>
    `).join("");
  }
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
  apiKeyInput.placeholder = providerOption?.api_key_placeholder || "API key";

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
  const keyLabel = apiKeyInput.value.trim() ? " | key set" : "";
  connectLlmBtn.textContent = `${label} | ${truncate(modelLabel, 22)}${keyLabel}`;
}

function updateTopbarSub() {
  if (!topbarSub) return;

  const departments = state.accessProfile?.allowed_departments || [];
  const scopeSummary = departments.length ? `${departments.length} business unit${departments.length > 1 ? "s" : ""}` : "Enterprise";
  const role = state.accessProfile?.role || "Authorized user";
  const provider = providerLabel(state.provider);
  const model = state.model || "Model not selected";
  const favoriteKpis = buildPersonalizedKpiPrompts().map((item) => item.topic);
  const kpiSummary = favoriteKpis.length ? favoriteKpis.slice(0, 2).join(" | ") : "Recommended KPI views";
  const chips = [
    {
      id: "role",
      label: "Role",
      value: truncate(role, 24),
      hover: `${role}${state.user?.name ? ` | ${state.user.name}` : ""}`,
    },
    {
      id: "scope",
      label: "Coverage",
      value: truncate(scopeSummary, 24),
      hover: departments.length ? departments.join(", ") : "Enterprise-wide access",
    },
    {
      id: "guardrails",
      label: "Access",
      value: "Role-based",
      hover: "HR analytics only, with governed role-based access",
    },
    {
      id: "model",
      label: "Model",
      value: truncate(`${provider} | ${model}`, 28),
      hover: `${provider} | ${model}`,
    },
    {
      id: "kpis",
      label: "My KPIs",
      value: truncate(kpiSummary, 28),
      hover: "History-aware KPI suggestions and starter questions",
    },
  ];

  topbarSub.innerHTML = chips.map((chip) => `
    <button
      type="button"
      class="topbar-chip${state.activeTopbarPanel === chip.id ? " active" : ""}"
      data-topbar-panel="${chip.id}"
      title="${escAttr(chip.hover)}"
      aria-expanded="${state.activeTopbarPanel === chip.id ? "true" : "false"}"
    >
      <span class="topbar-chip-label">${escHtml(chip.label)}</span>
      <span class="topbar-chip-value">${escHtml(chip.value)}</span>
    </button>
  `).join("");

  renderTopbarReveal();
}

function providerLabel(provider) {
  return provider === "anthropic" ? "Anthropic" : "OpenAI-compatible";
}

function toggleTopbarReveal(panelId) {
  state.activeTopbarPanel = state.activeTopbarPanel === panelId ? "" : panelId;
  updateTopbarSub();
}

function closeTopbarReveal() {
  if (!state.activeTopbarPanel) return;
  state.activeTopbarPanel = "";
  updateTopbarSub();
}

function buildPersonalizedKpiPrompts() {
  const topics = Array.isArray(state.historySummary.favoriteKpis) && state.historySummary.favoriteKpis.length
    ? state.historySummary.favoriteKpis.map((item) => String(item?.topic || "").trim()).filter(Boolean)
    : preferredTopicsFromHistory().filter((topic) => topic !== "Access policy guidance");

  const uniqueTopics = Array.from(new Set(topics)).slice(0, 4);
  return uniqueTopics.map((topic) => ({
    topic,
    prompt: buildTopicQuestions(topic, state.accessProfile)[0] || "",
  })).filter((item) => item.prompt);
}

function revealMetricSummary() {
  const allowed = normalizeMetrics(state.accessProfile?.allowed_metrics || []);
  return allowed.includes("all") ? "All approved HR measures" : (allowed.join(", ") || "Approved HR measures");
}

function renderTopbarReveal() {
  if (!topbarReveal) return;
  if (!state.activeTopbarPanel) {
    topbarReveal.classList.add("hidden");
    topbarReveal.innerHTML = "";
    return;
  }

  const departments = state.accessProfile?.allowed_departments || [];
  const favoriteKpis = buildPersonalizedKpiPrompts();
  const favoriteQuestionItems = preferredQuestionItemsFromHistory().slice(0, 3);
  let content = "";

  if (state.activeTopbarPanel === "role") {
    content = `
      <div class="topbar-reveal-card">
        <div class="topbar-reveal-kicker">Role Context</div>
        <div class="topbar-reveal-title">${escHtml(state.accessProfile?.role || "Authorized user")}</div>
        <div class="topbar-reveal-copy">Signed in as ${escHtml(state.user?.name || "your HR user")}. Your view includes only the business units, measures, and policy context approved for this role.</div>
      </div>
    `;
  } else if (state.activeTopbarPanel === "scope") {
    content = `
      <div class="topbar-reveal-card">
        <div class="topbar-reveal-kicker">Coverage</div>
        <div class="topbar-reveal-title">${escHtml(state.accessProfile?.scope_name || "Enterprise")}</div>
        <div class="topbar-reveal-copy">${departments.length ? escHtml(departments.join(", ")) : "Enterprise-wide access"}.</div>
        <div class="topbar-reveal-note">Visible measures: ${escHtml(revealMetricSummary())}</div>
      </div>
    `;
  } else if (state.activeTopbarPanel === "guardrails") {
    content = `
      <div class="topbar-reveal-card">
        <div class="topbar-reveal-kicker">Access</div>
        <div class="topbar-reveal-title">HR analytics with role-based access</div>
        <div class="topbar-reveal-copy">The assistant stays within HR questions and only uses the business units and measures approved for your role.</div>
        <div class="topbar-reveal-note">Current measures: ${escHtml(revealMetricSummary())}</div>
      </div>
    `;
  } else if (state.activeTopbarPanel === "model") {
    content = `
      <div class="topbar-reveal-card">
        <div class="topbar-reveal-kicker">Model Setup</div>
        <div class="topbar-reveal-title">${escHtml(providerLabel(state.provider))}</div>
        <div class="topbar-reveal-copy">${escHtml(state.model || "No model selected yet")}</div>
        <div class="topbar-reveal-note">Use the Connect LLM button to switch provider, model, base URL, or API key.</div>
      </div>
    `;
  } else if (state.activeTopbarPanel === "kpis") {
    content = `
      <div class="topbar-reveal-card">
        <div class="topbar-reveal-kicker">Most Relevant To You</div>
        <div class="topbar-reveal-title">Measures shaped by your recent history</div>
        <div class="topbar-reveal-copy">These suggestions lean into the workforce themes you revisit most often.</div>
        <div class="topbar-reveal-pills">
          ${favoriteKpis.map((item) => `<button type="button" class="topbar-reveal-pill" data-q="${escAttr(item.prompt)}">${escHtml(item.topic)}</button>`).join("")}
        </div>
        ${favoriteQuestionItems.length ? `
          <div class="topbar-reveal-list">
            ${favoriteQuestionItems.map((item) => `<button type="button" class="topbar-reveal-item" ${item.memory_id ? `data-memory-id="${escAttr(String(item.memory_id))}"` : ""} data-q="${escAttr(item.question || "")}" title="${escAttr(item.insight_summary || item.question || "")}">${escHtml(item.question || "")}</button>`).join("")}
          </div>
        ` : ""}
      </div>
    `;
  }

  topbarReveal.innerHTML = content;
  topbarReveal.classList.remove("hidden");
}

function onInputChange() {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 120)}px`;
  sendBtn.disabled = !chatInput.value.trim() || state.isLoading;
}

function ensureMessageThread() {
  let thread = messagesEl.querySelector(".msg-thread");
  if (!thread) {
    thread = document.createElement("div");
    thread.className = "msg-thread";
    messagesEl.appendChild(thread);
  }
  return thread;
}

function buildRecalledInsightText(memory = {}) {
  const question = String(memory.question || "").trim() || "Saved HR question";
  const summary = String(memory.insight_summary || "").trim();
  const createdAt = memory.created_at ? formatHistoryTime(memory.created_at) : "a previous chat";
  const topics = Array.isArray(memory.topics) && memory.topics.length
    ? `**Topics:** ${memory.topics.join(", ")}\n\n`
    : "";
  const summaryBlock = summary || "- Saved answer recalled from an earlier HR chat.";
  return [
    "### Recalled Insight",
    `**Question:** ${question}`,
    "",
    topics ? topics.trimEnd() : "",
    summaryBlock,
    "",
    `_Recalled from ${createdAt}. This is a saved insight summary, not a fresh query._`,
  ].filter(Boolean).join("\n");
}

async function recallStoredInsight(memoryId, fallbackQuestion = "") {
  if (state.authRequired && !state.user) {
    showAuthShell();
    return;
  }
  if (state.isLoading) return;

  const numericMemoryId = Number(memoryId || 0);
  if (!numericMemoryId) return;

  normalizeOpenAiCompatConnection();
  state.pendingTableContext = null;
  state.lastTable = null;

  if (emptyState) emptyState.style.display = "none";
  const thread = ensureMessageThread();
  const recalledQuestion = String(fallbackQuestion || "").trim();
  if (recalledQuestion) {
    appendUserMsg(thread, recalledQuestion);
  }

  const assistantRow = createAssistantPlaceholder(thread);
  const contentWrap = assistantRow.querySelector(".msg-content");
  const typingEl = document.createElement("div");
  typingEl.className = "bubble-typing";
  typingEl.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
  contentWrap.appendChild(typingEl);
  scrollToBottom();
  setLoading(true);

  try {
    const response = await fetch(`/api/memories/${numericMemoryId}/recall`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: apiKeyInput.value.trim(),
        provider: state.provider,
        model: modelInput.value.trim(),
        base_url: baseUrlInput.value.trim(),
        session_id: state.sessionId,
      }),
    });

    if (!response.ok) {
      if (response.status === 401) {
        handleUnauthorized();
        throw new Error("Please sign in to continue.");
      }
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "Could not recall that saved insight.");
    }

    const payload = await response.json();
    if (payload.session_id) {
      state.sessionId = payload.session_id;
      localStorage.setItem("hr_session_id", payload.session_id);
    }

    const memory = payload.memory || {};
    typingEl.remove();
    contentWrap.appendChild(buildMarkdownBubble(buildRecalledInsightText(memory)));
    scrollToBottom();
  } catch (error) {
    typingEl.remove();
    appendErrorBubble(contentWrap, error.message || "Could not recall that saved insight.");
    throw error;
  } finally {
    setLoading(false);
  }
}

async function handleSend() {
  if (state.authRequired && !state.user) {
    showAuthShell();
    return;
  }

  const text = chatInput.value.trim();
  if (!text || state.isLoading) return;
  normalizeOpenAiCompatConnection();
  const tableContext = buildOutgoingTableContext(text);

  const payload = {
    message: text,
    api_key: apiKeyInput.value.trim(),
    provider: state.provider,
    model: modelInput.value.trim(),
    base_url: baseUrlInput.value.trim(),
    session_id: state.sessionId,
    table_context_title: tableContext?.title || "",
    table_context_rows: tableContext?.rows || [],
  };
  state.pendingTableContext = null;

  chatInput.value = "";
  chatInput.style.height = "auto";
  sendBtn.disabled = true;
  if (emptyState) emptyState.style.display = "none";

  const thread = ensureMessageThread();
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
    if (response.status === 429) {
      throw new Error("Rate limit exceeded. Please wait a moment and try again.");
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
            state.lastTable = buildTableContext(event.title || "Query Preview", event.table_data);
            typingEl.remove();
            contentWrap.appendChild(buildTableCard(event.title || "Query Preview", event.table_data, {
              toolName: event.name || "",
              reportType: event.report_type || "",
              tableTotalRows: Number(event.table_total_rows || 0),
            }));
            contentWrap.appendChild(typingEl);
            scrollToBottom();
          }
          break;
        case "helpful_memories":
          if (Array.isArray(event.items) && event.items.length) {
            typingEl.remove();
            contentWrap.appendChild(buildHelpfulMemoriesCard(event.items));
            contentWrap.appendChild(typingEl);
            scrollToBottom();
          }
          break;
        case "visual_options":
          typingEl.remove();
          contentWrap.appendChild(buildVisualOptionsCard(event));
          contentWrap.appendChild(typingEl);
          scrollToBottom();
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
            if (event.memory_id) {
              state.feedbackByMemory[event.memory_id] = event.feedback_score || 0;
            }
            contentWrap.appendChild(buildMarkdownBubble(event.text, event.memory_id, event.feedback_score || 0));
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

  const summary = summarizePlotlyFigure(event.chart_json);
  const descriptor = summary?.descriptor || chartTypeDescriptor(summary?.chartType);
  const chips = [
    descriptor.badge,
    summary?.seriesLabel,
    summary?.axisSummary,
  ].filter(Boolean);
  const chartDetails = renderVisualizationDetails(event, {
    includeQuestion: true,
    includeBestFor: true,
    includeWatchOut: false,
  });

  card.innerHTML = `
    <div class="chart-card-header">
      <div class="chart-card-copy">
        <div class="chart-card-kicker">Selected chart</div>
        <div class="chart-title">${escHtml(event.title || "Chart")}</div>
        <div class="chart-card-sub">${escHtml(descriptor.note)}</div>
        ${chartDetails ? `<div class="chart-card-details">${chartDetails}</div>` : ""}
      </div>
      <div class="chart-card-meta">
        ${chips.map((chip) => `<span class="chart-pill">${escHtml(chip)}</span>`).join("")}
      </div>
    </div>
    <div class="chart-container"></div>
  `;

  const container = card.querySelector(".chart-container");
  renderPlotlyFigure(container, event.chart_json);

  return card;
}

function buildTableMetaLabel(rowCount, meta = {}) {
  const totalRows = Number(meta.tableTotalRows || 0);
  if (totalRows > rowCount) {
    return `${rowCount.toLocaleString()} of ${totalRows.toLocaleString()} rows shown`;
  }
  return `${rowCount.toLocaleString()} rows shown`;
}

function looksLikeIdentifierColumn(columnName) {
  return /(employee|id\b|identifier|number|email|name|label)/i.test(String(columnName || ""));
}

function parseNumericValue(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const normalized = value.trim().replace(/,/g, "").replace(/%$/, "");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function isMostlyNumericColumn(rows, columnName) {
  let populated = 0;
  let numeric = 0;
  rows.slice(0, 12).forEach((row) => {
    const value = row?.[columnName];
    if (value === null || value === undefined || String(value).trim() === "") return;
    populated += 1;
    if (parseNumericValue(value) !== null) numeric += 1;
  });
  return populated > 0 && numeric / populated >= 0.7;
}

function isVisualizationCandidate(rows) {
  if (!Array.isArray(rows) || rows.length < 2 || rows.length > TABLE_VISUAL_MAX_ROWS) return false;

  const columns = Object.keys(rows[0] || {});
  if (columns.length < 2 || columns.length > TABLE_VISUAL_MAX_COLUMNS) return false;
  if (columns.some(looksLikeIdentifierColumn)) return false;

  const numericColumns = columns.filter((column) => isMostlyNumericColumn(rows, column));
  const dimensionColumns = columns.filter((column) => !numericColumns.includes(column));
  return numericColumns.length >= 1 && dimensionColumns.length >= 1;
}

function getTableAction(title, rows, meta = {}) {
  if (meta.reportType) {
    return {
      kind: "download_excel",
      label: "Download Excel",
      reportType: meta.reportType,
    };
  }

  if (isVisualizationCandidate(rows)) {
    return {
      kind: "visualize",
      label: "Visual options",
    };
  }

  return null;
}

async function downloadReportExcel(reportType, title) {
  try {
    const response = await fetch("/api/reports/export/excel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report_type: reportType, title }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${String(title || "report").trim().replace(/[^a-z0-9]+/gi, "_").replace(/^_+|_+$/g, "") || "report"}.xls`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast("Excel download started.");
  } catch (error) {
    showToast(error.message || "Could not download the Excel report.", true);
  }
}

function buildTableCard(title, rows, meta = {}) {
  const card = document.createElement("div");
  card.className = "table-wrap";

  if (!Array.isArray(rows) || !rows.length) {
    card.innerHTML = '<div class="table-title">No rows returned</div>';
    return card;
  }

  const tableContext = buildTableContext(title, rows);
  const action = getTableAction(title, rows, meta);
  const columns = Object.keys(rows[0]);
  const head = columns.map((column) => `<th>${escHtml(column)}</th>`).join("");
  const body = rows.map((row) => {
    const cells = columns.map((column) => `<td>${escHtml(formatCell(row[column]))}</td>`).join("");
    return `<tr>${cells}</tr>`;
  }).join("");

  card.innerHTML = `
    <div class="table-header">
      <div>
        <div class="table-title">${escHtml(title)}</div>
        <div class="table-meta">${escHtml(buildTableMetaLabel(rows.length, meta))}</div>
      </div>
      ${action ? `<div class="table-actions"><button class="table-action-btn" type="button">${escHtml(action.label)}</button></div>` : ""}
    </div>
    <div class="table-scroll">
      <table>
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
  const actionButton = card.querySelector(".table-action-btn");
  if (actionButton && action?.kind === "visualize") {
    actionButton.addEventListener("click", () => requestVisualizationOptions(tableContext));
  }
  if (actionButton && action?.kind === "download_excel") {
    actionButton.addEventListener("click", () => downloadReportExcel(action.reportType, title));
  }
  return card;
}

function buildVisualOptionsCard(event) {
  const card = document.createElement("div");
  card.className = "visual-options-card";
  const options = Array.isArray(event.options) ? event.options : [];

  if (!options.length) {
    card.innerHTML = '<div class="visual-options-empty">No visualization options were returned.</div>';
    return card;
  }

  const recommendedId = event.recommended_option_id || options[0].id;
  const optionSummaries = options.map((option) => ({
    option,
    summary: summarizePlotlyFigure(option.chart_json),
  }));
  const recommendedOption = optionSummaries.find((item) => item.option.id === recommendedId) || optionSummaries[0];
  const recommendedDescriptor = chartTypeDescriptor(recommendedOption?.summary?.chartType || recommendedOption?.option?.chart_type);
  const sourceTitle = event.source_title || event.title || "Visualization options";
  const recommendedDetails = renderVisualizationDetails(recommendedOption?.option, {
    includeQuestion: true,
    includeBestFor: true,
    includeWatchOut: true,
  });
  card.innerHTML = `
    <div class="visual-options-header">
      <div class="visual-options-kicker">Visualization Studio</div>
      <div class="visual-options-title">${escHtml(sourceTitle)}</div>
      <div class="visual-options-sub">Compare a few executive-ready chart directions before committing to one.</div>
    </div>
    <div class="visual-recommendation">
      <div class="visual-recommendation-copy">
        <div class="visual-recommendation-label">Recommended first</div>
        <div class="visual-recommendation-title"></div>
        <div class="visual-recommendation-reason"></div>
        <div class="visual-recommendation-details"></div>
      </div>
      <div class="visual-recommendation-chips"></div>
    </div>
    <div class="visual-options-grid"></div>
    <div class="visual-preview">
      <div class="visual-preview-copy">
        <div class="visual-preview-topline">
          <div>
            <div class="visual-preview-label">Live preview</div>
            <div class="visual-preview-title"></div>
          </div>
          <div class="visual-preview-meta"></div>
        </div>
        <div class="visual-preview-reason"></div>
        <div class="visual-preview-details"></div>
      </div>
      <div class="chart-container visual-preview-chart"></div>
    </div>
  `;

  const grid = card.querySelector(".visual-options-grid");
  const recommendationTitle = card.querySelector(".visual-recommendation-title");
  const recommendationReason = card.querySelector(".visual-recommendation-reason");
  const recommendationDetails = card.querySelector(".visual-recommendation-details");
  const recommendationChips = card.querySelector(".visual-recommendation-chips");
  const previewTitle = card.querySelector(".visual-preview-title");
  const previewReason = card.querySelector(".visual-preview-reason");
  const previewDetails = card.querySelector(".visual-preview-details");
  const previewMeta = card.querySelector(".visual-preview-meta");
  const previewChart = card.querySelector(".visual-preview-chart");

  if (recommendedOption) {
    recommendationTitle.textContent = recommendedOption.option.title || recommendedDescriptor.label;
    recommendationReason.textContent = recommendedOption.option.reason || recommendedDescriptor.note;
    recommendationDetails.innerHTML = recommendedDetails || "";
    recommendationChips.innerHTML = [
      recommendedDescriptor.badge,
      recommendedDescriptor.label,
      recommendedOption.summary?.seriesLabel,
    ]
      .filter(Boolean)
      .map((chip) => `<span class="chart-pill">${escHtml(chip)}</span>`)
      .join("");
  }

  const setActiveOption = (option) => {
    const summary = summarizePlotlyFigure(option.chart_json);
    const descriptor = chartTypeDescriptor(summary?.chartType || option.chart_type);
    const optionDetails = renderVisualizationDetails(option, {
      includeQuestion: true,
      includeBestFor: true,
      includeWatchOut: true,
      compact: true,
    });
    grid.querySelectorAll(".visual-option-btn").forEach((button) => {
      button.classList.toggle("active", button.dataset.optionId === option.id);
    });
    previewTitle.textContent = option.title || chartTypeLabel(option.chart_type);
    previewReason.textContent = option.reason || descriptor.note;
    previewDetails.innerHTML = optionDetails || "";
    previewMeta.innerHTML = [
      descriptor.badge,
      summary?.seriesLabel,
      summary?.axisSummary,
    ]
      .filter(Boolean)
      .map((chip) => `<span class="chart-pill">${escHtml(chip)}</span>`)
      .join("");
    renderPlotlyFigure(previewChart, option.chart_json);
  };

  optionSummaries.forEach(({ option, summary }) => {
    const descriptor = chartTypeDescriptor(summary?.chartType || option.chart_type);
    const optionDetails = renderVisualizationDetails(option, {
      includeQuestion: true,
      includeBestFor: true,
      includeWatchOut: true,
      compact: true,
    });
    const button = document.createElement("button");
    button.type = "button";
    button.className = "visual-option-btn";
    button.dataset.optionId = option.id;
    button.innerHTML = `
      <span class="visual-option-topline">
        <span class="visual-option-type">${escHtml(descriptor.label)}</span>
        ${option.id === recommendedId ? '<span class="visual-option-badge">Recommended</span>' : `<span class="visual-option-badge visual-option-badge-muted">${escHtml(descriptor.badge)}</span>`}
      </span>
      <span class="visual-option-title">${escHtml(option.title || chartTypeLabel(option.chart_type))}</span>
      <span class="visual-option-reason">${escHtml(option.reason || descriptor.note)}</span>
      ${optionDetails ? `<div class="visual-option-details">${optionDetails}</div>` : ""}
      <span class="visual-option-footer">
        <span class="chart-pill chart-pill-soft">${escHtml(descriptor.badge)}</span>
        ${summary?.seriesLabel ? `<span class="chart-pill chart-pill-soft">${escHtml(summary.seriesLabel)}</span>` : ""}
      </span>
    `;
    button.addEventListener("click", () => setActiveOption(option));
    grid.appendChild(button);
  });

  setActiveOption((optionSummaries.find((item) => item.option.id === recommendedId) || optionSummaries[0]).option);
  return card;
}

function renderPlotlyFigure(container, chartJson) {
  container.textContent = "";
  requestAnimationFrame(() => {
    if (typeof Plotly === "undefined") {
      container.textContent = "(Plotly not loaded - chart unavailable)";
      return;
    }

    try {
      const fig = JSON.parse(chartJson);
      const data = Array.isArray(fig.data) ? fig.data : [];
      const chartType = normalizeChartType(data[0]?.type || fig?.layout?.meta?.chartType || "");
      const multiSeries = data.length > 1;
      const layout = Object.assign({}, fig.layout || {});
      layout.paper_bgcolor = "rgba(0,0,0,0)";
      layout.plot_bgcolor = "rgba(248,251,255,0.95)";
      layout.font = Object.assign({ family: "Inter, sans-serif", size: 12, color: "#334155" }, layout.font || {});
      layout.margin = Object.assign({ t: 28, r: 20, b: 56, l: 56 }, layout.margin || {});
      layout.showlegend = multiSeries || chartType === "pie" || chartType === "donut";
      layout.legend = Object.assign({
        orientation: multiSeries ? "h" : "v",
        y: multiSeries ? -0.22 : 1,
        x: 0,
        bgcolor: "rgba(255,255,255,0.78)",
        bordercolor: "rgba(203,213,225,0.65)",
        borderwidth: 1,
      }, layout.legend || {});
      layout.hoverlabel = Object.assign({
        bgcolor: "#FFFFFF",
        bordercolor: "#CBD5E1",
        font: { color: "#0F172A" },
      }, layout.hoverlabel || {});
      if (!layout.hovermode) {
        layout.hovermode = chartType === "scatter" || chartType === "box" || chartType === "heatmap" ? "closest" : "x unified";
      }
      layout.bargap = layout.bargap ?? 0.22;
      layout.bargroupgap = layout.bargroupgap ?? 0.08;
      layout.uirevision = layout.uirevision || "hr-viz";
      layout.transition = Object.assign({ duration: 220, easing: "cubic-in-out" }, layout.transition || {});
      delete layout.title;
      if (typeof Plotly.purge === "function") {
        Plotly.purge(container);
      }
      Plotly.newPlot(container, data, layout, {
        responsive: true,
        displayModeBar: false,
        displaylogo: false,
        scrollZoom: true,
        doubleClick: "reset",
      });
    } catch (error) {
      container.textContent = `Chart render error: ${error.message}`;
    }
  });
}

function buildTableContext(title, rows) {
  return {
    title: title || "Query Preview",
    rows: Array.isArray(rows) ? rows.map((row) => ({ ...row })) : [],
  };
}

function buildOutgoingTableContext(message) {
  if (state.pendingTableContext?.rows?.length) {
    return buildTableContext(state.pendingTableContext.title, state.pendingTableContext.rows);
  }
  if (state.lastTable?.rows?.length && shouldAttachTableContext(message)) {
    return buildTableContext(state.lastTable.title, state.lastTable.rows);
  }
  return null;
}

function shouldAttachTableContext(message) {
  const lowered = String(message || "").toLowerCase();
  const asksForVisual = /\b(chart|graph|visual|visualize|visualization|plot|dashboard|option|options)\b/.test(lowered);
  const referencesPriorResult = /\b(this|that|it|above|previous|latest|table|result)\b/.test(lowered)
    || /\bturn\b.*\binto\b/.test(lowered)
    || /\bconvert\b/.test(lowered);
  return asksForVisual && referencesPriorResult;
}

function requestVisualizationOptions(tableContext) {
  if (!tableContext?.rows?.length) return;
  state.pendingTableContext = buildTableContext(tableContext.title, tableContext.rows);
  chatInput.value = "Suggest 3 executive-ready visualization options for this table, emphasize clarity and comparison, and recommend the best one.";
  onInputChange();
  handleSend();
}

function normalizeChartType(chartType) {
  return String(chartType || "").trim().toLowerCase().replace(/\s+/g, "_");
}

function safeParsePlotlyFigure(chartJson) {
  try {
    return JSON.parse(chartJson);
  } catch {
    return null;
  }
}

function renderVisualizationDetails(option, config = {}) {
  if (!option || typeof option !== "object") return "";

  const includeQuestion = config.includeQuestion !== false;
  const includeBestFor = config.includeBestFor !== false;
  const includeWatchOut = Boolean(config.includeWatchOut);
  const compact = Boolean(config.compact);
  const rows = [];

  const addRow = (label, value, tone = "") => {
    const text = String(value || "").trim();
    if (!text) return;
    rows.push(`
      <div class="visual-detail-row${tone ? ` ${tone}` : ""}">
        <span class="visual-detail-label">${escHtml(label)}</span>
        <span class="visual-detail-value">${escHtml(text)}</span>
      </div>
    `);
  };

  if (includeQuestion) {
    addRow("Business question", option.business_question || option.businessQuestion || "");
  }
  if (includeBestFor) {
    addRow("Best for", option.best_for || option.bestFor || "", "best-for");
  }
  if (includeWatchOut) {
    addRow("Watch out", option.watch_out || option.watchOut || "", "watch-out");
  }

  if (!rows.length) return "";

  return `
    <div class="visual-details${compact ? " compact" : ""}">
      ${rows.join("")}
    </div>
  `;
}

function chartTypeDescriptor(chartType) {
  switch (normalizeChartType(chartType)) {
    case "bar":
      return {
        label: "Bar chart",
        badge: "Ranking",
        note: "Best for comparing categories side by side and making the ranking obvious.",
      };
    case "horizontal_bar":
      return {
        label: "Horizontal bar",
        badge: "Ranking",
        note: "Best when the categories have longer labels and need more breathing room.",
      };
    case "stacked_bar":
      return {
        label: "Stacked bar",
        badge: "Composition",
        note: "Best for showing totals and the mix behind each category in one view.",
      };
    case "line":
      return {
        label: "Line chart",
        badge: "Trend",
        note: "Best for change over an ordered sequence or time-based progression.",
      };
    case "area":
      return {
        label: "Area chart",
        badge: "Magnitude",
        note: "Best when the size of the movement matters as much as the trend itself.",
      };
    case "scatter":
      return {
        label: "Scatter plot",
        badge: "Relationship",
        note: "Best for checking spread, clusters, and relationships between two measures.",
      };
    case "histogram":
      return {
        label: "Histogram",
        badge: "Distribution",
        note: "Best for showing whether values cluster tightly or spread widely.",
      };
    case "box":
      return {
        label: "Box plot",
        badge: "Spread",
        note: "Best for comparing variation and outliers across groups.",
      };
    case "pie":
    case "donut":
      return {
        label: normalizeChartType(chartType) === "donut" ? "Donut chart" : "Pie chart",
        badge: "Share",
        note: "Best only when a small set of categories needs a simple share view.",
      };
    case "heatmap":
      return {
        label: "Heatmap",
        badge: "Hotspots",
        note: "Best for spotting the strongest and weakest combinations across two dimensions.",
      };
    default:
      return {
        label: chartTypeLabel(chartType),
        badge: "Custom",
        note: "A flexible chart view for executive review.",
      };
  }
}

function summarizePlotlyFigure(chartJson) {
  const fig = safeParsePlotlyFigure(chartJson);
  if (!fig) return null;

  const data = Array.isArray(fig.data) ? fig.data : [];
  const layout = fig.layout || {};
  const chartType = normalizeChartType(data[0]?.type || layout?.meta?.chartType || "");
  const descriptor = chartTypeDescriptor(chartType);
  const seriesCount = data.length;
  const traceNames = data
    .map((trace) => String(trace?.name || "").trim())
    .filter(Boolean)
    .slice(0, 3);
  const xAxisTitle = String(layout?.xaxis?.title?.text || layout?.xaxis?.title || "").trim();
  const yAxisTitle = String(layout?.yaxis?.title?.text || layout?.yaxis?.title || "").trim();
  const axisSummary = xAxisTitle && yAxisTitle ? `${xAxisTitle} vs ${yAxisTitle}` : (xAxisTitle || yAxisTitle || "");

  return {
    chartType,
    descriptor,
    seriesCount,
    seriesLabel: seriesCount > 1 ? `${seriesCount} series` : "Single series",
    traceNames,
    axisSummary,
  };
}

function chartTypeLabel(chartType) {
  return String(chartType || "chart")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function buildHelpfulMemoriesCard(items) {
  const card = document.createElement("div");
  card.className = "helpful-memories-card";
  card.innerHTML = `
    <div class="helpful-memories-kicker">Helpful From Past Chats</div>
    <div class="helpful-memories-title">You previously liked answers to similar HR questions</div>
    <div class="helpful-memories-list"></div>
  `;

  const list = card.querySelector(".helpful-memories-list");
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "helpful-memory-item";
    if (item.memory_id) {
      button.dataset.memoryId = String(item.memory_id);
    }
    button.dataset.q = item.question || "";
    button.innerHTML = `
      <span class="helpful-memory-question">${escHtml(item.question || "Helpful HR answer")}</span>
      <span class="helpful-memory-response">${escHtml((item.response || "").trim())}</span>
    `;
    list.appendChild(button);
  });

  return card;
}

function buildMarkdownBubble(text, memoryId = null, feedbackScore = 0) {
  const wrapper = document.createElement("div");
  wrapper.className = "assistant-response";

  const meta = document.createElement("div");
  meta.className = "assistant-response-meta";
  meta.innerHTML = `
    <div class="assistant-response-badge">HR Analyst</div>
    <div class="assistant-response-actions">
      <button type="button" class="assistant-action-btn">Copy</button>
    </div>
  `;
  wrapper.appendChild(meta);

  const bubble = document.createElement("div");
  bubble.className = "bubble-ai";
  bubble.innerHTML = markdownToHtml(normalizeMarkdownResponse(text));
  wrapper.appendChild(bubble);
  wireAssistantResponseActions(wrapper, text);

  if (memoryId) {
    wrapper.appendChild(buildFeedbackBar(memoryId, feedbackScore));
  }

  return wrapper;
}

function normalizeMarkdownResponse(markdown) {
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  const normalizedLines = [];
  let inCodeBlock = false;

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const trimmed = rawLine.trim();

    if (trimmed.startsWith("```")) {
      inCodeBlock = !inCodeBlock;
      normalizedLines.push(rawLine);
      continue;
    }

    if (inCodeBlock || !trimmed) {
      normalizedLines.push(rawLine);
      continue;
    }

    let nextNonEmptyLine = "";
    for (let lookahead = index + 1; lookahead < lines.length; lookahead += 1) {
      const candidate = lines[lookahead].trim();
      if (!candidate) continue;
      nextNonEmptyLine = candidate;
      break;
    }

    if (looksLikeStandaloneSectionHeading(trimmed, nextNonEmptyLine)) {
      normalizedLines.push(`### ${trimmed.replace(/:$/, "")}`);
      continue;
    }

    normalizedLines.push(rawLine);
  }

  return normalizedLines.join("\n");
}

function looksLikeStandaloneSectionHeading(line, nextNonEmptyLine = "") {
  const trimmed = String(line || "").trim();
  if (!trimmed) return false;
  if (/^(#{1,6}|>|\||[-*+]\s|\d+[\.\)])/.test(trimmed)) return false;
  if (trimmed.endsWith(".") || trimmed.endsWith("?") || trimmed.endsWith("!")) return false;

  const cleaned = trimmed.replace(/:$/, "");
  const normalized = cleaned.toLowerCase();
  if (SECTION_HEADING_HINTS.has(normalized)) return true;

  if (cleaned.length > 40 || cleaned.split(/\s+/).length > 5) return false;

  const nextTrimmed = String(nextNonEmptyLine || "").trim();
  const nextLooksStructured = /^[-*+]\s/.test(nextTrimmed) || /^\d+[\.\)]\s/.test(nextTrimmed);
  const looksTitleLike = cleaned.split(/\s+/).every((word) => /^[A-Z][A-Za-z0-9&/()+-]*$/.test(word));
  return nextLooksStructured && looksTitleLike;
}

function wireAssistantResponseActions(wrapper, sourceText) {
  const responseCopyButton = wrapper.querySelector(".assistant-action-btn");
  if (responseCopyButton) {
    responseCopyButton.addEventListener("click", async () => {
      const copied = await copyTextToClipboard(sourceText, "Response copied.");
      if (copied) flashButtonLabel(responseCopyButton, "Copied");
    });
  }

  wrapper.querySelectorAll(".md-code-copy-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      const code = button.closest(".md-code-block")?.querySelector("code")?.textContent || "";
      const copied = await copyTextToClipboard(code, "Code copied.");
      if (copied) flashButtonLabel(button, "Copied");
    });
  });
}

function flashButtonLabel(button, label) {
  if (!button) return;
  const originalLabel = button.dataset.originalLabel || button.textContent;
  button.dataset.originalLabel = originalLabel;
  button.textContent = label;
  window.clearTimeout(Number(button.dataset.resetTimer || 0));
  const timerId = window.setTimeout(() => {
    button.textContent = originalLabel;
  }, 1400);
  button.dataset.resetTimer = String(timerId);
}

async function copyTextToClipboard(text, successMessage = "Copied to clipboard.") {
  const value = String(text || "").trimEnd();
  if (!value) {
    showToast("Nothing to copy.", true);
    return false;
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
    } else {
      const fallback = document.createElement("textarea");
      fallback.value = value;
      fallback.setAttribute("readonly", "readonly");
      fallback.style.position = "fixed";
      fallback.style.opacity = "0";
      document.body.appendChild(fallback);
      fallback.select();
      document.execCommand("copy");
      fallback.remove();
    }
    showToast(successMessage);
    return true;
  } catch (error) {
    showToast(error.message || "Could not copy to clipboard.", true);
    return false;
  }
}

function buildFeedbackBar(memoryId, feedbackScore = 0) {
  const bar = document.createElement("div");
  bar.className = "feedback-bar";
  bar.dataset.memoryId = String(memoryId);
  bar.innerHTML = `
    <span class="feedback-label">Was this helpful?</span>
    <button type="button" class="feedback-btn${feedbackScore > 0 ? " active" : ""}" data-vote="yes" aria-label="Yes, this was helpful">Yes</button>
    <button type="button" class="feedback-btn${feedbackScore < 0 ? " active" : ""}" data-vote="no" aria-label="No, this was not helpful">No</button>
  `;

  return bar;
}

async function submitFeedback(memoryId, vote, bar) {
  try {
    const response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ memory_id: memoryId, vote }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    const payload = await response.json();
    const feedbackScore = Number(payload.feedback_score || 0);
    state.feedbackByMemory[memoryId] = feedbackScore;
    bar.querySelectorAll(".feedback-btn").forEach((button) => {
      const buttonVote = button.dataset.vote;
      const isActive = (buttonVote === "yes" && feedbackScore > 0) || (buttonVote === "no" && feedbackScore < 0);
      button.classList.toggle("active", isActive);
    });
    showToast(feedbackScore > 0 ? "Saved as a helpful response." : "Thanks. We'll avoid reusing that answer as a good example.");
    await loadHistory();
  } catch (error) {
    showToast(error.message || "Could not save feedback.", true);
  }
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let inCodeBlock = false;
  let codeFence = [];
  let codeFenceLanguage = "";
  let listType = null;
  let paragraph = [];
  let tableLines = [];
  let quoteLines = [];
  let metricSummaryLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${renderInline(paragraph.join("\n"))}</p>`);
    paragraph = [];
  };

  const flushMetricSummary = () => {
    if (!metricSummaryLines.length) return;
    if (metricSummaryLines.length >= 2) {
      html.push(renderMetricSummary(metricSummaryLines));
    } else {
      paragraph.push(`${metricSummaryLines[0].label}: ${metricSummaryLines[0].value}`);
    }
    metricSummaryLines = [];
  };

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = null;
  };

  const flushQuote = () => {
    if (!quoteLines.length) return;
    html.push(
      `<blockquote>${quoteLines.map((line) => `<p>${renderInline(line)}</p>`).join("")}</blockquote>`,
    );
    quoteLines = [];
  };

  const appendToLastListItem = (content) => {
    for (let index = html.length - 1; index >= 0; index -= 1) {
      if (typeof html[index] === "string" && html[index].startsWith("<li>")) {
        html[index] = html[index].replace(/<\/li>$/, `<br />${renderInline(content)}</li>`);
        return true;
      }
    }
    return false;
  };

  const flushTable = () => {
    if (!tableLines.length) return;
    const tableHtml = renderMarkdownTable(tableLines);
    if (tableHtml) {
      html.push(tableHtml);
    } else {
      paragraph.push(...tableLines.map((line) => line.trim()));
    }
    tableLines = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      flushQuote();
      flushTable();
      flushMetricSummary();
      flushParagraph();
      closeList();
      if (inCodeBlock) {
        html.push(renderCodeBlock(codeFence.join("\n"), codeFenceLanguage));
        codeFence = [];
        codeFenceLanguage = "";
        inCodeBlock = false;
      } else {
        codeFenceLanguage = trimmed.slice(3).trim();
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeFence.push(rawLine);
      continue;
    }

    if (!trimmed) {
      flushQuote();
      flushTable();
      flushMetricSummary();
      flushParagraph();
      closeList();
      continue;
    }

    const quoteMatch = trimmed.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushTable();
      flushMetricSummary();
      flushParagraph();
      closeList();
      quoteLines.push(quoteMatch[1]);
      continue;
    }

    flushQuote();

    if (isPipeTableLine(trimmed)) {
      flushMetricSummary();
      flushParagraph();
      closeList();
      tableLines.push(trimmed);
      continue;
    }

    flushTable();

    const metricSummaryLine = parseMetricSummaryLine(trimmed);
    if (metricSummaryLine) {
      flushParagraph();
      closeList();
      metricSummaryLines.push(metricSummaryLine);
      continue;
    }

    flushMetricSummary();

    if (isSectionLabelLine(trimmed)) {
      flushParagraph();
      closeList();
      html.push(`<h3>${renderInline(trimmed.replace(/:$/, ""))}</h3>`);
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      closeList();
      const level = Math.min(headingMatch[1].length, 6);
      html.push(`<h${level}>${renderInline(headingMatch[2])}</h${level}>`);
      continue;
    }

    if (/^([-*_])(?:\s*\1){2,}\s*$/.test(trimmed)) {
      flushMetricSummary();
      flushParagraph();
      closeList();
      html.push("<hr />");
      continue;
    }

    if (listType && /^[ \t]{2,}\S/.test(rawLine) && appendToLastListItem(trimmed)) {
      continue;
    }

    const bulletMatch = trimmed.match(/^(?:[-*+]|\u2022)\s+(.*)$/);
    if (bulletMatch) {
      flushMetricSummary();
      flushParagraph();
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${renderInline(bulletMatch[1])}</li>`);
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+[\.\)]\s+(.*)$/);
    if (orderedMatch) {
      flushMetricSummary();
      flushParagraph();
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${renderInline(orderedMatch[1])}</li>`);
      continue;
    }

    flushMetricSummary();
    closeList();
    paragraph.push(trimmed);
  }

  flushQuote();
  flushTable();
  flushMetricSummary();
  flushParagraph();
  closeList();

  if (inCodeBlock) {
    html.push(renderCodeBlock(codeFence.join("\n"), codeFenceLanguage));
  }

  return html.join("");
}

function parseMetricSummaryLine(line) {
  const match = String(line || "").trim().match(/^([A-Za-z][A-Za-z0-9&/%()+\-\s]{1,34}):\s+(.+)$/);
  if (!match) return null;

  const label = match[1].trim();
  const value = match[2].trim();
  if (!label || !value) return null;
  if (label.split(/\s+/).length > 4) return null;
  if (!/[\d%]/.test(value) && value.length > 36) return null;

  return { label, value };
}

function renderCodeBlock(code, language = "") {
  const languageLabel = language || "text";
  return `
    <div class="md-code-block">
      <div class="md-code-block-header">
        <span class="md-code-block-label">${escHtml(languageLabel)}</span>
        <button type="button" class="md-code-copy-btn">Copy</button>
      </div>
      <pre><code>${escHtml(code)}</code></pre>
    </div>
  `;
}

function renderMetricSummary(items) {
  return `
    <dl class="metric-summary">
      ${items.map((item) => `
        <div class="metric-summary-row">
          <dt>${escHtml(item.label)}</dt>
          <dd>${renderInline(item.value)}</dd>
        </div>
      `).join("")}
    </dl>
  `;
}

function sanitizeHref(value) {
  const href = String(value || "").trim();
  if (!href) return "";
  if (/^(https?:|mailto:)/i.test(href)) return href;
  if (href.startsWith("/") || href.startsWith("#")) return href;
  return "";
}

function renderInline(text) {
  let rendered = String(text || "");
  const codeTokens = [];
  const linkTokens = [];

  rendered = rendered.replace(/`([^`]+)`/g, (_, code) => {
    const token = `@@CODE${codeTokens.length}@@`;
    codeTokens.push(`<code>${escHtml(code)}</code>`);
    return token;
  });

  rendered = rendered.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
    const safeHref = sanitizeHref(href);
    if (!safeHref) return label;
    const token = `@@LINK${linkTokens.length}@@`;
    linkTokens.push(
      `<a href="${escAttr(safeHref)}" target="_blank" rel="noopener noreferrer">${escHtml(label)}</a>`,
    );
    return token;
  });

  rendered = escHtml(rendered);
  rendered = rendered.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  rendered = rendered.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  rendered = rendered.replace(/(^|[^\*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  rendered = rendered.replace(/\n/g, "<br />");

  codeTokens.forEach((token, index) => {
    rendered = rendered.replace(`@@CODE${index}@@`, token);
  });
  linkTokens.forEach((token, index) => {
    rendered = rendered.replace(`@@LINK${index}@@`, token);
  });

  return rendered;
}

function isSectionLabelLine(line) {
  const normalized = String(line || "").trim().replace(/:$/, "").toLowerCase();
  return SECTION_HEADING_HINTS.has(normalized)
    || /^(takeaways|notes|actions?)$/.test(normalized);
}

function isPipeTableLine(line) {
  const trimmed = String(line || "").trim();
  const pipeCount = (trimmed.match(/\|/g) || []).length;
  if (pipeCount < 2) return false;
  if (trimmed.startsWith("|") || trimmed.endsWith("|")) return true;
  return trimmed.split("|").filter((cell) => cell.trim()).length >= 3;
}

function splitMarkdownTableRow(line) {
  const trimmed = String(line || "").trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

function isMarkdownTableSeparator(row) {
  return Array.isArray(row) && row.length > 0 && row.every((cell) => /^:?-{2,}:?$/.test(String(cell || "").trim()));
}

function normalizeMarkdownTableRow(row, columnCount) {
  const cells = Array.isArray(row) ? row.slice(0, columnCount) : [];
  while (cells.length < columnCount) cells.push("");
  return cells;
}

function getMarkdownTableAlignment(cell) {
  const trimmed = String(cell || "").trim();
  const isCentered = trimmed.startsWith(":") && trimmed.endsWith(":");
  if (isCentered) return "center";
  if (trimmed.endsWith(":")) return "right";
  return "left";
}

function renderMarkdownTableCell(tag, content, alignment) {
  return `<${tag} class="align-${alignment}">${renderInline(content)}</${tag}>`;
}

function renderMarkdownTable(lines) {
  if (!Array.isArray(lines) || lines.length < 2) return "";

  const rows = lines.map(splitMarkdownTableRow).filter((row) => row.length && row.some((cell) => cell.length));
  if (rows.length < 2 || !isMarkdownTableSeparator(rows[1])) {
    return "";
  }

  const header = rows[0];
  const columnCount = header.length;
  const alignments = normalizeMarkdownTableRow(rows[1], columnCount).map(getMarkdownTableAlignment);
  const bodyRows = rows
    .slice(2)
    .map((row) => normalizeMarkdownTableRow(row, columnCount))
    .filter((row) => row.some((cell) => cell.trim()));

  if (!columnCount || !bodyRows.length) {
    return "";
  }

  const headHtml = header.map((cell, index) => renderMarkdownTableCell("th", cell, alignments[index] || "left")).join("");
  const bodyHtml = bodyRows.map((row) => {
    const cells = row.map((cell, index) => renderMarkdownTableCell("td", cell, alignments[index] || "left")).join("");
    return `<tr>${cells}</tr>`;
  }).join("");

  return `
    <div class="md-table-wrap">
      <table class="md-table">
        <thead><tr>${headHtml}</tr></thead>
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>
  `;
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function appendErrorBubble(parent, message) {
  const el = document.createElement("div");
  el.style.cssText = "padding:10px 14px; background:#FEF2F2; border:1px solid #FECACA; border-radius:10px; color:#DC2626; font-size:13px;";
  const text = String(message || "");
  if (/rate limit|too many requests/i.test(text)) {
    el.textContent = `Temporary provider slowdown: ${text} If the result above is already visible, you can keep using it and retry the written summary in a moment.`;
  } else {
    el.textContent = `Warning: ${text}`;
  }
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
  state.lastTable = null;
  state.pendingTableContext = null;
  state.feedbackByMemory = {};
  state.activeDiveTopic = "";
  state.activeTopbarPanel = "";
  state.relevantHistoryItems = [];
  state.pastHistoryItems = [];
  clearActiveTopicSelection();
  closeTopbarReveal();
  const thread = messagesEl.querySelector(".msg-thread");
  if (thread) thread.remove();
  if (emptyState) emptyState.style.display = "";
  renderDiveBackIn();
}

function handleUnauthorized() {
  state.user = null;
  state.accessProfile = null;
  state.stats = null;
  state.lastTable = null;
  state.pendingTableContext = null;
  state.feedbackByMemory = {};
  state.activeDiveTopic = "";
  state.activeTopbarPanel = "";
  state.historySummary = { favoriteTopics: [], favoriteKpis: [], favoriteQuestions: [] };
  state.relevantHistoryItems = [];
  state.pastHistoryItems = [];
  clearActiveTopicSelection();
  syncAuthUi();
  syncScopeUi();
  updateTopbarSub();
  showAuthShell();
}

function renderHistoryState(container, message) {
  if (container) {
    container.innerHTML = `<div class="history-empty">${escHtml(message)}</div>`;
  }
}

function renderHistoryItems(container, questions) {
  if (!container) return;
  container.innerHTML = questions.map((item) => `
    <button
      class="history-item"
      ${Number(item.memory_id || 0) ? `data-memory-id="${escAttr(String(Number(item.memory_id || 0)))}"` : ""}
      data-q="${escAttr(item.question)}"
      title="${escAttr(item.insight_summary || item.question)}"
    >
      <span class="history-question">${escHtml(item.question)}</span>
      <span class="history-time">${escHtml(formatHistoryTime(item.created_at))}${Array.isArray(item.topics) && item.topics.length ? ` | ${escHtml(item.topics.join(", "))}` : ""}</span>
    </button>
  `).join("");
}

function dedupeHistoryItems(items, limit = 8) {
  const unique = [];
  const seen = new Set();

  (Array.isArray(items) ? items : []).forEach((item) => {
    const question = String(item?.question || "").trim();
    const normalized = question.toLowerCase();
    if (!question || seen.has(normalized)) return;
    seen.add(normalized);
    unique.push({
      ...item,
      question,
      topics: Array.isArray(item?.topics) ? item.topics : [],
    });
  });

  return unique.slice(0, limit);
}

function buildRelevantHistoryQuery() {
  const role = state.accessProfile?.role || "";
  const scope = state.accessProfile?.scope_name || "";
  const favoriteTerms = [
    ...(Array.isArray(state.historySummary.favoriteKpis) ? state.historySummary.favoriteKpis : []),
    ...(Array.isArray(state.historySummary.favoriteTopics) ? state.historySummary.favoriteTopics : []),
  ]
    .map((item) => String(item?.topic || "").trim())
    .filter(Boolean)
    .slice(0, 4);
  const allowedTerms = normalizeMetrics(state.accessProfile?.allowed_metrics || [])
    .filter((metric) => metric && metric !== "all")
    .slice(0, 3);

  return Array.from(new Set([role, scope, ...favoriteTerms, ...allowedTerms].filter(Boolean))).join(" ");
}

function buildRelevantChatItems(personalizedItems = [], pastItems = []) {
  const favorites = new Set(preferredQuestionsFromHistory().map((question) => question.toLowerCase()));
  const preferredKeys = new Set(preferredTopicsFromHistory().map((topic) => topicMetricKey(topic)).filter(Boolean));
  const mergedItems = dedupeHistoryItems(personalizedItems, 20)
    .filter((item) => !favorites.has(item.question.toLowerCase()));

  const scoredItems = mergedItems.map((item) => {
    const topicKeys = (Array.isArray(item.topics) ? item.topics : []).map((topic) => topicMetricKey(topic));
    let score = 0;

    topicKeys.forEach((key) => {
      if (preferredKeys.has(key)) score += 4;
    });
    score += Math.max(Number(item.feedback_score || 0), 0) * 2;
    score += topicKeys.length * 0.25;

    return { item, score };
  });

  scoredItems.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return String(b.item?.created_at || "").localeCompare(String(a.item?.created_at || ""));
  });

  const relevantItems = scoredItems
    .filter((entry) => entry.score > 0)
    .map((entry) => entry.item)
    .slice(0, 20);

  return relevantItems;
}

function renderRelevantHistory(questions, activeTopic = getActiveSidebarTopic()) {
  const filteredQuestions = activeTopic
    ? filterHistoryItemsByTopic(questions, activeTopic)
    : questions;

  if (relevantHistoryCaption) {
    relevantHistoryCaption.textContent = activeTopic
      ? `Relevant chats related to ${activeTopic}.`
      : "Questions closely aligned to your role and the HR themes you revisit most.";
  }
  if (!relevantHistoryList) return;
  if (!filteredQuestions.length) {
    renderHistoryState(
      relevantHistoryList,
      activeTopic
        ? `No relevant chats found for ${activeTopic} yet.`
        : "Ask a few more HR questions and this list will sharpen.",
    );
    return;
  }
  renderHistoryItems(relevantHistoryList, filteredQuestions.slice(0, 6));
}

function renderPastHistory(questions, activeTopic = getActiveSidebarTopic()) {
  const filteredQuestions = activeTopic
    ? filterHistoryItemsByTopic(questions, activeTopic)
    : questions;

  if (pastHistoryCaption) {
    pastHistoryCaption.textContent = activeTopic
      ? `Past chats related to ${activeTopic} across prior sessions.`
      : "Questions asked across all prior sessions.";
  }
  if (!pastHistoryList) return;
  if (!filteredQuestions.length) {
    renderHistoryState(
      pastHistoryList,
      activeTopic
        ? `No past chats found for ${activeTopic} yet.`
        : "No prior HR questions yet.",
    );
    return;
  }
  renderHistoryItems(pastHistoryList, filteredQuestions);
}

async function fetchHistoryPayload(query = "", limit = 8) {
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (limit) params.set("limit", String(limit));
  const url = `/api/me/history${params.toString() ? `?${params.toString()}` : ""}`;
  const response = await fetch(url);
  if (!response.ok) {
    if (response.status === 401) {
      handleUnauthorized();
      return null;
    }
    throw new Error("Could not load history");
  }
  return response.json();
}

async function loadHistory() {
  if (!relevantHistoryList && !pastHistoryList) return;
  const requestToken = ++state.historyRequestToken;

  try {
    const recentPayload = await fetchHistoryPayload("", 12);
    if (requestToken !== state.historyRequestToken) return;
    if (!recentPayload) {
      throw new Error("Could not load history");
    }

    state.historySummary = {
      favoriteTopics: recentPayload.favorite_topics || [],
      favoriteKpis: recentPayload.favorite_kpis || [],
      favoriteQuestions: recentPayload.favorite_questions || [],
    };

    const relevantQuery = buildRelevantHistoryQuery();
    let relevantPayload = null;
    if (relevantQuery) {
      try {
        relevantPayload = await fetchHistoryPayload(relevantQuery, 10);
      } catch {
        relevantPayload = null;
      }
    }
    if (requestToken !== state.historyRequestToken) return;

    const pastQuestions = Array.isArray(recentPayload.past_questions)
      ? recentPayload.past_questions
      : dedupeHistoryItems(recentPayload.questions || [], 12);
    const relevantQuestions = buildRelevantChatItems(
      dedupeHistoryItems(relevantPayload?.questions || [], 10),
      pastQuestions,
    );

    state.relevantHistoryItems = relevantQuestions;
    state.pastHistoryItems = pastQuestions;
    renderDiveBackIn();
    updateTopbarSub();
  } catch (error) {
    if (requestToken !== state.historyRequestToken) return;
    state.relevantHistoryItems = [];
    state.pastHistoryItems = [];
    renderHistoryState(relevantHistoryList, error.message || "Could not load history");
    renderHistoryState(pastHistoryList, error.message || "Could not load history");
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
