import { applyBrandBindings } from "./brand-config.js";
import { applyTamperMutation, verifyV1BundleInBrowser } from "./verifier-core.js";
import { esc, renderVaultConsole, renderVaultError, renderVaultPending } from "./vault-render.js";

applyBrandBindings();

const MAX_UPLOAD_FILES = 500;
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const PRESET_LABELS = {
  open_live: "Track B · Open Demo",
  hazard_live: "Track C · Escrowed Demo",
};

let activeMap = null;
let activePem = null;
let activeLabel = "";
let activeKeySource = "bundled";
let externalKeyPem = null;
let externalKeyName = "";
let latestReqId = 0;

function setPresetButtons(folder) {
  const openBtn = document.getElementById("btn-verify-open");
  const hazBtn = document.getElementById("btn-verify-hazard");
  if (openBtn) {
    const on = folder === "open_live";
    openBtn.classList.toggle("is-active", on);
    openBtn.setAttribute("aria-pressed", String(on));
  }
  if (hazBtn) {
    const on = folder === "hazard_live";
    hazBtn.classList.toggle("is-active", on);
    hazBtn.setAttribute("aria-pressed", String(on));
  }
}

function setTamperTabs(activeAttackId) {
  const cleanBtn = document.getElementById("btn-verify-clean");
  if (cleanBtn) {
    const on = activeAttackId === null;
    cleanBtn.classList.toggle("is-active", on);
    cleanBtn.setAttribute("aria-pressed", String(on));
  }
  for (const btn of document.querySelectorAll("[data-tamper]")) {
    const on = btn.getAttribute("data-tamper") === activeAttackId;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", String(on));
  }
}

