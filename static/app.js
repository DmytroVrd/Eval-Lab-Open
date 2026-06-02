const API = {
  config: "/api/config",
  testSets: "/test-sets",
  testSet: (id) => `/test-sets/${encodeURIComponent(id)}`,
  cases: (id) => `/test-sets/${encodeURIComponent(id)}/cases`,
  bulkCases: (id) => `/test-sets/${encodeURIComponent(id)}/cases/bulk`,
  runs: "/runs",
  run: (id) => `/runs/${encodeURIComponent(id)}`,
  runResults: (id) => `/runs/${encodeURIComponent(id)}/results`,
  testSetRuns: (id) => `/test-sets/${encodeURIComponent(id)}/runs`,
};

const state = {
  config: null,
  testSets: [],
  selectedTestSetId: null,
  selectedTestSet: null,
  cases: [],
  runs: [],
  currentRunId: null,
  currentRun: null,
  results: [],
  pollTimer: null,
};

const els = {
  apiStatus: document.querySelector("#api-status"),
  configSummary: document.querySelector("#config-summary"),
  refreshAll: document.querySelector("#refresh-all"),
  refreshTestSets: document.querySelector("#refresh-test-sets"),
  testSetCount: document.querySelector("#test-set-count"),
  testSetList: document.querySelector("#test-set-list"),
  createTestSetForm: document.querySelector("#create-test-set-form"),
  newTestSetName: document.querySelector("#new-test-set-name"),
  newTestSetDescription: document.querySelector("#new-test-set-description"),
  selectedTitle: document.querySelector("#selected-title"),
  selectedDescription: document.querySelector("#selected-description"),
  caseCount: document.querySelector("#case-count"),
  runCount: document.querySelector("#run-count"),
  latestStatus: document.querySelector("#latest-status"),
  casePanelNote: document.querySelector("#case-panel-note"),
  bulkCasesForm: document.querySelector("#bulk-cases-form"),
  bulkCasesInput: document.querySelector("#bulk-cases-input"),
  clearBulkCases: document.querySelector("#clear-bulk-cases"),
  reloadCases: document.querySelector("#reload-cases"),
  casePreviewBody: document.querySelector("#case-preview-body"),
  runForm: document.querySelector("#run-form"),
  runFormNote: document.querySelector("#run-form-note"),
  runModel: document.querySelector("#run-model"),
  runJudge: document.querySelector("#run-judge"),
  runTemperature: document.querySelector("#run-temperature"),
  runMaxCases: document.querySelector("#run-max-cases"),
  runNotes: document.querySelector("#run-notes"),
  modelOptions: document.querySelector("#model-options"),
  judgeOptions: document.querySelector("#judge-options"),
  currentRunId: document.querySelector("#current-run-id"),
  currentRunStatus: document.querySelector("#current-run-status"),
  currentRunProgress: document.querySelector("#current-run-progress"),
  currentRunScore: document.querySelector("#current-run-score"),
  currentRunUpdated: document.querySelector("#current-run-updated"),
  currentRunProgressBar: document.querySelector("#current-run-progress-bar"),
  stopPolling: document.querySelector("#stop-polling"),
  resultsTab: document.querySelector("#results-tab"),
  historyTab: document.querySelector("#history-tab"),
  resultsView: document.querySelector("#results-view"),
  historyView: document.querySelector("#history-view"),
  reloadResults: document.querySelector("#reload-results"),
  reloadHistory: document.querySelector("#reload-history"),
  resultsBody: document.querySelector("#results-body"),
  historyBody: document.querySelector("#history-body"),
  toastRegion: document.querySelector("#toast-region"),
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  bindEvents();
  setSelectedEnabled(false);
  loadInitialData();
}

