import { groupIntervals } from "./grouped-timestamps.js";
import { summarizeRelationshipEvidence } from "./relationship-evidence.js";
import {
  buildDraftNarrative,
  formatTimestamp,
  inferNatureSummary,
  placementLabels,
} from "./nature-summary.js";

let scheduled = false;
let mockTransport = false;
let activeAnalysisId = "";
let latestPayload = null;
let latestBearer = "";
let loadedConfig = null;
let confirmedIntervals = [];
let reviewState = null;
let singleReviewMounted = false;
let saving = false;

const normalize = (value) =>
  String(value || "")
    .replace(/\s+/g, " ")
    .trim();

function enabled() {
  return !mockTransport || window.__LASTRADA_FORCE_SINGLE_REVIEW__;
}

function requestDetails(request, options = {}) {
  const url =
    typeof request === "string"
      ? request
      : request instanceof URL
        ? request.href
        : request?.url || "";
  const headers = new Headers(
    options.headers || (request instanceof Request ? request.headers : undefined),
  );
  return { url, headers };
}

function captureRequest(request, options) {
  try {
    const { url, headers } = requestDetails(request, options);
    const parsed = new URL(url, window.location.href);
    if (parsed.hostname.endsWith(".lastrada.test")) mockTransport = true;
    const authorization = headers.get("authorization");
    if (authorization?.startsWith("Bearer ")) latestBearer = authorization;
    const match = parsed.pathname.match(/\/api\/analyses\/([^/]+)/);
    if (match) activeAnalysisId = match[1];
  } catch {}
}

function captureResponse(request, options, response) {
  try {
    const { url } = requestDetails(request, options);
    const parsed = new URL(url, window.location.href);
    if (parsed.pathname === "/config.json" && response.ok) {
      response
        .clone()
        .json()
        .then((value) => {
          loadedConfig = value;
        })
        .catch(() => {});
    }
    if (
      parsed.pathname === "/api/analyses" &&
      String(options?.method || "GET").toUpperCase() === "POST" &&
      response.ok
    ) {
      response
        .clone()
        .json()
        .then((value) => {
          if (value?.id) activeAnalysisId = String(value.id);
        })
        .catch(() => {});
    }
    if (
      /\/api\/analyses\/[^/]+\/result$/.test(parsed.pathname) &&
      response.ok
    ) {
      response
        .clone()
        .json()
        .then((value) => {
          latestPayload = value;
          scheduleEnhancement();
        })
        .catch(() => {});
    }
    if (
      /\/api\/analyses\/[^/]+\/review$/.test(parsed.pathname) &&
      response.ok
    ) {
      response
        .clone()
        .json()
        .then((value) => {
          if (latestPayload && value?.analysis) latestPayload.analysis = value.analysis;
        })
        .catch(() => {});
    }
  } catch {}
}

const nativeFetch = window.fetch.bind(window);
window.fetch = async (...arguments_) => {
  captureRequest(arguments_[0], arguments_[1]);
  const response = await nativeFetch(...arguments_);
  captureResponse(arguments_[0], arguments_[1], response);
  return response;
};

function notice(message) {
  const box = document.querySelector("#notice");
  if (!box) return;
  box.textContent = message;
  box.hidden = !message;
  if (message) box.scrollIntoView({ block: "nearest" });
}

