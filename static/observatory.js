const API = {
  config: "/api/config",
  testSets: "/test-sets",
  testSet: (id) => `/test-sets/${id}`,
  cases: (id) => `/test-sets/${id}/cases`,
  runs: (id) => `/test-sets/${id}/runs`,
  run: (id) => `/runs/${id}`,
  results: (id) => `/runs/${id}/results`,
  compare: (a, b) => `/runs/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`,
  createRun: "/runs",
};

const state = {
  config: null,
  testSets: [],
  selectedSetId: null,
  cases: [],
  runs: [],
  selectedRunId: null,
  results: [],
  comparison: null,
  filter: "all",
  loadToken: 0,
  pollTimer: null,
  pollingRunId: null,
};

const els = {
  apiStatus: document.querySelector("#obs-api-status"),
  runNavLink: document.querySelector("#obs-run-nav-link"),
  retry: document.querySelector("#obs-retry"),
  testSet: document.querySelector("#obs-test-set"),
  setNote: document.querySelector("#obs-set-note"),
  pageError: document.querySelector("#obs-page-error"),
  pageErrorMessage: document.querySelector("#obs-page-error-message"),
  empty: document.querySelector("#obs-empty"),
  loading: document.querySelector("#obs-loading"),
  content: document.querySelector("#obs-content"),
  runStatus: document.querySelector("#obs-run-status"),
  scoreRing: document.querySelector("#obs-score-ring"),
  scoreValue: document.querySelector("#obs-score-value"),
  verdictKicker: document.querySelector("#obs-verdict-kicker"),
  verdictTitle: document.querySelector("#obs-verdict-title"),
  verdictCopy: document.querySelector("#obs-verdict-copy"),
  passRate: document.querySelector("#obs-pass-rate"),
  coverage: document.querySelector("#obs-coverage"),
  latency: document.querySelector("#obs-latency"),
  dimensionNote: document.querySelector("#obs-dimension-note"),
  dimensions: document.querySelector("#obs-dimensions"),
  promptRun: document.querySelector("#obs-prompt-run"),
  selectedPrompt: document.querySelector("#obs-selected-prompt"),
  promptTarget: document.querySelector("#obs-prompt-target"),
  promptJudge: document.querySelector("#obs-prompt-judge"),
  compareForm: document.querySelector("#obs-compare-form"),
  baselineRun: document.querySelector("#obs-baseline-run"),
  candidateRun: document.querySelector("#obs-candidate-run"),
  compareButton: document.querySelector("#obs-compare-button"),
  compareSummary: document.querySelector("#obs-compare-summary"),
  compareHelp: document.querySelector("#obs-compare-help"),
  compareDetails: document.querySelector("#obs-compare-details"),
  compareCaseCount: document.querySelector("#obs-compare-case-count"),
  baselinePromptLabel: document.querySelector("#obs-baseline-prompt-label"),
  baselinePrompt: document.querySelector("#obs-baseline-prompt"),
  candidatePromptLabel: document.querySelector("#obs-candidate-prompt-label"),
  candidatePrompt: document.querySelector("#obs-candidate-prompt"),
  compareCaseList: document.querySelector("#obs-compare-case-list"),
  providerList: document.querySelector("#obs-provider-list"),
  runtimeNote: document.querySelector("#obs-runtime-note"),
  historyMeta: document.querySelector("#obs-history-meta"),
  runRail: document.querySelector("#obs-run-rail"),
  filters: [...document.querySelectorAll(".obs-filter")],
  caseState: document.querySelector("#obs-case-state"),
  caseList: document.querySelector("#obs-case-list"),
  runForm: document.querySelector("#obs-run-form"),
  model: document.querySelector("#obs-model"),
  judge: document.querySelector("#obs-judge"),
  temperature: document.querySelector("#obs-temperature"),
  maxCases: document.querySelector("#obs-max-cases"),
  prompt: document.querySelector("#obs-prompt"),
  launchState: document.querySelector("#obs-launch-state"),
  liveProgress: document.querySelector("#obs-live-progress"),
  liveLabel: document.querySelector("#obs-live-label"),
  liveCount: document.querySelector("#obs-live-count"),
  liveMeter: document.querySelector("#obs-live-meter"),
  toastRegion: document.querySelector("#obs-toast-region"),
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  bindEvents();
  loadInitialData();
}

function bindEvents() {
  els.retry.addEventListener("click", loadInitialData);
  els.testSet.addEventListener("change", () => selectTestSet(Number(els.testSet.value)));
  els.compareForm.addEventListener("submit", handleCompare);
  els.runForm.addEventListener("submit", handleStartRun);
  els.filters.forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter || "all";
      els.filters.forEach((item) => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      renderCases();
    });
  });
}