function bindEvents() {
  els.refreshAll.addEventListener("click", loadInitialData);
  els.refreshTestSets.addEventListener("click", loadTestSets);
  els.createTestSetForm.addEventListener("submit", handleCreateTestSet);
  els.bulkCasesForm.addEventListener("submit", handleBulkCases);
  els.clearBulkCases.addEventListener("click", () => {
    els.bulkCasesInput.value = "";
    els.bulkCasesInput.focus();
  });
  els.reloadCases.addEventListener("click", () => loadCasesForSelected(true));
  els.runForm.addEventListener("submit", handleStartRun);
  els.stopPolling.addEventListener("click", stopPolling);
  els.reloadResults.addEventListener("click", () => loadResultsForCurrentRun(true));
  els.reloadHistory.addEventListener("click", () => loadRunsForSelected(true));

  [els.resultsTab, els.historyTab].forEach((tab) => {
    tab.addEventListener("click", () => setActiveView(tab.dataset.view));
  });
}

async function loadInitialData() {
  setApiStatus("neutral", "Connecting");
  const results = await Promise.allSettled([loadConfig(), loadTestSets()]);
  const [configResult, setsResult] = results;

  if (configResult.status === "rejected") {
    showToast("Config unavailable", getErrorMessage(configResult.reason), "error");
  }
  if (setsResult.status === "rejected") {
    showToast("Test sets unavailable", getErrorMessage(setsResult.reason), "error");
  }

  const failures = results.filter((result) => result.status === "rejected").length;
  if (failures === results.length) {
    setApiStatus("error", "Offline");
  } else if (failures > 0) {
    setApiStatus("warn", "Partial");
  } else {
    setApiStatus("ok", "Online");
  }
}

async function loadConfig() {
  const config = await request(API.config);
  state.config = config || {};
  renderConfig();
  return config;
}

async function loadTestSets() {
  const data = await request(API.testSets);
  state.testSets = toArray(data, ["test_sets", "sets", "items", "data"]).map(normalizeTestSet);
  renderTestSets();

  if (!state.selectedTestSetId && state.testSets.length > 0) {
    await selectTestSet(state.testSets[0].id);
  } else if (state.selectedTestSetId) {
    const exists = state.testSets.some((set) => String(set.id) === String(state.selectedTestSetId));
    if (exists) {
      renderTestSets();
      await loadSelectedDetails();
    } else {
      clearSelection();
    }
  }
}

async function selectTestSet(id) {
  state.selectedTestSetId = id;
  renderTestSets();
  await loadSelectedDetails();
}

async function loadSelectedDetails() {
  if (!state.selectedTestSetId) {
    clearSelection();
    return;
  }

  setSelectedEnabled(true);
  try {
    const [setResult, casesResult, runsResult] = await Promise.allSettled([
      request(API.testSet(state.selectedTestSetId)),
      request(API.cases(state.selectedTestSetId)),
      request(API.testSetRuns(state.selectedTestSetId)),
    ]);

    if (setResult.status === "fulfilled") {
      state.selectedTestSet = normalizeTestSet(setResult.value);
    } else {
      const listed = state.testSets.find((set) => String(set.id) === String(state.selectedTestSetId));
      state.selectedTestSet = listed || null;
      showToast("Set details unavailable", getErrorMessage(setResult.reason), "error");
    }

    if (casesResult.status === "fulfilled") {
      state.cases = toArray(casesResult.value, ["cases", "items", "data"]).map(normalizeCase);
    } else {
      state.cases = [];
      showToast("Cases unavailable", getErrorMessage(casesResult.reason), "error");
    }

    if (runsResult.status === "fulfilled") {
      state.runs = sortRuns(toArray(runsResult.value, ["runs", "items", "data"]).map(normalizeRun));
    } else {
      state.runs = [];
      showToast("Run history unavailable", getErrorMessage(runsResult.reason), "error");
    }

    renderSelected();
    renderCases();
    renderHistory();
  } catch (error) {
    showToast("Selection failed", getErrorMessage(error), "error");
  }
}

async function handleCreateTestSet(event) {
  event.preventDefault();
  const name = els.newTestSetName.value.trim();
  const description = els.newTestSetDescription.value.trim();

  if (!name) {
    showToast("Name required", "Add a name before creating a set.", "error");
    return;
  }

  setFormBusy(els.createTestSetForm, true);
  try {
    const created = await requestWithFallback(API.testSets, {
      payloads: [
        { name, description },
        { title: name, description },
      ],
    });
    els.createTestSetForm.reset();
    await loadTestSets();
    const createdId = getId(created) || findCreatedSetId(name);
    if (createdId) {
      await selectTestSet(createdId);
    }
    showToast("Set created", name, "ok");
  } catch (error) {
    showToast("Create failed", getErrorMessage(error), "error");
  } finally {
    setFormBusy(els.createTestSetForm, false);
  }
}

