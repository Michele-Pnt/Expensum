import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import LegalChrome from "@/components/legal/LegalChrome";
import ContattiContentIt from "@/components/legal/ContattiContentIt";
import ContattiContentEn from "@/components/legal/ContattiContentEn";
import { routing } from "@/i18n/routing";
import { localeAlternates } from "@/i18n/seo";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const isEn = locale === "en";
  return {
    title: isEn ? "Contact us | Expensum" : "Contatti | Expensum",
    description: isEn
      ? "How to get in touch with the Expensum team: email, feedback and social channels."
      : "Come contattare il team di Expensum: email, feedback e canali social.",
    alternates: localeAlternates("/contatti"),
  };
}

export default async function ContattiPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const isEn = locale === "en";

  return (
    <LegalChrome
      title={isEn ? "Contact us" : "Contatti"}
      subtitle={
        isEn
          ? "Assistance, business inquiries, feedback and social channels."
          : "Assistenza, richieste commerciali, feedback e canali social."
      }
    >
      {isEn ? <ContattiContentEn /> : <ContattiContentIt />}
    </LegalChrome>
  );
}