async function loadInitialData() {
  stopPolling();
  state.loadToken += 1;
  const token = state.loadToken;
  setInitialLoading(true);
  hidePageError();
  setApiStatus("neutral", "Connecting");

  const [configResult, setsResult] = await Promise.allSettled([
    request(API.config),
    request(API.testSets),
  ]);

  if (token !== state.loadToken) return;

  if (configResult.status === "fulfilled") {
    state.config = configResult.value;
    renderConfig();
  } else {
    state.config = null;
    renderConfig();
  }

  if (setsResult.status === "rejected") {
    setInitialLoading(false);
    showPageError(getErrorMessage(setsResult.reason));
    setApiStatus("error", "Offline");
    return;
  }

  state.testSets = toArray(setsResult.value).map(normalizeTestSet).filter((item) => item.id !== null);
  renderTestSetOptions();

  if (!state.testSets.length) {
    setInitialLoading(false);
    els.empty.hidden = false;
    els.content.hidden = true;
    setApiStatus(configResult.status === "fulfilled" ? "ok" : "warn", configResult.status === "fulfilled" ? "Online" : "Partial");
    return;
  }

  const query = new URLSearchParams(window.location.search);
  const queryId = Number(query.get("set"));
  const queryRunId = Number(query.get("run"));
  const requestedId = state.testSets.some((item) => item.id === queryId)
    ? queryId
    : (state.testSets.some((item) => item.id === state.selectedSetId) ? state.selectedSetId : state.testSets[0].id);

  setApiStatus(configResult.status === "fulfilled" ? "ok" : "warn", configResult.status === "fulfilled" ? "Online" : "Partial");
  await selectTestSet(requestedId, { initial: true, requestedRunId: queryRunId });
}

async function selectTestSet(id, options = {}) {
  if (!Number.isInteger(id)) return;
  stopPolling();
  state.selectedSetId = id;
  state.selectedRunId = null;
  state.results = [];
  state.comparison = null;
  const token = ++state.loadToken;

  renderTestSetOptions();
  updateResultsUrl(id, null);
  els.runNavLink.href = `/?set=${encodeURIComponent(id)}`;
  hidePageError();
  if (!options.initial) setContentBusy(true);

  const [casesResult, runsResult] = await Promise.allSettled([
    request(API.cases(id)),
    request(API.runs(id)),
  ]);

  if (token !== state.loadToken) return;

  state.cases = casesResult.status === "fulfilled"
    ? toArray(casesResult.value).map(normalizeCase)
    : [];
  state.runs = runsResult.status === "fulfilled"
    ? toArray(runsResult.value).map(normalizeRun).sort(sortRunsNewest)
    : [];

  if (casesResult.status === "rejected" && runsResult.status === "rejected") {
    setInitialLoading(false);
    setContentBusy(false);
    showPageError(getErrorMessage(runsResult.reason));
    setApiStatus("error", "Offline");
    return;
  }

  if (casesResult.status === "rejected" || runsResult.status === "rejected") {
    showPageError("Some data is unavailable. Refresh to try the incomplete request again.");
    setApiStatus("warn", "Partial");
  }

  renderRunControls();
  renderTimeline();
  renderSelectedRun();
  setInitialLoading(false);
  setContentBusy(false);
  els.empty.hidden = true;
  els.content.hidden = false;

  const completed = state.runs.filter((run) => run.status === "done");
  const requestedRunId = Number(options.requestedRunId);
  const requestedRun = Number.isInteger(requestedRunId)
    ? state.runs.find((run) => run.id === requestedRunId)
    : null;
  const candidate = requestedRun || completed[0] || state.runs[0] || null;
  if (!candidate) {
    renderCases();
    return;
  }

  const baseline = completed.find((run) => run.id !== candidate.id) || null;
  state.selectedRunId = candidate.id;
  if (candidate.status === "done") els.candidateRun.value = String(candidate.id);
  if (baseline) els.baselineRun.value = String(baseline.id);

  await loadRunResults(candidate.id, { token });
  if (candidate.status === "done" && baseline && token === state.loadToken) {
    await loadComparison(baseline.id, candidate.id, { quiet: true, token });
  }
}

async function loadRunResults(runId, options = {}) {
  const token = options.token ?? state.loadToken;
  state.selectedRunId = runId;
  updateResultsUrl(state.selectedSetId, runId);
  state.comparison = null;
  setCaseState("Loading case evidence…");
  renderTimeline();
  renderSelectedRun();

  try {
    const payload = await request(API.results(runId));
    if (token !== state.loadToken) return;
    state.results = toArray(payload).map(normalizeResult);
    renderSelectedRun();
    renderCases();
  } catch (error) {
    if (token !== state.loadToken) return;
    state.results = [];
    setCaseState(`Could not load results: ${getErrorMessage(error)}`);
    if (!options.quiet) showToast("Results unavailable", getErrorMessage(error), "error");
  }
}

async function handleCompare(event) {
  event.preventDefault();
  const baselineId = Number(els.baselineRun.value);
  const candidateId = Number(els.candidateRun.value);
  await loadComparison(baselineId, candidateId);
}

