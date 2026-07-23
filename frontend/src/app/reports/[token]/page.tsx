"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

/**
 * I vecchi link diretti (es. quelli inviati su Telegram prima che la lettura
 * dei report richiedesse login) atterravano qui come pagina pubblica. Ora la
 * lettura richiede sempre l'autenticazione: si rimanda alla lista report,
 * che apre subito la scheda corrispondente al token.
 */
export default function LegacyReportTokenRedirect() {
  const params = useParams();
  const router = useRouter();
  const token = params?.token as string;

  useEffect(() => {
    router.replace(`/reports${token ? `?highlight=${encodeURIComponent(token)}` : ""}`);
  }, [token, router]);

  return null;
}
