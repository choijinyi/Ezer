// apply-polish — apply user-confirmed polish proposals.
// Reads:   build/<job>/polish-proposals.md (Apply: y/n), polish-proposals.json
// Writes:  build/<job>/edited/*.md (overwrites; backup → edited.pre-polish/)
//          build/<job>/changelog.md, apply.log
// State:   polish-proposed → polished

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { buildJobDir, ensureDir, exists } from "./paths.ts";
import { readState, writeState, recordError, type State } from "./state.ts";

type Proposal = {
  line: number;
  before: string;
  after: string;
  category: string;
  reason: string;
};

type ChapterProposals = {
  file: string;
  proposals: Proposal[];
  llmError?: string;
};

type ProposalsJson = { jobId: string; proposals: ChapterProposals[] };

// Parse polish-proposals.md to extract Apply answers, indexed by global P-number.
function parseApplyAnswers(md: string): Map<number, "y" | "n" | "todo"> {
  const out = new Map<number, "y" | "n" | "todo">();
  const re = /^### P(\d+) — .*?$/gm;
  const indices: { num: number; index: number }[] = [];
  let m;
  while ((m = re.exec(md))) {
    indices.push({ num: parseInt(m[1]!, 10), index: m.index });
  }
  // For each block, find the next `- Apply: ...`
  for (let i = 0; i < indices.length; i++) {
    const start = indices[i]!.index;
    const end = i + 1 < indices.length ? indices[i + 1]!.index : md.length;
    const block = md.slice(start, end);
    const am = block.match(/^- Apply:\s*(.+?)\s*$/m);
    let val: "y" | "n" | "todo" = "todo";
    if (am) {
      const v = am[1]!.toLowerCase();
      if (v === "<todo>") val = "todo";
      else if (v === "y" || v === "yes") val = "y";
      else if (v === "n" || v === "no") val = "n";
      else val = "n"; // anything else = skip safely
    }
    out.set(indices[i]!.num, val);
  }
  return out;
}

