import { BRAND_CONFIG, applyBrandBindings } from "./brand-config.js";
import { applyTamperMutation, verifyV1BundleInBrowser } from "./verifier-core.js";
import { renderVaultConsole, renderVaultError, renderVaultPending } from "./vault-render.js";

applyBrandBindings();

const INSTALL_CMD = BRAND_CONFIG.PINNED_INSTALL_CMD;

const copyBtn = document.getElementById("btn-copy-install");
const installCodeEl = document.getElementById("home-install-code");
const copyStatusEl = document.getElementById("copy-status");
if (copyBtn) {
  copyBtn.addEventListener("click", async () => {
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(INSTALL_CMD);
      copyBtn.textContent = "Copied";
      if (copyStatusEl) copyStatusEl.textContent = "Pinned install command copied to clipboard.";
      setTimeout(() => {
        copyBtn.textContent = "Copy Install";
      }, 1400);
    } catch {
      if (installCodeEl && window.getSelection) {
        const range = document.createRange();
        range.selectNodeContents(installCodeEl);
        const sel = window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
      copyBtn.textContent = "Select Below";
      if (copyStatusEl) copyStatusEl.textContent = "Clipboard access unavailable; command selected for manual copy.";
      setTimeout(() => {
        copyBtn.textContent = "Copy Install";
      }, 2000);
    }
  });
}

let homeOpenMap = null;
let homeOpenPem = null;
let homeReqId = 0;
let homeAutoStarted = false;

function announceHomeVault(message) {
  const ann = document.getElementById("home-vault-announce");
  if (ann) ann.textContent = message;
}

function setHomeActiveControl(activeAttackId) {
  const resetBtn = document.getElementById("home-btn-reset");
  if (resetBtn) {
    const active = activeAttackId === null;
    resetBtn.classList.toggle("is-active", active);
    resetBtn.setAttribute("aria-pressed", String(active));
  }
  for (const btn of document.querySelectorAll("[data-home-tamper]")) {
    const active = btn.getAttribute("data-home-tamper") === activeAttackId;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-pressed", String(active));
  }
}

async function ensureHomeBundleLoaded() {
  if (homeOpenMap && homeOpenPem) return;
  const idxResp = await fetch("data/bundles/open_live.index.json");
  if (!idxResp.ok) throw new Error(`HTTP ${idxResp.status} loading open_live.index.json`);
  const idx = await idxResp.json();
  const pemResp = await fetch(`data/bundles/${idx.trusted_public_key}`);
  if (!pemResp.ok) throw new Error(`HTTP ${pemResp.status} loading public key`);
  const pem = await pemResp.text();
  const map = new Map();
  await Promise.all(
    idx.files.map(async (rel) => {
      const r = await fetch(`data/bundles/open_live/${rel}`);
      if (!r.ok) throw new Error(`HTTP ${r.status} loading ${rel}`);
      map.set(rel, new Uint8Array(await r.arrayBuffer()));
    })
  );
  homeOpenMap = map;
  homeOpenPem = pem;
}

async function runHomeCheck(attackId = null, attackLabel = null, { announce = false } = {}) {
  const target = document.getElementById("home-live-summary");
  const reqId = ++homeReqId;
  homeAutoStarted = true;
  setHomeActiveControl(attackId);
  renderVaultPending(target, "Open Track Demo");
  try {
    await ensureHomeBundleLoaded();
    const bundle = attackId ? applyTamperMutation(homeOpenMap, attackId) : homeOpenMap;
    const rep = await verifyV1BundleInBrowser(bundle, homeOpenPem, { keySource: "bundled" });
    if (reqId !== homeReqId) return;
    renderVaultConsole(target, rep, {
      attackLabel,
      sourceLabel: "Open Track Demo",
      showFullVerifyLink: true,
      headingTag: "h3",
      compactTelemetry: true,
    });
    if (announce) {
      announceHomeVault(
        rep.passed
          ? `Verified ${rep.checks.length} browser checks cleanly.`
          : `Tamper simulation flagged ${rep.failures.length} check failures.`
      );
    }
  } catch (err) {
    if (reqId !== homeReqId) return;
    renderVaultError(
      target,
      "Live Demo Bundle Unavailable",
      `Serve the static site over HTTPS or localhost HTTP to execute Web Crypto bundle fetches (${err.message}).`
    );
    if (announce) announceHomeVault("Live demo bundle verification error.");
  }
}

const resetBtn = document.getElementById("home-btn-reset");
if (resetBtn) {
  resetBtn.addEventListener("click", () => {
    void runHomeCheck(null, null, { announce: true });
  });
}

for (const btn of document.querySelectorAll("[data-home-tamper]")) {
  btn.addEventListener("click", () => {
    const attackId = btn.getAttribute("data-home-tamper");
    void runHomeCheck(attackId, btn.textContent.trim(), { announce: true });
  });
}

const vaultSection = document.getElementById("tamper-lab");
if (vaultSection && "IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting) && !homeAutoStarted) {
        observer.disconnect();
        void runHomeCheck(null, null, { announce: false });
      }
    },
    { rootMargin: "320px 0px" }
  );
  observer.observe(vaultSection);
} else {
  void runHomeCheck(null, null, { announce: false });
}
