/** Turn time-stamped points into chart data with explicit breaks at gaps (never interpolated). */

export interface TimeRangeIso {
  start: string;
  end: string;
}

export type ChartDatum = [number, number | null];

/**
 * Insert a null datum inside every gap so that line charts break instead of drawing a straight
 * segment across missing data.
 */
export function withGapBreaks<T>(
  points: T[],
  time: (p: T) => string,
  value: (p: T) => number | null,
  gaps: TimeRangeIso[],
): ChartDatum[] {
  const out: ChartDatum[] = points.map((p) => [Date.parse(time(p)), value(p)]);
  for (const g of gaps) {
    const s = Date.parse(g.start);
    const e = Date.parse(g.end);
    out.push([s + (e - s) / 2, null]);
  }
  return out.sort((a, b) => a[0] - b[0]);
}

/** Break a series wherever consecutive points are further apart than maxStepMs. */
export function breakOnStep(data: ChartDatum[], maxStepMs: number): ChartDatum[] {
  const out: ChartDatum[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i > 0 && data[i][0] - data[i - 1][0] > maxStepMs) {
      out.push([(data[i][0] + data[i - 1][0]) / 2, null]);
    }
    out.push(data[i]);
  }
  return out;
}
