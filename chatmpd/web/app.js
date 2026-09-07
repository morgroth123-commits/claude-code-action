"use strict";

const $ = (id) => document.getElementById(id);
const MOBILE_TOKEN_KEY = "chatmpd-mobile-token";
const state = {
  conversations: [],
  activeConversation: null,
  activeJob: null,
  workspace: "",
  mobile: null,
  clientMode: "desktop",
  pendingAttachments: [],
  pendingAttachmentIds: [],
  lastSubmittedText: "",
};

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = localStorage.getItem(MOBILE_TOKEN_KEY) || "";
  if (state.clientMode === "mobile" && token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

async function copyText(value) {
  const text = String(value || "");
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
  } else {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

function setTheme(theme) {
  const choice = ["system", "light", "dark"].includes(theme) ? theme : "system";
  document.documentElement.dataset.theme = choice;
  localStorage.setItem("chatmpd-theme", choice);
}

async function pairDevice() {
  const code = $("mobile-pair-code").value.trim();
  const deviceName = $("mobile-device-name").value.trim() || "My phone";
  try {
    const credential = await api("/api/pair", {
      method: "POST",
      body: JSON.stringify({ code, device_name: deviceName }),
    });
    localStorage.setItem(MOBILE_TOKEN_KEY, credential.token);
    $("mobile-pair-screen").hidden = true;
    $("app-shell").hidden = false;
    $("pair-error").textContent = "";
    await loadConversations();
    if (state.conversations.length) await openConversation(state.conversations[0].conversation_id);
    else await createConversation();
  } catch (error) {
    $("pair-error").textContent = error.message;
  }
}

function setBusy(busy, capability = "") {
  $("working").hidden = !busy;
  $("send").hidden = busy;
  $("stop").hidden = !busy;
  $("prompt").disabled = busy;
  if (capability) $("capability-label").textContent = capability;
}

function showSidebar(show) {
  document.body.classList.toggle("sidebar-open", Boolean(show));
  $("sidebar-scrim").hidden = !show;
}

function conversationButton(summary) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "conversation-item";
  if (state.activeConversation === summary.conversation_id) button.classList.add("active");
  button.addEventListener("click", () => openConversation(summary.conversation_id));

  const title = document.createElement("span");
  title.className = "conversation-title";
  title.textContent = `${summary.pinned ? "★ " : ""}${summary.title}`;
  const preview = document.createElement("span");
  preview.className = "conversation-preview";
  preview.textContent = summary.preview || "";
  button.append(title, preview);
  return button;
}

function renderConversationList(items) {
  const list = $("conversation-list");
  list.replaceChildren();
  let lastPinned = null;
  for (const item of items) {
    if (lastPinned !== item.pinned) {
      const label = document.createElement("div");
      label.className = "sidebar-section-label";
      label.textContent = item.pinned ? "Pinned" : "Recent";
      list.append(label);
      lastPinned = item.pinned;
    }
    list.append(conversationButton(item));
  }
}

async function loadConversations(query = "") {
  const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
  state.conversations = await api(`/api/conversations${suffix}`);
  renderConversationList(state.conversations);
}

function renderWorkspace(workspace) {
  state.workspace = String(workspace || "").trim();
  $("project-label").textContent = state.workspace || "Choose project";
  $("workspace-chip").textContent = state.workspace;
  $("workspace-chip").hidden = !state.workspace;
}

async function createConversation() {
  const document = await api("/api/conversations", { method: "POST", body: "{}" });
  state.activeConversation = document.conversation_id;
  clearPendingAttachmentSelection();
  $("conversation-title").textContent = document.title;
  renderWorkspace(document.workspace);
  renderMessages(document.messages || []);
  await loadConversations();
  $("prompt").focus();
  showSidebar(false);
  return document;
}

async function openConversation(conversationId) {
  const document = await api(`/api/conversations/${encodeURIComponent(conversationId)}`);
  state.activeConversation = document.conversation_id;
  clearPendingAttachmentSelection();
  $("conversation-title").textContent = document.title;
  renderWorkspace(document.workspace);
  renderMessages(document.messages || []);
  await loadConversations($("conversation-search").value.trim());
  showSidebar(false);
}

async function renameConversation() {
  if (!state.activeConversation) return;
  const current = $("conversation-title").textContent;
  const title = window.prompt("Rename conversation", current);
  if (!title || !title.trim()) return;
  const document = await api(`/api/conversations/${state.activeConversation}/rename`, {
    method: "POST", body: JSON.stringify({ title }),
  });
  $("conversation-title").textContent = document.title;
  await loadConversations();
}

async function togglePin() {
  if (!state.activeConversation) return;
  const current = state.conversations.find((item) => item.conversation_id === state.activeConversation);
  await api(`/api/conversations/${state.activeConversation}/pin`, {
    method: "POST", body: JSON.stringify({ pinned: !(current && current.pinned) }),
  });
  await loadConversations();
}

async function branchConversation() {
  if (!state.activeConversation) return;
  const document = await api(`/api/conversations/${state.activeConversation}/branch`, {
    method: "POST", body: "{}",
  });
  await loadConversations();
  await openConversation(document.conversation_id);
}

async function deleteConversation() {
  if (!state.activeConversation) return;
  if (!window.confirm("Delete this conversation? This is the only action that forgets it.")) return;
  await api(`/api/conversations/${state.activeConversation}`, { method: "DELETE" });
  state.activeConversation = null;
  $("conversation-title").textContent = "New chat";
  renderMessages([]);
  await loadConversations();
}

function renderInlineText(text, parent) {
  const pieces = String(text).split(/(`[^`]+`)/g);
  for (const piece of pieces) {
    if (piece.startsWith("`") && piece.endsWith("`") && piece.length > 1) {
      const code = document.createElement("code");
      code.className = "inline-code";
      code.textContent = piece.slice(1, -1);
      parent.append(code);
    } else {
      parent.append(document.createTextNode(piece));
    }
  }
}

function appendTextBlock(container, line) {
  const heading = line.match(/^(#{1,3})\s+(.+)/);
  if (heading) {
    const element = document.createElement(`h${heading[1].length}`);
    renderInlineText(heading[2], element);
    container.append(element);
    return;
  }
  const paragraph = document.createElement("p");
  renderInlineText(line, paragraph);
  container.append(paragraph);
}

function renderRichText(text) {
  const container = document.createElement("div");
  container.className = "rich-text";
  const sections = String(text || "").split("```");
  sections.forEach((section, index) => {
    if (index % 2 === 1) {
      const lines = section.replace(/^\n/, "").split("\n");
      const maybeLanguage = (lines[0] || "").trim();
      const language = /^[a-z0-9_+.-]{1,18}$/i.test(maybeLanguage) ? lines.shift() : "code";
      const block = document.createElement("div");
      block.className = "code-block";
      const header = document.createElement("div");
      header.className = "code-header";
      const label = document.createElement("span");
      label.textContent = language || "code";
      const copy = document.createElement("button");
      copy.type = "button";
      copy.textContent = "Copy";
      const codeText = lines.join("\n").replace(/\n$/, "");
      copy.addEventListener("click", () => copyText(codeText));
      header.append(label, copy);
      const pre = document.createElement("pre");
      pre.textContent = codeText;
      block.append(header, pre);
      container.append(block);
      return;
    }

    let list = null;
    for (const rawLine of section.split("\n")) {
      const line = rawLine.trimEnd();
      if (!line.trim()) { list = null; continue; }
      const item = line.match(/^\s*[-*]\s+(.+)/);
      if (item) {
        if (!list) { list = document.createElement("ul"); container.append(list); }
        const li = document.createElement("li");
        renderInlineText(item[1], li);
        list.append(li);
      } else {
        list = null;
        appendTextBlock(container, line);
      }
    }
  });
  return container;
}

function messageRow(message) {
  const row = document.createElement("article");
  row.className = `message-row ${message.role === "user" ? "user" : "assistant"}`;
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.append(renderRichText(message.content || ""));

  const actions = document.createElement("div");
  actions.className = "message-actions";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.textContent = "Copy";
  copy.addEventListener("click", () => copyText(message.content || ""));
  actions.append(copy);
  bubble.append(actions);
  row.append(bubble);
  return row;
}

function renderMessages(messages) {
  const list = $("messages");
  list.replaceChildren();
  for (const message of messages || []) {
    if (message.role === "user" || message.role === "assistant") list.append(messageRow(message));
  }
  $("welcome").hidden = Boolean((messages || []).length);
  requestAnimationFrame(() => { $("transcript").scrollTop = $("transcript").scrollHeight; });
}

function appendMessage(role, content) {
  $("welcome").hidden = true;
  $("messages").append(messageRow({ role, content }));
  requestAnimationFrame(() => { $("transcript").scrollTop = $("transcript").scrollHeight; });
}

function autoGrowComposer() {
  const prompt = $("prompt");
  prompt.style.height = "auto";
  prompt.style.height = `${Math.min(prompt.scrollHeight, 190)}px`;
}

function renderAttachmentChips() {
  const list = $("attachment-list");
  list.replaceChildren();
  for (const record of state.pendingAttachments) {
    const chip = document.createElement("span");
    chip.className = "attachment-chip";
    const name = document.createElement("span");
    name.textContent = record.original_name || "Attachment";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${record.original_name || "attachment"}`);
    remove.textContent = "?";
    remove.addEventListener("click", () => removeAttachment(record.attachment_id));
    chip.append(name, remove);
    list.append(chip);
  }
}

async function fileToBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const parts = [];
  for (let index = 0; index < bytes.length; index += 0x8000) {
    parts.push(String.fromCharCode(...bytes.subarray(index, index + 0x8000)));
  }
  return btoa(parts.join(""));
}

async function uploadAttachments(files) {
  const selected = Array.from(files || []);
  if (!selected.length) return;
  if (!state.activeConversation) await createConversation();
  if (state.clientMode === "mobile") {
    $("capability-label").textContent = "Attach files from the desktop for now";
    return;
  }
  for (const file of selected) {
    const data = await fileToBase64(file);
    const record = await api(`/api/conversations/${encodeURIComponent(state.activeConversation)}/attachments`, {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        data,
      }),
    });
    state.pendingAttachments.push(record);
    state.pendingAttachmentIds.push(record.attachment_id);
  }
  renderAttachmentChips();
}

async function removeAttachment(attachmentId) {
  const id = String(attachmentId || "").trim();
  if (!id || !state.activeConversation) return;
  await api(`/api/conversations/${encodeURIComponent(state.activeConversation)}/attachments/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  state.pendingAttachments = state.pendingAttachments.filter((item) => item.attachment_id !== id);
  state.pendingAttachmentIds = state.pendingAttachmentIds.filter((item) => item !== id);
  renderAttachmentChips();
}

function clearPendingAttachmentSelection() {
  state.pendingAttachments = [];
  state.pendingAttachmentIds = [];
  renderAttachmentChips();
}

function appendInlineAction(node) {
  if (!node) return;
  const last = $("messages").lastElementChild;
  const bubble = last && last.querySelector(".message-bubble");
  if (bubble) bubble.append(node);
}

function renderSuggestedAction(details) {
  const action = String(details?.suggested_action || "").trim();
  if (!action) return null;
  const card = document.createElement("div");
  card.className = "inline-action-card";
  const message = document.createElement("span");
  message.textContent = details?.needs_context?.message || "I need one more thing to continue.";
  const button = document.createElement("button");
  button.type = "button";
  if (action === "choose_workspace") {
    button.textContent = "Choose project";
    button.addEventListener("click", async () => {
      await chooseWorkspace();
      if (state.workspace && state.lastSubmittedText) await retryLastRequest();
    });
  } else {
    button.textContent = "Continue";
    button.disabled = true;
  }
  card.append(message, button);
  return card;
}

async function submitConfirmation(actionToken) {
  const token = String(actionToken || "").trim();
  if (!token) return;
  const result = await api("/api/confirmations", {
    method: "POST",
    body: JSON.stringify({ action_token: token }),
  });
  if (result?.message) appendMessage("assistant", result.message);
  renderResult(result);
}

function renderConfirmation(details) {
  const confirmation = details?.confirmation;
  const token = String(confirmation?.action_token || "").trim();
  if (!confirmation || !token) return null;
  const card = document.createElement("div");
  card.className = "inline-action-card confirmation-card";
  const copy = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = confirmation.title || "Confirm this action";
  const consequence = document.createElement("p");
  consequence.textContent = confirmation.consequence || "ChatMPD needs your approval before continuing.";
  copy.append(title, consequence);
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = confirmation.confirm_label || "Allow";
  button.addEventListener("click", () => submitConfirmation(token));
  card.append(copy, button);
  return card;
}

async function retryLastRequest() {
  if (state.activeJob || !state.lastSubmittedText) return;
  $("prompt").value = state.lastSubmittedText;
  autoGrowComposer();
  await submitPrompt();
}

function renderRetryAction() {
  if (!state.lastSubmittedText) return null;
  const card = document.createElement("div");
  card.className = "inline-action-card";
  const label = document.createElement("span");
  label.textContent = "You can try that request again.";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Retry";
  button.addEventListener("click", retryLastRequest);
  card.append(label, button);
  return card;
}

async function submitMobileCommand(text) {
  const payload = { text, conversation_id: state.activeConversation };
  if (state.workspace) payload.workspace = state.workspace;
  if (state.pendingAttachmentIds.length) payload.attachment_ids = [...state.pendingAttachmentIds];
  state.activeJob = "mobile-request";
  setBusy(true, "Working locally");
  try {
    const result = await api("/api/command", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.activeJob = null;
    setBusy(false, result.capability || "Ready");
    await openConversation(state.activeConversation);
    renderResult(result);
  } catch (error) {
    state.activeJob = null;
    setBusy(false, "Needs attention");
    appendMessage("assistant", `I couldn't complete that task: ${error.message}`);
  }
}

async function submitPrompt(event) {
  if (event) event.preventDefault();
  if (state.activeJob) return;
  const text = $("prompt").value.trim();
  if (!text) return;
  state.lastSubmittedText = text;
  if (!state.activeConversation) await createConversation();

  appendMessage("user", text);
  $("prompt").value = "";
  autoGrowComposer();
  if (state.clientMode === "mobile") {
    await submitMobileCommand(text);
    return;
  }
  setBusy(true, "Routing locally");
  try {
    const payload = { text, conversation_id: state.activeConversation };
    if (state.workspace) payload.workspace = state.workspace;
    if (state.pendingAttachmentIds.length) payload.attachment_ids = [...state.pendingAttachmentIds];
    const accepted = await api("/api/jobs", {
      method: "POST", body: JSON.stringify(payload),
    });
    state.activeJob = accepted.job_id;
    pollJob(accepted.job_id);
  } catch (error) {
    setBusy(false, "Needs attention");
    appendMessage("assistant", `I couldn't start that task: ${error.message}`);
  }
}

async function pollJob(jobId) {
  if (state.activeJob !== jobId) return;
  try {
    const job = await api(`/api/jobs/${jobId}`);
    if (["queued", "running", "cancelling"].includes(job.status)) {
      setBusy(true, job.status_label || "Working on it");
      setTimeout(() => pollJob(jobId), 500);
      return;
    }
    state.activeJob = null;
    setBusy(false, job.status === "completed" ? (job.result.capability || "Ready") : "Ready");
    if (job.status === "completed") {
      await openConversation(job.conversation_id);
      renderResult(job.result);
    } else if (job.status === "cancelled") {
      appendMessage("assistant", "Stopped. No success was reported for the cancelled task.");
    } else {
      appendMessage("assistant", `I couldn't complete that task: ${job.error || "Unknown error"}`);
      appendInlineAction(renderRetryAction());
    }
    await loadConversations();
  } catch (error) {
    state.activeJob = null;
    setBusy(false, "Connection error");
    appendMessage("assistant", `The local UI lost the job status: ${error.message}`);
    appendInlineAction(renderRetryAction());
  }
}

async function cancelActiveJob() {
  if (!state.activeJob) return;
  const jobId = state.activeJob;
  try {
    await api(`/api/jobs/${jobId}/cancel`, { method: "POST", body: "{}" });
    $("capability-label").textContent = "Stopping safely";
  } catch (error) {
    $("capability-label").textContent = `Stop failed: ${error.message}`;
  }
}

function addDetailRow(container, labelText, valueText) {
  const row = document.createElement("div");
  const label = document.createElement("strong");
  label.textContent = labelText;
  const value = document.createElement("span");
  value.textContent = String(valueText);
  row.append(label, document.createTextNode(" "), value);
  container.append(row);
}

function renderResult(result) {
  if (!result) return;
  const details = result.details || {};
  appendInlineAction(renderSuggestedAction(details));
  appendInlineAction(renderConfirmation(details));
  if (!Object.keys(details).length) return;
  const wrapper = document.createElement("details");
  wrapper.className = "details-toggle";
  const summary = document.createElement("summary");
  summary.textContent = "Activity and verification";
  const grid = document.createElement("div");
  grid.className = "details-grid";
  if (details.status) addDetailRow(grid, "Status", details.status);
  if (Array.isArray(details.changed_files) && details.changed_files.length) addDetailRow(grid, "Changed", details.changed_files.join(", "));
  if (Array.isArray(details.checks) && details.checks.length) addDetailRow(grid, "Checks", `${details.checks.length} verification check(s)`);
  wrapper.append(summary, grid);
  const last = $("messages").lastElementChild;
  const bubble = last && last.querySelector(".message-bubble");
  if (bubble) bubble.append(wrapper);
}

async function chooseWorkspace() {
  if (!state.activeConversation) await createConversation();
  if (state.clientMode === "mobile") {
    $("capability-label").textContent = "Choose the project once on the desktop PC";
    return;
  }
  const selection = await api("/api/system/select-folder", { method: "POST", body: "{}" });
  const workspace = String(selection.path || "").trim();
  if (!workspace) return;
  const document = await api(`/api/conversations/${state.activeConversation}/workspace`, {
    method: "POST", body: JSON.stringify({ workspace }),
  });
  renderWorkspace(document.workspace);
}

function showConversationActions() {
  if (!state.activeConversation) return;
  document.querySelector(".action-popover")?.remove();
  const menu = document.createElement("div");
  menu.className = "action-popover";
  const actions = [
    ["Rename", renameConversation],
    ["Pin / unpin", togglePin],
    ["Branch", branchConversation],
    ["Delete", deleteConversation],
  ];
  for (const [label, handler] of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", async () => { menu.remove(); await handler(); });
    menu.append(button);
  }
  $("conversation-menu").after(menu);
  setTimeout(() => document.addEventListener("click", () => menu.remove(), { once: true }), 0);
}

function openArtifact(title, node) {
  $("artifact-title").textContent = title || "Result";
  $("artifact-content").replaceChildren(node);
  $("artifact-pane").hidden = false;
}

function renderMobileSession(session) {
  state.mobile = session;
  $("mobile-off").hidden = Boolean(session);
  $("mobile-on").hidden = !session;
  if (!session) return;
  $("setup-link").value = session.setup_url || "";
  $("pairing-code-label").textContent = session.pairing_code ? `Pairing code: ${session.pairing_code}` : "";
  const qr = $("qr-box");
  qr.replaceChildren();
  if (session.qr_url) {
    const image = document.createElement("img");
    image.src = session.qr_url;
    image.alt = "QR code for ChatMPD mobile setup";
    image.width = 220;
    image.height = 220;
    qr.append(image);
  } else {
    qr.textContent = "QR code unavailable — use Copy setup link.";
  }
}

async function startMobileAccess() {
  try {
    const session = await api("/api/mobile/start", { method: "POST", body: "{}" });
    renderMobileSession(session);
  } catch (error) {
    $("qr-box").textContent = error.message;
  }
}

async function stopMobileAccess() {
  try { await api("/api/mobile/stop", { method: "POST", body: "{}" }); }
  finally { renderMobileSession(null); }
}

async function refreshMobileStatus() {
  try {
    const session = await api("/api/mobile/status");
    renderMobileSession(session.active ? session : null);
  } catch (_) {
    renderMobileSession(null);
  }
}

const CONTROL_TITLES = {
  overview: ["Overview", "Local ChatMPD platform"],
  memory: ["Memory", "Durable facts and preferences"],
  knowledge: ["Knowledge", "Local documents and retrieval"],
  capabilities: ["Skills & Tools", "Built-ins, extensions, packs, and mod sources"],
  models: ["Models", "Local models, LM Studio, and Bionic"],
  performance: ["Performance", "Analyze and optimize this PC with reversible profiles"],
  workflows: ["Workflows", "Reusable local commands"],
  automations: ["Automations", "Recurring and conditional local tasks"],
  recovery: ["Recovery", "Reversible snapshots and rollback"],
  prompts: ["Prompt Guide", "Goal → Context → Constraints → Result → Verification"],
  diagnostics: ["Diagnostics", "Health checks and safe self-repair"],
  sharing: ["Sharing", "Sanitized generic ChatMPD packages"],
};

function controlNode(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function controlCard(title, detail = "") {
  const card = controlNode("section", "", "control-item");
  card.append(controlNode("strong", title));
  if (detail) card.append(controlNode("p", detail));
  return card;
}
function controlInput(placeholder, value = "") {
  const input = document.createElement("input");
  input.placeholder = placeholder;
  input.value = value;
  input.autocomplete = "off";
  return input;
}

function controlAction(label, handler, className = "") {
  const button = controlNode("button", label, className);
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await handler(); }
    catch (error) { showControlError(error); }
    finally { button.disabled = false; }
  });
  return button;
}

function showControlError(error) {
  const content = $("control-content");
  const box = controlNode("div", `Error: ${error.message || error}`, "control-error");
  content.prepend(box);
}

function renderControlCards(cards) {
  const content = $("control-content");
  content.replaceChildren(...cards);
}
async function renderOverviewSection() {
  const summary = await api("/api/platform/summary");
  const cards = [];
  cards.push(controlCard("Local-first", "Unlimited local use; no ChatMPD token billing or mandatory paid API."));
  cards.push(controlCard("Hardware", `${summary.hardware?.gpu_name || "GPU unknown"} · ${summary.hardware?.memory_total_gib || "?"} GiB RAM · ${summary.recommended_model_tier || "auto"} tier`));
  cards.push(controlCard("Memory", `${summary.memory_count || 0} durable memories · ${summary.knowledge_count || 0} knowledge sources`));
  cards.push(controlCard("Extensions", `${summary.capability_count || 0} registered capabilities · ${summary.extension_count || 0} extensions`));
  const local = summary.lm_studio || {};
  cards.push(controlCard("LM Studio / Bionic", `${local.available ? "LM Studio runtime available" : "LM Studio runtime not found"} · Bionic ${summary.bionic?.installed ? "installed" : "not installed"}`));
  const media = controlCard("Local media & voice", `Voice transcription: ${summary.voice?.ready ? "ready" : "optional local model missing"} · Vision: ${summary.vision?.ready ? "ready" : "optional local model missing"}`);
  cards.push(media);
  renderControlCards(cards);
}

async function renderMemorySection() {
  const items = await api("/api/platform/memory");
  const cards = [];
  const add = controlCard("Add memory", "Store a durable fact or preference. Chats themselves already persist separately.");
  const input = controlInput("What should ChatMPD remember?");
  add.append(input, controlAction("Remember", async () => {
    if (!input.value.trim()) return;
    await api("/api/platform/memory", { method: "POST", body: JSON.stringify({ content: input.value.trim(), kind: "fact", source: "control-center" }) });
    await loadControlSection("memory");
  }, "primary-button"));
  cards.push(add);
  for (const item of items) {
    const card = controlCard(item.kind || "Memory", item.content || "");
    const meta = controlNode("small", `${item.pinned ? "Pinned · " : ""}${item.source || "local"}`);
    card.append(meta, controlAction("Delete", async () => {
      if (!window.confirm("Delete this durable memory?")) return;
      await api(`/api/platform/memory/${encodeURIComponent(item.memory_id)}`, { method: "DELETE" });
      await loadControlSection("memory");
    }, "danger-text"));
    cards.push(card);
  }
  renderControlCards(cards);
}

async function renderKnowledgeSection() {
  const items = await api("/api/platform/knowledge");
  const cards = [];
  const add = controlCard("Add local knowledge", "Index a local text, PDF, DOCX, CSV, JSON, code, or spreadsheet file for retrieval.");
  const input = controlInput("Full path to a local file");
  add.append(input, controlAction("Index file", async () => {
    if (!input.value.trim()) return;
    await api("/api/platform/knowledge", { method: "POST", body: JSON.stringify({ path: input.value.trim() }) });
    await loadControlSection("knowledge");
  }, "primary-button"));
  cards.push(add);
  for (const item of items) {
    cards.push(controlCard(item.title || "Knowledge source", `${item.path || ""}\nSHA-256: ${item.sha256 || ""}`));
  }
  renderControlCards(cards);
}
async function renderCapabilitiesSection() {
  const [items, packs, extensions, sources, civitai] = await Promise.all([
    api("/api/platform/capabilities"), api("/api/platform/packs"),
    api("/api/platform/extensions"), api("/api/platform/mod-sources"),
    api("/api/platform/civitai"),
  ]);
  const cards = [];
  const sourceCard = controlCard("Mod repositories", `ESOUI: ${sources.esoui?.catalog || "not configured"}\nNexus Mods: ${sources.nexus?.site || "not configured"}`);
  sourceCard.append(controlNode("small", sources.nexus?.api_key_configured ? "Nexus API key configured" : "Nexus API key optional and not configured"));
  cards.push(sourceCard);
  const civitaiCard = controlCard("Civitai MCP",
    `${civitai.endpoint || "https://mcp.civitai.com/mcp"} · anonymous browse ${civitai.browse_anonymous ? "enabled" : "unavailable"}`);
  civitaiCard.append(controlNode("small", civitai.api_key_configured
    ? "Civitai API key stored in the Windows-protected vault"
    : "Civitai API key optional; required only for account/write actions"));
  const civitaiKey = controlInput("Optional Civitai API key");
  civitaiKey.type = "password";
  civitaiKey.autocomplete = "new-password";
  civitaiCard.append(civitaiKey, controlAction("Save Civitai key", async () => {
    if (!civitaiKey.value.trim()) return;
    if (!window.confirm("Store this Civitai API key in ChatMPD's Windows-protected vault?")) return;
    await api("/api/platform/secrets/civitai-api-key", { method: "POST", body: JSON.stringify({ value: civitaiKey.value.trim(), confirmed: true }) });
    civitaiKey.value = "";
    await loadControlSection("capabilities");
  }));
  civitaiCard.append(controlAction("List Civitai tools", async () => {
    const result = await api("/api/platform/civitai/tools", { method: "POST", body: "{}" });
    const names = (result.tools || []).slice(0, 80).map((tool) =>
      `${tool.name || "unnamed"}${tool.annotations?.readOnlyHint === true ? " · read-only" : " · confirmation-gated"}`
    ).join("\n");
    civitaiCard.append(controlNode("pre", names || "No tools returned.", "control-prompt-output"));
  }, "primary-button"));
  cards.push(civitaiCard);
  for (const pack of packs) {
    const card = controlCard(pack.name, pack.description || pack.pack_id);
    card.append(controlAction(pack.installed ? "Uninstall pack" : "Install pack", async () => {
      const action = pack.installed ? "uninstall" : "install";
      await api(`/api/platform/packs/${encodeURIComponent(pack.pack_id)}/${action}`, { method: "POST", body: "{}" });
      await loadControlSection("capabilities");
    }));
    cards.push(card);
  }
  for (const item of items) cards.push(controlCard(item.title || item.capability_id, `${item.kind} · ${item.health} · risk ${item.risk}`));
  for (const item of extensions) {
    if (!items.some((existing) => existing.capability_id === item.capability_id)) {
      cards.push(controlCard(item.title || item.capability_id, `Extension · ${item.health}`));
    }
  }
  renderControlCards(cards);
}

async function renderModelsSection() {
  const [modelData, lm, bionic] = await Promise.all([
    api("/api/platform/models"), api("/api/platform/lmstudio"), api("/api/platform/bionic"),
  ]);
  const cards = [];
  const local = controlCard("LM Studio", lm.available ? `${lm.source || "local"} · ${lm.executable || "runtime detected"}` : "Not detected as a standalone runtime.");
  cards.push(local);
  const bionicCard = controlCard("Bionic", bionic.installed ? `Installed: ${bionic.executable}` : "Not installed");
  if (bionic.installed) bionicCard.append(controlAction("Open Bionic", async () => {
    await api("/api/platform/bionic/open", { method: "POST", body: "{}" });
  }));
  cards.push(bionicCard);
  for (const model of modelData.models || []) {
    cards.push(controlCard(model.name, `${model.family || "local"} · ${(model.roles || []).join(", ")} · ${model.parameter_billions || "?"}B`));
  }
  for (const bench of modelData.benchmarks || []) {
    cards.push(controlCard(`Benchmark: ${String(bench.model_path || "").split(/[\\/]/).pop()}`, `${bench.role} · ${bench.tokens_per_second} tok/s · quality ${bench.quality_score}`));
  }
  renderControlCards(cards);
}

async function renderPerformanceSection() {
  const data = await api("/api/platform/performance");
  const status = data.status || {};
  const latest = data.latest || null;
  const cards = [];
  const modeCard = controlCard(
    "Performance mode",
    `${status.active_mode || "balanced"} · power plan ${status.current_power_plan_name || "unknown"}`
  );
  const actions = controlNode("div", "", "control-actions");
  actions.append(controlAction("Optimize for current workload", async () => {
    await api("/api/platform/performance/optimize", { method: "POST", body: "{}" });
    await loadControlSection("performance");
  }, "primary-button"));
  actions.append(controlAction("Analyze only", async () => {
    await api("/api/platform/performance/analyze", { method: "POST", body: "{}" });
    await loadControlSection("performance");
  }));
  for (const mode of ["balanced", "gaming", "ai"]) {
    actions.append(controlAction(mode === "ai" ? "AI / ChatMPD" : mode[0].toUpperCase() + mode.slice(1), async () => {
      await api("/api/platform/performance/apply", {
        method: "POST", body: JSON.stringify({ mode }),
      });
      await loadControlSection("performance");
    }));
  }
  actions.append(controlAction("Restore baseline", async () => {
    await api("/api/platform/performance/restore", { method: "POST", body: "{}" });
    await loadControlSection("performance");
  }));
  modeCard.append(actions);
  modeCard.append(controlAction(
    status.adaptive_enabled ? "Disable adaptive" : "Enable adaptive",
    async () => {
      await api("/api/platform/performance/adaptive", {
        method: "POST",
        body: JSON.stringify({
          enabled: !status.adaptive_enabled,
          base_mode: status.active_mode === "ai" ? "ai" : "balanced",
        }),
      });
      await loadControlSection("performance");
    }
  ));
  modeCard.append(controlNode("small",
    "Profiles change only reversible Windows power/runtime coordination. Security, firmware, disks, and unrelated apps are never altered here."));
  cards.push(modeCard);

  if (status.last_optimization) {
    const comparison = status.last_optimization;
    const delta = Number(comparison.score_delta || 0);
    const sign = delta > 0 ? "+" : "";
    cards.push(controlCard(
      "Last optimization",
      `${comparison.mode || "profile"} · headroom ${comparison.before_score ?? "?"} → ${comparison.after_score ?? "?"} (${sign}${delta})`
    ));
  }

  if (latest) {
    const scores = controlNode("div", "", "performance-score-grid");
    for (const [label, value] of [
      ["Overall", latest.overall_score], ["Gaming", latest.gaming_score],
      ["AI", latest.ai_score], ["Balanced", latest.balanced_score],
    ]) {
      const card = controlCard(label);
      card.classList.add("performance-score-card");
      card.append(controlNode("div", `${value ?? "?"}/100`, "score-value"));
      scores.append(card);
    }
    const bottleneckLabels = {
      none: "No active bottleneck", cpu: "CPU", memory: "RAM",
      commit: "Memory commit", disk: "Storage", gpu: "GPU",
      vram: "VRAM", unknown: "Unknown",
    };
    const scoreWrap = controlCard(
      bottleneckLabels[latest.bottleneck] || `Bottleneck: ${latest.bottleneck || "unknown"}`,
      `Telemetry confidence ${Math.round((latest.telemetry_confidence || 0) * 100)}% · Scores measure available headroom, not FPS or synthetic benchmark speed.`
    );
    scoreWrap.append(scores);
    cards.push(scoreWrap);
    const recommendations = latest.recommendations || [];
    for (const recommendation of recommendations) {
      const card = controlCard(
        `${String(recommendation.priority || "info").toUpperCase()} · ${recommendation.title || "Recommendation"}`,
        recommendation.detail || ""
      );
      if (recommendation.action_mode) {
        card.append(controlAction(`Apply ${recommendation.action_mode === "ai" ? "AI / ChatMPD" : recommendation.action_mode} mode`, async () => {
          await api("/api/platform/performance/apply", {
            method: "POST", body: JSON.stringify({ mode: recommendation.action_mode }),
          });
          await loadControlSection("performance");
        }));
      }
      cards.push(card);
    }
  }
  if (latest?.evidence) {
    const evidence = latest.evidence;
    const gpu = evidence.gpu || {};
    cards.push(controlCard("Live evidence",
      `CPU ${Math.round(evidence.cpu_percent || 0)}% · RAM ${Math.round(100 * (1 - (evidence.memory_available_bytes || 0) / Math.max(1, evidence.memory_total_bytes || 1)))}% used · ` +
      `Commit ${Number(evidence.commit_percent || 0).toFixed(0)}% · Pagefile ${Number(evidence.pagefile_percent || 0).toFixed(0)}% · ` +
      `Disk ${Number(evidence.disk_active_percent || 0).toFixed(0)}% active / queue ${Number(evidence.disk_queue_length || 0).toFixed(1)} / ${Number((evidence.disk_bytes_per_sec || 0) / 1048576).toFixed(1)} MiB/s · ` +
      `GPU ${gpu.utilization_percent ?? "?"}% · VRAM ${gpu.vram_used_mib ?? "?"}/${gpu.vram_total_mib ?? "?"} MiB · ` +
      `Power ${evidence.power_plan_name || "unknown"} · ` +
      `Workloads ${(evidence.workloads || []).join(", ") || "general desktop"}`));
    const gamingConfig = evidence.gaming_config || {};
    const diskHealth = Array.isArray(evidence.disk_health) && evidence.disk_health.length
      ? evidence.disk_health.join("\n") : "No physical-disk health warning reported";
    cards.push(controlCard("Windows performance context",
      `Game Mode ${gamingConfig.game_mode || "default"} · HAGS ${gamingConfig.hags || "default"} · startup entries ${evidence.startup_count ?? "?"}\n${diskHealth}`));
    for (const finding of latest.findings || []) {
      cards.push(controlCard(`${String(finding.severity || "info").toUpperCase()} · ${finding.key}`, finding.summary || ""));
    }
    const competitors = latest.top_processes || [];
    if (competitors.length) {
      const text = competitors.slice(0, 8).map((item) =>
        `${item.name} (PID ${item.pid}) · CPU ${Number(item.cpu_percent || 0).toFixed(1)}% · RAM ${Math.round((item.memory_bytes || 0) / 1048576)} MiB · I/O ${Number((item.io_bytes_per_sec || 0) / 1048576).toFixed(1)} MiB/s`
      ).join("\n");
      cards.push(controlCard("Top competing processes", text));
    }
  } else {
    cards.push(controlCard("No baseline yet", "Run Analyze to measure this PC without changing anything."));
  }

  for (const item of (data.history || []).slice(1, 6)) {
    cards.push(controlCard(`Previous analysis · ${item.overall_score}/100`,
      `${item.created_at} · bottleneck ${item.bottleneck}`));
  }
  renderControlCards(cards);
}

async function renderWorkflowsSection() {
  const items = await api("/api/platform/workflows");
  const cards = [];
  const create = controlCard("Save workflow", "Reuse a successful natural-language command.");
  const name = controlInput("Workflow name");
  const command = controlInput("Command to run");
  create.append(name, command, controlAction("Save workflow", async () => {
    await api("/api/platform/workflows", { method: "POST", body: JSON.stringify({ name: name.value, command: command.value, workspace: state.workspace || null }) });
    await loadControlSection("workflows");
  }, "primary-button"));
  cards.push(create);
  for (const item of items) {
    const card = controlCard(item.name, item.command);
    card.append(controlAction("Run", async () => {
      const result = await api(`/api/platform/workflows/${encodeURIComponent(item.workflow_id)}/run`, { method: "POST", body: "{}" });
      $("control-dialog").close();
      appendMessage("assistant", result.message || "Workflow completed.");
      renderResult(result);
    }, "primary-button"));
    cards.push(card);
  }
  renderControlCards(cards);
}
async function renderAutomationsSection() {
  const items = await api("/api/platform/automations");
  const cards = [];
  const create = controlCard("Create automation", "Minimum interval is 60 seconds. Runs stay local.");
  const name = controlInput("Automation name");
  const command = controlInput("Command");
  const interval = controlInput("Interval seconds", "3600");
  const condition = controlInput("Optional result text condition");
  create.append(name, command, interval, condition, controlAction("Create", async () => {
    await api("/api/platform/automations", { method: "POST", body: JSON.stringify({
      name: name.value, command: command.value,
      interval_seconds: Number(interval.value || 3600),
      condition_contains: condition.value.trim() || null,
    }) });
    await loadControlSection("automations");
  }, "primary-button"));
  cards.push(create);
  for (const item of items) {
    const card = controlCard(item.name, `${item.command} · next ${item.next_run}`);
    card.append(controlAction(item.enabled ? "Disable" : "Enable", async () => {
      await api(`/api/platform/automations/${encodeURIComponent(item.automation_id)}/enabled`, { method: "POST", body: JSON.stringify({ enabled: !item.enabled }) });
      await loadControlSection("automations");
    }));
    card.append(controlAction("Delete", async () => {
      if (!window.confirm("Delete this automation?")) return;
      await api(`/api/platform/automations/${encodeURIComponent(item.automation_id)}`, { method: "DELETE" });
      await loadControlSection("automations");
    }, "danger-text"));
    cards.push(card);
  }
  renderControlCards(cards);
}
async function renderRecoverySection() {
  const items = await api("/api/platform/recovery");
  const cards = [controlCard("Recovery policy", "ChatMPD snapshots reversible files before managed changes. Rollback always requires explicit confirmation.")];
  for (const item of items) {
    const card = controlCard(item.label, `${item.created_at} · ${(item.entries || []).length} file(s)`);
    card.append(controlAction("Rollback", async () => {
      if (!window.confirm(`Restore snapshot '${item.label}'? Current target files will be replaced.`)) return;
      const result = await api(`/api/platform/recovery/${encodeURIComponent(item.snapshot_id)}/rollback`, { method: "POST", body: JSON.stringify({ confirmed: true }) });
      card.append(controlNode("small", `Restored ${(result.restored || []).length} file(s).`));
    }, "danger-text"));
    cards.push(card);
  }
  renderControlCards(cards);
}

async function renderPromptsSection() {
  const data = await api("/api/platform/prompts");
  const cards = [];
  const optimizer = controlCard("Improve a prompt", "You can still speak normally; this is optional for complex work.");
  const goal = controlInput("Goal");
  const context = controlInput("Context (optional)");
  const constraints = controlInput("Constraints, separated by ;");
  optimizer.append(goal, context, constraints, controlAction("Build optimized prompt", async () => {
    const result = await api("/api/platform/prompts", { method: "POST", body: JSON.stringify({
      goal: goal.value, context: context.value,
      constraints: constraints.value.split(";").map((x) => x.trim()).filter(Boolean),
    }) });
    const output = controlNode("pre", result.prompt || "", "control-prompt-output");
    optimizer.append(output, controlAction("Copy prompt", () => copyText(result.prompt || "")));
  }, "primary-button"));
  cards.push(optimizer);
  for (const [name, template] of Object.entries(data.templates || {})) {
    const card = controlCard(name, template);
    card.append(controlAction("Copy template", () => copyText(template)));
    cards.push(card);
  }
  renderControlCards(cards);
}
async function renderDiagnosticsSection() {
  const [doctor, voice, vision, activity] = await Promise.all([
    api("/api/platform/doctor"), api("/api/platform/voice"),
    api("/api/platform/vision"), api("/api/platform/activity"),
  ]);
  const cards = [];
  const head = controlCard("Platform Doctor", doctor.ready ? "All required platform checks are ready." : "One or more required checks need attention.");
  head.append(controlAction("Run safe repair", async () => {
    const result = await api("/api/platform/doctor/repair", { method: "POST", body: "{}" });
    head.append(controlNode("small", (result.actions || []).join(" · ") || "No repair was needed."));
  }, "primary-button"));
  cards.push(head);
  for (const check of doctor.checks || []) cards.push(controlCard(check.name, `${check.ready ? "Ready" : check.optional ? "Optional" : "Needs attention"} · ${check.detail}`));
  cards.push(controlCard("Voice", `TTS ${voice.tts || "unknown"} · transcription ${voice.transcription?.ready ? "ready" : "optional local Whisper not configured"}`));
  cards.push(controlCard("Vision", `${vision.mode || "local-only"} · ${vision.ready ? "ready" : "optional local vision model not configured"}`));
  for (const event of (activity || []).slice(0, 12)) cards.push(controlCard(`Activity · ${event.kind}`, `${event.summary} · ${event.created_at}`));
  renderControlCards(cards);
}

async function renderSharingSection() {
  const cards = [];
  const policy = controlCard("Generic shareable ChatMPD", "Exports use explicit include paths and exclude chats, durable memories, credentials, tokens, recovery data, machine secrets, and explicit-sex extensions.");
  const include = controlInput("Extension/skill folder or file to include");
  const destination = controlInput("Destination .chatmpdpack path");
  policy.append(include, destination, controlAction("Create sanitized pack", async () => {
    const result = await api("/api/platform/export", { method: "POST", body: JSON.stringify({
      include_paths: [include.value.trim()].filter(Boolean), destination: destination.value.trim() || undefined,
    }) });
    policy.append(controlNode("small", `Created: ${result.path}`), controlAction("Copy path", () => copyText(result.path)));
  }, "primary-button"));
  cards.push(policy);
  cards.push(controlCard("Unlimited local use", "No ChatMPD subscription, per-token billing, artificial quota, or mandatory paid API. Optional external services remain separately controlled by their providers."));
  renderControlCards(cards);
}
async function loadControlSection(section = "overview") {
  const key = CONTROL_TITLES[section] ? section : "overview";
  const [title, subtitle] = CONTROL_TITLES[key];
  $("control-section-title").textContent = title;
  $("control-section-subtitle").textContent = subtitle;
  $("control-content").replaceChildren(controlNode("p", "Loading local platform data…", "control-loading"));
  document.querySelectorAll("[data-control-section]").forEach((button) => {
    button.classList.toggle("active", button.dataset.controlSection === key);
  });
  try {
    const renderers = {
      overview: renderOverviewSection, memory: renderMemorySection,
      knowledge: renderKnowledgeSection, capabilities: renderCapabilitiesSection,
      models: renderModelsSection, performance: renderPerformanceSection, workflows: renderWorkflowsSection,
      automations: renderAutomationsSection, recovery: renderRecoverySection,
      prompts: renderPromptsSection, diagnostics: renderDiagnosticsSection,
      sharing: renderSharingSection,
    };
    await renderers[key]();
  } catch (error) {
    $("control-content").replaceChildren(controlNode("div", `Unable to load ${title}: ${error.message}`, "control-error"));
  }
}

async function openControlCenter(section = "overview") {
  const dialog = $("control-dialog");
  if (!dialog.open) dialog.showModal();
  await loadControlSection(section);
}


function bindEvents() {
  $("pair-device-button").addEventListener("click", pairDevice);
  $("control-center").addEventListener("click", () => openControlCenter("overview"));
  $("control-refresh").addEventListener("click", () => loadControlSection($("control-section-title").textContent.toLowerCase().replace("skills & tools", "capabilities").replace("prompt guide", "prompts")));
  document.querySelectorAll("[data-control-section]").forEach((button) => button.addEventListener("click", () => loadControlSection(button.dataset.controlSection)));
  $("new-chat").addEventListener("click", createConversation);
  $("composer").addEventListener("submit", submitPrompt);
  $("stop").addEventListener("click", cancelActiveJob);
  $("prompt").addEventListener("input", autoGrowComposer);
  $("prompt").addEventListener("keydown", (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submitPrompt(event);
    }
  });
  $("attachment-button").addEventListener("click", () => $("attachment-input").click());
  $("attachment-input").addEventListener("change", async (event) => {
    await uploadAttachments(event.target.files);
    event.target.value = "";
  });
  $("composer").addEventListener("dragover", (event) => {
    event.preventDefault();
    $("composer").classList.add("drag-active");
  });
  $("composer").addEventListener("dragleave", () => $("composer").classList.remove("drag-active"));
  $("composer").addEventListener("drop", async (event) => {
    event.preventDefault();
    $("composer").classList.remove("drag-active");
    await uploadAttachments(event.dataTransfer?.files || []);
  });
  document.querySelectorAll("[data-suggestion]").forEach((button) => {
    button.addEventListener("click", async () => {
      $("prompt").value = button.dataset.suggestion || button.textContent || "";
      autoGrowComposer();
      await submitPrompt();
    });
  });
  $("conversation-search").addEventListener("input", (event) => loadConversations(event.target.value.trim()));
  $("sidebar-toggle").addEventListener("click", () => showSidebar(!document.body.classList.contains("sidebar-open")));
  $("sidebar-close").addEventListener("click", () => showSidebar(false));
  $("sidebar-scrim").addEventListener("click", () => showSidebar(false));
  $("project-button").addEventListener("click", chooseWorkspace);
  $("conversation-menu").addEventListener("click", (event) => { event.stopPropagation(); showConversationActions(); });
  $("artifact-close").addEventListener("click", () => { $("artifact-pane").hidden = true; });
  $("mobile-access").addEventListener("click", () => { $("mobile-dialog").showModal(); refreshMobileStatus(); });
  $("mobile-start").addEventListener("click", startMobileAccess);
  $("mobile-stop").addEventListener("click", stopMobileAccess);
  $("copy-setup-link").addEventListener("click", () => copyText(state.mobile?.setup_url || ""));
  $("copy-address").addEventListener("click", () => copyText(state.mobile?.address || ""));
  $("copy-code").addEventListener("click", () => copyText(state.mobile?.pairing_code || ""));
  $("theme-button").addEventListener("click", () => $("theme-dialog").showModal());
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    button.addEventListener("click", () => { setTheme(button.dataset.themeChoice); $("theme-dialog").close(); });
  });
}

