import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { routing } from "@/i18n/routing";
import { localeAlternates } from "@/i18n/seo";
import LandingPageClient from "./LandingPageClient";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Landing.meta" });
  return {
    title: t("title"),
    description: t("description"),
    alternates: localeAlternates(""),
  };
}

export default function LandingPage() {
  return <LandingPageClient />;
}
