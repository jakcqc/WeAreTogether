const DRAFTER_SETTINGS_KEY = "localchat.drafter.settings.v4";
const DRAFTER_LEGACY_SETTINGS_KEY = "localchat.drafter.settings.v2";
const DRAFTER_AGENTS_KEY = "localchat.drafter.agents.v1";
const DRAFTER_SNAPSHOTS_KEY = "localchat.drafter.snapshots.v1";
const DRAFTER_ASSETS_API_PATH = "/api/drafter/assets";
const DRAFTER_COMPILE_API_PATH = "/api/drafter/compile";
const DEFAULT_AGENT_ID = "custom";
const DEFAULT_MODEL_ID = "ollama:qwen2.5:7b";
const SYNC_DEBOUNCE_MS = 180;
const COMPILE_DEBOUNCE_MS = 1100;
const MAX_IMAGE_UPLOAD_BYTES = 3_500_000;
const MAX_TEXT_UPLOAD_BYTES = 250_000;
const DEFAULT_LEFT_RAIL_WIDTH = 380;
const DEFAULT_RIGHT_RAIL_WIDTH = 300;
const MIN_RAIL_WIDTH = 220;
const MAX_RAIL_WIDTH = 760;
const DEFAULT_LAYOUT = {
  left: ["overview", "ai", "proposal", "assets", "compile"],
  right: ["connection", "collaborators"],
  activeLeft: "overview",
  activeRight: "connection",
  leftWidth: DEFAULT_LEFT_RAIL_WIDTH,
  rightWidth: DEFAULT_RIGHT_RAIL_WIDTH,
  centerMode: "split",
};
const DEFAULT_LATEX = String.raw`\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage{amsmath}
\title{Adaptive Neural Fields for Document Editing Agents}
\author{Jordan Lee \and Sam Patel \and Avery Chen}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
We study an interface for collaborative writing where humans and agents revise technical papers together.
The system keeps a live editing surface, a rendered preview, and a planning agent that proposes diffs instead of silent rewrites.
\end{abstract}

\section{Introduction}
Large language models are useful drafting tools, but paper writing requires traceability.
Users need explanations for proposed edits, not only a new paragraph dropped into the manuscript.

\section{Method}
Our environment uses a split view editor for LaTeX and a rendered reading pane.
The assistant receives the current paper as context and can answer questions or propose structured revisions.

\subsection{Agent behavior}
The drafting agent explains why it wants to change the text and then returns a unified diff for review.
This keeps the author in the loop and supports collaborative workflows.

\section{Conclusion}
Reviewable patches are a safer interface for paper editing than opaque rewrites.

\end{document}
`;
const LATEX_COMPLETIONS = [
  ["\\section{}", "\\section{${1:Title}}", "section"],
  ["\\subsection{}", "\\subsection{${1:Heading}}", "section"],
  ["\\subsubsection{}", "\\subsubsection{${1:Heading}}", "section"],
  ["\\begin{abstract}...\\end{abstract}", "\\begin{abstract}\n${1}\n\\end{abstract}", "env"],
  ["\\begin{equation}...\\end{equation}", "\\begin{equation}\n\t${1}\n\\end{equation}", "env"],
  ["\\begin{align}...\\end{align}", "\\begin{align}\n\t${1}\n\\end{align}", "env"],
  ["\\begin{itemize}...\\end{itemize}", "\\begin{itemize}\n\t\\item ${1:item}\n\\end{itemize}", "env"],
  ["\\begin{enumerate}...\\end{enumerate}", "\\begin{enumerate}\n\t\\item ${1:item}\n\\end{enumerate}", "env"],
  ["\\begin{figure}...\\end{figure}", "\\begin{figure}[ht]\n\t\\centering\n\t${1}\n\t\\caption{${2:Caption}}\n\t\\label{fig:${3:key}}\n\\end{figure}", "env"],
  ["\\textbf{}", "\\textbf{${1:text}}", "format"],
  ["\\emph{}", "\\emph{${1:text}}", "format"],
  ["\\frac{}{}", "\\frac{${1:numerator}}{${2:denominator}}", "math"],
  ["\\item", "\\item ${1:text}", "list"],
  ["\\label{}", "\\label{${1:key}}", "ref"],
  ["\\ref{}", "\\ref{${1:key}}", "ref"],
  ["\\cite{}", "\\cite{${1:key}}", "ref"],
  ["\\usepackage[]{}", "\\usepackage[${1:options}]{${2:package}}", "preamble"],
  ["\\title{}", "\\title{${1:Title}}", "preamble"],
  ["\\author{}", "\\author{${1:Author}}", "preamble"],
  ["\\date{}", "\\date{${1:\\today}}", "preamble"],
];
const elements = {
  agentPanel: document.querySelector("#drafter-agent-panel"),
  agentPanelToggle: document.querySelector("#drafter-agent-panel-toggle"),
  agentDiff: document.querySelector("#agent-diff code"),
  agentExplanation: document.querySelector("#agent-explanation"),
  agentModeButton: document.querySelector("#agent-mode-button"),
  agentNameInput: document.querySelector("#drafter-agent-name-input"),
  agentSelect: document.querySelector("#drafter-agent-select"),
  assetsTab: document.querySelector("#drafter-assets-tab"),
  assetDetail: document.querySelector("#drafter-asset-detail"),
  assetList: document.querySelector("#drafter-asset-list"),
  assetsPanel: document.querySelector("#drafter-assets-panel"),
  assetRefreshButton: document.querySelector("#drafter-asset-refresh-button"),
  assetUploadButton: document.querySelector("#drafter-asset-upload-button"),
  assetUploadInput: document.querySelector("#drafter-asset-upload-input"),
  applyDiffButton: document.querySelector("#apply-diff-button"),
  askModeButton: document.querySelector("#ask-mode-button"),
  collaboratorCount: document.querySelector("#collaborator-count"),
  collaboratorList: document.querySelector("#collaborator-list"),
  collabChatMessages: document.querySelector("#drafter-collab-chat-messages"),
  collabChatInput: document.querySelector("#drafter-collab-chat-input"),
  collabChatSend: document.querySelector("#drafter-collab-chat-send"),
  compileLog: document.querySelector("#compile-log"),
  compileNowButton: document.querySelector("#compile-now-button"),
  compileStatusLabel: document.querySelector("#compile-status-label"),
  connectButton: document.querySelector("#connect-drafter-button"),
  connectionLabel: document.querySelector("#drafter-connection-label"),
  cursorPosition: document.querySelector("#cursor-position"),
  deleteAgentButton: document.querySelector("#delete-drafter-agent-button"),
  disconnectButton: document.querySelector("#disconnect-drafter-button"),
  downloadDraftButton: document.querySelector("#download-draft-button"),
  editorGrid: document.querySelector("#drafter-editor-grid"),
  displayNameInput: document.querySelector("#drafter-display-name-input"),
  draftName: document.querySelector("#draft-name"),
  draftRoomLabel: document.querySelector("#draft-room-label"),
  exportPdfButton: document.querySelector("#export-pdf-button"),
  latexEditorHost: document.querySelector("#latex-editor"),
  latexPane: document.querySelector("#drafter-latex-pane"),
  latexToggleButton: document.querySelector("#drafter-latex-toggle"),
  lastDiffStatus: document.querySelector("#last-diff-status"),
  layout: document.querySelector(".drafter-layout"),
  leftNav: document.querySelector("#drafter-left-nav"),
  leftResizer: document.querySelector("#drafter-left-resizer"),
  leftStack: document.querySelector("#drafter-left-stack"),
  modelSelect: document.querySelector("#drafter-model-select"),
  openCompiledPdfButton: document.querySelector("#open-compiled-pdf-button"),
  previewPane: document.querySelector("#preview-pane"),
  previewPaneShell: document.querySelector("#drafter-preview-pane-shell"),
  previewToggleButton: document.querySelector("#drafter-preview-toggle"),
  proposalMeta: document.querySelector("#proposal-meta"),
  requestInput: document.querySelector("#drafter-request-input"),
  response: document.querySelector("#drafter-response"),
  rightNav: document.querySelector("#drafter-right-nav"),
  rightResizer: document.querySelector("#drafter-right-resizer"),
  rightStack: document.querySelector("#drafter-right-stack"),
  roomInput: document.querySelector("#drafter-room-name-input"),
  runButton: document.querySelector("#run-drafter-ai-button"),
  saveAgentButton: document.querySelector("#save-drafter-agent-button"),
  saveDraftButton: document.querySelector("#save-draft-button"),
  serverInput: document.querySelector("#drafter-server-url-input"),
  statusPill: document.querySelector("#drafter-status-pill"),
  systemPrompt: document.querySelector("#drafter-system-prompt"),
  temperatureInput: document.querySelector("#drafter-temperature-input"),
  maxTokensInput: document.querySelector("#drafter-max-tokens-input"),
  panelButtons: Array.from(document.querySelectorAll("[data-panel-key].drafter-nav-button")),
  panelSections: Array.from(document.querySelectorAll(".drafter-nav-panel[data-panel-key]")),
  wordCount: document.querySelector("#word-count"),
};
let latexEditor = initializeLatexEditor();
let modelCatalog = [];
let modelCatalogById = {};
let drafterAgents = loadAgents();
let drafterSettings = loadSettings();
let snapshots = loadSnapshots();
let drafterAssets = [];
let selectedAssetName = drafterSettings.selectedAssetName || "";
let currentMode = drafterSettings.mode || "ask";
let pendingDiffTarget = "";
let draftSocket = null;
let syncTimer = null;
let compileTimer = null;
let compileInFlight = false;
let compileQueued = false;
let latestCompiledPdfUrl = "";
let draftChatMessages = [];
let remoteApplyInProgress = false;
let suppressEditorEvents = false;
let loadedModelServerBase = "";
let currentLayout = normalizeLayoutState(drafterSettings.layout);
let activeResize = null;
let draggingPanelKey = "";

applySettingsToForm();
renderAgents();
await loadModelsForServer(drafterSettings.serverUrl);
await loadAssets();
applySelectedAgent();
elements.draftName.textContent = "main.tex";
elements.draftRoomLabel.textContent = drafterSettings.roomName;
updateEditorStats();
renderPreview();
renderCompileLog();
renderCollaborators([]);
renderDraftChat([]);
bindEvents();
updateModeUi();
updateAgentPanelUi();
applyLayoutState();
setCenterPaneMode(currentLayout.centerMode);
await connectToDraft();
scheduleCompile("initial");

