export type Tone = "ok" | "warn" | "bad" | "neutral";

const TONES: Record<Tone, string> = {
  ok: "border-teal-glow/40 bg-teal-glow/10 text-teal-glow",
  warn: "border-amber-warn/40 bg-amber-warn/10 text-amber-warn",
  bad: "border-rose-warn/40 bg-rose-warn/10 text-rose-warn",
  neutral: "border-slate-500/40 bg-slate-500/10 text-slate-300",
};

export function StatusBadge({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full bg-current ${tone === "ok" ? "wc-pulse" : ""}`} />
      {children}
    </span>
  );
}
