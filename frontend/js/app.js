// Frontend logic for interacting with backend
// ══════════════════════════════════════════════════════════
//  NL → SQL Assistant — app.js
//  All frontend logic in one clean, commented file.
// ══════════════════════════════════════════════════════════

// ── State ─────────────────────────────────────────────────
const BASE_URL = "http://127.0.0.1:8000";  // ← Change if backend is hosted elsewhere
const state = {
  session_id      : null,      // set after POST /session/init
  mode            : "demo",    // "demo" | "custom"
  connected       : false,
  currentSQL      : null,      // last generated SQL
  currentQuestion : null,
  explainCache    : {},        // key = sql → explanation string (avoids duplicate LLM calls)
  schemaCache     : null,      // cached GET /schema response
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

  // Schema Explorer
  viewTablesBtn   : $("view-tables-btn"),
  schemaExplorer  : $("schema-explorer"),
  schemaTableList : $("schema-table-list"),
  closeExplorerBtn: $("close-explorer-btn"),

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

  // Export
  exportToolbar    : $("export-toolbar"),
  copyTableBtn     : $("copy-table-btn"),
  downloadCsvBtn   : $("download-csv-btn"),
  downloadExcelBtn : $("download-excel-btn"),
  exportMsg        : $("export-msg"),
};

// ══════════════════════════════════════════════════════════
//  API HELPERS
// ══════════════════════════════════════════════════════════

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

async function apiGet(endpoint) {
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
    const data = await apiPost("/session/init", {
      database_url,
      gemini_api_key,
    });

    state.session_id = data.session_id;
    state.mode       = data.mode || "custom";
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
  els.queryBtn.disabled         = false;
  els.resetBtn.disabled         = false;
  els.refreshSchemaBtn.disabled = false;
}

// ══════════════════════════════════════════════════════════
//  SCHEMA
// ══════════════════════════════════════════════════════════

async function loadSchemaInfo() {
  try {
    const data = await apiGet("/schema");
    renderSchemaInfo(data);
    state.schemaCache = data;
  } catch {
    // Non-critical
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

    state.schemaCache = null;

    if (!els.schemaExplorer.classList.contains("hidden")) {
      await fetchAndRenderExplorer();
    }

    await loadSchemaInfo();

  } catch (err) {
    setMsg(els.schemaMsg, `Refresh failed: ${err.message}`, "error");
  } finally {
    setLoading(els.refreshSchemaBtn, false);
  }
}

// ══════════════════════════════════════════════════════════
//  SCHEMA EXPLORER
// ══════════════════════════════════════════════════════════

async function handleViewTables() {
  const isOpen = !els.schemaExplorer.classList.contains("hidden");

  if (isOpen) {
    closeExplorer();
    return;
  }

  els.schemaExplorer.classList.remove("hidden");
  updateViewTablesBtn(true);

  if (state.schemaCache) {
    renderExplorer(state.schemaCache);
  } else {
    await fetchAndRenderExplorer();
  }
}

async function fetchAndRenderExplorer() {
  els.schemaTableList.innerHTML = `
    <li class="schema-explorer-loading">Loading tables…</li>
  `;

  try {
    const data = await apiGet("/schema");
    state.schemaCache = data;
    renderSchemaInfo(data);
    renderExplorer(data);
  } catch (err) {
    els.schemaTableList.innerHTML = `
      <li class="schema-explorer-loading" style="color: var(--danger);">
        Failed to load schema: ${escapeHtml(err.message)}
      </li>
    `;
  }
}

function renderExplorer(schemaData) {
  const tables = schemaData.tables || [];

  if (!tables.length) {
    els.schemaTableList.innerHTML = `
      <li class="schema-explorer-loading">No tables found.</li>
    `;
    return;
  }

  const fkMap = buildFkMap(tables);
  const pkMap = buildPkMap(tables);

  els.schemaTableList.innerHTML = tables.map((table, idx) => {
    const tableName  = escapeHtml(table.table_name);
    const colCount   = (table.columns || []).length;
    const fkCols     = fkMap[table.table_name] || new Set();
    const pkCols     = pkMap[table.table_name] || new Set();

    const columnsHtml = (table.columns || []).map(col => {
      const colName = escapeHtml(col);
      const isPk    = pkCols.has(col);
      const isFk    = fkCols.has(col);

      const pkBadge = isPk ? `<span class="schema-column-pk">PK</span>` : "";
      const fkBadge = isFk ? `<span class="schema-column-fk">FK</span>` : "";

      return `
        <li class="schema-column-item">
          <span class="schema-column-name">${colName}</span>
          ${pkBadge}${fkBadge}
        </li>
      `;
    }).join("");

    return `
      <li class="schema-table-item" data-table-idx="${idx}">
        <button class="schema-table-toggle" type="button"
                aria-expanded="false"
                aria-controls="schema-cols-${idx}">
          <span class="schema-chevron">▶</span>
          <span class="schema-table-icon">⊡</span>
          <span class="schema-table-name">${tableName}</span>
          <span class="schema-col-count">${colCount}</span>
        </button>
        <ul class="schema-columns-list" id="schema-cols-${idx}" role="list">
          ${columnsHtml}
        </ul>
      </li>
    `;
  }).join("");

  els.schemaTableList.querySelectorAll(".schema-table-toggle").forEach(btn => {
    btn.addEventListener("click", handleTableToggle);
  });
}

