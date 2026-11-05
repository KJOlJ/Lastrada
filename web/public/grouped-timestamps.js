const EPSILON = 1e-9;

function duration(start, end) {
  return Math.max(0, Number(end) - Number(start));
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function overlapRatio(aStart, aEnd, bStart, bEnd) {
  const overlap = Math.max(0, Math.min(aEnd, bEnd) - Math.max(aStart, bStart));
  const denominator = Math.max(
    EPSILON,
    Math.min(duration(aStart, aEnd), duration(bStart, bEnd)),
  );
  return overlap / denominator;
}

function representativeSource(intervals) {
  const starts = intervals
    .map((item) => item.original_start)
    .filter(Number.isFinite);
  const ends = intervals
    .map((item) => item.original_end)
    .filter(Number.isFinite);
  if (!starts.length || !ends.length) return [null, null];
  return [median(starts), median(ends)];
}

function sourceFamilyScore(interval, family) {
  const [sourceStart, sourceEnd] = representativeSource(family);
  const sourceKnown =
    Number.isFinite(interval.original_start) &&
    Number.isFinite(interval.original_end);
  if (!sourceKnown) return sourceStart == null ? 1 : -1;
  if (sourceStart == null || sourceEnd == null) return -1;

  const overlap = overlapRatio(
    interval.original_start,
    interval.original_end,
    sourceStart,
    sourceEnd,
  );
  if (overlap >= 0.35) return 2 + overlap;

  const center = (interval.original_start + interval.original_end) / 2;
  const familyCenter = (sourceStart + sourceEnd) / 2;
  const tolerance = Math.max(
    2,
    0.25 *
      Math.max(
        duration(interval.original_start, interval.original_end),
        duration(sourceStart, sourceEnd),
      ),
  );
  const distance = Math.abs(center - familyCenter);
  return distance <= tolerance ? 1 - distance / Math.max(tolerance, EPSILON) : -1;
}

function sameNewOccurrence(a, b) {
  const overlap = overlapRatio(a.new_start, a.new_end, b.new_start, b.new_end);
  if (overlap >= 0.5) return true;

  const aCenter = (a.new_start + a.new_end) / 2;
  const bCenter = (b.new_start + b.new_end) / 2;
  const aDuration = duration(a.new_start, a.new_end);
  const bDuration = duration(b.new_start, b.new_end);
  const durationRatio =
    Math.max(aDuration, bDuration) /
    Math.max(EPSILON, Math.min(aDuration, bDuration));
  return Math.abs(aCenter - bCenter) <= 0.75 && durationRatio <= 2;
}

function collapseNewOccurrences(intervals) {
  const clusters = [];
  for (const interval of [...intervals].sort(
    (a, b) => a.new_start - b.new_start || a.new_end - b.new_end,
  )) {
    const match = clusters.find((cluster) =>
      cluster.some((old) => sameNewOccurrence(interval, old)),
    );
    if (match) match.push(interval);
    else clusters.push([interval]);
  }

  return clusters
    .map((cluster) => {
      const representative = [...cluster].sort(
        (a, b) =>
          (b.similarity ?? -2) - (a.similarity ?? -2) ||
          duration(b.new_start, b.new_end) - duration(a.new_start, a.new_end),
      )[0];
      return {
        ...representative,
        ending_uncertain: cluster.some(item => Boolean(item.ending_note || item.ending_uncertain)),
      };
    })
    .sort((a, b) => a.new_start - b.new_start || a.new_end - b.new_end);
}

function mergedCoverage(intervals) {
  if (!intervals.length) return 0;
  const ranges = intervals
    .map((item) => [item.new_start, item.new_end])
    .sort((a, b) => a[0] - b[0]);
  let [currentStart, currentEnd] = ranges[0];
  let total = 0;
  for (const [start, end] of ranges.slice(1)) {
    if (start <= currentEnd) currentEnd = Math.max(currentEnd, end);
    else {
      total += currentEnd - currentStart;
      currentStart = start;
      currentEnd = end;
    }
  }
  return total + currentEnd - currentStart;
}

function spacing(intervals) {
  if (intervals.length < 2) return [null, false];
  const starts = intervals.map((item) => item.new_start);
  const gaps = starts.slice(1).map((right, index) => right - starts[index]);
  const typical = median(gaps);
  if (gaps.length < 2) return [typical, false];
  const deviations = gaps.map((gap) => Math.abs(gap - typical));
  return [typical, median(deviations) <= Math.max(0.75, 0.2 * typical)];
}

function detailedPattern(
  occurrences,
  candidateCount,
  newDuration,
  regularSpacing,
  sourceKnown,
) {
  const count = occurrences.length;
  if (!sourceKnown)
    return candidateCount >= 3
      ? "Unresolved repeated candidates"
      : "Unresolved candidate";

  const span = count
    ? occurrences[occurrences.length - 1].new_end - occurrences[0].new_start
    : 0;
  const spread =
    Number.isFinite(newDuration) && newDuration > 0 ? span / newDuration : 0;
  if (count >= 3 && spread >= 0.65) return "Repeated across most of the track";
  if (count >= 3 && regularSpacing) return "Regular repeated use";
  if (count >= 2) return "Repeated use";
  if (candidateCount >= 3) return "One continuous or overlapping use";
  return "One-off use";
}

function sourcePassage(start, end) {
  return Number.isFinite(start) && Number.isFinite(end)
    ? { start: Number(start), end: Number(end) }
    : null;
}

function sourcePassagesFromFamily(family) {
  const [start, end] = representativeSource(family);
  const passage = sourcePassage(start, end);
  return passage ? [passage] : [];
}

function dedupeSourcePassages(passages) {
  const result = [];
  for (const passage of passages) {
    const duplicate = result.find(
      (existing) =>
        overlapRatio(
          passage.start,
          passage.end,
          existing.start,
          existing.end,
        ) >= 0.5,
    );
    if (!duplicate) result.push({ ...passage });
  }
  return result.sort((a, b) => a.start - b.start || a.end - b.end);
}

function occurrenceMatchCount(left, right) {
  const used = new Set();
  let matches = 0;
  for (const item of left) {
    const index = right.findIndex(
      (candidate, candidateIndex) =>
        !used.has(candidateIndex) && sameNewOccurrence(item, candidate),
    );
    if (index >= 0) {
      used.add(index);
      matches += 1;
    }
  }
  return matches;
}

function sameDerivativeRelationship(left, right) {
  if (!left.occurrences.length || !right.occurrences.length) return false;
  const leftHasSource = left.sourcePassages.length > 0;
  const rightHasSource = right.sourcePassages.length > 0;
  if (leftHasSource !== rightHasSource) return false;
  const matches = occurrenceMatchCount(left.occurrences, right.occurrences);
  const smaller = Math.min(left.occurrences.length, right.occurrences.length);
  const larger = Math.max(left.occurrences.length, right.occurrences.length);
  return matches / smaller >= 0.75 && matches / larger >= 0.6;
}

function finalizeRelationship(relationship, newDuration) {
  const occurrences = collapseNewOccurrences(relationship.rawCandidates);
  const [typicalSpacing, regularSpacing] = spacing(occurrences);
  const sourcePassages = dedupeSourcePassages(relationship.sourcePassages);
  return {
    ...relationship,
    sourcePassages,
    sourceStart: sourcePassages[0]?.start ?? null,
    sourceEnd: sourcePassages[0]?.end ?? null,
    candidateCount: relationship.rawCandidates.length,
    occurrenceCount: occurrences.length,
    firstUse: occurrences[0]?.new_start ?? null,
    lastUse: occurrences[occurrences.length - 1]?.new_end ?? null,
    coverageSeconds: mergedCoverage(occurrences),
    typicalSpacingSeconds: typicalSpacing,
    regularSpacing,
    useType: occurrences.length > 1 ? "Repeated" : "One-off",
    pattern: detailedPattern(
      occurrences,
      relationship.rawCandidates.length,
      newDuration,
      regularSpacing,
      sourcePassages.length > 0,
    ),
    occurrences,
  };
}

function mergeSourceAlternatives(sourceFamilies, newDuration) {
  const relationships = [];
  for (const family of sourceFamilies) {
    const match = relationships.find((relationship) =>
      sameDerivativeRelationship(relationship, family),
    );
    if (!match) {
      relationships.push({
        sourcePassages: [...family.sourcePassages],
        rawCandidates: [...family.rawCandidates],
        occurrences: [...family.occurrences],
      });
    } else {
      match.sourcePassages.push(...family.sourcePassages);
      match.rawCandidates.push(...family.rawCandidates);
      match.occurrences = collapseNewOccurrences([
        ...match.occurrences,
        ...family.occurrences,
      ]);
    }
  }
  return relationships.map((relationship) =>
    finalizeRelationship(relationship, newDuration),
  );
}

export function groupIntervals(intervals, newDuration = null) {
  const valid = intervals.filter(
    (item) =>
      Number.isFinite(item.new_start) &&
      Number.isFinite(item.new_end) &&
      item.new_end > item.new_start,
  );
  const rawFamilies = [];
  const ordered = [...valid].sort(
    (a, b) =>
      Number.isFinite(b.original_start) - Number.isFinite(a.original_start) ||
      (a.original_start ?? Infinity) - (b.original_start ?? Infinity) ||
      a.new_start - b.new_start,
  );

  for (const interval of ordered) {
    let bestFamily = null;
    let bestScore = -1;
    for (const family of rawFamilies) {
      const score = sourceFamilyScore(interval, family);
      if (score > bestScore) {
        bestScore = score;
        bestFamily = family;
      }
    }
    if (!bestFamily || bestScore < 0) rawFamilies.push([interval]);
    else bestFamily.push(interval);
  }

  const sourceFamilies = rawFamilies
    .map((family) => ({
      sourcePassages: sourcePassagesFromFamily(family),
      rawCandidates: [...family].sort(
        (a, b) => a.new_start - b.new_start || a.new_end - b.new_end,
      ),
      occurrences: collapseNewOccurrences(family),
    }))
    .filter((family) => family.occurrences.length);

  const relationships = mergeSourceAlternatives(sourceFamilies, newDuration)
    .sort(
      (a, b) =>
        b.occurrenceCount - a.occurrenceCount ||
        b.candidateCount - a.candidateCount ||
        (a.firstUse ?? Infinity) - (b.firstUse ?? Infinity),
    )
    .map((relationship, index) => ({
      ...relationship,
      groupNumber: index + 1,
    }));

  return relationships;
}

function timestamp(seconds) {
  if (!Number.isFinite(seconds)) return "Unknown";
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return `${minutes}:${remainder.toFixed(1).padStart(4, "0")}`;
}

function readNumber(cell) {
  const input = cell?.querySelector('input[type="number"]');
  const raw = input ? input.value : (cell?.dataset?.timeValue ?? cell?.textContent?.trim());
  if (!raw || /not located/i.test(raw)) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function rowsFromTable(table) {
  return [...(table.tBodies[0]?.rows || [])]
    .map((row, rowIndex) => {
      const cells = [...row.cells];
      return {
        row,
        rowIndex,
        new_start: readNumber(cells[0]),
        new_end: readNumber(cells[1]),
        original_start: readNumber(cells[2]),
        original_end: readNumber(cells[3]),
        ending_note: row.querySelector("[data-ending-review]")?.textContent || "",
      };
    })
    .filter(
      (item) =>
        Number.isFinite(item.new_start) &&
        Number.isFinite(item.new_end) &&
        item.new_end > item.new_start,
    );
}

function sourcePassageHtml(family) {
  if (!family.sourcePassages.length)
    return '<span class="muted">Original passage not located</span>';
  const endingUncertain = family.rawCandidates.some(item => item.ending_note);
  const chips = family.sourcePassages
    .map(
      (passage) =>
        `<span class="timestampChip">${timestamp(passage.start)}–${endingUncertain ? "≈ " : ""}${timestamp(passage.end)}</span>`,
    )
    .join("");
  const note =
    family.sourcePassages.length > 1
      ? '<small>Alternative original occurrences</small>'
      : "";
  return `<div class="timestampChips">${chips}</div>${note}`;
}

function derivativeTimestampHtml(family) {
  const visibleLimit = 6;
  const visible = family.occurrences.slice(0, visibleLimit);
  const remaining = family.occurrences.slice(visibleLimit);
  const chips = visible
    .map(
      (item) =>
        `<span class="timestampChip">${timestamp(item.new_start)}–${item.ending_uncertain ? "≈ " : ""}${timestamp(item.new_end)}</span>`,
    )
    .join("");
  if (!remaining.length) return `<div class="timestampChips">${chips}</div>${endingNotesHtml(family)}`;
  const more = remaining
    .map(
      (item) =>
        `<span class="timestampChip">${timestamp(item.new_start)}–${item.ending_uncertain ? "≈ " : ""}${timestamp(item.new_end)}</span>`,
    )
    .join("");
  return `<div class="timestampChips">${chips}</div>
    <details class="moreTimestamps"><summary>View ${remaining.length} more</summary><div class="timestampChips">${more}</div></details>${endingNotesHtml(family)}`;
}

function endingNotesHtml(family) {
  const notes = [...new Set(family.rawCandidates.map(item => item.ending_note).filter(Boolean))];
  const escape = text => text.replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
  if (!notes.length) return "";
  const body = notes.map(note => `<small class="endingReview">${escape(note)}</small>`).join("");
  return notes.length === 1
    ? `<div data-ending-review-summary>${body}</div>`
    : `<details data-ending-review-summary><summary>Ending unclear in ${notes.length} suggestions</summary>${body}</details>`;
}

function summaryTable(families) {
  return `<section class="groupedUseSummary" aria-label="Sample relationships">
    <h3>Sample relationships</h3>
    <p class="muted">Each row groups possible uses of a source passage. Confirm the suggested times by listening. Overlapping detector windows are counted once.</p>
    <div class="tableWrap groupedUseTable"><table>
      <thead><tr><th>Original track</th><th>Derivative track</th><th>Type of sampling</th><th>Suggested times in your track</th></tr></thead>
      <tbody>${families
        .map(
          (family) => `<tr>
            <td>${sourcePassageHtml(family)}</td>
            <td><strong>${family.occurrenceCount} possible ${family.occurrenceCount === 1 ? "use" : "uses"}</strong><small>${family.pattern}</small></td>
            <td><span class="useType ${family.useType === "Repeated" ? "repeated" : "oneOff"}">${family.useType}</span></td>
            <td>${derivativeTimestampHtml(family)}</td>
          </tr>`,
        )
        .join("")}</tbody>
    </table></div>
  </section>`;
}

function enhanceTrack(track) {
  const tableWrap = track.querySelector(".tableWrap");
  const table = tableWrap?.querySelector("table");
  if (!table || tableWrap.dataset.groupedEnhanced === "true") return;
  if (table.querySelector("input[data-interval]")) return;

  const rows = rowsFromTable(table);
  if (!rows.length) return;
  tableWrap.dataset.groupedEnhanced = "true";

  const audioDuration = document.querySelector("#newPlayer")?.duration;
  const fallbackDuration = Math.max(...rows.map((item) => item.new_end));
  const families = groupIntervals(
    rows,
    Number.isFinite(audioDuration) ? audioDuration : fallbackDuration,
  );
  if (!families.length) return;

  tableWrap.insertAdjacentHTML("beforebegin", summaryTable(families));
  const details = document.createElement("details");
  details.className = "exactTimestamps";
  const summary = document.createElement("summary");
  summary.textContent = `Technical detail: view all ${rows.length} Sony / DTW candidate rows`;
  tableWrap.parentNode.insertBefore(details, tableWrap);
  details.append(summary, tableWrap);
}

function enhanceAll() {
  document
    .querySelectorAll('.track[data-rights="master"]')
    .forEach((track) => enhanceTrack(track));
}

if (typeof document !== "undefined") {
  const view = document.querySelector("#view");
  let scheduled = false;
  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      enhanceAll();
    });
  };
  if (view) {
    new MutationObserver(schedule).observe(view, { childList: true, subtree: true });
    view.addEventListener("change", schedule);
  }
  window.addEventListener("load", schedule);
  schedule();
}