async function loadComparison(baselineId, candidateId, options = {}) {
  if (!Number.isInteger(baselineId) || !Number.isInteger(candidateId)) {
    showToast("Choose two runs", "Select a baseline and a candidate run.", "error");
    return;
  }
  if (baselineId === candidateId) {
    showToast("Choose different runs", "A run cannot be compared with itself.", "error");
    return;
  }

  const token = options.token ?? state.loadToken;
  setButtonBusy(els.compareButton, true, "Comparing…");
  setCaseState("Comparing case-level signals…");

  try {
    const [comparison, results] = await Promise.all([
      request(API.compare(baselineId, candidateId)),
      request(API.results(candidateId)),
    ]);
    if (token !== state.loadToken) return;
    state.comparison = normalizeComparison(comparison);
    state.results = toArray(results).map(normalizeResult);
    state.selectedRunId = candidateId;
    renderTimeline();
    renderSelectedRun();
    renderCompareSummary();
    renderCases();
    if (!options.quiet) showToast("Comparison ready", "Open the detailed comparison to inspect prompts, outputs, and score changes.", "ok");
  } catch (error) {
    if (token !== state.loadToken) return;
    state.comparison = null;
    renderCompareSummary();
    setCaseState(`Could not compare runs: ${getErrorMessage(error)}`);
    if (!options.quiet) showToast("Comparison failed", getErrorMessage(error), "error");
  } finally {
    setButtonBusy(els.compareButton, false);
  }
}

