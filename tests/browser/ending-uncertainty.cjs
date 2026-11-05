// Verify visible uncertainty, ordinary confirmation/editing, and separate evidence retention.
const { spawnSync } = require("child_process");
const path = require("path");
for (const scenario of ["accept", "edit", "edit_start", "mixed"]) {
  const env = { ...process.env, LASTRADA_BROWSER_ENDING: scenario };
  delete env.LASTRADA_BROWSER_STEMS;
  delete env.LASTRADA_BROWSER_ANALYSIS;
  const result = spawnSync(process.execPath, [path.join(__dirname, "firebase.cjs")], {
    env, stdio: "inherit",
  });
  if (result.status !== 0) process.exit(result.status || 1);
}
