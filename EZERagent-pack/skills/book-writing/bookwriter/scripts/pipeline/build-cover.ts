// build-cover — produce cover.<ext>: user-supplied wins; else LLM; else deterministic SVG.
// Input:  build/<job>/meta.json (userCover?), cover-user.<ext> if present
// Output: build/<job>/cover.<ext>, meta.json updated with coverFile
// Sub-stage of illustrate.ts (no own state transition)

import * as fs from "node:fs/promises";
import * as path from "node:path";
import { buildJobDir, exists } from "./paths.ts";
import { readState, writeState } from "./state.ts";
import { callAgent } from "./llm.ts";

type Meta = {
  title: string;
  subtitle?: string;
  authors: string[];
  lang: string;
  userCover?: string | null;
  coverFile?: string;
};

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function wrapTitle(title: string, maxChars: number): string[] {
  if (title.length <= maxChars) return [title];
  const mid = Math.floor(title.length / 2);
  let bestSplit = -1;
  let bestDist = Infinity;
  for (let i = 0; i < title.length; i++) {
    if (title[i] === " ") {
      const d = Math.abs(i - mid);
      if (d < bestDist) {
        bestDist = d;
        bestSplit = i;
      }
    }
  }
  if (bestSplit !== -1) {
    return [title.slice(0, bestSplit), title.slice(bestSplit + 1)];
  }
  // No space — hard split
  return [title.slice(0, mid), title.slice(mid)];
}

function deterministicCoverSvg(meta: Meta): string {
  const title = meta.title || "Untitled";
  const sub = meta.subtitle || "";
  const author = meta.authors.length ? meta.authors.join(", ") : "";
  const lang = meta.lang || "ko";
  const fontFamily =
    lang === "ko"
      ? "&apos;Noto Serif KR&apos;, &apos;Source Serif 4&apos;, serif"
      : "&apos;Source Serif 4&apos;, Georgia, serif";

  const titleLines = wrapTitle(title, lang === "ko" ? 14 : 22);
  const titleSize = titleLines.length === 1 ? 120 : 100;
  const lineH = titleSize + 30;
  const titleStartY = 760 - ((titleLines.length - 1) * lineH) / 2;

  let titleSvg = "";
  for (let i = 0; i < titleLines.length; i++) {
    const y = titleStartY + i * lineH;
    titleSvg += `\n    <text x="740" y="${y}" text-anchor="middle" font-size="${titleSize}" font-weight="bold" fill="#1e3a8a">${escapeXml(titleLines[i]!)}</text>`;
  }

  let subSvg = "";
  if (sub) {
    const subY = titleStartY + titleLines.length * lineH + 50;
    subSvg = `\n    <text x="740" y="${subY}" text-anchor="middle" font-size="44" fill="#1e3a8a" font-style="italic">${escapeXml(sub)}</text>`;
  }

  let authorSvg = "";
  if (author) {
    authorSvg = `\n    <text x="740" y="1750" text-anchor="middle" font-size="50" fill="#1e3a8a">${escapeXml(author)}</text>`;
  }

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1480 2100" width="1480" height="2100">
  <rect width="1480" height="2100" fill="#fbf9f4"/>
  <line x1="540" y1="1100" x2="940" y2="1100" stroke="#1e3a8a" stroke-width="2"/>
  <g font-family="${fontFamily}">${titleSvg}${subSvg}${authorSvg}
  </g>
</svg>
`;
}

function isLikelySvg(s: string): boolean {
  const trimmed = s.trim();
  return trimmed.startsWith("<svg") || trimmed.startsWith("<?xml");
}

function stripCodeFences(s: string): string {
  return s
    .trim()
    .replace(/^```[a-zA-Z]*\n/, "")
    .replace(/\n```\s*$/, "")
    .trim();
}

async function tryLlmCover(jobDir: string, meta: Meta): Promise<string | null> {
  try {
    const userMsg = JSON.stringify({
      title: meta.title,
      subtitle: meta.subtitle ?? "",
      authors: meta.authors,
      lang: meta.lang,
    });
    const resp = await callAgent(".claude/agents/cover-designer.md", userMsg, {
      cacheDir: jobDir,
      maxTokens: 8192,
    });
    const cleaned = stripCodeFences(resp);
    if (!isLikelySvg(cleaned)) return null;
    if (cleaned.length > 100_000) return null; // sanity
    return cleaned;
  } catch (e) {
    process.stderr.write(`build-cover: LLM unavailable (${(e as Error).message}); using fallback\n`);
    return null;
  }
}

async function buildCover(jobId: string): Promise<void> {
  const jobDir = await buildJobDir(jobId);
  const state = await readState(jobDir);
  const metaPath = path.join(jobDir, "meta.json");
  const meta: Meta = JSON.parse(await fs.readFile(metaPath, "utf8"));

  let coverFileName: string;
  let source: "user" | "generated";

  if (meta.userCover) {
    const ext = path.extname(meta.userCover).slice(1).toLowerCase();
    const dst = path.join(jobDir, `cover.${ext}`);
    const src = path.join(jobDir, meta.userCover);
    if (!(await exists(src))) {
      throw new Error(`meta.userCover points to ${meta.userCover}, but file is missing`);
    }
    await fs.copyFile(src, dst);
    coverFileName = `cover.${ext}`;
    source = "user";
  } else {
    let svg = await tryLlmCover(jobDir, meta);
    if (!svg) {
      svg = deterministicCoverSvg(meta);
    }
    const dst = path.join(jobDir, "cover.svg");
    await fs.writeFile(dst, svg, "utf8");
    coverFileName = "cover.svg";
    source = "generated";
  }

  meta.coverFile = coverFileName;
  await fs.writeFile(metaPath, JSON.stringify(meta, null, 2) + "\n", "utf8");

  await writeState(jobDir, { ...state, coverSource: source });

  console.log(`build-cover: ${coverFileName} (${source})`);
}

async function main(): Promise<void> {
  const jobId = process.argv[2];
  if (!jobId) {
    process.stderr.write("usage: build-cover.ts <job-id>\n");
    process.exit(1);
  }
  try {
    await buildCover(jobId);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    process.stderr.write(`build-cover: ${msg}\n`);
    process.exit(1);
  }
}

main();
