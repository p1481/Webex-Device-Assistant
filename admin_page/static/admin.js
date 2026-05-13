const EXECUTION_MODES = [
  { value: "separated", label: "Separated mode" },
  { value: "all-llm", label: "All LLM mode" },
];

const RISK_LEVELS = ["read_only", "low", "high"];
const APPROVAL_STATES = ["not_required", "required", "approved", "rejected"];
const AUTH_STORAGE_KEY = "adminPageAuthSession";
const AUTH_POLL_INTERVAL_MS = 2500;

const state = {
  settings: null,
  providers: null,
  policies: null,
  actions: null,
  devices: null,
  approvals: null,
  audit: null,
  stats: null,
  auth: {
    sessionId: null,
    email: "",
    status: "signed_out",
    authenticated: false,
    pollTimer: null,
  },
};

function byId(id) {
  return document.getElementById(id);
}

function setPageStatus(text, variant) {
  const element = byId("page-status");
  element.textContent = text;
  element.className = `status-pill status-pill--${variant}`;
}

function createHttpError(status, detail) {
  const error = new Error(detail || `Request failed: ${status}`);
  error.status = status;
  return error;
}

async function requestJson(url, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(url, {
    ...options,
    headers,
  });

  const rawBody = await response.text();
  let parsedBody = null;
  if (rawBody) {
    try {
      parsedBody = JSON.parse(rawBody);
    } catch (_error) {
      parsedBody = null;
    }
  }

  if (!response.ok) {
    const detail = parsedBody && typeof parsedBody.detail === "string"
      ? parsedBody.detail
      : response.statusText;
    throw createHttpError(response.status, detail || `Request failed: ${response.status}`);
  }

  return parsedBody;
}

function formatLabel(value) {
  if (!value) {
    return "—";
  }
  return String(value)
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatBoolean(value) {
  if (value === null || value === undefined) {
    return "—";
  }
  return value ? "Yes" : "No";
}

function formatDate(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

function messageClass(variant) {
  if (variant === true || variant === "success") {
    return "inline-message inline-message--success";
  }
  if (variant === false || variant === "error") {
    return "inline-message inline-message--error";
  }
  return "inline-message inline-message--info";
}

function setInlineMessage(id, text, variant = "info") {
  const element = byId(id);
  element.textContent = text;
  element.className = messageClass(variant);
}

function clearInlineMessage(id) {
  const element = byId(id);
  element.textContent = "";
  element.className = "inline-message";
}

function fillSelectOptions(select, options, selectedValue, placeholder) {
  select.innerHTML = "";
  if (placeholder) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = placeholder;
    select.append(option);
  }
  options.forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.value;
    option.textContent = entry.label;
    if (entry.value === selectedValue) {
      option.selected = true;
    }
    select.append(option);
  });
}

function renderSecretFields(runtime, startup) {
  const container = byId("secret-fields");
  const requiredRestartFields = new Set(startup.required_restart_fields || []);
  const definitions = [
    {
      key: "access_token",
      label: "Access token",
      description: "Current Webex service-app access token is supplied by the token manager sidecar for org device and xAPI calls.",
      value: runtime.access_token,
    },
    {
      key: "bot_token",
      label: "Bot token",
      description: "Configured Webex bot token used for messaging, webhook lifecycle, and attachment actions.",
      value: runtime.bot_token,
    },
    {
      key: "webhook_secret",
      label: "Webhook secret",
      description: "Configured secret used to validate Webex webhook signatures.",
      value: runtime.webhook_secret,
    },
    {
      key: "webhook_url",
      label: "Webhook URL",
      description: "Startup webhook target value exposed by the backend.",
      value: {
        field_state: requiredRestartFields.has("webhook_url") ? "restart_required" : "read_only",
        masked_value: startup.webhook_url,
        present: Boolean(startup.webhook_url),
      },
    },
  ];

  container.innerHTML = "";
  definitions.forEach((item) => {
    const card = document.createElement("article");
    card.className = "field-card";
    const displayValue = item.value.present
      ? item.value.masked_value || "Configured"
      : item.value.masked_value || "Not configured";
    card.innerHTML = `
      <div class="field-card__label-row">
        <span>${item.label}</span>
        <span class="field-state field-state--${item.value.field_state}">${formatLabel(item.value.field_state)}</span>
      </div>
      <input type="text" value="${escapeHtml(displayValue)}" readonly />
      <small>${item.description}</small>
    `;
    container.append(card);
  });
}

