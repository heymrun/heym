/* eslint-env node */
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const eslintPackageJsonPath = require.resolve("eslint/package.json");
const eslintPackage = require(eslintPackageJsonPath);
const eslintBinPath = resolve(
  dirname(eslintPackageJsonPath),
  typeof eslintPackage.bin === "string" ? eslintPackage.bin : eslintPackage.bin.eslint,
);

const child = spawn(process.execPath, [eslintBinPath, ...process.argv.slice(2)], {
  stdio: ["inherit", "pipe", "pipe"],
});

child.stdout.on("data", (chunk) => {
  process.stdout.write(chunk);
});

child.stderr.on("data", (chunk) => {
  process.stderr.write(chunk);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }

  process.exit(code ?? 1);
});
