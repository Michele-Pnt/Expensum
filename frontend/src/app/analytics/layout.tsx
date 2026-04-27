"use client";

import React, { useEffect, useState } from "react";
import { Box } from "@mui/material";
import Sidebar from "@/components/Sidebar";

export default function AnalyticsLayout({ children }: { children: React.ReactNode }) {
  const [isTelegram, setIsTelegram] = useState(false);

  useEffect(() => {
    if ((window as any).Telegram?.WebApp) setIsTelegram(true);
  }, []);

  if (isTelegram) {
    // Nessuna Sidebar, nessun padding laterale: full-screen per la Mini App Telegram
    return <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>{children}</Box>;
  }

  return (
    <Box sx={{ display: "flex", minHeight: "100vh", bgcolor: "background.default" }}>
      <Sidebar />
      <Box component="main" sx={{ flexGrow: 1, width: { sm: `calc(100% - 240px)` } }}>
        {children}
      </Box>
    </Box>
  );
}
