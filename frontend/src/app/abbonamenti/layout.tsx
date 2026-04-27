"use client";

import React from "react";
import { Box } from "@mui/material";
import Sidebar from "@/components/Sidebar";

export default function AbbonamentiLayout({ children }: { children: React.ReactNode }) {
  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
      <Sidebar />
      <Box component="main" sx={{ flexGrow: 1, width: { sm: `calc(100% - 240px)` } }}>
        {children}
      </Box>
    </Box>
  );
}
