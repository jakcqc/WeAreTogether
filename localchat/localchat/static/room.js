const ROOM_SETTINGS_KEY = "localchat.roomSettings.v2";
const ROOM_AGENTS_KEY = "localchat.roomAgents.v1";
const DEFAULT_AGENT_ID = "custom";
const DEFAULT_MODEL_ID = "ollama:qwen2.5:7b";
const DEFAULT_AI_RUNTIME_URL = "http://127.0.0.1:11434";
const WEBRTC_CONFIG = {
  iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
};
const QUICK_REACTION_EMOJIS = ["👍", "❤️", "😂", "🔥", "🎉"];
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
  focusButton: document.querySelector("#focus-room-button"),
  imageClearButton: document.querySelector("#room-image-clear-button"),
  imageInput: document.querySelector("#room-image-input"),
  imagePickButton: document.querySelector("#pick-room-image-button"),
  imagePreview: document.querySelector("#room-image-preview"),
  imagePreviewList: document.querySelector("#room-image-preview-list"),
  imagePreviewName: document.querySelector("#room-image-preview-name"),
  maxTokensInput: document.querySelector("#room-max-tokens-input"),
  messageInput: document.querySelector("#room-message-input"),
  messages: document.querySelector("#room-messages"),
  modelSelect: document.querySelector("#room-model-select"),
  profileAgent: document.querySelector("#room-profile-agent"),
  profileHandle: document.querySelector("#room-profile-handle"),
  profileName: document.querySelector("#room-profile-name"),
  profileStatus: document.querySelector("#room-profile-status"),
  roomInput: document.querySelector("#room-name-input"),
  runtimeLabel: document.querySelector("#room-runtime-label"),
  saveAgentButton: document.querySelector("#save-room-agent-button"),
  searchClearButton: document.querySelector("#room-search-clear-button"),
  searchInput: document.querySelector("#room-search-input"),
  searchStatus: document.querySelector("#room-search-status"),
  sendButton: document.querySelector("#send-room-button"),
  serverInput: document.querySelector("#server-url-input"),
  statusPill: document.querySelector("#room-status-pill"),
  systemPromptInput: document.querySelector("#room-system-prompt"),
  temperatureInput: document.querySelector("#room-temperature-input"),
  voiceJoinButton: document.querySelector("#voice-join-button"),
  voiceMuteButton: document.querySelector("#voice-mute-button"),
  voiceParticipantList: document.querySelector("#voice-participant-list"),
};

marked.setOptions({
  breaks: true,
  gfm: true,
});

let modelCatalog = [];
let modelCatalogById = {};
let modelCatalogSource = "unknown";
let roomAgents = loadRoomAgents();
let roomSettings = loadRoomSettings();
let roomSocket = null;
let resolvedClientRuntimeBase = "";
let canDeleteMessages = false;
let roomFocusMode = false;
let roomParticipantId = "";
let roomParticipants = [];
let pendingRoomAttachments = [];
let roomSearchQuery = "";
let localMicMuted = true;
let voiceSessionJoined = false;
let localVoiceStream = null;
let peerConnections = new Map();
let participantAudioElements = new Map();
let participantAudioState = new Map();

applyRoomSettingsToForm();
renderEdgeAds();
renderRoomAgents();
applySelectedRoomAgent();
updateRoomMeta();
updateRoomEmptyState();
autoGrow(elements.messageInput);
renderPendingImageAttachment();
renderVoiceParticipants();
applyRoomSearchFilter();
await resolveClientRuntimeBase();
await loadModelsForRuntime();
bindEvents();
applySharedFocusMode(roomFocusMode);

function bindEvents() {
  elements.connectButton.addEventListener("click", () => connectToRoom());
  elements.disconnectButton.addEventListener("click", () => disconnectFromRoom());
  elements.sendButton.addEventListener("click", () => void sendRoomMessage());
  elements.focusButton?.addEventListener("click", () => toggleSharedFocusMode());
  elements.imagePickButton?.addEventListener("click", () => elements.imageInput?.click());
  elements.imageInput?.addEventListener("change", (event) => onImageInputChange(event));
  elements.imageClearButton?.addEventListener("click", clearPendingImageAttachment);
  elements.voiceJoinButton?.addEventListener("click", () => toggleVoiceSession());
  elements.voiceMuteButton?.addEventListener("click", () => toggleLocalMute());
  elements.voiceParticipantList?.addEventListener("input", (event) => onVoiceParticipantControl(event));
  elements.voiceParticipantList?.addEventListener("click", (event) => onVoiceParticipantControl(event));
  elements.saveAgentButton.addEventListener("click", saveRoomAgent);
  elements.deleteAgentButton.addEventListener("click", deleteRoomAgent);
  elements.agentSelect.addEventListener("change", onRoomAgentChange);
  elements.messages.addEventListener("click", onRoomMessageActionClick);
  elements.searchInput?.addEventListener("input", () => onRoomSearchInput());
  elements.searchClearButton?.addEventListener("click", clearRoomSearch);

  elements.messageInput.addEventListener("input", () => autoGrow(elements.messageInput));
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendRoomMessage();
    }
  });

  [
    elements.serverInput,
    elements.roomInput,
    elements.displayNameInput,
    elements.agentNameInput,
  ].forEach((element) => element.addEventListener("change", persistRoomSettingsFromFormSafe));

  elements.modelSelect.addEventListener("change", onRoomModelChange);
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
    aiRuntimeUrl: normalizeServerBase(resolvedClientRuntimeBase || roomSettings.aiRuntimeUrl || DEFAULT_AI_RUNTIME_URL),
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
    aiRuntimeUrl: normalizeServerBase(parsed?.aiRuntimeUrl || DEFAULT_AI_RUNTIME_URL),
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

