import Link from "next/link";

import type { Dictionary, Locale } from "@/lib/i18n";

import { LanguageSwitch } from "./LanguageSwitch";
import { NavLinks } from "./NavLinks";

export function Header({ t, locale }: { t: Dictionary; locale: Locale }) {
  const items = [
    { href: "/", label: t.nav.dashboard },
    { href: "/map", label: t.nav.map },
    { href: "/history", label: t.nav.history },
    { href: "/forecast", label: t.nav.forecast },
    { href: "/about", label: t.nav.about },
  ];
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-ink-950/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center justify-between gap-4">
          <Link href="/" className="group flex items-center gap-3">
            <WindGlyph />
            <span>
              <span className="block font-mono text-base font-bold tracking-[0.22em] text-white">
                {t.appName}
              </span>
              <span className="block text-[11px] text-slate-400">{t.tagline}</span>
            </span>
          </Link>
          <div className="lg:hidden">
            <LanguageSwitch current={locale} label={t.languageLabel} />
          </div>
        </div>
        <div className="flex items-center gap-4">
          <NavLinks items={items} label={t.appName} />
          <div className="hidden lg:block">
            <LanguageSwitch current={locale} label={t.languageLabel} />
          </div>
        </div>
      </div>
    </header>
  );
}

function WindGlyph() {
  return (
    <svg aria-hidden="true" viewBox="0 0 32 32" className="h-8 w-8 text-cyan-glow">
      <circle cx="16" cy="16" r="15" fill="none" stroke="currentColor" strokeOpacity="0.25" />
      <path
        d="M6 12h13a3 3 0 1 0-3-3M6 17h18a3 3 0 1 1-3 3M6 22h9"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
