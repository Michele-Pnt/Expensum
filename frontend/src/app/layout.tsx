import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import ThemeRegistry from "@/theme/ThemeRegistry";
import { AppRouterCacheProvider } from '@mui/material-nextjs/v15-appRouter';

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Traky / Moneo",
  description: "Finance Tracker and AI Assistant",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="it" suppressHydrationWarning>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
      </head>
      <body className={inter.className} suppressHydrationWarning>
        <AppRouterCacheProvider>
          <ThemeRegistry>
            {children}
          </ThemeRegistry>
        </AppRouterCacheProvider>
      </body>
    </html>
  );
}
