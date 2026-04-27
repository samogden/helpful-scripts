/* global chrome, DEFAULT_SETTINGS, loadSettings, saveSettings, jsyaml */

const elCsvFile = document.getElementById("csvFile");
const elApplyBtn = document.getElementById("applyBtn");
const elExportBtn = document.getElementById("exportBtn");
const elOutput = document.getElementById("output");
const elUseCeilRounding = document.getElementById("useCeilRounding");
const elShowAlert = document.getElementById("showAlert");
const elOptionsLink = document.getElementById("optionsLink");
const elReviewBeforeApply = document.getElementById("reviewBeforeApply");

const elReviewModal = document.getElementById("reviewModal");
const elModalUseCeil = document.getElementById("modalUseCeil");
const elModalShowAlert = document.getElementById("modalShowAlert");
const elModalRules = document.getElementById("modalRules");
const elModalCancelBtn = document.getElementById("modalCancelBtn");
const elModalApplyOnceBtn = document.getElementById("modalApplyOnceBtn");
const elModalSaveApplyBtn = document.getElementById("modalSaveApplyBtn");

function setOutput(text) {
  elOutput.textContent = text;
}

function normalizeId(raw) {
  if (raw == null) return "";
  const digits = String(raw).trim().replace(/\D+/g, "");
  // PeopleSoft often zero-pads; Canvas exports sometimes don't.
  return digits.replace(/^0+/, "");
}

function normalizeNameKey(raw) {
  if (!raw) return "";
  // PeopleSoft example: "Cairo,Bryan A" (sometimes no space after comma)
  // Canvas example: "Cairo, Bryan A"
  const text = String(raw).trim();
  const parts = text.split(",");
  if (parts.length < 2) {
    // Some exports use "First Last" (no comma). Heuristic: first token = first name,
    // remainder = last name (supports compound last names like "Perez Herrera").
    const tokens = text.split(/\s+/).filter(Boolean);
    if (tokens.length >= 2) {
      const first = tokens[0].toLowerCase();
      const last = tokens.slice(1).join(" ").toLowerCase();
      return `${last},${first}`;
    }
    return text.toLowerCase().replace(/\s+/g, " ");
  }
  const last = parts[0].trim().toLowerCase();
  const first = parts
    .slice(1)
    .join(",")
    .trim()
    .split(/\s+/)[0]
    .trim()
    .toLowerCase();
  return `${last},${first}`;
}

function normalizeLast(raw) {
  if (!raw) return "";
  const text = String(raw).trim();
  const last = text.split(",")[0].trim().toLowerCase();
  return last;
}

