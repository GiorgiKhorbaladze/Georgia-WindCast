import { formatTbilisiMinute, formatTbilisiShort } from "./format";

export const COLORS = {
  actual: "#22d3ee",
  model: "#2dd4bf",
  forecast: "#a78bfa",
  reanalysis: "#94a3b8",
  gap: "rgba(251,191,36,0.12)",
  gapBorder: "rgba(251,191,36,0.45)",
  grid: "rgba(103,232,249,0.08)",
  axis: "#64748b",
  text: "#94a3b8",
};

export function tbilisiAxisLabel(withDate: boolean) {
  return (value: number) => formatTbilisiShort(value, withDate);
}

export function tbilisiTooltipTime() {
  return (value: number | string) => formatTbilisiMinute(value) ?? "";
}

export const baseChart = {
  backgroundColor: "transparent",
  textStyle: { color: COLORS.text, fontFamily: "Inter Variable, Noto Sans Georgian, sans-serif" },
  animationDuration: 400,
  grid: { left: 52, right: 20, top: 36, bottom: 56, containLabel: false },
  tooltip: {
    trigger: "axis",
    backgroundColor: "rgba(6,13,24,0.95)",
    borderColor: "rgba(103,232,249,0.25)",
    textStyle: { color: "#dbe7f3", fontSize: 12 },
  },
};
