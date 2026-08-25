// status — read-only inspection of jobs.
// Usage:
//   node scripts/pipeline/status.ts             # list latest 20 jobs
//   node scripts/pipeline/status.ts <job-id>    # detail of one job

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { buildJobDir, distJobDir, exists, repoRoot } from "./paths.ts";
import { readState } from "./state.ts";

async function listJobs(): Promise<void> {
  const root = await repoRoot();
  const buildRoot = path.join(root, "build");
  if (!(await exists(buildRoot))) {
    console.log("(no jobs)");
    return;
  }
  const entries = await fs.readdir(buildRoot, { withFileTypes: true });
  const jobs: { jobId: string; stage: string; ok: boolean; createdAt: string }[] = [];
  for (const e of entries) {
    if (!e.isDirectory()) continue;
    const stPath = path.join(buildRoot, e.name, "state.json");
    if (!(await exists(stPath))) continue;
    try {
      const st = JSON.parse(await fs.readFile(stPath, "utf8"));
      jobs.push({
        jobId: st.jobId ?? e.name,
        stage: st.stage ?? "?",
        ok: st.ok ?? false,
        createdAt: st.createdAt ?? "",
      });
    } catch {}
  }
  jobs.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  const top = jobs.slice(0, 20);
  if (top.length === 0) {
    console.log("(no jobs)");
    return;
  }
  console.log(`${top.length} job(s):`);
  for (const j of top) {
    const tag = j.ok ? "✓" : "✗";
    console.log(`  [${tag}] ${j.jobId}  stage=${j.stage}`);
  }
}

async function detail(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  if (!(await exists(jobDir))) {
    console.log(`job not found: ${jobId}`);
    process.exit(1);
  }
  const state = await readState(jobDir);
  console.log(`job ${jobId}`);
  console.log(`  stage: ${state.stage}  ok=${state.ok}  needsApproval=${state.needsApproval}`);
  console.log(`  manuscript: ${state.manuscript}`);
  console.log(`  template: ${state.template}, outputs: ${state.outputs.join(",")}`);
  console.log(`  polish: ${state.polish}`);
  if (state.pages != null) console.log(`  pages: ${state.pages}`);
  if (state.applied != null) console.log(`  applied: ${state.applied}, skipped: ${state.skipped ?? 0}`);
  if (state.coverSource) console.log(`  cover: ${state.coverSource}`);
  if (state.errors?.length) {
    console.log(`  errors:`);
    for (const e of state.errors) console.log(`    - ${e}`);
  }

  const errLog = path.join(jobDir, "errors.log");
  if (await exists(errLog)) {
    const c = await fs.readFile(errLog, "utf8");
    if (c.trim()) {
      console.log(`  errors.log:`);
      for (const ln of c.split("\n").filter(Boolean)) console.log(`    ${ln}`);
    }
  }

  const decisions = path.join(jobDir, "decisions.md");
  if (await exists(decisions)) {
    const c = await fs.readFile(decisions, "utf8");
    const todos = (c.match(/Decided:\s*<TODO>/g) || []).length;
    if (todos > 0) console.log(`  decisions.md: ${todos} unanswered question(s)`);
  }
  const polish = path.join(jobDir, "polish-proposals.md");
  if (await exists(polish)) {
    const c = await fs.readFile(polish, "utf8");
    const todos = (c.match(/Apply:\s*<TODO>/g) || []).length;
    if (todos > 0) console.log(`  polish-proposals.md: ${todos} unanswered`);
  }

  const dist = await distJobDir(jobId);
  if (await exists(dist)) {
    const files = await fs.readdir(dist);
    console.log(`  dist/${jobId}/: ${files.length} file(s) [${files.join(", ")}]`);
  }
}

async function main(): Promise<void> {
  const arg = process.argv[2];
  if (!arg) await listJobs();
  else await detail(arg);
}

main().catch((e) => {
  process.stderr.write(`status: ${e instanceof Error ? e.message : String(e)}\n`);
  process.exit(1);
});
