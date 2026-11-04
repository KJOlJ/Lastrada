const fs = require("fs");
const http = require("http");
const path = require("path");
let chromium;
try {
  ({ chromium } = require("../../web/node_modules/playwright"));
} catch {
  ({ chromium } = require("/opt/codex/cua_node/lib/node_modules/playwright"));
}

const root = path.resolve(__dirname, "../..");
const controls = (progress, label, extra = "") => `
  <section id="instruments">
    <h2>Instruments at each moment</h2>
    <p class="muted">Estimate stems for each matched moment.</p>
    <p role="status">${progress}</p>
    ${extra}
    <button data-action="stems">${label}</button>
  </section>`;
const html = `<!doctype html>
<html>
  <head><meta charset="utf-8"></head>
  <body>
    <section id="view"><div class="track" data-rights="master"><div class="tableWrap"><table><tbody><tr><td>0</td><td>4</td><td>2</td><td>6</td></tr></tbody></table></div></div>${controls("0 of 2 moments compared.", "Run instrument check")}</section>
    <script>
      window.__LASTRADA_FORCE_AUTO_INSTRUMENTS__ = true;
      window.automaticInstrumentClicks = 0;
      document.addEventListener("click", (event) => {
        if (event.target.closest('button[data-action="stems"]'))
          window.automaticInstrumentClicks += 1;
      });
    </script>
    <script type="module" src="/grouped-timestamps.js"></script>
    <script type="module" src="/relationship-evidence.js"></script>
    <script type="module" src="/auto-instruments.js"></script>
  </body>
</html>`;

const server = http.createServer((request, response) => {
  if (request.url === "/") {
    response.setHeader("Content-Type", "text/html");
    response.end(html);
    return;
  }
  if (["/auto-instruments.js", "/grouped-timestamps.js", "/relationship-evidence.js"].includes(request.url)) {
    response.setHeader("Content-Type", "text/javascript");
    response.end(fs.readFileSync(path.join(root, "web/public", request.url.slice(1))));
    return;
  }
  response.writeHead(404);
  response.end();
});

(async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : {}),
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(() => window.automaticInstrumentClicks === 1);

    const firstHidden = await page
      .locator('button[data-action="stems"]')
      .getAttribute("hidden");
    if (firstHidden === null)
      throw Error("The manual instrument action was not hidden");

    const automaticCopy = await page.locator("#instruments p.muted").textContent();
    if (!/automatically/i.test(automaticCopy || ""))
      throw Error("Automatic analysis copy was not shown");

    await page.locator(".relationshipEvidenceControls.automaticInstrumentControls").waitFor();
    await page.waitForTimeout(100);
    await page.evaluate(() => {
      window.combinedMutations = 0;
      window.combinedObserver = new MutationObserver(records => { window.combinedMutations += records.length; });
      window.combinedObserver.observe(document.querySelector("#view"), {childList: true, subtree: true, characterData: true});
    });
    await page.waitForTimeout(350);
    if (await page.evaluate(() => window.combinedMutations > 2))
      throw Error("Relationship and automatic status renderers keep overwriting each other");
    await page.evaluate(() => window.combinedObserver.disconnect());
    await page.evaluate((markup) => {
      document.querySelector("#view").innerHTML = markup;
    }, controls("0 of 2 moments compared.", "Run instrument check"));
    await page.waitForTimeout(350);
    if ((await page.evaluate(() => window.automaticInstrumentClicks)) !== 1)
      throw Error("The same automatic pass was started twice");

    await page.evaluate((markup) => {
      document.querySelector("#view").innerHTML = markup;
    }, controls("1 of 2 moments compared.", "Continue instrument checks"));
    await page.waitForFunction(() => window.automaticInstrumentClicks === 2);

    const failureMarkup = controls(
      "1 of 2 moments compared.",
      "Try instrument check again",
      '<p class="warning">The instrument check could not finish.</p>',
    );
    await page.evaluate((markup) => {
      document.querySelector("#view").innerHTML = markup;
    }, failureMarkup);
    await page.waitForFunction(() => window.automaticInstrumentClicks === 3);

    await page.evaluate((markup) => {
      document.querySelector("#view").innerHTML = markup;
    }, failureMarkup);
    await page.waitForTimeout(350);
    if ((await page.evaluate(() => window.automaticInstrumentClicks)) !== 3)
      throw Error("An unchanged failed pass retried indefinitely");

    await page.evaluate(() => {
      window.statusMutations = 0;
      new MutationObserver(records => { window.statusMutations += records.length; })
        .observe(document.querySelector("#instruments"), {childList: true, subtree: true, characterData: true});
    });
    await page.waitForTimeout(350);
    if (await page.evaluate(() => window.statusMutations > 2))
      throw Error("Idle automatic status continuously mutates the page");

    async function assertStableStatus(markup, expectedText) {
      await page.evaluate((value) => {
        document.querySelector("#view").innerHTML = value;
      }, markup);
      await page.waitForFunction((text) =>
        document.querySelector(".automaticInstrumentStatus")?.textContent === text,
        expectedText);
      await page.waitForTimeout(100);
      const mutations = await page.evaluate(() => new Promise((resolve) => {
        let count = 0;
        const observer = new MutationObserver((records) => { count += records.length; });
        observer.observe(document.querySelector("#instruments"), {
          childList: true, subtree: true, characterData: true,
        });
        setTimeout(() => { observer.disconnect(); resolve(count); }, 350);
      }));
      if (mutations > 2)
        throw Error(`Status keeps rewriting the DOM: ${expectedText}`);
    }

    // Exhaust the real six-pass bound, then check the terminal control state.
    for (const progress of [2, 3, 4]) {
      await page.evaluate((markup) => {
        document.querySelector("#view").innerHTML = markup;
      }, controls(`${progress} of 6 moments compared.`, "Continue instrument checks"));
      await page.waitForFunction((count) => window.automaticInstrumentClicks === count,
        progress + 2);
    }
    await assertStableStatus(
      controls("5 of 6 moments compared.", "Continue instrument checks"),
      "Automatic Demucs + DTW analysis reached its safe retry limit. Completed evidence is preserved.",
    );
    if (await page.evaluate(() => window.automaticInstrumentClicks !== 6))
      throw Error("Automatic checks exceeded the six-pass bound");

    const noAction = (body) => `<section id="instruments"><h2>Instruments</h2><p class="muted">Checks</p>${body}</section>`;
    for (const [body, expectedText] of [
      ['<p role="status">6 of 6 moments compared.</p><p>Completed results are reused.</p>',
        "Automatic Demucs + DTW analysis is complete. Review the evidence in the relationship table."],
      ['<span class="spinner"></span><button disabled>Instrument check in progress</button>',
        "Automatic Demucs + DTW analysis is running. Results will appear in the relationship table."],
      ['<p>No paired region with original timestamps is available.</p>',
        "Original-track timestamps are needed for automatic instrument checks."],
      ['<p class="warning">The instrument check could not finish.</p>',
        "Automatic Demucs + DTW analysis could not finish. The Sony and timing analysis is still preserved."],
    ]) await assertStableStatus(noAction(body), expectedText);
    console.log("Automatic instrument launch tests passed");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