function renderStartupStatus(startup) {
  const container = byId("startup-status-grid");
  const restartRequired = new Set(startup.required_restart_fields || []);
  const items = [
    {
      label: "Webhook URL",
      value: startup.webhook_url,
      fieldState: restartRequired.has("webhook_url") ? "restart_required" : "read_only",
    },
    {
      label: "Token manager base URL",
      value: startup.webex_token_manager_base_url,
      fieldState: "read_only",
    },
    {
      label: "Webex bot person ID",
      value: startup.webex_bot_person_id,
      fieldState: "read_only",
    },
    {
      label: "Webex mock mode",
      value: formatBoolean(startup.webex_mock_mode),
      fieldState: restartRequired.has("webex_mock_mode") ? "restart_required" : "read_only",
    },
    {
      label: "Device mock mode",
      value: formatBoolean(startup.device_mock_mode),
      fieldState: restartRequired.has("device_mock_mode") ? "restart_required" : "read_only",
    },
    {
      label: "Webhook reconcile on startup",
      value: formatBoolean(startup.reconcile_on_startup),
      fieldState: "read_only",
    },
  ];

  container.innerHTML = "";
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "field-card";
    card.innerHTML = `
      <div class="field-card__label-row">
        <span>${item.label}</span>
        <span class="field-state field-state--${item.fieldState}">${formatLabel(item.fieldState)}</span>
      </div>
      <input type="text" value="${escapeHtml(item.value || "—")}" readonly />
    `;
    container.append(card);
  });
}

function renderSettings(settingsPayload) {
  state.settings = settingsPayload;
  const runtime = settingsPayload.runtime;
  const startup = settingsPayload.startup;
  byId("default-admin-user").textContent = runtime.default_user_email || "youngcle@cisco.com";
  byId("default-space-id").value = runtime.default_space_id || "";
  byId("default-space-title").value = runtime.default_space_title || "";
  byId("default-user-email").value = runtime.default_user_email || "youngcle@cisco.com";
  byId("allowed-webex-user-emails").value = formatEmailList(runtime.allowed_webex_user_emails);
  byId("allowed-admin-emails").value = formatEmailList(runtime.allowed_admin_emails);
  byId("selected-provider-model").value = runtime.selected_provider_model || "";
  renderSecretFields(runtime, startup);
  renderStartupStatus(startup);

  fillSelectOptions(
    byId("default-execution-mode"),
    EXECUTION_MODES,
    runtime.default_execution_mode,
  );

  if (state.providers) {
    renderProviders(state.providers);
  }
  if (state.devices) {
    renderDevices(state.devices);
  }
}

function renderProviders(providerPayload) {
  state.providers = providerPayload;
  const providerOptions = providerPayload.providers.map((entry) => ({
    value: entry.provider,
    label: entry.label,
  }));
  fillSelectOptions(byId("selected-provider"), providerOptions, state.settings?.runtime?.selected_provider);
  fillSelectOptions(byId("provider-kind"), providerOptions, providerPayload.active.provider);

  byId("provider-model").value = providerPayload.active.model || "";
  byId("provider-base-url").value = providerPayload.active.base_url || "";
  byId("provider-api-key").value = providerPayload.active.api_key || "";
  byId("provider-temperature").value = providerPayload.active.temperature ?? "";
  byId("provider-max-tokens").value = providerPayload.active.max_tokens ?? "";
  byId("provider-enabled").checked = Boolean(providerPayload.active.enabled);

  const descriptorCards = byId("provider-descriptor-cards");
  descriptorCards.innerHTML = "";
  providerPayload.providers.forEach((descriptor) => {
    const card = document.createElement("article");
    card.className = "provider-descriptor";
    card.innerHTML = `
      <strong>
        <span>${escapeHtml(descriptor.label)}</span>
        <span class="badge ${descriptor.provider === providerPayload.active.provider ? "badge--approved" : "badge--executed"}">${escapeHtml(descriptor.provider)}</span>
      </strong>
      <small>Default model: ${escapeHtml(descriptor.default_model || "—")}</small>
      <small>Tools: ${formatBoolean(descriptor.capabilities.supports_tools)}</small>
      <small>Streaming: ${formatBoolean(descriptor.capabilities.supports_streaming)}</small>
      <small>Structured output: ${formatBoolean(descriptor.capabilities.supports_structured_output)}</small>
    `;
    descriptorCards.append(card);
  });
}

