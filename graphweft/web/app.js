const byId = (id) => document.getElementById(id);
const preset = byId("preset");
const operation = byId("operation");
const modelField = byId("model");
const planField = byId("plan");
const runButton = byId("run");
const openButton = byId("open-run");
const saveButton = byId("save-run");
const runFile = byId("run-file");
const status = byId("status");
const results = byId("results");
const findings = byId("finding");
const labels = {
  ordinary: "Ordinary OT",
  constrained: "Graph-bicausal OT",
  candidate: "Supplied plan",
};
const numberFormat = new Intl.NumberFormat("en", { maximumFractionDigits: 5 });
const maxRunBytes = 1024 * 1024;
let examples = [];
let request;
let completedRun;
let reports = {};
let inspectedPlan;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function format(value) {
  if (value === 0) return "0";
  return Math.abs(value) < 0.00001
    ? value.toExponential(2)
    : numberFormat.format(value);
}

function column(row, title) {
  const header = element("th", title);
  header.scope = "col";
  row.append(header);
}

function parse(field, label) {
  try {
    return JSON.parse(field.value);
  } catch {
    byId("inputs").open = true;
    field.focus();
    throw new Error(`Enter valid JSON for the ${label}.`);
  }
}

function updateOperation() {
  const auditing = operation.value === "audit";
  byId("plan-field").hidden = !auditing;
  runButton.textContent = auditing ? "Run audit" : "Run comparison";
}

function fillInputs(input) {
  operation.value = input.operation;
  modelField.value = JSON.stringify(input.model, null, 2);
  planField.value = input.plan ? JSON.stringify(input.plan) : "";
  updateOperation();
}

function selectPreset() {
  const selected = examples.find(({ id }) => id === preset.value);
  fillInputs(selected);
  void runExperiment();
}

function renderGraph(model) {
  const entries = [];
  for (const child of model.nodes) {
    for (const parent of model.parents[child]) {
      entries.push(element("li", `${parent} → ${child}`));
    }
  }
  if (!entries.length) entries.push(element("li", "No directed edges"));
  byId("edges").replaceChildren(...entries);
  byId("graph").hidden = false;
}

function renderMatrix(states, plan, peak, title) {
  const wrapper = element("div", undefined, "matrix-scroll");
  wrapper.tabIndex = 0;
  wrapper.setAttribute("role", "region");
  wrapper.setAttribute("aria-label", `${title} coupling matrix`);

  const table = element("table", undefined, "matrix");
  const headings = table.createTHead().insertRow();
  column(headings, "Source");
  for (const state of states) column(headings, state);

  const body = table.createTBody();
  for (const [index, values] of plan.entries()) {
    const row = body.insertRow();
    const heading = element("th", states[index]);
    heading.scope = "row";
    row.append(heading);
    for (const value of values) {
      const level = Math.ceil(5 * value / peak);
      const cell = element("td", format(value), `mass-${level}`);
      row.append(cell);
    }
  }
  wrapper.append(table);
  return wrapper;
}

function renderPlan(name, entry, states, peak) {
  const title = labels[name];
  const card = element("section", undefined, "plan");
  const header = element("div", undefined, "plan-header");
  const heading = element("h3", title);
  const badge = element("span", entry.audit.admissible ? "Graph-admissible" : "Graph-inadmissible", "badge");
  badge.dataset.admissible = String(entry.audit.admissible);
  if (entry.cost !== undefined) {
    const cost = element("p", undefined, "cost");
    cost.append(element("span", format(entry.cost), "cost-value"), element("span", "Hamming cost"));
    header.append(heading, cost, badge);
  } else {
    header.append(heading, badge);
  }
  card.append(header, renderMatrix(states, entry.plan, peak, title));
  return card;
}

function contexts(values) {
  const entries = Object.entries(values);
  return entries.length ? entries.map(([node, pair]) => `${node} = (${pair.join(", ")})`).join(" · ") : "None";
}

