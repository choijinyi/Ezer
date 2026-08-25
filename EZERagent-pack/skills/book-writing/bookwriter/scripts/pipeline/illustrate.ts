// illustrate — orchestrate render-figures + build-cover.
// State: normalized | polished | illustrated → illustrated

import { spawn } from "node:child_process";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { buildJobDir, exists } from "./paths.ts";
import { readState, writeState, recordError, type State } from "./state.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function runScript(name: string, jobId: string): Promise<number> {
  return new Promise((resolve) => {
    const child = spawn("node", [path.join(__dirname, name), jobId], {
      stdio: "inherit",
      shell: false,
    });
    child.on("close", (code) => resolve(code ?? -1));
    child.on("error", () => resolve(-1));
  });
}

async function illustrate(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  if (!(await exists(jobDir))) throw new Error(`job not found: ${jobId}`);

  const state = await readState(jobDir);
  const valid: State["stage"][] = ["normalized", "polished", "illustrated"];
  if (!valid.includes(state.stage)) {
    throw new Error(`expected stage ∈ ${valid.join("|")}, got ${state.stage}`);
  }

  const r1 = await runScript("render-figures.ts", jobId);
  if (r1 !== 0) throw new Error(`render-figures exited ${r1}`);

  const r2 = await runScript("build-cover.ts", jobId);
  if (r2 !== 0) throw new Error(`build-cover exited ${r2}`);

  // re-read state because build-cover updated coverSource
  const updated = await readState(jobDir);
  await writeState(jobDir, { ...updated, stage: "illustrated", ok: true });

  console.log(`illustrated: ${jobId}`);
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: illustrate.ts <job-id>\n");
    process.exit(1);
  }
  try {
    await illustrate(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`illustrate: ${msg}\n`);
    try {
      const jobDir = await buildJobDir(jobId);
      if (await exists(jobDir)) {
        await recordError(jobDir, `illustrate: ${msg}`);
        const st = await readState(jobDir).catch(() => null);
        if (st) await writeState(jobDir, { ...st, ok: false, errors: [msg] });
      }
    } catch {}
    process.exit(1);
  }
}

main();
