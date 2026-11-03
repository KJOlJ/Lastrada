const assert = require("assert");
const fs = require("fs");
const http = require("http");
const path = require("path");
let chromium;
try {
  ({ chromium } = require("../../web/node_modules/playwright"));
} catch {
  ({ chromium } = require("/opt/codex/cua_node/lib/node_modules/playwright"));
}

(async () => {
  const root = path.resolve(__dirname, "../..");
  const script = fs.readFileSync(
    path.join(root, "web/public/matched-stems-only.js"),
    "utf8",
  );
  const html = `<!doctype html>
  <html><body>
    <section id="view">
      <table><tbody><tr><td data-stem-dtw-evidence>
        <div class="stemEvidenceList">
          <div class="stemEvidenceItem"><div><strong>Drums → Drums</strong><span class="dtwResult accepted">Accepted</span></div><small>8 moments</small></div>
          <div class="stemEvidenceItem"><div><strong>Bass → Bass</strong><span class="dtwResult rejected">Rejected</span></div><small>8 moments</small></div>
        </div>
        <details class="moreStemEvidence"><summary>View 2 more stem results</summary><div class="stemEvidenceList">
          <div class="stemEvidenceItem"><div><strong>Vocals → Vocals</strong><span class="dtwResult weak">Weak</span></div><small>3 moments</small></div>
          <div class="stemEvidenceItem"><div><strong>Guitar → Guitar</strong><span class="dtwResult accepted">Accepted</span></div><small>2 moments</small></div>
        </div></details>
        <small class="evidenceProgress">8 of 12 eligible matched moments checked</small>
      </td></tr></tbody></table>
    </section>
    <script type="module" src="/matched-stems-only.js"></script>
  </body></html>`;

  const server = http.createServer((req, res) => {
    if (req.url === "/matched-stems-only.js") {
      res.setHeader("Content-Type", "text/javascript");
      res.end(script);
      return;
    }
    res.setHeader("Content-Type", "text/html");
    res.end(html);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));

  const browser = await chromium.launch({
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}), headless: true, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(
      () =>
        document.querySelectorAll(".stemEvidenceItem").length === 2 &&
        [...document.querySelectorAll(".dtwResult")].every(
          (item) => item.textContent === "Supporting evidence",
        ),
    );

    assert.strictEqual(await page.locator(".stemEvidenceItem").count(), 2);
    assert.strictEqual(await page.locator(".dtwResult.rejected").count(), 0);
    assert.strictEqual(await page.locator(".dtwResult.weak").count(), 0);
    assert.strictEqual(await page.locator(".moreStemEvidence").count(), 0);
    assert.strictEqual(
      await page.locator("[data-stem-dtw-evidence]").getAttribute("data-accepted-stem-count"),
      "2",
    );

    await page.locator("[data-stem-dtw-evidence]").evaluate((cell) => {
      cell.innerHTML = `<div class="stemEvidenceList">
        <div class="stemEvidenceItem"><div><strong>Bass → Bass</strong><span class="dtwResult rejected">Rejected</span></div></div>
      </div><small class="evidenceProgress">1 matched moment checked</small>`;
    });
    await page.getByText("No supporting stem match", { exact: true }).waitFor();
    assert.strictEqual(await page.locator(".stemEvidenceItem").count(), 0);
    assert.strictEqual(
      await page.locator("[data-stem-dtw-evidence]").getAttribute("data-accepted-stem-count"),
      "0",
    );

    console.log("Matched stem display tests passed");
  } finally {
    await browser.close();
    server.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
