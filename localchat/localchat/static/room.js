const ROOM_SETTINGS_KEY = "localchat.roomSettings.v2";
const ROOM_AGENTS_KEY = "localchat.roomAgents.v1";
const DEFAULT_AGENT_ID = "custom";
const DEFAULT_MODEL_ID = "ollama:qwen2.5:7b";
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
  agentNameInput: document.querySelector("#room-agent-name-input"),
  agentSelect: document.querySelector("#room-agent-select"),
  connectButton: document.querySelector("#connect-room-button"),
  deleteAgentButton: document.querySelector("#delete-room-agent-button"),
  disconnectButton: document.querySelector("#disconnect-room-button"),
  displayNameInput: document.querySelector("#display-name-input"),
  edgeAdLeft: document.querySelector("#edge-ad-left"),
  edgeAdRight: document.querySelector("#edge-ad-right"),
  edgeAdTop: document.querySelector("#edge-ad-top"),
  emptyState: document.querySelector("#room-empty-state"),
  maxTokensInput: document.querySelector("#room-max-tokens-input"),
  messageInput: document.querySelector("#room-message-input"),
  messages: document.querySelector("#room-messages"),
  modelSelect: document.querySelector("#room-model-select"),
  profileAgent: document.querySelector("#room-profile-agent"),
  profileHandle: document.querySelector("#room-profile-handle"),
  profileName: document.querySelector("#room-profile-name"),
  profileStatus: document.querySelector("#room-profile-status"),
  roomInput: document.querySelector("#room-name-input"),
  saveAgentButton: document.querySelector("#save-room-agent-button"),
  sendButton: document.querySelector("#send-room-button"),
  serverInput: document.querySelector("#server-url-input"),
  statusPill: document.querySelector("#room-status-pill"),
  systemPromptInput: document.querySelector("#room-system-prompt"),
  temperatureInput: document.querySelector("#room-temperature-input"),
};

marked.setOptions({
  breaks: true,
  gfm: true,
});

let modelCatalog = [];
let roomAgents = loadRoomAgents();
let roomSettings = loadRoomSettings();
let roomSocket = null;
const localModelServerBase = normalizeServerBase(window.location.origin);

applyRoomSettingsToForm();
renderEdgeAds();
renderRoomAgents();
applySelectedRoomAgent();
updateRoomMeta();
updateRoomEmptyState();
autoGrow(elements.messageInput);
await loadModelsForServer();
bindEvents();

function bindEvents() {
  elements.connectButton.addEventListener("click", () => connectToRoom());
  elements.disconnectButton.addEventListener("click", () => disconnectFromRoom());
  elements.sendButton.addEventListener("click", () => sendRoomMessage());
  elements.saveAgentButton.addEventListener("click", saveRoomAgent);
  elements.deleteAgentButton.addEventListener("click", deleteRoomAgent);
  elements.agentSelect.addEventListener("change", onRoomAgentChange);

  elements.messageInput.addEventListener("input", () => autoGrow(elements.messageInput));
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendRoomMessage();
    }
  });

  [
    elements.serverInput,
    elements.roomInput,
    elements.displayNameInput,
    elements.agentNameInput,
  ].forEach((element) => element.addEventListener("change", persistRoomSettingsFromFormSafe));

  elements.modelSelect.addEventListener("change", onRoomConfigInputChange);
  elements.systemPromptInput.addEventListener("change", onRoomConfigInputChange);
  elements.temperatureInput.addEventListener("change", onRoomConfigInputChange);
  elements.maxTokensInput.addEventListener("change", onRoomConfigInputChange);
  window.addEventListener("resize", renderEdgeAds);
}

function renderEdgeAds() {
  renderEdgeAdBand("horizontal", elements.edgeAdTop);
  renderEdgeAdBand("vertical", elements.edgeAdLeft);
  renderEdgeAdBand("vertical", elements.edgeAdRight);
}