function renderDevices(devicePayload) {
  state.devices = devicePayload;
  const selector = byId("selected-device");
  fillSelectOptions(
    selector,
    devicePayload.devices.map((device) => ({
      value: device.device_id,
      label: `${device.display_name}${device.place ? ` — ${device.place}` : ""}`,
    })),
    state.settings?.runtime?.selected_device_id,
    "Choose an org device",
  );

  const selectedByName = state.settings?.runtime?.selected_device_name;
  if (!selector.value && selectedByName) {
    const matching = devicePayload.devices.find((device) => device.display_name === selectedByName);
    if (matching) {
      selector.value = matching.device_id;
    }
  }

  updateSelectedDeviceCaption();

  renderTableRows(
    byId("devices-table-body"),
    devicePayload.devices,
    5,
    (device) => `
      <tr>
        <td>${escapeHtml(device.display_name)}</td>
        <td>${escapeHtml(device.product || "—")}</td>
        <td>${escapeHtml(device.place || "—")}</td>
        <td><span class="mono">${escapeHtml(device.workspace_id || "—")}</span></td>
        <td><span class="badge ${device.online ? "badge--approved" : "badge--rejected"}">${device.online === null ? "Unknown" : device.online ? "Online" : "Offline"}</span></td>
      </tr>
    `,
  );
}

function renderStats(statsPayload) {
  state.stats = statsPayload;
  const stats = statsPayload.stats;
  byId("stat-approvals-total").textContent = stats.approvals_total;
  byId("stat-approvals-approved").textContent = stats.approvals_approved;
  byId("stat-approvals-rejected").textContent = stats.approvals_rejected;
  byId("stat-sessions-total").textContent = stats.sessions_total;
  byId("hero-pending-approvals").textContent = stats.approvals_pending;
  byId("hero-webhook-events").textContent = stats.processed_webhook_events;
  byId("hero-audit-total").textContent = stats.audit_total;
}

function renderActions(actionPayload) {
  state.actions = actionPayload;
  renderTableRows(
    byId("actions-table-body"),
    actionPayload.actions,
    5,
    (action) => `
      <tr>
        <td><span class="mono">${escapeHtml(action.intent)}</span><br /><small>${escapeHtml(action.description)}</small></td>
        <td>${escapeHtml(action.label)}</td>
        <td>${escapeHtml(action.supported_modes.map(formatLabel).join(", "))}</td>
        <td><span class="badge ${action.approval_required_by_default ? "badge--pending" : "badge--approved"}">${action.approval_required_by_default ? "Required" : "Not required"}</span></td>
        <td><span class="badge ${action.enabled ? "badge--approved" : "badge--rejected"}">${action.enabled ? "Enabled" : "Disabled"}</span></td>
      </tr>
    `,
  );
}

function renderApprovals(approvalPayload) {
  state.approvals = approvalPayload;
  renderTableRows(
    byId("approvals-table-body"),
    approvalPayload.approvals,
    4,
    (approval) => `
      <tr>
        <td><span class="badge badge--${escapeHtml(approval.status)}">${formatLabel(approval.status)}</span></td>
        <td>${escapeHtml(approval.title)}<br /><small>${escapeHtml(approval.prompt)}</small></td>
        <td>${escapeHtml(approval.requested_by_email || approval.requested_by)}</td>
        <td>${escapeHtml(formatDate(approval.created_at))}</td>
      </tr>
    `,
  );
}

