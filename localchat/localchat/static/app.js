const STORAGE_KEY = "localchat.sessions.v2";
const LEGACY_STORAGE_KEY = "localchat.sessions.v1";
const SETTINGS_KEY = "localchat.settings.v2";
const AGENTS_KEY = "localchat.agents.v1";
const PRESETS_KEY = "localchat.presets.v1";
const FOCUS_MODE_KEY = "localchat.focusMode.v1";
const DEFAULT_AGENT_ID = "custom";
const CONTEXT_MESSAGE_LIMIT = 24;
const CONTEXT_CHAR_BUDGET = 24000;
const EDGE_ADS = {
  horizontal: [
    { src: "/assets/dataset-ads/superfine-train-hero.jpg" },
    { src: "/assets/dataset-ads/superfine-test-hero.jpg" },
    { src: "/downloads/vintage_ads/casino/20010702060202_gui_blue80.gif" },
    { src: "/downloads/vintage_ads/casino/20030401143018_468x60tournamentv5_80.gif" },
    { src: "/downloads/vintage_ads/casino/19971113114955_5rate.gif" },
    { src: "/downloads/vintage_ads/casino/20000819073845_add1.gif" },
  ],
  vertical: [
    { src: "/downloads/vintage_ads/casino/20060426022400_homesignup.gif" },
    { src: "/downloads/vintage_ads/casino/20060425202623_die_footer.gif" },
    { src: "/downloads/vintage_ads/casino/20060502011545_i_tech_logo.gif" },
    { src: "/downloads/vintage_ads/casino/20060426005105_downloadsm.gif" },
  ],
};

const elements = {
  agentNameInput: document.querySelector("#agent-name-input"),
  agentSelect: document.querySelector("#agent-select"),
  deleteAgentButton: document.querySelector("#delete-agent-button"),
  emptyState: document.querySelector("#empty-state"),
  focusModeButton: document.querySelector("#focus-mode-button"),
  historyList: document.querySelector("#history-list"),
  maxTokensInput: document.querySelector("#max-tokens-input"),
  messageInput: document.querySelector("#message-input"),
  messages: document.querySelector("#messages"),
  messageTemplate: document.querySelector("#message-template"),
  modelSelect: document.querySelector("#model-select"),
  newChatButton: document.querySelector("#new-chat-button"),
  presetList: document.querySelector("#preset-list"),
  presetMessageInput: document.querySelector("#preset-message-input"),
  presetNameInput: document.querySelector("#preset-name-input"),
  saveAgentButton: document.querySelector("#save-agent-button"),
  savePresetButton: document.querySelector("#save-preset-button"),
  sendButton: document.querySelector("#send-button"),
  statusPill: document.querySelector("#status-pill"),
  stopButton: document.querySelector("#stop-button"),
  systemPrompt: document.querySelector("#system-prompt"),
  temperatureInput: document.querySelector("#temperature-input"),
  edgeAdTop: document.querySelector("#edge-ad-top"),
  edgeAdRight: document.querySelector("#edge-ad-right"),
  edgeAdLeft: document.querySelector("#edge-ad-left"),
};

marked.setOptions({
  breaks: true,
  gfm: true,
});

let modelCatalog = [];
let modelCatalogById = {};
let sessions = loadSessions();
let settings = loadSettings();
let agents = loadAgents();
let presets = loadPresets();
let activeSessionId = sessions[0]?.id ?? createSession().id;
let activeAbortController = null;
let focusModeEnabled = loadFocusMode();

applySettingsToForm();
autoGrow(elements.messageInput);
updateStatus("Idle");
applyFocusMode();

await initialize();

async function initialize() {
  await loadModels();
  renderAgents();
  applySelectedAgent();
  renderEdgeAds();
  renderPresets();
  renderHistory();
  renderActiveSession();
  bindEvents();
}

