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
  if (["INPUT", "SELECT", "TEXTAREA", "BUTTON", "A"].includes(tag)) return;
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
    title: "Option 1 — Frontier Lab / Robotics Partner (Zero Capital Ask)",
    badge: "Integration & Pilot Option",
    ask: "$0 Capital Ask · Immediate Plugin Integration",
    summary: "Run eutropos-referee==1.0.1 alongside existing inspect-robots pipelines or via standalone isolated execution to attach software custody chains today.",
    allocation: [
      "15-minute entry-point registration in existing inspect-robots CI / eval workflows",
      "Joint specification of 1 private hazard-escrowed surrogate family (e.g. I2 or H2)",
      "Cross-lab blinded bundle exchange verifiable in browser Web Crypto + CLI",
    ],
    milestones: [
      "Day 1: Prove open + hazard-escrowed live cryptographic custody chains on your tasks",
      "Post Stage-1 Bench ($1,291 Gate): Evaluate blinded checkpoints on physical fixture",
      "Post Rig Build: Co-publish third-party verified safety / capability appendix",
    ],
  },
  lean: {
    title: "Option 2 — Lean Physical Proof Pilot ($250k – $500k)",
    badge: "Capital-Efficient Physical Proof",
    ask: "$250,000 – $500,000 · 12-Month Lean Runway",
    summary: "Stage hardware spend behind empirical verification: build the $1,291+ A4 sensor bench first, then commission one P2 dual-division rig.",
    allocation: [
      "$1,291+ Stage-1 A4 Sensor Bench (Radwag WTC 2000 + Basler ace 2 + stereo & H1/H4 fixtures)",
      "~$40.9k Single P2 UFACTORY 850 + ORCA v2.1 Touch rig + ~$15k interchangeable fixtures/spares",
      "Founder metrology engineering, physical 240-trial A4 publication, and Season-0 open launch",
    ],
    milestones: [
      "Gate 1: Publish 240-trial physical A4 study measuring physical sensor accuracy",
      "Gate 2: Commission P2 dual-division cell + human teleop ceilings across 15 families",
      "Gate 3: First external robotics policies evaluated under Track B + initial pilot buyers",
    ],
  },
  preseed: {
    title: "Option 3 — Pre-Seed Operating Round ($1.5M – $3.0M)",
    badge: "Full Dual-Track Startup",
    ask: "$1.5M – $3.0M · 18-Month Operating Runway",
    summary: "Stand up twin matched P1 + P2 physical referee cells, continuous Season-1 public submissions, and paid confidential Track C audits for labs and OEMs.",
    allocation: [
      "Dual matched physical referee cells (P1 open-commercial + P2 tactile/blind-stereo)",
      "Engineering hires: robotics metrology, fixtures/CAD, and isolated runner infrastructure",
      "Enterprise compliance prep, escrow custody operations, and direct lab/insurer GTM",
    ],
    milestones: [
      "Month 4: Dual P1 + P2 cells operational with cross-cell human teleop baselines",
      "Month 9: Season-1 public leaderboard open to metered external policy submissions",
      "Month 18: 3+ paid Track C closed-bank audits delivered; ISO/IEC 17025 roadmap active",
    ],
  },
  seed: {
    title: "Option 4 — Institutional Seed ($5.0M+)",
    badge: "Bureau Scale Option",
    ask: "$5.0M+ Institutional Lead · 24-Month Runway",
    summary: "Scale standardized multi-region physical certification infrastructure spanning public Season leaderboards and insurer/regulatory-grade hazard escrow bureaus.",
    allocation: [
      "Multi-cell automated referee labs (US + EU) supporting rapid throughput across divisions",
      "HSM-backed escrow key ceremony infrastructure and full continuous telemetry archives",
      "Insurer underwriting & OEM procurement partnerships translating scores to deployment limits",
    ],
    milestones: [
      "Month 6: Regional twin physical referee cells + accredited calibration roadmap",
      "Month 12: Standing Season-1 & Season-2 capability index referenced by labs and buyers",
      "Month 24: Multi-enterprise Track C recurring audit contracts + insurer underwriting adoption",
    ],
  },
};

const params = new URLSearchParams(window.location.search);
const requestedTrack = (params.get("track") || "").trim().toLowerCase();
const hasLockedTrack = Object.prototype.hasOwnProperty.call(TRACKS, requestedTrack);

