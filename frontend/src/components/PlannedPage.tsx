import type { Dictionary } from "@/lib/i18n";

const ISSUE_BASE = "https://github.com/GiorgiKhorbaladze/Georgia-WindCast/issues/";

export function PlannedPage({ t, title, issue }: { t: Dictionary; title: string; issue: number }) {
  return (
    <section className="wc-panel mx-auto max-w-2xl p-6 sm:p-8">
      <h1 className="text-2xl font-semibold text-white">{title}</h1>
      <p className="wc-label mt-4">{t.planned.title}</p>
      <p className="mt-2 text-slate-300">{t.planned.body}</p>
      <p className="mt-4 text-sm text-slate-400">
        <a className="text-cyan-glow hover:underline" href={`${ISSUE_BASE}${issue}`} rel="noreferrer" target="_blank">
          {t.planned.issue} #{issue}
        </a>
      </p>
    </section>
  );
}