function bindEvents() {
  elements.newChatButton.addEventListener("click", () => {
    const session = createSession();
    activeSessionId = session.id;
    renderHistory();
    renderActiveSession();
    elements.messageInput.focus();
  });

  elements.sendButton.addEventListener("click", () => sendMessage());
  elements.stopButton.addEventListener("click", stopStreaming);
  elements.focusModeButton.addEventListener("click", toggleFocusMode);
  elements.saveAgentButton.addEventListener("click", saveAgent);
  elements.savePresetButton.addEventListener("click", savePreset);
  elements.deleteAgentButton.addEventListener("click", deleteAgent);
  elements.agentSelect.addEventListener("change", onAgentChange);

  elements.messageInput.addEventListener("input", () => autoGrow(elements.messageInput));
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  elements.temperatureInput.addEventListener("change", onConfigInputChange);
  elements.maxTokensInput.addEventListener("change", onConfigInputChange);
  elements.systemPrompt.addEventListener("change", onConfigInputChange);
  elements.modelSelect.addEventListener("change", onModelChange);
  window.addEventListener("resize", renderEdgeAds);
}

function renderEdgeAds() {
  if (focusModeEnabled) {
    return;
  }
  renderEdgeAdBand("horizontal", elements.edgeAdTop);
  renderEdgeAdBand("vertical", elements.edgeAdLeft, {
    pinnedAds: [{ slot: 0, ad: { src: "/downloads/vintage_ads/casino/DiceRoll.gif" } }],
  });
  renderEdgeAdBand("vertical", elements.edgeAdRight, {
    pinnedAds: [{ slot: 1, ad: { src: "/downloads/vintage_ads/casino/DiceRoll.gif" } }],
  });
}

function loadFocusMode() {
  return localStorage.getItem(FOCUS_MODE_KEY) === "true";
}

function persistFocusMode() {
  localStorage.setItem(FOCUS_MODE_KEY, String(focusModeEnabled));
}

function applyFocusMode() {
  document.body.classList.toggle("focus-mode", focusModeEnabled);
  elements.focusModeButton.textContent = focusModeEnabled ? "Exit Focus Mode" : "Focus Mode";
}

function toggleFocusMode() {
  focusModeEnabled = !focusModeEnabled;
  persistFocusMode();
  applyFocusMode();
  if (!focusModeEnabled) {
    renderEdgeAds();
  }
}

function renderEdgeAdBand(category, container, options = {}) {
  if (!container) {
    return;
  }

  const slots = [...container.querySelectorAll(".edge-ad-slot")];
  const ads = pickRandomAds(EDGE_ADS[category], slots.length);
  const assignedAds = [...ads];

  (options.pinnedAds || []).forEach(({ slot, ad }) => {
    if (slot >= 0 && slot < assignedAds.length) {
      assignedAds[slot] = ad;
    }
  });

  slots.forEach((slot, index) => renderAdIntoSlot(slot, assignedAds[index]));
}

function renderAdIntoSlot(slot, ad) {
  slot.innerHTML = "";
  if (!ad) {
    return;
  }

  const image = document.createElement("img");
  image.src = ad.src;
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  slot.append(image);
}

function pickRandomAds(pool, count) {
  const ads = [...pool];
  for (let index = ads.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [ads[index], ads[swapIndex]] = [ads[swapIndex], ads[index]];
  }

  if (ads.length >= count) {
    return ads.slice(0, count);
  }

  const selected = [];
  for (let index = 0; index < count; index += 1) {
    selected.push(ads[index % ads.length]);
  }
  return selected;
}

async function loadModels() {
  const hadModelSelection = Boolean(settings.modelId);
  const response = await fetch("/api/models");
  modelCatalog = await response.json();
  modelCatalogById = Object.fromEntries(modelCatalog.map((model) => [model.id, model]));
  elements.modelSelect.innerHTML = "";
  modelCatalog.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label;
    elements.modelSelect.append(option);
  });

  const currentModel = settings.modelId || modelCatalog[0]?.id;
  elements.modelSelect.value = modelCatalog.some((model) => model.id === currentModel) ? currentModel : modelCatalog[0]?.id;
  settings.modelId = elements.modelSelect.value;
  if (!hadModelSelection) {
    applyModelDefaults(settings.modelId);
  }
  persistSettings();
}

function onModelChange() {
  applyModelDefaults(elements.modelSelect.value);
  onConfigInputChange();
}

function onConfigInputChange() {
  persistSettingsFromForm();
  const selectedAgent = getSelectedAgent();
  if (selectedAgent) {
    selectedAgent.modelId = settings.modelId;
    selectedAgent.temperature = settings.temperature;
    selectedAgent.maxTokens = settings.maxTokens;
    selectedAgent.systemPrompt = settings.systemPrompt;
    persistAgents();
  }
  renderAgents();
}

