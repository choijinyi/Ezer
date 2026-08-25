// /new — scaffold a manuscript or stage a job for the pipeline.
// Forms:
//   node scripts/pipeline/new.ts --scaffold <name> [--chapters N] [--lang ko|en] [--template <id>]
//   node scripts/pipeline/new.ts <path-to-manuscript-dir>
//   node scripts/pipeline/new.ts <path-to-single.md>

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { z } from "zod";
import {
  buildJobDir,
  ensureDir,
  exists,
  manuscriptDir,
  newJobId,
  repoRoot,
  templateDir,
} from "./paths.ts";
import { writeState, type State } from "./state.ts";

// ─── argv parsing ──────────────────────────────────────────────────────────

type Args = {
  scaffold?: string;
  chapters: number;
  lang: "ko" | "en";
  template: string;
  positional: string[];
};

function parseArgs(argv: string[]): Args {
  const out: Args = {
    chapters: 14,
    lang: "ko",
    template: "typst-classic",
    positional: [],
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a === "--scaffold") {
      const v = argv[++i];
      if (!v) throw new Error("--scaffold requires <name>");
      out.scaffold = v;
    } else if (a === "--chapters") {
      const v = argv[++i];
      if (!v || !/^\d+$/.test(v)) throw new Error("--chapters requires positive integer");
      out.chapters = parseInt(v, 10);
      if (out.chapters < 1 || out.chapters > 999) throw new Error("--chapters must be 1..999");
    } else if (a === "--lang") {
      const v = argv[++i];
      if (v !== "ko" && v !== "en") throw new Error("--lang must be ko or en");
      out.lang = v;
    } else if (a === "--template") {
      const v = argv[++i];
      if (!v) throw new Error("--template requires <id>");
      out.template = v;
    } else if (a.startsWith("--")) {
      throw new Error(`unknown flag: ${a}`);
    } else {
      out.positional.push(a);
    }
  }
  return out;
}

// ─── book.json schema ──────────────────────────────────────────────────────

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

// ─── helpers ───────────────────────────────────────────────────────────────

function padWidth(n: number): number {
  return Math.max(2, String(n).length);
}

function chapterStub(n: number, lang: "ko" | "en"): string {
  if (lang === "en") return `# Chapter ${n}\n\nWrite chapter ${n} here.\n`;
  return `# ${n}장\n\n여기에 ${n}장을 쓴다.\n`;
}

async function listFilesCaseSensitive(dir: string): Promise<Set<string>> {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  return new Set(entries.filter((e) => e.isFile()).map((e) => e.name));
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

// ─── mode: scaffold ────────────────────────────────────────────────────────

async function scaffold(args: Args): Promise<void> {
  const name = args.scaffold!;
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
    throw new Error(`invalid manuscript name: ${name} (use [a-zA-Z0-9_-]+)`);
  }
  const dst = await manuscriptDir(name);
  if (await exists(dst)) {
    throw new Error(`manuscripts/${name}/ already exists; refusing to overwrite`);
  }

  const tplDir = await templateDir("manuscript-default");
  if (!(await exists(tplDir))) {
    throw new Error(`template not found: templates/manuscript-default`);
  }

  await ensureDir(dst);

  // 1. Copy verbatim files: README, preface, references
  for (const f of ["README.md", "00-preface.md", "99-references.md"]) {
    const s = path.join(tplDir, f);
    if (await exists(s)) await fs.copyFile(s, path.join(dst, f));
  }

  // 2. Generate N body chapter files
  const w = padWidth(args.chapters);
  for (let i = 1; i <= args.chapters; i++) {
    const num = String(i).padStart(w, "0");
    const file = path.join(dst, `${num}-chapter.md`);
    await fs.writeFile(file, chapterStub(i, args.lang), "utf8");
  }

  // 3. Generate book.json
  const chapters: BookJson["chapters"] = [];
  if (await exists(path.join(dst, "00-preface.md"))) {
    chapters.push({ file: "00-preface.md", role: "frontmatter", title: args.lang === "en" ? "Preface" : "머리말" });
  }
  for (let i = 1; i <= args.chapters; i++) {
    const num = String(i).padStart(w, "0");
    chapters.push({
      file: `${num}-chapter.md`,
      role: "body",
      title: args.lang === "en" ? `Chapter ${i}` : `${i}장`,
    });
  }
  if (await exists(path.join(dst, "99-references.md"))) {
    chapters.push({
      file: "99-references.md",
      role: "backmatter",
      title: args.lang === "en" ? "References" : "참고문헌",
    });
  }

  const book: BookJson = {
    title: name,
    subtitle: "",
    authors: [],
    lang: args.lang,
    template: args.template,
    outputs: ["pdf"],
    chapters,
  };
  await fs.writeFile(path.join(dst, "book.json"), JSON.stringify(book, null, 2) + "\n", "utf8");

  console.log(`scaffolded: manuscripts/${name}/`);
  console.log(`  chapters: ${args.chapters} body + ${chapters.length - args.chapters} matter`);
  console.log(`  lang: ${args.lang}, template: ${args.template}`);
  console.log(`next: edit your chapters, then run`);
  console.log(`  node scripts/pipeline/new.ts manuscripts/${name}`);
}

