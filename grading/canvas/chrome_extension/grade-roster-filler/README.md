# Grade Roster Filler (Chrome Extension)

Fills PeopleSoft grade roster dropdowns from a CSV (e.g., a Canvas export), without copying HTML snippets around.

## Install (Developer mode)

1. Chrome → `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select `chrome_extension/grade-roster-filler`

## Use

1. Open the grade roster page (the one with the student rows and grade dropdowns).
2. Click the extension icon.
3. Pick your CSV.
4. Click **Apply to page**.

Matching order:
1. Student ID (PeopleSoft `EMPLID` ↔ CSV `SIS User ID`, after stripping non-digits and leading zeros)
2. Name key (`Last,First`) (also supports CSV names like `First Last` via heuristic)
3. Last-name-only (only if it uniquely identifies one CSV row)

## Bootstrap / debugging

PeopleSoft often renders the roster inside an iframe. The extension now scans all frames, and **Export page HTML** will try to export the roster-frame HTML (not just the portal shell). If it still can’t find rows, use export and drop the HTML into `example_files/` so we can adjust selectors.
