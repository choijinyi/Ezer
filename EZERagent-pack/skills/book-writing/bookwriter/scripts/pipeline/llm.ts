// LLM 호출 단일 진입점.
// Anthropic SDK 직접 호출. 응답을 build/<job>/llm-cache/ 에 캐시.

import Anthropic from "@anthropic-ai/sdk";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import * as crypto from "node:crypto";
import { repoRoot } from "./paths.ts";

const DEFAULT_MODEL = "claude-haiku-4-5";

export type CallAgentOpts = {
  model?: string;
  maxTokens?: number;
  cacheDir?: string;
};

type AgentFile = {
  frontmatter: Record<string, string>;
  body: string;
};

export async function loadAgentPrompt(filePath: string): Promise<AgentFile> {
  const raw = await fs.readFile(filePath, "utf8");
  return parseAgentFile(raw);
}

function parseAgentFile(raw: string): AgentFile {
  const m = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!m) return { frontmatter: {}, body: raw };
  const fm: Record<string, string> = {};
  for (const line of m[1]!.split("\n")) {
    const mm = line.match(/^([a-zA-Z_-]+):\s*(.+?)\s*$/);
    if (mm) fm[mm[1]!] = mm[2]!;
  }
  return { frontmatter: fm, body: m[2]! };
}

function cacheKey(model: string, system: string, user: string): string {
  return crypto
    .createHash("sha256")
    .update(model)
    .update("\0")
    .update(system)
    .update("\0")
    .update(user)
    .digest("hex");
}

export async function callAgent(
  agentFile: string,
  userMessage: string,
  opts: CallAgentOpts = {}
): Promise<string> {
  const root = await repoRoot();
  const fullPath = path.isAbsolute(agentFile) ? agentFile : path.join(root, agentFile);
  const agent = await loadAgentPrompt(fullPath);
  const systemPrompt = agent.body;
  const model = opts.model || agent.frontmatter.model || DEFAULT_MODEL;
  const maxTokens = opts.maxTokens ?? 4096;

  let cacheFile: string | null = null;
  if (opts.cacheDir) {
    const cacheDir = path.join(opts.cacheDir, "llm-cache");
    await fs.mkdir(cacheDir, { recursive: true });
    cacheFile = path.join(cacheDir, `${cacheKey(model, systemPrompt, userMessage)}.json`);
    try {
      const cached = JSON.parse(await fs.readFile(cacheFile, "utf8"));
      if (typeof cached.text === "string") return cached.text;
    } catch {}
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error("ANTHROPIC_API_KEY not set; cannot call LLM agent");
  }

  const client = new Anthropic({ apiKey });
  const resp = await client.messages.create({
    model,
    max_tokens: maxTokens,
    system: systemPrompt,
    messages: [{ role: "user", content: userMessage }],
  });

  const text = resp.content
    .filter((b): b is Anthropic.TextBlock => b.type === "text")
    .map((b) => b.text)
    .join("");

  if (cacheFile) {
    await fs.writeFile(
      cacheFile,
      JSON.stringify(
        {
          text,
          model,
          inputTokens: resp.usage?.input_tokens,
          outputTokens: resp.usage?.output_tokens,
          cachedAt: new Date().toISOString(),
        },
        null,
        2
      ),
      "utf8"
    );
  }

  return text;
}
