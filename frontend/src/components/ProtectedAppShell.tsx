"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Box, CircularProgress, Typography, useMediaQuery, useTheme } from "@mui/material";
import DesktopNavigation from "./navigation/DesktopNavigation";
import MobileNavigation from "./navigation/MobileNavigation";
import QuickCapture from "./QuickCapture";
import NotificationBell from "./NotificationBell";
import { TourProvider } from "@/context/TourContext";
import TourOverlay from "./TourOverlay";

// Spazio riservato in basso su mobile: altezza della bottom bar (~64px) più la
// sporgenza del pulsante centrale "Registra", che ne esce di ~16px verso l'alto.
// Senza questo margine il FAB coprirebbe l'ultimo elemento di ogni pagina.
const MOBILE_BAR_HEIGHT = 80;
const DESKTOP_RAIL_WIDTH = 220;

type AuthStatus =
  | { phase: "loading"; isTelegram: boolean }
  | { phase: "authorized"; isTelegram: boolean }
  | { phase: "unauthorized"; isTelegram: boolean; message: string };

type TelegramWebApp = {
  initData?: string;
};

type TelegramWindow = Window & {
  Telegram?: {
    WebApp?: TelegramWebApp;
  };
};

function getTelegramContext() {
  if (typeof window === "undefined") {
    return { isTelegram: false, initData: "" };
  }

  const telegramWindow = window as TelegramWindow;
  const webApp = telegramWindow.Telegram?.WebApp;
  const initData = webApp?.initData ?? "";
  return {
    isTelegram: Boolean(webApp) && initData.length > 0,
    initData,
  };
}

export default function ProtectedAppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const theme = useTheme();
  // Unico breakpoint dell'app shell: sotto i 900 px bottom bar, sopra sidebar.
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const [captureOpen, setCaptureOpen] = useState(false);

  const [authStatus, setAuthStatus] = useState<AuthStatus>(() => {
    const { isTelegram } = getTelegramContext();
    return { phase: "loading", isTelegram };
  });

  // Aprire il composer non cambia rotta: resta un overlay sulla pagina corrente.
  const openCapture = useCallback(() => setCaptureOpen(true), []);
  const closeCapture = useCallback(() => setCaptureOpen(false), []);
  const openManage = useCallback(() => router.push("/spazio"), [router]);

  useEffect(() => {
    let cancelled = false;
    const { isTelegram, initData } = getTelegramContext();
    const headers: HeadersInit = initData ? { "X-Telegram-Init-Data": initData } : {};

    fetch("/api/auth/session", {
      headers,
      credentials: "same-origin",
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP_${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        if (cancelled) return;
        if (data?.redirect_to) {
          window.location.assign(data.redirect_to);
          return;
        }
        setAuthStatus({ phase: "authorized", isTelegram });
      })
      .catch(() => {
        if (cancelled) return;
        if (isTelegram) {
          setAuthStatus({
            phase: "unauthorized",
            isTelegram,
            message: "Sessione non valida. Riapri la mini-app dal bot per continuare.",
          });
          return;
        }
        router.replace("/login");
      });

    return () => {
      cancelled = true;
    };
  }, [router]);

  if (authStatus.phase === "loading") {
    return (
      <Box
        sx={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          bgcolor: "background.default",
        }}
      >
        <CircularProgress color="primary" />
      </Box>
    );
  }

  if (authStatus.phase === "unauthorized") {
    return (
      <Box
        sx={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          px: 3,
          textAlign: "center",
          bgcolor: "background.default",
        }}
      >
        <Typography color="text.secondary">{authStatus.message}</Typography>
      </Box>
    );
  }

  // Web e Telegram condividono la stessa shell responsive: cambia solo il modo in
  // cui la sessione viene autenticata, non la navigazione.
  return (
    <TourProvider>
      <Box sx={{ display: "flex", height: ["100vh", "100dvh"], overflow: "hidden", bgcolor: "background.default" }}>
        {!isMobile && (
          <Box sx={{ width: DESKTOP_RAIL_WIDTH, flexShrink: 0, height: "100%" }}>
            <DesktopNavigation onOpenCapture={openCapture} />
          </Box>
        )}

        <Box
          component="main"
          data-tour="tour-final"
          sx={{
            flexGrow: 1,
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            overflow: "hidden",
            position: "relative",
          }}
        >
          <Box
            sx={{
              position: "absolute",
              top: 8,
              right: 8,
              zIndex: (theme) => theme.zIndex.appBar,
            }}
          >
            <NotificationBell />
          </Box>
          <Box
            sx={{
              flexGrow: 1,
              overflowY: "auto",
              minHeight: 0,
              display: "flex",
              flexDirection: "column",
              position: "relative",
              // La bottom bar è fissa: senza questo spazio l'ultimo elemento di
              // ogni pagina finirebbe sotto la barra.
              pb: isMobile ? `calc(${MOBILE_BAR_HEIGHT}px + env(safe-area-inset-bottom))` : 0,
            }}
          >
            {children}
          </Box>
        </Box>
      </Box>

      {isMobile && <MobileNavigation onOpenCapture={openCapture} />}

      <QuickCapture
        open={captureOpen}
        onClose={closeCapture}
        onOpenManage={openManage}
        isMobile={isMobile}
      />
      <TourOverlay />
    </TourProvider>
  );
}