function bindEvents() {
  bindLatexEditorEvents();
  elements.agentPanelToggle.addEventListener("click", toggleAgentPanel);
  elements.agentSelect.addEventListener("change", onAgentChange);
  bindPanelDragAndDrop();
  bindRailResizers();
  elements.panelButtons.forEach((button) => {
    button.addEventListener("click", () => activatePanel(button.dataset.rail || "left", button.dataset.panelKey || ""));
  });
  elements.saveAgentButton.addEventListener("click", saveAgent);
  elements.deleteAgentButton.addEventListener("click", deleteAgent);
  elements.assetUploadButton.addEventListener("click", () => void openAssetPicker());
  elements.assetUploadInput.addEventListener("change", () => void handleAssetUpload());
  elements.assetRefreshButton.addEventListener("click", () => void loadAssets());
  elements.modelSelect.addEventListener("change", onModelChange);
  elements.temperatureInput.addEventListener("change", onConfigChange);
  elements.maxTokensInput.addEventListener("change", onConfigChange);
  elements.systemPrompt.addEventListener("change", onConfigChange);
  elements.requestInput.addEventListener("input", () => {
    drafterSettings.request = elements.requestInput.value;
    persistSettings();
  });
  [elements.serverInput, elements.displayNameInput, elements.roomInput].forEach((element) => {
    element.addEventListener("change", () => void onSessionFieldChange());
  });
  elements.connectButton.addEventListener("click", () => void connectToDraft({ forceReconnect: true }));
  elements.disconnectButton.addEventListener("click", disconnectFromDraft);
  elements.collabChatSend.addEventListener("click", sendDraftChatMessage);
  elements.collabChatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendDraftChatMessage();
    }
  });
  elements.askModeButton.addEventListener("click", () => setMode("ask"));
  elements.agentModeButton.addEventListener("click", () => setMode("agent"));
  elements.runButton.addEventListener("click", () => void runAi());
  elements.saveDraftButton.addEventListener("click", saveSnapshot);
  elements.downloadDraftButton.addEventListener("click", downloadDraftFile);
  elements.exportPdfButton.addEventListener("click", () => void exportPreviewPdf());
  elements.compileNowButton.addEventListener("click", () => void compileLatex({ manual: true, reason: "manual" }));
  elements.openCompiledPdfButton.addEventListener("click", openCompiledPdf);
  elements.applyDiffButton.addEventListener("click", applyPendingDiff);
  elements.latexToggleButton.addEventListener("click", () => toggleCenterPane("latex"));
  elements.previewToggleButton.addEventListener("click", () => toggleCenterPane("preview"));
  document.addEventListener("visibilitychange", () => sendPresence(document.hidden ? "idle" : "viewing"));
  window.addEventListener("beforeunload", () => flushDraftSync("viewing"));
  window.addEventListener("resize", () => {
    if (window.innerWidth <= 980) {
      return;
    }
    latexEditor?.resize();
  });
}

function bindLatexEditorEvents() {
  if (!latexEditor) {
    return;
  }
  latexEditor.session.on("change", (delta) => {
    if (suppressEditorEvents) {
      return;
    }
    drafterSettings.paper = getEditorText();
    persistSettings();
    if (!latestCompiledPdfUrl) {
      renderPreview();
    }
    updateEditorStats();
    scheduleCompile("edit");
    const insertedText = delta.action === "insert" ? delta.lines.join("\n") : "";
    if (insertedText.includes("\\")) {
      window.setTimeout(() => latexEditor?.execCommand("startAutocomplete"), 0);
    }
    if (!remoteApplyInProgress) {
      scheduleDraftSync("editing");
    }
  });
  latexEditor.selection.on("changeCursor", updateCursorPosition);
  latexEditor.selection.on("changeSelection", updateCursorPosition);
  latexEditor.on("focus", () => sendPresence("editing"));
  latexEditor.on("blur", () => sendPresence("viewing"));
}

async function onSessionFieldChange() {
  try {
    persistSettingsFromForm({ validateServer: true });
  } catch (error) {
    updateConnectionState(`Invalid server URL: ${error instanceof Error ? error.message : String(error)}`);
    return;
  }
  elements.draftRoomLabel.textContent = drafterSettings.roomName;
  latestCompiledPdfUrl = "";
  updateCompileButtons();
  renderPreview();
  await loadModelsForServer(drafterSettings.serverUrl, { force: true });
  await loadAssets();
  await connectToDraft({ forceReconnect: true });
}

async function loadModelsForServer(serverBase = drafterSettings.serverUrl, options = {}) {
  const force = Boolean(options.force);
  const normalizedServerBase = normalizeServerBase(serverBase);
  if (!force && normalizedServerBase === loadedModelServerBase && modelCatalog.length) {
    return;
  }
  try {
    const response = await fetch(buildApiUrl(normalizedServerBase, "/api/models"));
    if (!response.ok) {
      throw new Error(`Model list request failed (${response.status})`);
    }
    modelCatalog = await response.json();
    modelCatalogById = Object.fromEntries(modelCatalog.map((model) => [model.id, model]));
  } catch {
    modelCatalog = [{ id: DEFAULT_MODEL_ID, label: DEFAULT_MODEL_ID }];
    modelCatalogById = Object.fromEntries(modelCatalog.map((model) => [model.id, model]));
  }
  loadedModelServerBase = normalizedServerBase;
  elements.modelSelect.innerHTML = "";
  modelCatalog.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label || model.id;
    elements.modelSelect.append(option);
  });
  const nextValue = modelCatalog.some((model) => model.id === drafterSettings.modelId) ? drafterSettings.modelId : modelCatalog[0]?.id || DEFAULT_MODEL_ID;
  drafterSettings.modelId = nextValue;
  elements.modelSelect.value = nextValue;
  persistSettings();
}

function onModelChange() {
  applyModelDefaults(elements.modelSelect.value);
  onConfigChange();
}

function loadSettings() {
  const parsed = safeParse(localStorage.getItem(DRAFTER_SETTINGS_KEY))
    ?? safeParse(localStorage.getItem(DRAFTER_LEGACY_SETTINGS_KEY))
    ?? safeParse(localStorage.getItem("localchat.drafter.settings.v1"));
  return {
    agentId: parsed?.agentId ?? DEFAULT_AGENT_ID,
    agentName: normalizeAgentName(parsed?.agentName || "Paper Editor"),
    agentPanelCollapsed: Boolean(parsed?.agentPanelCollapsed),
    displayName: normalizeHandle(parsed?.displayName || "guest"),
    layout: normalizeLayoutState(parsed?.layout),
    mode: parsed?.mode === "agent" ? "agent" : "ask",
    modelId: parsed?.modelId || DEFAULT_MODEL_ID,
    request: typeof parsed?.request === "string" ? parsed.request : "",
    paper: typeof parsed?.paper === "string" && parsed.paper.trim() ? parsed.paper : DEFAULT_LATEX,
    roomName: normalizeRoomName(parsed?.roomName || "paper-main", "paper-main"),
    selectedAssetName: typeof parsed?.selectedAssetName === "string" ? parsed.selectedAssetName : "",
    serverUrl: safeNormalizeServerBase(parsed?.serverUrl, window.location.origin),
    systemPrompt: typeof parsed?.systemPrompt === "string" ? parsed.systemPrompt : "",
    temperature: Number(parsed?.temperature ?? 0.3),
    maxTokens: Number(parsed?.maxTokens ?? 1400),
  };
}

function persistSettings() {
  drafterSettings = {
    ...drafterSettings,
    layout: normalizeLayoutState(currentLayout),
    mode: currentMode,
    selectedAssetName,
  };
  localStorage.setItem(DRAFTER_SETTINGS_KEY, JSON.stringify(drafterSettings));
}

function loadAgents() {
  const parsed = safeParse(localStorage.getItem(DRAFTER_AGENTS_KEY));
  if (!Array.isArray(parsed)) {
    return [];
  }
  return parsed.map((agent) => ({
    id: typeof agent.id === "string" ? agent.id : crypto.randomUUID(),
    name: normalizeAgentName(agent.name || "Paper Editor"),
    modelId: typeof agent.modelId === "string" ? agent.modelId : DEFAULT_MODEL_ID,
    temperature: Number(agent.temperature ?? 0.3),
    maxTokens: Number(agent.maxTokens ?? 1400),
    systemPrompt: typeof agent.systemPrompt === "string" ? agent.systemPrompt : "",
  }));
}

function persistAgents() {
  localStorage.setItem(DRAFTER_AGENTS_KEY, JSON.stringify(drafterAgents));
}

function renderAgents() {
  const currentValue = drafterSettings.agentId || DEFAULT_AGENT_ID;
  elements.agentSelect.innerHTML = "";
  const customOption = document.createElement("option");
  customOption.value = DEFAULT_AGENT_ID;
  customOption.textContent = "Custom Setup";
  elements.agentSelect.append(customOption);
  drafterAgents.forEach((agent) => {
    const option = document.createElement("option");
    option.value = agent.id;
    option.textContent = agent.name;
    elements.agentSelect.append(option);
  });
  elements.agentSelect.value = drafterAgents.some((agent) => agent.id === currentValue) ? currentValue : DEFAULT_AGENT_ID;
  drafterSettings.agentId = elements.agentSelect.value;
  persistSettings();
  const selectedAgent = getSelectedAgent();
  elements.agentNameInput.value = selectedAgent?.name ?? drafterSettings.agentName;
  elements.deleteAgentButton.disabled = !selectedAgent;
  elements.saveAgentButton.textContent = selectedAgent ? "Update Agent" : "Save Agent";
}

function applySettingsToForm() {
  elements.agentNameInput.value = drafterSettings.agentName;
  elements.displayNameInput.value = drafterSettings.displayName;
  elements.requestInput.value = drafterSettings.request;
  elements.roomInput.value = drafterSettings.roomName;
  elements.serverInput.value = drafterSettings.serverUrl;
  elements.systemPrompt.value = drafterSettings.systemPrompt;
  elements.temperatureInput.value = drafterSettings.temperature;
  elements.maxTokensInput.value = drafterSettings.maxTokens;
  setEditorText(drafterSettings.paper);
}

function onAgentChange() {
  drafterSettings.agentId = elements.agentSelect.value || DEFAULT_AGENT_ID;
  persistSettings();
  applySelectedAgent();
}

function applySelectedAgent() {
  const selectedAgent = getSelectedAgent();
  if (selectedAgent) {
    drafterSettings.agentName = selectedAgent.name;
    drafterSettings.modelId = selectedAgent.modelId || drafterSettings.modelId;
    drafterSettings.temperature = selectedAgent.temperature;
    drafterSettings.maxTokens = selectedAgent.maxTokens;
    drafterSettings.systemPrompt = selectedAgent.systemPrompt;
    persistSettings();
  }
  elements.agentNameInput.value = selectedAgent?.name ?? drafterSettings.agentName;
  elements.modelSelect.value = drafterSettings.modelId;
  elements.temperatureInput.value = drafterSettings.temperature;
  elements.maxTokensInput.value = drafterSettings.maxTokens;
  elements.systemPrompt.value = drafterSettings.systemPrompt;
  elements.deleteAgentButton.disabled = !selectedAgent;
  elements.saveAgentButton.textContent = selectedAgent ? "Update Agent" : "Save Agent";
}

