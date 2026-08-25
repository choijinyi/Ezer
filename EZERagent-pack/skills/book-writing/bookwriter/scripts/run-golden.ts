// run-golden — execute every fixture under tests/golden/ end-to-end and verify expected.json.
// Usage:
//   node scripts/run-golden.ts            # all fixtures
//   node scripts/run-golden.ts <name>     # one fixture

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { spawn } from "node:child_process";
import { repoRoot, exists } from "./pipeline/paths.ts";

type Outcome = { name: string; ok: boolean; failures: string[]; jobId?: string };

function runProc(cmd: string, args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { shell: false });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (c) => (stdout += c.toString()));
    child.stderr?.on("data", (c) => (stderr += c.toString()));
    child.on("close", (code) => resolve({ code: code ?? -1, stdout, stderr }));
    child.on("error", (e) => resolve({ code: -1, stdout: "", stderr: String(e) }));
  });
}

async function loadJson<T>(p: string): Promise<T> {
  return JSON.parse(await fs.readFile(p, "utf8"));
}

async function answerDecisions(jobDir: string): Promise<number> {
  const decisionsPath = path.join(jobDir, "decisions.md");
  if (!(await exists(decisionsPath))) return 0;
  let content = await fs.readFile(decisionsPath, "utf8");
  const before = (content.match(/Decided:\s*<TODO>/g) || []).length;
  if (before === 0) return 0;
  content = content.replace(/Decided:\s*<TODO>/g, "Decided: 1");
  await fs.writeFile(decisionsPath, content, "utf8");
  return before;
}

type Expected = {
  description?: string;
  stages?: {
    ingest?: { meta?: Record<string, unknown> };
    structure?: { needsApproval?: boolean; outline?: { chapterCount?: number } };
    normalize?: { wordCountDelta?: number };
    typeset?: { pagesMin?: number; pagesMax?: number };
    export?: { outputs?: string[] };
  };
};

async function runFixture(name: string, root: string): Promise<Outcome> {
  const fixDir = path.join(root, "tests", "golden", name);
  const manuscriptDir = path.join(fixDir, "manuscript");
  const expectedPath = path.join(fixDir, "expected.json");

  const o: Outcome = { name, ok: true, failures: [] };

  if (!(await exists(manuscriptDir))) {
    o.ok = false;
    o.failures.push("manuscript/ missing");
    return o;
  }
  if (!(await exists(expectedPath))) {
    o.ok = false;
    o.failures.push("expected.json missing");
    return o;
  }
  const expected: Expected = await loadJson(expectedPath);

  // 1. /new with manuscript directory
  const newRes = await runProc("node", [
    path.join(root, "scripts/pipeline/new.ts"),
    manuscriptDir,
  ]);
  if (newRes.code !== 0) {
    o.ok = false;
    o.failures.push(`new failed: ${newRes.stderr.trim()}`);
    return o;
  }
  const jobMatch = newRes.stdout.match(/JOB_ID=(\S+)/);
  if (!jobMatch) {
    o.ok = false;
    o.failures.push("no JOB_ID in new.ts output");
    return o;
  }
  const jobId = jobMatch[1]!;
  o.jobId = jobId;
  const jobDir = path.join(root, "build", jobId);

  // 2. /run — may halt at gate
  let runRes = await runProc("node", [path.join(root, "scripts/pipeline/run.ts"), jobId]);
  if (runRes.code === 2) {
    const answered = await answerDecisions(jobDir);
    if (answered === 0) {
      o.ok = false;
      o.failures.push(`gate halted but no <TODO> tokens to answer`);
      return o;
    }
    runRes = await runProc("node", [path.join(root, "scripts/pipeline/run.ts"), jobId]);
  }
  if (runRes.code !== 0) {
    o.ok = false;
    o.failures.push(`run failed (code ${runRes.code}): ${runRes.stderr.trim()}`);
    return o;
  }

  // 3. Verify state
  const state = await loadJson<{
    stage: string;
    ok: boolean;
    pages?: number;
    needsApproval?: boolean;
  }>(path.join(jobDir, "state.json"));

  if (state.stage !== "exported") {
    o.failures.push(`state.stage=${state.stage} (want exported)`);
  }
  if (!state.ok) {
    o.failures.push(`state.ok=false`);
  }

  // 4. Verify dist files
  const distDir = path.join(root, "dist", jobId);
  if (!(await exists(path.join(distDir, "book.pdf")))) {
    o.failures.push("dist/<job>/book.pdf missing");
  }
  if (!(await exists(path.join(distDir, "manifest.json")))) {
    o.failures.push("dist/<job>/manifest.json missing");
  }

  // 5. Verify ingest meta
  if (expected.stages?.ingest?.meta) {
    const meta = await loadJson<Record<string, unknown>>(path.join(jobDir, "meta.json"));
    for (const [k, want] of Object.entries(expected.stages.ingest.meta)) {
      if (JSON.stringify(meta[k]) !== JSON.stringify(want)) {
        o.failures.push(
          `meta.${k}: ${JSON.stringify(meta[k])} ≠ ${JSON.stringify(want)}`
        );
      }
    }
  }

  // 6. Verify outline structure
  if (expected.stages?.structure?.outline?.chapterCount != null) {
    const outline = await loadJson<{ chapters: unknown[] }>(path.join(jobDir, "outline.json"));
    if (outline.chapters.length !== expected.stages.structure.outline.chapterCount) {
      o.failures.push(
        `outline chapters: ${outline.chapters.length} ≠ ${expected.stages.structure.outline.chapterCount}`
      );
    }
  }

  // 7. Verify pages range
  const minP = expected.stages?.typeset?.pagesMin;
  const maxP = expected.stages?.typeset?.pagesMax;
  if (state.pages != null) {
    if (minP != null && state.pages < minP) {
      o.failures.push(`pages ${state.pages} < min ${minP}`);
    }
    if (maxP != null && state.pages > maxP) {
      o.failures.push(`pages ${state.pages} > max ${maxP}`);
    }
  }

  o.ok = o.failures.length === 0;
  return o;
}

async function main(): Promise<void> {
  const root = await repoRoot();
  const goldenRoot = path.join(root, "tests", "golden");
  if (!(await exists(goldenRoot))) {
    process.stderr.write(`tests/golden/ missing\n`);
    process.exit(1);
  }

  const arg = process.argv[2];
  let names: string[];
  if (arg) {
    names = [arg];
  } else {
    const entries = await fs.readdir(goldenRoot, { withFileTypes: true });
    names = entries
      .filter((e) => e.isDirectory() && !e.name.startsWith("_"))
      .map((e) => e.name);
  }

  if (names.length === 0) {
    console.log("(no fixtures)");
    return;
  }

  const outcomes: Outcome[] = [];
  for (const name of names) {
    process.stdout.write(`golden: ${name} ... `);
    const o = await runFixture(name, root);
    outcomes.push(o);
    if (o.ok) console.log("PASS");
    else console.log("FAIL");
    for (const f of o.failures) console.log(`  - ${f}`);
    if (o.jobId) console.log(`  job=${o.jobId}`);
  }

  const passed = outcomes.filter((o) => o.ok).length;
  console.log(`\n${passed}/${outcomes.length} fixtures passed`);
  process.exit(passed === outcomes.length ? 0 : 1);
}

main().catch((e) => {
  process.stderr.write(`run-golden: ${e instanceof Error ? e.message : String(e)}\n`);
  process.exit(1);
});
