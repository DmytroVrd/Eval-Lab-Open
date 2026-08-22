const API = {
  config: "/api/config",
  testSets: "/test-sets",
  testSet: (id) => `/test-sets/${encodeURIComponent(id)}`,
  cases: (id) => `/test-sets/${encodeURIComponent(id)}/cases`,
  bulkCases: (id) => `/test-sets/${encodeURIComponent(id)}/cases/bulk`,
  runs: "/runs",
  run: (id) => `/runs/${encodeURIComponent(id)}`,
  runResults: (id) => `/runs/${encodeURIComponent(id)}/results`,
  compareRuns: (a, b) => `/runs/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`,
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
  resultsRunId: null,
  compareRunIds: [],
  compareData: null,
  pollTimer: null,
};

const els = {
  apiStatus: document.querySelector("#api-status"),
  configSummary: document.querySelector("#config-summary"),
  resultsNavLink: document.querySelector("#results-nav-link"),
  testSetCount: document.querySelector("#test-set-count"),
  testSetList: document.querySelector("#test-set-list"),
  createTestSetForm: document.querySelector("#create-test-set-form"),
  newTestSetName: document.querySelector("#new-test-set-name"),
  newTestSetDescription: document.querySelector("#new-test-set-description"),
  selectedTitle: document.querySelector("#selected-title"),
  selectedDescription: document.querySelector("#selected-description"),
  clearSelectedCases: document.querySelector("#clear-selected-cases"),
  deleteSelectedSet: document.querySelector("#delete-selected-set"),
  caseCount: document.querySelector("#case-count"),
  runCount: document.querySelector("#run-count"),
  latestStatus: document.querySelector("#latest-status"),
  casePanelNote: document.querySelector("#case-panel-note"),
  bulkCasesForm: document.querySelector("#bulk-cases-form"),
  bulkCasesInput: document.querySelector("#bulk-cases-input"),
  loadSampleCases: document.querySelector("#load-sample-cases"),
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
  currentRunId: document.querySelector("#current-run-id"),
  currentRunStatus: document.querySelector("#current-run-status"),
  currentRunProgress: document.querySelector("#current-run-progress"),
  currentRunScore: document.querySelector("#current-run-score"),
  currentRunUpdated: document.querySelector("#current-run-updated"),
  currentRunProgressBar: document.querySelector("#current-run-progress-bar"),
  stopPolling: document.querySelector("#stop-polling"),
  viewResultsLink: document.querySelector("#view-results-link"),
  resultsTab: document.querySelector("#results-tab"),
  historyTab: document.querySelector("#history-tab"),
  compareTab: document.querySelector("#compare-tab"),
  resultsView: document.querySelector("#results-view"),
  historyView: document.querySelector("#history-view"),
  compareView: document.querySelector("#compare-view"),
  reloadResults: document.querySelector("#reload-results"),
  reloadHistory: document.querySelector("#reload-history"),
  runCompare: document.querySelector("#run-compare"),
  resultsRunMeta: document.querySelector("#results-run-meta"),
  resultsPromptDetail: document.querySelector("#results-prompt-detail"),
  resultsPromptSummary: document.querySelector("#results-prompt-summary"),
  resultsPromptFull: document.querySelector("#results-prompt-full"),
  compareSelectionMeta: document.querySelector("#compare-selection-meta"),
  scoreChart: document.querySelector("#score-chart"),
  scoreChartMeta: document.querySelector("#score-chart-meta"),
  compareRunMeta: document.querySelector("#compare-run-meta"),
  compareSummary: document.querySelector("#compare-summary"),
  resultsBody: document.querySelector("#results-body"),
  historyBody: document.querySelector("#history-body"),
  compareBody: document.querySelector("#compare-body"),
  toastRegion: document.querySelector("#toast-region"),
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  bindEvents();
  setSelectedEnabled(false);
  loadInitialData();
}