function saveAgent() {
  persistSettingsFromForm();
  const name = normalizeAgentName(elements.agentNameInput.value);
  if (!name) {
    elements.agentNameInput.focus();
    return;
  }
  const selectedAgent = getSelectedAgent();
  if (selectedAgent) {
    selectedAgent.name = name;
    selectedAgent.modelId = drafterSettings.modelId;
    selectedAgent.temperature = drafterSettings.temperature;
    selectedAgent.maxTokens = drafterSettings.maxTokens;
    selectedAgent.systemPrompt = drafterSettings.systemPrompt;
  } else {
    const agent = {
      id: crypto.randomUUID(),
      name,
      modelId: drafterSettings.modelId,
      temperature: drafterSettings.temperature,
      maxTokens: drafterSettings.maxTokens,
      systemPrompt: drafterSettings.systemPrompt,
    };
    drafterAgents.unshift(agent);
    drafterSettings.agentId = agent.id;
  }
  drafterSettings.agentName = name;
  persistAgents();
  persistSettings();
  renderAgents();
}

function deleteAgent() {
  const selectedAgent = getSelectedAgent();
  if (!selectedAgent) {
    return;
  }
  drafterAgents = drafterAgents.filter((agent) => agent.id !== selectedAgent.id);
  drafterSettings.agentId = DEFAULT_AGENT_ID;
  persistAgents();
  persistSettings();
  renderAgents();
  applySelectedAgent();
}

function onConfigChange() {
  persistSettingsFromForm();
  const selectedAgent = getSelectedAgent();
  if (!selectedAgent) {
    return;
  }
  selectedAgent.modelId = drafterSettings.modelId;
  selectedAgent.temperature = drafterSettings.temperature;
  selectedAgent.maxTokens = drafterSettings.maxTokens;
  selectedAgent.systemPrompt = drafterSettings.systemPrompt;
  persistAgents();
}

function persistSettingsFromForm(options = {}) {
  const serverUrl = options.validateServer
    ? normalizeServerBase(elements.serverInput.value)
    : safeNormalizeServerBase(elements.serverInput.value, drafterSettings.serverUrl || window.location.origin);
  drafterSettings = {
    ...drafterSettings,
    agentId: elements.agentSelect.value || DEFAULT_AGENT_ID,
    agentName: normalizeAgentName(elements.agentNameInput.value),
    displayName: normalizeHandle(elements.displayNameInput.value),
    layout: normalizeLayoutState(currentLayout),
    maxTokens: Number(elements.maxTokensInput.value || 1400),
    mode: currentMode,
    modelId: elements.modelSelect.value || DEFAULT_MODEL_ID,
    paper: getEditorText(),
    request: elements.requestInput.value,
    roomName: normalizeRoomName(elements.roomInput.value, "paper-main"),
    selectedAssetName,
    serverUrl,
    systemPrompt: elements.systemPrompt.value.trim(),
    temperature: Number(elements.temperatureInput.value || 0.3),
  };
  persistSettings();
}

function getSelectedAgent() {
  return drafterAgents.find((agent) => agent.id === elements.agentSelect.value) ?? null;
}

function setMode(mode) {
  currentMode = mode === "agent" ? "agent" : "ask";
  drafterSettings.mode = currentMode;
  persistSettings();
  updateModeUi();
}

function updateModeUi() {
  const isAgent = currentMode === "agent";
  elements.askModeButton.classList.toggle("active", !isAgent);
  elements.agentModeButton.classList.toggle("active", isAgent);
  elements.runButton.textContent = isAgent ? "Run Agent" : "Ask About Paper";
}

function toggleAgentPanel() {
  drafterSettings.agentPanelCollapsed = !drafterSettings.agentPanelCollapsed;
  persistSettings();
  updateAgentPanelUi();
}

function updateAgentPanelUi() {
  const collapsed = Boolean(drafterSettings.agentPanelCollapsed);
  elements.agentPanel.classList.toggle("is-collapsed", collapsed);
  elements.agentPanelToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  elements.agentPanelToggle.textContent = collapsed ? "Expand Setup" : "Collapse Setup";
}

function normalizeLayoutState(rawLayout) {
  const left = sanitizePanelList(rawLayout?.left, DEFAULT_LAYOUT.left);
  const right = sanitizePanelList(rawLayout?.right, DEFAULT_LAYOUT.right, left);
  const activeLeft = left.includes(rawLayout?.activeLeft) ? rawLayout.activeLeft : left[0] || "";
  const activeRight = right.includes(rawLayout?.activeRight) ? rawLayout.activeRight : right[0] || "";
  return {
    left,
    right,
    activeLeft,
    activeRight,
    leftWidth: clampRailWidth(rawLayout?.leftWidth ?? DEFAULT_LAYOUT.leftWidth),
    rightWidth: clampRailWidth(rawLayout?.rightWidth ?? DEFAULT_LAYOUT.rightWidth),
    centerMode: ["split", "latex-only", "preview-only"].includes(rawLayout?.centerMode) ? rawLayout.centerMode : DEFAULT_LAYOUT.centerMode,
  };
}

function sanitizePanelList(candidate, fallback, excluded = []) {
  const allowed = ["overview", "ai", "proposal", "assets", "compile", "connection", "collaborators"];
  const picked = Array.isArray(candidate)
    ? candidate.filter((item) => allowed.includes(item) && !excluded.includes(item))
    : [];
  fallback.forEach((item) => {
    if (!picked.includes(item) && !excluded.includes(item)) {
      picked.push(item);
    }
  });
  return picked;
}

function applyLayoutState() {
  syncPanelDomToLayout();
  updateRailStyles();
  activatePanel("left", currentLayout.activeLeft, { persist: false });
  activatePanel("right", currentLayout.activeRight, { persist: false });
}

function syncPanelDomToLayout() {
  syncRailDom("left", currentLayout.left, elements.leftNav, elements.leftStack);
  syncRailDom("right", currentLayout.right, elements.rightNav, elements.rightStack);
}

function syncRailDom(rail, orderedKeys, navContainer, stackContainer) {
  orderedKeys.forEach((panelKey) => {
    const button = getPanelButton(panelKey);
    const panel = getPanelSection(panelKey);
    if (!button || !panel) {
      return;
    }
    button.dataset.rail = rail;
    panel.dataset.rail = rail;
    navContainer.append(button);
    stackContainer.append(panel);
  });
}