function parseNumber(cell) {
  const input = cell?.querySelector('input[type="number"]');
  const raw = input ? input.value : cell?.textContent;
  if (!raw || /not located/i.test(raw)) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function timestampTable(track) {
  return (
    track?.querySelector(".exactTimestamps table") ||
    [...(track?.querySelectorAll("table") || [])].find((table) =>
      /original starts/i.test(table.tHead?.textContent || ""),
    )
  );
}

function intervalsFromTimestampScreen() {
  const track = document.querySelector('.track[data-rights="master"]');
  const table = timestampTable(track);
  if (!table) return [];
  return [...(table.tBodies?.[0]?.rows || [])]
    .map((row) => {
      const cells = [...row.cells];
      return {
        new_start: parseNumber(cells[0]),
        new_end: parseNumber(cells[1]),
        original_start: parseNumber(cells[2]),
        original_end: parseNumber(cells[3]),
        source: "creator_review",
        status: "candidate",
      };
    })
    .filter(
      (interval) =>
        Number.isFinite(interval.new_start) &&
        Number.isFinite(interval.new_end) &&
        interval.new_end > interval.new_start &&
        ((interval.original_start == null && interval.original_end == null) ||
          (Number.isFinite(interval.original_start) &&
            Number.isFinite(interval.original_end) &&
            interval.original_end > interval.original_start)),
    );
}

function ensureMasterAssumption() {
  const master = document.querySelector('.track[data-rights="master"]');
  const publishing = document.querySelector('.track[data-rights="publishing"]');
  if (publishing) {
    const status = publishing.querySelector('[data-field="status"]');
    if (status && status.value !== "no_use") {
      status.value = "no_use";
      status.dispatchEvent(new Event("change", { bubbles: true }));
      return false;
    }
    publishing.hidden = true;
  }
  if (master) {
    const status = master.querySelector('[data-field="status"]');
    if (status && status.value === "pending") {
      status.value = "confirmed";
      status.dispatchEvent(new Event("change", { bubbles: true }));
      return false;
    }
    const statusLabel = status?.closest("label");
    if (statusLabel) statusLabel.hidden = true;
    if (!master.querySelector(".masterAssumption")) {
      const assumption = document.createElement("p");
      assumption.className = "masterAssumption";
      assumption.textContent =
        "Rights assumption: the derivative track samples the original master recording.";
      master.prepend(assumption);
    }
  }
  return true;
}

function updateProgress(step, label) {
  const progress = document.querySelector("#progress");
  if (!progress) return;
  progress.innerHTML = `STEP ${step} OF 4 · ${label}<div class="bar"><span style="width:${step * 25}%"></span></div>`;
}

function enhanceUploadScreen() {
  updateProgress(1, "Your tracks");
  const muted = document.querySelector("#view h1 + .muted");
  if (muted) {
    muted.textContent =
      "Add the original master recording and the derivative track. We will identify candidate sample uses, confirm the timestamps, and prepare one editable Nature of Use draft.";
  }
  document.querySelectorAll("#view .warning").forEach((warning) => {
    if (/both types|replayed music|recording samples/i.test(warning.textContent)) {
      warning.textContent =
        "This workflow assumes the original master recording was sampled. It does not create a separate publishing or replay analysis.";
    }
  });
}

function enhanceAnalysisScreen() {
  updateProgress(2, "Finding the sample");
}

function enhanceTimestampScreen() {
  if (!ensureMasterAssumption()) return;
  updateProgress(3, "Confirm timestamps");
  const heading = document.querySelector("#view h1");
  if (heading) heading.textContent = "Confirm the sample timestamps.";
  const paragraphs = [...document.querySelectorAll("#view > p.muted")];
  if (paragraphs[0]) {
    paragraphs[0].textContent =
      "Listen to the candidate uses, accept the timestamps you hear, or unlock the table to correct them.";
  }
  paragraphs.slice(1).forEach((paragraph) => paragraph.remove());
  const next = document.querySelector(
    '#view button[data-action="next"].primary',
  );
  if (next) next.textContent = "Review Nature of Use draft →";
}

function activeIntervals() {
  if (confirmedIntervals.length) return confirmedIntervals;
  const corrected = latestPayload?.analysis?.review?.corrected?.master?.locate
    ?.sample_occurrences;
  if (Array.isArray(corrected) && corrected.length) return corrected;
  const suggestion = latestPayload?.suggestions?.master?.intervals;
  return Array.isArray(suggestion) ? suggestion : [];
}

function credits() {
  const analysis = latestPayload?.analysis;
  return {
    originalTitle: analysis?.input?.original_work?.title || "",
    originalArtist: analysis?.input?.original_work?.artist || "",
    newTitle: analysis?.input?.new_work?.title || "",
    newArtist: analysis?.input?.new_work?.artist || "",
  };
}

function correctedMaster() {
  return latestPayload?.analysis?.review?.corrected?.master || null;
}

function summaryFromData() {
  const analysis = latestPayload?.analysis || {};
  return inferNatureSummary({
    intervals: activeIntervals(),
    newDuration: Number(analysis.durations?.new || 0),
    instrumentRows:
      latestPayload?.instrument_rows || analysis.instrument_occurrences || [],
    stemEvidence: analysis.stem_evidence || [],
    backendSummary: latestPayload?.nature_of_use_summary || null,
  });
}

function correctedElement(path) {
  return (
    path?.describe?.elements?.find(
      (feature) => feature.feature === "musical_element",
    )?.value || ""
  );
}

function initializeReviewState() {
  const analysis = latestPayload?.analysis || {};
  const summary = summaryFromData();
  const corrected = correctedMaster();
  const correctedNarrative = analysis.review?.corrected?.nature_of_use?.text;
  reviewState = {
    intervals: activeIntervals().map((interval) => ({ ...interval })),
    summary,
    element: correctedElement(corrected) || summary.elementSuggestion,
    samplingLabel:
      corrected?.describe?.repetition || summary.samplingLabel,
    role: corrected?.describe?.role_in_new_song || summary.roleSuggestion,
    placement: corrected?.classification?.placement || summary.placement,
    sections: corrected?.describe?.sections?.length
      ? [...corrected.describe.sections]
      : [...summary.sections],
    narrative:
      correctedNarrative || buildDraftNarrative(summary, credits()),
    reviewer: analysis.review?.reviewer || "Creator",
    notes: analysis.review?.notes || "",
    narrativeTouched: Boolean(correctedNarrative),
    fieldsTouched: Boolean(corrected),
    approved: analysis.review?.status === "approved",
  };
}

function refreshReviewState() {
  if (!reviewState) {
    initializeReviewState();
    return;
  }
  const nextSummary = summaryFromData();
  const oldStemSignature = reviewState.summary.sampledStems.join("|");
  const nextStemSignature = nextSummary.sampledStems.join("|");
  reviewState.summary = nextSummary;
  reviewState.intervals = activeIntervals().map((interval) => ({ ...interval }));
  if (!reviewState.fieldsTouched && oldStemSignature !== nextStemSignature) {
    reviewState.element = nextSummary.elementSuggestion;
  }
  if (!reviewState.narrativeTouched && oldStemSignature !== nextStemSignature) {
    reviewState.narrative = buildDraftNarrative(nextSummary, credits());
  }
}

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
}

