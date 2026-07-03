// Bounded-concurrency map: run at most `limit` workers over `items`, collecting a
// per-item outcome (success OR failure) rather than rejecting the whole batch on the
// first error. Used to fan out per-member case work (upload/OCR/classify, extract) so
// one document's failure never blocks its siblings. Pure — no React, no globals.

/** One item's outcome: the original item plus a tagged success/failure result. */
export type SettledResult<T, R> = { item: T } & (
  | { ok: true; value: R }
  | { ok: false; error: unknown }
);

/**
 * Map `worker` over `items` with at most `limit` concurrent invocations. Results are
 * returned in input order regardless of completion order, and every item settles: a
 * worker that rejects yields `{ ok: false, error }` instead of failing the batch.
 */
export async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<Array<SettledResult<T, R>>> {
  const results = new Array<SettledResult<T, R>>(items.length);
  // A shared cursor: each runner grabs the next unclaimed index until they're gone.
  let cursor = 0;
  const runnerCount = Math.max(1, Math.min(limit, items.length));

  async function runner(): Promise<void> {
    for (;;) {
      const index = cursor++;
      if (index >= items.length) return;
      const item = items[index];
      try {
        const value = await worker(item, index);
        results[index] = { item, ok: true, value };
      } catch (error) {
        results[index] = { item, ok: false, error };
      }
    }
  }

  await Promise.all(Array.from({ length: runnerCount }, () => runner()));
  return results;
}
