import { applyBrandBindings } from "./brand-config.js";
import { applyTamperMutation, verifyV1BundleInBrowser } from "./verifier-core.js";
import { esc, formatVaultState, renderVaultConsole, renderVaultError, renderVaultPending } from "./vault-render.js";

applyBrandBindings();

const MAX_UPLOAD_FILES = 500;
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const PRESET_LABELS = {
  open_live: "Open Track (B) · Demo",
  hazard_live: "Escrowed Track (C) · Demo",
};
const SUPPORTS_DIR_PICKER = (() => {
  try {
    return typeof document !== "undefined" && "webkitdirectory" in document.createElement("input");
  } catch {
    return false;
  }
})();

let activeSourceType = null; // "preset" | "local" | null
let activePresetFolder = null;
let activeMap = null;
let activeBundledPem = null;
let activeBaseLabel = "";
let externalKeyPem = null;
let externalKeyName = "";
let latestReqId = 0;

function announceVerify(message) {
  const ann = document.getElementById("verify-announce");
  if (ann) ann.textContent = message;
}

function updateKeyStatus() {
  const keyStatusEl = document.getElementById("trusted-key-status");
  const clearBtn = document.getElementById("btn-clear-key");
  if (clearBtn) {
    clearBtn.hidden = !externalKeyPem;
  }
  if (!keyStatusEl) return;
  const pickerPrefix = SUPPORTS_DIR_PICKER
    ? "Files stay local on your device (client-side Web Crypto only)."
    : "Files stay local on your device. Folder selection is unsupported in this mobile browser; use desktop Chromium, Firefox, Safari, or the CLI for local bundles.";
  if (!externalKeyPem) {
    keyStatusEl.textContent = `${pickerPrefix} Until an external auditor key is selected, uploaded folders check consistency against their packaged key only.`;
    return;
  }
  if (activeSourceType === "preset") {
    keyStatusEl.textContent = `External key (${externalKeyName}) is staged for local folder uploads; demo presets always verify with pinned Eutropos keys.`;
  } else {
    keyStatusEl.textContent = `External trusted key active: ${externalKeyName}.`;
  }
}

function setControlsDisabled(disabled) {
  for (const id of ["btn-verify-open", "btn-verify-hazard", "btn-verify-clean"]) {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled;
  }
  for (const btn of document.querySelectorAll("[data-tamper]")) {
    btn.disabled = disabled;
  }
}

function effectiveLocalKeyAndLabel() {
  const useExternal = Boolean(externalKeyPem);
  return {
    pem: useExternal ? externalKeyPem : activeBundledPem,
    keySource: useExternal ? "external-file" : "bundled",
    label: useExternal ? `${activeBaseLabel} · Key: ${externalKeyName}` : `${activeBaseLabel} (Bundle Key Only)`,
  };
}

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

function syncTamperApplicability(map) {
  for (const btn of document.querySelectorAll("[data-tamper]")) {
    if (!map) {
      btn.title = "";
      continue;
    }
    const attackId = btn.getAttribute("data-tamper");
    const probe = applyTamperMutation(map, attackId);
    btn.title = probe.mutated ? "" : probe.reason;
  }
}