function renderAudit(auditPayload) {
  state.audit = auditPayload;
  renderTableRows(
    byId("audit-table-body"),
    auditPayload.audit,
    4,
    (record) => `
      <tr>
        <td>${escapeHtml(formatLabel(record.event_type))}<br /><small>${escapeHtml(record.detail)}</small></td>
        <td>${escapeHtml(record.outcome)}</td>
        <td>${escapeHtml(record.intent || "—")}</td>
        <td>${escapeHtml(formatDate(record.created_at))}</td>
      </tr>
    `,
  );
}

function renderPolicies(policyPayload) {
  state.policies = policyPayload;
  const container = byId("policy-forms");
  container.innerHTML = "";
  Object.entries(policyPayload.policies).forEach(([intent, policy]) => {
    const form = document.createElement("form");
    form.className = "policy-card";
    form.dataset.intent = intent;
    form.innerHTML = `
      <div class="policy-card__header">
        <strong>${escapeHtml(formatLabel(intent))}</strong>
        <span class="badge ${policy.approval_state === "required" ? "badge--pending" : "badge--approved"}">${escapeHtml(formatLabel(policy.approval_state))}</span>
      </div>
      <div class="policy-card__controls">
        <label>
          <span>Preferred allowed modes</span>
          <select name="allowed_modes" multiple size="2"></select>
        </label>
        <label>
          <span>Risk level</span>
          <select name="risk_level"></select>
        </label>
        <label>
          <span>Approval state</span>
          <select name="approval_state"></select>
        </label>
      </div>
      <label>
        <span>Reason</span>
        <textarea name="reason"></textarea>
      </label>
      <div class="form-footer">
        <p class="inline-message" data-role="policy-message" aria-live="polite"></p>
        <button class="button" type="submit">Save policy</button>
      </div>
    `;

    const modeSelect = form.querySelector('select[name="allowed_modes"]');
    EXECUTION_MODES.forEach((mode) => {
      const option = document.createElement("option");
      option.value = mode.value;
      option.textContent = mode.label;
      option.selected = policy.allowed_modes.includes(mode.value);
      modeSelect.append(option);
    });

    const riskSelect = form.querySelector('select[name="risk_level"]');
    RISK_LEVELS.forEach((riskLevel) => {
      const option = document.createElement("option");
      option.value = riskLevel;
      option.textContent = formatLabel(riskLevel);
      option.selected = policy.risk_level === riskLevel;
      riskSelect.append(option);
    });

    const approvalSelect = form.querySelector('select[name="approval_state"]');
    APPROVAL_STATES.forEach((approvalState) => {
      const option = document.createElement("option");
      option.value = approvalState;
      option.textContent = formatLabel(approvalState);
      option.selected = policy.approval_state === approvalState;
      approvalSelect.append(option);
    });

    form.querySelector('textarea[name="reason"]').value = policy.reason;
    form.addEventListener("submit", handlePolicySubmit);
    container.append(form);
  });
}

function renderTableRows(container, items, columnCount, renderRow) {
  if (!items || items.length === 0) {
    container.innerHTML = `<tr><td colspan="${columnCount}" class="empty-state">No data yet.</td></tr>`;
    return;
  }
  container.innerHTML = items.map(renderRow).join("");
}

function getSelectedDeviceRecord() {
  const deviceId = byId("selected-device").value;
  return state.devices?.devices?.find((device) => device.device_id === deviceId) || null;
}

function updateSelectedDeviceCaption() {
  const selected = getSelectedDeviceRecord();
  byId("selected-device-caption").textContent = selected
    ? `Current selection: ${selected.display_name}${selected.place ? ` — ${selected.place}` : ""}`
    : "Choose a device returned by /admin/devices.";
}

function formatEmailList(values) {
  return Array.isArray(values) ? values.join("\n") : "";
}

function parseEmailList(value) {
  const emails = value
    .split(/\r?\n/)
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
  return emails.filter((entry, index) => emails.indexOf(entry) === index);
}

function clearAuthPoll() {
  if (state.auth.pollTimer !== null) {
    window.clearTimeout(state.auth.pollTimer);
    state.auth.pollTimer = null;
  }
}