function timeRange(start, end) {
  return `${formatTimestamp(start)}–${formatTimestamp(end)}`;
}

function acceptedEntriesForFamily(family) {
  const rows =
    latestPayload?.instrument_rows ||
    latestPayload?.analysis?.instrument_occurrences ||
    [];
  return summarizeRelationshipEvidence(family, rows).entries.filter(
    (entry) =>
      entry.result === "accepted" && entry.sourceStem === entry.newStem,
  );
}

function relationshipRows() {
  const duration = Number(latestPayload?.analysis?.durations?.new || 0);
  return groupIntervals(reviewState.intervals, duration);
}

function relationshipTableHtml() {
  const families = relationshipRows();
  if (!families.length) {
    return '<p class="muted">No confirmed timestamp relationship is available.</p>';
  }
  return `<div class="singleRelationshipWrap"><table class="singleRelationshipTable" aria-label="Confirmed sample relationships"><thead><tr><th>Original passage</th><th>Derivative timestamps</th><th>Use pattern</th><th>Matched stem</th></tr></thead><tbody>${families
    .map((family) => {
      const originals = family.sourcePassages.length
        ? family.sourcePassages
            .map((passage) => timeRange(passage.start, passage.end))
            .join(", ")
        : "Original passage not located";
      const derivative = family.occurrences
        .map((occurrence) => timeRange(occurrence.new_start, occurrence.new_end))
        .join(", ");
      const stems = acceptedEntriesForFamily(family);
      const stemText = stems.length
        ? stems
            .map((entry) => {
              const ratio = Number.isFinite(entry.durationRatio)
                ? `, ${entry.durationRatio.toFixed(2)}× duration`
                : "";
              return `${entry.sourceStem.replaceAll("_", " ")} matched across ${entry.momentCount} ${entry.momentCount === 1 ? "moment" : "moments"}${ratio}`;
            })
            .join("; ")
        : "No supporting same-stem match";
      return `<tr><td>${esc(originals)}</td><td>${esc(derivative)}</td><td><strong>${esc(family.useType)}</strong><small>${esc(family.pattern)}</small></td><td>${esc(stemText)}</td></tr>`;
    })
    .join("")}</tbody></table></div>`;
}