function activatePanel(rail, panelKey, options = {}) {
  const persist = options.persist !== false;
  const keyList = rail === "right" ? currentLayout.right : currentLayout.left;
  const fallback = keyList[0] || "";
  const nextKey = keyList.includes(panelKey) ? panelKey : fallback;
  if (!nextKey) {
    return;
  }
  if (rail === "right") {
    currentLayout.activeRight = nextKey;
  } else {
    currentLayout.activeLeft = nextKey;
  }
  elements.panelButtons.forEach((button) => {
    if (button.dataset.rail !== rail) {
      return;
    }
    const active = button.dataset.panelKey === nextKey;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  elements.panelSections.forEach((panel) => {
    if (panel.dataset.rail !== rail) {
      return;
    }
    const active = panel.dataset.panelKey === nextKey;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
  if (persist) {
    persistLayoutState();
  }
}

function getPanelButton(panelKey) {
  return elements.panelButtons.find((button) => button.dataset.panelKey === panelKey) || null;
}

function getPanelSection(panelKey) {
  return elements.panelSections.find((panel) => panel.dataset.panelKey === panelKey) || null;
}

function bindPanelDragAndDrop() {
  elements.panelButtons.forEach((button) => {
    button.addEventListener("dragstart", (event) => {
      draggingPanelKey = button.dataset.panelKey || "";
      button.classList.add("is-dragging");
      event.dataTransfer?.setData("text/plain", draggingPanelKey);
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    });
    button.addEventListener("dragend", () => {
      draggingPanelKey = "";
      button.classList.remove("is-dragging");
      clearDragTargets();
    });
  });
  [elements.leftNav, elements.rightNav].forEach((container) => {
    container.addEventListener("dragover", (event) => {
      event.preventDefault();
      const targetRail = container === elements.rightNav ? "right" : "left";
      container.classList.add("is-drop-target");
      const insertBefore = getDragInsertBefore(container, event.clientY);
      movePanelToRail(draggingPanelKey, targetRail, insertBefore?.dataset.panelKey || null, { persist: false });
    });
    container.addEventListener("drop", (event) => {
      event.preventDefault();
      if (draggingPanelKey) {
        persistLayoutState();
        activatePanel(container === elements.rightNav ? "right" : "left", draggingPanelKey, { persist: false });
      }
      clearDragTargets();
    });
    container.addEventListener("dragleave", (event) => {
      if (!container.contains(event.relatedTarget)) {
        container.classList.remove("is-drop-target");
      }
    });
  });
}

function clearDragTargets() {
  elements.leftNav.classList.remove("is-drop-target");
  elements.rightNav.classList.remove("is-drop-target");
}

function getDragInsertBefore(container, clientY) {
  const draggableButtons = [...container.querySelectorAll(".drafter-nav-button:not(.is-dragging)")];
  return draggableButtons.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = clientY - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) {
      return { offset, element: child };
    }
    return closest;
  }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
}

function movePanelToRail(panelKey, targetRail, beforePanelKey = null, options = {}) {
  if (!panelKey) {
    return;
  }
  const sourceRail = currentLayout.left.includes(panelKey) ? "left" : currentLayout.right.includes(panelKey) ? "right" : "";
  if (!sourceRail) {
    return;
  }
  const sourceList = sourceRail === "right" ? currentLayout.right : currentLayout.left;
  const targetList = targetRail === "right" ? currentLayout.right : currentLayout.left;
  const sourceIndex = sourceList.indexOf(panelKey);
  if (sourceIndex >= 0) {
    sourceList.splice(sourceIndex, 1);
  }
  let targetIndex = beforePanelKey ? targetList.indexOf(beforePanelKey) : -1;
  if (targetIndex < 0) {
    targetIndex = targetList.length;
  }
  targetList.splice(targetIndex, 0, panelKey);
  if (!sourceList.length) {
    const fallback = (sourceRail === "left" ? currentLayout.right : currentLayout.left)[0] || panelKey;
    if (sourceRail === "left") {
      currentLayout.activeLeft = fallback;
    } else {
      currentLayout.activeRight = fallback;
    }
  }
  if (targetRail === "left") {
    currentLayout.activeLeft = panelKey;
  } else {
    currentLayout.activeRight = panelKey;
  }
  syncPanelDomToLayout();
  activatePanel("left", currentLayout.activeLeft, { persist: false });
  activatePanel("right", currentLayout.activeRight, { persist: false });
  if (options.persist !== false) {
    persistLayoutState();
  }
}

function bindRailResizers() {
  bindRailResizer(elements.leftResizer, "left");
  bindRailResizer(elements.rightResizer, "right");
}

function bindRailResizer(handle, side) {
  handle.addEventListener("pointerdown", (event) => {
    if (window.innerWidth <= 980) {
      return;
    }
    activeResize = { side, startX: event.clientX, startWidth: side === "left" ? currentLayout.leftWidth : currentLayout.rightWidth };
    handle.classList.add("is-active");
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener("pointermove", (event) => {
    if (!activeResize || activeResize.side !== side) {
      return;
    }
    const delta = event.clientX - activeResize.startX;
    const nextWidth = side === "left" ? activeResize.startWidth + delta : activeResize.startWidth - delta;
    if (side === "left") {
      currentLayout.leftWidth = clampRailWidth(nextWidth);
    } else {
      currentLayout.rightWidth = clampRailWidth(nextWidth);
    }
    updateRailStyles();
    latexEditor?.resize();
  });
  const stopResize = () => {
    if (!activeResize || activeResize.side !== side) {
      return;
    }
    activeResize = null;
    handle.classList.remove("is-active");
    persistLayoutState();
  };
  handle.addEventListener("pointerup", stopResize);
  handle.addEventListener("pointercancel", stopResize);
}

function clampRailWidth(value) {
  return Math.max(MIN_RAIL_WIDTH, Math.min(MAX_RAIL_WIDTH, Number(value || DEFAULT_LEFT_RAIL_WIDTH)));
}

function updateRailStyles() {
  elements.layout?.style.setProperty("--drafter-left-width", `${currentLayout.leftWidth}px`);
  elements.layout?.style.setProperty("--drafter-right-width", `${currentLayout.rightWidth}px`);
}

function persistLayoutState() {
  drafterSettings.layout = { ...currentLayout };
  persistSettings();
}

function setCenterPaneMode(mode) {
  currentLayout.centerMode = ["latex-only", "preview-only"].includes(mode) ? mode : "split";
  elements.editorGrid.dataset.centerMode = currentLayout.centerMode;
  elements.latexToggleButton.textContent = currentLayout.centerMode === "latex-only" ? "Restore Split" : "Expand";
  elements.previewToggleButton.textContent = currentLayout.centerMode === "preview-only" ? "Restore Split" : "Expand";
  latexEditor?.resize();
  persistLayoutState();
}

function toggleCenterPane(pane) {
  if (pane === "latex") {
    setCenterPaneMode(currentLayout.centerMode === "latex-only" ? "split" : "latex-only");
    return;
  }
  setCenterPaneMode(currentLayout.centerMode === "preview-only" ? "split" : "preview-only");
}

async function loadAssets() {
  try {
    const response = await fetch(buildApiUrl(drafterSettings.serverUrl, DRAFTER_ASSETS_API_PATH));
    const payload = await response.json().catch(() => []);
    if (!response.ok) {
      throw new Error(payload.detail || "Asset request failed");
    }
    drafterAssets = Array.isArray(payload) ? payload : [];
    if (!drafterAssets.some((asset) => asset.name === selectedAssetName)) {
      selectedAssetName = drafterAssets[0]?.name || "";
      persistSettings();
    }
    renderAssetShelf();
    if (!latestCompiledPdfUrl) {
      renderPreview();
    }
    scheduleCompile("assets");
  } catch (error) {
    drafterAssets = [];
    selectedAssetName = "";
    renderAssetShelf(`Assets unavailable: ${error instanceof Error ? error.message : String(error)}`);
    if (!latestCompiledPdfUrl) {
      renderPreview();
    }
    scheduleCompile("assets");
  }
}

async function handleAssetUpload() {
  const files = Array.from(elements.assetUploadInput.files || []);
  if (!files.length) {
    return;
  }
  try {
    persistSettingsFromForm({ validateServer: true });
  } catch (error) {
    renderAssetShelf(`Upload blocked: ${error instanceof Error ? error.message : String(error)}`);
    return;
  }
  try {
    let lastUploadedName = "";
    for (const file of files) {
      const asset = await uploadSingleAsset(file);
      lastUploadedName = asset?.name || lastUploadedName;
    }
    selectedAssetName = lastUploadedName || selectedAssetName;
    await loadAssets();
  } catch (error) {
    renderAssetShelf(`Upload failed: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    elements.assetUploadInput.value = "";
  }
}

async function openAssetPicker() {
  elements.assetUploadInput.value = "";
  if (typeof elements.assetUploadInput.showPicker === "function") {
    try {
      await elements.assetUploadInput.showPicker();
      return;
    } catch {
      // Fall back to click() for browsers that expose showPicker but reject it here.
    }
  }
  elements.assetUploadInput.click();
}

async function uploadSingleAsset(file) {
  const extension = getFileExtension(file.name);
  let content = "";
  if (isImageAsset(file.name)) {
    if (file.size > MAX_IMAGE_UPLOAD_BYTES) {
      throw new Error(`${file.name} is too large.`);
    }
    content = await readFileAsDataUrl(file);
  } else if (extension === ".bib" || extension === ".tex") {
    if (file.size > MAX_TEXT_UPLOAD_BYTES) {
      throw new Error(`${file.name} is too large.`);
    }
    content = await file.text();
  } else {
    throw new Error(`${file.name} is not a supported image, .bib, or .tex file.`);
  }
  const response = await fetch(buildApiUrl(drafterSettings.serverUrl, DRAFTER_ASSETS_API_PATH), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: file.name, content }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Upload failed for ${file.name}`);
  }
  return payload;
}

function renderAssetShelf(message = "") {
  renderAssetList();
  renderAssetDetail(message);
}

function renderAssetList() {
  elements.assetList.innerHTML = "";
  if (!drafterAssets.length) {
    const empty = document.createElement("div");
    empty.className = "asset-empty-state";
    empty.textContent = "No uploaded assets yet.";
    elements.assetList.append(empty);
    return;
  }
  drafterAssets.forEach((asset) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `asset-file${asset.name === selectedAssetName ? " active" : ""}`;
    button.innerHTML = `
      <span class="asset-file-name">${escapeHtml(asset.name)}</span>
      <span class="asset-file-meta">${escapeHtml(asset.kind.toUpperCase())} - ${escapeHtml(formatFileSize(asset.size))}</span>
    `;
    button.addEventListener("click", () => {
      selectedAssetName = asset.name;
      persistSettings();
      renderAssetShelf();
    });
    elements.assetList.append(button);
  });
}

function renderAssetDetail(message = "") {
  elements.assetDetail.innerHTML = "";
  const asset = getSelectedAsset();
  if (!asset) {
    const empty = document.createElement("div");
    empty.className = "asset-empty-state";
    empty.textContent = message || "Upload images, .bib, and .tex files to build a reusable drafting shelf.";
    elements.assetDetail.append(empty);
    return;
  }

  const wrapper = document.createElement("div");
  const detailCopy = asset.kind === "image"
    ? "Insert a figure block or an includegraphics line. Uploaded figures also show up in the render preview when referenced from the draft."
    : asset.kind === "bib"
      ? "Insert a bibliography command, paste the file contents, or drop citation keys directly into the draft."
      : "Insert the file contents directly or add a reusable \\input{} reference.";

  wrapper.innerHTML = `
    <div class="asset-detail-header">
      <div>
        <h4>${escapeHtml(asset.name)}</h4>
        <p class="asset-helper-copy">${escapeHtml(message || detailCopy)}</p>
      </div>
    </div>
    <div class="asset-detail-meta">
      <span class="asset-chip">Type: ${escapeHtml(asset.kind.toUpperCase())}</span>
      <span class="asset-chip">Size: ${escapeHtml(formatFileSize(asset.size))}</span>
      <span class="asset-chip">Path: ${escapeHtml(asset.referencePath || asset.name)}</span>
    </div>
    <div class="asset-actions"></div>
    <div class="asset-detail-preview"></div>
  `;
  elements.assetDetail.append(wrapper);

  const actions = wrapper.querySelector(".asset-actions");
  const preview = wrapper.querySelector(".asset-detail-preview");
  appendAssetAction(actions, "Copy Path", () => void copyText(asset.referencePath || asset.name));
  appendAssetAction(actions, "Delete", () => void deleteAsset(asset.name));

  if (asset.kind === "image") {
    appendAssetAction(actions, "Insert Figure", () => insertTextAtCursor(buildImageFigureSnippet(asset)));
    appendAssetAction(actions, "Insert Include", () => insertTextAtCursor(buildImageReferenceSnippet(asset)));
    const image = document.createElement("img");
    image.className = "asset-preview-image";
    image.alt = asset.name;
    image.src = buildAssetUrl(asset);
    preview.append(image);
    return;
  }

  if (asset.kind === "bib") {
    appendAssetAction(actions, "Insert Bibliography", () => insertTextAtCursor(buildBibliographySnippet(asset)));
    appendAssetAction(actions, "Insert Contents", () => insertTextAtCursor(`${asset.content || ""}\n`));
    const keys = Array.isArray(asset.citationKeys) ? asset.citationKeys : extractBibKeys(asset.content || "");
    if (keys.length) {
      const keyWrap = document.createElement("div");
      keyWrap.className = "asset-citation-list";
      keys.forEach((key) => {
        appendAssetAction(keyWrap, `\\cite{${key}}`, () => insertTextAtCursor(`\\cite{${key}}`));
      });
      preview.append(keyWrap);
    }
  } else {
    appendAssetAction(actions, "Insert \\input{}", () => insertTextAtCursor(buildTexInputSnippet(asset)));
    appendAssetAction(actions, "Insert Contents", () => insertTextAtCursor(`${asset.content || ""}\n`));
  }

  const code = document.createElement("pre");
  code.className = "asset-code-preview";
  code.textContent = asset.content || "";
  preview.append(code);
}

function getSelectedAsset() {
  return drafterAssets.find((asset) => asset.name === selectedAssetName) ?? null;
}

async function deleteAsset(assetName) {
  const response = await fetch(buildApiUrl(drafterSettings.serverUrl, `${DRAFTER_ASSETS_API_PATH}/${encodeURIComponent(assetName)}`), {
    method: "DELETE",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    renderAssetShelf(payload.detail || "Delete failed");
    return;
  }
  if (selectedAssetName === assetName) {
    selectedAssetName = "";
  }
  persistSettings();
  await loadAssets();
}

function renderCollaborators(collaborators) {
  elements.collaboratorList.innerHTML = "";
  const activeCollaborators = Array.isArray(collaborators) ? collaborators : [];
  elements.collaboratorCount.textContent = String(activeCollaborators.length);
  if (!activeCollaborators.length) {
    const empty = document.createElement("div");
    empty.className = "collaborator-card";
    empty.textContent = "No collaborators connected.";
    elements.collaboratorList.append(empty);
    return;
  }
  activeCollaborators.forEach((person) => {
    const row = document.createElement("div");
    row.className = "collaborator-card";
    row.innerHTML = `
      <div class="collaborator-name-row">
        <span class="presence-dot ${presenceClassFor(person.state)}"></span>
        <strong>${escapeHtml(person.name || "guest")}</strong>
      </div>
      <div class="history-meta">${escapeHtml(presenceLabelFor(person.state))}</div>
    `;
    elements.collaboratorList.append(row);
  });
}

function renderCompileLog() {
  elements.compileLog.textContent = "[compile] waiting for first real LaTeX compile...";
  elements.compileStatusLabel.textContent = "WARN";
  updateCompileButtons();
}

function updateCompileButtons() {
  if (elements.compileNowButton) {
    elements.compileNowButton.disabled = compileInFlight;
  }
  if (elements.openCompiledPdfButton) {
    elements.openCompiledPdfButton.disabled = !latestCompiledPdfUrl;
  }
}

function scheduleCompile(reason = "edit") {
  clearTimeout(compileTimer);
  compileTimer = window.setTimeout(() => {
    compileTimer = null;
    void compileLatex({ reason });
  }, COMPILE_DEBOUNCE_MS);
}

async function compileLatex(options = {}) {
  const manual = Boolean(options.manual);
  if (compileInFlight) {
    compileQueued = true;
    return null;
  }
  compileInFlight = true;
  updateCompileButtons();
  if (manual) {
    activatePanel(currentLayout.left.includes("compile") ? "left" : "right", "compile");
  }
  elements.compileStatusLabel.textContent = "BUILD";
  elements.compileLog.textContent = `[compile] running (${String(options.reason || "update")})...`;

  try {
    const response = await fetch(buildApiUrl(drafterSettings.serverUrl, DRAFTER_COMPILE_API_PATH), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: getEditorText(),
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || "Compile request failed");
    }

    const compileLog = String(payload?.log || "").trim();
    elements.compileLog.textContent = compileLog || "[compile] no compiler output returned.";

    if (!payload?.success) {
      elements.compileStatusLabel.textContent = "ERROR";
      return payload;
    }

    elements.compileStatusLabel.textContent = payload.status === "warn" ? "WARN" : "CLEAN";
    const relativePdfUrl = String(payload.pdfUrl || "").trim();
    if (!relativePdfUrl) {
      throw new Error("Compile succeeded but no PDF URL was returned.");
    }
    const base = normalizeServerBase(drafterSettings.serverUrl);
    const pdfUrl = new URL(relativePdfUrl, base);
    pdfUrl.searchParams.set("t", String(payload.compiledAt || Date.now()));
    latestCompiledPdfUrl = pdfUrl.toString();
    renderCompiledPdf(latestCompiledPdfUrl);
    if (Boolean(options.openPdf)) {
      window.open(latestCompiledPdfUrl, "_blank", "noopener,noreferrer");
    }
    return payload;
  } catch (error) {
    elements.compileStatusLabel.textContent = "ERROR";
    elements.compileLog.textContent = `[error] ${error instanceof Error ? error.message : String(error)}`;
    return null;
  } finally {
    compileInFlight = false;
    updateCompileButtons();
    if (compileQueued) {
      compileQueued = false;
      scheduleCompile("queued");
    }
  }
}

function renderCompiledPdf(url) {
  const source = String(url || "").trim();
  if (!source) {
    return;
  }
  elements.previewPane.classList.add("has-pdf");
  const frame = document.createElement("iframe");
  frame.className = "paper-preview-frame";
  frame.src = `${source}#toolbar=1&navpanes=0&view=FitH`;
  frame.title = "Compiled LaTeX PDF";
  frame.loading = "eager";
  elements.previewPane.innerHTML = "";
  elements.previewPane.append(frame);
}

function openCompiledPdf() {
  if (!latestCompiledPdfUrl) {
    return;
  }
  window.open(latestCompiledPdfUrl, "_blank", "noopener,noreferrer");
}

function updateEditorStats() {
  const value = stripLatexComments(getEditorText());
  const wordCount = value
    .replace(/\\[a-zA-Z*]+(\[[^\]]*\])?(\{[^}]*\})?/g, " ")
    .replace(/[{}\\]/g, " ")
    .split(/\s+/)
    .filter(Boolean).length;
  elements.wordCount.textContent = String(wordCount);
  updateCursorPosition();
}

function updateCursorPosition() {
  if (!latexEditor) {
    elements.cursorPosition.textContent = "1:1";
    return;
  }
  const cursor = latexEditor.getCursorPosition();
  elements.cursorPosition.textContent = `${cursor.row + 1}:${cursor.column + 1}`;
}

function renderPreview() {
  elements.previewPane.classList.remove("has-pdf");
  const source = stripLatexComments(getEditorText());
  const documentClass = parseDocumentClass(source);
  const packages = parseUsePackages(source);
  const title = matchLatex(source, /\\title\{([^}]*)\}/) || "Untitled Draft";
  const author = matchLatex(source, /\\author\{([^}]*)\}/)?.replaceAll("\\and", " | ") || "Unknown authors";
  const date = matchLatex(source, /\\date\{([^}]*)\}/) || "\\today";
  const abstractText = matchBlock(source, "abstract") || "";
  const bodySource = extractDocumentBody(source);
  const pageHtml = buildPreviewPages(bodySource, { abstractText });
  const styleClasses = buildPreviewStyleClasses(documentClass, packages);
  elements.previewPane.innerHTML = DOMPurify.sanitize(`
    <div class="paper-preview-deck ${styleClasses}">
      ${pageHtml.length ? pageHtml.map((page, index) => `
        <article class="paper-sheet preview-page" data-page-number="${index + 1}">
          ${index === 0 ? `
            <header class="paper-sheet-header">
              <div class="paper-class-line">${escapeHtml(documentClass.name)} document</div>
              <h2>${escapeHtml(title)}</h2>
              <p class="paper-authors">${escapeHtml(author)}</p>
              <p class="paper-date">${escapeHtml(renderLatexInline(date))}</p>
            </header>
          ` : `<div class="paper-continuation">Continued draft</div>`}
          <div class="paper-page-body">${page}</div>
          <footer class="paper-page-footer">Page ${index + 1}</footer>
        </article>
      `).join("") : `
        <article class="paper-sheet preview-page">
          <header class="paper-sheet-header">
            <div class="paper-class-line">${escapeHtml(documentClass.name)} document</div>
            <h2>${escapeHtml(title)}</h2>
            <p class="paper-authors">${escapeHtml(author)}</p>
            <p class="paper-date">${escapeHtml(renderLatexInline(date))}</p>
          </header>
          <div class="paper-page-body">
            <section class="preview-section"><h3>Preview</h3><p>Add LaTeX content inside \\begin{document}...\\end{document} to build the live preview.</p></section>
          </div>
        </article>
      `}
    </div>
  `);
}

