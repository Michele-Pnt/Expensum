import { getTranslations } from "next-intl/server";
import { routing } from "@/i18n/routing";
import { localeAlternates } from "@/i18n/seo";
import MutuoCalculatorClient from "./MutuoCalculatorClient";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "MutuoCalculator.meta" });
  return {
    title: t("title"),
    description: t("description"),
    alternates: localeAlternates("/mutuo"),
  };
}

export default function MutuoPage() {
  return <MutuoCalculatorClient />;
}