function stemStatusHtml() {
  const rows =
    latestPayload?.instrument_rows ||
    latestPayload?.analysis?.instrument_occurrences ||
    [];
  const pending = rows.filter((row) =>
    ["pending", "failed"].includes(row.status),
  ).length;
  const checked = rows.filter((row) => row.status === "checked").length;
  const accepted = reviewState.summary.stemMatches.length;
  if (pending) {
    return `<p class="singleAnalysisStatus"><span class="spinner"></span> Demucs and same-stem DTW are still running. ${checked} moments are complete and ${pending} remain.</p>`;
  }
  if (accepted) {
    return `<p class="singleAnalysisStatus complete">Stem analysis complete. ${accepted} supporting same-stem ${accepted === 1 ? "match" : "matches"} found.</p>`;
  }
  return '<p class="singleAnalysisStatus complete">Stem analysis complete. No supporting same-stem match was found.</p>';
}

function option(value, label, selected) {
  return `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(label)}</option>`;
}

function sectionChecksHtml() {
  const labels = [
    ["whole track", "Whole track"],
    ["intro", "Intro"],
    ["verse", "Verse"],
    ["chorus", "Chorus"],
    ["bridge", "Bridge"],
    ["outro", "Outro"],
  ];
  return labels
    .map(
      ([value, label]) =>
        `<label><input type="checkbox" data-single-section="${esc(value)}" ${reviewState.sections.includes(value) ? "checked" : ""}>${esc(label)}</label>`,
    )
    .join("");
}

function renderSingleReview() {
  if (!enabled()) return;
  refreshReviewState();
  singleReviewMounted = true;
  updateProgress(4, "Draft Nature of Use");
  const summary = reviewState.summary;
  const c = credits();
  const view = document.querySelector("#view");
  if (!view) return;
  view.innerHTML = `<section class="singleNatureReview">
    <div class="singleReviewHeader">
      <div><p class="eyebrow">MASTER SAMPLE ASSUMPTION</p><h1>Draft Nature of Use</h1><p class="muted">Everything derived from the confirmed timestamps is collected here. Edit any estimate, approve the draft, and open the final print version.</p></div>
      <span class="reviewStateBadge">${reviewState.approved ? "Reviewed" : "Draft"}</span>
    </div>
    ${stemStatusHtml()}
    <div class="summaryStats">
      <article><strong>${summary.coveragePercentage.toFixed(1)}%</strong><span>of derivative track</span><small>${summary.coveredSeconds.toFixed(1)} seconds covered</small></article>
      <article><strong>${summary.distinctUses}</strong><span>${summary.distinctUses === 1 ? "distinct use" : "distinct uses"}</span><small>${summary.samplingLabel}</small></article>
      <article><strong>${esc(summary.sampledStems.length ? summary.sampledStems.map((stem) => stem.replaceAll("_", " ")).join(", ") : "Unconfirmed")}</strong><span>sampled stem</span><small>Accepted same-stem DTW only</small></article>
      <article><strong>${esc(placementLabels[reviewState.placement] || "Selected sections")}</strong><span>estimated placement</span><small>${esc(summary.placementBasis)}</small></article>
    </div>
    <div class="singleReviewGrid">
      <label>Sampled stem or element<input data-single-field="element" value="${esc(reviewState.element)}"></label>
      <label>Sampling pattern<select data-single-field="samplingLabel">
        ${[
          "One-off use",
          "Repeated in multiple passages",
          "A short loop repeated in the track",
          "Repeated throughout the track",
        ]
          .map((label) => option(label, label, reviewState.samplingLabel))
          .join("")}
      </select></label>
      <label>Overall placement<select data-single-field="placement">
        ${Object.entries(placementLabels)
          .map(([value, label]) => option(value, label, reviewState.placement))
          .join("")}
      </select></label>
      <label>Role in the derivative track<input data-single-field="role" value="${esc(reviewState.role)}"></label>
    </div>
    <fieldset class="singleSections"><legend>Song sections</legend><div>${sectionChecksHtml()}</div><small>These labels are estimates from timing patterns. Change them when listening indicates a different section.</small></fieldset>
    <section class="singleEvidence">
      <div class="sectionHeading"><div><p class="eyebrow">TIMESTAMP EVIDENCE</p><h2>Confirmed sample relationships</h2></div><span>${esc(c.originalTitle || "Original")} → ${esc(c.newTitle || "Derivative")}</span></div>
      ${relationshipTableHtml()}
    </section>
    <label class="draftNarrative">Editable Nature of Use draft<textarea rows="10" data-single-field="narrative">${esc(reviewState.narrative)}</textarea></label>
    <div class="draftTools">
      <button data-single-action="regenerate">Regenerate from analysis</button>
      <label>Reviewer<input data-single-field="reviewer" value="${esc(reviewState.reviewer)}"></label>
      <label>Review notes<textarea rows="2" data-single-field="notes">${esc(reviewState.notes)}</textarea></label>
    </div>
    <div class="singleReviewActions">
      <button data-action="back">← Back to timestamps</button>
      <button data-single-action="save">Save draft</button>
      <button class="primary" data-single-action="approve-print">Approve and open print version</button>
    </div>
    <p class="singleDisclaimer">This is a music-use description, not a license or legal clearance decision.</p>
  </section>`;
}

