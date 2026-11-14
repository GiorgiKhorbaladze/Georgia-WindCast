import { GenerationExplorer } from "@/components/GenerationChart";
import { getGenerationHistory } from "@/lib/api";
import { getI18n } from "@/lib/locale-server";

export default async function HistoryPage() {
  const [{ locale, t }, history] = await Promise.all([getI18n(), getGenerationHistory()]);
  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-2xl font-semibold text-white">{t.history.pageTitle}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">{t.history.note}</p>
      </header>
      <section className="wc-panel p-4 sm:p-6">
        <GenerationExplorer initial={history.ok ? history.data : null} locale={locale} />
      </section>
    </div>
  );
}
