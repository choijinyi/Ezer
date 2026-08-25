import * as path from "node:path";
import * as fs from "node:fs/promises";

export async function findRepoRoot(start: string = process.cwd()): Promise<string> {
  let dir = path.resolve(start);
  while (true) {
    try {
      await fs.access(path.join(dir, "AGENTS.md"));
      return dir;
    } catch {
      const parent = path.dirname(dir);
      if (parent === dir) {
        throw new Error("repo root not found (no AGENTS.md in any ancestor)");
      }
      dir = parent;
    }
  }
}

let cachedRoot: string | null = null;
export async function repoRoot(): Promise<string> {
  if (!cachedRoot) cachedRoot = await findRepoRoot();
  return cachedRoot;
}

export async function buildJobDir(jobId: string): Promise<string> {
  return path.join(await repoRoot(), "build", jobId);
}

export async function distJobDir(jobId: string): Promise<string> {
  return path.join(await repoRoot(), "dist", jobId);
}

export async function manuscriptDir(name: string): Promise<string> {
  return path.join(await repoRoot(), "manuscripts", name);
}

export async function templateDir(id: string): Promise<string> {
  return path.join(await repoRoot(), "templates", id);
}

export async function ensureDir(p: string): Promise<void> {
  await fs.mkdir(p, { recursive: true });
}

export async function exists(p: string): Promise<boolean> {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

export function newJobId(): string {
  const now = new Date();
  const pad = (n: number, w = 2) => n.toString().padStart(w, "0");
  const stamp =
    now.getUTCFullYear().toString() +
    pad(now.getUTCMonth() + 1) +
    pad(now.getUTCDate()) +
    "-" +
    pad(now.getUTCHours()) +
    pad(now.getUTCMinutes()) +
    pad(now.getUTCSeconds());
  const rand = Math.random().toString(36).slice(2, 8);
  return `${stamp}-${rand}`;
}
