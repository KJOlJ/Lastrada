const fs = require("fs"),
  path = require("path"),
  http = require("http"),
  { spawnSync } = require("child_process");
let chromium;
try {
  ({ chromium } = require("../../web/node_modules/playwright"));
} catch {
  ({ chromium } = require("/opt/codex/cua_node/lib/node_modules/playwright"));
}
const root = path.resolve(__dirname, "../.."),
  fixture = (mode) =>
    spawnSync(
      process.env.PYTHON || "python",
      [path.join(__dirname, "fixture.py"), mode],
      { cwd: root, encoding: "utf8" },
    );
function python(mode, body) {
  const p = spawnSync(
    process.env.PYTHON || "python",
    [path.join(__dirname, "fixture.py"), mode],
    { cwd: root, input: JSON.stringify(body), encoding: "utf8" },
  );
  if (p.status !== 0) throw Error(p.stderr);
  return p.stdout;
}
(async () => {
  let data = JSON.parse(fixture("initial").stdout),
    job = "uploading",
    approved = false,
    requests = 0,
    instrumentRequests = 0,
    instrumentPolls = 0,
    operation = "analyze",
    jobError = null;
  const instrumentScenario = process.env.LASTRADA_BROWSER_STEMS;
  const endingScenario = process.env.LASTRADA_BROWSER_ENDING;
  if (instrumentScenario && instrumentScenario !== "no_source") {
    const interval = {
      new_start: 1,
      new_end: 4,
      original_start: 2,
      original_end: 5,
      source: "sampleid_rank_sequence",
      status: "candidate",
    };
    if (instrumentScenario === "short_context") {
      interval.new_end = 1.4;
      interval.original_end = 2.4;
    }
    data.analysis.master.locate.sample_occurrences = [interval];
    data.suggestions.master.intervals = [interval];
    data.instrument_rows = [
      {
        occurrence_id: "test-row",
        candidate_number: 1,
        interval: { ...interval },
        status: "pending",
        reason: "Not checked",
        evidence: [],
        suggested_instruments: [],
      },
    ];
    if (instrumentScenario === "success") {
      const second = {
        ...interval,
        new_start: 6,
        new_end: 9,
        original_start: 10,
        original_end: 13,
      };
      data.analysis.master.locate.sample_occurrences.push(second);
      data.suggestions.master.intervals = [
        ...data.analysis.master.locate.sample_occurrences,
      ];
      data.instrument_rows.push({
        ...data.instrument_rows[0],
        occurrence_id: "second-row",
        candidate_number: 2,
        interval: second,
      });
    }
  }
  const server = http.createServer((req, res) => {
    const file = path.join(
      root,
      "web/public",
      req.url === "/" ? "index.html" : req.url.split("?")[0],
    );
    if (!file.startsWith(path.join(root, "web/public"))) {
      res.writeHead(403);
      res.end();
      return;
    }
    try {
      res.setHeader(
        "Content-Type",
        file.endsWith(".js")
          ? "text/javascript"
          : file.endsWith(".css")
            ? "text/css"
            : "text/html",
      );
      res.end(fs.readFileSync(file));
    } catch {
      res.writeHead(404);
      res.end();
    }
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const b = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : {}),
    args: ["--no-sandbox"],
  });
  try {
    const p = await b.newPage({ viewport: { width: 1360, height: 1000 } });
    const errors = [];
    p.on("pageerror", (e) => errors.push(e.message));
    await p.route(
      "https://www.gstatic.com/firebasejs/**/firebase-app.js",
      (route) =>
        route.fulfill({
          contentType: "text/javascript",
          body: "export const initializeApp = config => config;",
        }),
    );
    await p.route(
      "https://www.gstatic.com/firebasejs/**/firebase-auth.js",
      (route) =>
        route.fulfill({
          contentType: "text/javascript",
          body: `let listener; const user={uid:'test',displayName:'Test Creator',getIdToken:async()=>'test-token'};export const getAuth=()=>({});export class GoogleAuthProvider{};export const onAuthStateChanged=(auth,callback)=>{listener=callback;setTimeout(()=>callback(sessionStorage.getItem('testGoogle')?user:null),0);};export const signInWithPopup=async()=>{sessionStorage.setItem('testGoogle','yes');listener(user);};export const signOut=async()=>listener(null);`,
        }),
    );
    await p.route("**/config.json", (route) =>
      route.fulfill({
        json: {
          firebase: { projectId: "lastrada-64bab" },
          apiBase: "https://api.lastrada.test",
          build: {
            branch: "local/stem-fast",
            commit: "a".repeat(40),
            profile: "stem-fast",
          },
        },
      }),
    );
    await p.route("https://upload.lastrada.test/**", (route) =>
      route.fulfill({
        status: 200,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "*",
          "Access-Control-Allow-Methods": "PUT, OPTIONS",
        },
      }),
    );
    await p.route("https://api.lastrada.test/**", async (route) => {
      requests++;
      const req = route.request(),
        u = new URL(req.url()),
        headers = {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "*",
          "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
        };
      if (req.method() === "OPTIONS")
        return route.fulfill({ status: 204, headers });
      let result = {},
        status = 200;
      const id = data.analysis.case_id;
      if (req.method() === "POST" && u.pathname === "/api/analyses") {
        result = {
          id,
          uploads: {
            original: "https://upload.lastrada.test/original",
            new: "https://upload.lastrada.test/new",
          },
        };
      } else if (u.pathname.endsWith("/run")) {
        job = "completed";
        result = { status: job };
      } else if (u.pathname.endsWith("/stems")) {
        instrumentRequests++;
        await new Promise((resolve) => setTimeout(resolve, 700));
        if (instrumentScenario === "quota") {
          status = 400;
          result = {
            detail:
              "Today's analysis limit has been reached. Try again tomorrow.",
          };
        } else {
          if (instrumentRequests > 1 && instrumentScenario === "success") {
            const reviewedTimes =
              data.analysis.review.corrected?.master?.locate.sample_occurrences;
            if (reviewedTimes?.[0]?.new_start !== 2)
              throw Error(
                "Instrument request did not save the edited timestamps first",
              );
            data.instrument_rows = reviewedTimes.map((interval, index) => ({
              ...data.instrument_rows[index],
              interval,
              status: index === 0 ? "pending" : "checked",
              suggested_instruments: index === 0 ? [] : ["Drums"],
            }));
          }
          instrumentPolls = 0;
          operation = "stems";
          job = "queued";
          result = { status: job, operation };
        }
      } else if (u.pathname.endsWith("/result")) result = data;
      else if (u.pathname.endsWith("/review")) {
        try {
          data.analysis = JSON.parse(
            python("review", {
              analysis: data.analysis,
              payload: req.postDataJSON(),
            }),
          );
          approved = data.analysis.review.status === "approved";
          result = { analysis: data.analysis };
        } catch (e) {
          status = 400;
          result = { detail: e.message };
        }
      } else if (u.pathname.includes("/export/")) {
        if (!approved) {
          status = 409;
          result = { detail: "Review required" };
        } else
          return route.fulfill({
            headers,
            body: python(u.pathname.endsWith("/html") ? "html" : "text", {
              analysis: data.analysis,
            }),
            contentType: "text/plain",
          });
      } else if (u.pathname.includes("/audio/"))
        return route.fulfill({
          headers,
          body: Buffer.alloc(44),
          contentType: "audio/wav",
        });
      else {
        if (operation === "stems" && job !== "completed") {
          instrumentPolls++;
          if (instrumentPolls === 1) job = "queued";
          else if (instrumentPolls === 2) job = "running";
          else {
            job = "completed";
            if (instrumentScenario === "worker_failure")
              jobError =
                "The optional instrument check could not finish. Your main analysis is preserved.";
            else if (instrumentScenario === "download_failure")
              data.analysis.methods.stems =
                "unavailable: model download failed with 403";
            else if (instrumentScenario !== "empty")
              data.analysis.stem_evidence = [
                {
                  candidate_number: 1,
                  source_stem: "bass",
                  new_song_stem: "bass",
                  dtw_result:
                    instrumentScenario === "no_match" ? "rejected" : "accepted",
                  interpretation: "Test evidence",
                  reason: "Generated browser fixture",
                },
              ];
            if (
              !["worker_failure", "download_failure", "empty"].includes(
                instrumentScenario,
              )
            ) {
              data.instrument_rows[0].status = "checked";
              data.instrument_rows[0].suggested_instruments =
                instrumentScenario === "no_match" ? [] : ["Bass"];
              data.instrument_rows[0].evidence = data.analysis.stem_evidence;
              data.instrument_rows[0].probe = {
                ...data.instrument_rows[0].interval,
              };
              if (instrumentScenario === "success") {
                data.instrument_rows[1] = {
                  ...data.instrument_rows[1],
                  status: "checked",
                  suggested_instruments: ["Drums"],
                  evidence: [],
                  probe: { ...data.instrument_rows[1].interval },
                };
              }
              if (instrumentScenario === "short_context") {
                const row = data.instrument_rows[0];
                row.context_only = true;
                row.suggested_instruments = [];
                row.source_sounds = [{ instrument: "Bass", energy_share: 0.7, scope: "sample", start: 2, end: 2.4 }];
                row.new_sounds = [{ instrument: "Drums", energy_share: 0.8, scope: "sample", start: 1, end: 1.4 }];
              }
              data.analysis.instrument_occurrences = data.instrument_rows;
            }
          }
        }
        result = { id, status: job, operation, error: jobError };
      }
      return route.fulfill({ status, headers, json: result });
    });
    await p.goto(`http://127.0.0.1:${server.address().port}`);
    await p.getByRole("button", { name: "Start", exact: true }).click();
    await p
      .getByLabel("Audio file")
      .nth(0)
      .setInputFiles({
        name: "Source by Artist.wav",
        mimeType: "audio/wav",
        buffer: Buffer.alloc(100),
      });
    await p
      .getByLabel("Audio file")
      .nth(1)
      .setInputFiles({
        name: "New by Artist.wav",
        mimeType: "audio/wav",
        buffer: Buffer.alloc(100),
      });
    if (
      (await p.locator('[data-field="original_title"]').inputValue()) !==
      "Source"
    )
      throw Error("Credits not prefilled");
    await p
      .getByRole("button", { name: "Find my sample →", exact: true })
      .click();
    await p
      .getByRole("heading", { name: "Listen & check.", exact: true })
      .waitFor();
    if (
      !(await p.locator("#buildVersion").textContent()).includes(
        "local/stem-fast · aaaaaaaaaaaa · stem-fast",
      )
    )
      throw Error("Missing branch and commit identification");
    if (data.loop_families?.length) {
      await p.locator("#loopGroups summary").click();
      const groups = p
        .getByRole("table", { name: "Repeated passage groups" })
        .locator("tbody tr");
      if ((await groups.count()) !== data.loop_families.length)
        throw Error("Missing repeated-passage groups");
    }
    const master = p.locator('[data-rights="master"]').first(),
      publishing = p.locator('[data-rights="publishing"]').first();
    if (endingScenario) {
      const cue = master.locator("[data-ending-review-summary]");
      await cue.waitFor({ state: "visible" });
      if (!(await cue.textContent()).includes("0:03.00 in your track and 0:04.00"))
        throw Error("Ending review extent missing from visible grouped table");
      if (!(await master.locator(".groupedUseTable").textContent()).includes("≈ 0:02.5"))
        throw Error("Grouped ending should be approximate without losing its numeric value");
      if (!(await master.locator(".groupedUseTable").textContent()).includes("≈ 0:03.5"))
        throw Error("Original ending lost its uncertainty cue");
      if ((await master.locator(".groupedUseTable tbody tr").count()) !== 1)
        throw Error("Ending cue changed sample grouping");
      if (process.env.LASTRADA_BROWSER_OUTPUT) {
        fs.mkdirSync(process.env.LASTRADA_BROWSER_OUTPUT, { recursive: true });
        await p.screenshot({ path: path.join(process.env.LASTRADA_BROWSER_OUTPUT, "ending-review.png"), fullPage: true });
      }
      if (endingScenario === "edit") {
        await master.locator("[data-times]").selectOption("edit");
        await master.locator('[data-interval="0:new_end"]').fill("2.6");
        if (await master.locator("[data-ending-review]").count())
          throw Error("Edited times retained a stale automated ending cue");
      }
    }
    await master.locator("[data-times]").selectOption("accept");
    if (endingScenario && await master.locator("[data-ending-review]").count())
      throw Error("Existing confirmation did not resolve the ending cue");
    await p
      .getByRole("button", { name: "Next: Describe the sound →", exact: true })
      .click();
    await p.getByText(/Replayed music: choose Yes only/).waitFor();
    const alertBox = await p.locator("#notice").boundingBox();
    if (!alertBox || alertBox.y < 0 || alertBox.y >= 1000)
      throw Error("Blocking guidance is off screen");
    // A change-only select event must persist its value, independent of input events.
    await publishing.locator('[data-field="status"]').evaluate((el) => {
      el.value = "no_use";
      el.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await master.locator("[data-times]").selectOption("pending");
    await p
      .getByRole("button", { name: "Next: Describe the sound →", exact: true })
      .click();
    await p
      .getByText(/accept the suggested times, or edit and confirm/)
      .waitFor();
    await master.locator("[data-times]").selectOption("accept");
    if (instrumentScenario === "no_source") {
      if (
        !(await p
          .getByRole("button", {
            name: "Instrument check unavailable",
            exact: true,
          })
          .isDisabled())
      )
        throw Error(
          "Missing source times should explain why instruments cannot run",
        );
      await p.getByText(/No paired region with original timestamps/).waitFor();
    } else if (instrumentScenario) {
      await p
        .getByRole("button", { name: "Run instrument check", exact: true })
        .click();
      await p
        .getByText("Starting the instrument check…", { exact: true })
        .waitFor();
      if (
        !(await p
          .getByRole("button", {
            name: "Instrument check in progress",
            exact: true,
          })
          .isDisabled())
      )
        throw Error("Instrument button allows duplicate requests");
      if (instrumentScenario === "reset") {
        await p.locator("#newSample").click();
        await new Promise((resolve) => setTimeout(resolve, 1000));
        await p
          .getByRole("heading", { name: "Start with the music.", exact: true })
          .waitFor();
        if (
          await p
            .getByRole("table", { name: "Instrument comparison results" })
            .count()
        )
          throw Error("Old result leaked into new sample");
        console.log("Instrument reset test passed");
        return;
      }
      if (instrumentScenario === "quota")
        await p.getByText(/Today's analysis limit/).waitFor();
      else {
        await p.getByText(/Instrument check queued/).waitFor();
        await p.getByText(/Comparing the instruments/).waitFor();
        if (instrumentScenario === "worker_failure")
          await p.getByText(/Your main analysis is preserved/).waitFor();
        else if (instrumentScenario === "download_failure")
          await p.getByText(/The instrument check could not finish/).waitFor();
        else if (instrumentScenario === "empty")
          await p.getByText(/Some moments still need a check/).waitFor();
        else {
          await p
            .getByRole("table", { name: "Instrument comparison results" })
            .waitFor();
          await p
            .getByText(
              instrumentScenario === "short_context"
                ? "Context only; reuse unconfirmed"
                : instrumentScenario === "no_match"
                ? "No supporting match"
                : "Possible supporting match",
              { exact: true },
            )
            .first()
            .waitFor();
          if (instrumentScenario === "short_context") {
            const presence = p.locator("[data-stem-dtw-evidence] .instrumentPresence");
            await presence.locator("summary").click();
            const text = await presence.innerText();
            if (!text.includes("Original: Bass") || !text.includes("New mix: Drums"))
              throw Error("Short-clip source and new-mix estimates were lost or conflated");
            if (await p.locator("[data-stem-dtw-evidence] .dtwResult.accepted").count())
              throw Error("Context-only match shown as support for the tiny interval");
          }
          if (instrumentScenario === "success") {
            const rows = p
              .getByRole("table", { name: "Instrument comparison results" })
              .locator("tbody tr");
            if (
              !(await rows.nth(0).innerText()).includes("Bass") ||
              (await rows.nth(0).innerText()).includes("Drums")
            )
              throw Error("First moment inherited another instrument");
            if (!(await rows.nth(1).innerText()).includes("Drums"))
              throw Error("Second moment instrument missing");
          }
          if (
            await p
              .getByRole("button", {
                name: "Run instrument check",
                exact: true,
              })
              .count()
          )
            throw Error("Completed check can be rerun");
        }
      }
      if (instrumentRequests !== 1) throw Error("Instrument request count");
      if (
        (await publishing.locator('[data-field="status"]').inputValue()) !==
          "no_use" ||
        (await master.locator("[data-times]").inputValue()) !== "accept"
      )
        throw Error("Instrument check lost review inputs");
    }
    if (instrumentScenario === "success") {
      await master.locator("[data-times]").selectOption("edit");
      await master.locator('[data-interval="0:new_start"]').fill("2");
      if (
        !(
          await master.locator('[data-instrument-index="0"]').innerText()
        ).includes("Not checked")
      )
        throw Error("Edited timestamp retained stale instrument label");
      await master
        .getByLabel("I’ve listened and confirmed these times", { exact: true })
        .check();
      await p
        .getByRole("button", {
          name: "Next: Describe the sound →",
          exact: true,
        })
        .click();
      if (
        (await p
          .getByLabel("What did you take?", { exact: true })
          .inputValue()) !== "Drums"
      )
        throw Error("Edited timestamp retained stale sound prefill");
      await p.getByRole("button", { name: "← Back", exact: true }).click();
      await p
        .getByRole("button", {
          name: "Continue instrument checks",
          exact: true,
        })
        .click();
      await p
        .getByText("Completed results are reused.", { exact: true })
        .waitFor();
      if (instrumentRequests !== 2)
        throw Error("Edited moment was not rechecked");
      if (
        !(
          await master.locator('[data-instrument-index="0"]').innerText()
        ).includes("Bass")
      )
        throw Error(
          "Rechecked moment did not restore its own instrument result",
        );
    }
    if (process.env.LASTRADA_BROWSER_OUTPUT) {
      fs.mkdirSync(process.env.LASTRADA_BROWSER_OUTPUT, { recursive: true });
      const presence = p.locator("[data-stem-dtw-evidence] .instrumentPresence").first();
      if (data.instrument_rows?.some(row => row.status === "checked" && row.source_sounds?.length))
        await presence.waitFor();
      if (await presence.count()) {
        await presence.locator("summary").click();
        await master.screenshot({ path: path.join(process.env.LASTRADA_BROWSER_OUTPUT, "source-and-new-instruments.png") });
      }
      await p.locator("#instruments").screenshot({
        path: path.join(
          process.env.LASTRADA_BROWSER_OUTPUT,
          "instruments-by-moment.png",
        ),
      });
    }
    await p
      .getByRole("button", { name: "Next: Describe the sound →", exact: true })
      .click();
    if (instrumentScenario === "success") {
      if (
        (await p
          .getByLabel("What did you take?", { exact: true })
          .inputValue()) !== "Bass, Drums"
      )
        throw Error("Timestamp instruments did not prefill the sound");
    }
    if (instrumentScenario === "short_context" && await p.getByLabel("What did you take?", { exact: true }).inputValue())
      throw Error("Context-only evidence must not prefill a sampled instrument");
    await p
      .getByLabel("What did you take?", { exact: true })
      .fill("A bassline");
    await p.getByRole("button", { name: "← Back", exact: true }).click();
    await p
      .getByRole("button", { name: "Next: Describe the sound →", exact: true })
      .click();
    if (
      (await p
        .getByLabel("What did you take?", { exact: true })
        .inputValue()) !== "A bassline"
    )
      throw Error("User sound edit was overwritten");
    if (instrumentScenario === "success") {
      await p.getByLabel("What did you take?", { exact: true }).fill("");
      await p.getByRole("button", { name: "← Back", exact: true }).click();
      await p
        .getByRole("button", {
          name: "Next: Describe the sound →",
          exact: true,
        })
        .click();
      if (
        (await p
          .getByLabel("What did you take?", { exact: true })
          .inputValue()) !== ""
      )
        throw Error("Intentionally cleared description was replaced");
      await p
        .getByLabel("What did you take?", { exact: true })
        .fill("A bassline");
    }
    await p
      .getByLabel("What does it do in your track?", { exact: true })
      .fill("Main hook");
    await p
      .getByRole("button", { name: "Next: Place the sample →", exact: true })
      .click();
    await p.getByLabel("whole track", { exact: true }).check();
    await p
      .getByLabel("I’ve listened and checked these details", { exact: true })
      .check();
    await p
      .getByRole("button", { name: "Next: Review your draft →", exact: true })
      .click();
    await p
      .getByRole("button", { name: "Mark document as reviewed", exact: true })
      .waitFor();
    await p
      .getByRole("button", { name: "Mark document as reviewed", exact: true })
      .click();
    await p
      .getByText("Reviewed and ready to download.", { exact: true })
      .first()
      .waitFor();
    await p
      .getByRole("button", { name: "Next: Your Nature of Use →", exact: true })
      .click();
    await p
      .getByRole("button", { name: "Download HTML", exact: true })
      .waitFor();
    const downloadReady = p.waitForEvent("download");
    await p.getByRole("button", { name: "Download HTML", exact: true }).click();
    const download = await downloadReady;
    if (process.env.LASTRADA_BROWSER_OUTPUT) {
      fs.mkdirSync(process.env.LASTRADA_BROWSER_OUTPUT, { recursive: true });
      await download.saveAs(
        path.join(
          process.env.LASTRADA_BROWSER_OUTPUT,
          "test-reviewed-nature-of-use.html",
        ),
      );
      await p.screenshot({
        path: path.join(
          process.env.LASTRADA_BROWSER_OUTPUT,
          "download-stage.png",
        ),
        fullPage: true,
      });
    }
    if (download.suggestedFilename() !== "nature-of-use.html")
      throw Error("Download name");
    if (
      !fs.readFileSync(await download.path(), "utf8").includes("NATURE OF USE")
    )
      throw Error("Missing exported document");
    await p.reload();
    await p
      .getByRole("heading", { name: "Listen & check.", exact: true })
      .waitFor();
    if (!approved) throw Error("Backend review was not approved");
    if (endingScenario) {
      if (!data.analysis.master.locate.sample_occurrences[0].end_review)
        throw Error("Review erased automated ending uncertainty from saved evidence");
      const corrected = data.analysis.review.corrected.master.locate.sample_occurrences[0];
      if (corrected.end_review)
        throw Error("Confirmed times retained an unresolved automated cue");
      if (corrected.new_end !== (endingScenario === "edit" ? 2.6 : 2.5))
        throw Error("Ending cue overwrote the reviewer's chosen time");
    }
    if (errors.length) throw Error(errors.join("; "));
    if (
      !data.analysis.review.corrected.nature_of_use.text.includes("throughout")
    )
      throw Error("Missing narrative");
    console.log(
      "Firebase web browser flow passed: mocked Google sign-in, filename prefill, private-upload contract, timestamps, no-replay skip, sound/placement review, real Python review validation, final document controls. API requests:",
      requests,
      instrumentScenario || endingScenario || "base",
    );
  } finally {
    await b.close();
    await new Promise((r) => server.close(r));
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