function conditionTitle(failure) {
  if (failure.kind === "history_dependence") return `Node ${failure.node} · History dependence`;
  if (failure.kind === "conditional_marginal") {
    return `Node ${failure.node} · ${failure.side} conditional marginal`;
  }
  return `Joint ${failure.side} marginal`;
}

function probabilityCell(value, className) {
  const cell = element("td", undefined, className);
  const meter = element("meter");
  meter.max = 1;
  meter.value = value;
  meter.setAttribute("aria-hidden", "true");
  cell.append(meter, element("span", format(value)));
  return cell;
}

function renderEvidence() {
  const report = reports[inspectedPlan];
  const failure = report.failures[Number(findings.value)];
  const panel = byId("evidence");
  panel.replaceChildren();
  if (!failure) {
    panel.append(element("p", "The plan passes the joint marginal and graph-bicausality checks.", "passing"));
    return;
  }

  if (failure.kind === "joint_marginal") {
    panel.append(element("p", `The plan’s ${failure.side} marginal differs from the model.`),
      element("p", `Maximum absolute error ${format(failure.max_absolute_error)}`, "context"));
    return;
  }

  const history = failure.kind === "history_dependence";
  const details = element("dl", undefined, "conditioning");
  details.append(element("dt", "Paired parents"), element("dd", contexts(failure.parents)));
  if (history) details.append(element("dt", "Paired history"), element("dd", contexts(failure.history)));
  const title = history
    ? "The paired outcome changes when earlier states outside the parent set are included."
    : `The plan’s conditional distribution differs from the prescribed ${failure.side} distribution.`;

  const table = element("table", undefined, "probabilities");
  const head = table.createTHead().insertRow();
  column(head, history ? "Paired outcome" : "Outcome");
  column(head, history ? "Given paired history" : "In plan");
  column(head, history ? "Given paired parents" : "In model");
  const outcomes = history ? report.pair_outcome_order.map((pair) => pair.join("")) : report.bit_outcome_order;
  const body = table.createTBody();
  for (const [index, outcome] of outcomes.entries()) {
    const row = body.insertRow();
    const heading = element("th", String(outcome));
    heading.scope = "row";
    row.append(heading, probabilityCell(failure.observed[index], "observed"),
      probabilityCell(failure.required[index], "required"));
  }
  panel.append(element("p", title), details, table,
    element("p", `Context mass ${format(failure.context_mass)} · Maximum absolute error ${format(failure.max_absolute_error)}`, "context"));
}

function inspect(name) {
  inspectedPlan = name;
  for (const button of byId("audit-options").children) {
    button.setAttribute("aria-pressed", String(button.dataset.plan === name));
  }
  const report = reports[name];
  const failures = report.failures.length;
  byId("audit-status").textContent = failures
    ? `${failures} failed ${failures === 1 ? "condition" : "conditions"} · tolerance ${format(report.absolute_tolerance)}`
    : `All checks passed · tolerance ${format(report.absolute_tolerance)}`;
  findings.replaceChildren(...report.failures.map((failure, index) => {
    const option = element("option", `${index + 1} · ${conditionTitle(failure)}`);
    option.value = index;
    return option;
  }));
  byId("finding-field").hidden = report.admissible;
  renderEvidence();
}

function renderResult(data, model, mode) {
  const entries = mode === "compare"
    ? [["ordinary", data.ordinary], ["constrained", data.constrained]]
    : [["candidate", data]];
  const peak = Math.max(Number.EPSILON, ...entries.flatMap(([, entry]) => entry.plan.flat()));
  byId("gap").hidden = mode !== "compare";
  if (mode === "compare") byId("gap").textContent = `Cost gap ${format(data.cost_gap)}`;
  byId("plans").replaceChildren(...entries.map(([name, entry]) => renderPlan(name, entry, data.states, peak)));
  byId("plans").classList.toggle("single", mode === "audit");

  reports = Object.fromEntries(entries.map(([name, entry]) => [name, entry.audit]));
  byId("audit-options").replaceChildren(...entries.map(([name]) => {
    const button = element("button", labels[name]);
    button.type = "button";
    button.dataset.plan = name;
    button.addEventListener("click", () => inspect(name));
    return button;
  }));
  byId("audit-options").hidden = mode === "audit";
  inspect(entries[0][0]);
  renderGraph(model);
  results.hidden = false;
}

