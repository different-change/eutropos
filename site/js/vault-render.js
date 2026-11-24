// Shared deterministic verdict formatter & renderer across index.html and verify.html.
export function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function formatVaultState(report, options = {}) {
  const { attackLabel = null, sourceLabel = "", inapplicableReason = null } = options;
  const checks = Array.isArray(report?.checks) ? report.checks : [];
  const failures = Array.isArray(report?.failures) ? report.failures : [];
  const okCount = checks.filter((c) => c.passed).length;
  const totalCount = checks.length;
  const failN = failures.length;
  const failWord = failN === 1 ? "CHECK" : "CHECKS";
  const labelSuffix = sourceLabel ? ` · ${sourceLabel}` : "";

  if (inapplicableReason) {
    return {
      stateCls: "is-pending",
      statusLine: `SIMULATION INAPPLICABLE · ${attackLabel || "TAMPER TEST"}${labelSuffix}`,
      verdictTitle: "Mutation Not Applicable to This Bundle",
      detailText: `${inapplicableReason} The active verification checks remain unchanged for reference.`,
    };
  }

  if (report?.status === "unsupported-browser") {
    return {
      stateCls: "is-error",
      statusLine: `BROWSER UNSUPPORTED · ED25519 WEB CRYPTO UNAVAILABLE${labelSuffix}`,
      verdictTitle: "Browser Support Required",
      detailText:
        "This browser environment lacks native SubtleCrypto Ed25519 support. Use a current Chromium, Firefox, or Safari release, or run the Python verifier CLI locally.",
    };
  }

  if (!report?.passed) {
    return {
      stateCls: "is-tampered",
      statusLine: attackLabel
        ? `TAMPER CAUGHT · ${failN} INTEGRITY ${failWord} FAILED${labelSuffix}`
        : `VERIFICATION FAILED · ${failN} INTEGRITY ${failWord} FAILED${labelSuffix}`,
      verdictTitle: attackLabel ? `${attackLabel} Rejected` : "Verification Failed",
      detailText:
        "Browser Web Crypto and ASN.1 DER checks recomputed canonical SHA-256 digests, SlotLedger state transitions, and the Ed25519 signature, and flagged the failures below.",
    };
  }

  if (report.trustStatus === "self-signed-untrusted") {
    return {
      stateCls: "is-self-signed",
      statusLine: `BUNDLE SELF-CONSISTENT · ${okCount} / ${totalCount} BROWSER CHECKS · SIGNER UNVERIFIED${labelSuffix}`,
      verdictTitle: "Self-Signed Bundle (Unverified Issuer)",
      detailText:
        "Every digest and signature agrees with the public key packaged inside the uploaded folder, while issuer identity stays unverified until checked against an external key.",
    };
  }

  if (attackLabel) {
    return {
      stateCls: "is-error",
      statusLine: `UNEXPECTED PASS · ${okCount} / ${totalCount} CHECKS${labelSuffix}`,
      verdictTitle: "Attack Uncaught",
      detailText: "Warning: the simulated mutation passed unexpectedly and bypassed tamper detection.",
    };
  }

  if (report?.summary?.isStubBeacon) {
    return {
      stateCls: "is-self-signed",
      statusLine: `LOCAL STUB BUNDLE · ${okCount} / ${totalCount} BROWSER CHECKS · DEV MODE${labelSuffix}`,
      verdictTitle: "Local Stub Bundle Consistent (Non-Production)",
      detailText:
        "Web Crypto Ed25519 signature, canonical SHA-256 artifact digests, SlotLedger transitions, and stub beacon/timestamp fields agree internally for local development; live drand-quicknet and FreeTSA anchors are absent.",
    };
  }

  return {
    stateCls: "is-verified",
    statusLine: `BROWSER SUBSET VERIFIED · ${okCount} / ${totalCount} CHECKS · FULL BLS/CMS: CLI${labelSuffix}`,
    verdictTitle: "Signed Bundle Consistent (Browser Subset)",
    detailText:
      "Web Crypto Ed25519 DSSE signature, canonical SHA-256 artifact digests, disclosure bindings, SlotLedger transitions, and strict CMS DER TSTInfo bounds passed against the active key.",
  };
}

export function renderVaultPending(targetEl, label) {
  if (!targetEl) return;
  targetEl.className = "vault-console is-pending";
  targetEl.innerHTML = `
    <div class="vault-readout">
      <div class="vault-status-row">
        <span class="status-dot"></span>
        <span>VERIFYING IN BROWSER${label ? ` · ${esc(label)}` : ""}</span>
      </div>
      <h3 class="vault-verdict">Running Web Crypto &amp; DER Checks</h3>
      <p class="vault-detail">Checking Ed25519 DSSE envelope, canonical SHA-256 digests, SlotLedger completion, and RFC 3161 DER timestamps locally.</p>
    </div>
  `;
}

