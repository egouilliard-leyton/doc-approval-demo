import { describe, expect, it } from "vitest";
import { mapWithConcurrency } from "@/lib/concurrency";

/** A deferred that resolves when the caller flips it, for interleaving control. */
function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("mapWithConcurrency", () => {
  it("never runs more than `limit` workers at once", async () => {
    const items = [0, 1, 2, 3, 4, 5, 6];
    let active = 0;
    let peak = 0;
    await mapWithConcurrency(items, 3, async (n) => {
      active++;
      peak = Math.max(peak, active);
      // Yield so sibling runners get a chance to start before we release.
      await new Promise((r) => setTimeout(r, 1));
      active--;
      return n;
    });
    expect(peak).toBe(3);
  });

  it("collects both successes and failures per item, in input order", async () => {
    const items = ["a", "b", "c", "d"];
    const results = await mapWithConcurrency(items, 2, async (s) => {
      if (s === "b") throw new Error("boom-b");
      return s.toUpperCase();
    });
    expect(results.map((r) => r.item)).toEqual(["a", "b", "c", "d"]);
    expect(results[0]).toEqual({ item: "a", ok: true, value: "A" });
    expect(results[2]).toEqual({ item: "c", ok: true, value: "C" });
    expect(results[3]).toEqual({ item: "d", ok: true, value: "D" });
    const failed = results[1];
    expect(failed.ok).toBe(false);
    if (!failed.ok) expect((failed.error as Error).message).toBe("boom-b");
  });

  it("preserves order even when later items resolve first", async () => {
    const gate = deferred();
    const results = await mapWithConcurrency([0, 1], 2, async (n) => {
      // Item 0 waits for item 1 to resolve, so completion order is reversed.
      if (n === 0) await gate.promise;
      else gate.resolve();
      return n * 10;
    });
    expect(results.map((r) => (r.ok ? r.value : null))).toEqual([0, 10]);
  });

  it("does not reject the whole batch when every item fails", async () => {
    const results = await mapWithConcurrency([1, 2], 2, async () => {
      throw new Error("nope");
    });
    expect(results.every((r) => !r.ok)).toBe(true);
    expect(results).toHaveLength(2);
  });

  it("returns an empty array for no items", async () => {
    const results = await mapWithConcurrency([], 3, async (x) => x);
    expect(results).toEqual([]);
  });
});