async function handleBulkCases(event) {
  event.preventDefault();
  if (!ensureSelected()) {
    return;
  }

  const text = els.bulkCasesInput.value.trim();
  if (!text) {
    showToast("No cases", "Paste cases before submitting.", "error");
    return;
  }

  let payloads;
  try {
    payloads = buildBulkPayloads(text);
  } catch (error) {
    showToast("Invalid cases", error.message, "error");
    return;
  }

  setFormBusy(els.bulkCasesForm, true);
  try {
    await requestWithFallback(API.bulkCases(state.selectedTestSetId), payloads);
    els.bulkCasesInput.value = "";
    await loadCasesForSelected(false);
    showToast("Cases added", `${payloads.caseCount} submitted`, "ok");
  } catch (error) {
    showToast("Bulk add failed", getErrorMessage(error), "error");
  } finally {
    setFormBusy(els.bulkCasesForm, false);
  }
}

async function handleStartRun(event) {
  event.preventDefault();
  if (!ensureSelected()) {
    return;
  }

  const runConfig = {
    model: els.runModel.value.trim(),
    judge_model: els.runJudge.value.trim() || null,
    temperature: toOptionalNumber(els.runTemperature.value),
    max_cases: toOptionalInteger(els.runMaxCases.value),
    prompt_template: els.runNotes.value.trim() || "Answer clearly:\n\n{input}",
  };

  if (!runConfig.model) {
    showToast("Model required", "Choose or enter a model.", "error");
    return;
  }

  const flatPayload = {
    test_set_id: state.selectedTestSetId,
    ...runConfig,
  };
  const wrappedPayload = {
    test_set_id: state.selectedTestSetId,
    config: runConfig,
  };

  setFormBusy(els.runForm, true);
  els.runFormNote.textContent = "Starting";
  try {
    const created = await requestWithFallback(API.runs, {
      payloads: [flatPayload, wrappedPayload],
    });
    const run = normalizeRun(created);
    state.currentRunId = run.id || getId(created);
    state.currentRun = run;
    state.results = [];
    renderCurrentRun();
    renderResults();
    await loadRunsForSelected(false);

    if (state.currentRunId) {
      startPolling(state.currentRunId);
      showToast("Run started", shortId(state.currentRunId), "ok");
    } else {
      showToast("Run queued", "No run id returned.", "ok");
    }
  } catch (error) {
    showToast("Run failed", getErrorMessage(error), "error");
  } finally {
    els.runFormNote.textContent = "Ready";
    setFormBusy(els.runForm, false);
  }
}

async function loadCasesForSelected(showNotice) {
  if (!ensureSelected()) {
    return;
  }
  try {
    const data = await request(API.cases(state.selectedTestSetId));
    state.cases = toArray(data, ["cases", "items", "data"]).map(normalizeCase);
    renderSelected();
    renderCases();
    if (showNotice) {
      showToast("Cases reloaded", `${state.cases.length} loaded`, "ok");
    }
  } catch (error) {
    showToast("Cases failed", getErrorMessage(error), "error");
  }
}

async function loadRunsForSelected(showNotice) {
  if (!ensureSelected()) {
    return;
  }
  try {
    const data = await request(API.testSetRuns(state.selectedTestSetId));
    state.runs = sortRuns(toArray(data, ["runs", "items", "data"]).map(normalizeRun));
    renderSelected();
    renderHistory();
    if (showNotice) {
      showToast("History reloaded", `${state.runs.length} runs`, "ok");
    }
  } catch (error) {
    showToast("History failed", getErrorMessage(error), "error");
  }
}

async function loadResultsForCurrentRun(showNotice) {
  if (!state.currentRunId) {
    showToast("No run", "Select or start a run first.", "error");
    return;
  }
  try {
    const data = await request(API.runResults(state.currentRunId));
    state.results = toArray(data, ["results", "items", "data"]).map(normalizeResult);
    renderResults();
    if (showNotice) {
      showToast("Results reloaded", `${state.results.length} rows`, "ok");
    }
  } catch (error) {
    showToast("Results failed", getErrorMessage(error), "error");
  }
}

