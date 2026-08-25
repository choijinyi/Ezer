// typeset — concat edited markdown → pandoc to Typst → fill template → typst compile to PDF.
// Input:  build/<job>/edited/*.md, manifest.json, meta.json, templates/<id>/template.typ
// Output: build/<job>/body.md, body.typ, book.typ, preview.pdf, typeset.log
// State:  normalized | polished | illustrated → typeset

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { spawn } from "node:child_process";
import { buildJobDir, exists, repoRoot, templateDir } from "./paths.ts";
import { readState, writeState, recordError, type State } from "./state.ts";

type ManifestChapter = { file: string; sourcePath: string; role: string };
type Manifest = {
  title: string;
  authors: string[];
  lang: string;
  template: string;
  chapters: ManifestChapter[];
};

type Meta = {
  title: string;
  authors: string[];
  lang: string;
};

function runProc(cmd: string, args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { shell: false });
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];
    child.stdout.on("data", (c) => stdoutChunks.push(c));
    child.stderr.on("data", (c) => stderrChunks.push(c));
    child.on("close", (code) => {
      resolve({
        code: code ?? -1,
        stdout: Buffer.concat(stdoutChunks).toString("utf8"),
        stderr: Buffer.concat(stderrChunks).toString("utf8"),
      });
    });
    child.on("error", (e) => {
      resolve({ code: -1, stdout: "", stderr: String(e) });
    });
  });
}

