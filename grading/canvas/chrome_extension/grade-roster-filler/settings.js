/* global chrome */

const DEFAULT_SETTINGS = {
  rounding: "round", // "round" | "ceil"
  rubric: {
    "60": "F",
    "70": "D",
    "73": "C-",
    "77": "C",
    "80": "C+",
    "83": "B-",
    "87": "B",
    "90": "B+",
    "93": "A-",
    "97": "A",
    inf: "A+"
  },
  rules: [],
  defaultShowAlert: true,
  reviewBeforeApply: false
};

async function loadSettings() {
  const stored = await chrome.storage.sync.get(DEFAULT_SETTINGS);
  return stored;
}

async function saveSettings(settings) {
  await chrome.storage.sync.set(settings);
}

async function resetSettings() {
  await chrome.storage.sync.set(DEFAULT_SETTINGS);
}
