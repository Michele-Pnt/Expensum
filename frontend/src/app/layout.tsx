import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import ThemeRegistry from "@/theme/ThemeRegistry";
import { AppRouterCacheProvider } from '@mui/material-nextjs/v15-appRouter';
import { PostHogProvider } from "@/components/PostHogProvider";
import CookieConsentBanner from "@/components/CookieConsent";

const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700", "800"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Expensum — Il tuo compagno del risparmio",
  description: "Traccia le spese via Telegram, capisci i tuoi soldi, vivi meglio. Powered by Gemini AI.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="it" className={inter.variable} suppressHydrationWarning>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
        <Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive" />
        {/*
          GA4, Meta Pixel e PostHog sono caricati condizionalmente da CookieConsentBanner
          in base al consenso dell'utente (GDPR). Non caricare qui script di tracking.
        */}
      </head>
      <body className={inter.variable} suppressHydrationWarning>
        <PostHogProvider>
          <AppRouterCacheProvider>
            <ThemeRegistry>
              {children}
            </ThemeRegistry>
          </AppRouterCacheProvider>
        </PostHogProvider>
        <CookieConsentBanner />
      </body>
    </html>
  );
}
