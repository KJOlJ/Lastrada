const assert = require("assert");
const path = require("path");
const { pathToFileURL } = require("url");

(async () => {
  const module = await import(
    pathToFileURL(
      path.resolve(__dirname, "../../web/public/grouped-timestamps.js"),
    ),
  );

  const repeated = [
    {
      rowIndex: 0,
      new_start: 10,
      new_end: 18,
      original_start: 42,
      original_end: 50,
    },
    {
      rowIndex: 1,
      new_start: 10.4,
      new_end: 18.2,
      original_start: 42.3,
      original_end: 50.1,
    },
    {
      rowIndex: 2,
      new_start: 30,
      new_end: 38,
      original_start: 42,
      original_end: 50,
    },
    {
      rowIndex: 3,
      new_start: 50,
      new_end: 58,
      original_start: 42,
      original_end: 50,
    },
    {
      rowIndex: 4,
      new_start: 5,
      new_end: 9,
      original_start: 90,
      original_end: 94,
    },
  ];

  const families = module.groupIntervals(repeated, 70);
  assert.strictEqual(families.length, 2);
  assert.strictEqual(families[0].candidateCount, 4);
  assert.strictEqual(families[0].occurrenceCount, 3);
  assert.strictEqual(families[0].useType, "Repeated");
  assert.strictEqual(families[1].occurrenceCount, 1);
  assert.strictEqual(families[1].useType, "One-off");

  // If multiple original passages point to the same derivative occurrences,
  // show the original passages as alternatives in one relationship. Do not
  // count the derivative occurrences twice.
  const alternatives = [
    {
      rowIndex: 0,
      new_start: 10,
      new_end: 18,
      original_start: 42,
      original_end: 50,
    },
    {
      rowIndex: 1,
      new_start: 30,
      new_end: 38,
      original_start: 42,
      original_end: 50,
    },
    {
      rowIndex: 2,
      new_start: 10.2,
      new_end: 18.1,
      original_start: 102,
      original_end: 110,
    },
    {
      rowIndex: 3,
      new_start: 30.1,
      new_end: 38.2,
      original_start: 102,
      original_end: 110,
    },
  ];
  const merged = module.groupIntervals(alternatives, 60);
  assert.strictEqual(merged.length, 1);
  assert.strictEqual(merged[0].sourcePassages.length, 2);
  assert.strictEqual(merged[0].occurrenceCount, 2);
  assert.strictEqual(merged[0].useType, "Repeated");

  // If different original passages point to different derivative groups, keep
  // them as separate table rows.
  const separate = [
    {
      rowIndex: 0,
      new_start: 10,
      new_end: 18,
      original_start: 42,
      original_end: 50,
    },
    {
      rowIndex: 1,
      new_start: 30,
      new_end: 38,
      original_start: 42,
      original_end: 50,
    },
    {
      rowIndex: 2,
      new_start: 70,
      new_end: 78,
      original_start: 102,
      original_end: 110,
    },
    {
      rowIndex: 3,
      new_start: 90,
      new_end: 98,
      original_start: 102,
      original_end: 110,
    },
  ];
  const distinct = module.groupIntervals(separate, 120);
  assert.strictEqual(distinct.length, 2);

  console.log("Grouped relationship tests passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
