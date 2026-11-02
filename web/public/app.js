import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  onAuthStateChanged,
  signOut,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
const $ = (s) => document.querySelector(s),
  esc = (x) =>
    String(x ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
let config,
  auth,
  user,
  caseId,
  analysis,
  forms = {},
  step = -1,
  polling = 0,
  narrative = "",
  generated = "",
  notes = "",
  reviewer = "",
  approved = false,
  localFiles = {},
  audioUrls = {},
  comparison,
  plotPromise,
  instrumentBusy = false,
  instrumentMessage = "",
  instrumentError = "";
const titles = [
  "Your tracks",
  "Finding your sample",
  "Listen & check",
  "Describe the sound",
  "Place the sample",
  "Review your draft",
  "Your Nature of Use",
];
const placements = {
  throughout: "Throughout the track",
  intro_only: "Intro only",
  outro_only: "Outro only",
  intro_outro_with_chorus: "Intro / outro and chorus",
  intro_outro_without_chorus: "Intro / outro outside chorus",
  chorus_only: "Choruses only",
  verses: "Verses",
  bridge_only: "Bridge only",
  selected_sections: "Selected sections",
  one_time: "One appearance",
};
function notice(message) {
  $("#notice").textContent = message;
  $("#notice").hidden = !message;
  if (message) $("#notice").scrollIntoView({ block: "nearest" });
}
function button(label, action, primary = false) {
  return `<button data-action="${action}" class="${primary ? "primary" : ""}">${label}</button>`;
}
function frame(content) {
  $("#progress").innerHTML =
    step < 0
      ? ""
      : `STEP ${step + 1} OF 7 · ${titles[step]}<div class="bar"><span style="width:${((step + 1) / 7) * 100}%"></span></div>`;
  $("#view").innerHTML = content;
  window.scrollTo({ top: 0, behavior: "instant" });
}
function field(label, key, value = "", placeholder = "") {
  return `<label>${label}<input data-field="${key}" value="${esc(value)}" placeholder="${esc(placeholder)}"></label>`;
}
function nav(next) {
  return `<div class="stepNav">${step > 2 ? button("← Back", "back") : button("New Sample", "new")}${button(next, "next", true)}</div>`;
}
function creditsFrom(name) {
  const stem = name.replace(/\.[^.]+$/, "");
  let parts = stem.split(/\s+by\s+/i);
  if (parts.length === 2)
    return { title: parts[0].trim(), artist: parts[1].trim() };
  parts = stem.split(/\s+[-–—]\s+/);
  return parts.length === 2
    ? { title: parts[1].trim(), artist: parts[0].trim() }
    : {};
}
async function api(path, options = {}) {
  const token = await user.getIdToken();
  const response = await fetch(config.apiBase + path, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let detail = "The request could not finish. Please try again.";
    try {
      const data = await response.json();
      detail =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
    } catch {}
    throw Error(detail);
  }
  return response;
}
async function json(path, options) {
  return (await api(path, options)).json();
}
function reset() {
  polling++;
  for (const url of Object.values(audioUrls)) URL.revokeObjectURL(url);
  audioUrls = {};
  localFiles = {};
  caseId = null;
  analysis = null;
  forms = {};
  comparison = null;
  instrumentBusy = false;
  instrumentMessage = "";
  instrumentError = "";
  narrative = "";
  generated = "";
  notes = "";
  approved = false;
  reviewer = user?.displayName || "";
  step = user ? 0 : -1;
  if (user) localStorage.removeItem(`lastrada:${user.uid}`);
  notice("");
  render();
}
function render() {
  if (step < 0) {
    frame(
      `<div class="landing"><h1>Your Music, Your Time.</h1><p class="muted">Upload your tracks, check where your sample appears, and create your Nature of Use document.</p>${button("Start", "start", true)}<p><small>Sign in with Google to keep your samples private.</small></p></div>`,
    );
    return;
  }
  if (step === 0) {
    frame(
      `<h1>Start with the music.</h1><p class="muted">Add the original and your track. We’ll fill in recognizable titles and artists, check both types of reuse, and show you the suggested moments.</p><div class="grid">${["original", "new"].map((role) => `<div><h2>${role === "original" ? "The original" : "Your track"}</h2><label>Audio file<input data-file="${role}" type="file" accept=".mp3,.wav,.flac,.m4a,.ogg"></label><small>Up to 100 MB · maximum 10 minutes</small>${field("Title", role + "_title")}${field("Artist", role + "_artist")}</div>`).join("")}</div><p class="warning">We check recording samples and separately replayed music. Checking both does not mean both happened—you can rule out either after listening.</p><div class="actions">${button("Find my sample →", "analyze", true)}</div><small>Up to 3 requests per person and 20 shared requests daily, including optional instrument checks.</small>`,
    );
    return;
  }
  if (step === 1) {
    frame(
      `<h1>Finding your sample.</h1><p><span class="spinner"></span></p><p id="jobStatus">Your tracks are queued. You can leave this page and come back.</p>`,
    );
    return;
  }
  if (!analysis) return;
  if (step === 2) {
    frame(
      `<h1>Listen & check.</h1><p class="muted">Accept the moments you hear, or unlock the table to correct them. Original-track times may be unavailable for fallback estimates.</p><p class="muted">Used the original audio without recording a separate replay? Confirm the recording sample, accept its times, and choose “No separate replay or re-sung part” below. You do not need timestamps for a use that did not happen.</p><div class="grid"><div><h3>The original</h3><audio controls id="originalPlayer"></audio></div><div><h3>Your track</h3><audio controls id="newPlayer"></audio></div></div>${(analysis.warnings || []).map((w) => `<p class="warning">${esc(w)}</p>`).join("")}<details><summary>See how the tracks compare</summary><div id="spectral"></div></details>${Object.keys(
        forms,
      )
        .map((r) => renderTimes(r))
        .join(
          "",
        )}<section id="instruments" aria-label="Instrument check">${renderInstruments()}</section>${nav("Next: Describe the sound →")}`,
    );
    loadAudio().catch((e) => notice(e.message));
    $("#spectral").parentElement.addEventListener("toggle", (e) => {
      if (e.target.open) showComparison().catch((e) => notice(e.message));
    });
    return;
  }
  if (step === 3) {
    frame(
      `<h1>What did you use?</h1><p class="muted">Method and repetition are suggested from the analysis. Check them, then describe the sound and its role.</p>${active()
        .map(
          (r) =>
            `<div class="track" data-rights="${r}"><h2>${name(r)}</h2>${field("What did you take?", "element", forms[r].element, "A bassline, vocal phrase or drum break")}${field("How did you use it?", "method", forms[r].method)}${field("Does it loop or repeat?", "repetition", forms[r].repetition)}${field("What does it do in your track?", "role", forms[r].role, "Main hook, rhythm bed, background texture…")}${field("Any reused lyrics? (optional)", "lyrics", forms[r].lyrics)}</div>`,
        )
        .join("")}${nav("Next: Place the sample →")}`,
    );
    return;
  }
  if (step === 4) {
    frame(
      `<h1>Where does it fit?</h1><p class="muted">Review the suggested placement. Timestamps alone cannot distinguish a chorus from a verse or bridge—choose the sections you hear.</p>${active()
        .map(
          (r) =>
            `<div class="track" data-rights="${r}"><h2>${name(r)}</h2><div class="checks">${["whole track", "intro", "verse", "chorus", "bridge", "outro"].map((s) => `<label><input type="checkbox" data-section="${s}" ${forms[r].sections.includes(s) ? "checked" : ""}>${s}</label>`).join("")}</div><label>Where does it appear overall?<select data-field="placement"><option value="">Choose placement</option>${Object.entries(
              placements,
            )
              .map(
                ([k, v]) =>
                  `<option value="${k}" ${forms[r].placement === k ? "selected" : ""}>${v}</option>`,
              )
              .join(
                "",
              )}</select></label>${!forms[r].times_confirmed ? renderTimes(r, true) : ""}<label><input type="checkbox" data-field="details_confirmed" ${forms[r].details_confirmed ? "checked" : ""}>I’ve listened and checked these details</label></div>`,
        )
        .join("")}${nav("Next: Review your draft →")}`,
    );
    return;
  }
  if (step === 5) {
    frame(
      `<h1>Make it yours.</h1><p class="muted">Read the draft, make any edits, then mark it as reviewed.</p><label>Edit your Nature of Use draft<textarea data-global="narrative" rows="9">${esc(narrative)}</textarea></label>${field("Your name / reviewer", "reviewer", reviewer)}<label>Anything still to check? (optional)<textarea data-global="notes">${esc(notes)}</textarea></label><div class="actions">${button("Save draft", "save")}${button("Mark document as reviewed", "approve", true)}</div>${approved ? "<p>Reviewed and ready to download.</p>" : ""}${nav("Next: Your Nature of Use →")}`,
    );
    return;
  }
  frame(
    `<h1>Your Nature of Use.</h1><p class="muted">A clear account of what you took and how you used it.</p><article class="document">${esc(narrative)}</article><div class="actions">${button("Download HTML", "html", true)}${button("Download text", "text")}</div><details><summary>Supporting analysis</summary>${button("Download analysis JSON", "json")}</details>${nav("Finish")}`,
  );
}
function renderInstruments() {
  const evidence = analysis?.stem_evidence || [];
  const eligible = analysis?.master?.locate?.sample_occurrences?.some(
    (i) => Number.isFinite(i.original_start) && Number.isFinite(i.original_end),
  );
  const method = analysis?.methods?.stems || "";
  const failure =
    instrumentError ||
    (method.startsWith("unavailable:")
      ? "The instrument check could not finish. You can continue using your timestamps or try again."
      : "");
  const header =
    '<h2>Check the instruments</h2><p class="muted">Optional · Compare bass, drums, vocals and other sounds in one short matched region. This does not check every timestamp.</p>';
  if (instrumentBusy)
    return `${header}<p role="status"><span class="spinner"></span> ${esc(instrumentMessage || "Starting the instrument check…")}</p><button disabled>Instrument check in progress</button>`;
  if (evidence.length) {
    const labels = {
      full_mix: "Full recording (reference)",
      bass: "Bass",
      drums: "Drums",
      vocals: "Vocals",
      other: "Other sounds",
    };
    return `${header}<p role="status">Instrument check complete. These are estimated stems; listen before confirming a sampled instrument.</p><div class="tableWrap"><table aria-label="Instrument comparison results"><thead><tr><th>Original</th><th>Your track</th><th>Result in this region</th></tr></thead><tbody>${evidence.map((x) => `<tr><td>${esc(labels[x.source_stem] || x.source_stem)}</td><td>${esc(labels[x.new_song_stem] || x.new_song_stem)}</td><td>${x.dtw_result === "accepted" ? "Possible supporting match" : x.dtw_result === "weak" ? "Uncertain alignment" : "No supporting match"}</td></tr>`).join("")}</tbody></table></div><p class="muted">Completed results are reused.</p>`;
  }
  return `${header}${failure ? `<p role="alert" class="warning">${esc(failure)}</p>` : ""}${method.startsWith("unavailable:") ? `<details><summary>Instrument check details</summary><pre>${esc(method)}</pre></details>` : ""}${instrumentMessage && !failure ? `<p role="status">${esc(instrumentMessage)}</p>` : ""}${eligible ? button(failure ? "Try instrument check again" : "Run instrument check", "stems") : '<p class="muted">This check needs a matched region with timestamps in both recordings. The current analysis has no paired region. You can still continue to your document.</p><button disabled>Instrument check unavailable</button>'}`;
}
function updateInstruments() {
  if ($("#instruments")) $("#instruments").innerHTML = renderInstruments();
}
async function startInstrumentCheck() {
  if (instrumentBusy) return;
  const target = caseId;
  const serial = ++polling;
  instrumentBusy = true;
  instrumentError = "";
  instrumentMessage = "Starting the instrument check…";
  updateInstruments();
  try {
    await json(`/api/analyses/${target}/stems`, { method: "POST" });
    if (serial !== polling || target !== caseId) return;
    await poll({ instruments: true });
  } catch (error) {
    if (serial !== polling || target !== caseId) return;
    instrumentBusy = false;
    instrumentError = error.message;
    updateInstruments();
  }
}
function active() {
  return Object.keys(forms).filter((r) => forms[r].status !== "no_use");
}
function name(r) {
  return r === "master"
    ? "Your recording sample"
    : "Your replayed melody / lyrics";
}
function renderTimes(r, nested = false) {
  const f = forms[r];
  return `<div class="track" data-rights="${r}">${nested ? "" : `<h2>${name(r)}</h2>`}<label>${r === "publishing" ? "Did you separately replay a melody or re-sing lyrics?" : "Have you checked this recording sample?"}<select data-field="status"><option value="pending" ${f.status === "pending" ? "selected" : ""}>I’m not sure yet</option><option value="confirmed" ${f.status === "confirmed" ? "selected" : ""}>${r === "publishing" ? "Yes, I replayed or re-sang a part" : "Yes, I used the original recording"}</option><option value="no_use" ${f.status === "no_use" ? "selected" : ""}>${r === "publishing" ? "No separate replay or re-sung part" : "No recording sample"}</option></select></label>${f.status === "no_use" ? '<p class="muted">Nothing else is needed for this check.</p>' : `<label>Suggested times<select data-times="${r}"><option value="pending" ${!f.times_confirmed && !f.edit ? "selected" : ""}>I haven’t checked these yet</option>${f.intervals.length ? `<option value="accept" ${f.times_confirmed && !f.edit ? "selected" : ""}>Yes, use these times</option>` : ""}<option value="edit" ${f.edit ? "selected" : ""}>${f.intervals.length ? "No, let me edit" : "Add times now"}</option></select></label><div class="tableWrap"><table><thead><tr><th>Your track starts (s)</th><th>Ends (s)</th><th>Original starts (s)</th><th>Ends (s)</th>${f.edit ? "<th></th>" : ""}</tr></thead><tbody>${f.intervals.map((i, n) => `<tr>${["new_start", "new_end", "original_start", "original_end"].map((k) => `<td>${f.edit ? `<input type="number" min="0" step=".01" data-interval="${n}:${k}" value="${i[k] ?? ""}" aria-label="${k}">` : esc(i[k] ?? "Not located")}</td>`).join("")}${f.edit ? `<td><button data-remove="${n}">×</button></td>` : ""}</tr>`).join("")}</tbody></table></div>${f.edit ? `${button("Add appearance", "add")}<label><input type="checkbox" data-field="times_confirmed" ${f.times_confirmed ? "checked" : ""}>I’ve listened and confirmed these times</label>` : ""}`}</div>`;
}
async function loadAudio() {
  for (const role of ["original", "new"]) {
    if (!audioUrls[role]) {
      const blob =
        localFiles[role] ||
        (await (await api(`/api/analyses/${caseId}/audio/${role}`)).blob());
      audioUrls[role] = URL.createObjectURL(blob);
    }
    const el = $(`#${role}Player`);
    if (el) el.src = audioUrls[role];
  }
}
async function showComparison() {
  if (!comparison)
    comparison = await json(`/api/analyses/${caseId}/comparison`);
  if (!window.Plotly) {
    plotPromise ??= new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://cdn.plot.ly/plotly-3.1.0.min.js";
      script.onload = resolve;
      script.onerror = () =>
        reject(Error("The visual comparison could not load."));
      document.head.append(script);
    });
    await plotPromise;
  }
  await window.Plotly.newPlot("spectral", comparison.data, comparison.layout, {
    responsive: true,
    displaylogo: false,
  });
}
async function analyze() {
  const credits = {};
  for (const r of ["original", "new"]) {
    const f = localFiles[r];
    if (!f || f.size > 100 * 1024 * 1024)
      throw Error("Choose two audio files under 100 MB each.");
    for (const k of ["title", "artist"]) {
      credits[r + "_" + k] = $(`[data-field="${r}_${k}"]`).value.trim();
      if (!credits[r + "_" + k])
        throw Error("Add a title and artist for both tracks.");
    }
  }
  const uploads = Object.fromEntries(
    Object.entries(localFiles).map(([r, f]) => [
      r,
      {
        name: f.name,
        size: f.size,
        content_type: f.type || "application/octet-stream",
      },
    ]),
  );
  step = 1;
  render();
  try {
    const reserved = await json("/api/analyses", {
      method: "POST",
      body: JSON.stringify({ ...uploads, credits }),
    });
    caseId = reserved.id;
    localStorage.setItem(`lastrada:${user.uid}`, caseId);
    await Promise.all(
      ["original", "new"].map(async (r) => {
        const response = await fetch(reserved.uploads[r], {
          method: "PUT",
          headers: { "Content-Type": uploads[r].content_type },
          body: localFiles[r],
        });
        if (!response.ok)
          throw Error("An audio upload failed. Please start a new sample.");
      }),
    );
    await json(`/api/analyses/${caseId}/run`, { method: "POST" });
    await poll();
  } catch (e) {
    step = 0;
    render();
    throw e;
  }
}
async function poll({ instruments = false } = {}) {
  const serial = ++polling;
  let errors = 0;
  while (serial === polling && user) {
    try {
      const state = await json(`/api/analyses/${caseId}`);
      if (serial !== polling) return;
      if (state.status === "completed") {
        if (
          !(await loadResult({
            preserveReview: instruments,
            expectedPoll: serial,
          }))
        )
          return;
        if (serial !== polling) return;
        if (instruments || state.operation === "stems") {
          instrumentBusy = false;
          instrumentError = state.error || "";
          instrumentMessage = analysis.stem_evidence?.length
            ? ""
            : "No instrument comparison results were returned. You can continue to your document.";
          if (instruments) updateInstruments();
          else {
            step = 2;
            render();
          }
        } else {
          step = 2;
          render();
        }
        return;
      }
      if (state.status === "failed")
        throw Object.assign(Error(state.error || "Analysis did not finish."), {
          terminal: true,
        });
      if (instruments) {
        instrumentMessage =
          state.status === "running"
            ? "Comparing the instruments. The first check may take a few minutes while the model starts."
            : "Instrument check queued. Waiting for the analysis worker.";
        updateInstruments();
      }
      if ($("#jobStatus"))
        $("#jobStatus").textContent =
          state.operation === "stems"
            ? "Your instrument check is in progress. Model startup can take a few minutes."
            : state.status === "running"
              ? "Your tracks are being analyzed. Model startup can take a few minutes."
              : "Your sample is queued. Only one heavy analysis runs at a time.";
      errors = 0;
    } catch (e) {
      if (e.terminal || ++errors >= 5) {
        if (instruments) {
          instrumentBusy = false;
          instrumentError = e.terminal
            ? e.message
            : "We lost contact with the instrument check. Reload this page to reconnect; the job may still be running.";
          updateInstruments();
        } else notice(e.message);
        return;
      }
    }
    await new Promise((r) => setTimeout(r, document.hidden ? 15000 : 4000));
  }
}
async function loadResult({
  preserveReview = false,
  expectedPoll = polling,
} = {}) {
  const target = caseId;
  const data = await json(`/api/analyses/${target}/result`);
  if (expectedPoll !== polling || target !== caseId) return false;
  analysis = data.analysis;
  const corrected = analysis.review.corrected;
  if (!Object.keys(forms).length) {
    for (const r of analysis.input.analysis_scope) {
      const path = corrected?.[r];
      const suggestion = data.suggestions[r];
      const values = suggestion.placement.values;
      forms[r] = {
        status: path
          ? path.locate.detection_status === "not_detected"
            ? "no_use"
            : path.locate.detection_status === "verified"
              ? "confirmed"
              : "pending"
          : "pending",
        intervals: path ? path.locate.sample_occurrences : suggestion.intervals,
        times_confirmed: !!path && path.locate.detection_status === "verified",
        details_confirmed: !!path && !path.locate.review_required,
        element:
          path?.describe.elements.find((x) => x.feature === "musical_element")
            ?.value || "",
        lyrics:
          path?.describe.elements.find((x) => x.feature === "lyrics")?.value ||
          "",
        method:
          path?.describe.reuse_type ||
          (suggestion.intervals.length
            ? r === "master"
              ? "Sampled the original recording"
              : "Replayed or re-sang the original music"
            : ""),
        repetition: path?.describe.repetition || values.repetition || "",
        role: path?.describe.role_in_new_song || "",
        sections: path?.describe.sections || values.sections || [],
        placement: path?.classification.placement || values.placement || null,
        edit: false,
      };
    }
  }
  if (corrected && !preserveReview) {
    narrative = corrected.nature_of_use.text;
    reviewer = analysis.review.reviewer || user.displayName || "";
    notes = analysis.review.notes || "";
    approved = analysis.review.status === "approved";
  }
  return true;
}
function validTimes(f) {
  return (
    f.times_confirmed &&
    f.intervals.length &&
    f.intervals.every(
      (i) =>
        Number.isFinite(i.new_start) &&
        Number.isFinite(i.new_end) &&
        i.new_start >= 0 &&
        i.new_end > i.new_start &&
        i.new_end <= analysis.durations.new &&
        ((i.original_start == null && i.original_end == null) ||
          (Number.isFinite(i.original_start) &&
            Number.isFinite(i.original_end) &&
            i.original_start >= 0 &&
            i.original_end > i.original_start &&
            i.original_end <= analysis.durations.original)),
    )
  );
}
function gate() {
  if (step === 2) {
    const pending = Object.keys(forms).filter(
      (r) => forms[r].status === "pending",
    );
    if (pending.length)
      throw Error(
        pending
          .map((r) =>
            r === "publishing"
              ? "Replayed music: choose Yes only if you separately replayed or re-sang a part; otherwise choose No separate replay or re-sung part."
              : "Recording sample: confirm whether you used audio from the original recording.",
          )
          .join(" "),
      );
    if (!active().length)
      throw Error(
        "No sample use is selected. Confirm at least one use to create a Nature of Use document, or start a new sample.",
      );
    const unchecked = active().filter((r) => !validTimes(forms[r]));
    if (unchecked.length)
      throw Error(
        unchecked
          .map(
            (r) =>
              `${name(r)}: accept the suggested times, or edit and confirm valid times before continuing.`,
          )
          .join(" "),
      );
  }
  if (
    step === 3 &&
    active().some((r) =>
      ["element", "method", "repetition", "role"].some(
        (k) => !forms[r][k].trim(),
      ),
    )
  )
    throw Error(
      "Describe the sound, method, repetition and role for each applicable use.",
    );
  if (
    step === 4 &&
    active().some(
      (r) =>
        !validTimes(forms[r]) ||
        !forms[r].sections.length ||
        !forms[r].placement ||
        !forms[r].details_confirmed,
    )
  )
    throw Error(
      "Confirm the times, song sections, placement and listening details before reviewing.",
    );
  if (step === 5 && !approved)
    throw Error("Mark the document as reviewed before downloading.");
}
async function save(approve = false) {
  const payload = {
    paths: Object.fromEntries(
      Object.entries(forms).map(([r, f]) => [
        r,
        Object.fromEntries(
          [
            "status",
            "intervals",
            "times_confirmed",
            "details_confirmed",
            "element",
            "lyrics",
            "method",
            "repetition",
            "role",
            "sections",
            "placement",
          ].map((k) => [
            k,
            k === "intervals"
              ? f.intervals.map((i) => ({
                  new_start: i.new_start,
                  new_end: i.new_end,
                  original_start: i.original_start ?? null,
                  original_end: i.original_end ?? null,
                  source: "creator_review",
                }))
              : f[k],
          ]),
        ),
      ]),
    ),
    narrative: narrative === generated ? "" : narrative,
    reviewer,
    notes,
    approve,
  };
  const value = await json(`/api/analyses/${caseId}/review`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  analysis = value.analysis;
  narrative = analysis.review.corrected.nature_of_use.text;
  if (!payload.narrative) generated = narrative;
  approved = analysis.review.status === "approved";
}
async function download(kind) {
  const blob = await (
    await api(`/api/analyses/${caseId}/export/${kind}`)
  ).blob();
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download =
    kind === "json"
      ? "supporting-analysis.json"
      : `nature-of-use.${kind === "text" ? "txt" : kind}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("#view").addEventListener("input", (e) => {
  const el = e.target,
    r = el.closest("[data-rights]")?.dataset.rights;
  if (el.dataset.global) {
    if (el.dataset.global === "narrative") narrative = el.value;
    else notes = el.value;
    approved = false;
  }
  if (el.dataset.field === "reviewer") {
    reviewer = el.value;
    approved = false;
  } else if (r && el.dataset.field) {
    forms[r][el.dataset.field] = el.type === "checkbox" ? el.checked : el.value;
    approved = false;
  }
  if (r && el.dataset.interval) {
    const [n, k] = el.dataset.interval.split(":");
    forms[r].intervals[n][k] = el.value === "" ? null : Number(el.value);
    forms[r].times_confirmed = false;
    forms[r].details_confirmed = false;
    approved = false;
  }
});
$("#view").addEventListener("change", (e) => {
  const el = e.target,
    r = el.closest("[data-rights]")?.dataset.rights;
  if (el.dataset.file) {
    const f = el.files[0];
    if (f) {
      localFiles[el.dataset.file] = f;
      const credits = creditsFrom(f.name);
      for (const k of ["title", "artist"]) {
        const input = $(`[data-field="${el.dataset.file}_${k}"]`);
        if (!input.value.trim()) input.value = credits[k] || "";
      }
    }
  }
  if (r && el.dataset.field === "status") {
    forms[r].status = el.value;
    forms[r].details_confirmed = el.value === "no_use";
    render();
  }
  if (el.dataset.times) {
    const f = forms[el.dataset.times];
    f.edit = el.value === "edit";
    f.times_confirmed = el.value === "accept";
    if (f.times_confirmed) f.status = "confirmed";
    render();
  }
  if (r && el.dataset.section) {
    forms[r].sections = [
      ...el.closest(".checks").querySelectorAll("input:checked"),
    ].map((x) => x.dataset.section);
    if (el.dataset.section === "whole track" && el.checked)
      forms[r].sections = ["whole track"];
    else if (el.dataset.section !== "whole track" && el.checked)
      forms[r].sections = forms[r].sections.filter((x) => x !== "whole track");
    const joined = forms[r].sections.sort().join(",");
    forms[r].placement =
      {
        chorus: "chorus_only",
        verse: "verses",
        bridge: "bridge_only",
        intro: "intro_only",
        outro: "outro_only",
        "whole track": "throughout",
        "intro,outro": "intro_outro_without_chorus",
        "chorus,intro,outro": "intro_outro_with_chorus",
      }[joined] || (forms[r].sections.length ? "selected_sections" : null);
    forms[r].details_confirmed = false;
    render();
  }
});
$("#view").addEventListener("click", async (e) => {
  const el = e.target.closest("button");
  if (!el) return;
  const r = el.closest("[data-rights]")?.dataset.rights;
  if (el.dataset.remove && r) {
    forms[r].intervals.splice(Number(el.dataset.remove), 1);
    forms[r].times_confirmed = false;
    render();
    return;
  }
  try {
    notice("");
    const action = el.dataset.action;
    if (action === "start") {
      if (user) {
        step = 0;
        render();
      } else await signInWithPopup(auth, new GoogleAuthProvider());
    } else if (action === "new") reset();
    else if (action === "analyze") await analyze();
    else if (action === "back") {
      step--;
      render();
    } else if (action === "next") {
      gate();
      if (step === 4) await save();
      if (step === 6) {
        reset();
        return;
      }
      step++;
      render();
    } else if (action === "add" && r) {
      forms[r].intervals.push({
        new_start: null,
        new_end: null,
        original_start: null,
        original_end: null,
      });
      forms[r].times_confirmed = false;
      render();
    } else if (action === "save" || action === "approve") {
      await save(action === "approve");
      render();
      notice(
        action === "approve"
          ? "Reviewed and ready to download."
          : "Draft saved.",
      );
    } else if (action === "stems") {
      await startInstrumentCheck();
    } else if (["html", "text", "json"].includes(action))
      await download(action);
  } catch (error) {
    notice(error.message);
  }
});
$("#newSample").onclick = reset;
$("#theme").onclick = () => {
  document.body.classList.toggle("light");
  $("#theme").textContent = document.body.classList.contains("light")
    ? "Dark mode"
    : "Light mode";
};
$("#account").onclick = async () => {
  try {
    if (user) await signOut(auth);
    else await signInWithPopup(auth, new GoogleAuthProvider());
  } catch (e) {
    notice(
      "Sign-in is unavailable. Please try again or contact the workspace owner.",
    );
  }
};
try {
  const response = await fetch("/config.json", { cache: "no-store" });
  if (!response.ok) throw Error();
  config = await response.json();
  if (!config.firebase?.projectId || !config.apiBase?.startsWith("https://"))
    throw Error();
  auth = getAuth(initializeApp(config.firebase));
  onAuthStateChanged(auth, async (value) => {
    user = value;
    const saved = user ? localStorage.getItem(`lastrada:${user.uid}`) : null;
    $("#account").textContent = user ? "Sign out" : "Sign in";
    reset();
    if (saved && user) {
      caseId = saved;
      localStorage.setItem(`lastrada:${user.uid}`, saved);
      step = 1;
      render();
      await poll();
    }
  });
} catch {
  step = -1;
  render();
  notice(
    "This workspace is being set up. Please contact the owner before uploading tracks.",
  );
  $("#account").disabled = true;
  $("#view button").disabled = true;
}