// ─── mode: stage a job from a manuscript dir or single .md ─────────────────

async function stageDir(srcDir: string): Promise<void> {
  const absSrc = path.resolve(srcDir);
  if (!(await exists(absSrc))) {
    throw new Error(`not found: ${srcDir}`);
  }
  const stat = await fs.stat(absSrc);
  if (!stat.isDirectory()) {
    throw new Error(`not a directory: ${srcDir}`);
  }

  // 1. parse book.json
  const bookPath = path.join(absSrc, "book.json");
  if (!(await exists(bookPath))) {
    throw new Error(
      `book.json not found in ${srcDir}. Run --scaffold first or write a book.json.`
    );
  }
  let book: BookJson;
  try {
    const raw = await fs.readFile(bookPath, "utf8");
    book = BookJsonSchema.parse(JSON.parse(raw));
  } catch (e) {
    throw new Error(`book.json parse failed: ${(e as Error).message}`);
  }

  // 2. case-sensitive verification of every chapter file
  const filesOnDisk = await listFilesCaseSensitive(absSrc);
  for (const ch of book.chapters) {
    if (!ch.file.endsWith(".md")) {
      throw new Error(`v1 supports .md only — chapter "${ch.file}" rejected`);
    }
    if (!filesOnDisk.has(ch.file)) {
      throw new Error(`chapter file missing or case-mismatch: ${ch.file}`);
    }
  }

  // 3. job id and build dir
  const jobId = newJobId();
  const jobDir = await buildJobDir(jobId);
  const inputDir = path.join(jobDir, "input");
  await ensureDir(inputDir);

  // 4. snapshot manuscript into build/<job>/input/
  await copyDirRecursive(absSrc, inputDir);

  // 5. write state.json
  const now = new Date().toISOString();
  const root = await repoRoot();
  const manuscriptRel = path.relative(root, absSrc).replace(/\\/g, "/");
  const state: State = {
    jobId,
    manuscript: manuscriptRel,
    stage: "created",
    ok: true,
    needsApproval: false,
    createdAt: now,
    updatedAt: now,
    template: book.template,
    outputs: book.outputs,
    polish: false,
  };
  await writeState(jobDir, state);

  // 6. record in manuscripts/<name>/.bookwriter/jobs.json
  await recordJobInManuscript(absSrc, jobId, now);

  console.log(`job created: ${jobId}`);
  console.log(`  manuscript: ${manuscriptRel}`);
  console.log(`  template: ${book.template}, chapters: ${book.chapters.length}`);
  console.log(`  build/: ${path.relative(root, jobDir).replace(/\\/g, "/")}/`);
  console.log(`next:`);
  console.log(`  node scripts/pipeline/run.ts ${jobId}`);
  // emit job-id as last line for scripting consumers
  process.stdout.write(`JOB_ID=${jobId}\n`);
}