function applySettingsToForm() {
  elements.temperatureInput.value = settings.temperature;
  elements.maxTokensInput.value = settings.maxTokens;
  elements.systemPrompt.value = settings.systemPrompt;
  if (settings.agentId) {
    elements.agentSelect.value = settings.agentId;
  }
}

function persistSettingsFromForm() {
  settings = {
    ...settings,
    agentId: elements.agentSelect.value || DEFAULT_AGENT_ID,
    modelId: elements.modelSelect.value,
    temperature: Number(elements.temperatureInput.value || 0.7),
    maxTokens: Number(elements.maxTokensInput.value || 1024),
    systemPrompt: elements.systemPrompt.value.trim(),
  };
  persistSettings();
}

function persistSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function loadSettings() {
  const parsed = safeParse(localStorage.getItem(SETTINGS_KEY));
  return {
    agentId: parsed?.agentId ?? DEFAULT_AGENT_ID,
    modelId: parsed?.modelId ?? "",
    temperature: parsed?.temperature ?? 0.7,
    maxTokens: parsed?.maxTokens ?? 1024,
    systemPrompt: parsed?.systemPrompt ?? "",
  };
}

function loadAgents() {
  const parsed = safeParse(localStorage.getItem(AGENTS_KEY));
  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed.map((agent) => ({
    id: typeof agent.id === "string" ? agent.id : crypto.randomUUID(),
    name: typeof agent.name === "string" && agent.name.trim() ? agent.name.trim() : "Saved Agent",
    modelId: typeof agent.modelId === "string" ? agent.modelId : "",
    temperature: Number(agent.temperature ?? 0.7),
    maxTokens: Number(agent.maxTokens ?? 1024),
    systemPrompt: typeof agent.systemPrompt === "string" ? agent.systemPrompt : "",
  }));
}

function loadPresets() {
  const parsed = safeParse(localStorage.getItem(PRESETS_KEY));
  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed
    .map((preset) => ({
      id: typeof preset.id === "string" ? preset.id : crypto.randomUUID(),
      name: typeof preset.name === "string" ? preset.name.trim() : "",
      message: typeof preset.message === "string" ? preset.message.trim() : "",
      createdAt: Number(preset.createdAt ?? Date.now()),
    }))
    .filter((preset) => preset.name && preset.message);
}

function persistAgents() {
  localStorage.setItem(AGENTS_KEY, JSON.stringify(agents));
}

function persistPresets() {
  localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
}

function renderAgents() {
  const currentValue = settings.agentId || DEFAULT_AGENT_ID;
  elements.agentSelect.innerHTML = "";

  const customOption = document.createElement("option");
  customOption.value = DEFAULT_AGENT_ID;
  customOption.textContent = "Custom Setup";
  elements.agentSelect.append(customOption);

  agents.forEach((agent) => {
    const option = document.createElement("option");
    option.value = agent.id;
    option.textContent = agent.name;
    elements.agentSelect.append(option);
  });

  elements.agentSelect.value = agents.some((agent) => agent.id === currentValue) ? currentValue : DEFAULT_AGENT_ID;
  settings.agentId = elements.agentSelect.value;
  persistSettings();

  const selectedAgent = getSelectedAgent();
  elements.agentNameInput.value = selectedAgent?.name ?? "";
  elements.deleteAgentButton.disabled = !selectedAgent;
  elements.saveAgentButton.textContent = selectedAgent ? "Update Agent" : "Save Agent";
}

function onAgentChange() {
  settings.agentId = elements.agentSelect.value || DEFAULT_AGENT_ID;
  persistSettings();
  applySelectedAgent();
}

function applySelectedAgent() {
  const selectedAgent = getSelectedAgent();
  if (selectedAgent) {
    settings.modelId = selectedAgent.modelId || settings.modelId;
    settings.temperature = selectedAgent.temperature;
    settings.maxTokens = selectedAgent.maxTokens;
    settings.systemPrompt = selectedAgent.systemPrompt;
    persistSettings();
  }

  elements.modelSelect.value = settings.modelId || elements.modelSelect.value;
  elements.temperatureInput.value = settings.temperature;
  elements.maxTokensInput.value = settings.maxTokens;
  elements.systemPrompt.value = settings.systemPrompt;
  elements.agentNameInput.value = selectedAgent?.name ?? "";
  elements.deleteAgentButton.disabled = !selectedAgent;
  elements.saveAgentButton.textContent = selectedAgent ? "Update Agent" : "Save Agent";
}

