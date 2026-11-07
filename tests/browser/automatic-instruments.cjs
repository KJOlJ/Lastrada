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
const controls = () => `
  <section id="instruments">
    <h2>Instruments at each moment</h2>
    <p class="muted">Estimate stems for each matched moment.</p>
    <p role="status">0 of 2 moments compared.</p>
    <button data-action="stems">Run instrument check</button>
  </section>`;
const html = `<!doctype html>
<html>
  <head><meta charset="utf-8"></head>
  <body>
    <section id="view">${controls()}</section>
    <script>
      window.instrumentClicks = 0;
      document.addEventListener("click", (event) => {
        if (event.target.closest('button[data-action="stems"]'))
          window.instrumentClicks += 1;
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
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : {}),
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(
      () => document.querySelector("#instruments")?.hidden === true,
    );
    await page.waitForTimeout(200);

    if ((await page.evaluate(() => window.instrumentClicks)) !== 0)
      throw Error("The browser launched a post-page-load stem job");

    const button = page.locator('button[data-action="stems"]');
    if (!(await button.isHidden()))
      throw Error("The legacy manual instrument action is still visible");
    if (!(await button.isDisabled()))
      throw Error("The legacy manual instrument action is still enabled");

    const integrated = await page
      .locator("#instruments")
      .getAttribute("data-integrated-stem-pipeline");
    if (integrated !== "true")
      throw Error("The controls were not marked as part of the integrated pipeline");

    await page.evaluate((markup) => {
      document.querySelector("#view").innerHTML = markup;
    }, controls());
    await page.waitForFunction(
      () => document.querySelector("#instruments")?.hidden === true,
    );
    await page.waitForTimeout(200);
    if ((await page.evaluate(() => window.instrumentClicks)) !== 0)
      throw Error("A DOM refresh launched a stem job");

    console.log("Integrated stem flow browser test passed");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