function renderCheckRows(report) {
  const tbody = document.getElementById("verify-checks-body");
  if (!tbody) return;
  const checks = report?.checks || [];
  if (!checks.length) {
    tbody.innerHTML = `<tr><td colspan="3" class="muted">Awaiting completed checks for the selected input.</td></tr>`;
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

async function runVerification(
  map,
  pem,
  label,
  keySource,
  attackLabel = null,
  reqId = latestReqId,
  commitUi = null,
  { inapplicableReason = null, announce = false } = {}
) {
  const statusEl = document.getElementById("verify-status");
  const rep = await verifyV1BundleInBrowser(map, pem, { keySource });
  if (reqId !== latestReqId) return false;
  if (typeof commitUi === "function") commitUi();
  const renderOpts = {
    attackLabel,
    sourceLabel: label,
    inapplicableReason,
    showFullVerifyLink: false,
    showCliHandoff: false,
    headingTag: "h2",
    compactTelemetry: false,
  };
  renderVaultConsole(statusEl, rep, renderOpts);
  renderCheckRows(rep);
  updateKeyStatus();
  if (announce) {
    const fmt = formatVaultState(rep, renderOpts);
    announceVerify(`${fmt.verdictTitle}. ${fmt.statusLine}`);
  }
  return true;
}

async function loadPreset(folder, { skipRun = false, announce = false } = {}) {
  const reqId = ++latestReqId;
  const label = PRESET_LABELS[folder] || folder;
  const statusEl = document.getElementById("verify-status");
  setControlsDisabled(true);
  renderVaultPending(statusEl, label);
  clearTablePending(`Loading ${label} artifacts...`);

  try {
    const idxResp = await fetch(`data/bundles/${folder}.index.json`);
    if (!idxResp.ok) throw new Error(`HTTP ${idxResp.status} loading bundle index`);
    const idx = await idxResp.json();
    const pemResp = await fetch(`data/bundles/${idx.trusted_public_key}`);
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
    if (reqId !== latestReqId) return false;
    activeSourceType = "preset";
    activePresetFolder = folder;
    activeMap = map;
    activeBundledPem = pem;
    activeBaseLabel = label;
    syncTamperApplicability(map);
    if (skipRun) {
      setPresetButtons(folder);
      updateKeyStatus();
      return true;
    }
    return await runVerification(
      map,
      pem,
      label,
      "bundled",
      null,
      reqId,
      () => {
        setPresetButtons(folder);
        setTamperTabs(null);
      },
      { announce }
    );
  } catch (err) {
    if (reqId !== latestReqId) return false;
    activeSourceType = null;
    activePresetFolder = null;
    activeMap = null;
    activeBundledPem = null;
    activeBaseLabel = "";
    setPresetButtons(null);
    setTamperTabs(null);
    renderVaultError(statusEl, "Failed Loading Bundle Preset", String(err.message || err));
    clearTablePending("Preset load failed.");
    updateKeyStatus();
    if (announce) announceVerify("Preset load failed.");
    return false;
  } finally {
    if (reqId === latestReqId) setControlsDisabled(false);
  }
}

document.getElementById("btn-verify-open")?.addEventListener("click", () => void loadPreset("open_live", { announce: true }));
document.getElementById("btn-verify-hazard")?.addEventListener("click", () => void loadPreset("hazard_live", { announce: true }));

document.getElementById("btn-verify-clean")?.addEventListener("click", async () => {
  if (!activeMap) {
    await loadPreset("open_live", { announce: true });
    return;
  }
  const reqId = ++latestReqId;
  const statusEl = document.getElementById("verify-status");
  const cfg = activeSourceType === "local"
    ? effectiveLocalKeyAndLabel()
    : { pem: activeBundledPem, keySource: "bundled", label: activeBaseLabel };
  setControlsDisabled(true);
  renderVaultPending(statusEl, cfg.label);
  clearTablePending(`Re-verifying clean artifacts for ${cfg.label}...`);
  try {
    await runVerification(
      activeMap,
      cfg.pem,
      cfg.label,
      cfg.keySource,
      null,
      reqId,
      () => {
        setTamperTabs(null);
      },
      { announce: true }
    );
  } catch (err) {
    if (reqId !== latestReqId) return;
    renderVaultError(statusEl, "Verification Error", String(err.message || err));
    clearTablePending("Verification stopped due to input error.");
  } finally {
    if (reqId === latestReqId) setControlsDisabled(false);
  }
});

for (const btn of document.querySelectorAll("[data-tamper]")) {
  btn.addEventListener("click", async () => {
    const attackId = btn.getAttribute("data-tamper");
    const attackText = btn.textContent.trim() || attackId;
    const statusEl = document.getElementById("verify-status");
    const reqId = ++latestReqId;
    setControlsDisabled(true);
    try {
      if (!activeMap) {
        renderVaultPending(statusEl, "Open Track (B) · Demo");
        clearTablePending("Loading default demo bundle...");
        const idxResp = await fetch("data/bundles/open_live.index.json");
        if (!idxResp.ok) throw new Error(`HTTP ${idxResp.status} loading bundle index`);
        const idx = await idxResp.json();
        const pemResp = await fetch(`data/bundles/${idx.trusted_public_key}`);
        if (!pemResp.ok) throw new Error(`HTTP ${pemResp.status} loading public key`);
        const pem = await pemResp.text();
        const map = new Map();
        await Promise.all(
          idx.files.map(async (rel) => {
            const res = await fetch(`data/bundles/open_live/${rel}`);
            if (!res.ok) throw new Error(`HTTP ${res.status} loading ${rel}`);
            map.set(rel, new Uint8Array(await res.arrayBuffer()));
          })
        );
        if (reqId !== latestReqId) return;
        activeSourceType = "preset";
        activePresetFolder = "open_live";
        activeMap = map;
        activeBundledPem = pem;
        activeBaseLabel = PRESET_LABELS.open_live;
        syncTamperApplicability(map);
      }
      const cfg = activeSourceType === "local"
        ? effectiveLocalKeyAndLabel()
        : { pem: activeBundledPem, keySource: "bundled", label: activeBaseLabel };
      const mutRes = applyTamperMutation(activeMap, attackId);
      renderVaultPending(statusEl, cfg.label);
      await runVerification(
        mutRes.map,
        cfg.pem,
        cfg.label,
        cfg.keySource,
        attackText,
        reqId,
        () => {
          if (activeSourceType === "preset") setPresetButtons(activePresetFolder);
          setTamperTabs(attackId);
        },
        {
          inapplicableReason: mutRes.mutated ? null : mutRes.reason,
          announce: true,
        }
      );
    } catch (err) {
      if (reqId !== latestReqId) return;
      renderVaultError(statusEl, "Tamper Simulation Failed", String(err.message || err));
      clearTablePending("Tamper simulation failed.");
    } finally {
      if (reqId === latestReqId) setControlsDisabled(false);
    }
  });
}

const keyInputEl = document.getElementById("input-trusted-key");
keyInputEl?.addEventListener("change", async (evt) => {
  const reqId = ++latestReqId;
  const statusEl = document.getElementById("verify-status");
  const file = evt.target.files?.[0];
  if (!file) {
    externalKeyPem = null;
    externalKeyName = "";
    if (activeMap && activeSourceType === "local") {
      const cfg = effectiveLocalKeyAndLabel();
      setControlsDisabled(true);
      renderVaultPending(statusEl, cfg.label);
      clearTablePending("Re-checking local folder against packaged key...");
      try {
        await runVerification(activeMap, cfg.pem, cfg.label, cfg.keySource, null, reqId, () => {
          setTamperTabs(null);
        }, { announce: true });
      } finally {
        if (reqId === latestReqId) setControlsDisabled(false);
      }
    } else {
      updateKeyStatus();
    }
    return;
  }

  if (activeMap && activeSourceType === "local") {
    setControlsDisabled(true);
    renderVaultPending(statusEl, `${activeBaseLabel} · Key: ${file.name}`);
    clearTablePending("Reading auditor key and re-checking local folder...");
  }
  try {
    const pemText = await file.text();
    if (reqId !== latestReqId) return;
    externalKeyPem = pemText;
    externalKeyName = file.name;
    updateKeyStatus();
    if (activeMap && activeSourceType === "local") {
      const cfg = effectiveLocalKeyAndLabel();
      await runVerification(activeMap, cfg.pem, cfg.label, cfg.keySource, null, reqId, () => {
        setTamperTabs(null);
      }, { announce: true });
    }
  } catch (err) {
    if (reqId !== latestReqId) return;
    renderVaultError(statusEl, "Trusted Key Read Error", String(err.message || err));
    clearTablePending("Failed reading selected .pem file.");
  } finally {
    if (reqId === latestReqId) setControlsDisabled(false);
  }
});

document.getElementById("btn-clear-key")?.addEventListener("click", async () => {
  const reqId = ++latestReqId;
  const statusEl = document.getElementById("verify-status");
  externalKeyPem = null;
  externalKeyName = "";
  if (keyInputEl) keyInputEl.value = "";
  if (activeMap && activeSourceType === "local") {
    const cfg = effectiveLocalKeyAndLabel();
    setControlsDisabled(true);
    renderVaultPending(statusEl, cfg.label);
    clearTablePending("Cleared auditor key; re-checking against bundle public key...");
    try {
      await runVerification(activeMap, cfg.pem, cfg.label, cfg.keySource, null, reqId, () => {
        setTamperTabs(null);
      }, { announce: true });
    } finally {
      if (reqId === latestReqId) setControlsDisabled(false);
    }
  } else {
    updateKeyStatus();
    announceVerify("Cleared staged external key.");
  }
});

document.getElementById("input-folder")?.addEventListener("change", async (evt) => {
  const reqId = ++latestReqId;
  const statusEl = document.getElementById("verify-status");
  const files = Array.from(evt.target.files || []);
  evt.target.value = "";
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

  setControlsDisabled(true);
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
    activeSourceType = "local";
    activePresetFolder = null;
    activeMap = map;
    activeBundledPem = bundledPem;
    activeBaseLabel = "Local Folder";
    syncTamperApplicability(map);
    const cfg = effectiveLocalKeyAndLabel();
    await runVerification(activeMap, cfg.pem, cfg.label, cfg.keySource, null, reqId, () => {
      setPresetButtons(null);
      setTamperTabs(null);
    }, { announce: true });
  } catch (err) {
    if (reqId !== latestReqId) return;
    activeSourceType = null;
    activeMap = null;
    activeBundledPem = null;
    setPresetButtons(null);
    setTamperTabs(null);
    renderVaultError(statusEl, "Local Folder Read Error", String(err.message || err));
    clearTablePending("Local read failed.");
    updateKeyStatus();
  } finally {
    if (reqId === latestReqId) setControlsDisabled(false);
  }
});

const drawerEl = document.getElementById("local-audit-drawer");
if (drawerEl && typeof window !== "undefined" && window.matchMedia && window.matchMedia("(max-width: 760px)").matches) {
  drawerEl.open = false;
}

updateKeyStatus();
void loadPreset("open_live", { announce: false });