function saveAgent() {
  persistSettingsFromForm();
  const name = elements.agentNameInput.value.trim();
  if (!name) {
    elements.agentNameInput.focus();
    return;
  }

  const selectedAgent = getSelectedAgent();
  if (selectedAgent) {
    selectedAgent.name = name;
    selectedAgent.modelId = settings.modelId;
    selectedAgent.temperature = settings.temperature;
    selectedAgent.maxTokens = settings.maxTokens;
    selectedAgent.systemPrompt = settings.systemPrompt;
  } else {
    const agent = {
      id: crypto.randomUUID(),
      name,
      modelId: settings.modelId,
      temperature: settings.temperature,
      maxTokens: settings.maxTokens,
      systemPrompt: settings.systemPrompt,
    };
    agents.unshift(agent);
    settings.agentId = agent.id;
  }

  persistAgents();
  persistSettings();
  renderAgents();
}

function deleteAgent() {
  const selectedAgent = getSelectedAgent();
  if (!selectedAgent) {
    return;
  }

  agents = agents.filter((agent) => agent.id !== selectedAgent.id);
  settings.agentId = DEFAULT_AGENT_ID;
  persistAgents();
  persistSettings();
  renderAgents();
}

function getSelectedAgent() {
  return agents.find((agent) => agent.id === elements.agentSelect.value) ?? null;
}

function renderPresets() {
  elements.presetList.innerHTML = "";

  if (!presets.length) {
    const empty = document.createElement("div");
    empty.className = "preset-empty";
    empty.textContent = "No presets yet. Save one here and it will show up in the start chat area.";
    elements.presetList.append(empty);
    return;
  }

  presets.forEach((preset) => {
    const card = document.createElement("article");
    card.className = "preset-card";

    const copy = document.createElement("div");
    copy.className = "preset-copy";
    copy.innerHTML = `
      <div class="preset-name">${escapeHtml(preset.name)}</div>
      <details class="preset-details">
        <summary class="preset-summary">Show first message</summary>
        <div class="preset-message-preview">${escapeHtml(preset.message)}</div>
      </details>
    `;

    const actions = document.createElement("div");
    actions.className = "preset-actions";

    const startButton = document.createElement("button");
    startButton.type = "button";
    startButton.className = "primary-button";
    startButton.textContent = "Start Chat";
    startButton.disabled = Boolean(activeAbortController);
    startButton.addEventListener("click", () => launchPreset(preset.id));

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "icon-button";
    deleteButton.textContent = "Delete";
    deleteButton.disabled = Boolean(activeAbortController);
    deleteButton.addEventListener("click", () => deletePreset(preset.id));

    actions.append(startButton, deleteButton);
    card.append(copy, actions);
    elements.presetList.append(card);
  });
}

function savePreset() {
  const name = elements.presetNameInput.value.trim();
  const message = elements.presetMessageInput.value.trim();
  if (!name) {
    elements.presetNameInput.focus();
    return;
  }
  if (!message) {
    elements.presetMessageInput.focus();
    return;
  }

  presets.unshift({
    id: crypto.randomUUID(),
    name,
    message,
    createdAt: Date.now(),
  });
  persistPresets();
  renderPresets();
  elements.presetNameInput.value = "";
  elements.presetMessageInput.value = "";
}

function deletePreset(presetId) {
  presets = presets.filter((preset) => preset.id !== presetId);
  persistPresets();
  renderPresets();
}