function persistAuthSession() {
  try {
    if (!state.auth.sessionId) {
      window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({
      sessionId: state.auth.sessionId,
      email: state.auth.email,
      status: state.auth.status,
      authenticated: state.auth.authenticated,
    }));
  } catch (_error) {
  }
}

function restoreAuthSession() {
  try {
    const raw = window.sessionStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) {
      return;
    }
    const saved = JSON.parse(raw);
    state.auth.sessionId = typeof saved.sessionId === "string" ? saved.sessionId : null;
    state.auth.email = typeof saved.email === "string" ? saved.email : "";
    state.auth.status = typeof saved.status === "string" ? saved.status : "signed_out";
    state.auth.authenticated = Boolean(saved.authenticated);
  } catch (_error) {
  }
}

function getStatusPillVariant(status) {
  if (status === "approved" || status === "executed" || status === "authenticated") {
    return "ready";
  }
  if (status === "pending") {
    return "loading";
  }
  if (status === "rejected" || status === "expired") {
    return "error";
  }
  return "idle";
}

function updateAuthUi() {
  const auth = state.auth;
  const authStatus = byId("auth-status");
  const guardStatus = byId("auth-guard-status");
  const sessionEmail = byId("auth-session-email");
  const sessionStatus = byId("auth-session-status");
  const sessionId = byId("auth-session-id");
  const authEmail = byId("auth-email");
  const pollButton = byId("poll-auth-status");
  const logoutButton = byId("logout");

  let authText = "Signed out";
  let guardText = "Locked";
  let detailText = "Enter an allowed admin email to request approval.";
  let variant = "idle";

  if (auth.authenticated) {
    authText = "Approved";
    guardText = "Unlocked";
    detailText = "Protected admin data is unlocked for this browser session.";
    variant = "ready";
  } else if (auth.status === "pending") {
    authText = "Pending approval";
    guardText = "Pending";
    detailText = "Approval request sent. Approve the Webex card, then this page will unlock automatically.";
    variant = "loading";
  } else if (auth.status === "rejected") {
    authText = "Rejected";
    guardText = "Locked";
    detailText = "Approval was rejected. Start a new login to request another approval card.";
    variant = "error";
  } else if (auth.status === "expired") {
    authText = "Expired";
    guardText = "Locked";
    detailText = "This approval request expired. Start a fresh login to continue.";
    variant = "error";
  }

  authStatus.textContent = authText;
  authStatus.className = `status-pill status-pill--${variant}`;
  guardStatus.textContent = guardText;
  guardStatus.className = `status-pill status-pill--${variant}`;
  sessionEmail.textContent = auth.email || (auth.authenticated ? "Authenticated browser session" : "Not signed in");
  sessionStatus.textContent = detailText;
  sessionId.textContent = auth.sessionId ? `Session ID: ${auth.sessionId}` : "No auth session started.";
  if (!authEmail.value && auth.email) {
    authEmail.value = auth.email;
  }
  pollButton.disabled = !auth.sessionId;
  logoutButton.disabled = !auth.authenticated && !auth.sessionId;
}

function setProtectedVisibility(visible) {
  byId("protected-dashboard").hidden = !visible;
  byId("auth-guard").hidden = visible;
}

