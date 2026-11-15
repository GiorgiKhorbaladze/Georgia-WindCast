import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource/noto-sans-georgian/400.css";
import "@fontsource/noto-sans-georgian/600.css";
import "./globals.css";

import type { Metadata, Viewport } from "next";

import { Header } from "@/components/Header";
import { getI18n } from "@/lib/locale-server";
import { openGraphBase } from "@/lib/pageMeta";
import { indexingAllowed, OG_IMAGE, publicUrl, SITE_NAME } from "@/lib/site";

export async function generateMetadata(): Promise<Metadata> {
  const { locale, t } = await getI18n();
  const base = publicUrl();
  const index = indexingAllowed();
  return {
    metadataBase: base ?? undefined,
    applicationName: SITE_NAME,
    title: { default: t.meta.defaultTitle, template: `%s · ${SITE_NAME}` },
    description: t.meta.description,
    robots: index ? { index: true, follow: true } : { index: false, follow: false },
    openGraph: openGraphBase(locale, t, t.meta.defaultTitle, t.meta.description),
    twitter: { card: "summary_large_image", title: t.meta.defaultTitle, description: t.meta.description, images: [OG_IMAGE.url] },
  };
}

export const viewport: Viewport = {
  themeColor: "#03070e",
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const { locale, t } = await getI18n();
  return (
    <html lang={locale === "ka" ? "ka" : "en"} className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <div className="wc-backdrop" aria-hidden="true" />
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-ink-800 focus:px-3 focus:py-2"
        >
          {t.skip}
        </a>
        <Header t={t} locale={locale} />
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
          {children}
        </main>
        <footer className="border-t border-line">
          <div className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-4 text-xs text-slate-400 sm:flex-row sm:justify-between sm:gap-6 sm:px-6">
            <span>{t.footer} {t.independence}</span>
            <span className="shrink-0">{t.timezoneNote}</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
