const EPSILON = 1e-9;

export const placementLabels = {
  throughout: "Throughout the track",
  intro_only: "Intro only",
  outro_only: "Outro only",
  intro_outro_with_chorus: "Intro, outro and chorus",
  intro_outro_without_chorus: "Intro and outro",
  chorus_only: "Recurring chorus-like sections",
  verses: "Verse sections",
  bridge_only: "Bridge",
  selected_sections: "Selected sections",
  one_time: "One appearance",
};

function finite(value) {
  return Number.isFinite(Number(value));
}

export function mergeIntervals(intervals = [], startKey = "new_start", endKey = "new_end") {
  const ranges = intervals
    .map((interval) => [Number(interval[startKey]), Number(interval[endKey])])
    .filter(([start, end]) => Number.isFinite(start) && Number.isFinite(end) && end > start)
    .sort((left, right) => left[0] - right[0] || left[1] - right[1]);
  const merged = [];
  for (const [start, end] of ranges) {
    const previous = merged.at(-1);
    if (previous && start <= previous[1] + EPSILON) previous[1] = Math.max(previous[1], end);
    else merged.push([start, end]);
  }
  return merged;
}

function median(values = []) {
  const sorted = values.filter(Number.isFinite).sort((left, right) => left - right);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function shortRegularUses(ranges) {
  if (ranges.length < 2) return false;
  const lengths = ranges.map(([start, end]) => end - start);
  const typical = median(lengths);
  return (
    typical <= 8 &&
    Math.max(...lengths) - Math.min(...lengths) <= Math.max(0.5, typical * 0.3)
  );
}

export function acceptedSameStemMatches(instrumentRows = [], fallbackEvidence = []) {
  const matches = new Map();
  const add = (evidence, momentKey) => {
    const source = String(evidence?.source_stem || "").toLowerCase();
    const derivative = String(evidence?.new_song_stem || "").toLowerCase();
    if (evidence?.dtw_result !== "accepted" || !source || source !== derivative) return;
    const current = matches.get(source) || { stem: source, moments: new Set(), ratios: [] };
    current.moments.add(momentKey);
    if (finite(evidence.duration_ratio)) current.ratios.push(Number(evidence.duration_ratio));
    matches.set(source, current);
  };

  instrumentRows.forEach((row, rowIndex) => {
    (row.evidence || []).forEach((evidence) =>
      add(evidence, row.occurrence_id || `row-${rowIndex}`),
    );
  });
  if (!matches.size) {
    fallbackEvidence.forEach((evidence, index) =>
      add(evidence, `candidate-${evidence.candidate_number || index + 1}`),
    );
  }

  const ordered = [...matches.values()]
    .map((item) => ({
      stem: item.stem,
      momentCount: item.moments.size,
      durationRatio: median(item.ratios),
    }))
    .sort(
      (left, right) =>
        Number(left.stem === "full_mix") - Number(right.stem === "full_mix") ||
        right.momentCount - left.momentCount ||
        left.stem.localeCompare(right.stem),
    );
  const separated = ordered.filter((item) => item.stem !== "full_mix");
  return separated.length ? separated : ordered;
}

function inferPlacement(ranges, duration, coveragePercentage) {
  if (!ranges.length || !duration) {
    return {
      placement: "selected_sections",
      sections: ["verse"],
      placementBasis: "Placement could not be estimated from the available timestamps.",
    };
  }
  const span = (ranges.at(-1)[1] - ranges[0][0]) / duration;
  const gaps = ranges.slice(1).map((range, index) => range[0] - ranges[index][1]);
  const frequent = ranges.length >= 6 && Math.max(0, ...gaps) <= duration * 0.18;
  if ((coveragePercentage >= 60 && span >= 0.85) || (span >= 0.85 && frequent)) {
    return {
      placement: "throughout",
      sections: ["whole track"],
      placementBasis: "The confirmed uses span most of the derivative track.",
    };
  }
  const intro = ranges.filter((range) => range[1] <= duration * 0.2);
  const outro = ranges.filter((range) => range[0] >= duration * 0.8);
  if (intro.length === ranges.length) {
    return {
      placement: "intro_only",
      sections: ["intro"],
      placementBasis: "All confirmed uses fall in the opening 20% of the track.",
    };
  }
  if (outro.length === ranges.length) {
    return {
      placement: "outro_only",
      sections: ["outro"],
      placementBasis: "All confirmed uses fall in the final 20% of the track.",
    };
  }
  if (intro.length + outro.length === ranges.length && intro.length && outro.length) {
    return {
      placement: "intro_outro_without_chorus",
      sections: ["intro", "outro"],
      placementBasis: "Confirmed uses are limited to the opening and ending.",
    };
  }
  if (ranges.length >= 2 && shortRegularUses(ranges)) {
    return {
      placement: "chorus_only",
      sections: ["chorus"],
      placementBasis:
        "Recurring similar-length interior uses are provisionally labeled chorus-like.",
    };
  }
  if (ranges.length === 1) {
    return {
      placement: "one_time",
      sections: ["verse"],
      placementBasis:
        "One interior use is provisionally labeled as a verse or selected section.",
    };
  }
  return {
    placement: "selected_sections",
    sections: ["verse", "chorus"],
    placementBasis:
      "The sample recurs in interior sections; the section labels remain editable estimates.",
  };
}

function samplingPattern(ranges, duration, coveragePercentage) {
  if (!ranges.length) return { samplingType: "unconfirmed", samplingLabel: "Timing unconfirmed" };
  const span = duration ? (ranges.at(-1)[1] - ranges[0][0]) / duration : 0;
  if (coveragePercentage >= 60 && span >= 0.85) {
    return { samplingType: "throughout", samplingLabel: "Repeated throughout the track" };
  }
  if (ranges.length === 1) {
    return { samplingType: "one_off", samplingLabel: "One-off use" };
  }
  if (shortRegularUses(ranges)) {
    return { samplingType: "looped", samplingLabel: "A short loop repeated in the track" };
  }
  return { samplingType: "repeated", samplingLabel: "Repeated in multiple passages" };
}

export function formatTimestamp(seconds) {
  if (!Number.isFinite(seconds)) return "Unknown";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(1).padStart(4, "0")}`;
}

export function inferNatureSummary({
  intervals = [],
  newDuration = 0,
  instrumentRows = [],
  stemEvidence = [],
  backendSummary = null,
} = {}) {
  const ranges = mergeIntervals(intervals);
  const sourcePassages = mergeIntervals(intervals, "original_start", "original_end");
  const coveredSeconds = ranges.reduce((total, [start, end]) => total + end - start, 0);
  const coveragePercentage = newDuration ? (coveredSeconds / newDuration) * 100 : 0;
  const placement = inferPlacement(ranges, newDuration, coveragePercentage);
  const pattern = samplingPattern(ranges, newDuration, coveragePercentage);
  const stemMatches = acceptedSameStemMatches(instrumentRows, stemEvidence);
  const sampledStems = stemMatches.map((match) => match.stem);
  const humanStems = sampledStems.map((stem) => stem.replaceAll("_", " "));
  const elementSuggestion = humanStems.length
    ? `${humanStems.join(", ")} ${humanStems.length === 1 ? "stem" : "stems"}`
    : "sampled material";
  const merged = {
    rightsAssumption: "master_recording_sample",
    distinctUses: ranges.length,
    coveredSeconds,
    coveragePercentage,
    firstUse: ranges[0]?.[0] ?? null,
    lastUse: ranges.at(-1)?.[1] ?? null,
    mergedDerivativeRanges: ranges,
    sourcePassages,
    stemMatches,
    sampledStems,
    elementSuggestion,
    roleSuggestion:
      placement.placement === "throughout"
        ? "Recurring foundation in the derivative track"
        : ranges.length > 1
          ? "Recurring section element"
          : "Supporting sampled element",
    ...pattern,
    ...placement,
  };

  if (backendSummary && typeof backendSummary === "object") {
    merged.coveredSeconds = Number(backendSummary.covered_seconds ?? merged.coveredSeconds);
    merged.coveragePercentage = Number(
      backendSummary.coverage_percentage ?? merged.coveragePercentage,
    );
    merged.distinctUses = Number(backendSummary.distinct_uses ?? merged.distinctUses);
    merged.firstUse = backendSummary.first_use ?? merged.firstUse;
    merged.lastUse = backendSummary.last_use ?? merged.lastUse;
    merged.samplingType = backendSummary.sampling_type || merged.samplingType;
    merged.samplingLabel = backendSummary.sampling_label || merged.samplingLabel;
    merged.placement = backendSummary.placement || merged.placement;
    merged.sections = backendSummary.sections || merged.sections;
    merged.placementBasis = backendSummary.placement_basis || merged.placementBasis;
    merged.roleSuggestion = backendSummary.role_suggestion || merged.roleSuggestion;
    merged.elementSuggestion = backendSummary.element_suggestion || merged.elementSuggestion;
  }
  return merged;
}

export function buildDraftNarrative(summary, credits = {}) {
  const derivative = credits.newTitle ? `"${credits.newTitle}"` : "The derivative track";
  const original = credits.originalTitle ? `"${credits.originalTitle}"` : "the original track";
  const count = Number(summary.distinctUses) || 0;
  const occurrenceWord = count === 1 ? "appearance" : "appearances";
  const placement = placementLabels[summary.placement] || placementLabels.selected_sections;
  const timing =
    Number.isFinite(summary.firstUse) && Number.isFinite(summary.lastUse)
      ? `The first confirmed use begins at ${formatTimestamp(summary.firstUse)} and the last ends at ${formatTimestamp(summary.lastUse)}.`
      : "The exact placement still requires review.";
  const stems = summary.sampledStems?.length
    ? `Demucs and same-stem DTW support ${summary.sampledStems
        .map((stem) => stem.replaceAll("_", " "))
        .join(", ")}.`
    : "No separated stem produced a supporting same-stem DTW match.";
  return `${derivative} samples ${summary.elementSuggestion} from the master recording of ${original}. The sample appears in ${count} distinct ${occurrenceWord}, covering ${summary.coveredSeconds.toFixed(1)} seconds (${summary.coveragePercentage.toFixed(1)}%) of the derivative track. It is ${summary.samplingLabel.toLowerCase()} and is estimated to appear ${placement.toLowerCase()}. ${timing} ${stems} The timestamps, stem label and section placement should be reviewed before finalization.`;
}