async function handleStartRun(event) {
  event.preventDefault();
  if (!state.selectedSetId) return;
  if (!state.cases.length) {
    showToast("No inputs to evaluate", "Add at least one input on the Run page first.", "error");
    return;
  }

  const promptTemplate = els.prompt.value.trim();
  if (!promptTemplate.includes("{input}")) {
    showToast("Prompt needs {input}", "Add the {input} placeholder before starting the run.", "error");
    els.prompt.focus();
    return;
  }

  const targetModel = els.model.value;
  const judgeModel = els.judge.value;
  const payload = {
    test_set_id: state.selectedSetId,
    target_model: targetModel,
    judge_model: judgeModel,
    judge_provider: providerForModel(judgeModel),
    prompt_template: promptTemplate,
    temperature: optionalNumber(els.temperature.value),
    max_cases: optionalInteger(els.maxCases.value),
  };

  setFormBusy(els.runForm, true);
  setLaunchState("neutral", "Starting");

  try {
    const queued = await request(API.createRun, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const runId = Number(queued?.run_id ?? queued?.id);
    if (!Number.isInteger(runId)) throw new Error("The API did not return a run id.");
    showToast("Evaluation queued", `Run #${runId} is collecting a fresh signal.`, "ok");
    startPolling(runId);
  } catch (error) {
    setFormBusy(els.runForm, false);
    setLaunchState("error", "Failed");
    showToast("Could not start run", getErrorMessage(error), "error");
  }
}

function startPolling(runId) {
  stopPolling();
  state.pollingRunId = runId;
  els.liveProgress.hidden = false;
  setLaunchState("warn", "Running");
  pollRun(runId);
}

function stopPolling() {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
  state.pollingRunId = null;
}

async function pollRun(runId) {
  if (state.pollingRunId !== runId) return;
  try {
    const run = normalizeRun(await request(API.run(runId)));
    if (state.pollingRunId !== runId) return;
    const total = Math.max(run.totalCount, 0);
    const completed = Math.min(run.doneCount, total || run.doneCount);
    els.liveLabel.textContent = run.status === "pending" ? `Run #${runId} queued` : `Run #${runId} ${run.status}`;
    els.liveCount.textContent = `${completed} / ${total}`;
    els.liveMeter.max = Math.max(total, 1);
    els.liveMeter.value = completed;

    if (run.status === "done" || run.status === "failed") {
      stopPolling();
      setFormBusy(els.runForm, false);
      setLaunchState(run.status === "done" ? "ok" : "error", run.status === "done" ? "Complete" : "Failed");
      showToast(
        run.status === "done" ? "Fresh signal ready" : "Evaluation failed",
        run.status === "done" ? "The timeline and attention queue have been updated." : (run.error || "The run did not complete."),
        run.status === "done" ? "ok" : "error",
      );
      await reloadSelectedSet();
      return;
    }
  } catch (error) {
    stopPolling();
    setFormBusy(els.runForm, false);
    setLaunchState("error", "Poll failed");
    showToast("Run status unavailable", getErrorMessage(error), "error");
    return;
  }

  state.pollTimer = window.setTimeout(() => pollRun(runId), 2200);
}

async function reloadSelectedSet() {
  const id = state.selectedSetId;
  if (!id) return;
  els.liveProgress.hidden = true;
  await selectTestSet(id);
}

function renderConfig() {
  const config = state.config || {};
  const providers = [
    ["OpenRouter", Boolean(config.openrouter_configured), "ready"],
    ["Anthropic", Boolean(config.anthropic_configured), "ready"],
    ["Gemini", Boolean(config.gemini_configured), "ready"],
    ["Groq", Boolean(config.groq_configured), "ready"],
    ["Local mock", Boolean(config.local_mock_without_keys), "mock"],
  ];

  els.providerList.replaceChildren();
  providers.forEach(([name, available, kind]) => {
    const item = element("div", `obs-provider ${available ? kind : ""}`);
    item.append(element("span", "", name), element("i"));
    item.title = available ? `${name} is available` : `${name} is not configured`;
    els.providerList.append(item);
  });

  const fallback = config.fallback_to_mock_judge_on_error ? "Mock fallback is on" : "Mock fallback is off";
  const threshold = numberOrNull(config.pass_threshold);
  els.runtimeNote.textContent = `${fallback}${threshold === null ? "" : ` · pass threshold ${formatScore(threshold)}`}. Provider secrets remain server-side.`;

  fillSelect(els.model, optionList(config.models, [config.default_target_model, "mock/target"]), config.default_target_model);
  fillSelect(els.judge, optionList(config.judge_models, [config.default_judge_model, "mock/judge"]), config.default_judge_model);
}

function renderTestSetOptions() {
  const selected = state.selectedSetId;
  els.testSet.replaceChildren();
  if (!state.testSets.length) {
    const option = element("option", "", "No evaluation suites available");
    option.value = "";
    els.testSet.append(option);
    els.testSet.disabled = true;
    els.setNote.textContent = "Create a set in the dashboard to begin.";
    return;
  }

  els.testSet.disabled = false;
  state.testSets.forEach((testSet) => {
    const option = element("option", "", `${testSet.name} · ${testSet.caseCount} ${testSet.caseCount === 1 ? "case" : "cases"}`);
    option.value = String(testSet.id);
    option.selected = testSet.id === selected;
    els.testSet.append(option);
  });
  const active = state.testSets.find((item) => item.id === selected);
  els.setNote.textContent = active ? `${active.caseCount} cases · created ${formatDate(active.createdAt)}` : "Choose a set to inspect its run history.";
}

function renderRunControls() {
  const completed = state.runs.filter((run) => run.status === "done");
  const previousBaseline = Number(els.baselineRun.value);
  const previousCandidate = Number(els.candidateRun.value);
  fillRunSelect(els.baselineRun, completed, previousBaseline || completed[1]?.id || completed[0]?.id);
  fillRunSelect(els.candidateRun, completed, previousCandidate || completed[0]?.id);
  const comparable = completed.length >= 2;
  els.compareButton.disabled = !comparable;
  els.baselineRun.disabled = !comparable;
  els.candidateRun.disabled = !comparable;
  els.compareHelp.textContent = comparable
    ? "Compare any two completed runs from this set."
    : "Two completed runs are needed for a comparison.";
  renderCompareSummary();
}

function renderTimeline() {
  els.runRail.replaceChildren();
  els.historyMeta.textContent = state.runs.length
    ? `${state.runs.length} ${state.runs.length === 1 ? "run" : "runs"} · newest first`
    : "No runs loaded";

  if (!state.runs.length) {
    els.runRail.append(element("div", "obs-inline-state", state.cases.length ? "No runs yet. Start the first evaluation from this page." : "Add inputs on the Run page before launching an evaluation."));
    return;
  }

  state.runs.slice(0, 14).forEach((run) => {
    const score = numberOrNull(run.avgScore);
    const scorePercent = score === null ? 0 : Math.round(score * 100);
    const button = element("button", `obs-run-card${run.id === state.selectedRunId ? " active" : ""}`);
    button.type = "button";
    button.style.setProperty("--run-score", String(scorePercent));
    button.style.setProperty("--run-color", runColor(run));
    button.disabled = run.status !== "done";
    button.setAttribute("aria-label", `Run ${run.id}, ${run.status}, score ${score === null ? "unavailable" : formatScore(score)}`);

    const top = element("div", "obs-run-card-top");
    top.append(element("strong", "", `Run #${run.id}`), element("span", "", run.status));
    const scoreNode = element("div", "obs-run-score", score === null ? "—" : formatScore(score));
    const model = element("div", "obs-run-model", run.targetModel || "Unknown target");
    const track = element("div", "obs-run-track");
    track.append(element("i"));
    button.append(top, scoreNode, model, track);
    if (run.status === "done") {
      button.addEventListener("click", async () => {
        els.candidateRun.value = String(run.id);
        await loadRunResults(run.id);
        renderCompareSummary();
      });
    }
    els.runRail.append(button);
  });
}

function renderSelectedRun() {
  const run = state.runs.find((item) => item.id === state.selectedRunId) || state.runs.find((item) => item.status === "done") || null;
  const score = numberOrNull(run?.avgScore);
  const scorePercent = score === null ? 0 : Math.round(score * 100);
  els.scoreRing.style.setProperty("--score", String(scorePercent));
  els.scoreRing.setAttribute("aria-label", score === null ? "No score available" : `Overall score ${formatScore(score)} out of 1`);
  els.scoreValue.textContent = score === null ? "—" : formatScore(score);
  setStatusPill(els.runStatus, run?.status || "neutral", run ? `Run #${run.id} · ${run.status}` : "No run");
  els.promptRun.textContent = run ? `Run #${run.id}` : "No run selected";
  els.selectedPrompt.textContent = run?.promptTemplate || "No prompt was recorded for this run.";
  els.promptTarget.textContent = run?.targetModel || "—";
  els.promptJudge.textContent = run?.judgeModel || "—";

  const threshold = numberOrNull(state.config?.pass_threshold) ?? 0.7;
  if (!run || score === null) {
    els.verdictKicker.textContent = "Waiting for evidence";
    els.verdictTitle.textContent = "Run this set to establish a baseline.";
    els.verdictCopy.textContent = "The observatory will combine score, pass rate, coverage, and case-level signals.";
  } else if (score >= Math.max(threshold, 0.85) && (run.passRate ?? 0) >= 0.8) {
    els.verdictKicker.textContent = "Strong signal";
    els.verdictTitle.textContent = "This candidate looks release-ready.";
    els.verdictCopy.textContent = "Quality and pass rate are aligned. Review the attention queue for isolated weak cases.";
  } else if (score >= threshold) {
    els.verdictKicker.textContent = "Promising signal";
    els.verdictTitle.textContent = "Quality clears the configured threshold.";
    els.verdictCopy.textContent = "Inspect low-scoring cases and comparison deltas before treating the change as stable.";
  } else {
    els.verdictKicker.textContent = "Review required";
    els.verdictTitle.textContent = "The latest signal is below threshold.";
    els.verdictCopy.textContent = "Use case evidence and judge dimensions to identify whether the prompt, target, or coverage needs work.";
  }

  els.passRate.textContent = formatPercent(run?.passRate);
  els.coverage.textContent = run ? `${run.doneCount}/${run.totalCount}` : "—";
  const latencies = state.results.map((item) => numberOrNull(item.latencyMs)).filter((value) => value !== null);
  els.latency.textContent = latencies.length ? `${Math.round(average(latencies))} ms` : "—";
  els.dimensionNote.textContent = run ? `Run #${run.id}` : "No completed run";
  renderDimensions();
}

function renderDimensions() {
  const metrics = [
    ["Correctness", "correctnessScore"],
    ["Relevance", "relevanceScore"],
    ["Completeness", "completenessScore"],
    ["Prompt quality", "promptQualityScore"],
  ];
  els.dimensions.replaceChildren();
  metrics.forEach(([label, key]) => {
    const values = state.results.map((item) => numberOrNull(item[key])).filter((value) => value !== null);
    const value = values.length ? average(values) : null;
    const row = element("div", "obs-dimension");
    row.append(element("span", "", label));
    const meter = element("div", "obs-meter");
    const bar = element("i");
    bar.style.setProperty("--value", String(value === null ? 0 : Math.round(value * 100)));
    meter.append(bar);
    row.append(meter, element("strong", "", value === null ? "—" : formatScore(value)));
    els.dimensions.append(row);
  });
}

function renderCompareSummary() {
  const delta = numberOrNull(state.comparison?.avgDeltaScore);
  els.compareSummary.className = "obs-delta neutral";
  if (delta === null) {
    els.compareSummary.textContent = "Select two runs";
    renderCompareDetails();
    return;
  }
  els.compareSummary.textContent = `${delta > 0 ? "+" : ""}${delta.toFixed(3)} average delta`;
  els.compareSummary.classList.remove("neutral");
  els.compareSummary.classList.add(delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral");
  renderCompareDetails();
}

function renderCompareDetails() {
  const comparison = state.comparison;
  els.compareCaseList.replaceChildren();
  if (!comparison) {
    els.compareCaseCount.textContent = "0 cases";
    els.baselinePromptLabel.textContent = "Baseline prompt";
    els.candidatePromptLabel.textContent = "Candidate prompt";
    els.baselinePrompt.textContent = "Choose two runs to compare their prompts.";
    els.candidatePrompt.textContent = "Choose two runs to compare their prompts.";
    return;
  }

  const baselineScore = numberOrNull(comparison.runA?.avg_score);
  const candidateScore = numberOrNull(comparison.runB?.avg_score);
  els.baselinePromptLabel.textContent = `Baseline · Run #${comparison.runA?.id ?? "—"} · ${formatScore(baselineScore)}`;
  els.candidatePromptLabel.textContent = `Candidate · Run #${comparison.runB?.id ?? "—"} · ${formatScore(candidateScore)}`;
  els.baselinePrompt.textContent = comparison.runA?.prompt_template || "No prompt recorded.";
  els.candidatePrompt.textContent = comparison.runB?.prompt_template || "No prompt recorded.";

  const cases = comparisonCases();
  els.compareCaseCount.textContent = `${cases.length} ${cases.length === 1 ? "case" : "cases"}`;
  cases.forEach((item, index) => els.compareCaseList.append(createCaseCard(item, index)));
}

function renderCases() {
  els.caseList.replaceChildren();
  const source = resultCases();
  const filtered = source.filter(matchesFilter);

  if (!state.selectedRunId) {
    setCaseState("Select a completed run to inspect its cases.");
    return;
  }
  if (!source.length) {
    setCaseState("This run has no result rows yet.");
    return;
  }
  if (!filtered.length) {
    setCaseState(`No cases match the “${state.filter}” filter.`);
    return;
  }

  els.caseState.hidden = true;
  filtered.forEach((item, index) => els.caseList.append(createCaseCard(item, index)));
}

function resultCases() {
  return state.results
    .map((result) => ({
      kind: "result",
      id: result.testCaseId,
      input: result.input,
      output: result.output,
      reference: result.reference,
      score: result.score,
      passed: result.passed,
      error: result.error,
      reason: result.judgeReason,
      subscores: result,
    }))
    .sort((a, b) => (a.score ?? 0) - (b.score ?? 0));
}

function comparisonCases() {
  return state.comparison.rows
    .map((row) => ({
      kind: "compare",
      id: row.testCaseId,
      input: row.input,
      reference: row.reference,
      outputA: row.outputA,
      outputB: row.outputB,
      score: row.scoreB,
      scoreA: row.scoreA,
      delta: row.deltaScore,
      passed: row.passedB,
      passedA: row.passedA,
      reasonA: row.reasonA,
      reason: row.reasonB,
      errorA: row.errorA,
      error: row.errorB,
      deltas: row,
    }))
    .sort((a, b) => (a.delta ?? 0) - (b.delta ?? 0));
}

function matchesFilter(item) {
  if (state.filter === "all") return true;
  if (state.filter === "passed") return item.passed === true;
  if (state.filter === "errors") return Boolean(item.error);
  if (state.filter === "attention") {
    return Boolean(item.error) || item.passed === false || (item.delta !== null && item.delta < 0) || (item.passedA === true && item.passed === false);
  }
  return true;
}

function createCaseCard(item, index) {
  const details = element("details", "obs-case");
  const summary = element("summary");
  const indexNode = element("span", "obs-case-index", String(index + 1).padStart(2, "0"));
  const title = element("span", "obs-case-title");
  title.append(
    element("strong", "", truncateText(item.input || "Untitled case", 110)),
    element("span", "", caseSubtitle(item)),
  );

  const scoreText = item.kind === "compare" ? formatDelta(item.delta) : formatScore(item.score);
  const scoreClass = item.kind === "compare"
    ? (item.delta > 0 ? "positive" : item.delta < 0 ? "negative" : "")
    : (item.passed ? "positive" : "negative");
  summary.append(indexNode, title, element("span", `obs-case-score ${scoreClass}`, scoreText));

  const body = element("div", "obs-case-body");
  body.append(casePanel("Input", item.input || "No input recorded", "full"));
  if (item.reference) body.append(casePanel("Reference", item.reference, "full"));
  if (item.kind === "compare") {
    body.append(compareSidePanel("Baseline", item.scoreA, item.passedA, item.outputA, item.reasonA, item.errorA));
    body.append(compareSidePanel("Candidate", item.score, item.passed, item.outputB, item.reason, item.error));
    body.append(compareDeltaPanel(item.deltas));
  } else {
    body.append(casePanel("Model output", item.output || "No output", "full"));
    body.append(casePanel("Judge reason", item.reason || item.error || "No reason recorded", "full"));
    body.append(casePanel("Dimension scores", formatResultSubscores(item.subscores), "full"));
  }
  details.append(summary, body);
  return details;
}

function compareSidePanel(label, score, passed, output, reason, error) {
  const panel = element("section", "obs-compare-side");
  const heading = element("div", "obs-compare-side-heading");
  const failureReason = error || (!output && /failed|error|not exist|access/i.test(String(reason || "")) ? reason : null);
  const status = failureReason ? "Error" : passed === null ? "No result" : passed ? "Passed" : "Failed";
  const statusClass = failureReason || passed === false ? "negative" : passed === true ? "positive" : "neutral";
  heading.append(
    element("strong", "", label),
    element("span", `obs-side-status ${statusClass}`, `${status} · ${formatScore(score)}`),
  );
  panel.append(heading);

  const outputText = output || (failureReason ? "Evaluation failed before an output was produced." : "No result was recorded for this run.");
  panel.append(element("p", "obs-compare-output", outputText));
  if (reason || error) panel.append(element("p", "obs-compare-reason", reason || error));
  return panel;
}

function compareDeltaPanel(row) {
  const panel = element("section", "obs-delta-panel full");
  panel.append(element("small", "", "Dimension changes"));
  const chips = element("div", "obs-delta-chips");
  [
    ["Correctness", row?.deltaCorrectness],
    ["Relevance", row?.deltaRelevance],
    ["Completeness", row?.deltaCompleteness],
    ["Prompt quality", row?.deltaPromptQuality],
  ].forEach(([label, value]) => {
    const delta = numberOrNull(value);
    const chip = element("span", delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral");
    chip.append(element("small", "", label), element("strong", "", formatDelta(delta)));
    chips.append(chip);
  });
  panel.append(chips);
  return panel;
}

function casePanel(label, content, className = "") {
  const panel = element("div", `obs-case-panel ${className}`.trim());
  panel.append(element("small", "", label), element("p", "", String(content)));
  return panel;
}

function caseSubtitle(item) {
  if (item.error) return "Provider or evaluation error";
  if (item.kind === "compare" && item.passedA && !item.passed) return "Pass changed to fail";
  if (item.kind === "compare" && item.delta < 0) return "Regression detected";
  if (item.kind === "compare" && item.delta > 0) return "Improvement detected";
  return item.passed ? "Passed evaluation" : "Needs attention";
}

function setInitialLoading(loading) {
  els.loading.hidden = !loading;
  if (loading) {
    els.content.hidden = true;
    els.empty.hidden = true;
  }
  els.testSet.disabled = loading || !state.testSets.length;
}

function setContentBusy(busy) {
  els.testSet.disabled = busy;
  els.content.setAttribute("aria-busy", String(busy));
  if (busy) setCaseState("Loading the selected evaluation suite…");
}

function showPageError(message) {
  els.pageErrorMessage.textContent = message;
  els.pageError.hidden = false;
}

function hidePageError() {
  els.pageError.hidden = true;
}

function setCaseState(message) {
  els.caseList.replaceChildren();
  els.caseState.textContent = message;
  els.caseState.hidden = false;
}

function setApiStatus(kind, text) {
  setStatusPill(els.apiStatus, kind, text);
}

function setLaunchState(kind, text) {
  setStatusPill(els.launchState, kind, text);
}

function setStatusPill(node, kind, text) {
  node.className = `status-pill ${statusClass(kind)}`;
  node.textContent = text;
}

function statusClass(kind) {
  if (["done", "ok"].includes(kind)) return "ok";
  if (["pending", "running", "warn"].includes(kind)) return "warn";
  if (["failed", "error"].includes(kind)) return "error";
  return "neutral";
}

function setFormBusy(form, busy) {
  form.querySelectorAll("button, input, select, textarea").forEach((control) => {
    control.disabled = busy;
  });
}

function setButtonBusy(button, busy, busyText = "Working…") {
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = state.runs.filter((run) => run.status === "done").length < 2;
  }
}

function showToast(title, message, kind = "neutral") {
  const toast = element("div", `toast ${kind}`);
  toast.append(element("strong", "", title), element("span", "", message));
  els.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 5200);
}

async function request(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const data = response.status === 204
    ? null
    : contentType.includes("application/json")
      ? await response.json()
      : await response.text();
  if (!response.ok) {
    const error = new Error(extractErrorMessage(data) || `Request failed with ${response.status}.`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function extractErrorMessage(data) {
  if (typeof data === "string") return data;
  if (!data || typeof data !== "object") return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item?.msg || item?.message).filter(Boolean).join("; ");
  }
  return data.message || data.error || "";
}

function getErrorMessage(error) {
  return error instanceof Error ? error.message : String(error || "Unknown error");
}

function normalizeTestSet(value) {
  return {
    id: integerOrNull(value?.id),
    name: String(value?.name || "Untitled evaluation suite"),
    caseCount: integerOrNull(value?.case_count ?? value?.caseCount) ?? 0,
    createdAt: value?.created_at ?? value?.createdAt ?? null,
  };
}

function normalizeCase(value) {
  return {
    id: integerOrNull(value?.id),
    input: String(value?.input ?? value?.prompt ?? ""),
    reference: value?.reference ?? null,
  };
}

function normalizeRun(value) {
  return {
    id: integerOrNull(value?.id ?? value?.run_id),
    testSetId: integerOrNull(value?.test_set_id),
    targetModel: String(value?.target_model ?? value?.model ?? ""),
    judgeModel: String(value?.judge_model ?? ""),
    judgeProvider: String(value?.judge_provider ?? ""),
    promptTemplate: String(value?.prompt_template ?? ""),
    status: String(value?.status ?? "pending"),
    avgScore: numberOrNull(value?.avg_score ?? value?.score),
    passRate: numberOrNull(value?.pass_rate),
    error: value?.error ?? null,
    createdAt: value?.created_at ?? null,
    finishedAt: value?.finished_at ?? null,
    doneCount: integerOrNull(value?.done_count ?? value?.completed) ?? 0,
    totalCount: integerOrNull(value?.total_count ?? value?.total) ?? 0,
  };
}

function normalizeResult(value) {
  return {
    id: integerOrNull(value?.id),
    testCaseId: integerOrNull(value?.test_case_id),
    input: String(value?.input ?? ""),
    reference: value?.reference ?? null,
    output: String(value?.output ?? ""),
    score: numberOrNull(value?.score),
    correctnessScore: numberOrNull(value?.correctness_score),
    relevanceScore: numberOrNull(value?.relevance_score),
    completenessScore: numberOrNull(value?.completeness_score),
    promptQualityScore: numberOrNull(value?.prompt_quality_score),
    passed: Boolean(value?.passed),
    judgeReason: String(value?.judge_reason ?? ""),
    latencyMs: numberOrNull(value?.latency_ms),
    error: value?.error ?? null,
  };
}

function normalizeComparison(value) {
  return {
    runA: value?.run_a || {},
    runB: value?.run_b || {},
    avgDeltaScore: numberOrNull(value?.avg_delta_score),
    rows: toArray(value?.rows).map((row) => ({
      testCaseId: integerOrNull(row?.test_case_id),
      input: String(row?.input ?? ""),
      reference: row?.reference ?? null,
      outputA: String(row?.output_a ?? ""),
      outputB: String(row?.output_b ?? ""),
      scoreA: numberOrNull(row?.score_a),
      scoreB: numberOrNull(row?.score_b),
      deltaScore: numberOrNull(row?.delta_score),
      correctnessA: numberOrNull(row?.correctness_a),
      correctnessB: numberOrNull(row?.correctness_b),
      deltaCorrectness: numberOrNull(row?.delta_correctness),
      relevanceA: numberOrNull(row?.relevance_a),
      relevanceB: numberOrNull(row?.relevance_b),
      deltaRelevance: numberOrNull(row?.delta_relevance),
      completenessA: numberOrNull(row?.completeness_a),
      completenessB: numberOrNull(row?.completeness_b),
      deltaCompleteness: numberOrNull(row?.delta_completeness),
      promptQualityA: numberOrNull(row?.prompt_quality_a),
      promptQualityB: numberOrNull(row?.prompt_quality_b),
      deltaPromptQuality: numberOrNull(row?.delta_prompt_quality),
      passedA: row?.passed_a === null ? null : Boolean(row?.passed_a),
      passedB: row?.passed_b === null ? null : Boolean(row?.passed_b),
      reasonA: row?.reason_a ?? null,
      reasonB: row?.reason_b ?? null,
      errorA: row?.error_a ?? null,
      errorB: row?.error_b ?? null,
    })),
  };
}

function fillRunSelect(select, runs, selectedId) {
  select.replaceChildren();
  if (!runs.length) {
    const option = element("option", "", "No completed runs");
    option.value = "";
    select.append(option);
    return;
  }
  runs.forEach((run) => {
    const option = element("option", "", `#${run.id} · ${formatScore(run.avgScore)} · ${shortModel(run.targetModel)}`);
    option.value = String(run.id);
    option.selected = run.id === selectedId;
    select.append(option);
  });
}

function fillSelect(select, values, preferred) {
  select.replaceChildren();
  values.forEach((value) => {
    const option = element("option", "", value);
    option.value = value;
    option.selected = value === preferred;
    select.append(option);
  });
}

function optionList(value, fallbacks) {
  return [...new Set([...toArray(value), ...fallbacks].map(String).filter(Boolean))];
}

function providerForModel(model) {
  if (model.startsWith("mock/")) return "mock";
  if (model.startsWith("gemini/")) return "gemini";
  if (model.startsWith("groq/")) return "groq";
  if (model.toLowerCase().startsWith("claude")) return "anthropic";
  return state.config?.default_judge_provider || "openrouter";
}

function formatResultSubscores(result) {
  return [
    ["Correctness", result.correctnessScore],
    ["Relevance", result.relevanceScore],
    ["Completeness", result.completenessScore],
    ["Prompt quality", result.promptQualityScore],
  ].map(([label, value]) => `${label}: ${formatScore(value)}`).join(" · ");
}

function formatSubscoreDeltas(row) {
  return [
    ["Correctness", row.deltaCorrectness],
    ["Relevance", row.deltaRelevance],
    ["Completeness", row.deltaCompleteness],
    ["Prompt quality", row.deltaPromptQuality],
  ].map(([label, value]) => `${label}: ${formatDelta(value)}`).join(" · ");
}

function element(tag, className = "", text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null) node.textContent = String(text);
  return node;
}

function toArray(value) {
  return Array.isArray(value) ? value : [];
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function integerOrNull(value) {
  const parsed = numberOrNull(value);
  return parsed === null ? null : Math.trunc(parsed);
}

function optionalNumber(value) {
  return value === "" ? null : numberOrNull(value);
}

function optionalInteger(value) {
  return value === "" ? null : integerOrNull(value);
}

function average(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function formatScore(value) {
  const number = numberOrNull(value);
  return number === null ? "—" : number.toFixed(3);
}

function formatDelta(value) {
  const number = numberOrNull(value);
  return number === null ? "—" : `${number > 0 ? "+" : ""}${number.toFixed(3)}`;
}

function formatPercent(value) {
  const number = numberOrNull(value);
  return number === null ? "—" : `${Math.round(number * 100)}%`;
}

function formatDate(value) {
  if (!value) return "unknown date";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "unknown date"
    : new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function shortModel(value) {
  if (!value) return "unknown model";
  const parts = String(value).split("/");
  return parts[parts.length - 1];
}

function truncateText(value, maxLength) {
  const text = String(value || "");
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function sortRunsNewest(a, b) {
  return new Date(b.createdAt || 0).getTime() - new Date(a.createdAt || 0).getTime() || (b.id || 0) - (a.id || 0);
}

function runColor(run) {
  if (run.status === "failed") return "var(--danger)";
  if (["pending", "running"].includes(run.status)) return "var(--warning)";
  const score = numberOrNull(run.avgScore);
  if (score === null) return "var(--text-muted)";
  return score >= (numberOrNull(state.config?.pass_threshold) ?? 0.7) ? "var(--success)" : "var(--danger)";
}

function updateResultsUrl(setId, runId) {
  const url = new URL(window.location.href);
  if (setId) url.searchParams.set("set", String(setId));
  else url.searchParams.delete("set");
  if (runId) url.searchParams.set("run", String(runId));
  else url.searchParams.delete("run");
  window.history.replaceState({}, "", url);
}
