"use client";

import { useState } from "react";

export interface SnackbarState {
  open: boolean;
  msg: string;
  severity: "success" | "error";
}

/**
 * Stato di uno snackbar di esito (successo/errore), prima duplicato identico
 * in goals/mutuo/spazio. Usare insieme a `<AppSnackbar />`.
 */
export function useSnackbar() {
  const [snack, setSnack] = useState<SnackbarState>({ open: false, msg: "", severity: "success" });

  const showSuccess = (msg: string) => setSnack({ open: true, msg, severity: "success" });
  const showError = (msg: string) => setSnack({ open: true, msg, severity: "error" });
  const close = () => setSnack((current) => ({ ...current, open: false }));

  return { snack, showSuccess, showError, close };
}