function handleTableToggle(e) {
  const btn  = e.currentTarget;
  const item = btn.closest(".schema-table-item");
  const isOpen = item.classList.contains("is-open");

  els.schemaTableList.querySelectorAll(".schema-table-item.is-open").forEach(openItem => {
    if (openItem !== item) {
      openItem.classList.remove("is-open");
      openItem.querySelector(".schema-table-toggle").setAttribute("aria-expanded", "false");
    }
  });

  item.classList.toggle("is-open", !isOpen);
  btn.setAttribute("aria-expanded", String(!isOpen));
}

function closeExplorer() {
  els.schemaExplorer.classList.add("hidden");
  updateViewTablesBtn(false);
}

function updateViewTablesBtn(isOpen) {
  const textEl = els.viewTablesBtn.querySelector(".btn-text");
  if (textEl) {
    textEl.textContent = isOpen ? "⊟ Hide Tables" : "⊞ View Tables";
  }
}

function buildFkMap(tables) {
  const map = {};
  tables.forEach(table => {
    const fkCols = new Set();
    (table.foreign_keys || []).forEach(fkStr => {
      const match = fkStr.match(/^(\w+)\s*→/);
      if (match) fkCols.add(match[1]);
    });
    map[table.table_name] = fkCols;
  });
  return map;
}

function buildPkMap(tables) {
  const map = {};
  tables.forEach(table => {
    map[table.table_name] = new Set(table.primary_keys || []);
  });
  return map;
}

// ══════════════════════════════════════════════════════════
//  QUERY
// ══════════════════════════════════════════════════════════

