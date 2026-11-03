// Exercise optional checks through document export, with generated evidence and mocked cloud transport.
const { spawnSync } = require("child_process");
const path = require("path");
for (const scenario of [
  "success",
  "short_context",
  "worker_failure",
  "download_failure",
  "quota",
  "no_match",
  "empty",
  "no_source",
  "reset",
]) {
  const env = { ...process.env, LASTRADA_BROWSER_STEMS: scenario };
  delete env.LASTRADA_BROWSER_ANALYSIS;
  delete env.LASTRADA_BROWSER_OUTPUT;
  const result = spawnSync(
    process.execPath,
    [path.join(__dirname, "firebase.cjs")],
    { env, stdio: "inherit" },
  );
  if (result.status !== 0) process.exit(result.status || 1);
}