function renderEdgeAdBand(category, container) {
  if (!container) {
    return;
  }

  const slots = [...container.querySelectorAll(".edge-ad-slot")];
  const ads = pickRandomAds(EDGE_ADS[category], slots.length);
  slots.forEach((slot, index) => renderAdIntoSlot(slot, ads[index]));
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

function applyRoomSettingsToForm() {
  elements.serverInput.value = roomSettings.serverUrl;
  elements.roomInput.value = roomSettings.roomName;
  elements.displayNameInput.value = roomSettings.displayName;
  elements.agentNameInput.value = roomSettings.agentName;
  elements.systemPromptInput.value = roomSettings.systemPrompt;
  elements.temperatureInput.value = roomSettings.temperature;
  elements.maxTokensInput.value = roomSettings.maxTokens;
}

function persistRoomSettingsFromFormSafe() {
  try {
    persistRoomSettingsFromForm();
  } catch {
    return;
  }
  updateRoomMeta();
}

function persistRoomSettingsFromForm() {
  roomSettings = {
    ...roomSettings,
    serverUrl: normalizeServerBase(elements.serverInput.value),
    roomName: normalizeRoomName(elements.roomInput.value),
    displayName: normalizeRoomName(elements.displayNameInput.value, "guest"),
    agentId: elements.agentSelect.value || DEFAULT_AGENT_ID,
    agentName: normalizeAgentName(elements.agentNameInput.value),
    systemPrompt: elements.systemPromptInput.value.trim(),
    modelId: elements.modelSelect.value || roomSettings.modelId || DEFAULT_MODEL_ID,
    temperature: Number(elements.temperatureInput.value || 0.7),
    maxTokens: Number(elements.maxTokensInput.value || 512),
  };
  localStorage.setItem(ROOM_SETTINGS_KEY, JSON.stringify(roomSettings));
}

function loadRoomSettings() {
  const parsed = safeParse(localStorage.getItem(ROOM_SETTINGS_KEY));
  let serverUrl = window.location.origin;
  try {
    serverUrl = normalizeServerBase(parsed?.serverUrl || window.location.origin);
  } catch {
    serverUrl = window.location.origin;
  }

  return {
    serverUrl,
    roomName: normalizeRoomName(parsed?.roomName || "lobby"),
    displayName: normalizeRoomName(parsed?.displayName || "guest", "guest"),
    agentId: parsed?.agentId ?? DEFAULT_AGENT_ID,
    agentName: normalizeAgentName(parsed?.agentName || "Room AI"),
    systemPrompt: typeof parsed?.systemPrompt === "string" ? parsed.systemPrompt : "",
    modelId: parsed?.modelId || DEFAULT_MODEL_ID,
    temperature: Number(parsed?.temperature ?? 0.7),
    maxTokens: Number(parsed?.maxTokens ?? 512),
  };
}

function loadRoomAgents() {
  const parsed = safeParse(localStorage.getItem(ROOM_AGENTS_KEY));
  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed.map((agent) => ({
    id: typeof agent.id === "string" ? agent.id : crypto.randomUUID(),
    name: normalizeAgentName(agent.name || "Room AI"),
    modelId: typeof agent.modelId === "string" ? agent.modelId : "",
    temperature: Number(agent.temperature ?? 0.7),
    maxTokens: Number(agent.maxTokens ?? 512),
    systemPrompt: typeof agent.systemPrompt === "string" ? agent.systemPrompt : "",
  }));
}

function persistRoomAgents() {
  localStorage.setItem(ROOM_AGENTS_KEY, JSON.stringify(roomAgents));
}

function renderRoomAgents() {
  const currentValue = roomSettings.agentId || DEFAULT_AGENT_ID;
  elements.agentSelect.innerHTML = "";

  const customOption = document.createElement("option");
  customOption.value = DEFAULT_AGENT_ID;
  customOption.textContent = "Custom Setup";
  elements.agentSelect.append(customOption);

  roomAgents.forEach((agent) => {
    const option = document.createElement("option");
    option.value = agent.id;
    option.textContent = agent.name;
    elements.agentSelect.append(option);
  });

  elements.agentSelect.value = roomAgents.some((agent) => agent.id === currentValue) ? currentValue : DEFAULT_AGENT_ID;
  roomSettings.agentId = elements.agentSelect.value;
  persistRoomSettings();

  const selectedAgent = getSelectedRoomAgent();
  elements.agentNameInput.value = selectedAgent?.name ?? roomSettings.agentName;
  elements.deleteAgentButton.disabled = !selectedAgent;
  elements.saveAgentButton.textContent = selectedAgent ? "Update Agent" : "Save Agent";
}

function onRoomAgentChange() {
  roomSettings.agentId = elements.agentSelect.value || DEFAULT_AGENT_ID;
  persistRoomSettings();
  applySelectedRoomAgent();
}

function applySelectedRoomAgent() {
  const selectedAgent = getSelectedRoomAgent();
  if (selectedAgent) {
    roomSettings.modelId = selectedAgent.modelId || roomSettings.modelId;
    roomSettings.agentName = selectedAgent.name;
    roomSettings.temperature = selectedAgent.temperature;
    roomSettings.maxTokens = selectedAgent.maxTokens;
    roomSettings.systemPrompt = selectedAgent.systemPrompt;
    persistRoomSettings();
  }

  elements.agentNameInput.value = selectedAgent?.name ?? roomSettings.agentName;
  elements.systemPromptInput.value = roomSettings.systemPrompt;
  elements.temperatureInput.value = roomSettings.temperature;
  elements.maxTokensInput.value = roomSettings.maxTokens;
  elements.modelSelect.value = roomSettings.modelId || elements.modelSelect.value;
  elements.deleteAgentButton.disabled = !selectedAgent;
  elements.saveAgentButton.textContent = selectedAgent ? "Update Agent" : "Save Agent";
  updateRoomMeta();
}

function saveRoomAgent() {
  persistRoomSettingsFromForm();
  const name = normalizeAgentName(elements.agentNameInput.value);
  if (!name) {
    elements.agentNameInput.focus();
    return;
  }

  const selectedAgent = getSelectedRoomAgent();
  if (selectedAgent) {
    selectedAgent.name = name;
    selectedAgent.modelId = roomSettings.modelId;
    selectedAgent.temperature = roomSettings.temperature;
    selectedAgent.maxTokens = roomSettings.maxTokens;
    selectedAgent.systemPrompt = roomSettings.systemPrompt;
  } else {
    const agent = {
      id: crypto.randomUUID(),
      name,
      modelId: roomSettings.modelId,
      temperature: roomSettings.temperature,
      maxTokens: roomSettings.maxTokens,
      systemPrompt: roomSettings.systemPrompt,
    };
    roomAgents.unshift(agent);
    roomSettings.agentId = agent.id;
  }

  roomSettings.agentName = name;
  persistRoomAgents();
  persistRoomSettings();
  renderRoomAgents();
  updateRoomMeta();
}

function deleteRoomAgent() {
  const selectedAgent = getSelectedRoomAgent();
  if (!selectedAgent) {
    return;
  }

  roomAgents = roomAgents.filter((agent) => agent.id !== selectedAgent.id);
  roomSettings.agentId = DEFAULT_AGENT_ID;
  persistRoomAgents();
  persistRoomSettings();
  renderRoomAgents();
  applySelectedRoomAgent();
}

function getSelectedRoomAgent() {
  return roomAgents.find((agent) => agent.id === elements.agentSelect.value) ?? null;
}

function onRoomConfigInputChange() {
  persistRoomSettingsFromFormSafe();
  const selectedAgent = getSelectedRoomAgent();
  if (!selectedAgent) {
    return;
  }

  selectedAgent.modelId = roomSettings.modelId;
  selectedAgent.temperature = roomSettings.temperature;
  selectedAgent.maxTokens = roomSettings.maxTokens;
  selectedAgent.systemPrompt = roomSettings.systemPrompt;
  persistRoomAgents();
}

function persistRoomSettings() {
  localStorage.setItem(ROOM_SETTINGS_KEY, JSON.stringify(roomSettings));
}

async function loadModelsForServer() {
  persistRoomSettingsFromForm();

  try {
    const response = await fetch(`${localModelServerBase}/api/models`, { mode: "cors" });
    if (!response.ok) {
      throw new Error(`Model list request failed (${response.status})`);
    }

    modelCatalog = await response.json();
    renderModelOptions(modelCatalog);
    updateStatus(roomSocket ? `Connected to #${roomSettings.roomName}` : "Disconnected");
  } catch (error) {
    modelCatalog = [{ id: roomSettings.modelId || DEFAULT_MODEL_ID, label: roomSettings.modelId || DEFAULT_MODEL_ID }];
    renderModelOptions(modelCatalog);
    appendLocalSystemMessage(`Could not load local models from ${localModelServerBase}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function renderModelOptions(models) {
  elements.modelSelect.innerHTML = "";
  models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label || model.id;
    elements.modelSelect.append(option);
  });

  const nextValue = models.some((model) => model.id === roomSettings.modelId)
    ? roomSettings.modelId
    : models[0]?.id || DEFAULT_MODEL_ID;
  elements.modelSelect.value = nextValue;
  roomSettings.modelId = nextValue;
  persistRoomSettings();
  updateRoomMeta();
}

async function connectToRoom() {
  if (roomSocket && roomSocket.readyState <= WebSocket.OPEN) {
    return;
  }

  try {
    persistRoomSettingsFromForm();
  } catch (error) {
    appendLocalSystemMessage(`Invalid server URL: ${error instanceof Error ? error.message : String(error)}`);
    updateStatus("Error");
    return;
  }

  await loadModelsForServer();

  const socketUrl = buildSocketUrl(roomSettings.serverUrl, roomSettings.roomName, roomSettings.displayName);
  updateStatus("Connecting");

  roomSocket = new WebSocket(socketUrl);
  roomSocket.addEventListener("open", () => {
    updateStatus(`Connected to #${roomSettings.roomName}`);
    elements.sendButton.disabled = false;
    elements.disconnectButton.disabled = false;
    elements.connectButton.disabled = true;
    appendLocalSystemMessage(`Connected to ${socketUrl}`);
  });

  roomSocket.addEventListener("message", (event) => handleSocketMessage(event.data));
  roomSocket.addEventListener("close", (event) => {
    updateStatus("Disconnected");
    elements.sendButton.disabled = true;
    elements.disconnectButton.disabled = true;
    elements.connectButton.disabled = false;
    if (event.reason) {
      appendLocalSystemMessage(`Disconnected: ${event.reason}`);
    }
    roomSocket = null;
  });
  roomSocket.addEventListener("error", () => {
    appendLocalSystemMessage("Socket connection error.");
    updateStatus("Error");
  });
}

function disconnectFromRoom() {
  if (!roomSocket) {
    return;
  }
  roomSocket.close();
}

function sendRoomMessage() {
  const content = elements.messageInput.value.trim();
  if (!content || !roomSocket || roomSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  persistRoomSettingsFromForm();
  roomSocket.send(JSON.stringify({
    type: "chat",
    content,
    agentName: roomSettings.agentName,
    systemPrompt: roomSettings.systemPrompt,
    modelId: roomSettings.modelId,
    temperature: roomSettings.temperature,
    maxTokens: roomSettings.maxTokens,
  }));

  elements.messageInput.value = "";
  autoGrow(elements.messageInput);
}

function handleSocketMessage(rawPayload) {
  const payload = safeParse(rawPayload);
  if (!payload) {
    appendLocalSystemMessage("Received invalid room payload.");
    return;
  }

  if (payload.type === "history") {
    elements.messages.innerHTML = "";
    payload.messages.forEach((message) => appendRoomMessage(message));
    updateRoomEmptyState();
    scrollMessagesToBottom();
    return;
  }

  appendRoomMessage(payload);
}

function appendRoomMessage(message) {
  const article = document.createElement("article");
  article.className = `message room-message ${messageClassFor(message)}`;
  article.dataset.messageId = message.id || crypto.randomUUID();

  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.innerHTML = `
    <span class="message-role">${escapeHtml(getRoomLabel(message))}</span>
    <span class="room-meta-tail">${escapeHtml(formatTimestamp(message.createdAt))}</span>
  `;

  const content = document.createElement("div");
  content.className = "message-content markdown-body";
  const rendered = marked.parse(message.content || "");
  content.innerHTML = DOMPurify.sanitize(rendered);
  enhanceRenderedMessage(content, message.content || "");

  article.append(meta, content);
  elements.messages.append(article);
  updateRoomEmptyState();
  scrollMessagesToBottom();
}

function getRoomLabel(message) {
  const modelLabel = message.modelId ? getModelLabel(message.modelId) : "";
  const modelSuffix = modelLabel ? ` - ${modelLabel}` : "";
  if (message.speakerType === "ai") {
    return `${message.sender || "Room AI"}${modelSuffix}`;
  }
  if (message.speakerType === "system") {
    return "system";
  }
  return message.sender || "guest";
}

function messageClassFor(message) {
  if (message.speakerType === "ai") {
    return "assistant";
  }
  if (message.speakerType === "system") {
    return "room-system";
  }
  return "user";
}

function appendLocalSystemMessage(content) {
  appendRoomMessage({
    id: crypto.randomUUID(),
    speakerType: "system",
    sender: "system",
    content,
    createdAt: Date.now(),
  });
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

function updateStatus(value) {
  if (elements.statusPill) {
    elements.statusPill.textContent = value;
  }
  elements.profileStatus.textContent = value === "Disconnected" ? "OFFLINE" : value.toUpperCase();
}

function updateRoomMeta() {
  elements.profileHandle.textContent = roomSettings.displayName;
  elements.profileName.textContent = roomSettings.roomName;
  elements.profileAgent.textContent = roomSettings.agentName || "Room AI";
}

function updateRoomEmptyState() {
  const hasMessages = elements.messages.childElementCount > 0;
  elements.emptyState.style.display = hasMessages ? "none" : "grid";
  elements.messages.classList.toggle("active", hasMessages);
}

function scrollMessagesToBottom() {
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function buildSocketUrl(serverBase, roomName, displayName) {
  const baseUrl = new URL(normalizeServerBase(serverBase));
  baseUrl.protocol = baseUrl.protocol === "https:" ? "wss:" : "ws:";
  baseUrl.pathname = `/ws/rooms/${encodeURIComponent(normalizeRoomName(roomName))}`;
  baseUrl.searchParams.set("name", normalizeRoomName(displayName, "guest"));
  return baseUrl.toString();
}

function normalizeServerBase(value) {
  const rawValue = (value || "").trim();
  if (!rawValue) {
    return window.location.origin;
  }

  try {
    const withScheme = /^[a-z]+:\/\//i.test(rawValue) ? rawValue : `http://${rawValue}`;
    const parsed = new URL(withScheme);
    if (parsed.protocol === "ws:") {
      parsed.protocol = "http:";
    } else if (parsed.protocol === "wss:") {
      parsed.protocol = "https:";
    }
    parsed.pathname = "";
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString().replace(/\/$/, "");
  } catch {
    throw new Error(`Could not parse "${rawValue}"`);
  }
}

function normalizeRoomName(value, fallback = "lobby") {
  const cleaned = (value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return cleaned || fallback;
}

function normalizeAgentName(value) {
  const cleaned = String(value || "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 48);
  return cleaned || "Room AI";
}

function getModelLabel(modelId) {
  return modelCatalog.find((model) => model.id === modelId)?.label ?? modelId ?? "";
}

function formatTimestamp(value) {
  const timestamp = Number(value || Date.now());
  return new Date(timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
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
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
