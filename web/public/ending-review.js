const endpoints = ["new_start", "new_end", "original_start", "original_end"];

function legacyEndingReview(interval, originals) {
  // Old saved reviews have no provenance for edited/reordered rows. Only
  // recover an exact paired match whose detector rows agree on the cue.
  const matches = originals.filter(original =>
    endpoints.every(key => (original[key] ?? null) === (interval[key] ?? null)),
  );
  const review = matches[0]?.end_review;
  if (!review || matches.some(original =>
    !original.end_review ||
    ["new_through", "original_through", "reason"].some(key =>
      original.end_review[key] !== review[key],
    ),
  )) return null;
  return review;
}

export function restoreEndingReview(interval, originals = []) {
  const review = interval.end_review ?? interval.ending_review_context ??
    legacyEndingReview(interval, originals);
  return { ...interval, end_review: review ? { ...review } : null };
}