function loadSessions() {
  const parsed = safeParse(localStorage.getItem(STORAGE_KEY))
    ?? safeParse(localStorage.getItem(LEGACY_STORAGE_KEY));
  if (!Array.isArray(parsed) || !parsed.length) {
    return [];
  }

  return parsed.map((session) => {
    const messages = Array.isArray(session.messages)
      ? session.messages.map((message) => normalizeMessage(message))
      : [];
    const savedTitle = typeof session.title === "string" ? session.title.trim() : "";
    const fallbackTitle = deriveSessionTitleFromMessages(messages);

    return {
      id: typeof session.id === "string" ? session.id : crypto.randomUUID(),
      title: savedTitle && savedTitle !== "New chat" ? savedTitle : (fallbackTitle || "New chat"),
      createdAt: Number(session.createdAt ?? Date.now()),
      updatedAt: Number(session.updatedAt ?? Date.now()),
      titleRequested: false,
      titleGenerated: false,
      messages,
    };
  });
}

function normalizeMessage(message) {
  return {
    id: typeof message.id === "string" ? message.id : crypto.randomUUID(),
    role: message.role === "assistant" ? "assistant" : "user",
    content: typeof message.content === "string" ? message.content : "",
    streaming: Boolean(message.streaming),
    modelId: typeof message.modelId === "string" ? message.modelId : "",
    editing: false,
  };
}

function createSession() {
  return createSessionWithMessage();
}

function createSessionWithMessage(initialMessage = "") {
  const session = {
    id: crypto.randomUUID(),
    title: deriveSessionTitleFromText(initialMessage) || "New chat",
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: initialMessage ? [{
      id: crypto.randomUUID(),
      role: "user",
      content: initialMessage,
      streaming: false,
      modelId: "",
      editing: false,
    }] : [],
    titleRequested: false,
    titleGenerated: false,
  };
  sessions.unshift(session);
  persistSessions();
  return session;
}

function persistSessions() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
}

function getActiveSession() {
  return sessions.find((session) => session.id === activeSessionId);
}

function renderHistory() {
  elements.historyList.innerHTML = "";
  sessions.forEach((session) => {
    const entry = document.createElement("div");
    entry.className = "history-entry";

    const button = document.createElement("button");
    button.type = "button";
    button.className = `history-item${session.id === activeSessionId ? " active" : ""}`;
    const title = session.title?.trim() || "New chat";
    const meta = new Date(session.updatedAt).toLocaleString();
    button.innerHTML = `
      <span class="history-title">${escapeHtml(title)}</span>
      <span class="history-meta">${escapeHtml(meta)}</span>
    `;
    button.addEventListener("click", () => {
      activeSessionId = session.id;
      renderHistory();
      renderActiveSession();
    });

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "icon-button history-delete-button";
    deleteButton.textContent = "x";
    deleteButton.setAttribute("aria-label", "Delete chat");
    deleteButton.title = "Delete chat";
    deleteButton.disabled = Boolean(activeAbortController && session.id === activeSessionId);
    deleteButton.addEventListener("click", () => deleteSession(session.id));

    entry.append(button, deleteButton);
    elements.historyList.append(entry);
  });
}

function renderActiveSession() {
  const session = getActiveSession();
  const hasMessages = Boolean(session?.messages.length);
  elements.emptyState.style.display = hasMessages ? "none" : "grid";
  elements.messages.classList.toggle("active", hasMessages);
  elements.messages.innerHTML = "";

  session?.messages.forEach((message) => {
    elements.messages.append(createMessageNode(message));
  });

  if (hasMessages) {
    scrollMessagesToBottom();
  }
}

function createMessageNode(message) {
  const fragment = elements.messageTemplate.content.cloneNode(true);
  const article = fragment.querySelector(".message");
  const role = fragment.querySelector(".message-role");
  const content = fragment.querySelector(".message-content");
  const copyButton = fragment.querySelector(".copy-message-button");
  const editButton = fragment.querySelector(".edit-message-button");
  const deleteButton = fragment.querySelector(".delete-message-button");

  article.dataset.messageId = message.id;
  article.classList.add(message.role);
  role.textContent = getMessageRoleLabel(message);
  updateRenderedMessage(content, message);

  copyButton.addEventListener("click", async () => {
    await navigator.clipboard.writeText(message.content || "");
    copyButton.textContent = "Copied";
    setTimeout(() => {
      copyButton.textContent = "Copy";
    }, 1200);
  });

  editButton.disabled = Boolean(message.streaming) || Boolean(activeAbortController);
  deleteButton.disabled = Boolean(message.streaming) || Boolean(activeAbortController);

  editButton.addEventListener("click", () => toggleEditMessage(message.id));
  deleteButton.addEventListener("click", () => deleteMessage(message.id));

  return fragment;
}

