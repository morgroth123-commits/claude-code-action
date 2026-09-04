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

async function createConversation() {
  const document = await api("/api/conversations", { method: "POST", body: "{}" });
  state.activeConversation = document.conversation_id;
  $("conversation-title").textContent = document.title;
  renderMessages(document.messages || []);
  await loadConversations();
  $("prompt").focus();
  showSidebar(false);
  return document;
}

async function openConversation(conversationId) {
  const document = await api(`/api/conversations/${encodeURIComponent(conversationId)}`);
  state.activeConversation = document.conversation_id;
  $("conversation-title").textContent = document.title;
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

async function submitMobileCommand(text) {
  const payload = { text, conversation_id: state.activeConversation };
  if (state.workspace) payload.workspace = state.workspace;
  state.activeJob = "mobile-request";
  setBusy(true, "Working on Vader");
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
    }
    await loadConversations();
  } catch (error) {
    state.activeJob = null;
    setBusy(false, "Connection error");
    appendMessage("assistant", `The local UI lost the job status: ${error.message}`);
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
  if (!result || !result.details || !Object.keys(result.details).length) return;
  const details = result.details;
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

function chooseWorkspace() {
  const value = window.prompt("Project folder on Vader", state.workspace || "C:\\Users\\Owner\\Documents");
  if (value === null) return;
  state.workspace = value.trim();
  $("project-label").textContent = state.workspace || "Local on Vader";
  $("workspace-chip").textContent = state.workspace;
  $("workspace-chip").hidden = !state.workspace;
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

function bindEvents() {
  $("pair-device-button").addEventListener("click", pairDevice);
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
