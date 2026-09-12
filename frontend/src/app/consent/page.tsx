"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, ApiError } from "@/lib/api";
import {
  Box,
  Button,
  Checkbox,
  CircularProgress,
  FormControlLabel,
  Link as MuiLink,
  Paper,
  TextField,
  Typography,
} from "@mui/material";

type SettingsResponse = {
  account?: {
    privacy_policy_version_accepted?: string | null;
    privacy_policy_current_version?: string;
    tos_version_accepted?: string | null;
    tos_current_version?: string;
  };
};

type SessionResponse = {
  redirect_to?: string | null;
};

type DeleteAccountResponse = {
  ok?: boolean;
  redirect_url?: string;
};

function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.message === "auth_401";
}

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

export default function ConsentPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsPrivacy, setNeedsPrivacy] = useState(false);
  const [needsTos, setNeedsTos] = useState(false);
  const [privacyChecked, setPrivacyChecked] = useState(false);
  const [tosChecked, setTosChecked] = useState(false);

  const [showDelete, setShowDelete] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"json" | "csv" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const goToDestination = useCallback(async () => {
    try {
      const session = await apiFetch<SessionResponse>("/api/auth/session");
      const dest =
        session.redirect_to && session.redirect_to !== "/consent" ? session.redirect_to : "/home";
      window.location.assign(dest);
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/login");
        return;
      }
      window.location.assign("/home");
    }
  }, [router]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const settings = await apiFetch<SettingsResponse>("/api/settings");
        if (cancelled) return;
        const account = settings.account || {};
        const privacyOutdated =
          account.privacy_policy_version_accepted !== account.privacy_policy_current_version;
        const tosOutdated = account.tos_version_accepted !== account.tos_current_version;
        if (!privacyOutdated && !tosOutdated) {
          await goToDestination();
          return;
        }
        setNeedsPrivacy(privacyOutdated);
        setNeedsTos(tosOutdated);
        setLoading(false);
      } catch (err) {
        if (cancelled) return;
        if (isUnauthorized(err)) {
          router.replace("/login");
          return;
        }
        setError("Non sono riuscito a caricare lo stato del consenso. Riprova.");
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, goToDestination]);

  async function handleContinue() {
    setSubmitting(true);
    setError(null);
    try {
      if (needsPrivacy) {
        await apiFetch("/api/privacy/accept-policy", { method: "POST" });
        setNeedsPrivacy(false);
      }
      if (needsTos) {
        await apiFetch("/api/privacy/accept-tos", { method: "POST" });
        setNeedsTos(false);
      }
      await goToDestination();
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/login");
        return;
      }
      setError("Non sono riuscito a registrare l'accettazione. Riprova.");
      setSubmitting(false);
    }
  }

  async function handleExport(kind: "json" | "csv") {
    setExporting(kind);
    setExportError(null);
    try {
      if (kind === "json") {
        await downloadFile("/api/privacy/export-json", `expensum_dati_${Date.now()}.json`);
      } else {
        await downloadFile("/api/privacy/export-csv", `expensum_transazioni_${Date.now()}.csv`);
      }
    } catch (e) {
      setExportError(
        e instanceof Error && e.message !== "download_failed"
          ? e.message
          : "Non sono riuscito a generare l'export. Riprova tra poco."
      );
    } finally {
      setExporting(null);
    }
  }

  async function handleDeleteAccount() {
    setDeleting(true);
    setDeleteError(null);
    try {
      const result = await apiFetch<DeleteAccountResponse>("/api/privacy/delete-account", {
        method: "POST",
        body: { confirm: deleteConfirm },
      });
      window.location.assign(result.redirect_url || "/login");
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/login");
        return;
      }
      setDeleteError("Eliminazione account non riuscita. Riprova.");
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <Box
        sx={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <CircularProgress color="primary" />
      </Box>
    );
  }

  const canContinue = (!needsPrivacy || privacyChecked) && (!needsTos || tosChecked);

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 3,
      }}
    >
      <Paper sx={{ maxWidth: 480, width: "100%", p: 4, borderRadius: 4 }}>
        <Typography variant="h5" fontWeight={800} gutterBottom>
          Prima di continuare
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 3 }}>
          Abbiamo aggiornato i nostri documenti legali. Per continuare a usare Expensum devi
          leggerli e accettarli esplicitamente.
        </Typography>

        {error && (
          <Typography color="error" sx={{ mb: 2 }}>
            {error}
          </Typography>
        )}

        {needsPrivacy && (
          <FormControlLabel
            sx={{ display: "flex", mb: 1 }}
            control={
              <Checkbox
                checked={privacyChecked}
                onChange={(e) => setPrivacyChecked(e.target.checked)}
              />
            }
            label={
              <span>
                Ho letto e accetto la{" "}
                <a href="/privacy" target="_blank" rel="noreferrer">
                  Privacy Policy
                </a>
                .
              </span>
            }
          />
        )}

        {needsTos && (
          <FormControlLabel
            sx={{ display: "flex", mb: 2 }}
            control={
              <Checkbox checked={tosChecked} onChange={(e) => setTosChecked(e.target.checked)} />
            }
            label={
              <span>
                Ho letto e accetto i{" "}
                <a href="/terms" target="_blank" rel="noreferrer">
                  Termini di Servizio
                </a>
                .
              </span>
            }
          />
        )}

        <Button
          variant="contained"
          fullWidth
          size="large"
          disabled={!canContinue || submitting}
          onClick={handleContinue}
          sx={{ mt: 1 }}
        >
          {submitting ? "..." : "Continua"}
        </Button>

        <Box sx={{ mt: 3, pt: 2, borderTop: "1px solid", borderColor: "divider" }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Puoi comunque scaricare una copia dei tuoi dati (Art. 15/20 GDPR) prima di
            decidere:
          </Typography>
          {exportError && (
            <Typography color="error" variant="body2" sx={{ mb: 1 }}>
              {exportError}
            </Typography>
          )}
          <Box sx={{ display: "flex", gap: 1, mb: 1 }}>
            <Button
              size="small"
              variant="outlined"
              fullWidth
              disabled={exporting !== null}
              onClick={() => handleExport("json")}
            >
              {exporting === "json" ? "..." : "Scarica JSON"}
            </Button>
            <Button
              size="small"
              variant="outlined"
              fullWidth
              disabled={exporting !== null}
              onClick={() => handleExport("csv")}
            >
              {exporting === "csv" ? "..." : "Scarica CSV"}
            </Button>
          </Box>
        </Box>

        <Box sx={{ mt: 2, textAlign: "center" }}>
          <Typography variant="body2" color="text.secondary">
            Non vuoi accettare?{" "}
            <MuiLink href="/logout" underline="hover">
              Esci
            </MuiLink>{" "}
            oppure{" "}
            <MuiLink
              component="button"
              underline="hover"
              onClick={() => setShowDelete((v) => !v)}
            >
              elimina il tuo account
            </MuiLink>
            .
          </Typography>
        </Box>

        {showDelete && (
          <Box sx={{ mt: 2, pt: 2, borderTop: "1px solid", borderColor: "divider" }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Elimina definitivamente il tuo account e tutti i tuoi dati. Scrivi{" "}
              <strong>DELETE</strong> per confermare.
            </Typography>
            {deleteError && (
              <Typography color="error" variant="body2" sx={{ mb: 1.5 }}>
                {deleteError}
              </Typography>
            )}
            <TextField
              size="small"
              fullWidth
              placeholder="DELETE"
              value={deleteConfirm}
              onChange={(e) => setDeleteConfirm(e.target.value)}
              sx={{ mb: 1.5 }}
            />
            <Button
              variant="outlined"
              color="error"
              fullWidth
              disabled={deleteConfirm.trim().toUpperCase() !== "DELETE" || deleting}
              onClick={handleDeleteAccount}
            >
              {deleting ? "..." : "Elimina account"}
            </Button>
          </Box>
        )}
      </Paper>
    </Box>
  );
}