function getMessageRoleLabel(message) {
  if (message.role === "assistant") {
    const modelLabel = getModelLabel(message.modelId);
    return modelLabel ? `assistant - ${modelLabel}` : "assistant";
  }
  return "user";
}

function getModelLabel(modelId) {
  return modelCatalog.find((model) => model.id === modelId)?.label ?? modelId ?? "";
}

function updateMessageNode(message, options = {}) {
  const article = elements.messages.querySelector(`[data-message-id="${message.id}"]`);
  if (!article) {
    return;
  }

  const role = article.querySelector(".message-role");
  const content = article.querySelector(".message-content");
  const editButton = article.querySelector(".edit-message-button");
  const deleteButton = article.querySelector(".delete-message-button");

  role.textContent = getMessageRoleLabel(message);
  editButton.disabled = Boolean(message.streaming) || Boolean(activeAbortController);
  deleteButton.disabled = Boolean(message.streaming) || Boolean(activeAbortController);

  const shouldStick = options.forceScroll || isNearBottom(elements.messages);
  updateRenderedMessage(content, message);
  if (shouldStick) {
    scrollMessagesToBottom();
  }
}

function updateRenderedMessage(contentNode, message) {
  if (message.editing) {
    renderEditMode(contentNode, message);
    return;
  }

  const rendered = marked.parse(message.content || "");
  contentNode.innerHTML = DOMPurify.sanitize(rendered);
  enhanceRenderedMessage(contentNode, message.content || "");
  contentNode.classList.toggle("streaming", Boolean(message.streaming));
}

function renderEditMode(contentNode, message) {
  contentNode.classList.remove("streaming");
  contentNode.innerHTML = `
    <div class="message-edit-box">
      <textarea class="message-edit-input">${escapeHtml(message.content || "")}</textarea>
      <div class="message-edit-actions">
        <button class="secondary-button cancel-edit-button" type="button">Cancel</button>
        <button class="primary-button save-edit-button" type="button">Save</button>
      </div>
    </div>
  `;

  const input = contentNode.querySelector(".message-edit-input");
  const saveButton = contentNode.querySelector(".save-edit-button");
  const cancelButton = contentNode.querySelector(".cancel-edit-button");
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);

  saveButton.addEventListener("click", () => saveEditedMessage(message.id, input.value));
  cancelButton.addEventListener("click", () => toggleEditMessage(message.id, false));
}

function enhanceRenderedMessage(container, rawText) {
  container.querySelectorAll("pre code").forEach((block) => {
    hljs.highlightElement(block);
    if (block.parentElement.previousElementSibling?.classList.contains("code-toolbar")) {
      return;
    }

    const toolbar = document.createElement("div");
    toolbar.className = "code-toolbar";
    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "icon-button";
    copyButton.textContent = "Copy code";
    copyButton.addEventListener("click", async () => {
      await navigator.clipboard.writeText(block.textContent || rawText);
      copyButton.textContent = "Copied";
      setTimeout(() => {
        copyButton.textContent = "Copy code";
      }, 1200);
    });
    toolbar.append(copyButton);
    block.parentElement.before(toolbar);
  });
}

async function sendMessage() {
  const input = elements.messageInput.value.trim();
  await sendMessageWithContent(input);
}

async function sendMessageWithContent(input) {
  if (!input || activeAbortController) {
    return;
  }

  persistSettingsFromForm();
  const session = getActiveSession();
  if (!session) {
    return;
  }

  clearEditingState(session);

  const userMessage = {
    id: crypto.randomUUID(),
    role: "user",
    content: input,
    streaming: false,
    modelId: "",
    editing: false,
  };
  session.messages.push(userMessage);
  session.updatedAt = Date.now();
  syncSessionTitleFallback(session);
  elements.messageInput.value = "";
  autoGrow(elements.messageInput);
  persistSessions();
  renderHistory();
  renderActiveSession();

  await streamAssistantReply(session, settings.modelId);
}

