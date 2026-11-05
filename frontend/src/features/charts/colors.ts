"use client";

/**
 * Resolve a CSS custom property (which may be an oklch() value) into an
 * rgba() string that canvas-based chart libraries understand.
 */
let ctx: CanvasRenderingContext2D | null = null;

export function cssVarToRgba(name: string, alpha?: number): string {
  if (typeof window === "undefined") return "rgba(0,0,0,1)";
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  if (!ctx) {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    ctx = canvas.getContext("2d", { willReadFrequently: true });
  }
  if (!ctx) return raw;
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillStyle = raw;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  const finalAlpha = alpha ?? Math.round(((a ?? 255) / 255) * 100) / 100;
  return `rgba(${r},${g},${b},${finalAlpha})`;
}

export function chartPalette() {
  return {
    background: cssVarToRgba("--card"),
    text: cssVarToRgba("--muted-foreground"),
    grid: cssVarToRgba("--chart-grid"),
    border: cssVarToRgba("--border"),
    gain: cssVarToRgba("--gain"),
    loss: cssVarToRgba("--loss"),
    gainSoft: cssVarToRgba("--gain", 0.35),
    lossSoft: cssVarToRgba("--loss", 0.35),
    c1: cssVarToRgba("--chart-1"),
    c2: cssVarToRgba("--chart-2"),
    c3: cssVarToRgba("--chart-3"),
    c4: cssVarToRgba("--chart-4"),
    c5: cssVarToRgba("--chart-5"),
    band: cssVarToRgba("--chart-2", 0.55),
    muted: cssVarToRgba("--muted-foreground", 0.5),
  };
}