function escapeTypstString(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

async function typeset(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  if (!(await exists(jobDir))) throw new Error(`job not found: ${jobId}`);

  const state = await readState(jobDir);
  const validPrior = ["normalized", "polished", "illustrated", "typeset"];
  if (!validPrior.includes(state.stage)) {
    throw new Error(`expected stage ∈ ${validPrior.join("|")}, got ${state.stage}`);
  }

  const manifest: Manifest = JSON.parse(
    await fs.readFile(path.join(jobDir, "manifest.json"), "utf8")
  );
  const meta: Meta = JSON.parse(await fs.readFile(path.join(jobDir, "meta.json"), "utf8"));

  const editedDir = path.join(jobDir, "edited");

  // 1. Concat full body for export/EPUB convenience (all roles in order)
  const allParts: string[] = [];
  for (const ch of manifest.chapters) {
    const p = path.join(editedDir, ch.file);
    if (!(await exists(p))) throw new Error(`edited file missing: ${ch.file}`);
    allParts.push((await fs.readFile(p, "utf8")).trimEnd());
    allParts.push("");
  }
  const bodyMdPath = path.join(jobDir, "body.md");
  await fs.writeFile(bodyMdPath, allParts.join("\n"), "utf8");

  // 2. Group by role and run pandoc per group → role-aware typst.
  const groups: Record<string, ManifestChapter[]> = { frontmatter: [], body: [], backmatter: [] };
  for (const ch of manifest.chapters) {
    const role = (ch.role || "body") as keyof typeof groups;
    (groups[role] ?? groups.body).push(ch);
  }

  const buildSection = async (
    role: "frontmatter" | "body" | "backmatter",
    chapters: ManifestChapter[],
  ): Promise<string> => {
    if (chapters.length === 0) return "";
    const parts: string[] = [];
    for (const ch of chapters) {
      const p = path.join(editedDir, ch.file);
      parts.push((await fs.readFile(p, "utf8")).trimEnd());
      parts.push("");
    }
    const md = parts.join("\n");
    const tmpMd = path.join(jobDir, `_section-${role}.md`);
    const tmpTyp = path.join(jobDir, `_section-${role}.typ`);
    await fs.writeFile(tmpMd, md, "utf8");
    const res = await runProc("pandoc", [tmpMd, "-t", "typst", "-o", tmpTyp]);
    if (res.code !== 0) {
      throw new Error(`pandoc(${role}) failed: ${res.stderr.trim() || "exit " + res.code}`);
    }
    let typ = await fs.readFile(tmpTyp, "utf8");

    // For frontmatter and backmatter: strip the chapter-number show rule by
    // converting `= Title` headings into a centered title block (not a heading).
    if (role === "frontmatter" || role === "backmatter") {
      typ = typ.replace(/^=\s+(.+?)\s*$/gm, (_m: string, title: string) => {
        return [
          "#pagebreak(weak: true)",
          "#v(2.5em)",
          `#align(center)[#text(size: 22pt, weight: "bold")[${title}]]`,
          "#v(1.5em)",
        ].join("\n");
      });
    }
    return typ;
  };

  const fmTyp = await buildSection("frontmatter", groups.frontmatter ?? []);
  const bdTyp = await buildSection("body", groups.body ?? []);
  const bmTyp = await buildSection("backmatter", groups.backmatter ?? []);

  // Compose body with role transitions (page numbering, counter resets, hanging indent for refs)
  const sectionParts: string[] = [];
  if (fmTyp) {
    sectionParts.push(`// === FRONTMATTER ===`);
    // header는 건드리지 않는다 — 템플릿의 러닝 헤더가 in_body 상태로 자체 제어하며,
    // 여기서 header: none을 설정하면 body 구간까지 헤더가 꺼진 채 유지된다.
    sectionParts.push(`#set page(numbering: "i", number-align: center)`);
    sectionParts.push(fmTyp);
  }
  if (bdTyp) {
    sectionParts.push(`// === BODY ===`);
    sectionParts.push(`#set page(numbering: "1", number-align: center)`);
    sectionParts.push(`#counter(page).update(1)`);
    sectionParts.push(`#counter(heading).update(0)`);
    sectionParts.push(`#in_body.update(true)`);
    sectionParts.push(bdTyp);
    sectionParts.push(`#in_body.update(false)`);
  }
  if (bmTyp) {
    sectionParts.push(`// === BACKMATTER (hanging-indent for references) ===`);
    sectionParts.push(`#set page(header: none)`);
    sectionParts.push(`#[`);
    sectionParts.push(`#set par(hanging-indent: 1.5em, first-line-indent: 0em)`);
    sectionParts.push(bmTyp);
    sectionParts.push(`]`);
  }
  const bodyTyp = sectionParts.join("\n\n");
  await fs.writeFile(path.join(jobDir, "body.typ"), bodyTyp, "utf8");

  // 3. Read template
  const tplDir = await templateDir(manifest.template);
  if (!(await exists(tplDir))) {
    throw new Error(`template not found: ${manifest.template}`);
  }
  const tplPath = path.join(tplDir, "template.typ");
  const tpl = await fs.readFile(tplPath, "utf8");

  // 4. Substitute placeholders (cover_path: only if cover exists)
  const author = meta.authors.length ? meta.authors.join(", ") : "(저자 미상)";
  const lang = meta.lang || "ko";

  let coverPath = "";
  for (const ext of ["svg", "png", "jpg", "jpeg", "webp"] as const) {
    const p = path.join(jobDir, `cover.${ext}`);
    if (await exists(p)) {
      coverPath = `cover.${ext}`;
      break;
    }
  }

  // 함수 replacer 사용: 문자열 replacement는 $&, $' 등 특수 패턴을 해석하므로
  // 본문/제목에 $가 있으면 조용히 손상된다.
  const book = tpl
    .replace(/\{\{title\}\}/g, () => escapeTypstString(meta.title))
    .replace(/\{\{author\}\}/g, () => escapeTypstString(author))
    .replace(/\{\{lang\}\}/g, () => lang)
    .replace(/\{\{cover_path\}\}/g, () => coverPath)
    .replace(/\{\{body\}\}/g, () => bodyTyp);

  const bookPath = path.join(jobDir, "book.typ");
  await fs.writeFile(bookPath, book, "utf8");

  // 5. typst compile
  const previewPath = path.join(jobDir, "preview.pdf");
  const root = await repoRoot();
  void root;
  const typstRes = await runProc("typst", [
    "compile",
    "--root",
    jobDir,
    bookPath,
    previewPath,
  ]);
  // Capture log regardless of result
  const log = `# typst\n${typstRes.stdout}${typstRes.stderr}\n`;
  await fs.writeFile(path.join(jobDir, "typeset.log"), log, "utf8");

  if (typstRes.code !== 0) {
    throw new Error(`typst compile failed (code ${typstRes.code}): see typeset.log`);
  }

  const pages = await countPdfPages(previewPath);

  const next: State = { ...state, stage: "typeset", ok: true };
  if (pages != null) next.pages = pages;
  await writeState(jobDir, next);

  console.log(`typeset: ${jobId}`);
  console.log(`  preview: build/${jobId}/preview.pdf${pages != null ? ` (${pages} pages)` : ""}`);
}

async function countPdfPages(pdfPath: string): Promise<number | undefined> {
  try {
    const buf = await fs.readFile(pdfPath);
    const text = buf.toString("latin1");
    // PDF /Type /Pages dictionary contains /Count <N> for the root page tree
    const matches = [...text.matchAll(/\/Type\s*\/Pages\b[\s\S]{0,400}?\/Count\s+(\d+)/g)];
    if (matches.length === 0) return undefined;
    const counts = matches.map((m) => parseInt(m[1]!, 10)).filter((n) => Number.isFinite(n));
    if (counts.length === 0) return undefined;
    return Math.max(...counts);
  } catch {
    return undefined;
  }
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: typeset.ts <job-id>\n");
    process.exit(1);
  }
  try {
    await typeset(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`typeset: ${msg}\n`);
    try {
      const jobDir = await buildJobDir(jobId);
      if (await exists(jobDir)) {
        await recordError(jobDir, `typeset: ${msg}`);
        const state = await readState(jobDir).catch(() => null);
        if (state) await writeState(jobDir, { ...state, ok: false, errors: [msg] });
      }
    } catch {}
    process.exit(1);
  }
}

main();