function normalizeWords(raw) {
  if (!raw) return "";
  return String(raw)
    .toLowerCase()
    .replace(/[\u00A0]/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function nameKeysFromDisplayName(raw) {
  if (!raw) return [];
  const text = String(raw).trim();

  // Prefer comma-separated "Last, First ..." (PeopleSoft)
  if (text.includes(",")) {
    const [left, ...rightParts] = text.split(",");
    const last = normalizeWords(left);
    const right = normalizeWords(rightParts.join(","));
    const first = right.split(" ")[0] || "";

    const keys = [];
    if (last && first) keys.push(`${last},${first}`);

    // Fallback for compound last names: allow matching by first token of last name.
    const lastFirstToken = last.split(" ")[0] || "";
    if (lastFirstToken && first && lastFirstToken !== last) keys.push(`${lastFirstToken},${first}`);

    return Array.from(new Set(keys));
  }

  // Space-separated "First Last [Last...]" (some exports)
  const tokens = normalizeWords(text).split(" ").filter(Boolean);
  if (tokens.length >= 2) {
    const first = tokens[0];
    const last = tokens.slice(1).join(" ");
    const keys = [`${last},${first}`];
    const lastFirstToken = last.split(" ")[0] || "";
    if (lastFirstToken && lastFirstToken !== last) keys.push(`${lastFirstToken},${first}`);
    return Array.from(new Set(keys));
  }

  return [normalizeWords(text)];
}

function lastNamesFromDisplayName(raw) {
  if (!raw) return [];
  const text = String(raw).trim();
  let last = "";
  if (text.includes(",")) {
    last = normalizeWords(text.split(",")[0]);
  } else {
    const tokens = normalizeWords(text).split(" ").filter(Boolean);
    last = tokens.length >= 2 ? tokens.slice(1).join(" ") : normalizeWords(text);
  }
  const variants = [];
  if (last) variants.push(last);
  const firstToken = last.split(" ")[0] || "";
  if (firstToken && firstToken !== last) variants.push(firstToken);
  return Array.from(new Set(variants));
}

function csvParse(text) {
  // Small RFC4180-ish parser: handles quoted fields, commas, and CRLF.
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];

    if (inQuotes) {
      if (ch === '"') {
        const next = text[i + 1];
        if (next === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
      continue;
    }

    if (ch === ",") {
      row.push(field);
      field = "";
      continue;
    }

    if (ch === "\n") {
      row.push(field);
      field = "";
      rows.push(row);
      row = [];
      continue;
    }

    if (ch === "\r") continue;
    field += ch;
  }

  row.push(field);
  rows.push(row);
  return rows;
}

function detectHeaderRowIndex(rows) {
  // Canvas exports sometimes include a couple pre-header lines; search near the top.
  const maxScan = Math.min(rows.length, 12);
  for (let i = 0; i < maxScan; i += 1) {
    const header = (rows[i] || []).map((v) => String(v || "").trim());
    if (header.includes("Student") && header.includes("SIS User ID")) return i;
    if (header.includes("Student") && header.includes("ID")) return i;
    if (header.includes("Name") && (header.includes("SIS User ID") || header.includes("ID"))) return i;
  }
  return 0;
}

function rowsToObjects(rows) {
  const headerRowIndex = detectHeaderRowIndex(rows);
  const header = (rows[headerRowIndex] || []).map((h) => String(h || "").trim());
  const objects = [];
  for (let r = headerRowIndex + 1; r < rows.length; r += 1) {
    const values = rows[r];
    if (!values || values.length === 0) continue;
    const obj = {};
    for (let c = 0; c < header.length; c += 1) obj[header[c]] = values[c] ?? "";
    objects.push(obj);
  }
  return objects;
}

function parseNumber(value) {
  if (value == null) return null;
  const cleaned = String(value).trim().replace(/%$/, "");
  if (!cleaned) return null;
  const num = Number(cleaned);
  return Number.isFinite(num) ? num : null;
}

function parseJsonOrYaml(text, kind) {
  const raw = String(text || "").trim();
  if (!raw) return kind === "rules" ? [] : {};
  if (raw.startsWith("{") || raw.startsWith("[")) return JSON.parse(raw);
  const parsed = jsyaml.load(raw, { schema: jsyaml.JSON_SCHEMA });
  if (parsed == null) return kind === "rules" ? [] : {};
  return parsed;
}

function normalizeColumnKey(key) {
  return String(key || "")
    .toLowerCase()
    .replace(/[\u00A0]/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function buildColumnLookup(headerKeys) {
  const map = Object.create(null);
  for (const key of headerKeys || []) {
    const nk = normalizeColumnKey(key);
    if (!nk) continue;
    if (!map[nk]) map[nk] = key;
  }
  return map;
}

function normalizeRubric(rubric) {
  const raw = rubric && typeof rubric === "object" && !Array.isArray(rubric) ? rubric : DEFAULT_SETTINGS.rubric;
  const entries = Object.entries(raw).map(([k, v]) => [String(k).trim().toLowerCase(), String(v).trim()]);
  const parsed = [];
  for (const [k, v] of entries) {
    if (!v) continue;
    if (k === "inf") {
      parsed.push([Number.POSITIVE_INFINITY, v]);
      continue;
    }
    const n = Number(k);
    if (Number.isFinite(n)) parsed.push([n, v]);
  }
  parsed.sort((a, b) => a[0] - b[0]);
  if (!parsed.some(([n]) => n === Number.POSITIVE_INFINITY)) parsed.push([Number.POSITIVE_INFINITY, "A+"]);
  return parsed;
}

function scoreToLetterGrade(score, rounding, rubricPairs) {
  const rounded = rounding === "ceil" ? Math.ceil(score) : Math.round(score);
  for (const [cutoff, grade] of rubricPairs) {
    if (rounded < cutoff) return grade;
  }
  return rubricPairs.length ? rubricPairs[rubricPairs.length - 1][1] : "A+";
}

function pickGradeFromRow(row, rounding, rubricPairs) {
  const possibleLetterKeys = ["Grade", "Final Grade", "Letter Grade"];
  for (const key of possibleLetterKeys) {
    const val = String(row[key] ?? "").trim();
    if (val && /^[A-DF][+-]?$/.test(val)) return val;
    if (val && /^(I|RP|WU)$/.test(val)) return val;
  }

  const possibleNumericKeys = ["Current Score", "Final Score", "Score", "Grade (% )", "Grade (%)"];
  for (const key of possibleNumericKeys) {
    const n = parseNumber(row[key]);
    if (n != null) return scoreToLetterGrade(n, rounding, rubricPairs);
  }

  return null;
}

function applyOverrideRules(row, baseGrade, rules, columnLookup) {
  if (!rules || rules.length === 0) return baseGrade;
  let grade = baseGrade;

  for (const rule of rules) {
    if (!rule || typeof rule !== "object") continue;
    const agg = String(rule.agg || "avg")
      .trim()
      .toLowerCase();
    const columns = [];
    if (typeof rule.column === "string" && rule.column.trim()) columns.push(rule.column.trim());
    if (Array.isArray(rule.columns)) {
      for (const c of rule.columns) if (typeof c === "string" && c.trim()) columns.push(c.trim());
    }
    if (columns.length === 0) continue;
    const min = Number(rule.min);
    const forced = String(rule.grade || "").trim();
    if (!Number.isFinite(min) || !forced) continue;

    const values = [];
    for (const column of columns) {
      const actualKey = columnLookup ? columnLookup[normalizeColumnKey(column)] : column;
      const value = row[actualKey];
      const n = parseNumber(value);
      if (n == null) continue;
      values.push(n <= 1 && min > 1 ? n * 100 : n);
    }
    if (values.length === 0) continue;

    let combined = values[0];
    if (agg === "min") combined = Math.min(...values);
    else if (agg === "max") combined = Math.max(...values);
    else if (agg === "avg") combined = values.reduce((a, b) => a + b, 0) / values.length;

    if (combined < min) grade = forced;
  }

  return grade;
}

function buildGradeIndex(csvObjects, settings) {
  const gradeById = Object.create(null);
  const gradeByNameKey = Object.create(null);
  const ambiguousNameKeys = new Set();
  const candidatesByLast = Object.create(null);

  const rubricPairs = normalizeRubric(settings.rubric);
  const columnLookup = buildColumnLookup(Object.keys(csvObjects[0] || {}));

  let usable = 0;
  let skipped = 0;

  for (const row of csvObjects) {
    const student = String(row["Student"] ?? row["Name"] ?? "").trim();
    const sisId = row["SIS User ID"] ?? row["ID"] ?? row["SIS ID"] ?? "";

    const baseGrade = pickGradeFromRow(row, settings.rounding, rubricPairs);
    const grade = baseGrade ? applyOverrideRules(row, baseGrade, settings.rules, columnLookup) : null;
    if (!grade) {
      skipped += 1;
      continue;
    }

    usable += 1;

    const idNorm = normalizeId(sisId);
    const nameKeys = nameKeysFromDisplayName(student);
    const lastNorms = lastNamesFromDisplayName(student);

    if (idNorm) gradeById[idNorm] = grade;
    for (const key of nameKeys) {
      if (!key) continue;
      if (ambiguousNameKeys.has(key)) continue;
      const existing = gradeByNameKey[key];
      if (!existing) {
        gradeByNameKey[key] = grade;
      } else if (existing !== grade) {
        delete gradeByNameKey[key];
        ambiguousNameKeys.add(key);
      }
    }

    for (const lastNorm of lastNorms) {
      if (!lastNorm) continue;
      if (!candidatesByLast[lastNorm]) candidatesByLast[lastNorm] = [];
      candidatesByLast[lastNorm].push({ student, grade, idNorm });
    }
  }

  return { gradeById, gradeByNameKey, ambiguousNameKeys: Array.from(ambiguousNameKeys), candidatesByLast, usable, skipped };
}

async function getActiveTabId() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || tab.id == null) throw new Error("No active tab found.");
  return tab.id;
}

function applyGradesInPage(payload) {
  const results = {
    updated: 0,
    unmatched: [],
    ambiguous: [],
    missingOption: [],
    totalRows: 0,
    notFilled: 0
  };

  const OUTLINE_UPDATED = null;
  const OUTLINE_UNMATCHED = "2px solid rgba(220, 38, 38, 0.9)";
  const OUTLINE_AMBIGUOUS = "2px solid rgba(234, 88, 12, 0.9)";
  const OUTLINE_MISSING_OPTION = "2px solid rgba(147, 51, 234, 0.9)";

  function markRow(tr, kind, outline) {
    if (outline) {
      tr.style.outline = outline;
      tr.style.outlineOffset = "-2px";
    }
    tr.setAttribute("data-grade-roster-filler", kind);
  }

  function normId(raw) {
    if (raw == null) return "";
    const digits = String(raw).trim().replace(/\D+/g, "");
    return digits.replace(/^0+/, "");
  }

  function normWords(raw) {
    if (!raw) return "";
    return String(raw)
      .toLowerCase()
      .replace(/[\u00A0]/g, " ")
      .replace(/[^a-z0-9]+/g, " ")
      .trim()
      .replace(/\s+/g, " ");
  }

  function nameKeysFrom(raw) {
    if (!raw) return [];
    const text = String(raw).trim();
    if (text.includes(",")) {
      const [left, ...rightParts] = text.split(",");
      const last = normWords(left);
      const right = normWords(rightParts.join(","));
      const first = right.split(" ")[0] || "";
      const keys = [];
      if (last && first) keys.push(`${last},${first}`);
      const lastFirstToken = last.split(" ")[0] || "";
      if (lastFirstToken && first && lastFirstToken !== last) keys.push(`${lastFirstToken},${first}`);
      return Array.from(new Set(keys));
    }
    const tokens = normWords(text).split(" ").filter(Boolean);
    if (tokens.length >= 2) {
      const first = tokens[0];
      const last = tokens.slice(1).join(" ");
      const keys = [`${last},${first}`];
      const lastFirstToken = last.split(" ")[0] || "";
      if (lastFirstToken && lastFirstToken !== last) keys.push(`${lastFirstToken},${first}`);
      return Array.from(new Set(keys));
    }
    return [normWords(text)];
  }

  function lastNamesFrom(raw) {
    if (!raw) return [];
    const text = String(raw).trim();
    let last = "";
    if (text.includes(",")) last = normWords(text.split(",")[0]);
    else {
      const tokens = normWords(text).split(" ").filter(Boolean);
      last = tokens.length >= 2 ? tokens.slice(1).join(" ") : normWords(text);
    }
    const variants = [];
    if (last) variants.push(last);
    const firstToken = last.split(" ")[0] || "";
    if (firstToken && firstToken !== last) variants.push(firstToken);
    return Array.from(new Set(variants));
  }

  const rowEls = Array.from(document.querySelectorAll('tr[id^="trGRADE_ROSTER$0_row"]'));
  results.totalRows = rowEls.length;

  for (const tr of rowEls) {
    const idSpan = tr.querySelector('span[id^="GRADE_ROSTER_EMPLID$"]');
    const nameLink = tr.querySelector('a[id^="DERIVED_SSSMAIL_EMAIL_ADDR$"]');
    const select = tr.querySelector('select[id^="DERIVED_SR_RSTR_CRSE_GRADE_INPUT$"]');

    const emplid = idSpan ? idSpan.textContent.trim() : "";
    const studentName = nameLink ? nameLink.textContent.trim() : "";

    if (!select) continue;

    const emplidNorm = normId(emplid);
    const nameKeys = nameKeysFrom(studentName);
    const lastNorms = lastNamesFrom(studentName);

    let grade = null;
    let matchType = "";

    if (emplidNorm && payload.gradeById && payload.gradeById[emplidNorm]) {
      grade = payload.gradeById[emplidNorm];
      matchType = "id";
    } else if (payload.gradeByNameKey) {
      for (const key of nameKeys) {
        if (key && payload.gradeByNameKey[key]) {
          grade = payload.gradeByNameKey[key];
          matchType = "name";
          break;
        }
      }
      if (!grade && payload.ambiguousNameKeys) {
        const isAmbiguous = nameKeys.some((k) => payload.ambiguousNameKeys.includes(k));
        if (isAmbiguous) {
          results.ambiguous.push({ emplid, studentName, reason: "ambiguous name key in CSV" });
          markRow(tr, "ambiguous", OUTLINE_AMBIGUOUS);
          continue;
        }
      }
    }

    if (!grade && payload.candidatesByLast) {
      for (const lastNorm of lastNorms) {
        const candidates = payload.candidatesByLast[lastNorm];
        if (!candidates) continue;
        if (candidates.length === 1) {
          grade = candidates[0].grade;
          matchType = "last";
          break;
        }
        if (candidates.length > 1) {
          results.ambiguous.push({ emplid, studentName, reason: "multiple CSV matches for last name" });
          markRow(tr, "ambiguous", OUTLINE_AMBIGUOUS);
          grade = null;
          matchType = "";
          break;
        }
      }
    }

    if (!grade) {
      results.unmatched.push({ emplid, studentName });
      markRow(tr, "unmatched", OUTLINE_UNMATCHED);
      continue;
    }

    const optionExists = Array.from(select.options).some((o) => String(o.value).trim() === grade);
    if (!optionExists) {
      results.missingOption.push({ emplid, studentName, grade });
      markRow(tr, "missingOption", OUTLINE_MISSING_OPTION);
      continue;
    }

    select.value = grade;
    select.dispatchEvent(new Event("input", { bubbles: true }));
    select.dispatchEvent(new Event("change", { bubbles: true }));

    markRow(tr, `updated:${matchType}`, OUTLINE_UPDATED);

    results.updated += 1;
  }

  // Highlight any remaining blank grade dropdown (even if it was not part of roster selector expectations).
  for (const tr of rowEls) {
    const select = tr.querySelector('select[id^="DERIVED_SR_RSTR_CRSE_GRADE_INPUT$"]');
    if (!select) continue;
    const current = String(select.value || "").trim();
    if (!current) {
      results.notFilled += 1;
      if (!tr.getAttribute("data-grade-roster-filler")) {
        markRow(tr, "notFilled", OUTLINE_UNMATCHED);
      }
    }
  }

  if (payload.showAlert) {
    if (results.totalRows === 0) return results;
    const problems = results.unmatched.length + results.ambiguous.length + results.missingOption.length;
    if (problems > 0) {
      alert(
        `Grade Roster Filler finished with issues:\\n` +
          `Updated: ${results.updated}\\n` +
          `Not filled: ${results.notFilled}\\n` +
          `Unmatched: ${results.unmatched.length}\\n` +
          `Ambiguous: ${results.ambiguous.length}\\n` +
          `Missing option: ${results.missingOption.length}`
      );
    } else {
      alert(`Grade Roster Filler updated ${results.updated} rows.`);
    }
  }

  return results;
}

function exportRosterHtml() {
  // Prefer exporting the roster document itself (often inside a PeopleSoft iframe).
  const html = document.documentElement.outerHTML;
  const rowCount = document.querySelectorAll('tr[id^="trGRADE_ROSTER$0_row"]').length;
  const hasRosterSelects = document.querySelectorAll('select[id^="DERIVED_SR_RSTR_CRSE_GRADE_INPUT$"]').length > 0;
  const isRosterDoc = rowCount > 0 || hasRosterSelects;

  if (!isRosterDoc) return { downloaded: false, rowCount: 0 };

  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `roster-export-${new Date().toISOString().replace(/[:.]/g, "-")}.html`;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5_000);
  return { downloaded: true, rowCount };
}

async function onApply() {
  try {
    const file = elCsvFile.files && elCsvFile.files[0];
    if (!file) {
      setOutput("Pick a CSV file first.");
      return;
    }

    const storedSettings = { ...(DEFAULT_SETTINGS || {}), ...(await loadSettings()) };

    if (elReviewBeforeApply.checked) {
      openReviewModal(storedSettings);
      return;
    }

    const runSettings = {
      ...storedSettings,
      rounding: elUseCeilRounding.checked ? "ceil" : "round",
      defaultShowAlert: elShowAlert.checked,
      reviewBeforeApply: elReviewBeforeApply.checked
    };

    await applyWithSettings(runSettings);
  } catch (err) {
    setOutput(`Error: ${err && err.message ? err.message : String(err)}`);
  } finally {
    elApplyBtn.disabled = false;
  }
}

async function onExport() {
  try {
    elExportBtn.disabled = true;
    setOutput("Exporting roster HTML (iframe-aware)...");
    const tabId = await getActiveTabId();
    const injectionResults = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: exportRosterHtml
    });

    const downloads = injectionResults.map((r) => r.result).filter((r) => r && r.downloaded);
    if (downloads.length === 0) {
      setOutput("No roster detected in any frame, so nothing was exported.");
      return;
    }

    const total = downloads.reduce((n, d) => n + (d.rowCount || 0), 0);
    setOutput(`Export triggered (check your downloads).\nRoster rows in exported doc(s): ${total}`);
  } catch (err) {
    setOutput(`Error: ${err && err.message ? err.message : String(err)}`);
  } finally {
    elExportBtn.disabled = false;
  }
}

