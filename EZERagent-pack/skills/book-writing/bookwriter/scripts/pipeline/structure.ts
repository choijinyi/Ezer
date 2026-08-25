// structure — build outline tree from manifest + source files.
// Input:  build/<job>/manifest.json, source/*.md, meta.json
// Output: build/<job>/outline.json, decisions.md
// State:  ingested → structured

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { buildJobDir, exists } from "./paths.ts";
import { readState, writeState, recordError, type State } from "./state.ts";

type Section = { id: string; title: string; headingLevel: number; line: number };
type Chapter = {
  id: string;
  slug: string;
  file: string;
  title: string;
  wordCount: number;
  role: "body" | "frontmatter" | "backmatter";
  sections: Section[];
};
type Outline = {
  title: string;
  chapters: Chapter[];
};

type ManifestChapter = {
  file: string;
  title?: string;
  role: "body" | "frontmatter" | "backmatter";
  sourcePath: string;
  wordCount: number;
};

type Manifest = {
  title: string;
  subtitle: string;
  authors: string[];
  lang: string;
  template: string;
  outputs: string[];
  chapters: ManifestChapter[];
};

function parseFrontHeadings(text: string): { firstH1: string | null; sections: Section[] } {
  const lines = text.split("\n");
  let firstH1: string | null = null;
  const sections: Section[] = [];
  let inFence = false;
  let sectionIdx = 0;
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i]!;
    if (/^```/.test(ln)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = ln.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (!m) continue;
    const level = m[1]!.length;
    const title = m[2]!;
    if (level === 1 && firstH1 === null) {
      firstH1 = title;
    } else if (level >= 2) {
      sections.push({
        id: "", // filled per chapter below
        title,
        headingLevel: level,
        line: i + 1,
      });
      sectionIdx++;
    }
  }
  void sectionIdx;
  return { firstH1, sections };
}

function chapterIdFromIndex(i: number, total: number): string {
  const w = Math.max(2, String(total).length);
  return `ch-${String(i + 1).padStart(w, "0")}`;
}

const SHORT_THRESHOLD = 300;
const LONG_THRESHOLD = 10_000;

async function structure(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  if (!(await exists(jobDir))) throw new Error(`job not found: ${jobId}`);

  const state = await readState(jobDir);
  if (state.stage !== "ingested" && state.stage !== "structured") {
    throw new Error(`expected stage=ingested, got stage=${state.stage}`);
  }

  const manifestPath = path.join(jobDir, "manifest.json");
  const manifest: Manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));

  const total = manifest.chapters.length;
  const outline: Outline = { title: manifest.title, chapters: [] };
  const questions: string[] = [];

  for (let i = 0; i < total; i++) {
    const ch = manifest.chapters[i]!;
    const id = chapterIdFromIndex(i, total);
    const slug = ch.file.replace(/^\d+-/, "").replace(/\.md$/, "");
    const text = await fs.readFile(path.join(jobDir, ch.sourcePath), "utf8");
    const { firstH1, sections: rawSections } = parseFrontHeadings(text);
    const title = firstH1 ?? ch.title ?? slug;
    const sections: Section[] = rawSections.map((s, j) => ({
      ...s,
      id: `${id}-s-${String(j + 1).padStart(2, "0")}`,
    }));

    outline.chapters.push({
      id,
      slug,
      file: ch.sourcePath,
      title,
      wordCount: ch.wordCount,
      role: ch.role,
      sections,
    });

    // Anomaly detection (body chapters only, plus empty matter detection)
    if (ch.role === "body") {
      if (ch.wordCount < SHORT_THRESHOLD) {
        questions.push(
          `## Q${questions.length + 1}: ${ch.file} is short (${ch.wordCount} words)\n` +
            `\nOptions:\n- 1. Keep as-is\n- 2. Skip in this build\n- 3. Wait — still writing\n\n` +
            `Decided: <TODO>\n`
        );
      } else if (ch.wordCount > LONG_THRESHOLD) {
        questions.push(
          `## Q${questions.length + 1}: ${ch.file} is long (${ch.wordCount} words)\n` +
            `\nOptions:\n- 1. Keep as one chapter\n- 2. Split before next stage (manual)\n\n` +
            `Decided: <TODO>\n`
        );
      }
    } else if (ch.wordCount < 1) {
      questions.push(
        `## Q${questions.length + 1}: ${ch.file} is empty\n` +
          `\nOptions:\n- 1. Skip in this build\n- 2. Keep with empty page\n\n` +
          `Decided: <TODO>\n`
      );
    }
  }

  // write outline
  await fs.writeFile(
    path.join(jobDir, "outline.json"),
    JSON.stringify(outline, null, 2) + "\n",
    "utf8"
  );

  // write decisions.md
  let decisionsContent: string;
  if (questions.length === 0) {
    decisionsContent = "# No structural decisions needed.\n";
  } else {
    decisionsContent = `# Structural decisions for ${jobId}\n\nFill each \`Decided: <TODO>\` with an option number.\n\n` + questions.join("\n");
  }
  await fs.writeFile(path.join(jobDir, "decisions.md"), decisionsContent, "utf8");

  const next: State = {
    ...state,
    stage: "structured",
    ok: true,
    needsApproval: questions.length > 0,
  };
  await writeState(jobDir, next);

  console.log(`structured: ${jobId}`);
  console.log(`  ${outline.chapters.length} chapters in outline`);
  if (questions.length > 0) {
    console.log(`  ⚠ ${questions.length} structural question(s) — fill build/${jobId}/decisions.md`);
  } else {
    console.log(`  no structural questions`);
  }
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: structure.ts <job-id>\n");
    process.exit(1);
  }
  try {
    await structure(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`structure: ${msg}\n`);
    try {
      const jobDir = await buildJobDir(jobId);
      if (await exists(jobDir)) {
        await recordError(jobDir, `structure: ${msg}`);
        const state = await readState(jobDir).catch(() => null);
        if (state) await writeState(jobDir, { ...state, ok: false, errors: [msg] });
      }
    } catch {}
    process.exit(1);
  }
}

main();
