// render-figures — process <!-- fig: id=... type=mermaid|raw -->...<!-- /fig --> markers.
// Input:  build/<job>/edited/*.md
// Output: build/<job>/figures/<id>.svg, <id>.caption.txt
// Sub-stage of illustrate.ts (no own state transition)

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { spawn } from "node:child_process";
import { buildJobDir, ensureDir, exists } from "./paths.ts";

type FigMarker = {
  id: string;
  type: string;
  caption: string;
  body: string;
  chapter: string;
};

function parseAttrs(s: string): Record<string, string> {
  const out: Record<string, string> = {};
  const re = /(\w+)=(?:"([^"]*)"|(\S+))/g;
  let m;
  while ((m = re.exec(s))) {
    out[m[1]!] = m[2] ?? m[3] ?? "";
  }
  return out;
}

function extractMarkers(text: string, chapter: string): FigMarker[] {
  const out: FigMarker[] = [];
  const re = /<!--\s*fig:\s*([^>]+?)\s*-->\n([\s\S]*?)\n<!--\s*\/fig\s*-->/g;
  let m;
  let i = 0;
  while ((m = re.exec(text))) {
    const attrs = parseAttrs(m[1]!);
    out.push({
      id: attrs.id ?? `fig-${++i}`,
      type: attrs.type ?? "raw",
      caption: attrs.caption ?? "",
      body: m[2]!,
      chapter,
    });
  }
  return out;
}

function spawnP(cmd: string, args: string[]): Promise<{ code: number; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { shell: false });
    let stderr = "";
    child.stderr.on("data", (c) => (stderr += c.toString()));
    child.on("close", (code) => resolve({ code: code ?? -1, stderr }));
    child.on("error", (e) => resolve({ code: -1, stderr: String(e) }));
  });
}

async function renderMermaid(body: string, dst: string): Promise<{ ok: boolean; reason?: string }> {
  const tmp = dst + ".mmd";
  await fs.writeFile(tmp, body, "utf8");
  const r = await spawnP("mmdc", ["-i", tmp, "-o", dst, "-b", "transparent"]);
  await fs.unlink(tmp).catch(() => {});
  if (r.code === 0) return { ok: true };
  return { ok: false, reason: r.stderr.trim() || `mmdc exit ${r.code}` };
}

async function renderFigures(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  const editedDir = path.join(jobDir, "edited");
  if (!(await exists(editedDir))) return;

  const files = (await fs.readdir(editedDir)).filter((f) => f.endsWith(".md")).sort();
  const allMarkers: FigMarker[] = [];
  for (const f of files) {
    const text = await fs.readFile(path.join(editedDir, f), "utf8");
    allMarkers.push(...extractMarkers(text, f));
  }

  if (allMarkers.length === 0) {
    console.log("render-figures: no markers");
    return;
  }

  const figDir = path.join(jobDir, "figures");
  await ensureDir(figDir);

  let ok = 0;
  let failed = 0;
  for (const m of allMarkers) {
    const svgPath = path.join(figDir, `${m.id}.svg`);
    const captionPath = path.join(figDir, `${m.id}.caption.txt`);

    if (m.type === "mermaid") {
      const r = await renderMermaid(m.body, svgPath);
      if (r.ok) ok++;
      else {
        failed++;
        console.log(`  [✗] ${m.id} (${m.chapter}): ${r.reason}`);
      }
    } else if (m.type === "raw") {
      await fs.writeFile(svgPath, m.body.trim() + "\n", "utf8");
      ok++;
    } else {
      console.log(`  [·] ${m.id} (${m.chapter}): type=${m.type} unsupported, skipped`);
      failed++;
    }

    if (m.caption) {
      await fs.writeFile(captionPath, m.caption + "\n", "utf8");
    }
  }

  console.log(`render-figures: ${ok} ok, ${failed} failed`);
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: render-figures.ts <job-id>\n");
    process.exit(1);
  }
  try {
    await renderFigures(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`render-figures: ${msg}\n`);
    process.exit(1);
  }
}

main();