function onRoomModelChange() {
  applyRoomModelDefaults(elements.modelSelect.value);
  onRoomConfigInputChange();
}

function persistRoomSettings() {
  localStorage.setItem(ROOM_SETTINGS_KEY, JSON.stringify(roomSettings));
}

async function loadModelsForRuntime() {
  persistRoomSettingsFromForm();
  const runtimeBase = normalizeServerBase(resolvedClientRuntimeBase || roomSettings.aiRuntimeUrl || DEFAULT_AI_RUNTIME_URL);
  roomSettings.aiRuntimeUrl = runtimeBase;
  persistRoomSettings();

  try {
    const modelResult = await fetchRuntimeModels(runtimeBase);
    modelCatalog = modelResult.models;
    modelCatalogById = Object.fromEntries(modelCatalog.map((model) => [model.id, model]));
    modelCatalogSource = modelResult.source;
    renderModelOptions(modelCatalog);
    updateStatus(roomSocket ? `Connected to #${roomSettings.roomName}` : "Disconnected");
  } catch (error) {
    modelCatalogSource = "unknown";
    modelCatalog = [{ id: roomSettings.modelId || DEFAULT_MODEL_ID, label: roomSettings.modelId || DEFAULT_MODEL_ID }];
    modelCatalogById = Object.fromEntries(modelCatalog.map((model) => [model.id, model]));
    renderModelOptions(modelCatalog);
    appendLocalSystemMessage(`Could not load models from ${runtimeBase}: ${error instanceof Error ? error.message : String(error)}`);
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

  await loadModelsForRuntime();

  const socketUrl = buildSocketUrl(roomSettings.serverUrl, roomSettings.roomName, roomSettings.displayName);
  updateStatus("Connecting");

  roomSocket = new WebSocket(socketUrl);
  roomSocket.addEventListener("open", () => {
    updateStatus(`Connected to #${roomSettings.roomName}`);
    elements.sendButton.disabled = false;
    if (elements.imagePickButton) {
      elements.imagePickButton.disabled = false;
    }
    elements.disconnectButton.disabled = false;
    elements.connectButton.disabled = true;
    if (elements.voiceJoinButton) {
      elements.voiceJoinButton.disabled = false;
    }
    updateVoiceUiState();
    if (elements.focusButton) {
      elements.focusButton.disabled = false;
    }
    appendLocalSystemMessage(`Connected to ${socketUrl}`);
  });

  roomSocket.addEventListener("message", (event) => handleSocketMessage(event.data));
  roomSocket.addEventListener("close", (event) => {
    closeVoiceSession({ notify: false });
    clearPendingImageAttachment();
    roomParticipantId = "";
    roomParticipants = [];
    renderVoiceParticipants();
    updateStatus("Disconnected");
    elements.sendButton.disabled = true;
    if (elements.imagePickButton) {
      elements.imagePickButton.disabled = true;
    }
    elements.disconnectButton.disabled = true;
    elements.connectButton.disabled = false;
    if (elements.voiceJoinButton) {
      elements.voiceJoinButton.disabled = true;
    }
    if (elements.voiceMuteButton) {
      elements.voiceMuteButton.disabled = true;
    }
    if (elements.focusButton) {
      elements.focusButton.disabled = true;
    }
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

async function sendRoomMessage() {
  const content = elements.messageInput.value.trim();
  const messageType = pendingRoomAttachments.length ? "file" : "text";
  if ((!content && !pendingRoomAttachments.length) || !roomSocket || roomSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  let uploadedAttachments = [];
  if (pendingRoomAttachments.length) {
    try {
      uploadedAttachments = await uploadPendingRoomAttachments();
    } catch (error) {
      appendLocalSystemMessage(`Attachment upload failed: ${error instanceof Error ? error.message : String(error)}`);
      return;
    }
  }

  persistRoomSettingsFromForm();
  roomSocket.send(JSON.stringify({
    type: "chat",
    messageType,
    content,
    attachments: uploadedAttachments,
    agentName: roomSettings.agentName,
    systemPrompt: roomSettings.systemPrompt,
    modelId: roomSettings.modelId,
    temperature: roomSettings.temperature,
    maxTokens: roomSettings.maxTokens,
    providerOptions: getRoomModelProviderOptions(roomSettings.modelId),
  }));

  elements.messageInput.value = "";
  autoGrow(elements.messageInput);
  clearPendingImageAttachment();
}

async function uploadPendingRoomAttachments() {
  const serverBase = normalizeServerBase(roomSettings.serverUrl);
  const roomName = normalizeRoomName(roomSettings.roomName);
  const endpoint = `${serverBase}/api/rooms/${encodeURIComponent(roomName)}/attachments`;
  const formData = new FormData();
  pendingRoomAttachments.forEach((attachment) => {
    formData.append("files", attachment.file, attachment.name);
  });

  const response = await fetch(endpoint, {
    method: "POST",
    mode: "cors",
    body: formData,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = String(payload?.detail || detail);
    } catch {
      detail = await response.text();
    }
    throw new Error(`Upload request failed (${response.status}): ${detail}`);
  }

  const payload = await response.json();
  return Array.isArray(payload?.attachments) ? payload.attachments : [];
}

function handleSocketMessage(rawPayload) {
  const payload = safeParse(rawPayload);
  if (!payload) {
    appendLocalSystemMessage("Received invalid room payload.");
    return;
  }

  if (payload.type === "ai_request") {
    void handleAiRequest(payload);
    return;
  }

  if (payload.type === "history") {
    elements.messages.innerHTML = "";
    canDeleteMessages = Boolean(payload.canDeleteMessages);
    roomParticipantId = String(payload.participantId || "");
    roomParticipants = Array.isArray(payload.participants) ? payload.participants : [];
    applySharedFocusMode(Boolean(payload.focusMode));
    payload.messages.forEach((message) => appendRoomMessage(message));
    applyRoomSearchFilter();
    renderVoiceParticipants();
    syncVoicePeerConnections();
    updateRoomEmptyState();
    scrollMessagesToBottom();
    return;
  }

  if (payload.type === "reaction_update") {
    applyMessageReactions(payload.messageId, payload.reactions);
    return;
  }

  if (payload.type === "message_deleted") {
    removeMessageFromRoom(payload.messageId);
    return;
  }

  if (payload.type === "focus_mode") {
    applySharedFocusMode(Boolean(payload.enabled));
    return;
  }

  if (payload.type === "voice_participants") {
    roomParticipants = Array.isArray(payload.participants) ? payload.participants : [];
    renderVoiceParticipants();
    syncVoicePeerConnections();
    return;
  }

  if (payload.type === "voice_participant_left") {
    const departedId = String(payload.participantId || "");
    if (departedId) {
      roomParticipants = roomParticipants.filter((participant) => String(participant?.participantId || "") !== departedId);
      closePeerConnection(departedId);
      renderVoiceParticipants();
    }
    return;
  }

  if (payload.type === "voice_signal") {
    void handleVoiceSignal(payload);
    return;
  }

  if (payload.type === "error") {
    appendLocalSystemMessage(payload.detail || "Room action failed.");
    return;
  }

  appendRoomMessage(payload);
}

async function handleAiRequest(payload) {
  if (!roomSocket || roomSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  const requestId = String(payload.requestId || "");
  const sourceMessages = Array.isArray(payload.messages) ? payload.messages : [];
  const runtimeBase = normalizeServerBase(resolvedClientRuntimeBase || roomSettings.aiRuntimeUrl || DEFAULT_AI_RUNTIME_URL);
  const modelId = String(payload.modelId || roomSettings.modelId || DEFAULT_MODEL_ID);
  const runtimeModelId = mapModelIdForRuntime(modelId);
  const temperature = Number(payload.temperature ?? roomSettings.temperature ?? 0.7);
  const maxTokens = Number(payload.maxTokens ?? roomSettings.maxTokens ?? 512);
  const providerOptions = payload.providerOptions && typeof payload.providerOptions === "object"
    ? payload.providerOptions
    : getRoomModelProviderOptions(modelId);

  if (!requestId || !sourceMessages.length) {
    roomSocket.send(JSON.stringify({
      type: "ai_result",
      requestId,
      modelId,
      agentName: payload.agentName || roomSettings.agentName,
      error: "Invalid AI request payload.",
    }));
    return;
  }

  try {
    const completion = await fetchLocalCompletion(runtimeBase, {
      model: runtimeModelId,
      messages: sourceMessages,
      stream: false,
      temperature,
      max_tokens: maxTokens,
      provider_options: providerOptions,
    });

    roomSocket.send(JSON.stringify({
      type: "ai_result",
      requestId,
      modelId,
      agentName: payload.agentName || roomSettings.agentName,
      content: completion,
    }));
  } catch (error) {
    roomSocket.send(JSON.stringify({
      type: "ai_result",
      requestId,
      modelId,
      agentName: payload.agentName || roomSettings.agentName,
      error: error instanceof Error ? error.message : String(error),
    }));
  }
}

function appendRoomMessage(message) {
  const article = document.createElement("article");
  article.className = `message room-message ${messageClassFor(message)}`;
  article.dataset.messageId = message.id || crypto.randomUUID();
  article.dataset.searchText = buildRoomSearchText(message);

  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.innerHTML = `
    <span class="message-role">${escapeHtml(getRoomLabel(message))}</span>
    <span class="room-meta-tail">${escapeHtml(formatTimestamp(message.createdAt))}</span>
  `;

  const content = document.createElement("div");
  content.className = "message-content markdown-body";
  const attachments = Array.isArray(message.attachments) ? message.attachments : [];
  const attachmentList = document.createElement("div");
  attachmentList.className = "room-attachment-list";
  let hasAttachmentContent = false;

  attachments.forEach((attachment) => {
    const attachmentType = String(attachment?.type || "").toLowerCase();
    const attachmentName = String(attachment?.name || "attachment");
    if (attachmentType === "image") {
      const imageSource = String(attachment?.dataUrl || attachment?.url || "");
      if (isSafeImageSource(imageSource)) {
        const imageFigure = document.createElement("figure");
        imageFigure.className = "room-image-figure";
        const image = document.createElement("img");
        image.className = "room-message-image";
        image.loading = "lazy";
        image.decoding = "async";
        image.src = imageSource;
        image.alt = attachmentName || "shared image";
        imageFigure.append(image);
        if (attachmentName) {
          const caption = document.createElement("figcaption");
          caption.textContent = attachmentName;
          imageFigure.append(caption);
        }
        attachmentList.append(imageFigure);
        hasAttachmentContent = true;
        return;
      }
    }

    const fileUrl = String(attachment?.url || "");
    if (!isSafeRoomAssetUrl(fileUrl)) {
      return;
    }
    const fileLink = document.createElement("a");
    fileLink.className = "room-attachment-link";
    fileLink.href = fileUrl;
    fileLink.target = "_blank";
    fileLink.rel = "noopener noreferrer";
    fileLink.textContent = attachmentName;
    attachmentList.append(fileLink);
    hasAttachmentContent = true;
  });

  if (hasAttachmentContent) {
    content.append(attachmentList);
  }

  if (message.content) {
    const rendered = marked.parse(message.content || "");
    const textContent = document.createElement("div");
    textContent.innerHTML = DOMPurify.sanitize(rendered);
    enhanceRenderedMessage(textContent, message.content || "");
    content.append(textContent);
  }

  const reactions = document.createElement("div");
  reactions.className = "message-reactions";

  const actions = document.createElement("div");
  actions.className = "message-actions";
  actions.dataset.messageId = article.dataset.messageId;

  if (message.speakerType !== "system") {
    const likeButton = document.createElement("button");
    likeButton.type = "button";
    likeButton.className = "secondary-button message-like-button";
    likeButton.dataset.action = "react";
    likeButton.dataset.emoji = "👍";
    likeButton.textContent = "Like 👍";
    actions.append(likeButton);

    QUICK_REACTION_EMOJIS.filter((emoji) => emoji !== "👍").forEach((emoji) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "icon-button message-action-button";
      button.dataset.action = "react";
      button.dataset.emoji = emoji;
      button.textContent = emoji;
      actions.append(button);
    });

    const customEmojiButton = document.createElement("button");
    customEmojiButton.type = "button";
    customEmojiButton.className = "icon-button message-action-button";
    customEmojiButton.dataset.action = "react_custom";
    customEmojiButton.textContent = "+";
    actions.append(customEmojiButton);

    if (canDeleteMessages) {
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "secondary-button message-delete-button";
      deleteButton.dataset.action = "delete";
      deleteButton.textContent = "Delete";
      actions.append(deleteButton);
    }
  }

  article.append(meta, content, reactions, actions);
  renderMessageReactions(article, message.reactions || {});
  elements.messages.append(article);
  applyRoomSearchFilter();
  updateRoomEmptyState();
  scrollMessagesToBottom();
}

function onRoomMessageActionClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button || !roomSocket || roomSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  const action = button.dataset.action;
  const actionsRow = button.closest(".message-actions");
  const messageId = actionsRow?.dataset.messageId;
  if (!messageId) {
    return;
  }

  if (action === "react") {
    const emoji = button.dataset.emoji;
    if (!emoji) {
      return;
    }
    roomSocket.send(JSON.stringify({
      type: "reaction_toggle",
      messageId,
      emoji,
    }));
    return;
  }

  if (action === "react_custom") {
    const emoji = (window.prompt("Emoji reaction", "") || "").trim();
    if (!emoji) {
      return;
    }
    roomSocket.send(JSON.stringify({
      type: "reaction_toggle",
      messageId,
      emoji,
    }));
    return;
  }

  if (action === "delete" && canDeleteMessages) {
    roomSocket.send(JSON.stringify({
      type: "delete_message",
      messageId,
    }));
  }
}

function applyMessageReactions(messageId, reactions) {
  const article = findMessageArticle(messageId);
  if (!article) {
    return;
  }
  renderMessageReactions(article, reactions || {});
}

function removeMessageFromRoom(messageId) {
  const article = findMessageArticle(messageId);
  if (!article) {
    return;
  }
  article.remove();
  applyRoomSearchFilter();
  updateRoomEmptyState();
}

function findMessageArticle(messageId) {
  if (!messageId) {
    return null;
  }
  return elements.messages.querySelector(`[data-message-id="${CSS.escape(String(messageId))}"]`);
}

function renderMessageReactions(article, reactions) {
  const container = article.querySelector(".message-reactions");
  if (!container) {
    return;
  }

  container.innerHTML = "";
  const entries = Object.entries(reactions || {})
    .map(([emoji, value]) => ({
      emoji,
      count: Number(value?.count ?? 0),
    }))
    .filter((item) => item.emoji && item.count > 0)
    .sort((left, right) => right.count - left.count || left.emoji.localeCompare(right.emoji));

  if (!entries.length) {
    container.style.display = "none";
    return;
  }

  container.style.display = "flex";
  entries.forEach((entry) => {
    const chip = document.createElement("span");
    chip.className = "reaction-chip";
    chip.textContent = `${entry.emoji} ${entry.count}`;
    container.append(chip);
  });
}

async function onImageInputChange(event) {
  const input = event.target;
  const selectedFiles = Array.from(input?.files || []);
  if (!selectedFiles.length) {
    return;
  }

  selectedFiles.forEach((file) => {
    if (pendingRoomAttachments.some((item) => item.name === file.name && item.size === file.size)) {
      return;
    }
    pendingRoomAttachments.push({
      file,
      name: file.name || "shared-file",
      size: Number(file.size || 0),
      mimeType: String(file.type || ""),
    });
  });

  renderPendingImageAttachment();
  input.value = "";
}

function clearPendingImageAttachment() {
  pendingRoomAttachments = [];
  renderPendingImageAttachment();
}

function renderPendingImageAttachment() {
  if (!elements.imagePreview || !elements.imagePreviewList || !elements.imagePreviewName) {
    return;
  }
  elements.imagePreviewList.innerHTML = "";
  if (!pendingRoomAttachments.length) {
    elements.imagePreview.hidden = true;
    elements.imagePreviewName.textContent = "No files selected";
    return;
  }

  elements.imagePreview.hidden = false;
  pendingRoomAttachments.forEach((attachment) => {
    const chip = document.createElement("span");
    chip.className = "room-image-preview-chip";
    chip.textContent = `${attachment.name} (${formatFileSize(attachment.size)})`;
    elements.imagePreviewList.append(chip);
  });
  elements.imagePreviewName.textContent = `${pendingRoomAttachments.length} file(s) attached`;
}

function isSafeImageDataUrl(value) {
  if (!value) {
    return false;
  }
  return /^data:image\/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+$/i.test(value);
}

function isSafeImageSource(value) {
  if (!value) {
    return false;
  }
  if (value.startsWith("data:")) {
    return isSafeImageDataUrl(value);
  }
  return isSafeRoomAssetUrl(value);
}

function isSafeRoomAssetUrl(value) {
  if (!value || value.length > 600 || value.includes("..")) {
    return false;
  }
  if (/^\/assets\/room_uploads\/[A-Za-z0-9._%/-]+$/i.test(value)) {
    return true;
  }
  try {
    const parsed = new URL(value);
    if (!/^https?:$/i.test(parsed.protocol)) {
      return false;
    }
    return /^\/assets\/room_uploads\/[A-Za-z0-9._%/-]+$/i.test(parsed.pathname || "");
  } catch {
    return false;
  }
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const amount = value / (1024 ** exponent);
  const decimals = exponent <= 1 ? 0 : 1;
  return `${amount.toFixed(decimals)} ${units[exponent]}`;
}

async function toggleVoiceSession() {
  if (!voiceSessionJoined) {
    await joinVoiceSession();
    return;
  }
  closeVoiceSession({ notify: true });
}

async function joinVoiceSession() {
  if (!roomSocket || roomSocket.readyState !== WebSocket.OPEN || voiceSessionJoined) {
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    appendLocalSystemMessage("This browser does not support microphone access.");
    return;
  }
  try {
    localVoiceStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    voiceSessionJoined = true;
    setLocalMuteState(localMicMuted, { broadcast: false });
    sendVoiceState();
    updateVoiceUiState();
    renderVoiceParticipants();
    syncVoicePeerConnections();
  } catch (error) {
    appendLocalSystemMessage(`Microphone access failed: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function closeVoiceSession({ notify }) {
  for (const participantId of [...peerConnections.keys()]) {
    closePeerConnection(participantId);
  }
  if (localVoiceStream) {
    localVoiceStream.getTracks().forEach((track) => track.stop());
  }
  localVoiceStream = null;
  voiceSessionJoined = false;
  setLocalMuteState(true, { broadcast: false });
  if (notify) {
    sendVoiceState();
  }
  updateVoiceUiState();
}

function toggleLocalMute() {
  setLocalMuteState(!localMicMuted);
  updateVoiceUiState();
}

function setLocalMuteState(nextMuted, options = {}) {
  localMicMuted = Boolean(nextMuted);
  if (localVoiceStream) {
    for (const track of localVoiceStream.getAudioTracks()) {
      track.enabled = !localMicMuted;
    }
  }
  if (options.broadcast !== false) {
    sendVoiceState();
  }
}

function sendVoiceState() {
  if (!roomSocket || roomSocket.readyState !== WebSocket.OPEN) {
    return;
  }
  roomSocket.send(JSON.stringify({
    type: "voice_state",
    enabled: voiceSessionJoined,
    muted: localMicMuted,
  }));
}

function updateVoiceUiState() {
  if (elements.voiceJoinButton) {
    elements.voiceJoinButton.textContent = voiceSessionJoined ? "Leave Voice" : "Join Voice";
  }
  if (elements.voiceMuteButton) {
    elements.voiceMuteButton.disabled = !voiceSessionJoined;
    elements.voiceMuteButton.textContent = localMicMuted ? "Unmute Mic" : "Mute Mic";
  }
}

function renderVoiceParticipants() {
  if (!elements.voiceParticipantList) {
    return;
  }

  const knownIds = new Set(
    roomParticipants
      .map((participant) => String(participant?.participantId || ""))
      .filter(Boolean),
  );
  for (const participantId of [...participantAudioState.keys()]) {
    if (!knownIds.has(participantId)) {
      participantAudioState.delete(participantId);
    }
  }

  elements.voiceParticipantList.innerHTML = "";
  if (!roomParticipants.length) {
    const empty = document.createElement("p");
    empty.className = "voice-participant-empty";
    empty.textContent = "No active participants.";
    elements.voiceParticipantList.append(empty);
    return;
  }

  roomParticipants.forEach((participant) => {
    const participantId = String(participant?.participantId || "");
    if (!participantId) {
      return;
    }
    const isSelf = participantId === roomParticipantId;
    const voiceEnabled = Boolean(participant?.voiceEnabled);
    const micMuted = Boolean(participant?.micMuted);
    const state = participantAudioState.get(participantId) || { volume: 100, muted: false };
    participantAudioState.set(participantId, state);

    const row = document.createElement("div");
    row.className = "voice-participant-row";
    row.dataset.participantId = participantId;

    const label = document.createElement("div");
    label.className = "voice-participant-label";
    label.textContent = `${participant?.name || "guest"}${isSelf ? " (you)" : ""}`;

    const status = document.createElement("div");
    status.className = "voice-participant-status";
    status.textContent = voiceEnabled ? (micMuted ? "voice: muted" : "voice: live") : "voice: off";

    row.append(label, status);

    if (!isSelf) {
      const controls = document.createElement("div");
      controls.className = "voice-participant-controls";

      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "0";
      slider.max = "200";
      slider.step = "1";
      slider.value = String(state.volume);
      slider.dataset.role = "volume";
      slider.dataset.participantId = participantId;

      const muteButton = document.createElement("button");
      muteButton.type = "button";
      muteButton.className = "icon-button";
      muteButton.dataset.role = "mute-remote";
      muteButton.dataset.participantId = participantId;
      muteButton.textContent = state.muted ? "Unmute User" : "Mute User";

      controls.append(slider, muteButton);
      row.append(controls);
    }

    elements.voiceParticipantList.append(row);
  });
}

function onVoiceParticipantControl(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  if (target.dataset.role === "volume") {
    const participantId = String(target.dataset.participantId || "");
    const value = Number(target.value || 100);
    const state = participantAudioState.get(participantId) || { volume: 100, muted: false };
    state.volume = Number.isFinite(value) ? Math.max(0, Math.min(200, value)) : 100;
    participantAudioState.set(participantId, state);
    applyRemoteAudioState(participantId);
    return;
  }

  if (target.dataset.role === "mute-remote") {
    const participantId = String(target.dataset.participantId || "");
    const state = participantAudioState.get(participantId) || { volume: 100, muted: false };
    state.muted = !state.muted;
    participantAudioState.set(participantId, state);
    applyRemoteAudioState(participantId);
    renderVoiceParticipants();
  }
}

function syncVoicePeerConnections() {
  if (!voiceSessionJoined || !localVoiceStream || !roomParticipantId) {
    for (const participantId of [...peerConnections.keys()]) {
      closePeerConnection(participantId);
    }
    return;
  }

  const activeRemoteIds = new Set(
    roomParticipants
      .filter((participant) => participant?.voiceEnabled)
      .map((participant) => String(participant?.participantId || ""))
      .filter((participantId) => participantId && participantId !== roomParticipantId),
  );

  for (const participantId of [...peerConnections.keys()]) {
    if (!activeRemoteIds.has(participantId)) {
      closePeerConnection(participantId);
    }
  }

  roomParticipants.forEach((participant) => {
    const remoteId = String(participant?.participantId || "");
    if (!remoteId || remoteId === roomParticipantId || !participant?.voiceEnabled) {
      return;
    }
    ensurePeerConnection(remoteId);
    if (roomParticipantId < remoteId) {
      void createAndSendOffer(remoteId);
    }
  });
}

function ensurePeerConnection(remoteParticipantId) {
  if (peerConnections.has(remoteParticipantId)) {
    return peerConnections.get(remoteParticipantId);
  }

  const peerConnection = new RTCPeerConnection(WEBRTC_CONFIG);
  if (localVoiceStream) {
    localVoiceStream.getAudioTracks().forEach((track) => {
      peerConnection.addTrack(track, localVoiceStream);
    });
  }

  peerConnection.addEventListener("icecandidate", (event) => {
    if (!event.candidate) {
      return;
    }
    sendVoiceSignal(remoteParticipantId, {
      type: "ice",
      candidate: event.candidate,
    });
  });

  peerConnection.addEventListener("track", (event) => {
    const [stream] = event.streams;
    if (!stream) {
      return;
    }
    let audioElement = participantAudioElements.get(remoteParticipantId);
    if (!audioElement) {
      audioElement = document.createElement("audio");
      audioElement.autoplay = true;
      audioElement.playsInline = true;
      participantAudioElements.set(remoteParticipantId, audioElement);
    }
    audioElement.srcObject = stream;
    applyRemoteAudioState(remoteParticipantId);
  });

  peerConnections.set(remoteParticipantId, peerConnection);
  return peerConnection;
}

async function createAndSendOffer(remoteParticipantId) {
  const peerConnection = ensurePeerConnection(remoteParticipantId);
  if (!peerConnection) {
    return;
  }
  if (peerConnection.signalingState !== "stable") {
    return;
  }
  const offer = await peerConnection.createOffer();
  await peerConnection.setLocalDescription(offer);
  sendVoiceSignal(remoteParticipantId, {
    type: "offer",
    sdp: peerConnection.localDescription,
  });
}

async function handleVoiceSignal(payload) {
  if (!voiceSessionJoined || !localVoiceStream) {
    return;
  }
  const remoteParticipantId = String(payload.fromParticipantId || "");
  const signal = payload.signal;
  if (!remoteParticipantId || !signal || typeof signal !== "object") {
    return;
  }

  const peerConnection = ensurePeerConnection(remoteParticipantId);
  if (!peerConnection) {
    return;
  }

  try {
    if (signal.type === "offer" && signal.sdp) {
      await peerConnection.setRemoteDescription(new RTCSessionDescription(signal.sdp));
      const answer = await peerConnection.createAnswer();
      await peerConnection.setLocalDescription(answer);
      sendVoiceSignal(remoteParticipantId, {
        type: "answer",
        sdp: peerConnection.localDescription,
      });
      return;
    }

    if (signal.type === "answer" && signal.sdp) {
      await peerConnection.setRemoteDescription(new RTCSessionDescription(signal.sdp));
      return;
    }

    if (signal.type === "ice" && signal.candidate) {
      await peerConnection.addIceCandidate(new RTCIceCandidate(signal.candidate));
    }
  } catch (error) {
    appendLocalSystemMessage(`Voice signal error: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function sendVoiceSignal(targetParticipantId, signal) {
  if (!roomSocket || roomSocket.readyState !== WebSocket.OPEN) {
    return;
  }
  roomSocket.send(JSON.stringify({
    type: "voice_signal",
    targetParticipantId,
    signal,
  }));
}

function closePeerConnection(participantId) {
  const peerConnection = peerConnections.get(participantId);
  if (peerConnection) {
    peerConnection.getSenders().forEach((sender) => {
      try {
        peerConnection.removeTrack(sender);
      } catch {
        return;
      }
    });
    peerConnection.close();
    peerConnections.delete(participantId);
  }

  const audioElement = participantAudioElements.get(participantId);
  if (audioElement) {
    audioElement.pause();
    audioElement.srcObject = null;
    participantAudioElements.delete(participantId);
  }
}

function applyRemoteAudioState(participantId) {
  const audioElement = participantAudioElements.get(participantId);
  if (!audioElement) {
    return;
  }
  const state = participantAudioState.get(participantId) || { volume: 100, muted: false };
  audioElement.muted = Boolean(state.muted);
  audioElement.volume = Math.max(0, Math.min(2, Number(state.volume || 100) / 100));
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

function applySharedFocusMode(enabled) {
  roomFocusMode = Boolean(enabled);
  document.body.classList.toggle("focus-mode", roomFocusMode);
  if (elements.focusButton) {
    elements.focusButton.textContent = roomFocusMode ? "Focus Mode: On" : "Focus Mode: Off";
  }
}

function toggleSharedFocusMode() {
  if (!roomSocket || roomSocket.readyState !== WebSocket.OPEN) {
    return;
  }
  roomSocket.send(JSON.stringify({
    type: "focus_mode",
    enabled: !roomFocusMode,
  }));
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

function onRoomSearchInput() {
  roomSearchQuery = String(elements.searchInput?.value || "");
  applyRoomSearchFilter();
}

function clearRoomSearch() {
  roomSearchQuery = "";
  if (elements.searchInput) {
    elements.searchInput.value = "";
  }
  applyRoomSearchFilter();
}

function applyRoomSearchFilter() {
  const messages = [...elements.messages.querySelectorAll(".room-message")];
  const normalizedQuery = normalizeSearchText(roomSearchQuery);
  if (!normalizedQuery) {
    messages.forEach((message) => message.classList.remove("is-search-hidden"));
    if (elements.searchStatus) {
      elements.searchStatus.textContent = `${messages.length} messages`;
    }
    return;
  }

  const threshold = Math.max(8, normalizedQuery.length * 3);
  let matchCount = 0;
  messages.forEach((message) => {
    const haystack = normalizeSearchText(message.dataset.searchText || "");
    const score = fuzzyScore(normalizedQuery, haystack);
    const isMatch = score >= threshold;
    message.classList.toggle("is-search-hidden", !isMatch);
    if (isMatch) {
      matchCount += 1;
    }
  });

  if (elements.searchStatus) {
    elements.searchStatus.textContent = `${matchCount} match${matchCount === 1 ? "" : "es"}`;
  }
}

function buildRoomSearchText(message) {
  const sender = String(message?.sender || "");
  const content = String(message?.content || "");
  const modelId = String(message?.modelId || "");
  const attachments = Array.isArray(message?.attachments) ? message.attachments : [];
  const attachmentNames = attachments
    .map((item) => String(item?.name || ""))
    .filter(Boolean)
    .join(" ");
  return `${sender} ${content} ${modelId} ${attachmentNames}`.trim();
}

function normalizeSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function fuzzyScore(query, text) {
  if (!query || !text) {
    return -1;
  }

  const directIndex = text.indexOf(query);
  if (directIndex >= 0) {
    return 1000 - Math.min(999, directIndex);
  }

  let score = 0;
  let scanIndex = 0;
  let firstMatchIndex = -1;
  let lastMatchIndex = -2;

  for (const char of query) {
    const nextIndex = text.indexOf(char, scanIndex);
    if (nextIndex < 0) {
      return -1;
    }
    if (firstMatchIndex < 0) {
      firstMatchIndex = nextIndex;
    }
    score += 5;
    if (nextIndex === lastMatchIndex + 1) {
      score += 3;
    }
    score -= Math.min(2, Math.max(0, nextIndex - scanIndex));
    lastMatchIndex = nextIndex;
    scanIndex = nextIndex + 1;
  }

  if (firstMatchIndex >= 0 && lastMatchIndex >= firstMatchIndex) {
    score += Math.max(0, 30 - (lastMatchIndex - firstMatchIndex));
  }
  return score;
}

function scrollMessagesToBottom() {
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

async function resolveClientRuntimeBase() {
  const localApiBase = normalizeServerBase(window.location.origin);
  const fallback = localApiBase;
  try {
    const response = await fetch("/api/client/runtime", { mode: "cors" });
    if (!response.ok) {
      throw new Error(`Runtime config request failed (${response.status})`);
    }
    const payload = await response.json();
    const ollamaBase = normalizeServerBase(payload?.ollamaBaseUrl || DEFAULT_AI_RUNTIME_URL);
    resolvedClientRuntimeBase = localApiBase;
    roomSettings.aiRuntimeUrl = localApiBase;
    persistRoomSettings();
    if (elements.runtimeLabel) {
      elements.runtimeLabel.textContent = `${localApiBase} (OLLAMA_BASE_URL=${ollamaBase})`;
    }
  } catch {
    resolvedClientRuntimeBase = fallback;
    if (elements.runtimeLabel) {
      elements.runtimeLabel.textContent = fallback;
    }
  }
}

async function fetchRuntimeModels(runtimeBase) {
  const localChatResponse = await fetch(`${runtimeBase}/api/models`, { mode: "cors" }).catch(() => null);
  if (localChatResponse?.ok) {
    const payload = await localChatResponse.json();
    if (Array.isArray(payload) && payload.length > 0) {
      return { source: "localchat", models: payload };
    }
  }

  const openAiResponse = await fetch(`${runtimeBase}/v1/models`, { mode: "cors" }).catch(() => null);
  if (openAiResponse?.ok) {
    const payload = await openAiResponse.json();
    const data = Array.isArray(payload?.data) ? payload.data : [];
    const models = data
      .map((item) => ({ id: String(item?.id || "").trim(), label: String(item?.id || "").trim() }))
      .filter((item) => item.id);
    if (models.length > 0) {
      return { source: "openai", models };
    }
  }

  const ollamaResponse = await fetch(`${runtimeBase}/api/tags`, { mode: "cors" }).catch(() => null);
  if (ollamaResponse?.ok) {
    const payload = await ollamaResponse.json();
    const tags = Array.isArray(payload?.models) ? payload.models : [];
    const models = tags
      .map((item) => String(item?.name || item?.model || "").trim())
      .filter(Boolean)
      .map((id) => ({ id, label: id }));
    if (models.length > 0) {
      return { source: "ollama", models };
    }
  }

  throw new Error("No models endpoint responded. Expected /api/models, /v1/models, or /api/tags.");
}

async function fetchLocalCompletion(runtimeBase, body) {
  const response = await fetch(`${runtimeBase}/v1/chat/completions`, {
    method: "POST",
    mode: "cors",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload?.error?.message || payload?.detail || detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(`Completion request failed (${response.status}): ${detail}`);
  }

  const payload = await response.json();
  const content = payload?.choices?.[0]?.message?.content;
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content.map((part) => String(part?.text || "")).join("");
  }
  return String(content || "");
}

function mapModelIdForRuntime(modelId) {
  if (modelCatalogSource === "localchat") {
    return modelId;
  }
  return String(modelId || "").replace(/^(ollama|hf|gemini):/i, "");
}

function getRoomModelProviderOptions(modelId) {
  const options = modelCatalogById[modelId]?.provider_options;
  return options && typeof options === "object" ? options : {};
}

function applyRoomModelDefaults(modelId) {
  const model = modelCatalogById[modelId];
  if (!model) {
    return;
  }
  if (typeof model.default_temperature === "number") {
    roomSettings.temperature = model.default_temperature;
    elements.temperatureInput.value = model.default_temperature;
  }
  if (typeof model.default_max_tokens === "number") {
    roomSettings.maxTokens = model.default_max_tokens;
    elements.maxTokensInput.value = model.default_max_tokens;
  }
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
