"use client";

import React from "react";
import { Box } from "@mui/material";
import { usePathname } from "next/navigation";
import ProtectedAppShell from "@/components/ProtectedAppShell";

export default function ReportsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublicSharedReport = /^\/reports\/[^/]+$/.test(pathname);

  if (isPublicSharedReport) {
    return <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>{children}</Box>;
  }

  return <ProtectedAppShell>{children}</ProtectedAppShell>;
}
