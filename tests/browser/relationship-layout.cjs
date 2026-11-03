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
const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="stylesheet" href="/style.css">
    <link rel="stylesheet" href="/grouped-timestamps.css">
    <link rel="stylesheet" href="/relationship-evidence.css">
  </head>
  <body>
    <main>
      <section class="groupedUseSummary">
        <h3>Sample relationships</h3>
        <p class="muted">Each row links an original passage to the derivative timestamps that matched it.</p>
        <section class="relationshipEvidenceControls">
          <h2>Stem + DTW evidence</h2>
          <p class="muted">Demucs estimates the stem, then stem-level DTW tests whether it aligns.</p>
          <p>Instrument check queued. Waiting for the analysis worker.</p>
          <button disabled>Instrument check in progress</button>
        </section>
        <div class="tableWrap groupedUseTable">
          <table aria-label="Sample relationships with Demucs stem and DTW evidence">
            <thead><tr>
              <th>Original track</th>
              <th>Derivative track</th>
              <th>Type of sampling</th>
              <th>Matched derivative timestamps</th>
              <th>Demucs stem + DTW</th>
            </tr></thead>
            <tbody>
              <tr>
                <td><span class="timestampChip">2:35.0–2:43.0</span></td>
                <td><strong>12 matched uses</strong><small>Repeated across most of the track</small></td>
                <td><span class="useType repeated">Repeated</span></td>
                <td><div class="timestampChips">
                  <span class="timestampChip">0:30.5–0:31.7</span>
                  <span class="timestampChip">0:35.0–0:43.0</span>
                  <span class="timestampChip">0:42.0–0:51.0</span>
                  <span class="timestampChip">0:47.0–0:56.0</span>
                  <span class="timestampChip">0:54.0–1:02.0</span>
                  <span class="timestampChip">1:07.0–1:16.0</span>
                </div><details class="moreTimestamps"><summary>View 6 more</summary></details></td>
                <td class="relationshipEvidenceCell"><span class="evidenceState">Not checked</span><small>Run the stem + DTW check above.</small><small class="evidenceProgress">0 of 12 eligible matched moments checked · 2 too short · 12 pending</small></td>
              </tr>
              <tr>
                <td><span class="timestampChip">3:05.0–3:11.0</span></td>
                <td><strong>8 matched uses</strong><small>Repeated across most of the track</small></td>
                <td><span class="useType repeated">Repeated</span></td>
                <td><div class="timestampChips"><span class="timestampChip">0:15.0–0:22.0</span><span class="timestampChip">0:21.0–0:28.0</span></div></td>
                <td class="relationshipEvidenceCell"><div class="stemEvidenceList"><div class="stemEvidenceItem"><div><strong>Bass → Bass</strong><span class="dtwResult accepted">Accepted</span></div><small>1.04× duration · 3 moments</small></div></div><small class="evidenceProgress">3 of 8 eligible matched moments checked</small></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>
  </body>
</html>`;

const server = http.createServer((req, res) => {
  if (req.url === "/") {
    res.setHeader("Content-Type", "text/html");
    res.end(html);
    return;
  }
  const file = path.join(root, "web/public", req.url.slice(1));
  if (!file.startsWith(path.join(root, "web/public"))) {
    res.writeHead(403);
    res.end();
    return;
  }
  try {
    res.setHeader("Content-Type", "text/css");
    res.end(fs.readFileSync(file));
  } catch {
    res.writeHead(404);
    res.end();
  }
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
    const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    const desktop = await page.locator(".groupedUseTable").evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      tableWidth: element.querySelector("table").getBoundingClientRect().width,
    }));
    if (desktop.scrollWidth > desktop.clientWidth + 2)
      throw Error(`Desktop relationship table overflows: ${JSON.stringify(desktop)}`);
    const widths = await page.locator(".groupedUseTable thead th").evaluateAll((cells) =>
      cells.map((cell) => cell.getBoundingClientRect().width),
    );
    if (widths.length !== 5 || widths.some((width) => width < 90))
      throw Error(`Desktop columns are too narrow: ${widths.join(", ")}`);

    await page.setViewportSize({ width: 700, height: 1000 });
    const mobile = await page.locator(".groupedUseTable").evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      rowDisplay: getComputedStyle(element.querySelector("tbody tr")).display,
    }));
    if (mobile.scrollWidth > mobile.clientWidth + 2)
      throw Error(`Responsive relationship cards overflow: ${JSON.stringify(mobile)}`);
    if (mobile.rowDisplay !== "block")
      throw Error(`Responsive rows did not switch to cards: ${mobile.rowDisplay}`);

    console.log("Relationship layout tests passed");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
