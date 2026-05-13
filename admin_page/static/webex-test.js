"use strict";

const RUNTIME_FIELDS = [
  { key: "webex_mock_mode", label: "Webex mock mode" },
  { key: "device_mock_mode", label: "Device mock mode" },
  { key: "default_execution_mode", label: "Default execution mode" },
  { key: "webex_api_base", label: "Webex API base" },
  { key: "webex_bot_person_id", label: "Bot person id" },
  { key: "webex_bot_token_present", label: "Bot token configured" },
  { key: "webex_webhook_secret_present", label: "Webhook secret configured" },
  { key: "webex_webhook_target_url", label: "Webhook target URL" },
  { key: "webex_webhook_reconcile_on_startup", label: "Reconcile on startup" },
  { key: "webex_token_manager_base_url", label: "Token manager base URL" },
  { key: "webex_token_manager_api_key_present", label: "Token manager key configured" },
  { key: "default_user_email", label: "Default user email" },
];

function setStatus(text, variant) {
  const pill = document.getElementById("page-status");
  if (!pill) return;
  pill.textContent = text;
  pill.className = "status-pill" + (variant ? " status-pill--" + variant : "");
}

function setInline(elementId, text, variant) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.textContent = text;
  el.className =
    "inline-message" + (variant ? " inline-message--" + variant : "");
}

function formatRuntimeValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "(empty)";
  return String(value);
}

function renderRuntime(payload) {
  const grid = document.getElementById("runtime-grid");
  if (!grid) return;
  grid.innerHTML = "";
  for (const field of RUNTIME_FIELDS) {
    const card = document.createElement("article");
    card.className = "field-card";
    const labelRow = document.createElement("span");
    labelRow.className = "field-card__label-row";
    const label = document.createElement("span");
    label.textContent = field.label;
    const state = document.createElement("span");
    state.className = "field-state field-state--live";
    state.textContent = "runtime";
    labelRow.appendChild(label);
    labelRow.appendChild(state);
    const value = document.createElement("strong");
    value.className = "mono";
    value.textContent = formatRuntimeValue(payload[field.key]);
    card.appendChild(labelRow);
    card.appendChild(value);
    grid.appendChild(card);
  }

  const allowed = payload.allowed_webex_user_emails;
  if (Array.isArray(allowed)) {
    const card = document.createElement("article");
    card.className = "field-card field-card--full";
    const labelRow = document.createElement("span");
    labelRow.className = "field-card__label-row";
    const label = document.createElement("span");
    label.textContent = "Allowed Webex user emails";
    const state = document.createElement("span");
    state.className = "field-state field-state--live";
    state.textContent = "runtime";
    labelRow.appendChild(label);
    labelRow.appendChild(state);
    const value = document.createElement("strong");
    value.className = "mono";
    value.textContent = allowed.length
      ? allowed.join(", ")
      : "(empty — all senders accepted)";
    card.appendChild(labelRow);
    card.appendChild(value);
    grid.appendChild(card);
  }

  const heroMock = document.getElementById("hero-mock-mode-status");
  if (heroMock) {
    heroMock.textContent = payload.webex_mock_mode
      ? "Webex transport is mocked. Safe to simulate."
      : "Real Webex transport — simulation disabled.";
  }
  const heroWebex = document.getElementById("hero-webex-mock");
  if (heroWebex) heroWebex.textContent = payload.webex_mock_mode ? "on" : "off";
  const heroDevice = document.getElementById("hero-device-mock");
  if (heroDevice)
    heroDevice.textContent = payload.device_mock_mode ? "on" : "off";
  const heroBot = document.getElementById("hero-bot-token");
  if (heroBot)
    heroBot.textContent = payload.webex_bot_token_present ? "set" : "unset";

  const submit = document.getElementById("simulate-submit");
  if (submit) {
    submit.disabled = !payload.webex_mock_mode;
    submit.title = payload.webex_mock_mode
      ? ""
      : "Simulation disabled while WEBEX_MOCK_MODE=false.";
  }
}

function showOutput(label, payload) {
  const pre = document.getElementById("output-pre");
  if (!pre) return;
  pre.classList.remove("empty-state");
  const stamp = new Date().toISOString();
  pre.textContent =
    "[" + stamp + "] " + label + "\n" + JSON.stringify(payload, null, 2);
}

async function loadRuntime() {
  setStatus("Loading…", "loading");
  try {
    const response = await fetch("/debug/webex/runtime", {
      headers: { Accept: "application/json" },
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.detail || "Runtime fetch failed.");
    }
    renderRuntime(data);
    setStatus("Ready", "ready");
    showOutput("GET /debug/webex/runtime", data);
  } catch (err) {
    setStatus("Error", "error");
    showOutput("GET /debug/webex/runtime (error)", {
      error: String(err && err.message ? err.message : err),
    });
  }
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  let payload;
  try {
    payload = await response.json();
  } catch (_err) {
    payload = { detail: "Non-JSON response", status: response.status };
  }
  return { ok: response.ok, status: response.status, payload };
}

function bindSimulateForm() {
  const form = document.getElementById("simulate-form");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setInline("sim-message", "Submitting…", null);
    const body = {
      text: document.getElementById("sim-text").value,
      room_id: document.getElementById("sim-room").value,
      person_id: document.getElementById("sim-person").value,
      person_email: document.getElementById("sim-email").value || null,
    };
    const result = await postJson("/debug/webex/simulate-message", body);
    if (result.ok) {
      setInline(
        "sim-message",
        "Accepted event " + (result.payload.event_id || "(unknown)") + ".",
        "success",
      );
    } else {
      setInline(
        "sim-message",
        "Failed: " + (result.payload.detail || result.status),
        "error",
      );
    }
    showOutput("POST /debug/webex/simulate-message", result.payload);
  });
}

function bindDebugForm() {
  const form = document.getElementById("debug-form");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setInline("debug-message", "Sending…", null);
    const mode = document.getElementById("debug-mode").value;
    const body = {
      text: document.getElementById("debug-text").value,
      session_id: document.getElementById("debug-session").value,
      room_id: "webex-test-room",
    };
    if (mode) body.preferred_mode = mode;
    const result = await postJson("/debug/messages", body);
    if (result.ok) {
      const replyText = result.payload?.reply?.text;
      setInline(
        "debug-message",
        replyText ? "Reply: " + replyText : "Reply received.",
        "success",
      );
    } else {
      setInline(
        "debug-message",
        "Failed: " + (result.payload.detail || result.status),
        "error",
      );
    }
    showOutput("POST /debug/messages", result.payload);
  });
}

function bindRefresh() {
  const button = document.getElementById("refresh-runtime");
  if (button) button.addEventListener("click", loadRuntime);
}

document.addEventListener("DOMContentLoaded", () => {
  bindSimulateForm();
  bindDebugForm();
  bindRefresh();
  loadRuntime();
});