function renderCheckRows(report) {
  const tbody = document.getElementById("verify-checks-body");
  if (!tbody) return;
  const checks = report?.checks || [];
  if (!checks.length) {
    tbody.innerHTML = `<tr><td colspan="3" class="muted">No checks completed for the selected input.</td></tr>`;
    return;
  }
  tbody.innerHTML = checks
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

function clearTablePending(message) {
  const tbody = document.getElementById("verify-checks-body");
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="3" class="muted">${esc(message)}</td></tr>`;
  }
}

async function runVerification(map, pem, label, keySource, attackLabel = null, reqId = latestReqId) {
  const statusEl = document.getElementById("verify-status");
  const rep = await verifyV1BundleInBrowser(map, pem, { keySource });
  if (reqId !== latestReqId) return;
  renderVaultConsole(statusEl, rep, {
    attackLabel,
    sourceLabel: label,
    showFullVerifyLink: false,
    headingTag: "h2",
    compactTelemetry: false,
  });
  renderCheckRows(rep);
}

async function loadPreset(folder) {
  const reqId = ++latestReqId;
  const label = PRESET_LABELS[folder] || folder;
  const statusEl = document.getElementById("verify-status");
  setPresetButtons(folder);
  setTamperTabs(null);
  renderVaultPending(statusEl, label);
  clearTablePending(`Loading ${label} artifacts...`);

  try {
    const idxResp = await fetch(`data/bundles/${folder}/bundle_index.json`);
    if (!idxResp.ok) throw new Error(`HTTP ${idxResp.status} loading bundle index`);
    const idx = await idxResp.json();
    const pemResp = await fetch(`data/bundles/${folder}/${idx.trusted_public_key}`);
    if (!pemResp.ok) throw new Error(`HTTP ${pemResp.status} loading public key`);
    const pem = await pemResp.text();
    const map = new Map();
    await Promise.all(
      idx.files.map(async (rel) => {
        const res = await fetch(`data/bundles/${folder}/${rel}`);
        if (!res.ok) throw new Error(`HTTP ${res.status} loading ${rel}`);
        map.set(rel, new Uint8Array(await res.arrayBuffer()));
      })
    );
    if (reqId !== latestReqId) return;
    activeMap = map;
    activePem = pem;
    activeLabel = label;
    activeKeySource = "bundled";
    await runVerification(map, pem, label, "bundled", null, reqId);
  } catch (err) {
    if (reqId !== latestReqId) return;
    activeMap = null;
    activePem = null;
    renderVaultError(statusEl, "Failed Loading Bundle Preset", String(err.message || err));
    clearTablePending("Preset load failed.");
  }
}

document.getElementById("btn-verify-open")?.addEventListener("click", () => void loadPreset("open_live"));
document.getElementById("btn-verify-hazard")?.addEventListener("click", () => void loadPreset("hazard_live"));

document.getElementById("btn-verify-clean")?.addEventListener("click", async () => {
  if (!activeMap || !activePem) {
    await loadPreset("open_live");
    return;
  }
  const reqId = ++latestReqId;
  setTamperTabs(null);
  const statusEl = document.getElementById("verify-status");
  renderVaultPending(statusEl, activeLabel);
  try {
    await runVerification(activeMap, activePem, activeLabel, activeKeySource, null, reqId);
  } catch (err) {
    if (reqId !== latestReqId) return;
    renderVaultError(statusEl, "Verification Error", String(err.message || err));
    clearTablePending("Verification stopped due to input error.");
  }
});

for (const btn of document.querySelectorAll("[data-tamper]")) {
  btn.addEventListener("click", async () => {
    const reqId = ++latestReqId;
    const statusEl = document.getElementById("verify-status");
    try {
      if (!activeMap || !activePem) {
        await loadPreset("open_live");
        if (reqId !== latestReqId && !activeMap) return;
      }
      const attackId = btn.getAttribute("data-tamper");
      setTamperTabs(attackId);
      const mutated = applyTamperMutation(activeMap, attackId);
      await runVerification(mutated, activePem, activeLabel, activeKeySource, btn.textContent.trim() || attackId, reqId);
    } catch (err) {
      if (reqId !== latestReqId) return;
      renderVaultError(statusEl, "Tamper Simulation Failed", String(err.message || err));
    }
  });
}

const keyStatusEl = document.getElementById("trusted-key-status");
document.getElementById("input-trusted-key")?.addEventListener("change", async (evt) => {
  const file = evt.target.files?.[0];
  if (!file) {
    externalKeyPem = null;
    externalKeyName = "";
    if (keyStatusEl) keyStatusEl.textContent = "No external auditor key selected; uploads check against bundle-supplied key.";
    return;
  }
  externalKeyPem = await file.text();
  externalKeyName = file.name;
  if (keyStatusEl) keyStatusEl.textContent = `External trusted key active: ${file.name}`;
  if (activeMap && activeLabel.startsWith("Local Folder")) {
    const reqId = ++latestReqId;
    activePem = externalKeyPem;
    activeKeySource = "external-file";
    await runVerification(activeMap, activePem, `${activeLabel} + ${externalKeyName}`, "external-file", null, reqId);
  }
});

document.getElementById("input-folder")?.addEventListener("change", async (evt) => {
  const reqId = ++latestReqId;
  const statusEl = document.getElementById("verify-status");
  setPresetButtons(null);
  setTamperTabs(null);
  const files = Array.from(evt.target.files || []);
  if (!files.length) return;

  if (files.length > MAX_UPLOAD_FILES) {
    renderVaultError(statusEl, "Directory Exceeds File Limit", `Selected ${files.length} files (maximum ${MAX_UPLOAD_FILES}). Select a single sealed evidence bundle directory.`);
    clearTablePending("Upload rejected due to file count cap.");
    return;
  }
  const totalBytes = files.reduce((acc, f) => acc + (f.size || 0), 0);
  if (totalBytes > MAX_UPLOAD_BYTES) {
    renderVaultError(statusEl, "Directory Exceeds Size Limit", `Selected ${(totalBytes / (1024 * 1024)).toFixed(1)} MB (maximum 50.0 MB for browser inspection).`);
    clearTablePending("Upload rejected due to size cap.");
    return;
  }

  renderVaultPending(statusEl, "Local Folder");
  clearTablePending("Reading local directory bytes locally inside your browser...");

  try {
    const map = new Map();
    let bundledPem = null;
    for (const f of files) {
      const parts = (f.webkitRelativePath || f.name).split("/");
      const rel = parts.length > 1 ? parts.slice(1).join("/") : parts[0];
      const buf = new Uint8Array(await f.arrayBuffer());
      map.set(rel, buf);
      if (rel === "trusted_public_key.pem" || (rel === "public_key.pem" && !bundledPem)) {
        bundledPem = new TextDecoder().decode(buf);
      }
    }
    if (reqId !== latestReqId) return;
    const useExternal = Boolean(externalKeyPem);
    activeMap = map;
    activePem = useExternal ? externalKeyPem : bundledPem;
    activeKeySource = useExternal ? "external-file" : "bundled";
    activeLabel = useExternal ? `Local Folder + ${externalKeyName}` : "Local Folder (Bundle Key Only)";
    await runVerification(activeMap, activePem, activeLabel, activeKeySource, null, reqId);
  } catch (err) {
    if (reqId !== latestReqId) return;
    renderVaultError(statusEl, "Local Folder Read Error", String(err.message || err));
    clearTablePending("Local read failed.");
  }
});

void loadPreset("open_live");