function resetProtectedData() {
  state.settings = null;
  state.providers = null;
  state.policies = null;
  state.actions = null;
  state.devices = null;
  state.approvals = null;
  state.audit = null;
  state.stats = null;

  byId("default-admin-user").textContent = "youngcle@cisco.com";
  byId("hero-pending-approvals").textContent = "--";
  byId("hero-webhook-events").textContent = "--";
  byId("hero-audit-total").textContent = "--";
  byId("stat-approvals-total").textContent = "--";
  byId("stat-approvals-approved").textContent = "--";
  byId("stat-approvals-rejected").textContent = "--";
  byId("stat-sessions-total").textContent = "--";

  byId("default-space-id").value = "";
  byId("default-space-title").value = "";
  byId("default-user-email").value = "";
  byId("allowed-webex-user-emails").value = "";
  byId("allowed-admin-emails").value = "";
  byId("selected-provider-model").value = "";
  byId("provider-model").value = "";
  byId("provider-base-url").value = "";
  byId("provider-api-key").value = "";
  byId("provider-temperature").value = "";
  byId("provider-max-tokens").value = "";
  byId("provider-enabled").checked = false;

  fillSelectOptions(byId("default-execution-mode"), EXECUTION_MODES, null);
  fillSelectOptions(byId("selected-provider"), [], null, "Load provider data after sign-in");
  fillSelectOptions(byId("provider-kind"), [], null, "Load provider data after sign-in");
  fillSelectOptions(byId("selected-device"), [], null, "Choose an org device");
  updateSelectedDeviceCaption();

  byId("secret-fields").innerHTML = "";
  byId("startup-status-grid").innerHTML = "";
  byId("provider-descriptor-cards").innerHTML = "";
  byId("policy-forms").innerHTML = "";

  renderTableRows(byId("actions-table-body"), [], 5, () => "");
  renderTableRows(byId("devices-table-body"), [], 5, () => "");
  renderTableRows(byId("approvals-table-body"), [], 4, () => "");
  renderTableRows(byId("audit-table-body"), [], 4, () => "");

  clearInlineMessage("settings-save-message");
  clearInlineMessage("provider-save-message");
}

function setSignedOutState(message, variant = "info") {
  clearAuthPoll();
  state.auth.sessionId = null;
  state.auth.authenticated = false;
  state.auth.status = "signed_out";
  persistAuthSession();
  resetProtectedData();
  setProtectedVisibility(false);
  updateAuthUi();
  if (message) {
    setInlineMessage("auth-message", message, variant);
  }
  setPageStatus("Sign in required", "idle");
}

function scheduleAuthPoll() {
  clearAuthPoll();
  if (state.auth.status !== "pending" || state.auth.authenticated || !state.auth.sessionId) {
    return;
  }
  state.auth.pollTimer = window.setTimeout(() => {
    pollAuthStatus();
  }, AUTH_POLL_INTERVAL_MS);
}

function handleUnauthorized(message) {
  setSignedOutState(message, "info");
}

