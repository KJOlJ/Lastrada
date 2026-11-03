import { groupIntervals } from "./grouped-timestamps.js";

let latestInstrumentRows = [];
let scheduled = false;

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
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

function titleCase(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function closeEnough(left, right, tolerance = 0.000001) {
  if (left == null && right == null) return true;
  return Number.isFinite(left) && Number.isFinite(right)
    ? Math.abs(left - right) <= tolerance
    : false;
}

function sameInterval(left, right) {
  if (!left || !right) return false;
  return ["new_start", "new_end", "original_start", "original_end"].every(
    (key) => closeEnough(left[key], right[key]),
  );
}

function rowsForRelationship(family, rows) {
  return rows.filter((row) =>
    family.rawCandidates.some((candidate) =>
      sameInterval(row.interval, candidate),
    ),
  );
}

function resultRank(result) {
  return { accepted: 3, weak: 2, rejected: 1 }[result] || 0;
}

function normalizedStem(label) {
  return String(label || "other")
    .toLowerCase()
    .replace(/\s+/g, "_");
}

function evidenceForRow(row) {
  // A label without the stored comparison is not accepted alignment evidence.
  if (row.context_only) return [];
  return Array.isArray(row.evidence) ? row.evidence.filter(e => e.scope !== "context") : [];
}

function presenceHtml(rows) {
  const checked = rows.filter(row => row.status === "checked");
  if (!checked.some(row => row.source_sounds?.length || row.new_sounds?.length)) return "";
  const sounds = values => values?.length
    ? values.map(value => `${esc(value.instrument)} (${Number(value.start).toFixed(2)}–${Number(value.end).toFixed(2)} s${value.scope === "context" ? ", surrounding context" : ""})`).join(", ")
    : "No clear estimate";
  return `<details class="instrumentPresence"><summary>Sounds at each timestamp</summary>
    <p>Estimated sounds present in each recording; this does not establish which sounds were sampled. Identical source intervals share one estimate; the new mix can differ. “Other” remains unidentified.</p>
    ${checked.map(row => `<div><strong>New ${Number(row.interval.new_start).toFixed(2)}–${Number(row.interval.new_end).toFixed(2)} s · Original ${Number(row.interval.original_start).toFixed(2)}–${Number(row.interval.original_end).toFixed(2)} s</strong><br>
      Original: ${sounds(row.source_sounds)}<br>New mix: ${sounds(row.new_sounds)}
      ${row.context_only ? "<small>Alignment was checked in surrounding context only.</small>" : ""}</div>`).join("")}
  </details>`;
}

export function summarizeRelationshipEvidence(family, rows = []) {
  const matchedRows = rowsForRelationship(family, rows);
  const checkedRows = matchedRows.filter((row) => row.status === "checked");
  const pending = matchedRows.filter((row) => row.status === "pending").length;
  const failed = matchedRows.filter((row) => row.status === "failed").length;
  const tooShort = matchedRows.filter((row) => row.status === "too_short").length;
  const noSource = matchedRows.filter((row) => row.status === "no_source").length;
  const pairs = new Map();

  checkedRows.forEach((row, rowIndex) => {
    for (const evidence of evidenceForRow(row)) {
      const sourceStem = normalizedStem(evidence.source_stem);
      const newStem = normalizedStem(evidence.new_song_stem);
      const key = `${sourceStem}|${newStem}`;
      const current = pairs.get(key) || {
        sourceStem,
        newStem,
        result: "rejected",
        ratios: [],
        moments: new Set(),
        checkedMoments: new Set(),
        interpretation: "",
      };
      if (resultRank(evidence.dtw_result) > resultRank(current.result)) {
        current.result = evidence.dtw_result;
        current.interpretation = evidence.interpretation || evidence.reason || "";
      }
      current.checkedMoments.add(row.occurrence_id || `${rowIndex}`);
      if (evidence.dtw_result === "accepted") {
        if (Number.isFinite(evidence.duration_ratio)) current.ratios.push(evidence.duration_ratio);
        current.moments.add(row.occurrence_id || `${rowIndex}`);
      }
      pairs.set(key, current);
    }
  });

  const entries = [...pairs.values()]
    .map((entry) => ({
      sourceStem: entry.sourceStem,
      newStem: entry.newStem,
      result: entry.result,
      durationRatio: median(entry.ratios),
      momentCount: entry.moments.size,
      checkedMomentCount: entry.checkedMoments.size,
      interpretation: entry.interpretation,
    }))
    .sort(
      (left, right) =>
        resultRank(right.result) - resultRank(left.result) ||
        Number(right.sourceStem === right.newStem) -
          Number(left.sourceStem === left.newStem) ||
        left.sourceStem.localeCompare(right.sourceStem),
    );

  return {
    matchedCount: matchedRows.length,
    checkedCount: checkedRows.length,
    pending,
    failed,
    tooShort,
    noSource,
    entries,
  };
}

function evidenceEntryHtml(entry) {
  const ratio = Number.isFinite(entry.durationRatio)
    ? `${entry.durationRatio.toFixed(2)}× duration`
    : "";
  const moments = `${entry.momentCount} of ${entry.checkedMomentCount} checked moments support this comparison`;
  const detail = [ratio, moments].filter(Boolean).join(" · ");
  return `<div class="stemEvidenceItem">
    <div><strong>${esc(titleCase(entry.sourceStem))} → ${esc(titleCase(entry.newStem))}</strong><span class="dtwResult ${esc(entry.result)}">${esc(titleCase(entry.result))}</span></div>
    ${detail ? `<small>${esc(detail)}</small>` : ""}
  </div>`;
}

function evidenceHtml(family) {
  const summary = summarizeRelationshipEvidence(family, latestInstrumentRows);
  const assessable = Math.max(
    0,
    summary.matchedCount - summary.tooShort - summary.noSource,
  );
  let body;
  if (!summary.matchedCount) {
    body = '<span class="evidenceState">Not checked</span><small>No matching stem result is stored for this relationship.</small>';
  } else if (!summary.checkedCount && summary.tooShort === summary.matchedCount) {
    body = '<span class="evidenceState">Too short to assess</span><small>This older result skipped short clips. Rerun instrument checks to estimate sounds using surrounding context.</small>';
  } else if (!summary.checkedCount && summary.failed) {
    body = '<span class="evidenceState">Check failed</span><small>Retry the stem + DTW check above.</small>';
  } else if (!summary.checkedCount) {
    body = '<span class="evidenceState">Not checked</span><small>Run the stem + DTW check above.</small>';
  } else if (!summary.entries.length) {
    body = '<span class="evidenceState">No reliable stem alignment</span>';
  } else {
    const visible = summary.entries.slice(0, 4);
    const remaining = summary.entries.slice(4);
    body = `<div class="stemEvidenceList">${visible.map(evidenceEntryHtml).join("")}</div>`;
    if (remaining.length)
      body += `<details class="moreStemEvidence"><summary>View ${remaining.length} more stem result${remaining.length === 1 ? "" : "s"}</summary><div class="stemEvidenceList">${remaining.map(evidenceEntryHtml).join("")}</div></details>`;
  }
  const progress = assessable
    ? `${summary.checkedCount} of ${assessable} eligible moments checked`
    : `${summary.checkedCount} moments checked`;
  const exclusions = [
    summary.tooShort ? `${summary.tooShort} too short` : "",
    summary.noSource ? `${summary.noSource} missing original time` : "",
    summary.pending ? `${summary.pending} pending` : "",
  ].filter(Boolean);
  return `${body}${presenceHtml(rowsForRelationship(family, latestInstrumentRows))}<small class="evidenceProgress">${esc(progress)}${exclusions.length ? ` · ${esc(exclusions.join(" · "))}` : ""}</small>`;
}

function readNumber(cell) {
  const input = cell?.querySelector('input[type="number"]');
  const raw = input ? input.value : cell?.textContent?.trim();
  if (!raw || /not located/i.test(raw)) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function rowsFromRawTable(table) {
  return [...(table?.tBodies?.[0]?.rows || [])]
    .map((row, rowIndex) => {
      const cells = [...row.cells];
      return {
        rowIndex,
        new_start: readNumber(cells[0]),
        new_end: readNumber(cells[1]),
        original_start: readNumber(cells[2]),
        original_end: readNumber(cells[3]),
      };
    })
    .filter(
      (item) =>
        Number.isFinite(item.new_start) &&
        Number.isFinite(item.new_end) &&
        item.new_end > item.new_start,
    );
}

function relationshipFamilies(track) {
  const rawTable = track.querySelector(".exactTimestamps table");
  if (!rawTable) return [];
  const rows = rowsFromRawTable(rawTable);
  if (!rows.length) return [];
  const durationFromAudio = document.querySelector("#newPlayer")?.duration;
  const fallbackDuration = Math.max(...rows.map((item) => item.new_end));
  return groupIntervals(
    rows,
    Number.isFinite(durationFromAudio) ? durationFromAudio : fallbackDuration,
  );
}

function enrichRelationshipTable(track) {
  const summary = track.querySelector(".groupedUseSummary");
  const table = summary?.querySelector(".groupedUseTable table");
  if (!summary || !table) return;
  const families = relationshipFamilies(track);
  if (!families.length) return;

  table.setAttribute(
    "aria-label",
    "Sample relationships with Demucs stem and DTW evidence",
  );
  const header = table.tHead?.rows?.[0];
  if (header && !header.querySelector("[data-stem-dtw-heading]")) {
    const heading = document.createElement("th");
    heading.dataset.stemDtwHeading = "true";
    heading.textContent = "Demucs stem + DTW";
    header.append(heading);
  }

  [...(table.tBodies?.[0]?.rows || [])].forEach((row, index) => {
    let cell = row.querySelector("[data-stem-dtw-evidence]");
    if (!cell) {
      cell = document.createElement("td");
      cell.dataset.stemDtwEvidence = "true";
      cell.className = "relationshipEvidenceCell";
      row.append(cell);
    }
    const nextHtml = families[index]
      ? evidenceHtml(families[index])
      : '<span class="evidenceState">Unavailable</span>';
    if (cell.__lastradaEvidenceHtml !== nextHtml) {
      cell.__lastradaEvidenceHtml = nextHtml;
      cell.innerHTML = nextHtml;
    }
  });

  const controls = document.querySelector("#instruments");
  const tableWrap = summary.querySelector(".groupedUseTable");
  if (controls && tableWrap) {
    controls.classList.add("relationshipEvidenceControls");
    if (controls.parentElement !== summary) summary.insertBefore(controls, tableWrap);
    const heading = controls.querySelector("h2");
    if (!controls.classList.contains("automaticInstrumentControls") && heading && heading.textContent !== "Stem + DTW evidence")
      heading.textContent = "Stem + DTW evidence";
    const description = controls.querySelector("p.muted");
    const descriptionText =
      "Compare supporting alignments and estimated sounds at each timestamp below. Short clips use surrounding context; an instrument present in both mixes is not proof of sampling.";
    if (!controls.classList.contains("automaticInstrumentControls") && description && description.textContent !== descriptionText)
      description.textContent = descriptionText;
  }
}

function enhanceAllEvidence() {
  document
    .querySelectorAll('.track[data-rights="master"]')
    .forEach((track) => enrichRelationshipTable(track));
}

function scheduleEvidenceRefresh() {
  if (scheduled || typeof window === "undefined") return;
  scheduled = true;
  window.requestAnimationFrame(() => {
    scheduled = false;
    enhanceAllEvidence();
  });
}

function captureResultPayload(payload) {
  latestInstrumentRows = Array.isArray(payload?.instrument_rows)
    ? payload.instrument_rows
    : Array.isArray(payload?.analysis?.instrument_occurrences)
      ? payload.analysis.instrument_occurrences
      : [];
  scheduleEvidenceRefresh();
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...arguments_) => {
    const response = await nativeFetch(...arguments_);
    try {
      const request = arguments_[0];
      const url =
        typeof request === "string"
          ? request
          : request instanceof URL
            ? request.href
            : request?.url || "";
      if (
        response.ok &&
        /\/api\/analyses\/[^/]+\/result(?:\?|$)/.test(String(url))
      )
        response
          .clone()
          .json()
          .then(captureResultPayload)
          .catch(() => {});
    } catch {}
    return response;
  };

  const view = document.querySelector("#view");
  if (view)
    new MutationObserver(scheduleEvidenceRefresh).observe(view, {
      childList: true,
      subtree: true,
    });
  window.addEventListener("load", scheduleEvidenceRefresh);
  scheduleEvidenceRefresh();
}
