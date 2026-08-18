#!/usr/bin/env node
/*
 * Generate web/static/hl7ref/tables.json — the HL7 value tables (code → meaning)
 * used by the web message inspector to decode coded fields such as ORC-5
 * (HL7 table 0038, "Order status": CA = "Order was canceled", …).
 *
 * hl7apy (used by generate_hl7_reference.py for the structural definitions)
 * enumerates the valid codes of a table but NOT their descriptions, so the
 * descriptions come from the `hl7-dictionary` npm package (MIT). Like the
 * structural reference, this is a BUILD-TIME step only: the JSON is committed
 * and served as a static asset, so the running app needs neither package.
 *
 * hl7-dictionary keys tables by their bare number without the "HL7"/leading-zero
 * padding (e.g. "38"); the inspector normalises a field's "HL70038" table id to
 * that form before looking it up.
 *
 * Run from the repo root:
 *
 *     npm install hl7-dictionary          # or: npm ci, in tools/
 *     node tools/generate_hl7_tables.js
 *
 * Then commit web/static/hl7ref/tables.json.
 */

const fs = require("fs");
const path = require("path");

let dict;
try {
  dict = require("hl7-dictionary");
} catch (e) {
  console.error("hl7-dictionary is not installed. Run: npm install hl7-dictionary");
  process.exit(1);
}

const outDir = path.join(__dirname, "..", "web", "static", "hl7ref");
const outPath = path.join(outDir, "tables.json");

const src = dict.tables || {};
const out = {};
let codeCount = 0;
for (const key of Object.keys(src)) {
  const t = src[key];
  if (!t || !t.values) continue;
  const values = {};
  for (const [code, desc] of Object.entries(t.values)) {
    if (code === "") continue;              // skip empty placeholder codes
    values[code] = desc;
    codeCount++;
  }
  if (Object.keys(values).length === 0) continue;
  out[key] = { desc: t.desc || "", values };
}

fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(out));
console.log(`Wrote ${Object.keys(out).length} tables (${codeCount} codes) to ${outPath}`);
