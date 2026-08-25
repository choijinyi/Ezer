// 의존성 점검: node, pandoc, typst, mmdc, ANTHROPIC_API_KEY.
// 단계별로 실제로 필요한 것만 fail. 누락은 경고로 안내.

import { spawnSync } from "node:child_process";

type DepStatus = {
  name: string;
  required: boolean;
  found: boolean;
  version?: string;
  reason?: string;
};

function check(cmd: string, args: string[] = ["--version"]): { ok: boolean; out: string } {
  try {
    const res = spawnSync(cmd, args, { encoding: "utf8", shell: true });
    if (res.status === 0) {
      return { ok: true, out: (res.stdout || res.stderr).trim().split(/\r?\n/)[0] ?? "" };
    }
    return { ok: false, out: (res.stderr || res.stdout || "").trim() };
  } catch (e) {
    return { ok: false, out: String(e) };
  }
}

const deps: DepStatus[] = [];

const node = check("node");
deps.push({ name: "node", required: true, found: node.ok, version: node.out });

const pandoc = check("pandoc");
deps.push({
  name: "pandoc",
  required: true,
  found: pandoc.ok,
  version: pandoc.out,
  reason: "MD → Typst conversion (typeset stage)",
});

const typst = check("typst");
deps.push({
  name: "typst",
  required: true,
  found: typst.ok,
  version: typst.out,
  reason: "PDF compilation (typeset stage)",
});

const mmdc = check("mmdc");
deps.push({
  name: "mmdc (Mermaid CLI)",
  required: false,
  found: mmdc.ok,
  version: mmdc.out,
  reason: "render-figures stage; needed only if manuscripts use <!-- fig: type=mermaid -->",
});

const apiKey = !!process.env.ANTHROPIC_API_KEY;
deps.push({
  name: "ANTHROPIC_API_KEY",
  required: false,
  found: apiKey,
  version: apiKey ? "set" : "",
  reason: "polish-proposer / cover-designer LLM stages",
});

let hardFail = 0;
let softWarn = 0;

console.log("bookwriter — dependency check\n");
for (const d of deps) {
  const tag = d.found ? "✓" : d.required ? "✗" : "·";
  const ver = d.version ? ` ${d.version}` : "";
  console.log(`  [${tag}] ${d.name}${ver}`);
  if (!d.found && d.reason) console.log(`        ${d.reason}`);
  if (!d.found && d.required) hardFail++;
  if (!d.found && !d.required) softWarn++;
}

console.log();
if (hardFail > 0) {
  console.log(`${hardFail} required dependencies missing. Pipeline cannot run end-to-end.`);
  process.exit(1);
}
if (softWarn > 0) {
  console.log(`${softWarn} optional dependencies missing. Some stages will be unavailable.`);
}
console.log("ok");