function startPolling(runId) {
  stopPolling(false);
  pollRun(runId);
  state.pollTimer = window.setInterval(() => pollRun(runId), 2200);
}

function stopPolling(showNotice = true) {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
    if (showNotice) {
      showToast("Polling stopped", "Current run will not auto-refresh.", "ok");
    }
  }
}

async function pollRun(runId) {
  try {
    const [runData, resultsData] = await Promise.allSettled([
      request(API.run(runId)),
      request(API.runResults(runId)),
    ]);

    if (runData.status === "fulfilled") {
      state.currentRun = normalizeRun(runData.value);
      state.currentRunId = state.currentRun.id || runId;
      renderCurrentRun();
    }

    if (resultsData.status === "fulfilled") {
      state.results = toArray(resultsData.value, ["results", "items", "data"]).map(normalizeResult);
      renderResults();
    }

    const status = String(state.currentRun?.status || "").toLowerCase();
    if (["completed", "complete", "finished", "failed", "error", "cancelled", "canceled"].includes(status)) {
      stopPolling(false);
      await loadRunsForSelected(false);
    }
  } catch (error) {
    setApiStatus("warn", "Polling issue");
    showToast("Polling failed", getErrorMessage(error), "error");
  }
}

function renderConfig() {
  const config = state.config || {};
  const models = optionList(config, ["models", "available_models", "model_names"]);
  const judges = optionList(config, ["judge_models", "judges", "evaluator_models"]);
  fillDatalist(els.modelOptions, models);
  fillDatalist(els.judgeOptions, judges);

  const defaultModel = firstString(config.default_model, config.model, models[0]);
  const defaultJudge = firstString(config.default_judge_model, config.judge_model, judges[0]);
  if (!els.runModel.value && defaultModel) {
    els.runModel.value = defaultModel;
  }
  if (!els.runJudge.value && defaultJudge) {
    els.runJudge.value = defaultJudge;
  }

  const modelCount = models.length ? `${models.length} models` : "Manual model";
  const judgeCount = judges.length ? `${judges.length} judges` : "Manual judge";
  els.configSummary.textContent = `${modelCount} / ${judgeCount}`;
}

function renderTestSets() {
  els.testSetCount.textContent = `${state.testSets.length} ${plural(state.testSets.length, "set", "sets")}`;
  els.testSetList.innerHTML = "";

  if (state.testSets.length === 0) {
    els.testSetList.appendChild(emptyBlock("No test sets yet"));
    return;
  }

  state.testSets.forEach((testSet) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "test-set-item";
    button.setAttribute("role", "listitem");
    if (String(testSet.id) === String(state.selectedTestSetId)) {
      button.classList.add("active");
    }
    button.addEventListener("click", () => selectTestSet(testSet.id));

    const title = document.createElement("strong");
    title.textContent = testSet.name || `Set ${shortId(testSet.id)}`;
    const meta = document.createElement("span");
    meta.textContent = [
      typeof testSet.caseCount === "number" ? `${testSet.caseCount} cases` : null,
      formatDate(testSet.createdAt),
    ]
      .filter(Boolean)
      .join(" / ") || "No metadata";

    button.append(title, meta);
    els.testSetList.appendChild(button);
  });
}

function renderSelected() {
  const selected = state.selectedTestSet;
  if (!selected) {
    clearSelection();
    return;
  }

  els.selectedTitle.textContent = selected.name || `Set ${shortId(selected.id)}`;
  els.selectedDescription.textContent = selected.description || "No description";
  const caseCount = state.cases.length || selected.caseCount || 0;
  els.caseCount.textContent = String(caseCount);
  els.runCount.textContent = String(state.runs.length);
  els.latestStatus.textContent = state.runs[0]?.status || "Idle";
  els.casePanelNote.textContent = `${caseCount} ${plural(caseCount, "case", "cases")}`;
}