function bindEvents() {
  els.createTestSetForm.addEventListener("submit", handleCreateTestSet);
  els.clearSelectedCases.addEventListener("click", handleClearSelectedCases);
  els.deleteSelectedSet.addEventListener("click", handleDeleteSelectedSet);
  els.bulkCasesForm.addEventListener("submit", handleBulkCases);
  els.loadSampleCases.addEventListener("click", loadSampleCases);
  els.clearBulkCases.addEventListener("click", () => {
    els.bulkCasesInput.value = "";
    els.bulkCasesInput.focus();
  });
  els.reloadCases.addEventListener("click", () => loadCasesForSelected(true));
  els.runForm.addEventListener("submit", handleStartRun);
  els.stopPolling.addEventListener("click", stopPolling);
  els.reloadResults.addEventListener("click", () => loadResultsForCurrentRun(true));
  els.reloadHistory.addEventListener("click", () => loadRunsForSelected(true));
  els.runCompare.addEventListener("click", loadCompare);

  [els.resultsTab, els.historyTab, els.compareTab].forEach((tab) => {
    tab.addEventListener("click", () => setActiveView(tab.dataset.view));
  });
}

function loadSampleCases() {
  els.bulkCasesInput.value = [
    "What is retrieval-augmented generation (RAG)?",
    "Why can large language models hallucinate?",
  ].join("\n");
  els.bulkCasesInput.focus();
  showToast("Sample loaded", "Add these cases, then start a run.", "ok");
}