elApplyBtn.addEventListener("click", onApply);
elExportBtn.addEventListener("click", onExport);

elOptionsLink.addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

function openReviewModal(storedSettings) {
  elModalUseCeil.checked = (storedSettings.rounding || "round") === "ceil";
  elModalShowAlert.checked = storedSettings.defaultShowAlert !== false;
  elModalRules.value = jsyaml.dump(storedSettings.rules || [], {
    schema: jsyaml.JSON_SCHEMA,
    lineWidth: -1,
    noRefs: true,
    sortKeys: false
  });
  elReviewModal.classList.add("open");
}

function closeReviewModal() {
  elReviewModal.classList.remove("open");
}

async function applyWithSettings(settings) {
  const file = elCsvFile.files && elCsvFile.files[0];
  if (!file) {
    setOutput("Pick a CSV file first.");
    return;
  }

  elApplyBtn.disabled = true;
  try {
    setOutput("Reading CSV...");

    const text = await file.text();
    const rows = csvParse(text);
    const csvObjects = rowsToObjects(rows);
    const index = buildGradeIndex(csvObjects, settings);

    if (index.usable === 0) {
      setOutput(
        "No usable grade rows found in that CSV.\n" +
          "Expected either a letter-grade column (e.g. 'Grade') or a numeric score column (e.g. 'Current Score')."
      );
      return;
    }

    setOutput(`Parsed CSV rows: usable=${index.usable}, skipped=${index.skipped}\nApplying to page...`);

    const tabId = await getActiveTabId();
    const injectionResults = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: applyGradesInPage,
      args: [
        {
          gradeById: index.gradeById,
          gradeByNameKey: index.gradeByNameKey,
          ambiguousNameKeys: index.ambiguousNameKeys,
          candidatesByLast: index.candidatesByLast,
          showAlert: settings.defaultShowAlert !== false
        }
      ]
    });

    const frameResults = injectionResults.map((r) => r.result).filter(Boolean);
    if (frameResults.length === 0) {
      setOutput("No results returned from page script.");
      return;
    }

    const combined = {
      totalRows: 0,
      updated: 0,
      unmatched: [],
      ambiguous: [],
      missingOption: [],
      notFilled: 0
    };

    for (const fr of frameResults) {
      combined.totalRows += fr.totalRows || 0;
      combined.updated += fr.updated || 0;
      combined.unmatched.push(...(fr.unmatched || []));
      combined.ambiguous.push(...(fr.ambiguous || []));
      combined.missingOption.push(...(fr.missingOption || []));
      combined.notFilled += fr.notFilled || 0;
    }

    const summarize = (arr, label) => {
      if (!arr || arr.length === 0) return "";
      const head = arr
        .slice(0, 8)
        .map((x) => `- ${x.studentName || "(no name)"} (${x.emplid || "no id"})${x.grade ? ` -> ${x.grade}` : ""}`)
        .join("\n");
      const more = arr.length > 8 ? `\n...and ${arr.length - 8} more` : "";
      return `${label}: ${arr.length}\n${head}${more}\n`;
    };

    const summary =
      `Done.\n` +
      `Frames scanned: ${frameResults.length}\n` +
      `Found roster rows: ${combined.totalRows}\n` +
      `Updated: ${combined.updated}\n` +
      `Not filled: ${combined.notFilled}\n` +
      (combined.totalRows === 0
        ? "No roster rows found. This page may render the roster in a different grid or after a navigation step.\n"
        : "") +
      summarize(combined.unmatched, "Unmatched") +
      summarize(combined.ambiguous, "Ambiguous") +
      summarize(combined.missingOption, "Missing option");

    setOutput(summary.trim());
  } finally {
    elApplyBtn.disabled = false;
  }
}