function clearResult() {
  completedRun = undefined;
  saveButton.disabled = true;
  results.hidden = true;
  byId("graph").hidden = true;
}

async function postRun(path, body, signal) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

async function requestRun(message, load, imported = false) {
  request?.abort();
  const active = new AbortController();
  request = active;
  runButton.disabled = true;
  status.textContent = message;
  status.classList.remove("error");
  clearResult();
  try {
    const run = await load(active.signal);
    if (request !== active) return;
    if (imported) {
      preset.value = "imported";
      fillInputs(run.input);
    }
    renderResult(run.result, run.input.model, run.input.operation);
    completedRun = run;
    saveButton.disabled = false;
    status.textContent = imported ? "Saved run verified." : "";
  } catch (error) {
    if (request !== active) return;
    status.textContent = error.message || "GraphWeft could not complete the operation.";
    status.classList.add("error");
  } finally {
    if (request === active) runButton.disabled = false;
  }
}

function runExperiment() {
  const mode = operation.value;
  return requestRun(mode === "compare" ? "Solving transport…" : "Checking the plan…", (signal) => {
    const payload = { operation: mode, model: parse(modelField, "model") };
    if (mode === "audit") payload.plan = parse(planField, "coupling matrix");
    return postRun("/api/run", JSON.stringify(payload), signal);
  });
}

preset.addEventListener("change", selectPreset);
operation.addEventListener("change", () => {
  request?.abort();
  request = undefined;
  clearResult();
  status.textContent = "";
  runButton.disabled = !examples.length;
  updateOperation();
  if (operation.value === "audit" && !planField.value) byId("inputs").open = true;
});
findings.addEventListener("change", renderEvidence);
byId("experiment").addEventListener("submit", (event) => {
  event.preventDefault();
  void runExperiment();
});
openButton.addEventListener("click", () => runFile.click());
runFile.addEventListener("change", () => {
  const file = runFile.files[0];
  runFile.value = "";
  if (!file) return;
  void requestRun("Verifying saved run…", async (signal) => {
    if (file.size > maxRunBytes) throw new Error("Run files are limited to 1 MiB.");
    return postRun("/api/replay", await file.text(), signal);
  }, true);
});
saveButton.addEventListener("click", () => {
  if (!completedRun) return;
  const file = new Blob([JSON.stringify(completedRun, null, 2) + "\n"], { type: "application/json" });
  if (file.size > maxRunBytes) {
    status.textContent = "This result exceeds the 1 MiB run-file limit.";
    status.classList.add("error");
    return;
  }
  const link = element("a");
  const url = URL.createObjectURL(file);
  link.href = url;
  link.download = `graphweft-${completedRun.input.operation}-${completedRun.manifest.input_sha256.slice(0, 8)}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

try {
  const response = await fetch("/api/examples");
  if (!response.ok) throw new Error("GraphWeft could not load its examples.");
  examples = await response.json();
  for (const example of examples) {
    const option = element("option", example.label);
    option.value = example.id;
    preset.append(option);
  }
  const importedOption = element("option", "Imported run");
  importedOption.value = "imported";
  importedOption.hidden = true;
  preset.append(importedOption);
  preset.disabled = false;
  openButton.disabled = false;
  selectPreset();
} catch (error) {
  status.textContent = error.message || "GraphWeft could not load its examples.";
  status.classList.add("error");
}
