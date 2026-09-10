"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getCsrfToken } from "@/lib/csrf";
import {
  Alert,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";

type PreferencesResponse = {
  notifications_enabled?: boolean;
};

type SettingsResponse = {
  account?: {
    first_name?: string | null;
    last_name?: string | null;
    privacy_policy_version_accepted?: string | null;
    privacy_policy_current_version?: string;
  };
};

async function downloadFile(url: string, filename: string): Promise<void> {
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error || "download_failed");
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export default function PrivacyPage() {
  const router = useRouter();
  const [busy, setBusy] = useState<
    "json" | "csv" | "delete" | "notifications" | "name" | "email" | "password" | "consent" | null
  >(null);
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [policyAccepted, setPolicyAccepted] = useState<string | null>(null);
  const [policyCurrent, setPolicyCurrent] = useState<string | null>(null);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [currentPasswordForEmail, setCurrentPasswordForEmail] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [currentPasswordForPassword, setCurrentPasswordForPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");

  const loadPreferences = useCallback(async () => {
    try {
      const res = await fetch("/api/user/preferences", { credentials: "same-origin" });
      if (!res.ok) return;
      const json: PreferencesResponse = await res.json();
      if (typeof json.notifications_enabled === "boolean") {
        setNotificationsEnabled(json.notifications_enabled);
      }
    } catch {
      // Preferenze non disponibili: mantiene il default.
    }
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const res = await fetch("/api/settings", { credentials: "same-origin" });
      if (!res.ok) return;
      const json: SettingsResponse = await res.json();
      setPolicyAccepted(json.account?.privacy_policy_version_accepted ?? null);
      setPolicyCurrent(json.account?.privacy_policy_current_version ?? null);
      setFirstName(json.account?.first_name ?? "");
      setLastName(json.account?.last_name ?? "");
    } catch {
      // Stato consenso non disponibile: il banner resta nascosto.
    }
  }, []);

  useEffect(() => {
    loadPreferences();
    loadSettings();
  }, [loadPreferences, loadSettings]);

  async function handleAcceptPolicy() {
    setBusy("consent");
    setError(null);
    setInfo(null);
    try {
      const csrfToken = await getCsrfToken();
      const res = await fetch("/api/privacy/accept-policy", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error();
      setPolicyAccepted(json.privacy_policy_version_accepted);
      setInfo("Privacy policy accettata.");
    } catch {
      setError("Non sono riuscito a registrare l'accettazione. Riprova.");
    } finally {
      setBusy(null);
    }
  }

  async function handleChangeName() {
    setBusy("name");
    setError(null);
    setInfo(null);
    try {
      const csrfToken = await getCsrfToken();
      const res = await fetch("/api/settings/change-name", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ first_name: firstName, last_name: lastName }),
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json.error || "change_name_failed");
      setInfo("Nome aggiornato con successo.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Non sono riuscito ad aggiornare il nome.");
    } finally {
      setBusy(null);
    }
  }

  async function handleChangeEmail() {
    setBusy("email");
    setError(null);
    setInfo(null);
    try {
      const csrfToken = await getCsrfToken();
      const res = await fetch("/api/settings/change-email", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ new_email: newEmail, current_password: currentPasswordForEmail }),
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json.error || "change_email_failed");
      setInfo("Email aggiornata con successo.");
      setNewEmail("");
      setCurrentPasswordForEmail("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Non sono riuscito ad aggiornare l'email.");
    } finally {
      setBusy(null);
    }
  }

  async function handleChangePassword() {
    if (newPassword !== newPasswordConfirm) {
      setError("Le nuove password non coincidono.");
      return;
    }
    setBusy("password");
    setError(null);
    setInfo(null);
    try {
      const csrfToken = await getCsrfToken();
      const res = await fetch("/api/settings/change-password", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({
          current_password: currentPasswordForPassword,
          new_password: newPassword,
        }),
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json.error || "change_password_failed");
      setInfo("Password aggiornata con successo.");
      setCurrentPasswordForPassword("");
      setNewPassword("");
      setNewPasswordConfirm("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Non sono riuscito ad aggiornare la password.");
    } finally {
      setBusy(null);
    }
  }

  async function handleExportJson() {
    setBusy("json");
    setError(null);
    setInfo(null);
    try {
      await downloadFile("/api/privacy/export-json", `expensum_dati_${Date.now()}.json`);
      setInfo("Export completato: controlla i download del browser.");
    } catch {
      setError("Non sono riuscito a generare l'export JSON. Riprova tra poco.");
    } finally {
      setBusy(null);
    }
  }

  async function handleExportCsv() {
    setBusy("csv");
    setError(null);
    setInfo(null);
    try {
      await downloadFile("/api/privacy/export-csv", `expensum_transazioni_${Date.now()}.csv`);
      setInfo("Export completato: controlla i download del browser.");
    } catch (e) {
      setError(
        e instanceof Error && e.message !== "download_failed"
          ? e.message
          : "Non sono riuscito a generare l'export CSV. Se usi il backend Notion, esporta direttamente da notion.so."
      );
    } finally {
      setBusy(null);
    }
  }

  async function handleToggleNotifications() {
    const next = !notificationsEnabled;
    setBusy("notifications");
    setError(null);
    try {
      const csrfToken = await getCsrfToken();
      const res = await fetch("/api/user/preferences", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ notifications_enabled: next }),
      });
      if (!res.ok) throw new Error("update_failed");
      setNotificationsEnabled(next);
    } catch {
      setError("Non sono riuscito ad aggiornare la preferenza. Riprova.");
    } finally {
      setBusy(null);
    }
  }

  async function handleDeleteAccount() {
    setBusy("delete");
    setError(null);
    try {
      const csrfToken = await getCsrfToken();
      const res = await fetch("/api/privacy/delete-account", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ confirm: deleteConfirm }),
      });
      const json = await res.json();
      if (!res.ok || !json.ok) {
        throw new Error(json.error || "delete_failed");
      }
      window.location.assign(json.redirect_url || "/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Eliminazione account non riuscita. Riprova.");
      setBusy(null);
    }
  }

  return (
    <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 980 }}>
      <Box sx={{ mb: 4 }}>
        <Typography component="h1" variant="h4" fontWeight={800} color="primary.main" gutterBottom>
          Privacy e dati
        </Typography>
        <Typography color="text.secondary">
          Qui puoi esercitare i tuoi diritti GDPR: accedere ai tuoi dati (Art. 15), ottenerli in
          formato portabile (Art. 20), opporti a un trattamento (Art. 21) o cancellare il tuo
          account (Art. 17). Tempo di risposta standard: 1 mese, target 24h.
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}
      {info && (
        <Alert severity="success" sx={{ mb: 3 }}>
          {info}
        </Alert>
      )}

      {policyAccepted !== null && policyCurrent !== null && policyAccepted !== policyCurrent && (
        <Alert
          severity="warning"
          sx={{ mb: 3 }}
          action={
            <Button color="inherit" size="small" onClick={handleAcceptPolicy} disabled={busy !== null}>
              {busy === "consent" ? "..." : "Accetta"}
            </Button>
          }
        >
          Abbiamo aggiornato la nostra{" "}
          <a href="/privacy" target="_blank" rel="noreferrer">
            informativa sulla privacy
          </a>
          . Accettala per continuare a usare Expensum senza interruzioni.
        </Alert>
      )}

      <Stack spacing={3}>
        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              I tuoi dati
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 2 }}>
              Scarica una copia completa dei tuoi dati personali (JSON, Art. 15) oppure solo le
              transazioni in formato portabile (CSV, Art. 20). Se usi il backend Notion, i tuoi
              dati finanziari restano nel tuo workspace personale: puoi esportarli direttamente da
              notion.so.
            </Typography>
          </CardContent>
          <CardActions sx={{ px: 2, pb: 2, pt: 0 }}>
            <Button variant="outlined" onClick={handleExportJson} disabled={busy !== null}>
              {busy === "json" ? "Generazione..." : "Scarica i miei dati (JSON)"}
            </Button>
            <Button variant="outlined" onClick={handleExportCsv} disabled={busy !== null}>
              {busy === "csv" ? "Generazione..." : "Scarica transazioni (CSV)"}
            </Button>
          </CardActions>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              Preferenze privacy
            </Typography>
            <FormControlLabel
              control={
                <Switch
                  checked={notificationsEnabled}
                  onChange={handleToggleNotifications}
                  disabled={busy !== null}
                />
              }
              label="Ricevi notifiche e promemoria (opposizione Art. 21: disattivala in qualsiasi momento)"
            />
          </CardContent>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              Cambia nome
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 2 }}>
              Correggi nome e cognome associati al tuo account (diritto di rettifica, Art. 16).
            </Typography>
            <Stack spacing={2} sx={{ maxWidth: 420 }}>
              <TextField
                label="Nome"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                fullWidth
              />
              <TextField
                label="Cognome"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                fullWidth
              />
            </Stack>
          </CardContent>
          <CardActions sx={{ px: 2, pb: 2, pt: 0 }}>
            <Button
              variant="outlined"
              onClick={handleChangeName}
              disabled={busy !== null || !firstName}
            >
              {busy === "name" ? "Aggiornamento..." : "Aggiorna nome"}
            </Button>
          </CardActions>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              Cambia email
            </Typography>
            <Stack spacing={2} sx={{ maxWidth: 420 }}>
              <TextField
                label="Nuova email"
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                fullWidth
              />
              <TextField
                label="Password corrente"
                type="password"
                value={currentPasswordForEmail}
                onChange={(e) => setCurrentPasswordForEmail(e.target.value)}
                fullWidth
              />
            </Stack>
          </CardContent>
          <CardActions sx={{ px: 2, pb: 2, pt: 0 }}>
            <Button
              variant="outlined"
              onClick={handleChangeEmail}
              disabled={busy !== null || !newEmail || !currentPasswordForEmail}
            >
              {busy === "email" ? "Aggiornamento..." : "Aggiorna email"}
            </Button>
          </CardActions>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              Cambia password
            </Typography>
            <Stack spacing={2} sx={{ maxWidth: 420 }}>
              <TextField
                label="Password corrente"
                type="password"
                value={currentPasswordForPassword}
                onChange={(e) => setCurrentPasswordForPassword(e.target.value)}
                fullWidth
              />
              <TextField
                label="Nuova password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                helperText="Almeno 8 caratteri."
                fullWidth
              />
              <TextField
                label="Conferma nuova password"
                type="password"
                value={newPasswordConfirm}
                onChange={(e) => setNewPasswordConfirm(e.target.value)}
                fullWidth
              />
            </Stack>
          </CardContent>
          <CardActions sx={{ px: 2, pb: 2, pt: 0 }}>
            <Button
              variant="outlined"
              onClick={handleChangePassword}
              disabled={
                busy !== null ||
                !currentPasswordForPassword ||
                newPassword.length < 8 ||
                !newPasswordConfirm
              }
            >
              {busy === "password" ? "Aggiornamento..." : "Aggiorna password"}
            </Button>
          </CardActions>
        </Card>

        <Card sx={{ borderRadius: 4, border: "1px solid rgba(211, 47, 47, 0.24)" }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} color="error.main" gutterBottom>
              Zona pericolosa
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 2 }}>
              Questa azione elimina definitivamente account, impostazioni e dati locali. I dati
              presenti nel tuo workspace Notion non vengono toccati.
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
            <Button variant="text" onClick={() => router.push("/impostazioni")}>
              Torna a Impostazioni
            </Button>
          </CardActions>
        </Card>
      </Stack>
    </Box>
  );
}