async function runAi() {
  const request = elements.requestInput.value.trim();
  if (!request) {
    elements.requestInput.focus();
    return;
  }
  try {
    persistSettingsFromForm({ validateServer: true });
  } catch (error) {
    elements.response.textContent = `Invalid server URL: ${error instanceof Error ? error.message : String(error)}`;
    setStatus("Error");
    return;
  }
  pendingDiffTarget = "";
  elements.applyDiffButton.disabled = true;
  setStatus("Streaming");
  try {
    const messages = currentMode === "agent" ? buildAgentMessages(request) : buildAskMessages(request);
    const text = await requestCompletion(messages);
    if (currentMode === "agent") {
      handleAgentResponse(text);
    } else {
      handleAskResponse(text);
    }
    setStatus("Ready");
  } catch (error) {
    elements.response.textContent = `Request failed: ${error instanceof Error ? error.message : String(error)}`;
    setStatus("Error");
  }
}

function buildAskMessages(request) {
  const system = [
    "You are a concise paper-writing assistant.",
    "Answer questions using the provided LaTeX paper as the primary context.",
    "When useful, cite specific sections or passages from the current draft.",
    drafterSettings.systemPrompt || "",
  ].filter(Boolean).join(" ");
  const assetsContext = buildDrafterAssetsContext();
  return [
    { role: "system", content: system },
    {
      role: "user",
      content: `Current paper:\n\n${drafterSettings.paper}\n\nUploaded assets:\n${assetsContext}\n\nQuestion:\n${request}`,
    },
  ];
}

function buildAgentMessages(request) {
  const system = [
    "You are a paper-editing agent.",
    "Given the current LaTeX project and a user request, propose a concrete revision.",
    "Return exactly two labeled sections in plain text.",
    "First section: EXPLANATION: followed by a concise explanation.",
    "Second section: DIFF: followed by a unified diff patch against the current LaTeX content.",
    "The diff must update only main.tex content and be directly reviewable by a human.",
    "Use uploaded assets when relevant and reference them by their provided referencePath.",
    drafterSettings.systemPrompt || "",
  ].filter(Boolean).join(" ");
  const assetsContext = buildDrafterAssetsContext();
  return [
    { role: "system", content: system },
    {
      role: "user",
      content: `Current file: main.tex\n\n${drafterSettings.paper}\n\nUploaded assets:\n${assetsContext}\n\nUser request:\n${request}`,
    },
  ];
}

function buildDrafterAssetsContext() {
  if (!Array.isArray(drafterAssets) || !drafterAssets.length) {
    return "None.";
  }

  const lines = drafterAssets.map((asset, index) => {
    const kind = String(asset?.kind || "unknown").toLowerCase();
    const name = String(asset?.name || "unnamed");
    const size = Number(asset?.size || 0);
    const referencePath = String(asset?.referencePath || name);
    const url = String(asset?.url || "");
    const citationKeys = Array.isArray(asset?.citationKeys) ? asset.citationKeys.filter(Boolean).slice(0, 20) : [];
    const textContent = kind === "bib" || kind === "tex" ? String(asset?.content || "") : "";
    const snippet = textContent ? textContent.slice(0, 1800) : "";
    const truncated = textContent.length > snippet.length;

    const detailParts = [
      `${index + 1}. name=${name}`,
      `type=${kind}`,
      `size=${size}`,
      `referencePath=${referencePath}`,
    ];
    if (url) {
      detailParts.push(`url=${url}`);
    }
    if (citationKeys.length) {
      detailParts.push(`citationKeys=${citationKeys.join(", ")}`);
    }
    if (snippet) {
      detailParts.push(`contentSnippet=${JSON.stringify(snippet)}${truncated ? " (truncated)" : ""}`);
    }
    return detailParts.join(" | ");
  });
  return lines.join("\n");
}