function sectionDefaultsForPlacement(placement) {
  return {
    throughout: ["whole track"],
    intro_only: ["intro"],
    outro_only: ["outro"],
    intro_outro_with_chorus: ["intro", "chorus", "outro"],
    intro_outro_without_chorus: ["intro", "outro"],
    chorus_only: ["chorus"],
    verses: ["verse"],
    bridge_only: ["bridge"],
    selected_sections: ["verse", "chorus"],
    one_time: ["verse"],
  }[placement] || ["verse"];
}

function handleSingleInput(event) {
  const field = event.target.dataset.singleField;
  if (!field || !reviewState) return;
  reviewState[field] = event.target.value;
  if (field === "narrative") reviewState.narrativeTouched = true;
  else {
    reviewState.fieldsTouched = true;
    if (field === "placement") {
      reviewState.sections = sectionDefaultsForPlacement(event.target.value);
      renderSingleReview();
      return;
    }
  }
  reviewState.approved = false;
}

function handleSectionChange(event) {
  const section = event.target.dataset.singleSection;
  if (!section || !reviewState) return;
  const selected = new Set(reviewState.sections);
  if (event.target.checked) selected.add(section);
  else selected.delete(section);
  if (section === "whole track" && event.target.checked) {
    reviewState.sections = ["whole track"];
    reviewState.placement = "throughout";
  } else {
    selected.delete("whole track");
    reviewState.sections = [...selected];
    if (!reviewState.sections.length) reviewState.sections = ["verse"];
  }
  reviewState.fieldsTouched = true;
  reviewState.approved = false;
  renderSingleReview();
}

async function ensureConfig() {
  if (loadedConfig?.apiBase) return loadedConfig;
  const response = await nativeFetch("/config.json", { cache: "no-store" });
  if (!response.ok) throw Error("The workspace configuration could not be loaded.");
  loadedConfig = await response.json();
  return loadedConfig;
}

async function bearer() {
  if (latestBearer) return latestBearer;
  try {
    const appModule = await import(
      "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js"
    );
    const authModule = await import(
      "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js"
    );
    const apps = appModule.getApps();
    const current = apps.length ? authModule.getAuth(apps[0]).currentUser : null;
    if (!current) throw Error();
    latestBearer = `Bearer ${await current.getIdToken()}`;
    if (reviewState?.reviewer === "Creator") {
      reviewState.reviewer = current.displayName || current.email || "Creator";
    }
    return latestBearer;
  } catch {
    throw Error("Sign in again before saving the Nature of Use draft.");
  }
}