function renderTrack(trackKey) {
  const t = TRACKS[trackKey] || TRACKS.partner;
  document.querySelectorAll(".track-btn").forEach((b) => {
    const active = b.getAttribute("data-track") === trackKey;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", String(active));
  });
  const leftHeading = hasLockedTrack ? "Scope & Strategic Fit" : t.title;
  const host = document.getElementById("track-detail");
  host.innerHTML = `
    <div class="grid-2">
      <div class="panel panel-white">
        <span class="badge badge-pass">${esc(t.badge)}</span>
        <h3>${esc(leftHeading)}</h3>
        <div class="big-num">${esc(t.ask)}</div>
        <p class="small muted">${esc(t.summary)}</p>
      </div>
      <div class="panel panel-white">
        <h3>Capital / Effort Allocation</h3>
        <ul class="small">${t.allocation.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        <h3 class="mt-1">Concrete Execution Milestones</h3>
        <ul class="small">${t.milestones.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      </div>
    </div>
  `;
}

document.querySelectorAll(".track-btn").forEach((btn) => {
  btn.addEventListener("click", () => renderTrack(btn.getAttribute("data-track")));
});

async function hydrateEvidence() {
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
    parts.push(`<rect x="${pL + 150}" y="10" width="9" height="9" fill="#9C7A3C"/><text x="${pL + 164}" y="18" font-size="9.5" fill="#14171D" font-family="'JetBrains Mono', ui-monospace, monospace">S4 Decoy (n=15)</text>`);
    parts.push(`<rect x="${pL + 286}" y="10" width="9" height="9" fill="#14233C"/><text x="${pL + 300}" y="18" font-size="9.5" fill="#14171D" font-family="'JetBrains Mono', ui-monospace, monospace">S1 Clean FFR (n=15)</text>`);
    parts.push(`<line x1="${w - pR - 110}" y1="14" x2="${w - pR - 86}" y2="14" stroke="#795B2B" stroke-width="1.5" stroke-dasharray="5,4"/><text x="${w - pR}" y="18" text-anchor="end" font-size="9.5" font-weight="600" fill="#795B2B" font-family="'JetBrains Mono', ui-monospace, monospace">5% FPR Gate</text>`);
    [0, 10, 20, 30, 40, 50].forEach((tk) => {
      const yy = yF(tk);
      parts.push(`<line x1="${pL}" y1="${yy}" x2="${w - pR}" y2="${yy}" stroke="#DCD5C7" stroke-width="1"/>`);
      parts.push(`<text x="${pL - 6}" y="${yy + 3}" text-anchor="end" font-size="10" fill="#5A606A" font-family="'JetBrains Mono', ui-monospace, monospace">${tk}%</text>`);
    });
    const yt = yF(5);
    parts.push(`<line x1="${pL}" y1="${yt}" x2="${w - pR}" y2="${yt}" stroke="#795B2B" stroke-width="1.5" stroke-dasharray="5,4"/>`);

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
            <img src="${esc(SITE_ROOT + tr.left_img)}" alt="${esc(tr.opaque_id)} left"/>
            <img src="${esc(SITE_ROOT + tr.right_img)}" alt="${esc(tr.opaque_id)} right"/>
          </div>
          <p class="small"><strong>Simulator Ref:</strong> ${esc(tr.gt_reason)}</p>
        </div>
      `;
      })
      .join("");
  } catch {
    // Keeps static fallback readable without HTTP
  }
}

const hashMatch = /^#slide-(\d+)$/i.exec(window.location.hash || "");
const initialSlideIdx = hashMatch ? Math.max(0, Math.min(slides.length - 1, Number(hashMatch[1]) - 1)) : 0;

goToSlide(initialSlideIdx, false);
renderTrack(hasLockedTrack ? requestedTrack : "partner");
if (hasLockedTrack) {
  const bar = document.querySelector(".track-bar");
  if (bar) bar.classList.add("is-hidden");
  const ey = document.querySelector('section[data-slide="12"] .slide-eyebrow');
  if (ey) ey.textContent = "Slide 12 · Proposed Path Forward & Collaboration Scope";
  const h2 = document.querySelector('section[data-slide="12"] h2');
  if (h2) h2.textContent = TRACKS[requestedTrack].title;
}
hydrateEvidence();
