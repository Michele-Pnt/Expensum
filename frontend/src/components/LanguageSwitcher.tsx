"use client";

import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";

const LOCALE_LABELS: Record<string, string> = {
  it: "IT",
  en: "EN",
};

export default function LanguageSwitcher() {
  const locale = useLocale();
  const t = useTranslations("LanguageSwitcher");
  const pathname = usePathname();
  const router = useRouter();

  return (
    <div style={{ display: "flex", gap: 4 }} aria-label={t("label")}>
      {routing.locales.map((loc) => (
        <button
          key={loc}
          type="button"
          onClick={() => router.replace(pathname, { locale: loc })}
          aria-current={loc === locale ? "true" : undefined}
          style={{
            border: "none",
            background: "none",
            cursor: loc === locale ? "default" : "pointer",
            fontWeight: loc === locale ? 700 : 400,
            opacity: loc === locale ? 1 : 0.55,
            fontSize: "0.85rem",
            padding: "4px 6px",
          }}
        >
          {LOCALE_LABELS[loc] ?? loc}
        </button>
      ))}
    </div>
  );
}
