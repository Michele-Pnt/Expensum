"use client";

import React from "react";
import ProtectedAppShell from "@/components/ProtectedAppShell";

export default function ImpostazioniLayout({ children }: { children: React.ReactNode }) {
  return <ProtectedAppShell>{children}</ProtectedAppShell>;
}