async function launchPreset(presetId) {
  const preset = presets.find((item) => item.id === presetId);
  if (!preset || activeAbortController) {
    return;
  }

  persistSettingsFromForm();
  const session = createSessionWithMessage(preset.message);
  activeSessionId = session.id;
  renderPresets();
  renderHistory();
  renderActiveSession();
  await streamAssistantReply(session, settings.modelId);
}

async function streamAssistantReply(session, modelId) {
  const assistantMessage = {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "",
    streaming: true,
    modelId,
    editing: false,
  };

  session.messages.push(assistantMessage);
  session.updatedAt = Date.now();
  persistSessions();
  renderHistory();
  renderActiveSession();

  activeAbortController = new AbortController();
  updateStatus("Streaming");
  elements.sendButton.disabled = true;
  elements.stopButton.disabled = false;
  renderPresets();

  const outboundMessages = buildConversationMessages(session);

  try {
    const response = await fetch("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: modelId,
        stream: true,
        temperature: settings.temperature,
        max_tokens: settings.maxTokens,
        provider_options: getModelProviderOptions(modelId),
        messages: outboundMessages,
      }),
      signal: activeAbortController.signal,
    });

    if (!response.ok || !response.body) {
      const errorPayload = await response.json().catch(() => ({}));
      throw new Error(errorPayload.detail || "Request failed");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const eventChunk of events) {
        const line = eventChunk
          .split("\n")
          .find((entry) => entry.startsWith("data: "));
        if (!line) {
          continue;
        }
        const payload = line.slice(6);
        if (payload === "[DONE]") {
          continue;
        }

        const parsed = JSON.parse(payload);
        if (parsed.error) {
          throw new Error(parsed.error.message);
        }

        const choice = parsed.choices?.[0];
        const delta = choice?.delta ?? {};
        if (typeof delta.content === "string") {
          assistantMessage.content += delta.content;
          updateMessageNode(assistantMessage);
        }
      }
    }

    assistantMessage.streaming = false;
    session.updatedAt = Date.now();
    persistSessions();
    renderHistory();
    updateMessageNode(assistantMessage);
    updateStatus("Idle");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    assistantMessage.streaming = false;
    assistantMessage.content = assistantMessage.content || `Request failed: ${message}`;
    session.updatedAt = Date.now();
    persistSessions();
    renderHistory();
    updateMessageNode(assistantMessage);
    updateStatus(message.includes("aborted") ? "Stopped" : "Error");
  } finally {
    activeAbortController = null;
    elements.sendButton.disabled = false;
    elements.stopButton.disabled = true;
    refreshMessageActionStates();
  }
}

function getModelProviderOptions(modelId) {
  const options = modelCatalogById[modelId]?.provider_options;
  return options && typeof options === "object" ? options : {};
}

function applyModelDefaults(modelId) {
  const model = modelCatalogById[modelId];
  if (!model) {
    return;
  }
  if (typeof model.default_temperature === "number") {
    settings.temperature = model.default_temperature;
    elements.temperatureInput.value = model.default_temperature;
  }
  if (typeof model.default_max_tokens === "number") {
    settings.maxTokens = model.default_max_tokens;
    elements.maxTokensInput.value = model.default_max_tokens;
  }
}

function buildConversationMessages(session) {
  const conversationMessages = session.messages
    .filter((message) => !message.streaming)
    .map((message) => ({ role: message.role, content: message.content }));
  const outboundMessages = trimConversationForContext(conversationMessages);

  if (settings.systemPrompt) {
    return [{ role: "system", content: settings.systemPrompt }, ...outboundMessages];
  }

  return outboundMessages;
}

function toggleEditMessage(messageId, nextState = true) {
  if (activeAbortController) {
    return;
  }

  const session = getActiveSession();
  if (!session) {
    return;
  }

  session.messages.forEach((message) => {
    message.editing = message.id === messageId ? nextState : false;
  });
  persistSessions();
  renderActiveSession();
}

function saveEditedMessage(messageId, nextContent) {
  const session = getActiveSession();
  if (!session) {
    return;
  }

  const messageIndex = session.messages.findIndex((item) => item.id === messageId);
  if (messageIndex < 0) {
    return;
  }

  const message = session.messages[messageIndex];
  const trimmed = nextContent.trim();
  if (!trimmed) {
    return;
  }

  message.content = trimmed;
  message.editing = false;
  applyConversationMutation(session, messageIndex + 1);
}

