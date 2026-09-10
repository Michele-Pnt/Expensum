import type { Metadata, Viewport } from "next";
import { Sora } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import ThemeRegistry from "@/theme/ThemeRegistry";
import { AppRouterCacheProvider } from '@mui/material-nextjs/v15-appRouter';
import CookieConsentBanner from "@/components/CookieConsent";
import PageViewTracker from "@/components/PageViewTracker";

const sora = Sora({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-sora",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Expensum: il tuo compagno del risparmio",
  description: "Traccia le spese in pochi secondi, capisci i tuoi soldi, vivi meglio. Basato su intelligenza artificiale.",
  manifest: "/site.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Expensum",
  },
  icons: {
    apple: "/apple-touch-icon.png",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#1C363D",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="it" className={sora.variable} suppressHydrationWarning>
      <head>
        <Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive" />
        {/*
          GA4, Meta Pixel e PostHog non caricano script nel browser: gli eventi
          sono inoltrati server-side da /api/track (vedi src/lib/analytics.ts),
          in base al consenso raccolto da CookieConsentBanner (GDPR).
        */}
      </head>
      <body className={sora.variable} suppressHydrationWarning>
        <AppRouterCacheProvider>
          <ThemeRegistry>
            {children}
          </ThemeRegistry>
        </AppRouterCacheProvider>
        <CookieConsentBanner />
        <PageViewTracker />
      </body>
    </html>
  );
}
