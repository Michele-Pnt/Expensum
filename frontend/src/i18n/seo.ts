import { routing } from "./routing";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://expensum.it";

export function localeAlternates(pathname: string) {
  const languages: Record<string, string> = {};
  for (const locale of routing.locales) {
    languages[locale] = `${SITE_URL}/${locale}${pathname}`;
  }
  languages["x-default"] = `${SITE_URL}/${routing.defaultLocale}${pathname}`;
  return { languages };
}