async function api(path, options = {}) {
  const config = await ensureConfig();
  const response = await nativeFetch(config.apiBase + path, {
    ...options,
    headers: {
      Authorization: await bearer(),
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let message = "The request could not finish.";
    try {
      const payload = await response.json();
      message =
        typeof payload.detail === "string"
          ? payload.detail
          : JSON.stringify(payload.detail);
    } catch {}
    throw Error(message);
  }
  return response;
}

function reviewPaths() {
  const intervalPayload = reviewState.intervals.map((interval) => ({
    new_start: Number(interval.new_start),
    new_end: Number(interval.new_end),
    original_start:
      interval.original_start == null ? null : Number(interval.original_start),
    original_end:
      interval.original_end == null ? null : Number(interval.original_end),
    source: "creator_review",
  }));
  const master = {
    status: "confirmed",
    intervals: intervalPayload,
    times_confirmed: true,
    details_confirmed: true,
    element: reviewState.element.trim() || "Sampled material",
    lyrics: "",
    method: "Sampled from the original master recording",
    repetition: reviewState.samplingLabel,
    role: reviewState.role.trim() || "Supporting sampled element",
    sections: reviewState.sections.length ? reviewState.sections : ["verse"],
    placement: reviewState.placement || "selected_sections",
  };
  const paths = { master };
  const scope = latestPayload?.analysis?.input?.analysis_scope || ["master"];
  if (scope.includes("publishing")) {
    paths.publishing = {
      status: "no_use",
      intervals: [],
      times_confirmed: false,
      details_confirmed: true,
      element: "",
      lyrics: "",
      method: "",
      repetition: "",
      role: "",
      sections: [],
      placement: null,
    };
  }
  return paths;
}

async function saveReview(approve) {
  if (saving) return;
  if (!activeAnalysisId) {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key?.startsWith("lastrada:")) {
        activeAnalysisId = localStorage.getItem(key) || "";
        if (activeAnalysisId) break;
      }
    }
  }
  if (!activeAnalysisId) throw Error("The current analysis could not be identified.");
  if (!reviewState.intervals.length) throw Error("Confirm at least one timestamp before saving.");
  saving = true;
  try {
    const response = await api(`/api/analyses/${activeAnalysisId}/review`, {
      method: "PUT",
      body: JSON.stringify({
        paths: reviewPaths(),
        narrative: reviewState.narrative.trim(),
        reviewer: reviewState.reviewer.trim() || "Creator",
        notes: reviewState.notes.trim(),
        approve,
      }),
    });
    const value = await response.json();
    if (latestPayload && value?.analysis) latestPayload.analysis = value.analysis;
    reviewState.approved = value?.analysis?.review?.status === "approved";
    notice(approve ? "Reviewed. The print version is opening." : "Draft saved.");
  } finally {
    saving = false;
  }
}

function printHtml() {
  const summary = reviewState.summary;
  const c = credits();
  const timestamps = summary.mergedDerivativeRanges
    .map(([start, end]) => timeRange(start, end))
    .join(", ");
  return `<!doctype html><html><head><meta charset="utf-8"><title>Nature of Use</title><style>
    body{font:16px/1.6 system-ui,-apple-system,sans-serif;max-width:850px;margin:40px auto;padding:28px;color:#181329}
    h1{margin-bottom:0}.meta{color:#625b70;margin-top:4px}.summary{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin:28px 0}
    .summary div{border:1px solid #d9d4e2;border-radius:12px;padding:14px}.summary strong{display:block;font-size:22px}
    article{white-space:pre-wrap;border-top:2px solid #4b2787;padding-top:22px}.foot{margin-top:35px;font-size:13px;color:#625b70}
    @media print{body{margin:0;max-width:none}.noPrint{display:none}}
  </style></head><body>
    <h1>Nature of Use</h1><p class="meta">Reviewed by ${esc(reviewState.reviewer)} · Master recording sample</p>
    <p><strong>Original track:</strong> ${esc(c.originalTitle)}${c.originalArtist ? ` by ${esc(c.originalArtist)}` : ""}<br>
    <strong>Derivative track:</strong> ${esc(c.newTitle)}${c.newArtist ? ` by ${esc(c.newArtist)}` : ""}</p>
    <div class="summary">
      <div><strong>${summary.coveragePercentage.toFixed(1)}%</strong>of the derivative track</div>
      <div><strong>${summary.distinctUses}</strong>distinct ${summary.distinctUses === 1 ? "use" : "uses"}</div>
      <div><strong>${esc(reviewState.element)}</strong>sampled stem or element</div>
      <div><strong>${esc(placementLabels[reviewState.placement] || "Selected sections")}</strong>placement</div>
    </div>
    <p><strong>Sampling pattern:</strong> ${esc(reviewState.samplingLabel)}<br>
    <strong>Sections:</strong> ${esc(reviewState.sections.join(", "))}<br>
    <strong>Confirmed derivative timestamps:</strong> ${esc(timestamps)}</p>
    <article>${esc(reviewState.narrative)}</article>
    ${reviewState.notes ? `<p><strong>Review notes:</strong> ${esc(reviewState.notes)}</p>` : ""}
    <p class="foot">This document describes musical use. It is not a license or a legal clearance decision.</p>
    <script>window.addEventListener("load",()=>setTimeout(()=>window.print(),200));<\/script>
  </body></html>`;
}