export function renderVaultError(targetEl, title, detail) {
  if (!targetEl) return;
  targetEl.className = "vault-console is-error";
  targetEl.innerHTML = `
    <div class="vault-readout">
      <div class="vault-status-row">
        <span class="status-dot"></span>
        <span>VERIFIER ERROR · INPUT COULD NOT BE CHECKED</span>
      </div>
      <h3 class="vault-verdict">${esc(title)}</h3>
      <p class="vault-detail">${esc(detail)}</p>
    </div>
  `;
}

export function renderVaultConsole(targetEl, report, options = {}) {
  if (!targetEl) return;
  const {
    attackLabel = null,
    sourceLabel = "",
    inapplicableReason = null,
    showFullVerifyLink = false,
    showCliHandoff = true,
    headingTag = "h3",
    compactTelemetry = false,
  } = options;

  const fmt = formatVaultState(report, { attackLabel, sourceLabel, inapplicableReason });
  const s = report.summary || {};
  const failuresHtml = report.failures?.length && !inapplicableReason
    ? `<ul class="vault-failure-list">${report.failures.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`
    : "";

  let slotInfo = "Unavailable";
  if (s.slot_summary) {
    const retryCount = Number(s.slot_summary.retries ?? 0);
    const retryWord = retryCount === 1 ? "retry" : "retries";
    const attempts = Number(s.slot_attempts ?? (Number(s.slot_summary.registered_slots ?? 0) + retryCount));
    const ledgerTerm = s.slot_summary.all_slots_accounted ? "all terminal" : "INCOMPLETE LEDGER";
    slotInfo = `${s.slot_summary.passed_slots} / ${s.slot_summary.registered_slots} slots passed · ${attempts} attempts (${retryCount} ${retryWord}) · ${ledgerTerm}`;
  }

  const demoStampHtml = report.isSoftwareDemo
    ? `<div class="vault-demo-stamp">SOFTWARE DEMO · SIMULATED BENCH TELEMETRY · UNBUILT SPEC ${esc(s.pareto_profile || "UNSPECIFIED")}</div>`
    : "";

  const fullVerifyLinkHtml = showFullVerifyLink
    ? `<a class="link-editorial-light" href="verify.html">Open Full Verifier &amp; Select External Key &rarr;</a>`
    : "";

  const cliHandoffHtml = showCliHandoff
    ? `<p class="vault-cli-handoff">Full third-party BLS12-381 beacon pairing and X.509 CMS certificate-chain verification run locally via <span class="mono-inline-dark">eutropos-referee verify --evidence-dir &lt;dir&gt; --public-key &lt;key.pem&gt; --require-live-beacon --require-live-tsa</span>.</p>`
    : "";

  const telItems = compactTelemetry
    ? `
      <div class="tel-item">
        <div class="tel-k">Signer Key</div>
        <div class="tel-v">${esc(report.trustLabel || "n/a")} &middot; kid ${esc(report.keyId || "n/a")}</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">Public Randomness</div>
        <div class="tel-v">drand-quicknet &middot; Round ${esc(s.round_number ?? "n/a")} (${esc(s.beacon_round_utc || "n/a")})</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">FreeTSA Commitment (DER)</div>
        <div class="tel-v">${esc(s.tsa_commitment_der_utc || "n/a")}</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">Passed / Registered Slots</div>
        <div class="tel-v">${esc(slotInfo)}</div>
      </div>
    `
    : `
      <div class="tel-item">
        <div class="tel-k">Signer Trust Key</div>
        <div class="tel-v">${esc(report.trustLabel || "n/a")} &middot; kid ${esc(report.keyId || "n/a")}</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">Disclosure Mode &amp; Spec</div>
        <div class="tel-v">${esc(s.disclosure_mode || "n/a")} &middot; ${esc(s.pareto_profile || "n/a")} (mask_tactile=${esc(s.mask_tactile)})</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">Public Randomness</div>
        <div class="tel-v">${esc(s.beacon_scheme || "n/a")} &middot; Round ${esc(s.round_number ?? "n/a")} (${esc(s.beacon_round_utc || "n/a")})</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">FreeTSA DER Commitment &rarr; Close</div>
        <div class="tel-v">${esc(s.tsa_commitment_der_utc || "n/a")} &rarr; ${esc(s.tsa_close_der_utc || "n/a")}</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">Passed / Registered Slots</div>
        <div class="tel-v">${esc(slotInfo)}</div>
      </div>
    `;

  const hTag = headingTag === "h2" ? "h2" : "h3";
  targetEl.className = `vault-console ${fmt.stateCls}`;
  targetEl.innerHTML = `
    <div class="vault-readout">
      <div class="vault-status-row">
        <span class="status-dot"></span>
        <span>${esc(fmt.statusLine)}</span>
      </div>
      ${demoStampHtml}
      <${hTag} class="vault-verdict">${esc(fmt.verdictTitle)}</${hTag}>
      <p class="vault-detail">${esc(fmt.detailText)}</p>
      ${failuresHtml}
      ${cliHandoffHtml}
      ${fullVerifyLinkHtml}
    </div>
    <div class="vault-telemetry">${telItems}</div>
  `;
}
