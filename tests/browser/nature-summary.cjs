const assert = require("assert");
const path = require("path");
const { pathToFileURL } = require("url");

(async () => {
  const module = await import(
    pathToFileURL(
      path.resolve(__dirname, "../../web/public/nature-summary.js"),
    ),
  );

  const intervals = [
    {
      new_start: 0,
      new_end: 8,
      original_start: 25,
      original_end: 33,
    },
    {
      new_start: 20,
      new_end: 28,
      original_start: 25,
      original_end: 33,
    },
    {
      new_start: 40,
      new_end: 48,
      original_start: 25,
      original_end: 33,
    },
  ];
  const instrumentRows = intervals.map((interval, index) => ({
    occurrence_id: `row-${index}`,
    status: "checked",
    interval,
    evidence: [
      {
        source_stem: "drums",
        new_song_stem: "drums",
        dtw_result: "accepted",
        duration_ratio: 1,
      },
      {
        source_stem: "drums",
        new_song_stem: "guitar",
        dtw_result: "accepted",
        duration_ratio: 1,
      },
      {
        source_stem: "bass",
        new_song_stem: "bass",
        dtw_result: "rejected",
      },
    ],
  }));

  const summary = module.inferNatureSummary({
    intervals,
    newDuration: 60,
    instrumentRows,
  });

  assert.strictEqual(summary.distinctUses, 3);
  assert.strictEqual(summary.coveredSeconds, 24);
  assert.strictEqual(summary.coveragePercentage, 40);
  assert.strictEqual(summary.samplingType, "looped");
  assert.deepStrictEqual(summary.sampledStems, ["drums"]);
  assert.strictEqual(summary.stemMatches[0].momentCount, 3);
  assert.strictEqual(summary.placement, "chorus_only");
  assert.deepStrictEqual(summary.sections, ["chorus"]);

  const narrative = module.buildDraftNarrative(summary, {
    originalTitle: "Source",
    newTitle: "Derivative",
  });
  assert(narrative.includes("40.0%"));
  assert(narrative.includes("drums"));
  assert(narrative.includes("same-stem DTW"));
  assert(!narrative.includes("drums, guitar"));

  const intro = module.inferNatureSummary({
    intervals: [{ new_start: 0, new_end: 5 }],
    newDuration: 100,
  });
  assert.strictEqual(intro.placement, "intro_only");
  assert.strictEqual(intro.samplingType, "one_off");

  console.log("Nature of Use summary tests passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