async function loadInitialData() {
  setApiStatus("neutral", "Connecting");
  const results = await Promise.allSettled([loadConfig(), loadTestSets()]);
  const [configResult, setsResult] = results;

  if (configResult.status === "rejected") {
    showToast("Config unavailable", getErrorMessage(configResult.reason), "error");
  }
  if (setsResult.status === "rejected") {
    showToast("Evaluation suites unavailable", getErrorMessage(setsResult.reason), "error");
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
    const queryId = Number(new URLSearchParams(window.location.search).get("set"));
    const requested = state.testSets.find((set) => Number(set.id) === queryId);
    await selectTestSet(requested?.id ?? state.testSets[0].id);
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
  const changed = String(state.selectedTestSetId) !== String(id);
  if (changed) {
    stopPolling(false);
    state.currentRunId = null;
    state.currentRun = null;
    state.results = [];
    state.resultsRunId = null;
  }
  state.selectedTestSetId = id;
  updateRunUrl(id);
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

    adoptLatestRunFromHistory();

    renderSelected();
    renderCases();
    renderHistory();
    renderCurrentRun();
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

async function handleDeleteSelectedSet() {
  if (!state.selectedTestSetId || !state.selectedTestSet) {
    return;
  }

  const name = state.selectedTestSet.name || `Set ${shortId(state.selectedTestSetId)}`;
  const confirmed = window.confirm(
    `Delete "${name}"? This removes its cases, runs, and results.`
  );
  if (!confirmed) {
    return;
  }

  els.deleteSelectedSet.disabled = true;
  try {
    await request(API.testSet(state.selectedTestSetId), { method: "DELETE" });
    showToast("Set deleted", `${name} was removed.`, "ok");
    clearSelection();
    await loadTestSets();
  } catch (error) {
    showToast("Delete failed", getErrorMessage(error), "error");
  } finally {
    els.deleteSelectedSet.disabled = !state.selectedTestSetId;
  }
}

async function handleClearSelectedCases() {
  if (!state.selectedTestSetId || !state.selectedTestSet) {
    return;
  }

  const name = state.selectedTestSet.name || `Set ${shortId(state.selectedTestSetId)}`;
  const confirmed = window.confirm(
    `Clear inputs from "${name}"? This also removes run history for this suite.`
  );
  if (!confirmed) {
    return;
  }

  els.clearSelectedCases.disabled = true;
  try {
    await request(API.cases(state.selectedTestSetId), { method: "DELETE" });
    state.cases = [];
    state.runs = [];
    state.currentRunId = null;
    state.currentRun = null;
    state.results = [];
    state.resultsRunId = null;
    state.compareRunIds = [];
    state.compareData = null;
    showToast("Cases cleared", `${name} is empty now.`, "ok");
    await loadTestSets();
    if (state.selectedTestSetId) {
      await loadSelectedDetails();
    }
  } catch (error) {
    showToast("Clear failed", getErrorMessage(error), "error");
  } finally {
    els.clearSelectedCases.disabled = !state.selectedTestSetId;
  }
}

async function handleBulkCases(event) {
  event.preventDefault();
  if (!ensureSelected()) {
    return;
  }

  const text = els.bulkCasesInput.value.trim();
  if (!text) {
    showToast("No inputs", "Paste one or more inputs before submitting.", "error");
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
    judge_provider: providerForModel(els.runJudge.value.trim(), "openrouter"),
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
    state.currentRun = {
      ...run,
      model: runConfig.model,
      target_model: runConfig.model,
      judge_model: runConfig.judge_model,
      prompt_template: runConfig.prompt_template,
      status: run.status || "pending",
      total: runConfig.max_cases || state.cases.length,
      completed: 0,
    };
    state.results = [];
    state.resultsRunId = null;
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
    adoptLatestRunFromHistory();
    renderSelected();
    renderHistory();
    renderCurrentRun();
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
    state.resultsRunId = state.currentRunId;
    renderResults();
    if (showNotice) {
      showToast("Results reloaded", `${state.results.length} rows`, "ok");
    }
  } catch (error) {
    showToast("Results failed", getErrorMessage(error), "error");
  }
}

async function loadCompare() {
  if (state.compareRunIds.length !== 2) {
    showToast("Pick two runs", "Use History to select run A and run B.", "error");
    setActiveView("history");
    return;
  }
  try {
    const [a, b] = state.compareRunIds;
    state.compareData = await request(API.compareRuns(a, b));
    renderCompare();
    setActiveView("compare");
  } catch (error) {
    showToast("Compare failed", getErrorMessage(error), "error");
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
      state.resultsRunId = state.currentRunId || runId;
      renderResults();
    }

    const status = String(state.currentRun?.status || "").toLowerCase();
    if (["done", "completed", "complete", "finished", "failed", "error", "cancelled", "canceled"].includes(status)) {
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
  const keptModel = fillSelect(els.runModel, models);
  const keptJudge = fillSelect(els.runJudge, judges);

  const preferredModel = firstString(
    config.gemini_configured ? models.find((model) => model.startsWith("gemini/")) : "",
    config.groq_configured ? models.find((model) => model.startsWith("groq/")) : "",
    config.default_model,
    config.model,
    models[0]
  );
  const preferredJudge = firstString(
    config.groq_configured ? judges.find((judge) => judge.startsWith("groq/")) : "",
    config.gemini_configured ? judges.find((judge) => judge.startsWith("gemini/")) : "",
    config.default_judge_model,
    config.judge_model,
    judges[0]
  );
  if (!keptModel && preferredModel) {
    els.runModel.value = preferredModel;
  }
  if (!keptJudge && preferredJudge) {
    els.runJudge.value = preferredJudge;
  }

  const modelCount = models.length ? `${models.length} models` : "Manual model";
  const judgeCount = judges.length ? `${judges.length} judges` : "Manual judge";
  els.configSummary.textContent = `${modelCount} / ${judgeCount}`;
}

function renderTestSets() {
  els.testSetCount.textContent = `${state.testSets.length} ${plural(state.testSets.length, "suite", "suites")}`;
  els.testSetList.innerHTML = "";

  if (state.testSets.length === 0) {
    els.testSetList.appendChild(emptyBlock("No evaluation suites yet"));
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
      typeof testSet.caseCount === "number" ? `${testSet.caseCount} inputs` : null,
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
  els.casePanelNote.textContent = `${caseCount} ${plural(caseCount, "input", "inputs")}`;
}

function renderCases() {
  els.casePreviewBody.innerHTML = "";

  if (state.cases.length === 0) {
    appendEmptyRow(els.casePreviewBody, 1, "No inputs added");
    return;
  }

  state.cases.slice(0, 8).forEach((testCase) => {
    const row = document.createElement("tr");
    appendCell(row, compactValue(testCase.input || testCase.prompt || testCase.name || testCase.raw));
    els.casePreviewBody.appendChild(row);
  });
}

function renderCurrentRun() {
  const run = state.currentRun;
  if (!run) {
    els.stopPolling.hidden = true;
    els.viewResultsLink.hidden = true;
    els.currentRunId.textContent = state.selectedTestSetId ? "No runs for this suite yet" : "Choose a suite to see its latest run";
    els.currentRunStatus.textContent = "Ready";
    els.currentRunProgress.textContent = "—";
    els.currentRunScore.textContent = "-";
    els.currentRunUpdated.textContent = "Not started";
    els.currentRunProgressBar.style.width = "0%";
    syncResultsLinks();
    return;
  }

  const runStatus = String(run.status || "").toLowerCase();
  els.stopPolling.hidden = ["done", "completed", "complete", "finished", "failed", "error", "cancelled", "canceled"].includes(runStatus);
  els.viewResultsLink.hidden = false;

  const total = run.total ?? run.totalCases ?? state.cases.length ?? 0;
  const completed = run.completed ?? run.completedCases ?? state.results.length ?? 0;
  const progress = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;

  els.currentRunId.textContent = `Run ${shortId(run.id || state.currentRunId)} · ${modelForRun(run)}`;
  els.currentRunStatus.textContent = run.status || "Unknown";
  els.currentRunProgress.textContent = `${completed} / ${total}`;
  els.currentRunScore.textContent = formatScore(run.score ?? run.averageScore ?? run.avg_score);
  els.currentRunUpdated.textContent = formatDate(run.updatedAt || run.finishedAt || run.startedAt);
  els.currentRunProgressBar.style.width = `${progress}%`;
  syncResultsLinks();
}

function adoptLatestRunFromHistory() {
  const current = state.runs.find((run) => String(run.id) === String(state.currentRunId));
  const active = state.runs.find((run) => !isTerminalRunStatus(run.status));
  const next = current && !isTerminalRunStatus(current.status) ? current : (active || state.runs[0] || null);
  state.currentRun = next;
  state.currentRunId = next?.id || null;
}

function isTerminalRunStatus(status) {
  return ["done", "completed", "complete", "finished", "failed", "error", "cancelled", "canceled"].includes(String(status || "").toLowerCase());
}

function syncResultsLinks() {
  const url = new URL("/observatory", window.location.origin);
  if (state.selectedTestSetId) url.searchParams.set("set", String(state.selectedTestSetId));
  if (state.currentRunId) url.searchParams.set("run", String(state.currentRunId));
  const href = `${url.pathname}${url.search}`;
  els.resultsNavLink.href = href;
  els.viewResultsLink.href = href;
}

function renderResults() {
  els.resultsBody.innerHTML = "";
  renderResultsMeta();

  if (state.results.length === 0) {
    appendEmptyRow(els.resultsBody, 7, "No results loaded");
    return;
  }

  state.results.forEach((result, index) => {
    const row = document.createElement("tr");
    appendCell(row, result.caseName || result.caseId || String(index + 1));
    appendCell(row, compactValue(result.input));
    appendCell(row, compactValue(result.output));
    appendCell(row, formatScore(result.score));
    appendCell(row, renderSubScores(result), { node: true });

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
  renderScoreChart();
  renderCompareSelectionMeta();

  if (state.runs.length === 0) {
    appendEmptyRow(els.historyBody, 8, "No runs loaded");
    return;
  }

  state.runs.forEach((run) => {
    const row = document.createElement("tr");
    row.className = String(run.id) === String(state.currentRunId) ? "history-row active" : "history-row";
    appendCell(row, shortId(run.id));
    appendCell(row, run.status || "Unknown");
    appendCell(row, modelForRun(run));
    appendCell(row, judgeForRun(run));
    appendCell(row, formatScore(run.score ?? run.averageScore ?? run.avg_score));
    appendCell(row, formatDate(run.startedAt || run.createdAt));

    const compareCell = document.createElement("td");
    const compareButton = document.createElement("button");
    compareButton.type = "button";
    compareButton.className = "button secondary compact";
    compareButton.textContent = compareLabel(run.id);
    compareButton.addEventListener("click", () => {
      toggleCompareRun(run.id);
      renderHistory();
    });
    compareCell.appendChild(compareButton);
    row.appendChild(compareCell);

    const actionCell = document.createElement("td");
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "button secondary compact";
    openButton.textContent = String(run.id) === String(state.currentRunId) ? "Viewing" : "View";
    openButton.addEventListener("click", async () => {
      stopPolling(false);
      state.currentRunId = run.id;
      state.currentRun = run;
      state.results = [];
      state.resultsRunId = null;
      renderCurrentRun();
      renderResults();
      renderHistory();
      setActiveView("results");
      await loadResultsForCurrentRun(false);
    });
    actionCell.appendChild(openButton);
    row.appendChild(actionCell);
    els.historyBody.appendChild(row);
  });
}

function renderCompare() {
  els.compareBody.innerHTML = "";
  els.compareSummary.innerHTML = "";

  const data = state.compareData;
  if (!data) {
    els.compareRunMeta.textContent = "Pick two runs in History";
    appendEmptyRow(els.compareBody, 6, "Select two runs in History");
    return;
  }

  els.compareRunMeta.textContent = `Run ${data.run_a.id} -> Run ${data.run_b.id} / avg delta ${formatDelta(data.avg_delta_score)}`;
  els.compareSummary.append(
    metricCard("Run A", `#${data.run_a.id}`, formatScore(data.run_a.avg_score)),
    metricCard("Run B", `#${data.run_b.id}`, formatScore(data.run_b.avg_score)),
    metricCard("Delta", "score", formatDelta(data.avg_delta_score))
  );

  if (!data.rows?.length) {
    appendEmptyRow(els.compareBody, 6, "No comparable rows");
    return;
  }

  data.rows.forEach((item) => {
    const row = document.createElement("tr");
    const delta = toOptionalNumber(item.delta_score);
    if (delta !== null) {
      row.className = delta < -0.05 ? "compare-down" : delta > 0.05 ? "compare-up" : "";
    }
    appendCell(row, item.test_case_id);
    appendCell(row, compactValue(item.input));
    appendCell(row, compareRunCell(item.output_a, item.score_a, item.reason_a), { node: true });
    appendCell(row, compareRunCell(item.output_b, item.score_b, item.reason_b), { node: true });
    appendCell(row, formatDelta(item.delta_score));
    appendCell(row, renderDeltaScores(item), { node: true });
    els.compareBody.appendChild(row);
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
  state.resultsRunId = null;
  state.compareRunIds = [];
  state.compareData = null;
  stopPolling(false);
  setSelectedEnabled(false);
  els.selectedTitle.textContent = "No set selected";
  els.selectedDescription.textContent = "Select an evaluation suite to begin.";
  els.caseCount.textContent = "0";
  els.runCount.textContent = "0";
  els.latestStatus.textContent = "Idle";
  els.casePanelNote.textContent = "Bulk add";
  renderCases();
  renderCurrentRun();
  renderResults();
  renderHistory();
  syncResultsLinks();
}

function updateRunUrl(id) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("set", String(id));
  else url.searchParams.delete("set");
  window.history.replaceState({}, "", url);
}

function setSelectedEnabled(enabled) {
  [
    els.bulkCasesInput,
    els.bulkCasesForm.querySelector("button[type='submit']"),
    els.loadSampleCases,
    els.clearBulkCases,
    els.reloadCases,
    els.runModel,
    els.runJudge,
    els.runTemperature,
    els.runMaxCases,
    els.runNotes,
    els.runForm.querySelector("button[type='submit']"),
    els.clearSelectedCases,
    els.deleteSelectedSet,
    els.reloadHistory,
  ].forEach((element) => {
    element.disabled = !enabled;
  });
}

function setActiveView(view) {
  const showResults = view === "results";
  const showHistory = view === "history";
  const showCompare = view === "compare";
  els.resultsTab.classList.toggle("active", showResults);
  els.resultsTab.setAttribute("aria-selected", String(showResults));
  els.historyTab.classList.toggle("active", showHistory);
  els.historyTab.setAttribute("aria-selected", String(showHistory));
  els.compareTab.classList.toggle("active", showCompare);
  els.compareTab.setAttribute("aria-selected", String(showCompare));
  els.resultsView.classList.toggle("active", showResults);
  els.historyView.classList.toggle("active", showHistory);
  els.compareView.classList.toggle("active", showCompare);
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
    model: firstString(item.model, item.target_model, item.model_name, config.model),
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
    correctness: toOptionalNumber(item.correctness_score ?? item.correctness),
    relevance: toOptionalNumber(item.relevance_score ?? item.relevance),
    completeness: toOptionalNumber(item.completeness_score ?? item.completeness),
    promptQuality: toOptionalNumber(item.prompt_quality_score ?? item.prompt_quality),
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

function renderResultsMeta() {
  if (!state.currentRunId || !state.currentRun) {
    els.resultsRunMeta.textContent = "No run selected";
    els.resultsPromptDetail.hidden = true;
    els.resultsPromptSummary.textContent = "Prompt: -";
    els.resultsPromptFull.textContent = "";
    return;
  }

  const loading = state.resultsRunId === null && state.results.length === 0 ? "loading results" : "showing results";
  els.resultsRunMeta.textContent = [
    `Run ${shortId(state.currentRunId)}`,
    `Target: ${modelForRun(state.currentRun)}`,
    `Judge: ${judgeForRun(state.currentRun)}`,
    loading,
  ].join(" / ");
  const prompt = promptForRun(state.currentRun);
  els.resultsPromptDetail.hidden = false;
  els.resultsPromptSummary.textContent = `Prompt: ${promptPreviewForRun(state.currentRun)}`;
  els.resultsPromptFull.textContent = prompt;
}

function modelForRun(run) {
  return firstString(run?.target_model, run?.model, run?.model_name, run?.config?.model, "-");
}

function judgeForRun(run) {
  const provider = firstString(run?.judge_provider, run?.config?.judge_provider);
  const model = firstString(run?.judge_model, run?.config?.judge_model);
  if (provider && model) {
    return `${provider}:${model}`;
  }
  return model || provider || "-";
}

function promptPreviewForRun(run) {
  const prompt = promptForRun(run);
  if (!prompt) {
    return "-";
  }
  return truncateText(prompt.replace(/\{input\}/g, "[input]"), 180);
}

function promptForRun(run) {
  return firstString(run?.prompt_template, run?.promptTemplate, run?.config?.prompt_template);
}

function toggleCompareRun(runId) {
  const value = String(runId);
  const existing = state.compareRunIds.findIndex((id) => String(id) === value);
  if (existing >= 0) {
    state.compareRunIds.splice(existing, 1);
  } else {
    if (state.compareRunIds.length >= 2) {
      state.compareRunIds.shift();
    }
    state.compareRunIds.push(runId);
  }
  state.compareData = null;
  renderCompareSelectionMeta();
  renderCompare();
}

function compareLabel(runId) {
  const index = state.compareRunIds.findIndex((id) => String(id) === String(runId));
  if (index === 0) {
    return "A";
  }
  if (index === 1) {
    return "B";
  }
  return "Pick";
}

function renderCompareSelectionMeta() {
  const ids = state.compareRunIds.map((id, index) => `${index === 0 ? "A" : "B"}: #${id}`);
  els.compareSelectionMeta.textContent = ids.length ? ids.join(" / ") : "Select two runs to compare";
}

function renderScoreChart() {
  const doneRuns = [...state.runs]
    .filter((run) => toOptionalNumber(run.score ?? run.avg_score) !== null)
    .reverse();
  els.scoreChart.innerHTML = "";

  if (!doneRuns.length) {
    els.scoreChartMeta.textContent = "No score data yet";
    els.scoreChart.appendChild(emptyBlock("No score data"));
    return;
  }

  els.scoreChartMeta.textContent = `${doneRuns.length} runs`;
  const width = 720;
  const height = 150;
  const pad = 18;
  const points = doneRuns.map((run, index) => {
    const score = toOptionalNumber(run.score ?? run.avg_score) ?? 0;
    const x = doneRuns.length === 1 ? width / 2 : pad + (index * (width - pad * 2)) / (doneRuns.length - 1);
    const y = height - pad - score * (height - pad * 2);
    return { run, score, x, y };
  });

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Average score by run");

  const path = document.createElementNS(svg.namespaceURI, "path");
  path.setAttribute("d", points.map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`).join(" "));
  path.setAttribute("class", "score-line");
  svg.appendChild(path);

  points.forEach((point) => {
    const circle = document.createElementNS(svg.namespaceURI, "circle");
    circle.setAttribute("cx", String(point.x));
    circle.setAttribute("cy", String(point.y));
    circle.setAttribute("r", "4");
    circle.setAttribute("class", "score-point");
    const title = document.createElementNS(svg.namespaceURI, "title");
    title.textContent = `Run ${point.run.id}: ${formatScore(point.score)}`;
    circle.appendChild(title);
    svg.appendChild(circle);
  });

  els.scoreChart.appendChild(svg);
}

function renderSubScores(result) {
  const wrap = document.createElement("div");
  wrap.className = "subscore-list";
  [
    ["C", result.correctness],
    ["R", result.relevance],
    ["Comp", result.completeness],
    ["Prompt", result.promptQuality],
  ].forEach(([label, value]) => {
    const chip = document.createElement("span");
    chip.className = "subscore-chip";
    chip.textContent = `${label} ${formatScore(value)}`;
    wrap.appendChild(chip);
  });
  return wrap;
}

function renderDeltaScores(item) {
  const wrap = document.createElement("div");
  wrap.className = "subscore-list";
  [
    ["Correct", item.delta_correctness],
    ["Rel", item.delta_relevance],
    ["Comp", item.delta_completeness],
    ["Prompt", item.delta_prompt_quality],
  ].forEach(([label, value]) => {
    const chip = document.createElement("span");
    const delta = toOptionalNumber(value);
    chip.className = `subscore-chip ${delta < -0.05 ? "negative" : delta > 0.05 ? "positive" : ""}`;
    chip.textContent = `${label} ${formatDelta(value)}`;
    wrap.appendChild(chip);
  });
  return wrap;
}

function compareRunCell(output, score, reason) {
  const wrap = document.createElement("div");
  wrap.className = "compare-cell";
  const scoreLine = document.createElement("strong");
  scoreLine.textContent = `Score ${formatScore(score)}`;
  const outputLine = document.createElement("p");
  outputLine.textContent = compactValue(output);
  const reasonLine = document.createElement("small");
  reasonLine.textContent = compactValue(reason);
  wrap.append(scoreLine, outputLine, reasonLine);
  return wrap;
}

function metricCard(label, value, metric) {
  const card = document.createElement("div");
  card.className = "compare-metric";
  const title = document.createElement("small");
  title.textContent = label;
  const main = document.createElement("strong");
  main.textContent = value;
  const sub = document.createElement("span");
  sub.textContent = metric;
  card.append(title, main, sub);
  return card;
}

function providerForModel(model, fallback) {
  if (model.startsWith("mock/")) {
    return "mock";
  }
  if (model.startsWith("gemini/")) {
    return "gemini";
  }
  if (model.startsWith("groq/")) {
    return "groq";
  }
  return fallback;
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

function fillSelect(select, values) {
  const previous = select.value;
  select.innerHTML = "";
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });

  if (previous && values.includes(previous)) {
    select.value = previous;
    return true;
  }

  if (values.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No options";
    select.appendChild(option);
  }
  return false;
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

function truncateText(value, maxLength) {
  const text = compactValue(value).replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}...`;
}

function formatScore(value) {
  const number = toOptionalNumber(value);
  if (number === null) {
    return "-";
  }
  return Number.isInteger(number) ? String(number) : number.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function formatDelta(value) {
  const number = toOptionalNumber(value);
  if (number === null) {
    return "-";
  }
  const formatted = formatScore(Math.abs(number));
  return `${number > 0 ? "+" : number < 0 ? "-" : ""}${formatted}`;
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("en-US", {
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

function appendCell(row, value, options = {}) {
  const cell = document.createElement("td");
  if (options.node) {
    cell.appendChild(value);
  } else {
    cell.textContent = value;
  }
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
    showToast("No evaluation suite", "Select or create a suite first.", "error");
    return false;
  }
  return true;
}

function setApiStatus(kind, text) {
  els.apiStatus.className = `status-pill ${kind}`;
  els.apiStatus.textContent = text;
}

function setFormBusy(form, busy) {
  form.querySelectorAll("button, input, select, textarea").forEach((element) => {
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
