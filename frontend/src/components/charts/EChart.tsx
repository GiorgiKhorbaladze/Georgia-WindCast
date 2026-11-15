"use client";

import type { EChartsCoreOption, EChartsType } from "echarts/core";
import { useEffect, useRef } from "react";

/** Minimal ECharts host: lazy-loads the library, resizes with its container, disposes cleanly. */
export function EChart({
  option,
  height = 320,
  ariaLabel,
  className,
}: {
  option: EChartsCoreOption;
  height?: number;
  ariaLabel: string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);
  const latest = useRef(option);

  useEffect(() => {
    latest.current = option;
    chart.current?.setOption(option, true);
  }, [option]);

  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | null = null;
    (async () => {
      const echarts = await import("echarts");
      if (disposed || !ref.current) return;
      chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
      chart.current.setOption(latest.current, true);
      observer = new ResizeObserver(() => chart.current?.resize());
      observer.observe(ref.current);
    })();
    return () => {
      disposed = true;
      observer?.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  return <div ref={ref} role="img" aria-label={ariaLabel} className={className} style={{ height, width: "100%" }} />;
}
