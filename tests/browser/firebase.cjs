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
    requests = 0;
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
      else result = { id, status: job, operation: "analyze" };
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
    const master = p.locator('[data-rights="master"]').first(),
      publishing = p.locator('[data-rights="publishing"]').first();
    await master.locator("[data-times]").selectOption("accept");
    await p.getByRole("button", { name: "Next: Describe the sound →", exact: true }).click();
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
    await p.getByRole("button", { name: "Next: Describe the sound →", exact: true }).click();
    await p.getByText(/accept the suggested times, or edit and confirm/).waitFor();
    await master.locator("[data-times]").selectOption("accept");
    await p
      .getByRole("button", { name: "Next: Describe the sound →", exact: true })
      .click();
    await p
      .getByLabel("What did you take?", { exact: true })
      .fill("A bassline");
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
      await download.saveAs(path.join(process.env.LASTRADA_BROWSER_OUTPUT, "test-reviewed-nature-of-use.html"));
      await p.screenshot({ path: path.join(process.env.LASTRADA_BROWSER_OUTPUT, "download-stage.png"), fullPage: true });
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
    if (errors.length) throw Error(errors.join("; "));
    if (
      !data.analysis.review.corrected.nature_of_use.text.includes("throughout")
    )
      throw Error("Missing narrative");
    console.log(
      "Firebase web browser flow passed: mocked Google sign-in, filename prefill, private-upload contract, timestamps, no-replay skip, sound/placement review, real Python review validation, final document controls. API requests:",
      requests,
    );
  } finally {
    await b.close();
    await new Promise((r) => server.close(r));
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
