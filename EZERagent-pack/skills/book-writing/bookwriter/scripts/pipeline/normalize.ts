// normalize — narrow editor. Whitespace/EOL/BOM hygiene only. No word-level edits.
// Input:  build/<job>/source/*.md
// Output: build/<job>/edited/*.md, changelog.md
// State:  structured → normalized

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { buildJobDir, ensureDir, exists } from "./paths.ts";
import { readState, writeState, recordError, type State } from "./state.ts";

type Manifest = {
  chapters: { file: string; sourcePath: string }[];
};

function normalize(text: string): string {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  text = text.replace(/\r\n?/g, "\n");
  // Trim trailing whitespace per line
  text = text
    .split("\n")
    .map((ln) => ln.replace(/[ \t]+$/u, ""))
    .join("\n");
  // Collapse 3+ blank lines to 2
  text = text.replace(/\n{3,}/g, "\n\n");
  // Single trailing LF
  text = text.replace(/\n*$/, "\n");
  return text;
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

function paragraphCount(text: string): number {
  // Markdown paragraphs: groups of non-blank lines outside code fences
  const lines = text.split("\n");
  let inFence = false;
  let inPara = false;
  let count = 0;
  for (const ln of lines) {
    if (/^```/.test(ln)) {
      if (inPara) {
        count++;
        inPara = false;
      }
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    if (/^#{1,6}\s/.test(ln)) {
      if (inPara) {
        count++;
        inPara = false;
      }
      continue;
    }
    if (ln.trim() === "") {
      if (inPara) {
        count++;
        inPara = false;
      }
    } else {
      inPara = true;
    }
  }
  if (inPara) count++;
  return count;
}

function headingLines(text: string): string[] {
  return text
    .split("\n")
    .filter((ln) => /^#{1,6}\s/.test(ln));
}

async function runNormalize(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  if (!(await exists(jobDir))) throw new Error(`job not found: ${jobId}`);

  const state = await readState(jobDir);
  if (state.stage !== "structured" && state.stage !== "normalized") {
    throw new Error(`expected stage=structured, got stage=${state.stage}`);
  }
  if (state.needsApproval) {
    // Re-check decisions.md for unanswered questions
    const decisionsPath = path.join(jobDir, "decisions.md");
    if (await exists(decisionsPath)) {
      const c = await fs.readFile(decisionsPath, "utf8");
      if (/Decided:\s*<TODO>/.test(c)) {
        process.stderr.write(
          `normalize: decisions.md has unanswered questions. Fill 'Decided: <TODO>' lines.\n`
        );
        process.exit(2);
      }
    }
  }

  const manifest: Manifest = JSON.parse(
    await fs.readFile(path.join(jobDir, "manifest.json"), "utf8")
  );
  const editedDir = path.join(jobDir, "edited");
  await ensureDir(editedDir);

  for (const ch of manifest.chapters) {
    const src = path.join(jobDir, ch.sourcePath);
    const dst = path.join(editedDir, ch.file);
    const original = await fs.readFile(src, "utf8");
    const normalized = normalize(original);

    // Self-checks: word count, paragraph count, heading lines must be invariant
    const beforeWc = wordCount(original);
    const afterWc = wordCount(normalized);
    if (beforeWc !== afterWc) {
      throw new Error(
        `${ch.file}: word count changed (${beforeWc} → ${afterWc}); narrow mode forbids this`
      );
    }
    const beforePc = paragraphCount(original);
    const afterPc = paragraphCount(normalized);
    if (beforePc !== afterPc) {
      throw new Error(
        `${ch.file}: paragraph count changed (${beforePc} → ${afterPc})`
      );
    }
    const beforeHs = headingLines(original);
    const afterHs = headingLines(normalized);
    if (beforeHs.length !== afterHs.length || beforeHs.some((h, i) => h.trim() !== afterHs[i]?.trim())) {
      throw new Error(`${ch.file}: heading lines changed`);
    }

    await fs.writeFile(dst, normalized, "utf8");
  }

  // Empty changelog (narrow mode marker)
  const changelog = `# Edit log for ${jobId}\nMode: narrow (no --polish). No word-level edits performed.\n`;
  await fs.writeFile(path.join(jobDir, "changelog.md"), changelog, "utf8");

  const next: State = { ...state, stage: "normalized", ok: true, needsApproval: false };
  await writeState(jobDir, next);

  console.log(`normalized: ${jobId}`);
  console.log(`  ${manifest.chapters.length} chapters → edited/`);
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: normalize.ts <job-id>\n");
    process.exit(1);
  }
  try {
    await runNormalize(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`normalize: ${msg}\n`);
    try {
      const jobDir = await buildJobDir(jobId);
      if (await exists(jobDir)) {
        await recordError(jobDir, `normalize: ${msg}`);
        const state = await readState(jobDir).catch(() => null);
        if (state) await writeState(jobDir, { ...state, ok: false, errors: [msg] });
      }
    } catch {}
    process.exit(1);
  }
}

main();
