import { readFileSync } from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { applyTamperMutation, verifyV1BundleInBrowser } from "../site/js/verifier-core.js";

function loadBundleFromDisk(bundleDir) {
  const idx = JSON.parse(readFileSync(path.join(bundleDir, "bundle_index.json"), "utf-8"));
  const pubPem = readFileSync(path.join(bundleDir, idx.trusted_public_key), "utf-8");
  const fileMap = new Map();
  for (const rel of idx.files) {
    fileMap.set(rel, new Uint8Array(readFileSync(path.join(bundleDir, rel))));
  }
  return { fileMap, pubPem };
}

const openDir = path.resolve("site/data/bundles/open_live");
const hazDir = path.resolve("site/data/bundles/hazard_live");

const openBundle = loadBundleFromDisk(openDir);
const repOpen = await verifyV1BundleInBrowser(openBundle.fileMap, openBundle.pubPem);
assert.equal(repOpen.passed, true, `open_live failed: ${repOpen.failures.join("; ")}`);
console.log("OPEN_LIVE_WEB_CRYPTO_OK:", repOpen.checks.length, "checks, round", repOpen.summary.round_number);

const hazBundle = loadBundleFromDisk(hazDir);
const repHaz = await verifyV1BundleInBrowser(hazBundle.fileMap, hazBundle.pubPem);
assert.equal(repHaz.passed, true, `hazard_live failed: ${repHaz.failures.join("; ")}`);
console.log("HAZARD_LIVE_WEB_CRYPTO_OK:", repHaz.checks.length, "checks, round", repHaz.summary.round_number);

for (const attack of ["scale_byte_flip", "hide_start_failure", "forge_ledger_pass", "swap_cert_bytes"]) {
  const mutated = applyTamperMutation(openBundle.fileMap, attack);
  const bad = await verifyV1BundleInBrowser(mutated, openBundle.pubPem);
  assert.equal(bad.passed, false, `Attack ${attack} unexpectedly passed!`);
  console.log(`TAMPER_CAUGHT_${attack}:`, bad.failures[0]);
}

console.log("WEB_VERIFIER_TESTS_PASSED");