function renderCases() {
  els.casePreviewBody.innerHTML = "";

  if (state.cases.length === 0) {
    appendEmptyRow(els.casePreviewBody, 2, "No cases loaded");
    return;
  }

  state.cases.slice(0, 8).forEach((testCase) => {
    const row = document.createElement("tr");
    appendCell(row, compactValue(testCase.input || testCase.prompt || testCase.name || testCase.raw));
    appendCell(row, compactValue(testCase.expected || testCase.expected_output || testCase.answer || "-"));
    els.casePreviewBody.appendChild(row);
  });
}

function renderCurrentRun() {
  const run = state.currentRun;
  if (!run) {
    els.currentRunId.textContent = "No active run";
    els.currentRunStatus.textContent = "Idle";
    els.currentRunProgress.textContent = "0 / 0";
    els.currentRunScore.textContent = "-";
    els.currentRunUpdated.textContent = "-";
    els.currentRunProgressBar.style.width = "0%";
    return;
  }

  const total = run.total ?? run.totalCases ?? state.cases.length ?? 0;
  const completed = run.completed ?? run.completedCases ?? state.results.length ?? 0;
  const progress = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;

  els.currentRunId.textContent = `Run ${shortId(run.id || state.currentRunId)}`;
  els.currentRunStatus.textContent = run.status || "Unknown";
  els.currentRunProgress.textContent = `${completed} / ${total}`;
  els.currentRunScore.textContent = formatScore(run.score ?? run.averageScore ?? run.avg_score);
  els.currentRunUpdated.textContent = formatDate(run.updatedAt || run.finishedAt || run.startedAt);
  els.currentRunProgressBar.style.width = `${progress}%`;
}

function renderResults() {
  els.resultsBody.innerHTML = "";

  if (state.results.length === 0) {
    appendEmptyRow(els.resultsBody, 6, "No results loaded");
    return;
  }

  state.results.forEach((result, index) => {
    const row = document.createElement("tr");
    appendCell(row, result.caseName || result.caseId || String(index + 1));
    appendCell(row, compactValue(result.input));
    appendCell(row, compactValue(result.output));
    appendCell(row, formatScore(result.score));

    const passCell = document.createElement("td");
    const passed = normalizeBoolean(result.passed);
    passCell.textContent = passed === null ? "-" : passed ? "Pass" : "Fail";
    passCell.className = passed === false ? "result-fail" : passed === true ? "result-pass" : "";
    row.appendChild(passCell);

    appendCell(row, compactValue(result.notes || result.reason || result.error || "-"));
    els.resultsBody.appendChild(row);
  });
}

function renderHistory() {
  els.historyBody.innerHTML = "";

  if (state.runs.length === 0) {
    appendEmptyRow(els.historyBody, 6, "No runs loaded");
    return;
  }

  state.runs.forEach((run) => {
    const row = document.createElement("tr");
    appendCell(row, shortId(run.id));
    appendCell(row, run.status || "Unknown");
    appendCell(row, run.model || run.config?.model || "-");
    appendCell(row, formatScore(run.score ?? run.averageScore ?? run.avg_score));
    appendCell(row, formatDate(run.startedAt || run.createdAt));

    const actionCell = document.createElement("td");
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "button secondary compact";
    openButton.textContent = "Open";
    openButton.addEventListener("click", async () => {
      state.currentRunId = run.id;
      state.currentRun = run;
      renderCurrentRun();
      await loadResultsForCurrentRun(false);
      setActiveView("results");
    });
    actionCell.appendChild(openButton);
    row.appendChild(actionCell);
    els.historyBody.appendChild(row);
  });
}

function clearSelection() {
  state.selectedTestSetId = null;
  state.selectedTestSet = null;
  state.cases = [];
  state.runs = [];
  state.currentRunId = null;
  state.currentRun = null;
  state.results = [];
  stopPolling(false);
  setSelectedEnabled(false);
  els.selectedTitle.textContent = "No set selected";
  els.selectedDescription.textContent = "Create or select a test set to begin.";
  els.caseCount.textContent = "0";
  els.runCount.textContent = "0";
  els.latestStatus.textContent = "Idle";
  els.casePanelNote.textContent = "Bulk add";
  renderCases();
  renderCurrentRun();
  renderResults();
  renderHistory();
}