async function approveAndPrint() {
  const printWindow = window.open("", "_blank");
  if (!printWindow) throw Error("Allow pop-ups to open the final print version.");
  printWindow.document.write("<p>Preparing the reviewed Nature of Use…</p>");
  try {
    await saveReview(true);
    printWindow.document.open();
    printWindow.document.write(printHtml());
    printWindow.document.close();
    renderSingleReview();
  } catch (error) {
    printWindow.close();
    throw error;
  }
}

function regenerateDraft() {
  reviewState.summary = summaryFromData();
  reviewState.element = reviewState.summary.elementSuggestion;
  reviewState.samplingLabel = reviewState.summary.samplingLabel;
  reviewState.role = reviewState.summary.roleSuggestion;
  reviewState.placement = reviewState.summary.placement;
  reviewState.sections = [...reviewState.summary.sections];
  reviewState.narrative = buildDraftNarrative(reviewState.summary, credits());
  reviewState.narrativeTouched = false;
  reviewState.fieldsTouched = false;
  reviewState.approved = false;
  renderSingleReview();
}

async function handleSingleAction(action) {
  if (action === "regenerate") regenerateDraft();
  else if (action === "save") {
    await saveReview(false);
    renderSingleReview();
  } else if (action === "approve-print") await approveAndPrint();
}

function currentHeading() {
  return normalize(document.querySelector("#view h1")?.textContent);
}

function enhanceFlow() {
  scheduled = false;
  if (!enabled()) return;
  const heading = currentHeading();
  if (heading === "Start with the music.") {
    singleReviewMounted = false;
    reviewState = null;
    confirmedIntervals = [];
    enhanceUploadScreen();
  } else if (heading === "Finding your sample.") {
    enhanceAnalysisScreen();
  } else if (
    heading === "Listen & check." ||
    heading === "Confirm the sample timestamps."
  ) {
    singleReviewMounted = false;
    enhanceTimestampScreen();
  } else if (
    [
      "What did you use?",
      "Where does it fit?",
      "Make it yours.",
      "Your Nature of Use.",
    ].includes(heading)
  ) {
    renderSingleReview();
  } else if (singleReviewMounted && document.querySelector(".singleNatureReview")) {
    refreshReviewState();
  }
}

function scheduleEnhancement() {
  if (scheduled || typeof window === "undefined") return;
  scheduled = true;
  window.requestAnimationFrame(enhanceFlow);
}

document.addEventListener(
  "click",
  async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (
      button.dataset.action === "next" &&
      ["Listen & check.", "Confirm the sample timestamps."].includes(
        currentHeading(),
      )
    ) {
      const intervals = intervalsFromTimestampScreen();
      if (intervals.length) confirmedIntervals = intervals;
      window.setTimeout(scheduleEnhancement, 0);
      return;
    }
    const action = button.dataset.singleAction;
    if (!action) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      notice("");
      await handleSingleAction(action);
    } catch (error) {
      notice(error.message);
    }
  },
  true,
);

document.addEventListener("input", handleSingleInput, true);
document.addEventListener("change", (event) => {
  if (event.target.dataset.singleSection) handleSectionChange(event);
  else handleSingleInput(event);
}, true);

const view = document.querySelector("#view");
if (view) {
  new MutationObserver(scheduleEnhancement).observe(view, {
    childList: true,
    subtree: true,
    characterData: true,
  });
}
window.addEventListener("load", scheduleEnhancement);
scheduleEnhancement();
