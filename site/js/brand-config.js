// Global brand configuration. Update fields here before public deployment.
export const BRAND_CONFIG = Object.freeze({
  BRAND_NAME: "Habilis",
  LEGAL_NAME: "Habilis",
  TAGLINE: "Independent Physical Certification Standard for Embodied AI",
  VERSION: "1.0.0",
  PROTOCOL_SCHEMA: "habilis-referee-v1.0",
  DOMAIN: "different-change.github.io/habilis",
  GITHUB_URL: "https://github.com/different-change/habilis",
  PYPI_PACKAGE: "habilis-referee",
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