async function boot() {
  setTheme(localStorage.getItem("chatmpd-theme") || "system");
  bindEvents();
  autoGrowComposer();
  try {
    const client = await api("/api/client");
    state.clientMode = client.mode === "mobile" ? "mobile" : "desktop";
    const query = new URLSearchParams(window.location.search);
    const pairingCode = query.get("pair") || "";
    if (pairingCode) $("mobile-pair-code").value = pairingCode;
    if (state.clientMode === "mobile") {
      $("mobile-access").hidden = true;
      const token = localStorage.getItem(MOBILE_TOKEN_KEY) || "";
      if (!token) {
        $("mobile-pair-screen").hidden = false;
        $("app-shell").hidden = true;
        return;
      }
      await api("/api/status");
    }
    $("mobile-pair-screen").hidden = true;
    $("app-shell").hidden = false;
    await loadConversations();
    if (state.conversations.length) await openConversation(state.conversations[0].conversation_id);
  } catch (error) {
    if (state.clientMode === "mobile") {
      localStorage.removeItem(MOBILE_TOKEN_KEY);
      $("mobile-pair-screen").hidden = false;
      $("app-shell").hidden = true;
      $("pair-error").textContent = error.message;
      return;
    }
    $("runtime-label").textContent = `Local UI error: ${error.message}`;
    $("runtime-dot").style.background = "#c85151";
  }
}

document.addEventListener("DOMContentLoaded", boot);
