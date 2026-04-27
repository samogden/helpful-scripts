/* global DEFAULT_SETTINGS, loadSettings, saveSettings, resetSettings, jsyaml */

const elRubricJson = document.getElementById("rubricJson");
const elRulesJson = document.getElementById("rulesJson");
const elDefaultShowAlert = document.getElementById("defaultShowAlert");
const elReviewBeforeApply = document.getElementById("reviewBeforeApply");
const elSaveBtn = document.getElementById("saveBtn");
const elResetBtn = document.getElementById("resetBtn");
const elStatus = document.getElementById("status");

function setStatus(text) {
  elStatus.textContent = text;
  if (!text) return;
  window.setTimeout(() => {
    if (elStatus.textContent === text) elStatus.textContent = "";
  }, 2500);
}

function getRoundingValue() {
  const el = document.querySelector('input[name="rounding"]:checked');
  return el ? el.value : "round";
}

function setRoundingValue(value) {
  const v = value === "ceil" ? "ceil" : "round";
  const el = document.querySelector(`input[name="rounding"][value="${v}"]`);
  if (el) el.checked = true;
}

function validateRubric(rubric) {
  if (rubric == null || typeof rubric !== "object" || Array.isArray(rubric)) {
    throw new Error("Rubric must be a JSON object mapping cutoffs to grades.");
  }
  const entries = Object.entries(rubric);
  if (entries.length === 0) throw new Error("Rubric is empty.");

  let hasInf = false;
  for (const [k, v] of entries) {
    const key = String(k).trim();
    if (key.toLowerCase() === "inf") {
      hasInf = true;
    } else if (!Number.isFinite(Number(key))) {
      throw new Error(`Rubric key '${k}' is not a number or 'inf'.`);
    }
    if (typeof v !== "string" || !v.trim()) throw new Error(`Rubric value for '${k}' must be a non-empty string.`);
  }
  if (!hasInf) throw new Error("Rubric must include an 'inf' entry for the top grade.");
}

function validateRules(rules) {
  if (!Array.isArray(rules)) throw new Error("Rules must be a JSON array.");
  for (const [i, rule] of rules.entries()) {
    if (rule == null || typeof rule !== "object" || Array.isArray(rule)) {
      throw new Error(`Rule #${i + 1} must be an object.`);
    }
    const hasColumn = typeof rule.column === "string" && rule.column.trim();
    const hasColumns =
      Array.isArray(rule.columns) && rule.columns.length > 0 && rule.columns.every((c) => typeof c === "string" && c.trim());
    if (!hasColumn && !hasColumns) {
      throw new Error(`Rule #${i + 1} must include 'column' (string) or 'columns' (string list).`);
    }
    if (rule.agg != null) {
      const agg = String(rule.agg).trim().toLowerCase();
      if (!["min", "max", "avg"].includes(agg)) throw new Error(`Rule #${i + 1} has invalid 'agg' (min|max|avg).`);
    }
    if (!Number.isFinite(Number(rule.min))) {
      throw new Error(`Rule #${i + 1} is missing 'min' (number).`);
    }
    if (typeof rule.grade !== "string" || !rule.grade.trim()) {
      throw new Error(`Rule #${i + 1} is missing 'grade' (string).`);
    }
  }
}

function parseJsonOrYaml(text, kind) {
  const raw = String(text || "").trim();
  if (!raw) return kind === "rules" ? [] : {};

  // JSON fast path
  if (raw.startsWith("{") || raw.startsWith("[")) return JSON.parse(raw);

  // YAML fallback (restricted schema: JSON types only)
  const parsed = jsyaml.load(raw, { schema: jsyaml.JSON_SCHEMA });
  if (parsed == null) return kind === "rules" ? [] : {};
  return parsed;
}

function dumpYaml(value) {
  return jsyaml.dump(value, {
    schema: jsyaml.JSON_SCHEMA,
    lineWidth: -1,
    noRefs: true,
    sortKeys: false
  });
}

async function fillFormFromStorage() {
  const settings = await loadSettings();
  setRoundingValue(settings.rounding);
  elRubricJson.value = dumpYaml(settings.rubric ?? DEFAULT_SETTINGS.rubric);
  elRulesJson.value = dumpYaml(settings.rules ?? []);
  elDefaultShowAlert.checked = Boolean(settings.defaultShowAlert);
  elReviewBeforeApply.checked = Boolean(settings.reviewBeforeApply);
}

async function onSave() {
  try {
    const rounding = getRoundingValue();
    const rubric = parseJsonOrYaml(elRubricJson.value, "rubric");
    const rules = parseJsonOrYaml(elRulesJson.value, "rules");
    const defaultShowAlert = Boolean(elDefaultShowAlert.checked);
    const reviewBeforeApply = Boolean(elReviewBeforeApply.checked);

    validateRubric(rubric);
    validateRules(rules);

    await saveSettings({ rounding, rubric, rules, defaultShowAlert, reviewBeforeApply });
    setStatus("Saved.");
  } catch (err) {
    setStatus(`Error: ${err && err.message ? err.message : String(err)}`);
  }
}

async function onReset() {
  await resetSettings();
  await fillFormFromStorage();
  setStatus("Reset to defaults.");
}

elSaveBtn.addEventListener("click", onSave);
elResetBtn.addEventListener("click", onReset);

fillFormFromStorage().catch((e) => setStatus(`Error: ${e.message || String(e)}`));
