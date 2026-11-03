const assert = require("assert");
const path = require("path");
const { pathToFileURL } = require("url");

(async () => {
  const module = await import(
    pathToFileURL(
      path.resolve(__dirname, "../../web/public/relationship-evidence.js"),
    ),
  );

  const family = {
    rawCandidates: [
      {
        new_start: 10,
        new_end: 18,
        original_start: 42,
        original_end: 50,
      },
      {
        new_start: 30,
        new_end: 38,
        original_start: 42,
        original_end: 50,
      },
    ],
  };
  const rows = [
    {
      occurrence_id: "one",
      status: "checked",
      interval: family.rawCandidates[0],
      suggested_instruments: ["Bass"],
      evidence: [
        {
          source_stem: "bass",
          new_song_stem: "bass",
          dtw_result: "accepted",
          duration_ratio: 1.04,
          interpretation: "Strong supporting evidence",
        },
        {
          source_stem: "drums",
          new_song_stem: "drums",
          dtw_result: "weak",
          duration_ratio: null,
          interpretation: "Weak alignment",
        },
      ],
    },
    {
      occurrence_id: "two",
      status: "checked",
      interval: family.rawCandidates[1],
      suggested_instruments: ["Bass"],
      evidence: [
        {
          source_stem: "bass",
          new_song_stem: "bass",
          dtw_result: "accepted",
          duration_ratio: 0.98,
          interpretation: "Strong supporting evidence",
        },
      ],
    },
  ];

  const summary = module.summarizeRelationshipEvidence(family, rows);
  assert.strictEqual(summary.checkedCount, 2);
  assert.strictEqual(summary.entries[0].sourceStem, "bass");
  assert.strictEqual(summary.entries[0].newStem, "bass");
  assert.strictEqual(summary.entries[0].result, "accepted");
  assert.strictEqual(summary.entries[0].momentCount, 2);
  assert(Math.abs(summary.entries[0].durationRatio - 1.01) < 0.001);
  assert.strictEqual(summary.entries[1].result, "weak");

  const pending = module.summarizeRelationshipEvidence(family, [
    {
      occurrence_id: "pending",
      status: "pending",
      interval: family.rawCandidates[0],
      evidence: [],
      suggested_instruments: [],
    },
  ]);
  assert.strictEqual(pending.checkedCount, 0);
  assert.strictEqual(pending.pending, 1);
  rows[1].evidence[0].dtw_result = "rejected";
  rows[1].evidence[0].duration_ratio = 8;
  const mixed = module.summarizeRelationshipEvidence(family, rows).entries[0];
  assert.strictEqual(mixed.momentCount, 1);
  assert.strictEqual(mixed.checkedMomentCount, 2);
  assert.strictEqual(mixed.durationRatio, 1.04);
  rows[0].context_only = true;
  assert(!module.summarizeRelationshipEvidence(family, rows).entries.some(e => e.result === "accepted"));
  rows[1].evidence = [];
  assert.strictEqual(module.summarizeRelationshipEvidence(family, rows).entries.length, 0,
    "A suggested label must never fabricate an accepted comparison");
  console.log("Relationship evidence tests passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