async function stageSingleFile(filePath: string): Promise<void> {
  const abs = path.resolve(filePath);
  if (!abs.endsWith(".md")) {
    throw new Error(`v1 supports .md only — got ${filePath}`);
  }
  if (!(await exists(abs))) {
    throw new Error(`not found: ${filePath}`);
  }

  // wrap into a tmp manuscript dir under build/<job>/input/ directly
  const jobId = newJobId();
  const jobDir = await buildJobDir(jobId);
  const inputDir = path.join(jobDir, "input");
  await ensureDir(inputDir);

  const fname = "01-chapter.md";
  await fs.copyFile(abs, path.join(inputDir, fname));

  // derive title from first # line
  const content = await fs.readFile(abs, "utf8");
  const titleMatch = content.match(/^#\s+(.+?)\s*$/m);
  const title = titleMatch?.[1] ?? path.basename(abs, ".md");

  const book: BookJson = {
    title,
    subtitle: "",
    authors: [],
    lang: /[ㄱ-힝]/.test(content) ? "ko" : "en",
    template: "typst-classic",
    outputs: ["pdf"],
    chapters: [{ file: fname, role: "body", title }],
  };
  await fs.writeFile(
    path.join(inputDir, "book.json"),
    JSON.stringify(book, null, 2) + "\n",
    "utf8"
  );

  const now = new Date().toISOString();
  const root = await repoRoot();
  const state: State = {
    jobId,
    manuscript: `(single-file: ${path.relative(root, abs).replace(/\\/g, "/")})`,
    stage: "created",
    ok: true,
    needsApproval: false,
    createdAt: now,
    updatedAt: now,
    template: book.template,
    outputs: book.outputs,
    polish: false,
  };
  await writeState(jobDir, state);

  console.log(`job created: ${jobId} (wrapped single-file)`);
  console.log(`  source: ${filePath}`);
  console.log(`next:`);
  console.log(`  node scripts/pipeline/run.ts ${jobId}`);
  process.stdout.write(`JOB_ID=${jobId}\n`);
}

async function recordJobInManuscript(
  manuscriptAbs: string,
  jobId: string,
  iso: string
): Promise<void> {
  const dotDir = path.join(manuscriptAbs, ".bookwriter");
  await ensureDir(dotDir);
  const jobsPath = path.join(dotDir, "jobs.json");
  let jobs: { jobId: string; createdAt: string }[] = [];
  if (await exists(jobsPath)) {
    try {
      jobs = JSON.parse(await fs.readFile(jobsPath, "utf8"));
    } catch {
      jobs = [];
    }
  }
  jobs.push({ jobId, createdAt: iso });
  await fs.writeFile(jobsPath, JSON.stringify(jobs, null, 2) + "\n", "utf8");
}

// ─── main ──────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));

  if (args.scaffold) {
    await scaffold(args);
    return;
  }

  if (args.positional.length !== 1) {
    throw new Error(
      "usage: new.ts --scaffold <name> [--chapters N] [--lang ko|en] [--template id]\n" +
        "       new.ts <path-to-manuscript-dir>\n" +
        "       new.ts <path-to-single.md>"
    );
  }
  const target = args.positional[0]!;
  const abs = path.resolve(target);
  const stat = await fs.stat(abs).catch(() => null);
  if (!stat) throw new Error(`not found: ${target}`);

  if (stat.isDirectory()) await stageDir(target);
  else if (stat.isFile()) await stageSingleFile(target);
  else throw new Error(`not a file or directory: ${target}`);
}

main().catch((e: unknown) => {
  const msg = e instanceof Error ? e.message : String(e);
  process.stderr.write(`new: ${msg}\n`);
  process.exit(1);
});
