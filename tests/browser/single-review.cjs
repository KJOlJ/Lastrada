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
const payload = {
  analysis: {
    input: {
      analysis_scope: ["master"],
      original_work: { title: "Source", artist: "Artist" },
      new_work: { title: "Derivative", artist: "Creator" },
    },
    durations: { original: 120, new: 60 },
    review: { status: "pending", corrected: null, reviewer: null, notes: "" },
    stem_evidence: [],
    instrument_occurrences: [],
  },
  suggestions: {
    master: {
      intervals: [
        {
          new_start: 0,
          new_end: 8,
          original_start: 25,
          original_end: 33,
          source: "sampleid",
          status: "candidate",
        },
        {
          new_start: 20,
          new_end: 28,
          original_start: 25,
          original_end: 33,
          source: "sampleid",
          status: "candidate",
        },
        {
          new_start: 40,
          new_end: 48,
          original_start: 25,
          original_end: 33,
          source: "sampleid",
          status: "candidate",
        },
      ],
      placement: { values: {} },
      instruments: {},
    },
  },
  instrument_rows: [
    {
      occurrence_id: "one",
      status: "checked",
      interval: {
        new_start: 0,
        new_end: 8,
        original_start: 25,
        original_end: 33,
      },
      evidence: [
        {
          source_stem: "drums",
          new_song_stem: "drums",
          dtw_result: "accepted",
          duration_ratio: 1,
        },
      ],
    },
  ],
};

(async () => {
  const server = http.createServer((request, response) => {
    if (request.url === "/test") {
      response.setHeader("Content-Type", "text/html");
      response.end(`<!doctype html><html><body>
        <div id="notice" hidden></div>
        <div id="progress"></div>
        <section id="view"><h1>What did you use?</h1></section>
        <script>window.__LASTRADA_FORCE_SINGLE_REVIEW__ = true;</script>
        <script type="module" src="/single-review.js"></script>
        <script type="module" src="/single-review-sync.js"></script>
      </body></html>`);
      return;
    }
    if (request.url === "/api/analyses/test/result") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify(payload));
      return;
    }
    const file = path.join(root, "web/public", request.url.split("?")[0]);
    if (!file.startsWith(path.join(root, "web/public"))) {
      response.writeHead(403);
      response.end();
      return;
    }
    try {
      response.setHeader(
        "Content-Type",
        file.endsWith(".js") ? "text/javascript" : "text/css",
      );
      response.end(fs.readFileSync(file));
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));

  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
    await page.goto(`http://127.0.0.1:${server.address().port}/test`);
    await page.evaluate(() => fetch("/api/analyses/test/result"));
    await page
      .getByRole("heading", { name: "Draft Nature of Use", exact: true })
      .waitFor();
    await page.getByText("40.0%", { exact: true }).waitFor();

    const text = await page.locator("#view").innerText();
    if (!text.includes("40.0%")) throw Error("Coverage statistic missing");
    if (!text.toLowerCase().includes("drums")) throw Error("Matched stem missing");
    if (!text.includes("A short loop repeated in the track"))
      throw Error("Sampling pattern missing");
    if (!text.includes("Recurring chorus-like sections"))
      throw Error("Placement estimate missing");
    if (/publishing|replayed melody/i.test(text))
      throw Error("Removed rights branch leaked into the single review page");
    if ((await page.locator("textarea[data-single-field='narrative']").count()) !== 1)
      throw Error("Editable narrative is missing");
    if ((await page.locator(".singleRelationshipTable tbody tr").count()) !== 1)
      throw Error("Relationship summary table is missing");

    console.log("Single Nature of Use review test passed");
  } finally {
    await browser.close();
    server.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