async function handleQuery() {
  const question = els.questionInput.value.trim();

  if (!question || !state.session_id) return;

  resetResultsUI();
  setLoading(els.queryBtn, true);

  try {
    const data = await apiPost("/query", {
      question,
      session_id: state.session_id,
      mode      : state.mode,
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
  els.resultsSection.classList.remove("hidden");

  renderWarnings(data.warnings || []);
  els.sqlOutput.textContent = data.generated_sql || "";

  const rowInfo = data.truncated
    ? `Showing ${data.returned_rows} of ${data.total_rows}+ rows`
    : `${data.row_count} row${data.row_count !== 1 ? "s" : ""} returned`;
  els.resultMeta.textContent = rowInfo;

  renderTable(data.columns || [], data.rows || [], data.truncated);

  if ((data.columns || []).length > 0) {
    storeExportData(data.columns, data.rows || []);
    els.exportToolbar.classList.remove("hidden");
  } else {
    els.exportToolbar.classList.add("hidden");
  }
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

  const thead = `<thead><tr>${columns.map(c =>
    `<th>${escapeHtml(c)}</th>`
  ).join("")}</tr></thead>`;

  const tbody = `<tbody>${rows.map(row =>
    `<tr>${row.map(cell =>
      `<td>${cell === null ? '<span style="color:var(--text-muted)">null</span>' : escapeHtml(String(cell))}</td>`
    ).join("")}</tr>`
  ).join("")}</tbody>`;

  els.tableContainer.innerHTML = `<table>${thead}${tbody}</table>`;

  let metaText = `${rows.length} row${rows.length !== 1 ? "s" : ""}`;
  if (truncated) metaText += ` <span class="truncated-badge">truncated</span>`;
  els.tableMeta.innerHTML = metaText;
}

// ══════════════════════════════════════════════════════════
//  EXPLAIN — on-demand only, called only when user clicks button
// ══════════════════════════════════════════════════════════

async function handleExplain() {
  // Guard: must have a query result to explain
  if (!state.currentSQL || !state.session_id) return;

  // Cache key = the SQL itself (same SQL = same explanation regardless of session)
  const cacheKey = state.currentSQL;

  // Return cached explanation immediately — no LLM call needed
  if (state.explainCache[cacheKey]) {
    showExplanation(state.explainCache[cacheKey]);
    return;
  }

  // Show loading state on button
  setLoading(els.explainBtn, true);
  els.explanationBox.classList.add("hidden");

  try {
    // POST /explain — dedicated endpoint, only hit on user demand
    const data = await apiPost("/explain", {
      question  : state.currentQuestion,
      sql       : state.currentSQL,
      session_id: state.session_id,
      mode      : state.mode,
    });

    const explanation = data.explanation || "No explanation returned.";

    // Cache so repeated clicks are free (no extra LLM calls)
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
  els.explanationBox.classList.add("hidden");
  els.explanationText.textContent = "";
  els.warningsContainer.classList.add("hidden");
  els.warningsContainer.innerHTML = "";
  els.sqlOutput.textContent       = "";
  els.tableContainer.innerHTML    = "";
  els.tableMeta.innerHTML         = "";
  els.resultMeta.textContent      = "";
  els.exportToolbar.classList.add("hidden");
  _exportData = { columns: [], rows: [] };
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
    els.copySqlBtn.textContent = "Copied!";
    setTimeout(() => { els.copySqlBtn.textContent = "Copy"; }, 2000);
  } catch {
    // Clipboard API not available
  }
}

// ══════════════════════════════════════════════════════════
//  UTILITY HELPERS
// ══════════════════════════════════════════════════════════

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatRelativeTime(date) {
  const now  = Date.now();
  const diff = Math.floor((now - date.getTime()) / 1000);

  if (diff < 60)    return "just now";
  if (diff < 3600)  return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`;
  return date.toLocaleDateString();
}

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
//  EXPORT
// ══════════════════════════════════════════════════════════

let _exportData = { columns: [], rows: [] };

function storeExportData(columns, rows) {
  _exportData = { columns, rows };
}

function flashExportMsg(text, type = "success") {
  els.exportMsg.textContent = text;
  els.exportMsg.className   = `status-msg status-msg--${type} export-msg`;
  setTimeout(() => { els.exportMsg.textContent = ""; }, 2500);
}

async function handleCopyTable() {
  const { columns, rows } = _exportData;
  if (!columns.length) return;

  const header = columns.join("\t");
  const body   = rows.map(r => r.map(v => (v === null ? "" : String(v))).join("\t")).join("\n");
  const text   = header + "\n" + body;

  try {
    await navigator.clipboard.writeText(text);
    flashExportMsg("✓ Copied to clipboard");
  } catch {
    flashExportMsg("Clipboard not available", "error");
  }
}

function handleDownloadCSV() {
  const { columns, rows } = _exportData;
  if (!columns.length) return;

  const escape = v => {
    const s = v === null ? "" : String(v);
    return s.includes(",") || s.includes('"') || s.includes("\n")
      ? `"${s.replace(/"/g, '""')}"`
      : s;
  };

  const lines = [
    columns.map(escape).join(","),
    ...rows.map(r => r.map(escape).join(",")),
  ];

  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  triggerDownload(blob, "query_results.csv");
  flashExportMsg("✓ CSV downloaded");
}

function handleDownloadExcel() {
  const { columns, rows } = _exportData;
  if (!columns.length) return;

  const BOM    = "\uFEFF";
  const escape = v => (v === null ? "" : String(v).replace(/\t/g, " "));
  const lines  = [
    columns.map(escape).join("\t"),
    ...rows.map(r => r.map(escape).join("\t")),
  ];

  const blob = new Blob([BOM + lines.join("\n")], { type: "application/vnd.ms-excel;charset=utf-8;" });
  triggerDownload(blob, "query_results.xls");
  flashExportMsg("✓ Excel file downloaded");
}

function triggerDownload(blob, filename) {
  const url  = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href     = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// ══════════════════════════════════════════════════════════
//  EVENT LISTENERS
// ══════════════════════════════════════════════════════════

els.connectBtn.addEventListener("click", handleConnect);
els.apiKey.addEventListener("keydown", e => {
  if (e.key === "Enter") handleConnect();
});

els.queryBtn.addEventListener("click", handleQuery);
els.questionInput.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") handleQuery();
});

els.resetBtn.addEventListener("click", handleReset);
els.refreshSchemaBtn.addEventListener("click", handleRefreshSchema);
els.viewTablesBtn.addEventListener("click", handleViewTables);
els.closeExplorerBtn.addEventListener("click", closeExplorer);

// Explain: fires only on button click — never automatically
els.explainBtn.addEventListener("click", handleExplain);

els.copySqlBtn.addEventListener("click", handleCopySQL);
els.copyTableBtn.addEventListener("click", handleCopyTable);
els.downloadCsvBtn.addEventListener("click", handleDownloadCSV);
els.downloadExcelBtn.addEventListener("click", handleDownloadExcel);

// ══════════════════════════════════════════════════════════
//  INIT — load schema on page load (demo mode, no credentials needed)
// ══════════════════════════════════════════════════════════

(async function init() {
  try {
    const data = await apiGet("/schema");
    renderSchemaInfo(data);
    state.schemaCache = data;
  } catch {
    // Schema not ready yet — fine
  }
})();