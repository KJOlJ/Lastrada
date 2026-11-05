const assert = require("assert");
const path = require("path");
const { pathToFileURL } = require("url");

(async () => {
  const { restoreEndingReview } = await import(pathToFileURL(
    path.resolve(__dirname, "../../web/public/ending-review.js"),
  ));
  const cue = { new_through: 3, original_through: 4, reason: "quiet_or_obscured_tail" };
  const original = { new_start: 1, new_end: 2.5, original_start: 2, original_end: 3.5, end_review: cue };
  const saved = { ...original, end_review: null };
  const before = structuredClone([original, saved]);
  assert.deepStrictEqual(restoreEndingReview(saved, [original]).end_review, cue);
  assert.deepStrictEqual([original, saved], before);

  // Reordered or deleted rows cannot transfer their warning by array index.
  const other = { new_start: 10, new_end: 12, original_start: 7, original_end: 9 };
  assert.strictEqual(restoreEndingReview(other, [original]).end_review, null);
  assert.deepStrictEqual(restoreEndingReview(saved, [other, original]).end_review, cue);
  assert.strictEqual(restoreEndingReview({ ...saved, new_start: 1.2 }, [original]).end_review, null);
  assert.strictEqual(restoreEndingReview({ ...saved, original_start: 2.2 }, [original]).end_review, null);
  assert.strictEqual(restoreEndingReview(saved, [original, saved]).end_review, null);
  assert.strictEqual(restoreEndingReview(saved, [original, {
    ...original, end_review: { ...cue, new_through: 3.5 },
  }]).end_review, null);
  assert.deepStrictEqual(restoreEndingReview(saved, [original, { ...original }]).end_review, cue);
  assert.strictEqual(restoreEndingReview(saved).end_review, null);

  // Persisted context follows the reviewed row even after edits beyond the
  // reference points; it must never replace the reviewer's timestamps.
  const edited = { ...other, ending_review_context: cue };
  const restored = restoreEndingReview(edited);
  assert.deepStrictEqual(restored, { ...edited, end_review: cue });
  restored.end_review.new_through = 99;
  assert.strictEqual(cue.new_through, 3);
  console.log("Ending review restoration tests passed");
})().catch(error => {
  console.error(error);
  process.exit(1);
});
