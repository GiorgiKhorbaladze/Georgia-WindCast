import { setLocale } from "@/app/actions";
import { LOCALES, type Locale } from "@/lib/i18n";

const LABELS: Record<Locale, { short: string; full: string }> = {
  ka: { short: "GE", full: "ქართული" },
  en: { short: "EN", full: "English" },
};

/** Server Action form: works without client JavaScript and keeps the cookie server-set. */
export function LanguageSwitch({ current, label }: { current: Locale; label: string }) {
  return (
    <form action={setLocale} role="group" aria-label={label} className="flex rounded-md border border-line p-0.5 text-xs">
      {LOCALES.map((locale) => (
        <button
          key={locale}
          type="submit"
          name="locale"
          value={locale}
          lang={locale}
          aria-pressed={locale === current}
          aria-label={LABELS[locale].full}
          className={`rounded px-2.5 py-1 font-mono font-semibold tracking-wider transition-colors ${
            locale === current ? "bg-cyan-glow/15 text-cyan-glow" : "text-slate-400 hover:text-slate-100"
          }`}
        >
          {LABELS[locale].short}
        </button>
      ))}
    </form>
  );
}
