// Frontend logic for interacting with backend
// ══════════════════════════════════════════════════════════
//  NL → SQL Assistant — app.js
//  All frontend logic in one clean, commented file.
// ══════════════════════════════════════════════════════════

// ── State ─────────────────────────────────────────────────
const BASE_URL = "http://127.0.0.1:8000";  // ← Change if backend is hosted elsewhere
const state = {
  session_id      : null,      // set after POST /session/init
  connected       : false,
  currentSQL      : null,      // last generated SQL
  currentQuestion : null,
  explainCache    : {},        // key = session_id + sql → explanation string
};

// ── Element refs ──────────────────────────────────────────
const $ = id => document.getElementById(id);

const els = {
  // Connection
  dbUrl           : $("db-url"),
  apiKey          : $("api-key"),
  connectBtn      : $("connect-btn"),
  connectMsg      : $("connect-msg"),
  connectionBadge : $("connection-badge"),

  // Query
  questionInput   : $("question-input"),
  queryBtn        : $("query-btn"),
  resetBtn        : $("reset-btn"),

  // Schema
  schemaVersion   : $("schema-version"),
  schemaTables    : $("schema-tables"),
  schemaUpdated   : $("schema-updated"),
  refreshSchemaBtn: $("refresh-schema-btn"),
  schemaMsg       : $("schema-msg"),

  // Results
  resultsSection  : $("results-section"),
  resultMeta      : $("result-meta"),
  warningsContainer: $("warnings-container"),
  sqlOutput       : $("sql-output"),
  copySqlBtn      : $("copy-sql-btn"),
  tableContainer  : $("table-container"),
  tableMeta       : $("table-meta"),

  // Explain
  explainBtn      : $("explain-btn"),
  explanationBox  : $("explanation-box"),
  explanationText : $("explanation-text"),

  // Error
  errorSection    : $("error-section"),
  errorText       : $("error-text"),
};

// ══════════════════════════════════════════════════════════
//  API HELPERS
// ══════════════════════════════════════════════════════════

/**
 * Generic POST helper.
 * Returns parsed JSON or throws an Error with a friendly message.
 */
async function apiPost(endpoint, body) {
  const res = await fetch(BASE_URL + endpoint, {
    method  : "POST",
    headers : { "Content-Type": "application/json" },
    body    : JSON.stringify(body),
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const msg = data.detail || data.error || `HTTP ${res.status}`;
    throw new Error(msg);
  }

  return data;
}

/**
 * Generic GET helper.
 */
async function apiGet( endpoint) {
  const res = await fetch(BASE_URL + endpoint);
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }

  return data;
}

// ══════════════════════════════════════════════════════════
//  BUTTON LOADING HELPERS
// ══════════════════════════════════════════════════════════

function setLoading(btn, loading) {
  const text    = btn.querySelector(".btn-text");
  const spinner = btn.querySelector(".btn-spinner");

  btn.disabled = loading;

  if (text)    text.style.opacity    = loading ? "0.5" : "1";
  if (spinner) spinner.classList.toggle("hidden", !loading);
}

// ══════════════════════════════════════════════════════════
//  STATUS MESSAGE HELPERS
// ══════════════════════════════════════════════════════════

function setMsg(el, text, type = "info") {
  el.textContent = text;
  el.className   = `status-msg status-msg--${type}`;
}

function clearMsg(el) {
  el.textContent = "";
  el.className   = "status-msg";
}

// ══════════════════════════════════════════════════════════
//  CONNECTION
// ══════════════════════════════════════════════════════════

async function handleConnect() {
  const database_url   = els.dbUrl.value.trim();
  const gemini_api_key = els.apiKey.value.trim();

  if (!database_url || !gemini_api_key) {
    setMsg(els.connectMsg, "Please fill in both fields.", "error");
    return;
  }

  clearMsg(els.connectMsg);
  setLoading(els.connectBtn, true);

  try {
    // Call /session/init with credentials
    const data = await apiPost("/session/init", {
      database_url,
      gemini_api_key,
    });

    state.session_id = data.session_id;
    state.mode       = data.mode || "custom";  // ← Track which mode
    state.connected  = true;

    setMsg(els.connectMsg, "✓ Connected successfully", "success");
    updateConnectionBadge(true);
    enableQueryUI();
    await loadSchemaInfo();

  } catch (err) {
    setMsg(els.connectMsg, `Connection failed: ${err.message}`, "error");
  } finally {
    setLoading(els.connectBtn, false);
  }
}

function updateConnectionBadge(connected) {
  const badge = els.connectionBadge;
  if (connected) {
    badge.textContent = "● Connected";
    badge.className   = "badge badge--connected";
  } else {
    badge.textContent = "● Disconnected";
    badge.className   = "badge badge--disconnected";
  }
}

