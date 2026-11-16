"use server";

import { cookies } from "next/headers";

import { LOCALE_COOKIE, resolveLocale } from "@/lib/i18n";
import { publicUrl } from "@/lib/site";

export async function setLocale(formData: FormData): Promise<void> {
  const locale = resolveLocale(String(formData.get("locale") ?? ""));
  // The only cookie: an allow-listed language code. Not readable by scripts; HTTPS-only once the
  // site runs on its approved https origin (a plain-HTTP private pilot still works).
  (await cookies()).set(LOCALE_COOKIE, locale, {
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
    sameSite: "lax",
    httpOnly: true,
    secure: publicUrl() !== null,
  });
}
