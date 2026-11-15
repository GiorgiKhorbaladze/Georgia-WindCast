import type { Metadata } from "next";

import type { Dictionary, Locale } from "./i18n";
import { getI18n } from "./locale-server";
import { OG_IMAGE, publicUrl, SITE_NAME } from "./site";

type PageKey = keyof Dictionary["meta"]["pages"];
type OpenGraph = NonNullable<Metadata["openGraph"]>;

/**
 * Open Graph fields shared by every page. Next.js replaces (does not merge) a parent's openGraph
 * object when a page defines its own, so pages must start from this base.
 */
export function openGraphBase(locale: Locale, t: Dictionary, title: string, description: string, path?: string): OpenGraph {
  return {
    type: "website",
    siteName: SITE_NAME,
    title,
    description,
    locale: locale === "ka" ? "ka_GE" : "en_US",
    alternateLocale: locale === "ka" ? ["en_US"] : ["ka_GE"],
    url: publicUrl() && path ? path : undefined,
    images: [{ ...OG_IMAGE, alt: t.meta.ogAlt }],
  };
}

/** Per-page title, description, canonical path and Open Graph text in the visitor's language. */
export async function pageMetadata(key: PageKey, path: string): Promise<Metadata> {
  const { locale, t } = await getI18n();
  const { title, description } = t.meta.pages[key];
  return {
    title,
    description,
    alternates: publicUrl() ? { canonical: path } : undefined,
    openGraph: openGraphBase(locale, t, title, description, path),
    twitter: { card: "summary_large_image", title, description, images: [OG_IMAGE.url] },
  };
}

/** The dashboard keeps the site-wide title and description and adds its canonical URL. */
export async function homeMetadata(): Promise<Metadata> {
  const { locale, t } = await getI18n();
  if (!publicUrl()) return {};
  return {
    alternates: { canonical: "/" },
    openGraph: openGraphBase(locale, t, t.meta.defaultTitle, t.meta.description, "/"),
  };
}
