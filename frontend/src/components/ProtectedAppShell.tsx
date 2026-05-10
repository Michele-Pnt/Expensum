"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Box, CircularProgress, Typography } from "@mui/material";
import Sidebar from "./Sidebar";

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
  const [authStatus, setAuthStatus] = useState<AuthStatus>(() => {
    const { isTelegram } = getTelegramContext();
    return { phase: "loading", isTelegram };
  });

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
    return <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>{children}</Box>;
  }

  return (
    <Box sx={{ display: "flex", minHeight: "100vh", bgcolor: "background.default" }}>
      <Sidebar />
      <Box component="main" sx={{ flexGrow: 1, width: { sm: "calc(100% - 240px)" } }}>
        {children}
      </Box>
    </Box>
  );
}
