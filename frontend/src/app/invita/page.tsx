"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  LinearProgress,
  Stack,
  Typography,
} from "@mui/material";
import { Gift, Trophy, Share2, Check } from "lucide-react";
import { trackReferralLinkGenerated } from "@/lib/analytics";

type ReferralLinkResponse = {
  referral_code: string;
  link: string;
  referred_count: number;
  lifetime_founder_guaranteed: boolean;
};

export default function InvitaPage() {
  const [data, setData] = useState<ReferralLinkResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const loadReferral = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/referral/link", { credentials: "same-origin" });
      if (!res.ok) throw new Error("referral_fetch_failed");
      const json = await res.json();
      setData(json);
      trackReferralLinkGenerated();
    } catch {
      setError("Non sono riuscito a caricare il tuo link. Riprova tra poco.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadReferral();
  }, [loadReferral]);

  const handleCopy = async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard non disponibile (es. contesto non sicuro): l'utente può selezionare il testo a mano
    }
  };

  if (loading) {
    return (
      <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <CircularProgress color="primary" />
      </Box>
    );
  }

  const referredCount = data?.referred_count ?? 0;
  const progressCapped = Math.min(referredCount, 3);
  const shareText = data
    ? `Sto usando Expensum per tenere sotto controllo le spese, provalo anche tu: ${data.link}`
    : "";
  const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(shareText)}`;

  return (
    <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 980 }}>
      <Box sx={{ mb: 4 }}>
        <Typography component="h1" variant="h4" fontWeight={300} color="primary.main" gutterBottom>
          Invita amici
        </Typography>
        <Typography color="text.secondary">
          Condividi il tuo link personale: chi si iscrive tramite il tuo invito riceve 14 giorni di
          Pro gratis, e tu ricevi gli stessi 14 giorni per ciascuno dei tuoi primi 3 inviti, fino a
          42 giorni.
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
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
                <Gift size={20} />
                <Typography variant="h6" fontWeight={500}>
                  Il tuo link
                </Typography>
              </Stack>

              <Box
                sx={{
                  mb: 2, p: 1.5, borderRadius: 2, bgcolor: "action.hover",
                  wordBreak: "break-all", fontSize: 14, color: "text.secondary",
                }}
              >
                {data.link}
              </Box>

              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
                <Button
                  variant="contained"
                  size="large"
                  href={whatsappUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  startIcon={<Share2 size={18} strokeWidth={1.5} aria-hidden="true" />}
                  sx={{ textTransform: "none" }}
                >
                  Condividi su WhatsApp
                </Button>
                <Button
                  variant="outlined"
                  size="large"
                  onClick={handleCopy}
                  startIcon={copied ? <Check size={18} strokeWidth={1.5} aria-hidden="true" /> : undefined}
                  sx={{ textTransform: "none" }}
                >
                  {copied ? "Copiato!" : "Copia link"}
                </Button>
              </Stack>
            </CardContent>
          </Card>

          <Card sx={{ borderRadius: 4 }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
                <Trophy size={20} />
                <Typography variant="h6" fontWeight={500}>
                  I tuoi inviti
                </Typography>
              </Stack>

              <Typography sx={{ mb: 1.5 }}>
                Persone iscritte tramite il tuo link: <strong>{referredCount}</strong>
              </Typography>

              <LinearProgress
                variant="determinate"
                value={(progressCapped / 3) * 100}
                sx={{ height: 8, borderRadius: 4, mb: 1.5 }}
              />

              {data.lifetime_founder_guaranteed ? (
                <Chip
                  color="warning"
                  icon={<Trophy size={16} strokeWidth={1.5} aria-hidden="true" />}
                  label="Accesso garantito a Lifetime Founder sbloccato"
                  sx={{ fontWeight: 600 }}
                />
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Invita {3 - progressCapped} {3 - progressCapped === 1 ? "persona" : "persone"} in più per
                  sbloccare l&apos;accesso garantito all&apos;offerta Lifetime Founder.
                </Typography>
              )}

              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 2 }}>
                Raggiunti i 3 inviti hai ottenuto il massimo per te: 42 giorni di Pro e l&apos;accesso
                garantito a Lifetime Founder. Il link però non scade mai: puoi continuare a
                condividerlo e chi lo usa riceve sempre i suoi 14 giorni.
              </Typography>
            </CardContent>
          </Card>
        </Stack>
      )}
    </Box>
  );
}
