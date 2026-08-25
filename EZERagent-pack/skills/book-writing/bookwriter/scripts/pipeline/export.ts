// export — produce dist/<job>/book.pdf (+ epub/web optionally) and a hashed manifest.
// Input:  build/<job>/preview.pdf, meta.json, manifest.json
// Output: dist/<job>/book.pdf, manifest.json (+ optional book.epub)
// State:  typeset → exported

import * as fs from "node:fs/promises";
import * as path from "node:path";
import * as crypto from "node:crypto";
import { spawn } from "node:child_process";
import { buildJobDir, distJobDir, ensureDir, exists } from "./paths.ts";
import { readState, writeState, recordError, type State } from "./state.ts";

type Meta = {
  title: string;
  authors: string[];
  lang: string;
};

function runProc(cmd: string, args: string[]): Promise<{ code: number; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { shell: false });
    const stderrChunks: Buffer[] = [];
    child.stderr.on("data", (c) => stderrChunks.push(c));
    child.on("close", (code) => {
      resolve({ code: code ?? -1, stderr: Buffer.concat(stderrChunks).toString("utf8") });
    });
    child.on("error", (e) => resolve({ code: -1, stderr: String(e) }));
  });
}

async function sha256(filePath: string): Promise<string> {
  const buf = await fs.readFile(filePath);
  return crypto.createHash("sha256").update(buf).digest("hex");
}

async function runExport(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  if (!(await exists(jobDir))) throw new Error(`job not found: ${jobId}`);

  const state = await readState(jobDir);
  if (state.stage !== "typeset" && state.stage !== "exported") {
    throw new Error(`expected stage=typeset, got ${state.stage}`);
  }
  if (!state.ok) throw new Error(`upstream failure (state.ok=false); refusing to export`);

  const meta: Meta = JSON.parse(await fs.readFile(path.join(jobDir, "meta.json"), "utf8"));

  const dist = await distJobDir(jobId);
  await ensureDir(dist);

  const outputs: Record<string, { ok: boolean; reason?: string; sha256?: string }> = {};

  // 1. PDF — copy preview.pdf
  const preview = path.join(jobDir, "preview.pdf");
  if (!(await exists(preview))) {
    throw new Error(`preview.pdf missing; typeset stage did not complete cleanly`);
  }
  const pdfDst = path.join(dist, "book.pdf");
  await fs.copyFile(preview, pdfDst);
  outputs["book.pdf"] = { ok: true, sha256: await sha256(pdfDst) };

  // 2. EPUB (optional)
  if (state.outputs.includes("epub")) {
    const bodyMd = path.join(jobDir, "body.md");
    const epubDst = path.join(dist, "book.epub");
    if (!(await exists(bodyMd))) {
      outputs["book.epub"] = { ok: false, reason: "body.md missing" };
    } else {
      const args = [
        bodyMd,
        "-o",
        epubDst,
        "--metadata",
        `title=${meta.title}`,
        "--metadata",
        `lang=${meta.lang}`,
      ];
      for (const a of meta.authors) args.push("--metadata", `author=${a}`);
      const res = await runProc("pandoc", args);
      if (res.code === 0 && (await exists(epubDst))) {
        outputs["book.epub"] = { ok: true, sha256: await sha256(epubDst) };
      } else {
        outputs["book.epub"] = {
          ok: false,
          reason: res.stderr.trim() || `pandoc exit ${res.code}`,
        };
      }
    }
  }

  // 3. Manifest
  const manifest = {
    jobId,
    builtAt: new Date().toISOString(),
    title: meta.title,
    authors: meta.authors,
    lang: meta.lang,
    outputs,
  };
  await fs.writeFile(path.join(dist, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8");

  const next: State = { ...state, stage: "exported", ok: true };
  await writeState(jobDir, next);

  console.log(`exported: ${jobId}`);
  for (const [name, info] of Object.entries(outputs)) {
    const tag = info.ok ? "✓" : "✗";
    const detail = info.ok ? `sha256:${info.sha256!.slice(0, 8)}` : info.reason!;
    console.log(`  [${tag}] ${name} (${detail})`);
  }
  console.log(`  dist/${jobId}/`);
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: export.ts <job-id>\n");
    process.exit(1);
  }
  try {
    await runExport(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`export: ${msg}\n`);
    try {
      const jobDir = await buildJobDir(jobId);
      if (await exists(jobDir)) {
        await recordError(jobDir, `export: ${msg}`);
        const state = await readState(jobDir).catch(() => null);
        if (state) await writeState(jobDir, { ...state, ok: false, errors: [msg] });
      }
    } catch {}
    process.exit(1);
  }
}

main();
