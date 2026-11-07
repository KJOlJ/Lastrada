// The production flow no longer launches a separate instrument request from the
// timestamp page. Reuse the focused browser regression that verifies the legacy
// control is hidden, disabled and never clicked after rendering or rerendering.
const { spawnSync } = require("child_process");
const path = require("path");

const result = spawnSync(
  process.execPath,
  [path.join(__dirname, "automatic-instruments.cjs")],
  { env: process.env, stdio: "inherit" },
);
if (result.status !== 0) process.exit(result.status || 1);