async function handleAuthStart(event) {
  event.preventDefault();
  clearAuthPoll();

  const email = byId("auth-email").value.trim().toLowerCase();
  if (!email) {
    setInlineMessage("auth-message", "Enter an allowed admin email to start login.", "error");
    return;
  }

  setInlineMessage("auth-message", "Sending approval request…", "info");
  setPageStatus("Starting login…", "loading");

  try {
    const response = await requestJson("/admin/auth/start", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
    state.auth.sessionId = response.session_id;
    state.auth.email = email;
    state.auth.status = response.status || "pending";
    state.auth.authenticated = false;
    persistAuthSession();
    resetProtectedData();
    setProtectedVisibility(false);
    updateAuthUi();
    setInlineMessage("auth-message", "Approval requested in Webex. Waiting for approval…", "info");
    setPageStatus("Waiting for approval", "loading");
    await pollAuthStatus({ silentPending: true });
  } catch (error) {
    setPageStatus("Sign in required", "idle");
    setInlineMessage("auth-message", error.message, error.status === 403 ? "error" : "info");
  }
}

async function pollAuthStatus(options = {}) {
  if (!state.auth.sessionId) {
    setInlineMessage("auth-message", "Start login before checking approval.", "info");
    return;
  }

  clearAuthPoll();
  if (!options.silentPending) {
    setInlineMessage("auth-message", "Checking approval status…", "info");
  }

  try {
    const response = await requestJson(`/admin/auth/status/${encodeURIComponent(state.auth.sessionId)}`);
    state.auth.email = response.email || state.auth.email;
    state.auth.status = response.status;

    if (response.status === "approved" || response.status === "executed") {
      state.auth.authenticated = true;
      persistAuthSession();
      updateAuthUi();
      setInlineMessage("auth-message", "Approval complete. Loading protected admin data…", "success");
      await loadProtectedData({ showSuccessMessage: true });
      return;
    }

    state.auth.authenticated = false;
    persistAuthSession();
    updateAuthUi();

    if (response.status === "pending") {
      setPageStatus("Waiting for approval", "loading");
      if (!options.silentPending) {
        setInlineMessage("auth-message", "Still waiting for approval in Webex…", "info");
      }
      scheduleAuthPoll();
      return;
    }

    resetProtectedData();
    setProtectedVisibility(false);

    if (response.status === "rejected") {
      setPageStatus("Approval rejected", "error");
      setInlineMessage("auth-message", "Approval was rejected. Start a new login to continue.", "error");
      return;
    }

    if (response.status === "expired") {
      state.auth.sessionId = null;
      persistAuthSession();
      updateAuthUi();
      setPageStatus("Approval expired", "error");
      setInlineMessage("auth-message", "This approval request expired. Start login again.", "error");
      return;
    }

    setPageStatus("Sign in required", "idle");
  } catch (error) {
    if (error.status === 404) {
      setSignedOutState("This approval request no longer exists. Start a new login.", "error");
      return;
    }
    setInlineMessage("auth-message", error.message, "error");
    setPageStatus("Approval check failed", "error");
  }
}

async function handleLogout() {
  clearAuthPoll();
  setInlineMessage("auth-message", "Signing out…", "info");

  try {
    await requestJson("/admin/auth/logout", { method: "POST" });
  } catch (error) {
    if (error.status !== 401) {
      setInlineMessage("auth-message", error.message, "error");
      setPageStatus("Logout failed", "error");
      return;
    }
  }

  state.auth.email = byId("auth-email").value.trim().toLowerCase() || state.auth.email;
  setSignedOutState("Signed out from this browser session.", "success");
}

async function handleSettingsSubmit(event) {
  event.preventDefault();
  setInlineMessage("settings-save-message", "Saving runtime settings…", "info");
  const selectedDevice = getSelectedDeviceRecord();
  const payload = {
    default_space_id: byId("default-space-id").value || null,
    default_space_title: byId("default-space-title").value || null,
    default_user_email: byId("default-user-email").value || null,
    allowed_webex_user_emails: parseEmailList(byId("allowed-webex-user-emails").value),
    allowed_admin_emails: parseEmailList(byId("allowed-admin-emails").value),
    default_execution_mode: byId("default-execution-mode").value || null,
    selected_provider: byId("selected-provider").value || null,
    selected_provider_model: byId("selected-provider-model").value || null,
    selected_device_id: selectedDevice ? selectedDevice.device_id : null,
    selected_device_name: selectedDevice ? selectedDevice.display_name : null,
  };

  try {
    const response = await requestJson("/admin/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    state.settings = { ...state.settings, runtime: response.runtime };
    renderSettings(state.settings);
    setInlineMessage("settings-save-message", "Runtime settings saved.", "success");
  } catch (error) {
    if (error.status === 401) {
      handleUnauthorized("Your admin session ended. Sign in again to save settings.");
      return;
    }
    setInlineMessage("settings-save-message", error.message, "error");
  }
}

async function handleProviderSubmit(event) {
  event.preventDefault();
  setInlineMessage("provider-save-message", "Applying provider settings…", "info");

  const payload = {
    provider: byId("provider-kind").value,
    model: byId("provider-model").value || null,
    base_url: byId("provider-base-url").value || null,
    api_key: byId("provider-api-key").value || null,
    temperature: toNullableNumber(byId("provider-temperature").value),
    max_tokens: toNullableInteger(byId("provider-max-tokens").value),
    enabled: byId("provider-enabled").checked,
  };

  try {
    const response = await requestJson("/admin/providers", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    state.providers.active = response.provider;
    renderProviders(state.providers);
    setInlineMessage("provider-save-message", "Provider settings applied.", "success");
  } catch (error) {
    if (error.status === 401) {
      handleUnauthorized("Your admin session ended. Sign in again to update providers.");
      return;
    }
    setInlineMessage("provider-save-message", error.message, "error");
  }
}

async function handlePolicySubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = form.querySelector('[data-role="policy-message"]');
  message.textContent = "Saving policy…";
  message.className = messageClass("info");
  const intent = form.dataset.intent;

  const payload = {
    allowed_modes: Array.from(form.querySelector('select[name="allowed_modes"]').selectedOptions).map((option) => option.value),
    risk_level: form.querySelector('select[name="risk_level"]').value,
    approval_state: form.querySelector('select[name="approval_state"]').value,
    reason: form.querySelector('textarea[name="reason"]').value,
  };

  try {
    const response = await requestJson(`/admin/policies/${intent}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    state.policies.policies[response.intent] = response.policy;
    renderPolicies(state.policies);
    const refreshedForm = byId("policy-forms").querySelector(`form[data-intent="${intent}"]`);
    const refreshedMessage = refreshedForm?.querySelector('[data-role="policy-message"]');
    if (refreshedMessage) {
      refreshedMessage.textContent = "Policy saved.";
      refreshedMessage.className = messageClass("success");
    }
  } catch (error) {
    if (error.status === 401) {
      handleUnauthorized("Your admin session ended. Sign in again to update policies.");
      return;
    }
    message.textContent = error.message;
    message.className = messageClass("error");
  }
}

function toNullableNumber(value) {
  if (value === "") {
    return null;
  }
  return Number(value);
}

function toNullableInteger(value) {
  if (value === "") {
    return null;
  }
  return Number.parseInt(value, 10);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadProtectedData(options = {}) {
  setPageStatus("Loading admin data…", "loading");
  try {
    const settings = await requestJson("/admin/settings");
    const [providers, policies, actions, devices, approvals, audit, stats] = await Promise.all([
      requestJson("/admin/providers"),
      requestJson("/admin/policies"),
      requestJson("/admin/actions"),
      requestJson("/admin/devices"),
      requestJson("/admin/approvals"),
      requestJson("/admin/audit"),
      requestJson("/admin/stats"),
    ]);

    state.auth.authenticated = true;
    if (state.auth.status !== "approved" && state.auth.status !== "executed") {
      state.auth.status = "authenticated";
    }
    persistAuthSession();
    renderSettings(settings);
    renderProviders(providers);
    renderPolicies(policies);
    renderActions(actions);
    renderDevices(devices);
    renderApprovals(approvals);
    renderAudit(audit);
    renderStats(stats);
    setProtectedVisibility(true);
    updateAuthUi();
    setPageStatus("Live data loaded", "ready");
    if (options.showSuccessMessage) {
      setInlineMessage("auth-message", "Admin session active. Protected data loaded.", "success");
    }
  } catch (error) {
    if (error.status === 401) {
      handleUnauthorized(options.unauthorizedMessage || "Sign in to load protected admin data.");
      return;
    }
    setPageStatus("Failed to load", "error");
    setInlineMessage("auth-message", error.message, "error");
  }
}

async function handleRefreshAll() {
  if (state.auth.authenticated) {
    await loadProtectedData({ showSuccessMessage: false });
    return;
  }
  if (state.auth.sessionId) {
    await pollAuthStatus();
    return;
  }
  setInlineMessage("auth-message", "Sign in first to load live admin data.", "info");
  setPageStatus("Sign in required", "idle");
}

function registerEvents() {
  byId("refresh-all").addEventListener("click", handleRefreshAll);
  byId("auth-form").addEventListener("submit", handleAuthStart);
  byId("poll-auth-status").addEventListener("click", () => {
    pollAuthStatus();
  });
  byId("logout").addEventListener("click", handleLogout);
  byId("settings-form").addEventListener("submit", handleSettingsSubmit);
  byId("provider-form").addEventListener("submit", handleProviderSubmit);
  byId("selected-device").addEventListener("change", updateSelectedDeviceCaption);
}

async function initializePage() {
  resetProtectedData();
  setProtectedVisibility(false);
  restoreAuthSession();
  updateAuthUi();

  if (state.auth.sessionId) {
    await pollAuthStatus({ silentPending: true });
    if (state.auth.authenticated || state.auth.status === "pending") {
      return;
    }
  }

  setSignedOutState(
    "Sign in with an allowed admin email to load the admin dashboard.",
    "info",
  );
}

registerEvents();
initializePage();
