import { applyBrandBindings } from "../site/js/brand-config.js";

const SITE_ROOT = "../site/";
applyBrandBindings();

const slides = Array.from(document.querySelectorAll(".slide"));
const jumpStrip = document.getElementById("jump-strip");
const counterEl = document.getElementById("slide-counter");
const prevBtn = document.getElementById("btn-prev");
const nextBtn = document.getElementById("btn-next");

let activeIdx = 0;

function esc(v) {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function goToSlide(idx, updateHash = true) {
  activeIdx = Math.max(0, Math.min(slides.length - 1, idx));
  slides.forEach((s, i) => s.classList.toggle("active", i === activeIdx));
  const dots = Array.from(jumpStrip.querySelectorAll(".jump-dot"));
  dots.forEach((d, i) => {
    const on = i === activeIdx;
    d.classList.toggle("active", on);
    d.setAttribute("aria-current", on ? "step" : "false");
  });
  counterEl.textContent = `${activeIdx + 1} / ${slides.length}`;
  if (prevBtn) prevBtn.disabled = activeIdx === 0;
  if (nextBtn) nextBtn.disabled = activeIdx === slides.length - 1;
  if (updateHash && window.history && window.history.replaceState) {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#slide-${activeIdx + 1}`);
  }
}

slides.forEach((_, i) => {
  const dot = document.createElement("button");
  dot.className = "jump-dot";
  dot.type = "button";
  dot.textContent = String(i + 1);
  dot.setAttribute("aria-label", `Go to slide ${i + 1}`);
  dot.addEventListener("click", () => goToSlide(i));
  jumpStrip.appendChild(dot);
});

prevBtn.addEventListener("click", () => goToSlide(activeIdx - 1));
nextBtn.addEventListener("click", () => goToSlide(activeIdx + 1));

const printBtn = document.getElementById("btn-print");
if (printBtn) {
  printBtn.addEventListener("click", () => window.print());
}

document.addEventListener("keydown", (evt) => {
  const tag = evt.target && evt.target.tagName ? evt.target.tagName.toUpperCase() : "";
  if (["INPUT", "SELECT", "TEXTAREA"].includes(tag) || Boolean(evt.target?.isContentEditable)) return;
  if (evt.key === "ArrowRight" || evt.key === "PageDown") {
    evt.preventDefault();
    goToSlide(activeIdx + 1);
  } else if (evt.key === "ArrowLeft" || evt.key === "PageUp") {
    evt.preventDefault();
    goToSlide(activeIdx - 1);
  } else if (evt.key === "Home") {
    evt.preventDefault();
    goToSlide(0);
  } else if (evt.key === "End") {
    evt.preventDefault();
    goToSlide(slides.length - 1);
  }
});

const TRACKS = {
  partner: {
    title: "Option 1 — Lab Partner ($0 Capital Ask)",
    shortTitle: "Lab Partner ($0 Capital Ask)",
    badge: "Integration & Pilot Option",
    ask: "$0 Capital Ask",
    runway: "Immediate Software Plugin Integration",
    summary: "Run eutropos-referee==1.0.2 alongside existing inspect-robots pipelines or via standalone isolated execution to attach software custody chains today.",
    allocation: [
      "Direct Python entry-point registration inside existing inspect-robots CI / eval workflows",
      "Joint specification of 1 private hazard-escrowed surrogate family (e.g. I2 or H2)",
      "Cross-lab blinded bundle exchange verifiable in browser Web Crypto + CLI",
    ],
    milestones: [
      "Day 1: Prove open + hazard-escrowed live cryptographic custody chains on your tasks",
      "Post Stage-1 Bench ($1,291 core subtotal): Evaluate blinded checkpoints on physical fixture",
      "Post Rig Build: Co-publish third-party verified safety / capability appendix",
    ],
  },
  lean: {
    title: "Option 2 — Lean Physical Proof Pilot ($250k – $500k)",
    shortTitle: "Lean Physical Proof Pilot ($250k – $500k)",
    badge: "Capital-Efficient Physical Proof",
    ask: "$250,000 – $500,000",
    runway: "12-Month Lean Operating Runway",
    summary: "$250k validates physical metrology on the Stage-1 sensor bench ($1,291 core subtotal + stereo & fixtures) across 240 trials; $500k adds one commissioned P2 cell and Season-0 baselines.",
    allocation: [
      "$1,291 core Stage-1 sensor subtotal (Radwag WTC 2000 + Basler ace 2) + ZED 2i stereo ($529) & H1/H4 fixtures",
      "~$40.9k Single P2 UFACTORY 850 + ORCA v2.1 Touch rig + ~$15k interchangeable fixtures/spares",
      "Founder metrology engineering, physical 240-trial A4 publication, and Season-0 open launch",
    ],
    milestones: [
      "Gate 1: Publish 240-trial physical A4 study measuring physical sensor error rates",
      "Gate 2: Commission P2 dual-division cell (UFACTORY 850 + ORCA Touch) + human teleop ceilings across 15 families",
      "Gate 3: First external robotics policies evaluated under Open Track + initial escrow pilot buyers",
    ],
  },
  preseed: {
    title: "Option 3 — Pre-Seed Operating Round ($1.5M – $3.0M)",
    shortTitle: "Pre-Seed Operating Round ($1.5M – $3.0M)",
    badge: "Full Dual-Track Startup",
    ask: "$1.5M – $3.0M",
    runway: "18-Month Operating Runway",
    summary: "$1.5M funds Stage-1 validation, a single P2 UFACTORY 850 + ORCA Touch cell, Season-0 baselines, and an initial escrow pilot; $3.0M expands to matched P1 + P2 cells, dedicated metrology hires, and 3+ paid closed-bank audits.",
    allocation: [
      "Dual matched physical referee cells (P1 YAM Ultra 2 + P2 UFACTORY 850 / ORCA Touch)",
      "Engineering hires: robotics metrology, fixtures/CAD, and isolated runner infrastructure",
      "Enterprise compliance prep, escrow custody operations, and direct lab/insurer GTM",
    ],
    milestones: [
      "Month 4: Physical Stage-1 study published; P1 + P2 cells in commissioning after vendor RFQs",
      "Month 9: Season-1 public leaderboard open to metered external policy submissions",
      "Month 18: 3+ paid Escrowed Track audits delivered; ISO/IEC 17025 accreditation roadmap active",
    ],
  },
  seed: {
    title: "Option 4 — Institutional Seed ($5.0M+)",
    shortTitle: "Institutional Seed ($5.0M+)",
    badge: "Bureau Scale Option",
    ask: "$5.0M+ Institutional Lead",
    runway: "24-Month Operating Runway",
    summary: "Build regional US and EU physical referee cells for public Season leaderboards and insurer-audited escrow testing.",
    allocation: [
      "Multi-cell automated referee labs (US + EU) supporting rapid throughput across divisions",
      "HSM-backed escrow key ceremony infrastructure and full continuous telemetry archives",
      "Insurer underwriting & OEM procurement partnerships translating scores to deployment limits",
    ],
    milestones: [
      "Month 6: Regional twin physical referee cells + accredited calibration roadmap",
      "Month 12: Standing Season-1 & Season-2 capability index referenced by labs and buyers",
      "Month 24: Multi-enterprise Escrowed Track recurring audit contracts + underwriting adoption",
    ],
  },
};

const params = new URLSearchParams(window.location.search);
const requestedTrack = (params.get("track") || "").trim().toLowerCase();
const hasLockedTrack = Object.prototype.hasOwnProperty.call(TRACKS, requestedTrack);
const trackBar = document.querySelector(".track-bar");
const trackBtns = Array.from(document.querySelectorAll(".track-btn"));

function renderTrack(trackKey) {
  const t = TRACKS[trackKey] || TRACKS.partner;
  trackBtns.forEach((b) => {
    const active = b.getAttribute("data-track") === trackKey;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", String(active));
    b.setAttribute("tabindex", active ? "0" : "-1");
  });
  const leftHeading = hasLockedTrack ? "Scope" : t.title;
  const host = document.getElementById("track-detail");
  if (host) {
    host.setAttribute("aria-labelledby", `tab-${trackKey}`);
    host.innerHTML = `
    <div class="grid-2">
      <div class="panel panel-white">
        <span class="badge badge-pass">${esc(t.badge)}</span>
        <h3>${esc(leftHeading)}</h3>
        <div class="big-num">${esc(t.ask)}</div>
        <div class="ask-sub">${esc(t.runway)}</div>
        <p class="small muted">${esc(t.summary)}</p>
      </div>
      <div class="panel panel-white">
        <h3>Capital / Effort Allocation</h3>
        <ul class="small">${t.allocation.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        <h3 class="mt-1">Milestones</h3>
        <ul class="small">${t.milestones.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      </div>
    </div>
  `;
  }
}

trackBtns.forEach((btn) => {
  btn.addEventListener("click", () => renderTrack(btn.getAttribute("data-track")));
});

if (trackBar) {
  trackBar.addEventListener("keydown", (evt) => {
    const idx = trackBtns.indexOf(document.activeElement);
    if (idx === -1) return;
    let nextIdx = -1;
    if (evt.key === "ArrowRight") nextIdx = (idx + 1) % trackBtns.length;
    else if (evt.key === "ArrowLeft") nextIdx = (idx - 1 + trackBtns.length) % trackBtns.length;
    else if (evt.key === "Home") nextIdx = 0;
    else if (evt.key === "End") nextIdx = trackBtns.length - 1;
    if (nextIdx !== -1) {
      evt.preventDefault();
      evt.stopPropagation();
      const targetBtn = trackBtns[nextIdx];
      targetBtn.focus();
      renderTrack(targetBtn.getAttribute("data-track"));
    }
  });
}

async function hydrateEvidence() {
  if (printBtn) printBtn.disabled = true;
  try {
    const resp = await fetch(`${SITE_ROOT}data/a4_study.json`);
    if (!resp.ok) return;
    const data = await resp.json();

    const chartHost = document.getElementById("deck-a4-chart");
    const jList = [
      { key: "robodojo_astra", label: "GPT-6 Astra" },
      { key: "claude_opus_5_5", label: "Claude Opus 5.5" },
      { key: "datacenterbench_dual", label: "DataCenterBench Dual" },
      { key: "gemini_4_neon", label: "Gemini 4 Neon" },
    ];
    const w = 780;
    const h = 232;
    const pL = 46;
    const pR = 16;
    const pT = 38;
    const pB = 38;
    const cw = w - pL - pR;
    const ch = h - pT - pB;
    const yF = (v) => pT + ch - (Math.min(v, 50) / 50) * ch;
    const parts = [`<svg class="deck-chart-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="Deck A4 VLM FPR vs S4 Decoy vs S1 FFR in MuJoCo simulation">`];
    parts.push(`<rect x="${pL}" y="10" width="9" height="9" fill="#9C2F1E"/><text x="${pL + 14}" y="18" font-size="9.5" fill="#14171D" font-family="'JetBrains Mono', ui-monospace, monospace">Overall FPR (n=45)</text>`);
    parts.push(`<rect x="${pL + 136}" y="10" width="9" height="9" fill="#9C7A3C"/><text x="${pL + 150}" y="18" font-size="9.5" fill="#14171D" font-family="'JetBrains Mono', ui-monospace, monospace">S4 Decoy (n=15)</text>`);
    parts.push(`<rect x="${pL + 258}" y="10" width="9" height="9" fill="#14233C"/><text x="${pL + 272}" y="18" font-size="9.5" fill="#14171D" font-family="'JetBrains Mono', ui-monospace, monospace">S1 FFR (n=15)</text>`);
    parts.push(`<line x1="${w - pR - 252}" y1="14" x2="${w - pR - 232}" y2="14" stroke="#9C2F1E" stroke-width="1.5" stroke-dasharray="5,4"/><text x="${w - pR - 150}" y="18" text-anchor="end" font-size="9" font-weight="600" fill="#9C2F1E" font-family="'JetBrains Mono', ui-monospace, monospace">5% FPR Gate</text>`);
    parts.push(`<line x1="${w - pR - 134}" y1="14" x2="${w - pR - 114}" y2="14" stroke="#795B2B" stroke-width="1.5" stroke-dasharray="2,3"/><text x="${w - pR}" y="18" text-anchor="end" font-size="9" font-weight="600" fill="#795B2B" font-family="'JetBrains Mono', ui-monospace, monospace">10% S4/S1 Gates</text>`);
    [0, 10, 20, 30, 40, 50].forEach((tk) => {
      const yy = yF(tk);
      parts.push(`<line x1="${pL}" y1="${yy}" x2="${w - pR}" y2="${yy}" stroke="#DCD5C7" stroke-width="1"/>`);
      parts.push(`<text x="${pL - 6}" y="${yy + 3}" text-anchor="end" font-size="10" fill="#5A606A" font-family="'JetBrains Mono', ui-monospace, monospace">${tk}%</text>`);
    });
    parts.push(`<line x1="${pL}" y1="${yF(10)}" x2="${w - pR}" y2="${yF(10)}" stroke="#795B2B" stroke-width="1.5" stroke-dasharray="2,3"/>`);
    parts.push(`<line x1="${pL}" y1="${yF(5)}" x2="${w - pR}" y2="${yF(5)}" stroke="#9C2F1E" stroke-width="1.5" stroke-dasharray="5,4"/>`);

    const gw = cw / jList.length;
    const bw = 28;
    jList.forEach((item, idx) => {
      const cx = pL + idx * gw + gw / 2;
      const st = data.statistics.judges[item.key];
      const bars = [
        { v: st.overall_fpr * 100, c: "#9C2F1E" },
        { v: st.per_stratum.S4.fpr * 100, c: "#9C7A3C" },
        { v: st.overall_ffr * 100, c: "#14233C" },
      ];
      const xs = cx - (3 * bw + 12) / 2;
      bars.forEach((b, bi) => {
        const bx = xs + bi * (bw + 6);
        const by = yF(b.v);
        parts.push(`<rect x="${bx}" y="${by}" width="${bw}" height="${Math.max(2, yF(0) - by)}" rx="0" fill="${b.c}"/>`);
        parts.push(`<text x="${bx + bw / 2}" y="${by - 4}" text-anchor="middle" font-size="9.5" font-weight="600" fill="#14171D" font-family="'JetBrains Mono', ui-monospace, monospace">${b.v.toFixed(1)}%</text>`);
      });
      parts.push(`<text x="${cx}" y="${h - 12}" text-anchor="middle" font-size="11" font-weight="600" fill="#14171D" font-family="'Inter', sans-serif">${esc(item.label)}</text>`);
    });
    parts.push("</svg>");
    chartHost.innerHTML = parts.join("");

    const showIds = ["tr_57_962127", "tr_40_574742", "tr_23_604214"];
    const picked = showIds.map((id) => data.showcase.find((s) => s.opaque_id === id)).filter(Boolean);
    document.getElementById("deck-showcase").innerHTML = picked
      .map((tr) => {
        const falsePasses = Object.values(tr.verdicts).filter((v) => v.category === "PASS").length;
        const abstained = Object.values(tr.verdicts).filter((v) => v.category === "UNSURE").length;
        return `
        <div class="panel panel-white">
          <div class="mono small"><code>${esc(tr.opaque_id)}</code> &middot; <code>${esc(tr.family_id)}/${esc(tr.stratum)}</code> &middot; <span class="badge badge-fail">${falsePasses}/4 FALSE PASS${abstained ? ` (${abstained} UNSURE)` : ""}</span></div>
          <div class="mini-stereo">
            <img src="${esc(SITE_ROOT + tr.left_img)}" width="360" height="270" alt="MuJoCo left stereo frame for ${esc(tr.opaque_id)}"/>
            <img src="${esc(SITE_ROOT + tr.right_img)}" width="360" height="270" alt="MuJoCo right stereo frame for ${esc(tr.opaque_id)}"/>
          </div>
          <p class="small"><strong>Simulator Ref:</strong> ${esc(tr.gt_reason)}</p>
        </div>
      `;
      })
      .join("");
  } catch {
    // Keeps static fallback readable offline
  } finally {
    if (printBtn) printBtn.disabled = false;
  }
}

const hashMatch = /^#slide-(\d+)$/i.exec(window.location.hash || "");
const initialSlideIdx = hashMatch ? Math.max(0, Math.min(slides.length - 1, Number(hashMatch[1]) - 1)) : 0;

goToSlide(initialSlideIdx, false);
renderTrack(hasLockedTrack ? requestedTrack : "partner");
if (hasLockedTrack) {
  if (trackBar) trackBar.classList.add("is-hidden");
  const ey = document.querySelector('section[data-slide="12"] .slide-eyebrow');
  if (ey) ey.textContent = "Slide 12 · Proposed Path Forward & Collaboration Scope";
  const h2 = document.querySelector('section[data-slide="12"] h2');
  if (h2) h2.textContent = TRACKS[requestedTrack].shortTitle;
  document.title = `${TRACKS[requestedTrack].shortTitle} (v1.0.2) — Eutropos`;
}
hydrateEvidence();
