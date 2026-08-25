// polish-propose — invoke polish-proposer LLM per chapter, collect proposals.
// Input:  build/<job>/edited/*.md (post-narrow), manifest.json
// Output: build/<job>/polish-proposals.md, polish-proposals.json
// State:  normalized → polish-proposed (needsApproval=true)

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { z } from "zod";
import { buildJobDir, exists } from "./paths.ts";
import { readState, writeState, recordError, type State } from "./state.ts";
import { callAgent } from "./llm.ts";

type ManifestChapter = { file: string; sourcePath: string; role: string };
type Manifest = { chapters: ManifestChapter[] };

const ProposalSchema = z.object({
  line: z.number().int().min(1),
  before: z.string().min(1),
  after: z.string(),
  category: z.enum(["spelling", "particle", "terminology", "repetition", "punctuation"]),
  reason: z.string(),
});
const ProposalsResponseSchema = z.object({
  proposals: z.array(ProposalSchema),
});
type Proposal = z.infer<typeof ProposalSchema>;

type ChapterProposals = {
  file: string;
  proposals: Proposal[];
  llmError?: string;
};

function stripCodeFences(s: string): string {
  return s
    .trim()
    .replace(/^```[a-zA-Z]*\n/, "")
    .replace(/\n```\s*$/, "")
    .trim();
}

function isHeadingLine(line: string): boolean {
  return /^#{1,6}\s/.test(line);
}

function validateProposal(p: Proposal, chapterText: string): string | null {
  const lines = chapterText.split("\n");
  const targetLine = lines[p.line - 1];
  if (targetLine == null) return `line ${p.line} out of range`;
  if (isHeadingLine(targetLine)) return `line ${p.line} is a heading; rejected`;
  if (!chapterText.includes(p.before)) return `before text not found in chapter`;
  if (p.before === p.after) return `before == after`;
  if (p.before.includes("\n") || p.after.includes("\n")) return `multi-line edit forbidden`;
  return null;
}

async function proposeForChapter(
  jobDir: string,
  ch: ManifestChapter
): Promise<ChapterProposals> {
  const editedPath = path.join(jobDir, "edited", ch.file);
  const text = await fs.readFile(editedPath, "utf8");

  // Skip empty / matter chapters
  if (text.trim().length === 0 || ch.role !== "body") {
    return { file: ch.file, proposals: [] };
  }

  const userMessage = `Chapter file: ${ch.file}\n\n--- BEGIN CHAPTER ---\n${text}\n--- END CHAPTER ---`;

  let raw: string;
  try {
    raw = await callAgent(".claude/agents/polish-proposer.md", userMessage, {
      cacheDir: jobDir,
      maxTokens: 4096,
    });
  } catch (e) {
    return { file: ch.file, proposals: [], llmError: (e as Error).message };
  }

  let parsed: { proposals: Proposal[] };
  try {
    const cleaned = stripCodeFences(raw);
    const obj = JSON.parse(cleaned);
    parsed = ProposalsResponseSchema.parse(obj);
  } catch (e) {
    return {
      file: ch.file,
      proposals: [],
      llmError: `JSON parse: ${(e as Error).message}`,
    };
  }

  const validated: Proposal[] = [];
  for (const p of parsed.proposals) {
    const err = validateProposal(p, text);
    if (!err) validated.push(p);
  }

  return { file: ch.file, proposals: validated };
}

function renderProposalsMarkdown(jobId: string, all: ChapterProposals[]): string {
  let total = 0;
  let out = `# Polish proposals for ${jobId}\n\n`;
  out += `각 항목의 \`Apply: <TODO>\`에 \`y\`(적용) 또는 \`n\`(스킵)을 표시.\n`;
  out += `헤딩 줄(#)은 제안 대상에서 제외됨. 응답 후 \`/run\` 재실행하면 적용됨.\n\n`;

  for (const cp of all) {
    if (cp.llmError) {
      out += `## ${cp.file}\n\n> LLM error: ${cp.llmError}\n\n`;
      continue;
    }
    if (cp.proposals.length === 0) {
      out += `## ${cp.file}\n\n(no proposals)\n\n`;
      continue;
    }
    out += `## ${cp.file}\n\n`;
    for (let i = 0; i < cp.proposals.length; i++) {
      const p = cp.proposals[i]!;
      total++;
      out += `### P${total} — L${p.line} — ${p.category}\n`;
      out += `- before: ${JSON.stringify(p.before)}\n`;
      out += `- after:  ${JSON.stringify(p.after)}\n`;
      out += `- reason: ${p.reason}\n`;
      out += `- Apply: <TODO>\n\n`;
    }
  }

  if (total === 0) {
    out += `> No proposals across all chapters.\n`;
  }
  return out;
}

async function polishPropose(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  if (!(await exists(jobDir))) throw new Error(`job not found: ${jobId}`);

  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error(
      "ANTHROPIC_API_KEY not set. --polish requires the LLM. Either set the key or run without --polish."
    );
  }

  const state = await readState(jobDir);
  if (state.stage !== "normalized" && state.stage !== "polish-proposed") {
    throw new Error(`expected stage=normalized, got ${state.stage}`);
  }

  const manifest: Manifest = JSON.parse(
    await fs.readFile(path.join(jobDir, "manifest.json"), "utf8")
  );

  const all: ChapterProposals[] = [];
  for (const ch of manifest.chapters) {
    process.stdout.write(`  proposing for ${ch.file} ... `);
    const r = await proposeForChapter(jobDir, ch);
    if (r.llmError) console.log(`error: ${r.llmError}`);
    else console.log(`${r.proposals.length} proposal(s)`);
    all.push(r);
  }

  // JSON sidecar (machine-readable)
  await fs.writeFile(
    path.join(jobDir, "polish-proposals.json"),
    JSON.stringify({ jobId, proposals: all }, null, 2) + "\n",
    "utf8"
  );

  // Markdown (human-facing, with Apply: <TODO> tokens)
  const md = renderProposalsMarkdown(jobId, all);
  await fs.writeFile(path.join(jobDir, "polish-proposals.md"), md, "utf8");

  const totalProposals = all.reduce((n, c) => n + c.proposals.length, 0);
  const next: State = {
    ...state,
    stage: "polish-proposed",
    ok: true,
    needsApproval: totalProposals > 0,
  };
  await writeState(jobDir, next);

  console.log(`polish-proposed: ${jobId} (${totalProposals} proposals across ${all.length} chapters)`);
  if (totalProposals > 0) {
    console.log(`  → fill 'Apply: <TODO>' in build/${jobId}/polish-proposals.md`);
  }
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: polish-propose.ts <job-id>\n");
    process.exit(1);
  }
  try {
    await polishPropose(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`polish-propose: ${msg}\n`);
    try {
      const jobDir = await buildJobDir(jobId);
      if (await exists(jobDir)) {
        await recordError(jobDir, `polish-propose: ${msg}`);
        const st = await readState(jobDir).catch(() => null);
        if (st) await writeState(jobDir, { ...st, ok: false, errors: [msg] });
      }
    } catch {}
    process.exit(1);
  }
}

main();
