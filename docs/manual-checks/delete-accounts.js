// Deletes the accounts a browser check registered, from the local development database.
// After an interrupted run: backend> .venv\Scripts\python -m scripts.delete_check_accounts --all

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

/** True when every one of these accounts was found and deleted. */
module.exports = function deleteAccounts(emails) {
  if (emails.length === 0) return true;
  const backend = path.resolve("backend");
  const python = [".venv/Scripts/python.exe", ".venv/bin/python"]
    .map((file) => path.join(backend, file))
    .find((file) => fs.existsSync(file));
  if (!python) {
    console.log("      backend/.venv not found (run from the repository root)");
    return false;
  }
  const result = spawnSync(python, ["-m", "scripts.delete_check_accounts", ...emails], {
    cwd: backend,
    encoding: "utf8",
  });
  if (result.status !== 0) console.log(`      ${result.stderr || result.stdout || result.error}`);
  return result.status === 0;
};