function deleteMessage(messageId) {
  if (activeAbortController) {
    return;
  }

  const session = getActiveSession();
  if (!session) {
    return;
  }

  const messageIndex = session.messages.findIndex((message) => message.id === messageId);
  if (messageIndex < 0) {
    return;
  }

  applyConversationMutation(session, messageIndex);
}

function deleteSession(sessionId) {
  if (!sessionId || (activeAbortController && sessionId === activeSessionId)) {
    return;
  }

  sessions = sessions.filter((session) => session.id !== sessionId);
  if (!sessions.length) {
    const nextSession = createSession();
    activeSessionId = nextSession.id;
  } else if (activeSessionId === sessionId) {
    activeSessionId = sessions[0].id;
  }

  persistSessions();
  renderHistory();
  renderActiveSession();
}

function clearEditingState(session) {
  session.messages.forEach((message) => {
    message.editing = false;
  });
}

function applyConversationMutation(session, nextLength) {
  clearEditingState(session);
  session.messages = session.messages.slice(0, nextLength);
  session.updatedAt = Date.now();
  resetSessionTitle(session);
  syncSessionTitleFallback(session);
  persistSessions();
  renderHistory();
  renderActiveSession();

  const tailMessage = session.messages.at(-1);
  if (tailMessage?.role === "user") {
    void streamAssistantReply(session, settings.modelId);
  }
}

function refreshMessageActionStates() {
  const session = getActiveSession();
  session?.messages.forEach((message) => updateMessageNode(message));
  renderPresets();
  renderHistory();
  renderActiveSession();
}

function resetSessionTitle(session) {
  session.title = "New chat";
  session.titleRequested = false;
  session.titleGenerated = false;
}

function syncSessionTitleFallback(session) {
  if (session.titleGenerated) {
    return;
  }

  const fallbackTitle = deriveSessionTitleFromMessages(session.messages);
  session.title = fallbackTitle || "New chat";
}

function stopStreaming() {
  if (!activeAbortController) {
    return;
  }
  activeAbortController.abort();
  updateStatus("Stopped");
}

function updateStatus(text) {
  elements.statusPill.textContent = text;
  elements.statusPill.classList.remove("is-idle", "is-streaming", "is-error", "is-stopped");
  const normalized = String(text || "").toLowerCase();
  if (normalized === "streaming") {
    elements.statusPill.classList.add("is-streaming");
    return;
  }
  if (normalized === "error") {
    elements.statusPill.classList.add("is-error");
    return;
  }
  if (normalized === "stopped") {
    elements.statusPill.classList.add("is-stopped");
    return;
  }
  elements.statusPill.classList.add("is-idle");
}

function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function scrollMessagesToBottom() {
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function isNearBottom(container, threshold = 64) {
  const distance = container.scrollHeight - container.scrollTop - container.clientHeight;
  return distance <= threshold;
}

async function maybeGenerateSessionTitle(sessionId, modelId) {
  void sessionId;
  void modelId;
}

function deriveSessionTitleFromMessages(messages) {
  const firstUser = messages.find((message) => message.role === "user" && !message.streaming);
  return deriveSessionTitleFromText(firstUser?.content || "");
}

function deriveSessionTitleFromText(value) {
  if (typeof value !== "string") {
    return "";
  }

  const cleaned = value
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) {
    return "";
  }

  return cleaned.slice(0, 80).split(/\s+/).slice(0, 6).join(" ");
}

function trimConversationForContext(messages) {
  if (!messages.length) {
    return [];
  }

  const selected = [];
  let charCount = 0;

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const nextCost = estimateMessageCost(message);
    const exceedsMessageLimit = selected.length >= CONTEXT_MESSAGE_LIMIT;
    const exceedsCharBudget = selected.length > 0 && (charCount + nextCost > CONTEXT_CHAR_BUDGET);

    if (exceedsMessageLimit || exceedsCharBudget) {
      break;
    }

    selected.unshift(message);
    charCount += nextCost;
  }

  if (!selected.length) {
    return [messages.at(-1)];
  }

  return selected;
}

function estimateMessageCost(message) {
  return (message?.content?.length || 0) + 32;
}

function safeParse(value) {
  if (!value) {
    return null;
  }
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