async function applyPolish(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  const state = await readState(jobDir);
  if (state.stage !== "polish-proposed" && state.stage !== "polished") {
    throw new Error(`expected stage=polish-proposed, got ${state.stage}`);
  }

  const mdPath = path.join(jobDir, "polish-proposals.md");
  const jsonPath = path.join(jobDir, "polish-proposals.json");
  if (!(await exists(mdPath)) || !(await exists(jsonPath))) {
    throw new Error("polish-proposals.{md,json} missing — run polish-propose first");
  }

  const md = await fs.readFile(mdPath, "utf8");
  if (/^- Apply:\s*<TODO>\s*$/m.test(md)) {
    process.stderr.write(`apply-polish: polish-proposals.md still has unanswered 'Apply: <TODO>'\n`);
    process.exit(2);
  }

  const json: ProposalsJson = JSON.parse(await fs.readFile(jsonPath, "utf8"));
  const answers = parseApplyAnswers(md);

  // Re-build flat list with global P-numbers (matching propose render order)
  type FlatProposal = Proposal & { chapter: string; pNum: number };
  const flat: FlatProposal[] = [];
  let pNum = 0;
  for (const cp of json.proposals) {
    for (const p of cp.proposals) {
      pNum++;
      flat.push({ ...p, chapter: cp.file, pNum });
    }
  }

  // Backup edited/ → edited.pre-polish/
  const editedDir = path.join(jobDir, "edited");
  const backupDir = path.join(jobDir, "edited.pre-polish");
  if (!(await exists(backupDir))) {
    await ensureDir(backupDir);
    const files = await fs.readdir(editedDir);
    for (const f of files) {
      await fs.copyFile(path.join(editedDir, f), path.join(backupDir, f));
    }
  }

  let applied = 0;
  let skipped = 0;
  const applyLog: string[] = [];
  const changelog: string[] = [`# Edit log for ${jobId}`, `Mode: polished`, ``];

  // Group by chapter, sort by line desc per chapter (TI-6)
  const byChapter = new Map<string, FlatProposal[]>();
  for (const p of flat) {
    if (!byChapter.has(p.chapter)) byChapter.set(p.chapter, []);
    byChapter.get(p.chapter)!.push(p);
  }
  for (const [chapter, props] of byChapter) {
    props.sort((a, b) => b.line - a.line);

    const filePath = path.join(editedDir, chapter);
    let text = await fs.readFile(filePath, "utf8");
    const beforeWords = wordCount(text);

    changelog.push(`## ${chapter}`);

    for (const p of props) {
      const ans = answers.get(p.pNum) ?? "n";
      if (ans !== "y") {
        skipped++;
        applyLog.push(`P${p.pNum} ${chapter} L${p.line}: skipped (Apply=${ans})`);
        continue;
      }

      // Defensive: heading line check on current text
      const lines = text.split("\n");
      const targetIdx = p.line - 1;
      const targetLn = lines[targetIdx];
      if (targetLn == null || /^#{1,6}\s/.test(targetLn)) {
        skipped++;
        applyLog.push(`P${p.pNum} ${chapter} L${p.line}: refused (heading or out-of-range)`);
        continue;
      }

      // Try in-place line replacement first
      if (targetLn.includes(p.before)) {
        lines[targetIdx] = targetLn.replace(p.before, p.after);
        text = lines.join("\n");
        applied++;
        changelog.push(
          `- L${p.line} (${p.category}): ${JSON.stringify(p.before)} → ${JSON.stringify(p.after)} (${p.reason})`
        );
      } else if (text.includes(p.before)) {
        // Line shifted but text still present somewhere
        text = text.replace(p.before, p.after);
        applied++;
        applyLog.push(
          `P${p.pNum} ${chapter}: applied at non-original line (text matched somewhere)`
        );
        changelog.push(
          `- L${p.line}? (${p.category}): ${JSON.stringify(p.before)} → ${JSON.stringify(p.after)}`
        );
      } else {
        skipped++;
        applyLog.push(`P${p.pNum} ${chapter} L${p.line}: 'before' not found`);
      }
    }

    await fs.writeFile(filePath, text, "utf8");

    const afterWords = wordCount(text);
    const delta = Math.abs(afterWords - beforeWords);
    const allowed = props.length * 2 + 1;
    if (delta > allowed) {
      throw new Error(
        `${chapter}: word count delta ${delta} exceeds allowed ${allowed} for ${props.length} proposals`
      );
    }
    changelog.push(``);
  }

  await fs.writeFile(path.join(jobDir, "changelog.md"), changelog.join("\n") + "\n", "utf8");
  await fs.writeFile(path.join(jobDir, "apply.log"), applyLog.join("\n") + "\n", "utf8");

  const next: State = {
    ...state,
    stage: "polished",
    ok: true,
    needsApproval: false,
    applied,
    skipped,
  };
  await writeState(jobDir, next);

  console.log(`polished: ${jobId} (applied=${applied}, skipped=${skipped})`);
}

function wordCount(text: string): number {
  const lines = text.split("\n");
  let inFence = false;
  let total = 0;
  for (const ln of lines) {
    if (/^```/.test(ln)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    if (/^#{1,6}\s/.test(ln)) continue;
    const stripped = ln.replace(/`[^`]+`/g, "").trim();
    if (!stripped) continue;
    total += stripped.split(/\s+/).filter(Boolean).length;
  }
  return total;
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: apply-polish.ts <job-id>\n");
    process.exit(1);
  }
  try {
    await applyPolish(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`apply-polish: ${msg}\n`);
    try {
      const jobDir = await buildJobDir(jobId);
      if (await exists(jobDir)) {
        await recordError(jobDir, `apply-polish: ${msg}`);
        const st = await readState(jobDir).catch(() => null);
        if (st) await writeState(jobDir, { ...st, ok: false, errors: [msg] });
      }
    } catch {}
    process.exit(1);
  }
}

main();
