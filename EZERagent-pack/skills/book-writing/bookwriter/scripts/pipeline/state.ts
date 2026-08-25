import { z } from "zod";
import * as fs from "node:fs/promises";
import * as path from "node:path";

export const StageSchema = z.enum([
  "created",
  "ingested",
  "structured",
  "normalized",
  "polish-proposed",
  "polished",
  "illustrated",
  "typeset",
  "exported",
]);
export type Stage = z.infer<typeof StageSchema>;

export const OutputSchema = z.enum(["pdf", "epub", "web"]);
export type Output = z.infer<typeof OutputSchema>;

export const StateSchema = z.object({
  jobId: z.string(),
  manuscript: z.string(),
  stage: StageSchema,
  ok: z.boolean(),
  needsApproval: z.boolean().default(false),
  createdAt: z.string(),
  updatedAt: z.string(),
  template: z.string(),
  outputs: z.array(OutputSchema).default(["pdf"]),
  polish: z.boolean().default(false),
  errors: z.array(z.string()).optional(),
  pages: z.number().optional(),
  applied: z.number().optional(),
  skipped: z.number().optional(),
  coverSource: z.enum(["user", "generated"]).optional(),
});
export type State = z.infer<typeof StateSchema>;

export async function readState(jobDir: string): Promise<State> {
  const p = path.join(jobDir, "state.json");
  const raw = await fs.readFile(p, "utf8");
  return StateSchema.parse(JSON.parse(raw));
}

export async function writeState(
  jobDir: string,
  state: State
): Promise<void> {
  state.updatedAt = new Date().toISOString();
  const p = path.join(jobDir, "state.json");
  const tmp = p + ".tmp";
  await fs.writeFile(tmp, JSON.stringify(state, null, 2), "utf8");
  await fs.rename(tmp, p);
}

const LOCK_STALE_MS = 5_000;

export async function acquireLock(jobDir: string): Promise<() => Promise<void>> {
  const lockPath = path.join(jobDir, ".lock");
  const tryAcquire = async (): Promise<boolean> => {
    try {
      const fh = await fs.open(lockPath, "wx");
      await fh.writeFile(`${process.pid}\n${new Date().toISOString()}\n`);
      await fh.close();
      return true;
    } catch (e: unknown) {
      const err = e as NodeJS.ErrnoException;
      if (err.code === "EEXIST") {
        try {
          const stat = await fs.stat(lockPath);
          if (Date.now() - stat.mtimeMs > LOCK_STALE_MS) {
            await fs.unlink(lockPath).catch(() => {});
            return tryAcquire();
          }
        } catch {}
        return false;
      }
      throw e;
    }
  };
  if (!(await tryAcquire())) {
    throw new Error(
      `job locked: ${path.basename(jobDir)} (.lock present, not stale)`
    );
  }
  return async () => {
    await fs.unlink(lockPath).catch(() => {});
  };
}

export async function recordError(jobDir: string, msg: string): Promise<void> {
  const p = path.join(jobDir, "errors.log");
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  await fs.appendFile(p, line, "utf8");
}
