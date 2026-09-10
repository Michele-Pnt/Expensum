"use client";

import { Alert, Button, type SxProps, type Theme } from "@mui/material";

interface ErrorBannerProps {
  message: string | null | undefined;
  onRetry?: () => void;
  sx?: SxProps<Theme>;
}

/** Banner di errore standard dell'app: prima riscritto ad-hoc in più pagine
 * (analytics, impostazioni, invita, mutuo). Non renderizza nulla se `message`
 * è vuoto, così può stare sempre montato nel JSX del chiamante. */
export default function ErrorBanner({ message, onRetry, sx }: ErrorBannerProps) {
  if (!message) return null;
  return (
    <Alert
      severity="error"
      sx={{ mb: 3, ...sx }}
      action={onRetry ? <Button color="inherit" size="small" onClick={onRetry}>Riprova</Button> : undefined}
    >
      {message}
    </Alert>
  );
}