function enableQueryUI() {
  els.queryBtn.disabled        = false;
  els.resetBtn.disabled        = false;
  els.refreshSchemaBtn.disabled = false;
}

// ══════════════════════════════════════════════════════════
//  SCHEMA
// ══════════════════════════════════════════════════════════

async function loadSchemaInfo() {
  try {
    const data = await apiGet("/schema");
    renderSchemaInfo(data);
  } catch {
    // Non-critical — silently ignore if schema fetch fails on load
  }
}

function renderSchemaInfo(data) {
  els.schemaVersion.textContent = data.version ?? "—";
  els.schemaTables.textContent  = data.table_count ?? "—";

  if (data.cached_at) {
    const d = new Date(data.cached_at * 1000);
    els.schemaUpdated.textContent = formatRelativeTime(d);
  } else {
    els.schemaUpdated.textContent = "—";
  }
}

async function handleRefreshSchema() {
  clearMsg(els.schemaMsg);
  setLoading(els.refreshSchemaBtn, true);

  try {
    const data = await apiPost("/schema/refresh", {});

    if (data.changed) {
      setMsg(els.schemaMsg, `✓ Schema updated — v${data.version}, ${data.table_count} tables`, "success");
    } else {
      setMsg(els.schemaMsg, "✓ Schema is already up to date", "info");
    }

    // Refresh the displayed metadata
    await loadSchemaInfo();

  } catch (err) {
    setMsg(els.schemaMsg, `Refresh failed: ${err.message}`, "error");
  } finally {
    setLoading(els.refreshSchemaBtn, false);
  }
}

// ══════════════════════════════════════════════════════════
//  QUERY
// ══════════════════════════════════════════════════════════

// Update query to send the mode
async function handleQuery() {
  const question = els.questionInput.value.trim();

  if (!question || !state.session_id) return;

  resetResultsUI();
  setLoading(els.queryBtn, true);

  try {
    const data = await apiPost("/query", {
      question,
      session_id: state.session_id,
      mode: state.mode || "demo",  // ← Send the actual mode
    });

    if (data.success) {
      state.currentSQL      = data.generated_sql;
      state.currentQuestion = question;
      renderResults(data);
      hideError();
    } else {
      showError(data.error || "Query could not be processed.");
      hideResults();
    }

  } catch (err) {
    showError(friendlyError(err.message));
    hideResults();
  } finally {
    setLoading(els.queryBtn, false);
  }
}

function renderResults(data) {
  // Show results section
  els.resultsSection.classList.remove("hidden");

  // Warnings
  renderWarnings(data.warnings || []);

  // Generated SQL
  els.sqlOutput.textContent = data.generated_sql || "";

  // Result meta (above card header)
  const rowInfo = data.truncated
    ? `Showing ${data.returned_rows} of ${data.total_rows}+ rows`
    : `${data.row_count} row${data.row_count !== 1 ? "s" : ""} returned`;

  els.resultMeta.textContent = rowInfo;

  // Table
  renderTable(data.columns || [], data.rows || [], data.truncated);
}

function renderWarnings(warnings) {
  if (!warnings.length) {
    els.warningsContainer.classList.add("hidden");
    return;
  }

  els.warningsContainer.innerHTML = warnings.map(w => `
    <div class="warning-item">
      <span class="warning-item__icon">⚠</span>
      <span>${escapeHtml(w.message)}</span>
    </div>
  `).join("");

  els.warningsContainer.classList.remove("hidden");
}

function renderTable(columns, rows, truncated) {
  if (!columns.length) {
    els.tableContainer.innerHTML = `<div class="empty-state">No results found.</div>`;
    els.tableMeta.textContent    = "";
    return;
  }

  // Build <table>
  const thead = `<thead><tr>${columns.map(c =>
    `<th>${escapeHtml(c)}</th>`
  ).join("")}</tr></thead>`;

  const tbody = `<tbody>${rows.map(row =>
    `<tr>${row.map(cell =>
      `<td>${cell === null ? '<span style="color:var(--text-muted)">null</span>' : escapeHtml(String(cell))}</td>`
    ).join("")}</tr>`
  ).join("")}</tbody>`;

  els.tableContainer.innerHTML = `<table>${thead}${tbody}</table>`;

  // Table footer meta
  let metaText = `${rows.length} row${rows.length !== 1 ? "s" : ""}`;
  if (truncated) metaText += ` <span class="truncated-badge">truncated</span>`;
  els.tableMeta.innerHTML = metaText;
}

// ══════════════════════════════════════════════════════════
//  EXPLAIN
// ══════════════════════════════════════════════════════════

