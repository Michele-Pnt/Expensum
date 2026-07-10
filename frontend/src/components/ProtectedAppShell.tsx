"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Box, CircularProgress, Typography, IconButton, useMediaQuery, useTheme } from "@mui/material";
import { Menu as MenuIcon } from "lucide-react";
import Sidebar from "./Sidebar";
import { TourProvider } from "@/context/TourContext";
import TourOverlay from "./TourOverlay";

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
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopOpen, setDesktopOpen] = useState(true);

  const [authStatus, setAuthStatus] = useState<AuthStatus>(() => {
    const { isTelegram } = getTelegramContext();
    return { phase: "loading", isTelegram };
  });

  const handleDrawerToggle = () => {
    if (isMobile) {
      setMobileOpen(!mobileOpen);
    } else {
      setDesktopOpen(!desktopOpen);
    }
  };

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

  if (authStatus.isTelegram) {
    return (
      <TourProvider>
        <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>{children}</Box>
        <TourOverlay />
      </TourProvider>
    );
  }

  return (
    <TourProvider>
      <Box sx={{ display: "flex", height: ["100vh", "100dvh"], overflow: "hidden", bgcolor: "background.default" }}>
        <Sidebar mobileOpen={mobileOpen} desktopOpen={desktopOpen} onToggle={handleDrawerToggle} isMobile={isMobile} />
        <Box
          component="main"
          data-tour="tour-final"
          sx={{
            flexGrow: 1,
            width: { sm: desktopOpen ? "calc(100% - 240px)" : "100%" },
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            overflow: "hidden",
          }}
        >
          <Box sx={{ flexGrow: 1, overflowY: "auto", minHeight: 0, display: "flex", flexDirection: "column", position: "relative" }}>
            {(!desktopOpen || isMobile) && (
              <IconButton
                onClick={handleDrawerToggle}
                data-action="sidebar-open"
                sx={{
                  position: "absolute",
                  top: 16,
                  left: 16,
                  zIndex: 30,
                  bgcolor: "background.paper",
                  boxShadow: 1,
                  border: "1px solid var(--color-border)",
                }}
              >
                <MenuIcon size={20} />
              </IconButton>
            )}
            {children}
          </Box>
        </Box>
      </Box>
      <TourOverlay />
    </TourProvider>
  );
}
