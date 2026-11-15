import { cookies } from "next/headers";

import { getDictionary, LOCALE_COOKIE, resolveLocale, type Locale } from "./i18n";

export async function getLocale(): Promise<Locale> {
  const store = await cookies();
  return resolveLocale(store.get(LOCALE_COOKIE)?.value);
}

export async function getI18n() {
  const locale = await getLocale();
  return { locale, t: getDictionary(locale) };
}