async function requestCompletion(messages) {
  const response = await fetch(buildApiUrl(drafterSettings.serverUrl, "/v1/chat/completions"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: drafterSettings.modelId,
      stream: false,
      temperature: drafterSettings.temperature,
      max_tokens: drafterSettings.maxTokens,
      provider_options: getModelProviderOptions(drafterSettings.modelId),
      messages,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "Request failed");
  }
  return payload?.choices?.[0]?.message?.content?.trim() || "";
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
    drafterSettings.temperature = model.default_temperature;
    elements.temperatureInput.value = model.default_temperature;
  }
  if (typeof model.default_max_tokens === "number") {
    drafterSettings.maxTokens = model.default_max_tokens;
    elements.maxTokensInput.value = model.default_max_tokens;
  }
}

function handleAskResponse(text) {
  const answer = String(text || "No response.");
  elements.response.innerHTML = DOMPurify.sanitize(marked.parse(answer));
  elements.agentExplanation.textContent = answer;
  elements.agentDiff.textContent = "No diff generated in Ask mode.";
  elements.proposalMeta.textContent = `Ask response at ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  elements.lastDiffStatus.textContent = "none";
  elements.applyDiffButton.disabled = true;
  activateProposalPanel();
}

function handleAgentResponse(text) {
  const parsed = parseAgentResponse(text);
  elements.response.innerHTML = DOMPurify.sanitize(marked.parse(parsed.explanation || "No explanation returned."));
  elements.agentExplanation.textContent = parsed.explanation || "No explanation returned.";
  elements.agentDiff.textContent = parsed.diff || "No diff returned.";
  hljs.highlightElement(elements.agentDiff);
  elements.proposalMeta.textContent = `Generated at ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  const appliedText = applyUnifiedDiff(drafterSettings.paper, parsed.diff);
  if (appliedText && appliedText !== drafterSettings.paper) {
    pendingDiffTarget = appliedText;
    elements.applyDiffButton.disabled = false;
    elements.lastDiffStatus.textContent = "proposal ready";
  } else {
    pendingDiffTarget = "";
    elements.applyDiffButton.disabled = true;
    elements.lastDiffStatus.textContent = "diff not applicable";
  }
  activateProposalPanel();
}

function activateProposalPanel() {
  activatePanel(currentLayout.left.includes("proposal") ? "left" : "right", "proposal");
}

function parseAgentResponse(text) {
  const explanationMatch = text.match(/EXPLANATION:\s*([\s\S]*?)(?:\nDIFF:|$)/i);
  const diffMatch = text.match(/DIFF:\s*([\s\S]*)$/i);
  let diff = normalizeAgentDiff(diffMatch?.[1] || "");
  if (!diff) {
    const inferred = normalizeAgentDiff(text);
    if (inferred.includes("@@")) {
      diff = inferred;
    }
  }
  return {
    explanation: explanationMatch?.[1]?.trim() || text.trim(),
    diff,
  };
}

function applyPendingDiff() {
  if (!pendingDiffTarget) {
    return;
  }
  drafterSettings.paper = pendingDiffTarget;
  setEditorText(pendingDiffTarget);
  pendingDiffTarget = "";
  elements.applyDiffButton.disabled = true;
  elements.lastDiffStatus.textContent = "applied";
  persistSettings();
  if (!latestCompiledPdfUrl) {
    renderPreview();
  }
  updateEditorStats();
  scheduleCompile("apply-diff");
  flushDraftSync("editing");
}

function saveSnapshot() {
  snapshots.unshift({ id: crypto.randomUUID(), paper: getEditorText(), savedAt: Date.now() });
  snapshots = snapshots.slice(0, 8);
  localStorage.setItem(DRAFTER_SNAPSHOTS_KEY, JSON.stringify(snapshots));
  elements.lastDiffStatus.textContent = "snapshot saved";
}

function downloadDraftFile() {
  const blob = new Blob([getEditorText()], { type: "application/x-tex" });
  downloadBlob(blob, "main.tex");
  elements.lastDiffStatus.textContent = "main.tex downloaded";
}

async function exportPreviewPdf() {
  const result = await compileLatex({ manual: true, reason: "export", openPdf: true });
  if (result?.success) {
    elements.lastDiffStatus.textContent = "compiled pdf opened";
    return;
  }
  elements.lastDiffStatus.textContent = compileInFlight ? "compile in progress" : "compile failed";
}

function loadSnapshots() {
  const parsed = safeParse(localStorage.getItem(DRAFTER_SNAPSHOTS_KEY));
  return Array.isArray(parsed) ? parsed : [];
}

function setStatus(text) {
  elements.statusPill.textContent = text;
  elements.statusPill.classList.remove("is-idle", "is-streaming", "is-error");
  if (text === "Streaming") {
    elements.statusPill.classList.add("is-streaming");
  } else if (text === "Error") {
    elements.statusPill.classList.add("is-error");
  } else {
    elements.statusPill.classList.add("is-idle");
  }
}

function updateConnectionState(text) {
  elements.connectionLabel.textContent = text;
}

async function connectToDraft(options = {}) {
  const forceReconnect = Boolean(options.forceReconnect);
  try {
    persistSettingsFromForm({ validateServer: true });
  } catch (error) {
    updateConnectionState(`Invalid server URL: ${error instanceof Error ? error.message : String(error)}`);
    return;
  }
  elements.draftRoomLabel.textContent = drafterSettings.roomName;
  await loadModelsForServer(drafterSettings.serverUrl);
  if (draftSocket && draftSocket.readyState === WebSocket.OPEN && !forceReconnect) {
    return;
  }
  if (draftSocket && draftSocket.readyState <= WebSocket.OPEN) {
    draftSocket.close();
  }
  updateConnectionState("Connecting");
  const socket = new WebSocket(buildDraftSocketUrl(drafterSettings.serverUrl, drafterSettings.roomName, drafterSettings.displayName));
  draftSocket = socket;
  socket.addEventListener("open", () => {
    if (draftSocket !== socket) {
      return;
    }
    updateConnectionState(`Connected to #${drafterSettings.roomName}`);
    elements.connectButton.disabled = true;
    elements.disconnectButton.disabled = false;
    elements.collabChatSend.disabled = false;
    elements.collabChatInput.disabled = false;
    sendPresence("viewing");
  });
  socket.addEventListener("message", (event) => {
    if (draftSocket === socket) {
      handleDraftSocketMessage(event.data);
    }
  });
  socket.addEventListener("close", (event) => {
    if (draftSocket !== socket) {
      return;
    }
    updateConnectionState(`Disconnected${event.reason ? `: ${event.reason}` : ""}`);
    elements.connectButton.disabled = false;
    elements.disconnectButton.disabled = true;
    elements.collabChatSend.disabled = true;
    elements.collabChatInput.disabled = true;
    renderCollaborators([]);
    renderDraftChat([]);
    draftSocket = null;
  });
  socket.addEventListener("error", () => {
    if (draftSocket === socket) {
      updateConnectionState("Error");
    }
  });
}

function disconnectFromDraft() {
  if (draftSocket) {
    draftSocket.close();
  }
}

function handleDraftSocketMessage(rawPayload) {
  const payload = safeParse(rawPayload);
  if (!payload) {
    return;
  }
  if (Array.isArray(payload.collaborators)) {
    renderCollaborators(payload.collaborators);
  }
  if (payload.type === "snapshot") {
    if (typeof payload.content === "string" && payload.content.trim()) {
      applyRemotePaper(payload.content);
    } else if (drafterSettings.paper.trim()) {
      flushDraftSync("viewing");
    }
    renderDraftChat(payload.chatMessages);
    return;
  }
  if (payload.type === "draft_update" && typeof payload.content === "string" && payload.content !== drafterSettings.paper) {
    applyRemotePaper(payload.content);
    return;
  }
  if (payload.type === "draft_chat") {
    appendDraftChatMessage(payload.message);
  }
}

function applyRemotePaper(content) {
  remoteApplyInProgress = true;
  drafterSettings.paper = content;
  setEditorText(content);
  persistSettings();
  if (!latestCompiledPdfUrl) {
    renderPreview();
  }
  updateEditorStats();
  scheduleCompile("remote-sync");
  remoteApplyInProgress = false;
}

function sendPresence(state) {
  if (draftSocket?.readyState === WebSocket.OPEN) {
    draftSocket.send(JSON.stringify({ type: "presence", state }));
  }
}

function sendDraftChatMessage() {
  if (draftSocket?.readyState !== WebSocket.OPEN) {
    return;
  }
  const content = String(elements.collabChatInput.value || "").trim();
  if (!content) {
    return;
  }
  draftSocket.send(JSON.stringify({ type: "draft_chat", content }));
  elements.collabChatInput.value = "";
}

function renderDraftChat(messages) {
  draftChatMessages = Array.isArray(messages) ? messages.slice(-80) : [];
  elements.collabChatMessages.innerHTML = "";
  if (!draftChatMessages.length) {
    const empty = document.createElement("div");
    empty.className = "history-meta";
    empty.textContent = "No messages yet.";
    elements.collabChatMessages.append(empty);
    return;
  }
  draftChatMessages.forEach((message) => {
    elements.collabChatMessages.append(buildDraftChatMessageNode(message));
  });
  elements.collabChatMessages.scrollTop = elements.collabChatMessages.scrollHeight;
}

function appendDraftChatMessage(message) {
  if (!message || typeof message !== "object") {
    return;
  }
  draftChatMessages.push(message);
  draftChatMessages = draftChatMessages.slice(-80);
  if (draftChatMessages.length === 1) {
    elements.collabChatMessages.innerHTML = "";
  }
  elements.collabChatMessages.append(buildDraftChatMessageNode(message));
  elements.collabChatMessages.scrollTop = elements.collabChatMessages.scrollHeight;
}

function buildDraftChatMessageNode(message) {
  const item = document.createElement("article");
  item.className = "drafter-chat-message";
  const sender = escapeHtml(String(message.sender || "guest"));
  const content = escapeHtml(String(message.content || ""));
  const stamp = formatTimestamp(message.createdAt);
  item.innerHTML = `
    <div class="drafter-chat-meta">
      <strong>${sender}</strong>
      <span class="room-meta-tail">${escapeHtml(stamp)}</span>
    </div>
    <div class="drafter-chat-content">${content}</div>
  `;
  return item;
}

function scheduleDraftSync(state = "editing") {
  clearTimeout(syncTimer);
  syncTimer = window.setTimeout(() => flushDraftSync(state), SYNC_DEBOUNCE_MS);
}

