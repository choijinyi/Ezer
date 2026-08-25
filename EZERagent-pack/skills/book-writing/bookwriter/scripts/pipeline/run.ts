// run — orchestrator. Runs pipeline stages for a job, respecting gates.
// Usage:
//   node scripts/pipeline/run.ts <job-id> [stage|all] [--polish]
//
// Phase 2 implements: ingest → structure → normalize → typeset → export.
// Phase 3 will add: polish-propose → apply-polish, illustrate.

import { spawn } from "node:child_process";
import * as path from "node:path";
import * as fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { buildJobDir, exists, repoRoot } from "./paths.ts";
import { readState, acquireLock, type Stage } from "./state.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

type StageId =
  | "ingest"
  | "structure"
  | "normalize"
  | "polish-propose"
  | "apply-polish"
  | "illustrate"
  | "typeset"
  | "export";

const STAGE_SCRIPTS: Record<StageId, string> = {
  ingest: "ingest.ts",
  structure: "structure.ts",
  normalize: "normalize.ts",
  "polish-propose": "polish-propose.ts",
  "apply-polish": "apply-polish.ts",
  illustrate: "illustrate.ts",
  typeset: "typeset.ts",
  export: "export.ts",
};

function nextFromStage(currentStage: Stage, polish: boolean): StageId | null {
  switch (currentStage) {
    case "created":
      return "ingest";
    case "ingested":
      return "structure";
    case "structured":
      return "normalize";
    case "normalized":
      return polish ? "polish-propose" : "illustrate";
    case "polish-proposed":
      return "apply-polish";
    case "polished":
      return "illustrate";
    case "illustrated":
      return "typeset";
    case "typeset":
      return "export";
    case "exported":
      return null;
  }
  return null;
}

function runStage(stage: StageId, jobId: string): Promise<number> {
  const script = path.join(__dirname, STAGE_SCRIPTS[stage]);
  return new Promise((resolve) => {
    const child = spawn("node", [script, jobId], {
      stdio: "inherit",
      shell: false,
    });
    child.on("close", (code) => resolve(code ?? -1));
    child.on("error", () => resolve(-1));
  });
}

async function setPolishFlag(jobDir: string): Promise<void> {
  const flagPath = path.join(jobDir, "polish.flag");
  await fs.writeFile(flagPath, new Date().toISOString() + "\n", "utf8");
}

async function readPolishFlag(jobDir: string): Promise<boolean> {
  return exists(path.join(jobDir, "polish.flag"));
}

async function gateStalled(jobDir: string): Promise<{ stalled: boolean; file?: string; count?: number }> {
  const decisions = path.join(jobDir, "decisions.md");
  if (await exists(decisions)) {
    const c = await fs.readFile(decisions, "utf8");
    const matches = c.match(/Decided:\s*<TODO>/g);
    if (matches && matches.length > 0) {
      return { stalled: true, file: "decisions.md", count: matches.length };
    }
  }
  const polish = path.join(jobDir, "polish-proposals.md");
  if (await exists(polish)) {
    const c = await fs.readFile(polish, "utf8");
    const matches = c.match(/Apply:\s*<TODO>/g);
    if (matches && matches.length > 0) {
      return { stalled: true, file: "polish-proposals.md", count: matches.length };
    }
  }
  return { stalled: false };
}

async function checkPhase3Stage(_stage: StageId): Promise<void> {
  // Phase 3 implemented; no stages are stubbed any more.
  void _stage;
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (args.length < 1) {
    process.stderr.write(
      "usage: run.ts <job-id> [ingest|structure|normalize|polish-propose|apply-polish|illustrate|typeset|export|all] [--polish]\n"
    );
    process.exit(1);
  }
  const jobId = args[0]!;
  const polishFlag = args.includes("--polish");
  const stageArg = args.find(
    (a) => a !== jobId && !a.startsWith("--")
  ) as StageId | "all" | undefined;

  const jobDir = await buildJobDir(jobId);
  if (!(await exists(jobDir))) {
    process.stderr.write(`run: job not found: ${jobId}\n`);
    process.exit(1);
  }

  if (polishFlag) {
    await setPolishFlag(jobDir);
  }
  const polish = polishFlag || (await readPolishFlag(jobDir));

  const release = await acquireLock(jobDir);
  let exitCode = 0;
  try {
    if (stageArg && stageArg !== "all") {
      await checkPhase3Stage(stageArg as StageId);
      const code = await runStage(stageArg as StageId, jobId);
      if (code !== 0) {
        exitCode = code;
      }
    } else {
      while (true) {
        const state = await readState(jobDir);
        if (!state.ok) {
          process.stderr.write(
            `run: prior stage left ok=false (stage=${state.stage}). See errors.log.\n`
          );
          exitCode = 1;
          break;
        }
        const next = nextFromStage(state.stage, polish);
        if (!next) {
          console.log(`run: pipeline complete at stage=${state.stage}`);
          break;
        }
        try {
          await checkPhase3Stage(next);
        } catch (e) {
          process.stderr.write(`run: ${(e as Error).message}\n`);
          exitCode = 1;
          break;
        }
        if (state.needsApproval) {
          const g = await gateStalled(jobDir);
          if (g.stalled) {
            process.stderr.write(
              `run: gate blocked at stage=${state.stage}. ${g.count} unanswered in build/${jobId}/${g.file}.\n`
            );
            exitCode = 2;
            break;
          }
        }
        const code = await runStage(next, jobId);
        if (code !== 0) {
          exitCode = code;
          break;
        }
      }
    }
  } finally {
    await release();
  }

  void repoRoot();
  if (exitCode !== 0) process.exit(exitCode);
}

main().catch((e) => {
  process.stderr.write(`run: ${e instanceof Error ? e.message : String(e)}\n`);
  process.exit(1);
});