elReviewModal.addEventListener("click", (e) => {
  if (e.target === elReviewModal) closeReviewModal();
});
elModalCancelBtn.addEventListener("click", closeReviewModal);
elModalApplyOnceBtn.addEventListener("click", async () => {
  try {
    const storedSettings = { ...(DEFAULT_SETTINGS || {}), ...(await loadSettings()) };
    const rules = parseJsonOrYaml(elModalRules.value, "rules");
    const runSettings = {
      ...storedSettings,
      rounding: elModalUseCeil.checked ? "ceil" : "round",
      defaultShowAlert: elModalShowAlert.checked,
      rules
    };
    closeReviewModal();
    await applyWithSettings(runSettings);
  } catch (err) {
    setOutput(`Error: ${err && err.message ? err.message : String(err)}`);
  }
});
elModalSaveApplyBtn.addEventListener("click", async () => {
  try {
    const storedSettings = { ...(DEFAULT_SETTINGS || {}), ...(await loadSettings()) };
    const rules = parseJsonOrYaml(elModalRules.value, "rules");
    const newSettings = {
      ...storedSettings,
      rounding: elModalUseCeil.checked ? "ceil" : "round",
      defaultShowAlert: elModalShowAlert.checked,
      reviewBeforeApply: true,
      rules
    };
    await saveSettings(newSettings);
    closeReviewModal();
    await applyWithSettings(newSettings);
  } catch (err) {
    setOutput(`Error: ${err && err.message ? err.message : String(err)}`);
  }
});

elReviewBeforeApply.addEventListener("change", async () => {
  try {
    const storedSettings = { ...(DEFAULT_SETTINGS || {}), ...(await loadSettings()) };
    await saveSettings({ ...storedSettings, reviewBeforeApply: elReviewBeforeApply.checked });
  } catch {
    // ignore
  }
});

// Preload user defaults (best-effort).
(async () => {
  try {
    const settings = { ...(DEFAULT_SETTINGS || {}), ...(await loadSettings()) };
    elUseCeilRounding.checked = settings.rounding === "ceil";
    elShowAlert.checked = settings.defaultShowAlert !== false;
    elReviewBeforeApply.checked = settings.reviewBeforeApply === true;
  } catch {
    // ignore
  }
})();
