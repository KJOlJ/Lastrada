const assert = require("assert");
const fs = require("fs");
const path = require("path");

module.exports = async (page, data, scenario, errors) => {
  if (scenario === "no_match") {
    await page.getByRole("heading", { name: "We couldn’t confidently identify the sample." }).waitFor();
    assert.strictEqual(await page.getByRole("button", { name: "Confirm description & continue →" }).count(), 0);
    await page.getByRole("button", { name: "Try another pair" }).click();
    await page.getByRole("heading", { name: "Start with the music." }).waitFor();
    return;
  }
  await page.getByRole("heading", { name: "Does this describe your sample?" }).waitFor();
  assert((await page.locator("#progress").innerText()).includes("STEP 3 OF 6"));
  assert.strictEqual(await page.locator("[data-times], [data-field=times_confirmed], [data-field=status]").count(), 0);
  assert.strictEqual(await page.locator('[data-rights="publishing"]').count(), 0);
  const fields = ["element", "method", "repetition", "role", "lyrics"];
  for (const field of fields)
    assert((await page.locator(`[data-field=${field}]`).inputValue()).trim(), `${field} must be prefilled`);
  const element = page.getByLabel("What did you take?", { exact: true });
  assert((await element.inputValue()).includes(scenario === "prefilled" ? "Guitar" : "instrument not identified"));
  assert((await page.getByLabel("Any reused lyrics? (optional)").inputValue()).includes("Not assessed"));
  const role = page.getByLabel("What does it do in your track?", { exact: true });
  if (scenario === "reload_edits" || scenario.startsWith("automatic")) {
    await element.fill("My edited sound");
    await role.fill("My main hook");
    await page.getByLabel("Any reused lyrics? (optional)").fill("");
  }
  if (scenario === "automatic" || scenario === "automatic_subset") {
    await page.waitForFunction(() => [...document.querySelectorAll(".automaticInstrumentStatus")]
      .some(node => node.textContent.includes("is complete")));
    assert.strictEqual(await element.inputValue(), "My edited sound");
    assert.strictEqual(await role.inputValue(), "My main hook");
    assert.strictEqual(await page.getByLabel("Any reused lyrics? (optional)").inputValue(), "");
    assert.strictEqual(data.analysis.review.corrected, null, "Instrument launch must not save an unconfirmed description");
    if (scenario === "automatic_subset") {
      assert.strictEqual(data.analysis.master.locate.sample_occurrences.length, 2);
      assert.strictEqual(data.sample_review.intervals.length, 1);
    }
  }
  await page.locator("#sampleEvidence > summary").click();
  await page.locator(".groupedUseTable").waitFor();
  assert((await page.locator("#sampleEvidence").innerText()).includes("Estimated ending"));
  assert.strictEqual(await page.locator("[data-times], [data-field=times_confirmed]").count(), 0);
  await page.locator("#sampleEvidence > summary").click();
  if (process.env.LASTRADA_BROWSER_OUTPUT) {
    fs.mkdirSync(process.env.LASTRADA_BROWSER_OUTPUT, { recursive: true });
    await page.screenshot({ path: path.join(process.env.LASTRADA_BROWSER_OUTPUT, `sample-description-${scenario}.png`), fullPage: true });
  }
  const savedElement = await element.inputValue();
  await page.getByRole("button", { name: "Confirm description & continue →" }).click();
  await page.getByRole("heading", { name: "Does this placement look right?" }).waitFor();
  assert(await page.getByLabel("matched passages", { exact: true }).isChecked());
  assert(await page.getByLabel("Where does it appear overall?").inputValue());
  await page.getByRole("button", { name: "← Back", exact: true }).click();
  assert.strictEqual(await element.inputValue(), savedElement);
  await page.getByRole("button", { name: "Confirm description & continue →" }).click();
  await page.getByRole("button", { name: "Confirm placement & review draft →" }).click();
  if (scenario === "automatic_confirm")
    await page.getByText(/Your answers are kept\. Finishing the instrument check/).waitFor();
  await page.getByRole("heading", { name: "Make it yours." }).waitFor();
  assert.strictEqual(data.analysis.review.workflow, "sample");
  assert.strictEqual(data.analysis.review.corrected.master.locate.detection_status, "candidate");
  assert.strictEqual(data.analysis.review.corrected.master.locate.timing_source, "automated");
  assert(data.analysis.review.corrected.master.locate.sample_occurrences[0].end_review);
  await page.getByRole("button", { name: "Mark document as reviewed", exact: true }).click();
  await page.getByText("Reviewed and ready to download.", { exact: true }).first().waitFor();
  await page.getByRole("button", { name: "Next: Your Nature of Use →" }).click();
  const ready = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download HTML", exact: true }).click();
  const download = await ready;
  const text = fs.readFileSync(await download.path(), "utf8");
  assert(text.includes("NATURE OF USE") && text.includes("automatically estimated"));
  assert(!text.includes("No separate replayed") && !text.includes("Replayed melody"));
  await page.reload();
  await page.getByRole("heading", { name: "Does this describe your sample?" }).waitFor();
  assert.strictEqual(await element.inputValue(), savedElement);
  if (scenario === "reload_edits" || scenario.startsWith("automatic")) {
    assert.strictEqual(await role.inputValue(), "My main hook");
    assert.strictEqual(await page.getByLabel("Any reused lyrics? (optional)").inputValue(), "");
  }
  await page.setViewportSize({ width: 700, height: 1000 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
  assert.deepStrictEqual(errors, []);
};
