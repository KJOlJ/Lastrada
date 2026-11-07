let scheduled = false;

function normalize(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function updateRelationshipCopy() {
  document
    .querySelectorAll(".relationshipEvidenceCell small")
    .forEach((element) => {
      const text = normalize(element.textContent);
      if (
        text === "Run the stem + DTW check above." ||
        text === "Automatic Demucs + DTW evidence is pending."
      ) {
        element.textContent =
          "No grouped representative comparison is stored for this relationship.";
      } else if (
        text === "Retry the stem + DTW check above." ||
        text === "The automatic Demucs + DTW check could not finish."
      ) {
        element.textContent =
          "The integrated representative comparison could not finish.";
      }
    });
}

function updateTestingLimitCopy() {
  document.querySelectorAll("#view small").forEach((element) => {
    const text = normalize(element.textContent);
    if (
      text.includes("Up to 3 requests per person and 20 shared requests daily") ||
      text.includes("Demucs and stem-level DTW run automatically after")
    ) {
      element.textContent =
        "Sony, full-mix DTW, grouped Demucs and same-stem DTW run as one analysis before timestamp review. Testing limits are 25 operations per person and 200 shared operations daily.";
    }
  });
}

function hideLegacyInstrumentControls() {
  const controls = document.querySelector("#instruments");
  if (!controls) return;
  controls
    .querySelectorAll('button[data-action="stems"], button')
    .forEach((button) => {
      button.hidden = true;
      button.disabled = true;
      button.setAttribute("aria-hidden", "true");
      button.tabIndex = -1;
    });
  controls.hidden = true;
  controls.setAttribute("aria-hidden", "true");
  controls.dataset.integratedStemPipeline = "true";
}

function enhanceIntegratedStemFlow() {
  scheduled = false;
  updateRelationshipCopy();
  updateTestingLimitCopy();
  hideLegacyInstrumentControls();
}

function scheduleIntegratedStemFlow() {
  if (scheduled || typeof window === "undefined") return;
  scheduled = true;
  window.requestAnimationFrame(enhanceIntegratedStemFlow);
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const view = document.querySelector("#view");
  if (view) {
    new MutationObserver(scheduleIntegratedStemFlow).observe(view, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }
  window.addEventListener("load", scheduleIntegratedStemFlow);
  scheduleIntegratedStemFlow();
}
