const assert = require("assert");
const path = require("path");
const { pathToFileURL } = require("url");

(async () => {
  const module = await import(
    pathToFileURL(
      path.resolve(__dirname, "../../web/public/grouped-timestamps.js"),
    ),
  );
  const rows = [
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

  const families = module.groupIntervals(rows, 70);
  assert.strictEqual(families.length, 2);
  assert.strictEqual(families[0].candidateCount, 4);
  assert.strictEqual(families[0].occurrenceCount, 3);
  assert.strictEqual(families[0].pattern, "Likely looped throughout");
  assert.strictEqual(families[0].groupNumber, 1);
  assert.strictEqual(families[1].occurrenceCount, 1);
  console.log("Grouped timestamp tests passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
