"use server";

import { cookies } from "next/headers";

import { LOCALE_COOKIE, resolveLocale } from "@/lib/i18n";

export async function setLocale(formData: FormData): Promise<void> {
  const locale = resolveLocale(String(formData.get("locale") ?? ""));
  (await cookies()).set(LOCALE_COOKIE, locale, {
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
    sameSite: "lax",
  });
}