function setSelectedEnabled(enabled) {
  [
    els.bulkCasesInput,
    els.bulkCasesForm.querySelector("button[type='submit']"),
    els.clearBulkCases,
    els.reloadCases,
    els.runModel,
    els.runJudge,
    els.runTemperature,
    els.runMaxCases,
    els.runNotes,
    els.runForm.querySelector("button[type='submit']"),
    els.reloadHistory,
  ].forEach((element) => {
    element.disabled = !enabled;
  });
}

function setActiveView(view) {
  const showResults = view === "results";
  els.resultsTab.classList.toggle("active", showResults);
  els.resultsTab.setAttribute("aria-selected", String(showResults));
  els.historyTab.classList.toggle("active", !showResults);
  els.historyTab.setAttribute("aria-selected", String(!showResults));
  els.resultsView.classList.toggle("active", showResults);
  els.historyView.classList.toggle("active", !showResults);
}

async function request(path, options = {}) {
  const init = {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  };

  const response = await fetch(path, init);
  const contentType = response.headers.get("content-type") || "";
  const raw = await response.text();
  const data = raw && contentType.includes("application/json") ? JSON.parse(raw) : raw;

  if (!response.ok) {
    const error = new Error(extractErrorMessage(data) || `${response.status} ${response.statusText}`);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

async function requestWithFallback(path, options) {
  const payloads = Array.isArray(options) ? options : options.payloads;
  let lastError = null;

  for (const payload of payloads) {
    try {
      return await request(path, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    } catch (error) {
      lastError = error;
      if (![400, 415, 422].includes(error.status)) {
        throw error;
      }
    }
  }

  throw lastError;
}

function buildBulkPayloads(text) {
  let parsed;
  const trimmed = text.trim();

  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    parsed = JSON.parse(trimmed);
  } else {
    parsed = text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        if (line.startsWith("{")) {
          try {
            return JSON.parse(line);
          } catch {
            return { input: line };
          }
        }
        return { input: line };
      });
  }

  const cases = Array.isArray(parsed) ? parsed : toArray(parsed, ["cases", "items", "data"]);
  if (!cases.length && parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const payloads = [parsed, { cases: [parsed] }];
    payloads.caseCount = 1;
    return payloads;
  }

  if (!cases.length) {
    throw new Error("Add at least one case.");
  }

  const payloads = [cases, { cases }];
  payloads.caseCount = cases.length;
  return payloads;
}

function normalizeTestSet(value) {
  const item = asObject(value);
  return {
    ...item,
    id: getId(item),
    name: firstString(item.name, item.title, item.slug, item.id),
    description: firstString(item.description, item.notes, ""),
    caseCount: toOptionalInteger(item.case_count ?? item.caseCount ?? item.cases_count ?? item.total_cases),
    createdAt: item.created_at || item.createdAt,
  };
}

function normalizeCase(value) {
  const item = asObject(value);
  return {
    ...item,
    id: getId(item),
    input: firstString(item.input, item.prompt, item.question, item.text, item.user_input, item.raw),
    expected: firstString(item.expected, item.expected_output, item.answer, item.target, item.reference),
    raw: value,
  };
}

function normalizeRun(value) {
  const item = asObject(value);
  const config = asObject(item.config);
  return {
    ...item,
    id: getId(item),
    status: firstString(item.status, item.state, item.phase, "Unknown"),
    model: firstString(item.model, item.model_name, config.model),
    score: toOptionalNumber(item.score ?? item.average_score ?? item.avg_score ?? item.mean_score),
    total: toOptionalInteger(item.total ?? item.total_cases ?? item.case_count),
    completed: toOptionalInteger(item.completed ?? item.completed_cases ?? item.finished_cases),
    createdAt: item.created_at || item.createdAt,
    startedAt: item.started_at || item.startedAt || item.created_at,
    updatedAt: item.updated_at || item.updatedAt,
    finishedAt: item.finished_at || item.finishedAt,
    config,
  };
}

