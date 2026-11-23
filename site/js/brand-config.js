// Canonical brand and verifier trust anchor registry.
export const DEMO_SIGNER_KEYS = Object.freeze({
  "1ce3689cc2c269b4": {
    label: "Eutropos Demo Signer (Track B · Open Software Demo)",
    sha256: "1ce3689cc2c269b4ebbb578bf42d6e712365167191d94466833ee48448ab5744",
    evidenceClass: "software-demo",
  },
  "1d496df7c8a8001a": {
    label: "Eutropos Demo Signer (Track C · Escrowed Software Demo)",
    sha256: "1d496df7c8a8001a04bf5b61825eab89f64a77be1c10589c5bb80181485f25cd",
    evidenceClass: "software-demo",
  },
});

export const BRAND_CONFIG = Object.freeze({
  BRAND_NAME: "Eutropos",
  LEGAL_NAME: "Eutropos",
  TAGLINE: "Independent Physical Referee & Open-Kit Standard for Embodied AI",
  VERSION: "1.0.1",
  RELEASE_TAG: "v1.0.1",
  PROTOCOL_SCHEMA: "eutropos-referee-v1.0",
  DOMAIN: "different-change.github.io/eutropos",
  GITHUB_URL: "https://github.com/different-change/eutropos",
  PYPI_PACKAGE: "eutropos-referee",
  PINNED_INSTALL_CMD: 'pip install "git+https://github.com/different-change/eutropos.git@v1.0.1#subdirectory=referee"',
  CONTACT_EMAIL: "different.change@pm.me",
  INSPECT_ROBOTS_COMPAT: "inspect-robots==1.0.0",
});

export function applyBrandBindings(root = document) {
  for (const el of root.querySelectorAll("[data-brand]")) {
    const key = el.getAttribute("data-brand");
    if (key && Object.prototype.hasOwnProperty.call(BRAND_CONFIG, key)) {
      const val = BRAND_CONFIG[key];
      if (el.tagName === "A" && key === "GITHUB_URL") {
        el.setAttribute("href", val);
      } else if (el.tagName === "A" && key === "CONTACT_EMAIL") {
        el.setAttribute("href", `mailto:${val}`);
        el.textContent = val;
      } else {
        el.textContent = val;
      }
    }
  }
}
