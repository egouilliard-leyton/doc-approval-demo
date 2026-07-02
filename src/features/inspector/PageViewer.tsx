import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { fileUrl } from "@/lib/api";
import { scaleRects } from "@/lib/grounding";
import type { DocRegion } from "@/lib/highlights";
import type { PageInfo } from "@/lib/types";

export function PageViewer({
  pages,
  page,
  regions,
  selectedKey,
  hoveredKey,
  flashTick,
  onPageChange,
}: {
  pages: PageInfo[];
  page: number;
  regions: DocRegion[]; // all pages; filtered to `page` here
  selectedKey: string | null;
  hoveredKey: string | null;
  flashTick: number; // bumped on each select so the flash replays even if re-clicked
  onPageChange: (page: number) => void;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const selectedBoxRef = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState({ width: 0, height: 0 });
  const [displayed, setDisplayed] = useState({ width: 0, height: 0 });

  // Track the rendered <img> size so we can scale natural-pixel bboxes onto it.
  useEffect(() => {
    const el = imgRef.current;
    if (!el) return;
    const update = () =>
      setDisplayed({ width: el.clientWidth, height: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [page]);

  // Scroll the selected box into view when the selection (or its replay) changes.
  useLayoutEffect(() => {
    selectedBoxRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "center",
      inline: "center",
    });
  }, [selectedKey, flashTick, displayed.width]);

  const current = pages.find((p) => p.page === page) ?? pages[0];
  const pageRegions = regions.filter((r) => r.page === page);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="relative flex-1 overflow-auto rounded-xl border bg-muted/40 p-4">
        <div className="relative mx-auto w-fit">
          <img
            ref={imgRef}
            src={fileUrl(current?.image_url)}
            alt={`Page ${page}`}
            className="max-h-[68vh] w-auto rounded-md shadow-sm ring-1 ring-border"
            onLoad={(e) => {
              const t = e.currentTarget;
              setNatural({ width: t.naturalWidth, height: t.naturalHeight });
              setDisplayed({ width: t.clientWidth, height: t.clientHeight });
            }}
          />
          {pageRegions.map((region) => {
            const scaled = scaleRects(region.rects, natural, displayed);
            const isSelected = region.key === selectedKey;
            const active = isSelected || region.key === hoveredKey;
            return scaled.map((r, i) => (
              <div
                // Include flashTick on the selected box so it remounts and replays
                // the flash animation even when the same field is clicked again.
                key={`${region.key}:${i}:${isSelected ? flashTick : ""}`}
                ref={isSelected && i === 0 ? selectedBoxRef : undefined}
                className={cn(
                  "pointer-events-none absolute rounded-sm transition-all",
                  isSelected && "hl-flash",
                )}
                style={{
                  left: r.x,
                  top: r.y,
                  width: r.width,
                  height: r.height,
                  borderStyle: "solid",
                  borderColor: region.color,
                  backgroundColor: `${region.color}${active ? "33" : "1f"}`,
                  borderWidth: isSelected ? 3 : 2,
                  opacity: active ? 1 : 0.7,
                  boxShadow: isSelected
                    ? `0 0 0 2px ${region.color}55`
                    : undefined,
                }}
              />
            ));
          })}
        </div>
      </div>

      {pages.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {pages.map((p) => (
            <button
              key={p.page}
              onClick={() => onPageChange(p.page)}
              className={cn(
                "shrink-0 overflow-hidden rounded-md border-2 transition-colors",
                p.page === page
                  ? "border-brand"
                  : "border-transparent hover:border-border",
              )}
            >
              <img
                src={fileUrl(p.thumbnail_url)}
                alt={`Page ${p.page} thumbnail`}
                className="h-16 w-auto"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