function normalizeResult(value) {
  const item = asObject(value);
  const testCase = asObject(item.case || item.test_case);
  return {
    ...item,
    id: getId(item),
    caseId: firstString(item.case_id, item.test_case_id, testCase.id),
    caseName: firstString(item.case_name, testCase.name, testCase.title),
    input: firstString(item.input, item.prompt, item.question, testCase.input, testCase.prompt),
    output: firstString(item.output, item.actual, item.actual_output, item.response, item.model_output),
    score: toOptionalNumber(item.score ?? item.grade ?? item.value),
    passed: item.passed ?? item.pass ?? item.success,
    notes: firstString(item.notes, item.feedback, item.judge_reason, item.reason, item.explanation),
    reason: item.reason || item.judge_reason,
    error: item.error,
  };
}

function sortRuns(runs) {
  return runs.sort((left, right) => {
    const leftTime = Date.parse(left.startedAt || left.createdAt || left.updatedAt || "") || 0;
    const rightTime = Date.parse(right.startedAt || right.createdAt || right.updatedAt || "") || 0;
    return rightTime - leftTime;
  });
}

function toArray(value, keys = []) {
  if (Array.isArray(value)) {
    return value;
  }
  if (!value || typeof value !== "object") {
    return [];
  }
  for (const key of keys) {
    if (Array.isArray(value[key])) {
      return value[key];
    }
  }
  return [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function optionList(config, keys) {
  for (const key of keys) {
    const value = config?.[key];
    if (Array.isArray(value)) {
      return value
        .map((item) => (typeof item === "string" ? item : item?.name || item?.id || item?.model))
        .filter(Boolean);
    }
  }
  return [];
}

function fillDatalist(datalist, values) {
  datalist.innerHTML = "";
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    datalist.appendChild(option);
  });
}

function getId(value) {
  if (!value || typeof value !== "object") {
    return value;
  }
  return value.id ?? value.uuid ?? value.run_id ?? value.test_set_id ?? value.name;
}

function findCreatedSetId(name) {
  return state.testSets.find((set) => set.name === name)?.id;
}

function firstString(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    if (typeof value === "number") {
      return String(value);
    }
  }
  return "";
}

function toOptionalNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function toOptionalInteger(value) {
  const number = toOptionalNumber(value);
  return number === null ? null : Math.trunc(number);
}

function normalizeBoolean(value) {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    const normalized = value.toLowerCase();
    if (["true", "pass", "passed", "success", "ok"].includes(normalized)) {
      return true;
    }
    if (["false", "fail", "failed", "error", "no"].includes(normalized)) {
      return false;
    }
  }
  return null;
}

function compactValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatScore(value) {
  const number = toOptionalNumber(value);
  if (number === null) {
    return "-";
  }
  return Number.isInteger(number) ? String(number) : number.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function shortId(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const text = String(value);
  return text.length > 10 ? `${text.slice(0, 8)}...` : text;
}

function plural(count, one, many) {
  return count === 1 ? one : many;
}

function appendCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  row.appendChild(cell);
}

function appendEmptyRow(body, colSpan, text) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = colSpan;
  cell.className = "empty-cell";
  cell.textContent = text;
  row.appendChild(cell);
  body.appendChild(row);
}

function emptyBlock(text) {
  const block = document.createElement("div");
  block.className = "empty-cell";
  block.textContent = text;
  return block;
}

function ensureSelected() {
  if (!state.selectedTestSetId) {
    showToast("No test set", "Select or create a set first.", "error");
    return false;
  }
  return true;
}

function setApiStatus(kind, text) {
  els.apiStatus.className = `status-pill ${kind}`;
  els.apiStatus.textContent = text;
}

function setFormBusy(form, busy) {
  form.querySelectorAll("button, input, textarea").forEach((element) => {
    element.disabled = busy;
  });
}

function showToast(title, message, kind = "neutral") {
  const toast = document.createElement("div");
  toast.className = `toast ${kind}`;

  const titleElement = document.createElement("strong");
  titleElement.textContent = title;
  const messageElement = document.createElement("span");
  messageElement.textContent = message;

  toast.append(titleElement, messageElement);
  els.toastRegion.appendChild(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

function getErrorMessage(error) {
  if (!error) {
    return "Unknown error";
  }
  return extractErrorMessage(error.data) || error.message || String(error);
}

function extractErrorMessage(data) {
  if (!data) {
    return "";
  }
  if (typeof data === "string") {
    return data;
  }
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  return data.detail || data.message || data.error || "";
}
