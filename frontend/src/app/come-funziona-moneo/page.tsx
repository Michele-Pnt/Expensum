"use client";

import Link from "next/link";
import { Box, Card, CardContent, Chip, Stack, Typography } from "@mui/material";

type AiModel = {
  name: string;
  purpose: string;
  scope: string;
};

const MODELS: AiModel[] = [
  {
    name: "Mistral Small 3.1",
    purpose: "Lettura e categorizzazione delle spese che scrivi o fotografi (scontrini).",
    scope: "Tutti gli utenti",
  },
  {
    name: "Mistral Large 3",
    purpose: "Conversazione con Moneo nella chat: risponde alle tue domande sulle tue finanze.",
    scope: "Tutti gli utenti",
  },
  {
    name: "Gemini 2.0 (Vertex AI)",
    purpose: "Trascrizione dei messaggi vocali in testo, prima dell'analisi della spesa.",
    scope: "Solo piano PRO",
  },
];

export default function ComeFunzionaMoneoPage() {
  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Navbar */}
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          px: { xs: 2, md: 4 },
          py: { xs: 1.25, md: 1.5 },
          borderBottom: 1,
          borderColor: "divider",
          bgcolor: "background.paper",
          position: "sticky",
          top: 0,
          zIndex: 10,
        }}
      >
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <img src="/logo-expensum-icon.png" alt="Expensum" style={{ height: 28, width: "auto" }} />
          <img src="/scritta_expensum.png" alt="Expensum" style={{ height: 16, width: "auto" }} />
        </Link>
        <Link href="/" style={{ textDecoration: "none", color: "inherit" }}>
          <Typography
            sx={{
              color: "text.secondary",
              fontSize: "0.875rem",
              lineHeight: 1.2,
              transition: "color 0.15s",
              "&:hover": { color: "primary.main" },
            }}
          >
            ← Torna al sito
          </Typography>
        </Link>
      </Box>

      {/* Main Content */}
      <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 980, mx: "auto", flex: 1 }}>
        <Box sx={{ mb: 4 }}>
          <Typography variant="h4" fontWeight={800} color="primary.main" gutterBottom>
            Come funziona Moneo
          </Typography>
        <Typography color="text.secondary">
          Moneo è l&apos;assistente AI di Expensum 🤖. Qui trovi quali modelli usiamo, per cosa li
          usiamo e quali sono i loro limiti, in linea con gli obblighi di trasparenza dell&apos;
          AI Act (Regolamento UE 2024/1689, Art. 50).
        </Typography>
      </Box>

      <Stack spacing={3}>
        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              Stai parlando con un&apos;intelligenza artificiale
            </Typography>
            <Typography color="text.secondary">
              Ogni risposta di Moneo — sul bot Telegram, nella chat web e nei report mensili e
              settimanali — è generata automaticamente da un modello linguistico (LLM), non da una
              persona. Te lo segnaliamo sempre alla prima interazione e in ogni report.
            </Typography>
          </CardContent>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              I modelli AI che usiamo
            </Typography>
            <Stack spacing={2} sx={{ mt: 1 }}>
              {MODELS.map((model) => (
                <Box key={model.name} sx={{ display: "flex", gap: 2, alignItems: "flex-start" }}>
                  <Chip label={model.scope} size="small" sx={{ mt: 0.5, flexShrink: 0 }} />
                  <Box>
                    <Typography fontWeight={700}>{model.name}</Typography>
                    <Typography color="text.secondary">{model.purpose}</Typography>
                  </Box>
                </Box>
              ))}
            </Stack>
            <Typography color="text.secondary" sx={{ mt: 2 }}>
              Tutti i modelli usati per l&apos;analisi testo/foto sono forniti da Mistral AI,
              azienda europea conforme al GDPR. Gemini 2.0 (Vertex AI) è usato solo per la
              trascrizione vocale, esclusivamente per gli utenti PRO.
            </Typography>
          </CardContent>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              Limiti noti
            </Typography>
            <Typography color="text.secondary">
              Moneo può commettere errori: categorie sbagliate, importi letti male da uno scontrino
              poco leggibile, o trascrizioni vocali imprecise. Verifica sempre i dati finanziari
              importanti prima di prendere decisioni basate sui report o sulle risposte di Moneo.
              Puoi correggere qualsiasi spesa o entrata in qualsiasi momento.
            </Typography>
          </CardContent>
        </Card>

        <Card sx={{ borderRadius: 4 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              Dati personali e privacy
            </Typography>
            <Typography color="text.secondary">
              Per sapere come trattiamo i tuoi dati personali e come esercitare i tuoi diritti
              GDPR, consulta{" "}
              <Link href="/impostazioni/privacy">la pagina privacy e dati</Link>.
            </Typography>
          </CardContent>
        </Card>
      </Stack>
    </Box>
    </Box>
  );
}
