// ingest — normalize per-chapter Markdown, derive meta, snapshot figures and cover.
// Input:  build/<job>/input/<book.json + chapter .md + figures/?>
// Output: build/<job>/source/<NN-*.md>, manifest.json, meta.json, figures/orig/?, cover-user.?
// State:  created → ingested

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { z } from "zod";
import { buildJobDir, ensureDir, exists } from "./paths.ts";
import { readState, writeState, recordError, type State } from "./state.ts";

const ChapterEntrySchema = z.object({
  file: z.string(),
  title: z.string().optional(),
  role: z.enum(["body", "frontmatter", "backmatter"]).default("body"),
});

const BookJsonSchema = z.object({
  title: z.string(),
  subtitle: z.string().default(""),
  authors: z.array(z.string()).default([]),
  lang: z.string().default("ko"),
  template: z.string().default("typst-classic"),
  outputs: z.array(z.enum(["pdf", "epub", "web"])).default(["pdf"]),
  chapters: z.array(ChapterEntrySchema).min(1),
});
type BookJson = z.infer<typeof BookJsonSchema>;
type ChapterEntry = z.infer<typeof ChapterEntrySchema>;

const COVER_EXTS = ["svg", "png", "jpg", "jpeg", "webp"] as const;

function normalizeChapter(text: string): string {
  // 1. Strip BOM
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  // 2. CRLF/CR → LF
  text = text.replace(/\r\n?/g, "\n");
  // 3. Setext → ATX (rare, but per spec)
  text = text.replace(/^(.+)\n=+\s*$/gm, "# $1");
  text = text.replace(/^(.+)\n-+\s*$/gm, "## $1");
  // 4. Image path rewrite: figures/X → figures/orig/X (only for relative paths starting with figures/)
  text = text.replace(
    /(!\[[^\]]*\]\()(figures\/)([^)]+)(\))/g,
    "$1figures/orig/$3$4"
  );
  // 5. Collapse 3+ blank lines to 2
  text = text.replace(/\n{3,}/g, "\n\n");
  // 6. Single trailing LF
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

async function copyDirRecursive(src: string, dst: string): Promise<void> {
  await ensureDir(dst);
  const entries = await fs.readdir(src, { withFileTypes: true });
  for (const e of entries) {
    const s = path.join(src, e.name);
    const d = path.join(dst, e.name);
    if (e.isDirectory()) await copyDirRecursive(s, d);
    else if (e.isFile()) await fs.copyFile(s, d);
  }
}

async function findUserCover(inputDir: string): Promise<string | null> {
  for (const ext of COVER_EXTS) {
    const p = path.join(inputDir, `cover.${ext}`);
    if (await exists(p)) return p;
  }
  return null;
}

async function ingest(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  if (!(await exists(jobDir))) {
    throw new Error(`job not found: ${jobId}`);
  }

  const state = await readState(jobDir);
  if (state.stage !== "created" && state.stage !== "ingested") {
    throw new Error(`expected stage=created, got stage=${state.stage}`);
  }

  const inputDir = path.join(jobDir, "input");
  const sourceDir = path.join(jobDir, "source");
  const figuresOrig = path.join(jobDir, "figures", "orig");
  await ensureDir(sourceDir);

  // 1. parse book.json
  const bookPath = path.join(inputDir, "book.json");
  const book: BookJson = BookJsonSchema.parse(
    JSON.parse(await fs.readFile(bookPath, "utf8"))
  );

  // 2. normalize each chapter, validate
  const emptyChapters: string[] = [];
  let totalWords = 0;
  const enrichedChapters: (ChapterEntry & { sourcePath: string; wordCount: number })[] = [];

  for (const ch of book.chapters) {
    const src = path.join(inputDir, ch.file);
    if (!(await exists(src))) {
      throw new Error(`missing chapter: ${ch.file}`);
    }
    const raw = await fs.readFile(src, "utf8");
    const normalized = normalizeChapter(raw);
    const wc = wordCount(normalized);

    if (ch.role === "body" && wc < 1) {
      throw new Error(`body chapter is empty: ${ch.file}`);
    }
    if (wc < 1) {
      const slug = ch.file.replace(/\.md$/, "");
      emptyChapters.push(slug);
    }

    const dstFile = path.join(sourceDir, ch.file);
    await fs.writeFile(dstFile, normalized, "utf8");
    enrichedChapters.push({
      ...ch,
      sourcePath: `source/${ch.file}`,
      wordCount: wc,
    });
    totalWords += wc;
  }

  // 3. copy figures/ → figures/orig/ if input has any
  const inputFigures = path.join(inputDir, "figures");
  if (await exists(inputFigures)) {
    await copyDirRecursive(inputFigures, figuresOrig);
  }

  // 4. user cover detection
  const userCoverPath = await findUserCover(inputDir);
  let userCoverRel: string | null = null;
  if (userCoverPath) {
    const ext = path.extname(userCoverPath).slice(1).toLowerCase();
    const dst = path.join(jobDir, `cover-user.${ext}`);
    await fs.copyFile(userCoverPath, dst);
    userCoverRel = `cover-user.${ext}`;
  }

  // 5. write manifest.json
  const manifest = {
    ...book,
    chapters: enrichedChapters,
  };
  await fs.writeFile(
    path.join(jobDir, "manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n",
    "utf8"
  );

  // 6. write meta.json
  const meta = {
    title: book.title,
    subtitle: book.subtitle,
    authors: book.authors,
    lang: book.lang,
    template: book.template,
    chapterCount: book.chapters.length,
    wordCount: totalWords,
    ingestedAt: new Date().toISOString(),
    userCover: userCoverRel,
    emptyChapters,
  };
  await fs.writeFile(
    path.join(jobDir, "meta.json"),
    JSON.stringify(meta, null, 2) + "\n",
    "utf8"
  );

  // 7. update state
  const next: State = { ...state, stage: "ingested", ok: true };
  await writeState(jobDir, next);

  console.log(`ingested: ${jobId}`);
  console.log(`  ${enrichedChapters.length} chapters, ${totalWords} words`);
  if (emptyChapters.length) console.log(`  empty (matter): ${emptyChapters.join(", ")}`);
  if (userCoverRel) console.log(`  user cover: ${userCoverRel}`);
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: ingest.ts <job-id>\n");
    process.exit(1);
  }

  try {
    await ingest(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`ingest: ${msg}\n`);
    try {
      const jobDir = await buildJobDir(jobId);
      if (await exists(jobDir)) {
        await recordError(jobDir, `ingest: ${msg}`);
        const state = await readState(jobDir).catch(() => null);
        if (state) {
          await writeState(jobDir, { ...state, ok: false, errors: [msg] });
        }
      }
    } catch {}
    process.exit(1);
  }
}

main();
