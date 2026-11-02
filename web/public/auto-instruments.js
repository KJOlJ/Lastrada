const MAX_AUTOMATIC_PASSES = 6;

let activeAnalysisId = "";
let mockTransport = false;
let scheduled = false;
const automaticRuns = new Map();

function normalize(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function requestUrl(request) {
  if (typeof request === "string") return request;
  if (request instanceof URL) return request.href;
  return request?.url || "";
}

function runState() {
  const key = activeAnalysisId || "current-analysis";
  if (!automaticRuns.has(key)) {
    automaticRuns.set(key, { attempts: 0, signatures: new Set() });
  }
  return automaticRuns.get(key);
}

function controlsSignature(controls) {
  const copy = controls.cloneNode(true);
  copy
    .querySelectorAll(
      "button, .instrumentTable, .automaticInstrumentStatus, .spinner",
    )
    .forEach((element) => element.remove());
  return `${activeAnalysisId || "current-analysis"}|${normalize(copy.textContent)}`;
}

function statusLine(controls) {
  let status = controls.querySelector(".automaticInstrumentStatus");
  if (!status) {
    status = document.createElement("p");
    status.className = "automaticInstrumentStatus";
    status.setAttribute("role", "status");
    const description = controls.querySelector("p.muted");
    if (description?.nextSibling) description.after(status);
    else controls.prepend(status);
  }
  return status;
}

function updateRelationshipCopy() {
  document
    .querySelectorAll(".relationshipEvidenceCell small")
    .forEach((element) => {
      const text = normalize(element.textContent);
      if (text === "Run the stem + DTW check above.") {
        element.textContent = "Automatic Demucs + DTW evidence is pending.";
      } else if (text === "Retry the stem + DTW check above.") {
        element.textContent =
          "The automatic Demucs + DTW check could not finish.";
      }
    });
}

function updateTestingLimitCopy() {
  document.querySelectorAll("#view small").forEach((element) => {
    if (
      normalize(element.textContent).includes(
        "Up to 3 requests per person and 20 shared requests daily",
      )
    ) {
      element.textContent =
        "Demucs and stem-level DTW run automatically after the timestamp analysis. Testing limits are 25 operations per person and 200 shared operations daily.";
    }
  });
}

function enhanceAutomaticInstrumentFlow() {
  scheduled = false;
  if (mockTransport && !window.__LASTRADA_FORCE_AUTO_INSTRUMENTS__) return;

  updateRelationshipCopy();
  updateTestingLimitCopy();

  const controls = document.querySelector("#instruments");
  if (!controls) return;

  controls.classList.add("automaticInstrumentControls");
  const heading = controls.querySelector("h2");
  if (heading) heading.textContent = "Automatic stem + DTW evidence";
  const description = controls.querySelector("p.muted");
  if (description) {
    description.textContent =
      "After Sony identifies candidate regions, Demucs estimates the stems and stem-level DTW tests those matches automatically. Results appear in the final column below.";
  }

  const status = statusLine(controls);
  const action = controls.querySelector(
    'button[data-action="stems"]:not([disabled])',
  );

  controls
    .querySelectorAll('button[data-action="stems"], button:disabled')
    .forEach((button) => {
      button.hidden = true;
      button.setAttribute("aria-hidden", "true");
      button.tabIndex = -1;
    });

  if (action) {
    const label = normalize(action.textContent).toLowerCase();
    status.textContent = label.includes("continue")
      ? "Automatic Demucs + DTW analysis is continuing with the remaining matched moments."
      : label.includes("try")
        ? "Automatic Demucs + DTW analysis is retrying after an incomplete pass."
        : "Automatic Demucs + DTW analysis is starting.";

    const state = runState();
    const signature = controlsSignature(controls);
    if (
      state.attempts < MAX_AUTOMATIC_PASSES &&
      !state.signatures.has(signature)
    ) {
      state.attempts += 1;
      state.signatures.add(signature);
      window.setTimeout(() => {
        if (
          action.isConnected &&
          !(mockTransport && !window.__LASTRADA_FORCE_AUTO_INSTRUMENTS__)
        ) {
          action.click();
        }
      }, 0);
    } else if (state.attempts >= MAX_AUTOMATIC_PASSES) {
      status.textContent =
        "Automatic Demucs + DTW analysis reached its safe retry limit. Completed evidence is preserved.";
    }
    return;
  }

  const text = normalize(controls.textContent).toLowerCase();
  if (controls.querySelector(".spinner") || text.includes("in progress")) {
    status.textContent =
      "Automatic Demucs + DTW analysis is running. Results will appear in the relationship table.";
  } else if (
    text.includes("could not finish") ||
    text.includes("check failed") ||
    text.includes("unavailable")
  ) {
    status.textContent =
      "Automatic Demucs + DTW analysis could not finish. The Sony and timing analysis is still preserved.";
  } else if (
    text.includes("no eligible paired region") ||
    text.includes("instrument check unavailable")
  ) {
    status.textContent =
      "No paired region is long enough for automatic Demucs + DTW analysis.";
  } else if (
    text.includes("completed results are reused") ||
    /\d+ of \d+ moments compared/.test(text)
  ) {
    status.textContent =
      "Automatic Demucs + DTW analysis is complete. Review the evidence in the relationship table.";
  } else {
    status.textContent =
      "Automatic Demucs + DTW analysis will begin when paired timestamps are ready.";
  }
}

function scheduleAutomaticInstrumentFlow() {
  if (scheduled || typeof window === "undefined") return;
  scheduled = true;
  window.requestAnimationFrame(enhanceAutomaticInstrumentFlow);
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...arguments_) => {
    const response = await nativeFetch(...arguments_);
    try {
      const url = new URL(requestUrl(arguments_[0]), window.location.href);
      if (url.hostname.endsWith(".lastrada.test")) mockTransport = true;

      const match = url.pathname.match(/\/api\/analyses\/([^/]+)/);
      if (match) activeAnalysisId = match[1];

      if (
        response.ok &&
        url.pathname === "/api/analyses" &&
        String(arguments_[1]?.method || "GET").toUpperCase() === "POST"
      ) {
        response
          .clone()
          .json()
          .then((payload) => {
            if (payload?.id) activeAnalysisId = String(payload.id);
            scheduleAutomaticInstrumentFlow();
          })
          .catch(() => {});
      }
    } catch {}
    scheduleAutomaticInstrumentFlow();
    return response;
  };

  const view = document.querySelector("#view");
  if (view) {
    new MutationObserver(scheduleAutomaticInstrumentFlow).observe(view, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }
  window.addEventListener("load", scheduleAutomaticInstrumentFlow);
  scheduleAutomaticInstrumentFlow();
}
