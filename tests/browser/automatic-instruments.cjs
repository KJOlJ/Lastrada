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
    <section id="view">${controls("0 of 2 moments compared.", "Run instrument check")}</section>
    <script>
      window.__LASTRADA_FORCE_AUTO_INSTRUMENTS__ = true;
      window.automaticInstrumentClicks = 0;
      document.addEventListener("click", (event) => {
        if (event.target.closest('button[data-action="stems"]'))
          window.automaticInstrumentClicks += 1;
      });
    </script>
    <script type="module" src="/auto-instruments.js"></script>
  </body>
</html>`;

const server = http.createServer((request, response) => {
  if (request.url === "/") {
    response.setHeader("Content-Type", "text/html");
    response.end(html);
    return;
  }
  if (request.url === "/auto-instruments.js") {
    response.setHeader("Content-Type", "text/javascript");
    response.end(fs.readFileSync(path.join(root, "web/public/auto-instruments.js")));
    return;
  }
  response.writeHead(404);
  response.end();
});

(async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
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

    console.log("Automatic instrument launch tests passed");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
