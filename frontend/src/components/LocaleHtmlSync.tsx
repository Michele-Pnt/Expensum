"use client";

import { useEffect } from "react";

export default function LocaleHtmlSync({ locale }: { locale: string }) {
  useEffect(() => {
    document.documentElement.lang = locale;
    return () => {
      document.documentElement.lang = "it";
    };
  }, [locale]);

  return null;
}