async function handleExplain() {
  if (!state.currentSQL || !state.session_id) return;

  // Cache key = session_id + sql (avoids duplicate API calls)
  const cacheKey = state.session_id + "::" + state.currentSQL;

  // Return cached explanation immediately
  if (state.explainCache[cacheKey]) {
    showExplanation(state.explainCache[cacheKey]);
    return;
  }

  setLoading(els.explainBtn, true);
  els.explanationBox.classList.add("hidden");

  try {
    const data = await apiPost("/explain", {
      question   : state.currentQuestion,
      sql        : state.currentSQL,
      session_id : state.session_id,
    });

    const explanation = data.explanation || "No explanation returned.";

    // Cache it
    state.explainCache[cacheKey] = explanation;

    showExplanation(explanation);

  } catch (err) {
    showExplanation(`Could not generate explanation: ${err.message}`);
  } finally {
    setLoading(els.explainBtn, false);
  }
}

function showExplanation(text) {
  els.explanationText.textContent = text;
  els.explanationBox.classList.remove("hidden");
}

// ══════════════════════════════════════════════════════════
//  RESET / CLEAR
// ══════════════════════════════════════════════════════════

function handleReset() {
  els.questionInput.value = "";
  state.currentSQL        = null;
  state.currentQuestion   = null;
  resetResultsUI();
  hideError();
  hideResults();
}

function resetResultsUI() {
  // Clear explanation on every new query
  els.explanationBox.classList.add("hidden");
  els.explanationText.textContent = "";
  els.warningsContainer.classList.add("hidden");
  els.warningsContainer.innerHTML = "";
  els.sqlOutput.textContent       = "";
  els.tableContainer.innerHTML    = "";
  els.tableMeta.innerHTML         = "";
  els.resultMeta.textContent      = "";
}

function hideResults() {
  els.resultsSection.classList.add("hidden");
}

// ══════════════════════════════════════════════════════════
//  ERROR DISPLAY
// ══════════════════════════════════════════════════════════

function showError(message) {
  els.errorText.textContent = message;
  els.errorSection.classList.remove("hidden");
}

function hideError() {
  els.errorSection.classList.add("hidden");
  els.errorText.textContent = "";
}

// ══════════════════════════════════════════════════════════
//  COPY SQL
// ══════════════════════════════════════════════════════════

async function handleCopySQL() {
  const sql = els.sqlOutput.textContent;
  if (!sql) return;

  try {
    await navigator.clipboard.writeText(sql);
    els.copySqlBtn.querySelector(".btn-text")
      ? (els.copySqlBtn.textContent = "Copied!")
      : null;
    els.copySqlBtn.textContent = "Copied!";
    setTimeout(() => { els.copySqlBtn.textContent = "Copy"; }, 2000);
  } catch {
    // Clipboard API not available
  }
}

// ══════════════════════════════════════════════════════════
//  UTILITY HELPERS
// ══════════════════════════════════════════════════════════

/**
 * Escapes HTML special characters to prevent XSS.
 */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Converts a Date object into a relative time string.
 * e.g. "2 minutes ago", "just now"
 */
function formatRelativeTime(date) {
  const now  = Date.now();
  const diff = Math.floor((now - date.getTime()) / 1000);

  if (diff < 60)    return "just now";
  if (diff < 3600)  return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`;
  return date.toLocaleDateString();
}

/**
 * Maps raw API/fetch errors to user-friendly messages.
 */
function friendlyError(msg = "") {
  if (msg.includes("503") || msg.toLowerCase().includes("overload"))
    return "AI service is busy right now. Please try again in a moment.";
  if (msg.includes("401") || msg.toLowerCase().includes("api key"))
    return "Invalid API key. Please check your Gemini credentials.";
  if (msg.includes("fetch") || msg.includes("network"))
    return "Network error. Please check your connection.";
  return msg || "Something went wrong. Please try again.";
}

// ══════════════════════════════════════════════════════════
//  EVENT LISTENERS
// ══════════════════════════════════════════════════════════

// Connection
els.connectBtn.addEventListener("click", handleConnect);

// Allow Enter key on API key field to trigger connect
els.apiKey.addEventListener("keydown", e => {
  if (e.key === "Enter") handleConnect();
});

// Query — click or Ctrl+Enter in textarea
els.queryBtn.addEventListener("click", handleQuery);
els.questionInput.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") handleQuery();
});

// Reset
els.resetBtn.addEventListener("click", handleReset);

// Schema refresh
els.refreshSchemaBtn.addEventListener("click", handleRefreshSchema);

// Explain (on-demand only)
els.explainBtn.addEventListener("click", handleExplain);

// Copy SQL
els.copySqlBtn.addEventListener("click", handleCopySQL);

// ══════════════════════════════════════════════════════════
//  INIT — load schema info if already in demo mode
// ══════════════════════════════════════════════════════════

(async function init() {
  // Try to load schema info immediately (works in demo mode without credentials)
  try {
    const data = await apiGet("/schema");
    renderSchemaInfo(data);
  } catch {
    // Schema not ready yet — that's fine
  }
})();