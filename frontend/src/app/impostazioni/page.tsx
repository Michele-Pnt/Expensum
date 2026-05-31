"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Alert,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

type SettingsResponse = {
  chat_id: string;
  auth_mode: string;
  account: {
    email?: string | null;
    first_name?: string | null;
    last_name?: string | null;
    telegram_connected: boolean;
    telegram_chat_id?: string | null;
    storage_backend?: string | null;
    is_active: boolean;
  };
  plan: {
    plan_type: string;
    tokens_total: number;
    tokens_used_current_cycle: number;
    tokens_reserved_current_cycle: number;
    tokens_remaining: number;
    tokens_usage_percent: number;
    tokens_reset_at?: string | null;
    alert?: string | null;
  };
};

function formatResetDate(value?: string | null): string {
  if (!value) return "n/d";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/d";
  return date.toLocaleDateString("it-IT");
}

export default function ImpostazioniPage() {
  const router = useRouter();
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"logout" | "delete" | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/settings", { credentials: "same-origin" });
      if (!res.ok) throw new Error("settings_fetch_failed");
      const json = await res.json();
      setData(json);
    } catch {
      setError("Non sono riuscito a caricare le impostazioni. Riprova tra poco.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  async function handleSuspendAccount() {
    setBusy("logout");
    setError(null);
    try {
      const res = await fetch("/api/settings/logout", {
        method: "POST",
        credentials: "same-origin",
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error("logout_failed");
      window.location.assign(json.redirect_url || "/login");
    } catch {
      setError("Non sono riuscito a sospendere l'account. Riprova.");
      setBusy(null);
    }
  }

  async function handleDeleteAccount() {
    setBusy("delete");
    setError(null);
    try {
      const res = await fetch("/api/settings/delete-account", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: deleteConfirm }),
      });
      const json = await res.json();
      if (!res.ok || !json.ok) {
        throw new Error(json.error || "delete_failed");
      }
      window.location.assign(json.redirect_url || "/login");
    } catch {
      setError("Eliminazione account non riuscita. Controlla la conferma e riprova.");
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <CircularProgress color="primary" />
      </Box>
    );
  }

  return (
    <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 980 }}>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" fontWeight={800} color="primary.main" gutterBottom>
          Impostazioni
        </Typography>
        <Typography color="text.secondary">
          Qui raccogliamo le azioni che su Telegram vivevano come comandi: accesso, logout, piano e gestione account.
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {data && (
        <Stack spacing={3}>
          <Card sx={{ borderRadius: 4 }}>
            <CardContent>
              <Typography variant="h6" fontWeight={700} gutterBottom>
                Accesso
              </Typography>
              <Stack spacing={1.5}>
                <Typography color="text.secondary">
                  {data.account.email
                    ? `Sei connesso come ${data.account.email}.`
                    : "Account senza email associata."}
                </Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Chip label={`Backend: ${(data.account.storage_backend || "notion").toUpperCase()}`} />
                  <Chip label={data.account.telegram_connected ? "Telegram collegato" : "Telegram non collegato"} />
                  <Chip label={data.auth_mode === "telegram" ? "Sessione Telegram" : "Sessione Web"} />
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  Per cambiare account puoi sospendere l&apos;account corrente e tornare alla schermata di login.
                </Typography>
              </Stack>
            </CardContent>
            <CardActions sx={{ px: 2, pb: 2, pt: 0 }}>
              <Button variant="outlined" onClick={() => window.location.assign("/logout")}>
                Cambia account
              </Button>
              <Button
                color="warning"
                variant="contained"
                onClick={handleSuspendAccount}
                disabled={busy !== null}
              >
                {busy === "logout" ? "Sospensione..." : "Sospendi account e logout"}
              </Button>
            </CardActions>
          </Card>

          <Card sx={{ borderRadius: 4 }}>
            <CardContent>
              <Typography variant="h6" fontWeight={700} gutterBottom>
                Piano
              </Typography>
              <Stack spacing={1.5}>
                <Typography>
                  Piano attuale: <strong>{data.plan.plan_type.toUpperCase()}</strong>
                </Typography>
                <Typography color="text.secondary">
                  Token usati: {data.plan.tokens_used_current_cycle.toLocaleString("it-IT")} | Riservati:{" "}
                  {data.plan.tokens_reserved_current_cycle.toLocaleString("it-IT")} | Rimanenti:{" "}
                  {data.plan.tokens_remaining.toLocaleString("it-IT")} / {data.plan.tokens_total.toLocaleString("it-IT")}
                </Typography>
                <Typography color="text.secondary">
                  Utilizzo ciclo corrente: {data.plan.tokens_usage_percent}% | Reset previsto: {formatResetDate(data.plan.tokens_reset_at)}
                </Typography>
                {data.plan.alert && (
                  <Alert severity={data.plan.alert === "exhausted" ? "error" : "warning"}>
                    {data.plan.alert === "exhausted"
                      ? "Hai esaurito i token del ciclo corrente."
                      : "Stai raggiungendo il limite token del ciclo corrente."}
                  </Alert>
                )}
              </Stack>
            </CardContent>
            <CardActions sx={{ px: 2, pb: 2, pt: 0 }}>
              <Button variant="contained" onClick={() => router.push("/abbonamenti")}>
                Gestisci piano
              </Button>
            </CardActions>
          </Card>

          <Card sx={{ borderRadius: 4, border: "1px solid rgba(211, 47, 47, 0.24)" }}>
            <CardContent>
              <Typography variant="h6" fontWeight={700} color="error.main" gutterBottom>
                Zona pericolosa
              </Typography>
              <Typography color="text.secondary" sx={{ mb: 2 }}>
                Questa azione elimina definitivamente account, impostazioni e dati locali. I dati presenti nel tuo workspace Notion non vengono toccati.
              </Typography>
              <TextField
                label='Scrivi "DELETE" per confermare'
                value={deleteConfirm}
                onChange={(e) => setDeleteConfirm(e.target.value)}
                fullWidth
              />
            </CardContent>
            <CardActions sx={{ px: 2, pb: 2, pt: 0 }}>
              <Button
                color="error"
                variant="contained"
                onClick={handleDeleteAccount}
                disabled={busy !== null || deleteConfirm.trim().toUpperCase() !== "DELETE"}
              >
                {busy === "delete" ? "Eliminazione..." : "Elimina account"}
              </Button>
            </CardActions>
          </Card>
        </Stack>
      )}
    </Box>
  );
}
