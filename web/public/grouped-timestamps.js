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
    Math.max(aDuration, bDuration) / Math.max(EPSILON, Math.min(aDuration, bDuration));
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
    .map((cluster) =>
      [...cluster].sort(
        (a, b) =>
          (b.similarity ?? -2) - (a.similarity ?? -2) ||
          duration(b.new_start, b.new_end) - duration(a.new_start, a.new_end),
      )[0],
    )
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

function patternFor(
  occurrences,
  candidateCount,
  newDuration,
  regularSpacing,
  sourceKnown,
) {
  const count = occurrences.length;
  if (!sourceKnown)
    return candidateCount >= 3
      ? "Clustered unresolved candidates"
      : "Unresolved candidate";

  const span = count
    ? occurrences[occurrences.length - 1].new_end - occurrences[0].new_start
    : 0;
  const spread = Number.isFinite(newDuration) && newDuration > 0 ? span / newDuration : 0;
  if (count >= 3 && spread >= 0.65) return "Likely looped throughout";
  if (count >= 3 && regularSpacing) return "Likely regular loop";
  if (count >= 3) return "Repeated use";
  if (count === 2) return "Repeated twice";
  if (candidateCount >= 3) return "Continuous or overlapping use";
  return "Single use";
}

export function groupIntervals(intervals, newDuration = null) {
  const valid = intervals.filter(
    (item) =>
      Number.isFinite(item.new_start) &&
      Number.isFinite(item.new_end) &&
      item.new_end > item.new_start,
  );
  const families = [];
  const ordered = [...valid].sort(
    (a, b) =>
      Number.isFinite(b.original_start) - Number.isFinite(a.original_start) ||
      (a.original_start ?? Infinity) - (b.original_start ?? Infinity) ||
      a.new_start - b.new_start,
  );

  for (const interval of ordered) {
    let bestFamily = null;
    let bestScore = -1;
    for (const family of families) {
      const score = sourceFamilyScore(interval, family);
      if (score > bestScore) {
        bestScore = score;
        bestFamily = family;
      }
    }
    if (!bestFamily || bestScore < 0) families.push([interval]);
    else bestFamily.push(interval);
  }

  const summaries = families
    .map((family) => {
      const occurrences = collapseNewOccurrences(family);
      if (!occurrences.length) return null;
      const [sourceStart, sourceEnd] = representativeSource(family);
      const [typicalSpacing, regularSpacing] = spacing(occurrences);
      return {
        sourceStart,
        sourceEnd,
        candidateCount: family.length,
        occurrenceCount: occurrences.length,
        firstUse: occurrences[0].new_start,
        lastUse: occurrences[occurrences.length - 1].new_end,
        coverageSeconds: mergedCoverage(occurrences),
        typicalSpacingSeconds: typicalSpacing,
        regularSpacing,
        pattern: patternFor(
          occurrences,
          family.length,
          newDuration,
          regularSpacing,
          sourceStart != null,
        ),
        occurrences,
        rawCandidates: [...family].sort(
          (a, b) => a.new_start - b.new_start || a.new_end - b.new_end,
        ),
      };
    })
    .filter(Boolean)
    .sort(
      (a, b) =>
        b.occurrenceCount - a.occurrenceCount ||
        b.candidateCount - a.candidateCount ||
        a.firstUse - b.firstUse,
    );

  return summaries.map((family, index) => ({
    ...family,
    groupNumber: index + 1,
  }));
}

function timestamp(seconds) {
  if (!Number.isFinite(seconds)) return "Unknown";
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return `${minutes}:${remainder.toFixed(1).padStart(4, "0")}`;
}

function readNumber(cell) {
  const input = cell?.querySelector('input[type="number"]');
  const raw = input ? input.value : cell?.textContent?.trim();
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
      };
    })
    .filter(
      (item) =>
        Number.isFinite(item.new_start) &&
        Number.isFinite(item.new_end) &&
        item.new_end > item.new_start,
    );
}

function summaryTable(families) {
  return `<section class="groupedUseSummary" aria-label="Grouped use pattern">
    <h3>Grouped use pattern</h3>
    <p class="muted">Overlapping Sony windows that point to the same source passage are collapsed into use groups. Every exact timestamp remains available below.</p>
    <div class="tableWrap groupedUseTable"><table>
      <thead><tr><th>Group</th><th>Pattern</th><th>Source passage</th><th>Uses</th><th>Candidate rows</th><th>First use</th><th>Last use</th><th>Coverage</th><th>Typical spacing</th></tr></thead>
      <tbody>${families
        .map(
          (family) => `<tr>
            <td><span class="groupBadge">G${family.groupNumber}</span></td>
            <td><strong>${family.pattern}</strong></td>
            <td>${family.sourceStart == null ? "Source not identified" : `${timestamp(family.sourceStart)}–${timestamp(family.sourceEnd)}`}</td>
            <td>${family.occurrenceCount}</td>
            <td>${family.candidateCount}</td>
            <td>${timestamp(family.firstUse)}</td>
            <td>${timestamp(family.lastUse)}</td>
            <td>${family.coverageSeconds.toFixed(1)}s</td>
            <td>${family.typicalSpacingSeconds == null ? "—" : `${family.typicalSpacingSeconds.toFixed(1)}s`}</td>
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

  const groupByRow = new Map();
  for (const family of families)
    for (const item of family.rawCandidates)
      groupByRow.set(item.rowIndex, family.groupNumber);

  const header = table.tHead?.rows[0];
  if (header) {
    const th = document.createElement("th");
    th.textContent = "Group";
    header.insertBefore(th, header.firstElementChild);
  }

  const ordered = [...rows].sort(
    (a, b) =>
      (groupByRow.get(a.rowIndex) ?? Infinity) -
        (groupByRow.get(b.rowIndex) ?? Infinity) ||
      a.new_start - b.new_start ||
      a.new_end - b.new_end,
  );
  for (const item of ordered) {
    const td = document.createElement("td");
    td.innerHTML = `<span class="groupBadge">G${groupByRow.get(item.rowIndex)}</span>`;
    item.row.insertBefore(td, item.row.firstElementChild);
    table.tBodies[0].append(item.row);
  }

  tableWrap.insertAdjacentHTML("beforebegin", summaryTable(families));
  const details = document.createElement("details");
  details.className = "exactTimestamps";
  const summary = document.createElement("summary");
  summary.textContent = `View all ${rows.length} exact timestamp suggestion${rows.length === 1 ? "" : "s"}`;
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