function flushDraftSync(state = "editing") {
  clearTimeout(syncTimer);
  syncTimer = null;
  if (draftSocket?.readyState !== WebSocket.OPEN) {
    return;
  }
  draftSocket.send(JSON.stringify({ type: "sync", content: drafterSettings.paper, state }));
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function buildDraftSocketUrl(serverBase, roomName, displayName) {
  const url = new URL(normalizeServerBase(serverBase));
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/ws/drafts/${encodeURIComponent(normalizeRoomName(roomName, "paper-main"))}`;
  url.searchParams.set("name", normalizeHandle(displayName));
  return url.toString();
}

function buildApiUrl(serverBase, pathname) {
  const url = new URL(normalizeServerBase(serverBase));
  url.pathname = pathname;
  url.search = "";
  url.hash = "";
  return url.toString();
}

function presenceClassFor(state) {
  if (state === "editing") {
    return "presence-live";
  }
  if (state === "viewing" || state === "reviewing") {
    return "presence-review";
  }
  return "presence-idle";
}

function presenceLabelFor(state) {
  if (state === "editing") {
    return "editing draft";
  }
  if (state === "reviewing") {
    return "reviewing";
  }
  if (state === "idle") {
    return "idle";
  }
  return "viewing";
}

function formatTimestamp(value) {
  const timestamp = Number(value || Date.now());
  return new Date(timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function initializeLatexEditor() {
  if (!window.ace || !elements.latexEditorHost) {
    return null;
  }
  const editor = window.ace.edit(elements.latexEditorHost);
  editor.session.setMode("ace/mode/latex");
  editor.setTheme("ace/theme/textmate");
  editor.session.setUseWrapMode(true);
  editor.setShowPrintMargin(false);
  editor.setOptions({
    behavioursEnabled: true,
    enableBasicAutocompletion: true,
    enableLiveAutocompletion: true,
    enableSnippets: true,
    fontFamily: "\"Courier New\", monospace",
    fontSize: "15px",
    tabSize: 2,
    useSoftTabs: true,
    wrap: true,
  });
  editor.renderer.setScrollMargin(14, 14, 0, 0);
  configureLatexAutocomplete(editor);
  return editor;
}

function configureLatexAutocomplete(editor) {
  const languageTools = window.ace?.require?.("ace/ext/language_tools");
  if (!languageTools || window.__localchatLatexCompleterInstalled) {
    return;
  }
  languageTools.addCompleter({
    identifierRegexps: [/[\\a-zA-Z]+/],
    getCompletions(_editor, _session, position, prefix, callback) {
      const linePrefix = editor.session.getLine(position.row).slice(0, position.column);
      const latexPrefix = linePrefix.match(/\\[a-zA-Z]*$/)?.[0] || prefix || "";
      const search = latexPrefix.toLowerCase();
      callback(null, LATEX_COMPLETIONS
        .filter(([caption, snippet]) => !search || caption.toLowerCase().includes(search) || snippet.toLowerCase().includes(search))
        .map(([caption, snippet, meta], index) => ({
          caption,
          meta,
          score: 1000 - index,
          snippet,
          value: snippet,
        })));
    },
  });
  window.__localchatLatexCompleterInstalled = true;
}

function getEditorText() {
  return latexEditor ? latexEditor.getValue() : "";
}

function setEditorText(value) {
  if (!latexEditor) {
    return;
  }
  suppressEditorEvents = true;
  latexEditor.session.setValue(String(value || ""));
  latexEditor.clearSelection();
  latexEditor.moveCursorTo(0, 0);
  latexEditor.scrollToLine(0, true, false, () => {});
  suppressEditorEvents = false;
}

function appendAssetAction(container, label, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = label;
  button.addEventListener("click", handler);
  container.append(button);
}

function buildAssetUrl(asset) {
  return new URL(asset.url, normalizeServerBase(drafterSettings.serverUrl)).toString();
}

function buildImageFigureSnippet(asset) {
  const label = normalizeLatexLabel(asset.name);
  return String.raw`\begin{figure}[ht]
\centering
\includegraphics[width=0.82\linewidth]{${asset.referencePath}}
\caption{${humanizeAssetLabel(asset.name)}}
\label{fig:${label}}
\end{figure}

`;
}

function buildImageReferenceSnippet(asset) {
  return `\\includegraphics[width=\\linewidth]{${asset.referencePath}}\n`;
}

function buildBibliographySnippet(asset) {
  const target = asset.referencePath.replace(/\.bib$/i, "");
  return `\\bibliographystyle{plain}\n\\bibliography{${target}}\n`;
}

function buildTexInputSnippet(asset) {
  const target = asset.referencePath.replace(/\.tex$/i, "");
  return `\\input{${target}}\n`;
}

function insertTextAtCursor(value) {
  if (!latexEditor) {
    return;
  }
  latexEditor.session.insert(latexEditor.getCursorPosition(), value);
  latexEditor.focus();
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    insertTextAtCursor(value);
  }
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
    reader.onload = () => resolve(String(reader.result || ""));
    reader.readAsDataURL(file);
  });
}

function getFileExtension(value) {
  return value.includes(".") ? `.${value.split(".").pop().toLowerCase()}` : "";
}

function isImageAsset(value) {
  return [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"].includes(getFileExtension(value));
}

function formatFileSize(value) {
  const size = Number(value || 0);
  if (size >= 1_000_000) {
    return `${(size / 1_000_000).toFixed(1)} MB`;
  }
  if (size >= 1_000) {
    return `${Math.round(size / 1_000)} KB`;
  }
  return `${size} B`;
}

function resolveAssetReference(reference) {
  const normalized = String(reference || "").trim().replace(/^\.?\//, "").replace(/^assets\//, "");
  return drafterAssets.find((asset) => asset.referencePath === normalized || asset.name === normalized || normalized.endsWith(`/${asset.name}`)) ?? null;
}

function humanizeAssetLabel(value) {
  return String(value || "")
    .replace(/\.[^.]+$/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim() || "Uploaded figure";
}

function normalizeLatexLabel(value) {
  return String(value || "")
    .replace(/\.[^.]+$/, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "asset";
}

function extractBibKeys(content) {
  return [...String(content || "").matchAll(/@\w+\s*\{\s*([^,\s]+)/g)].map((match) => match[1]).filter(Boolean);
}

function normalizeAgentName(value) {
  const cleaned = String(value || "").replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 48);
  return cleaned || "Paper Editor";
}

function normalizeHandle(value) {
  const cleaned = String(value || "").replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim().replace(/[^a-zA-Z0-9 .:_-]+/g, "").slice(0, 32);
  return cleaned || "guest";
}

function normalizeRoomName(value, fallback) {
  const cleaned = String(value || "").trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  return cleaned || fallback;
}

function normalizeServerBase(value) {
  const rawValue = String(value || "").trim();
  if (!rawValue) {
    return window.location.origin;
  }
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
}

function safeNormalizeServerBase(value, fallback) {
  try {
    return normalizeServerBase(value);
  } catch {
    return normalizeServerBase(fallback || window.location.origin);
  }
}

function extractDocumentBody(source) {
  return source.match(/\\begin\{document\}([\s\S]*?)\\end\{document\}/)?.[1]?.trim() || source.trim();
}

function parseDocumentClass(source) {
  const match = source.match(/\\documentclass(?:\[([^\]]*)\])?\{([^}]*)\}/);
  return {
    name: match?.[2]?.trim() || "article",
    options: match?.[1]?.split(",").map((item) => item.trim()).filter(Boolean) || [],
  };
}

function parseUsePackages(source) {
  return [...source.matchAll(/\\usepackage(?:\[([^\]]*)\])?\{([^}]+)\}/g)].flatMap((match) => {
    const options = match[1]?.split(",").map((item) => item.trim()).filter(Boolean) || [];
    return match[2].split(",").map((name) => ({ name: name.trim(), options })).filter((item) => item.name);
  });
}

function buildPreviewStyleClasses(documentClass, packages) {
  const classNames = [`is-${documentClass.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`];
  if (documentClass.options.includes("twocolumn")) {
    classNames.push("is-twocolumn");
  }
  if (packages.some((pkg) => pkg.name === "xcolor" || pkg.name === "color")) {
    classNames.push("has-color-package");
  }
  if (packages.some((pkg) => pkg.name === "geometry")) {
    classNames.push("has-geometry-package");
  }
  return classNames.join(" ");
}

function stripLatexComments(source) {
  return String(source || "")
    .split(/\r?\n/)
    .map((line) => stripLatexCommentLine(line))
    .join("\n");
}

function stripLatexCommentLine(line) {
  let escaped = false;
  let output = "";
  for (const character of String(line || "")) {
    if (character === "%" && !escaped) {
      break;
    }
    output += character;
    if (character === "\\") {
      escaped = !escaped;
    } else {
      escaped = false;
    }
  }
  return output;
}

function cleanLatexText(value) {
  return stripLatexComments(value)
    .replace(/\\subsection\{([^}]*)\}/g, "$1")
    .replace(/\\textbf\{([^}]*)\}/g, "$1")
    .replace(/\\emph\{([^}]*)\}/g, "$1")
    .replace(/\\[a-zA-Z*]+(\[[^\]]*\])?/g, " ")
    .replace(/[{}]/g, " ")
    .replace(/\s+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function matchLatex(source, regex) {
  return source.match(regex)?.[1]?.trim() || "";
}

function matchBlock(source, name) {
  return source.match(new RegExp(String.raw`\\begin\{${name}\}([\s\S]*?)\\end\{${name}\}`))?.[1]?.trim() || "";
}

function renderLatexInline(value) {
  return String(value || "")
    .replace(/\\today/g, new Date().toLocaleDateString())
    .replace(/\\textbf\{([^}]*)\}/g, "<strong>$1</strong>")
    .replace(/\\emph\{([^}]*)\}/g, "<em>$1</em>")
    .replace(/\\textit\{([^}]*)\}/g, "<em>$1</em>")
    .replace(/\\underline\{([^}]*)\}/g, "<span class=\"preview-underline\">$1</span>")
    .replace(/\\cite\{([^}]*)\}/g, "<span class=\"preview-cite\">[$1]</span>")
    .replace(/\\ref\{([^}]*)\}/g, "<span class=\"preview-ref\">$1</span>")
    .replace(/\\label\{([^}]*)\}/g, "")
    .replace(/\\[a-zA-Z*]+(?:\[[^\]]*\])?/g, " ")
    .replace(/[{}]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function buildPreviewPages(bodySource, options = {}) {
  const explicitChunks = bodySource
    .split(/\\(?:newpage|clearpage|pagebreak)(?:\[[^\]]*\])?\s*/g)
    .map((chunk) => chunk.trim())
    .filter(Boolean);
  const sourceChunks = explicitChunks.length ? explicitChunks : [bodySource.trim()];
  const pages = [];

  sourceChunks.forEach((chunk, chunkIndex) => {
    const blocks = [];
    if (chunkIndex === 0 && options.abstractText?.trim()) {
      blocks.push(renderAbstractBlock(options.abstractText));
    }
    blocks.push(...renderPreviewBlocks(chunk));
    if (!blocks.length) {
      return;
    }
    pages.push(...paginatePreviewBlocks(blocks));
  });
  return pages;
}

function renderAbstractBlock(abstractText) {
  return {
    weight: Math.max(240, abstractText.length),
    html: `
      <section class="preview-abstract">
        <div class="section-label">Abstract</div>
        ${renderLatexParagraphs(abstractText)}
      </section>
    `,
  };
}

function renderPreviewBlocks(source) {
  const blocks = [];
  const sectionMatches = [...source.matchAll(/\\section\{([^}]*)\}([\s\S]*?)(?=\\section\{|$)/g)];
  if (!sectionMatches.length) {
    const html = renderGenericBodyBlock(source);
    return html ? [{ weight: Math.max(220, source.length), html }] : [];
  }
  const firstSectionIndex = sectionMatches[0]?.index ?? 0;
  const intro = source.slice(0, firstSectionIndex).trim();
  if (intro) {
    const introHtml = renderGenericBodyBlock(intro);
    if (introHtml) {
      blocks.push({ weight: Math.max(180, intro.length), html: introHtml });
    }
  }
  sectionMatches.forEach((match) => {
    const heading = match[1] || "Section";
    const body = match[2] || "";
    blocks.push({
      weight: Math.max(340, heading.length + body.length),
      html: `<section class="preview-section"><h3>${escapeHtml(heading)}</h3>${renderSectionBody(body)}</section>`,
    });
  });
  return blocks;
}

function renderSectionBody(source) {
  const body = source.trim();
  if (!body) {
    return "<p>Section body pending.</p>";
  }
  const figureMatches = [...body.matchAll(/\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}/g)];
  const figuresHtml = figureMatches.map((match, index) => renderFigureBlock(match[0], index + 1)).join("");
  const bodyWithoutFigures = body.replace(/\\includegraphics(?:\[[^\]]*\])?\{[^}]+\}/g, "");
  const renderedBody = renderRichLatexBody(bodyWithoutFigures);
  return `${renderedBody}${figuresHtml}`;
}

function renderRichLatexBody(body) {
  const trimmed = body.trim();
  if (!trimmed) {
    return "";
  }
  const subsections = [...trimmed.matchAll(/\\subsection\{([^}]*)\}([\s\S]*?)(?=\\subsection\{|$)/g)];
  if (!subsections.length) {
    return renderBlockElements(trimmed);
  }
  const intro = trimmed.slice(0, subsections[0]?.index ?? 0).trim();
  const introHtml = intro ? renderBlockElements(intro) : "";
  return `${introHtml}${subsections.map((match) => `
    <div class="preview-subsection-block">
      <h4>${escapeHtml(match[1])}</h4>
      ${renderBlockElements(match[2])}
    </div>
  `).join("")}`;
}

function renderBlockElements(source) {
  let remaining = String(source || "");
  const parts = [];
  const pattern = /\\begin\{(itemize|enumerate|equation|align)\}([\s\S]*?)\\end\{\1\}/g;
  let lastIndex = 0;
  for (const match of remaining.matchAll(pattern)) {
    const before = remaining.slice(lastIndex, match.index).trim();
    if (before) {
      parts.push(renderLatexParagraphs(before));
    }
    if (match[1] === "itemize" || match[1] === "enumerate") {
      parts.push(renderListBlock(match[2], match[1] === "enumerate"));
    } else {
      parts.push(`<pre class="preview-equation">${escapeHtml(match[2].trim() || `${match[1]} block`)}</pre>`);
    }
    lastIndex = match.index + match[0].length;
  }
  const tail = remaining.slice(lastIndex).trim();
  if (tail) {
    parts.push(renderLatexParagraphs(tail));
  }
  return parts.join("");
}

function renderGenericBodyBlock(source) {
  const cleaned = source
    .replace(/\\maketitle/g, "")
    .replace(/\\tableofcontents/g, "<div class=\"preview-toc\">Table of contents will be generated in full LaTeX compile.</div>")
    .trim();
  if (!cleaned) {
    return "";
  }
  return `<section class="preview-section">${renderLatexParagraphs(cleaned)}</section>`;
}

function renderLatexParagraphs(source) {
  const paragraphs = String(source || "")
    .replace(/\\par\b/g, "\n\n")
    .split(/\n\s*\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!paragraphs.length) {
    return "<p></p>";
  }
  return paragraphs.map((paragraph) => `<p>${renderLatexInline(paragraph)}</p>`).join("");
}

function renderListBlock(source, ordered = false) {
  const tag = ordered ? "ol" : "ul";
  const items = source.split(/\\item/g).map((item) => item.trim()).filter(Boolean);
  if (!items.length) {
    return "";
  }
  return `<${tag} class="preview-list">${items.map((item) => `<li>${renderLatexInline(item)}</li>`).join("")}</${tag}>`;
}

function renderFigureBlock(rawFigure, index) {
  const target = rawFigure.match(/\{([^}]+)\}/)?.[1] || "";
  const asset = resolveAssetReference(target);
  if (!asset) {
    return `<figure class="preview-figure"><div class="section-label">Figure ${index}</div><figcaption>Missing uploaded asset for ${escapeHtml(target)}</figcaption></figure>`;
  }
  return `
    <figure class="preview-figure">
      <div class="section-label">Figure ${index}</div>
      <img src="${escapeHtml(buildAssetUrl(asset))}" alt="${escapeHtml(asset.name)}">
      <figcaption>${escapeHtml(humanizeAssetLabel(asset.name))}</figcaption>
    </figure>
  `;
}

function paginatePreviewBlocks(blocks) {
  const pages = [];
  let current = [];
  let currentWeight = 0;
  const pageLimit = 1500;
  blocks.forEach((block) => {
    if (current.length && currentWeight + block.weight > pageLimit) {
      pages.push(current.map((item) => item.html).join(""));
      current = [];
      currentWeight = 0;
    }
    current.push(block);
    currentWeight += block.weight;
  });
  if (current.length) {
    pages.push(current.map((item) => item.html).join(""));
  }
  return pages;
}

function normalizeAgentDiff(rawDiff) {
  let text = String(rawDiff || "").trim();
  if (!text) {
    return "";
  }
  const fencedMatches = [...text.matchAll(/```(?:diff|patch)?\s*([\s\S]*?)```/gi)];
  if (fencedMatches.length) {
    const withHunks = fencedMatches.find((match) => String(match[1] || "").includes("@@"));
    text = (withHunks?.[1] || fencedMatches[0]?.[1] || "").trim();
  }
  return text.trim();
}

function applyUnifiedDiff(originalText, diffText) {
  const strict = applyUnifiedDiffStrict(originalText, diffText);
  if (strict) {
    return strict;
  }
  return applyUnifiedDiffLenient(originalText, diffText);
}

function applyUnifiedDiffStrict(originalText, diffText) {
  if (!diffText.trim()) {
    return "";
  }
  const lines = diffText.split(/\r?\n/);
  const hunks = [];
  let currentHunk = null;
  for (const line of lines) {
    if (line.startsWith("@@")) {
      const match = line.match(/^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@/);
      if (!match) {
        continue;
      }
      currentHunk = { oldStart: Number(match[1]), oldCount: Number(match[2] || "1"), newStart: Number(match[3]), newCount: Number(match[4] || "1"), lines: [] };
      hunks.push(currentHunk);
      continue;
    }
    if (currentHunk && (/^[ +-]/.test(line) || line === "\\ No newline at end of file")) {
      currentHunk.lines.push(line);
    }
  }
  if (!hunks.length) {
    return "";
  }
  const sourceLines = originalText.split("\n");
  const output = [];
  let sourceIndex = 0;
  for (const hunk of hunks) {
    const targetIndex = Math.max(0, hunk.oldStart - 1);
    if (targetIndex < sourceIndex) {
      return "";
    }
    while (sourceIndex < targetIndex) {
      output.push(sourceLines[sourceIndex]);
      sourceIndex += 1;
    }
    for (const line of hunk.lines) {
      if (!line) {
        output.push("");
        continue;
      }
      const prefix = line[0];
      const content = line.slice(1);
      if (prefix === " ") {
        if (sourceLines[sourceIndex] !== content) {
          return "";
        }
        output.push(content);
        sourceIndex += 1;
      } else if (prefix === "-") {
        if (sourceLines[sourceIndex] !== content) {
          return "";
        }
        sourceIndex += 1;
      } else if (prefix === "+") {
        output.push(content);
      }
    }
  }
  while (sourceIndex < sourceLines.length) {
    output.push(sourceLines[sourceIndex]);
    sourceIndex += 1;
  }
  return output.join("\n");
}

function applyUnifiedDiffLenient(originalText, diffText) {
  if (!diffText.trim()) {
    return "";
  }
  const lines = diffText.split(/\r?\n/);
  const hunks = [];
  let currentHunk = null;
  for (const line of lines) {
    if (line.startsWith("@@")) {
      const match = line.match(/^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@/);
      if (!match) {
        continue;
      }
      currentHunk = { oldStart: Number(match[1]), oldCount: Number(match[2] || "1"), newStart: Number(match[3]), newCount: Number(match[4] || "1"), lines: [] };
      hunks.push(currentHunk);
      continue;
    }
    if (currentHunk && (/^[ +-]/.test(line) || line === "\\ No newline at end of file")) {
      currentHunk.lines.push(line);
    }
  }
  if (!hunks.length) {
    return "";
  }
  const sourceLines = originalText.split("\n");
  const output = [];
  let sourceIndex = 0;
  for (const hunk of hunks) {
    const targetIndex = Math.max(sourceIndex, hunk.oldStart - 1);
    while (sourceIndex < targetIndex && sourceIndex < sourceLines.length) {
      output.push(sourceLines[sourceIndex]);
      sourceIndex += 1;
    }
    for (const line of hunk.lines) {
      if (!line) {
        output.push("");
        continue;
      }
      const prefix = line[0];
      const content = line.slice(1);
      if (prefix === " ") {
        output.push(content);
        if (sourceIndex < sourceLines.length) {
          sourceIndex += 1;
        }
      } else if (prefix === "-") {
        if (sourceIndex < sourceLines.length) {
          sourceIndex += 1;
        }
      } else if (prefix === "+") {
        output.push(content);
      }
    }
  }
  while (sourceIndex < sourceLines.length) {
    output.push(sourceLines[sourceIndex]);
    sourceIndex += 1;
  }
  return output.join("\n");
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
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("\"", "&quot;").replaceAll("'", "&#039;");
}
