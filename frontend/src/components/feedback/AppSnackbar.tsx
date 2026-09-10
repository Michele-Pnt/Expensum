"use client";

import { Alert, Snackbar } from "@mui/material";
import type { SnackbarState } from "./useSnackbar";

interface AppSnackbarProps {
  snack: SnackbarState;
  onClose: () => void;
}

/** Snackbar di esito standard dell'app: usare con `useSnackbar()`. */
export default function AppSnackbar({ snack, onClose }: AppSnackbarProps) {
  return (
    <Snackbar open={snack.open} autoHideDuration={4000} onClose={onClose}>
      <Alert severity={snack.severity} onClose={onClose}>
        {snack.msg}
      </Alert>
    </Snackbar>
  );
}
