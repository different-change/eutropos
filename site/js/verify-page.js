import { applyBrandBindings } from "./brand-config.js";
import { applyTamperMutation, verifyV1BundleInBrowser } from "./verifier-core.js";

applyBrandBindings();

let activeMap = null;
let activePem = null;
let activeLabel = "";

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function setPresetButtons(folder) {
  const openBtn = document.getElementById("btn-verify-open");
  const hazBtn = document.getElementById("btn-verify-hazard");
  if (openBtn) openBtn.classList.toggle("is-active", folder === "open_live");
  if (hazBtn) hazBtn.classList.toggle("is-active", folder === "hazard_live");
}

function setTamperTabs(activeAttackId) {
  const cleanBtn = document.getElementById("btn-verify-clean");
  if (cleanBtn) cleanBtn.classList.toggle("is-active", activeAttackId === null);
  for (const btn of document.querySelectorAll("[data-tamper]")) {
    btn.classList.toggle("is-active", btn.getAttribute("data-tamper") === activeAttackId);
  }
}

function renderReport(report, label, attackLabel = null) {
  const statusEl = document.getElementById("verify-status");
  const tbody = document.getElementById("verify-checks-body");

  const stateCls = report.passed ? "is-verified" : "is-tampered";
  const statusLine = attackLabel
    ? (report.passed
        ? `UNEXPECTED PASS · ${report.checks.length} CHECKS · ${label}`
        : `TAMPER CAUGHT · ${report.failures.length} INTEGRITY CHECK FAILED · ${label}`)
    : (report.passed
        ? `VERIFIED · ${report.checks.length} / ${report.checks.length} CRYPTOGRAPHIC CHECKS PASSED · ${label}`
        : `VERIFICATION FAILED (${report.failures.length}) · ${label}`);

  const verdictTitle = attackLabel
    ? (report.passed ? "Attack Uncaught" : `${attackLabel} Rejected`)
    : (report.passed ? "Custody Chain Intact" : "Verification Failed");

  const detailText = report.failures.length
    ? "Native browser Web Crypto recomputed the canonical digest chain, ledger sequence, and Ed25519 signature, exposing every mutated artifact below."
    : "Ed25519 DSSE signature, canonical SHA-256 file hashes, monotonic SlotLedger transitions, and FreeTSA RFC 3161 commitments match the sealed beacon seed.";

  const failuresHtml = report.failures.length
    ? `<ul class="vault-failure-list">${report.failures.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`
    : "";

  const s = report.summary || {};
  statusEl.className = `vault-console ${stateCls}`;
  statusEl.innerHTML = `
    <div class="vault-readout">
      <div class="vault-status-row">
        <span class="status-dot"></span>
        <span>${esc(statusLine)}</span>
      </div>
      <h2 class="vault-verdict">${esc(verdictTitle)}</h2>
      <p class="vault-detail">${esc(detailText)}</p>
      ${failuresHtml}
    </div>
    <div class="vault-telemetry">
      <div class="tel-item">
        <div class="tel-k">Disclosure Mode</div>
        <div class="tel-v">${esc(s.disclosure_mode || "n/a")}</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">Rig Profile</div>
        <div class="tel-v">${esc(s.pareto_profile || "n/a")} (mask_tactile=${esc(s.mask_tactile)})</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">Public Randomness</div>
        <div class="tel-v">${esc(s.beacon_scheme || "n/a")} &middot; Round ${esc(s.round_number ?? "n/a")}</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">Registered / Passed Slots</div>
        <div class="tel-v">${s.slot_summary ? `${esc(s.slot_summary.passed_slots)} / ${esc(s.slot_summary.registered_slots)}` : "n/a"}</div>
      </div>
    </div>
  `;

  tbody.innerHTML = report.checks
    .map(
      (c) => `
      <tr>
        <td><span class="mono-inline">${esc(c.name)}</span></td>
        <td><span class="badge ${c.passed ? "badge-pass" : "badge-fail"}">${c.passed ? "PASS" : "FAIL"}</span></td>
        <td><span class="mono-inline">${esc(c.detail)}</span></td>
      </tr>`
    )
    .join("");
}

async function loadPreset(folder) {
  setPresetButtons(folder);
  setTamperTabs(null);
  const statusEl = document.getElementById("verify-status");
  statusEl.className = "vault-console is-verified";
  statusEl.innerHTML = `<div class="vault-readout"><p class="vault-detail">Fetching and verifying ${esc(folder)} in browser...</p></div>`;
  try {
    const idxResp = await fetch(`data/bundles/${folder}/bundle_index.json`);
    const idx = await idxResp.json();
    const pemResp = await fetch(`data/bundles/${folder}/${idx.trusted_public_key}`);
    const pem = await pemResp.text();
    const map = new Map();
    await Promise.all(
      idx.files.map(async (rel) => {
        const res = await fetch(`data/bundles/${folder}/${rel}`);
        map.set(rel, new Uint8Array(await res.arrayBuffer()));
      })
    );
    activeMap = map;
    activePem = pem;
    activeLabel = folder;
    const rep = await verifyV1BundleInBrowser(map, pem);
    renderReport(rep, folder);
  } catch (err) {
    statusEl.className = "vault-console is-tampered";
    statusEl.innerHTML = `<div class="vault-readout"><p class="vault-detail">Failed to load preset: ${esc(err.message)}</p></div>`;
  }
}

document.getElementById("btn-verify-open").addEventListener("click", () => loadPreset("open_live"));
document.getElementById("btn-verify-hazard").addEventListener("click", () => loadPreset("hazard_live"));

const cleanBtn = document.getElementById("btn-verify-clean");
if (cleanBtn) {
  cleanBtn.addEventListener("click", async () => {
    if (!activeMap || !activePem) {
      await loadPreset("open_live");
      return;
    }
    setTamperTabs(null);
    const rep = await verifyV1BundleInBrowser(activeMap, activePem);
    renderReport(rep, activeLabel, null);
  });
}

for (const btn of document.querySelectorAll("[data-tamper]")) {
  btn.addEventListener("click", async () => {
    if (!activeMap || !activePem) {
      await loadPreset("open_live");
    }
    const attackId = btn.getAttribute("data-tamper");
    setTamperTabs(attackId);
    const mutated = applyTamperMutation(activeMap, attackId);
    const rep = await verifyV1BundleInBrowser(mutated, activePem);
    renderReport(rep, activeLabel, btn.textContent.trim() || attackId);
  });
}

document.getElementById("input-folder").addEventListener("change", async (evt) => {
  setPresetButtons(null);
  setTamperTabs(null);
  const files = Array.from(evt.target.files || []);
  if (!files.length) return;
  const map = new Map();
  let pemText = null;
  for (const f of files) {
    const parts = (f.webkitRelativePath || f.name).split("/");
    const rel = parts.length > 1 ? parts.slice(1).join("/") : parts[0];
    const buf = new Uint8Array(await f.arrayBuffer());
    map.set(rel, buf);
    if (rel === "public_key.pem" || rel === "trusted_public_key.pem") {
      pemText = new TextDecoder().decode(buf);
    }
  }
  activeMap = map;
  activePem = pemText;
  activeLabel = "local-upload (public_key.pem)";
  const rep = await verifyV1BundleInBrowser(map, pemText);
  renderReport(rep, activeLabel);
});

loadPreset("open_live");
