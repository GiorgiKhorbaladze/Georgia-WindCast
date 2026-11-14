import { getI18n } from "@/lib/locale-server";

export default async function AboutPage() {
  const { t } = await getI18n();
  return (
    <article className="wc-panel mx-auto max-w-3xl p-6 sm:p-8">
      <h1 className="text-2xl font-semibold text-white">{t.about.title}</h1>
      <div className="mt-5 space-y-4 leading-relaxed text-slate-300">
        {t.about.paragraphs.map((p) => (
          <p key={p}>{p}</p>
        ))}
      </div>
      <p className="mt-6 text-sm text-slate-500">{t.timezoneNote}</p>
    </article>
  );
}
