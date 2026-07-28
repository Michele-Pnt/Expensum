"use client";

import { useEffect, useState } from "react";
import { Box, Card, CardHeader, CardContent, Typography, LinearProgress, Chip, Button } from "@mui/material";
import Link from "next/link";

interface SavingsGoal {
  id: number;
  name: string;
  goal_type: string;
  target_amount: number;
  progress: number;
  score_label: string;
  eta_date: string | null;
}

function getTelegramInitData(): string {
  if (typeof window === "undefined") return "";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (window as any).Telegram?.WebApp?.initData ?? "";
}

function scoreColor(label: string): "success" | "info" | "warning" | "error" | "default" {
  if (label === "In anticipo" || label === "Ottimo mese" || label === "Obiettivo centrato") return "success";
  if (label === "In linea" || label === "Vicino all'obiettivo") return "info";
  if (label === "In ritardo" || label === "Sotto obiettivo") return "warning";
  if (label === "A rischio") return "error";
  return "default";
}

/** Widget compatto (2-3 obiettivi principali), riusato in dashboard overview e analytics.
 * Non renderizza nulla per utenti Free/Notion (nessun banner invasivo fuori dalla
 * pagina /goals dedicata, che gestisce già il gating con testo esplicativo).
 */
export default function SavingsGoalsProgress() {
  const [goals, setGoals] = useState<SavingsGoal[] | null>(null);

  useEffect(() => {
    const initData = getTelegramInitData();
    const headers: HeadersInit = initData ? { "X-Telegram-Init-Data": initData } : {};
    fetch("/api/savings-goals", { headers })
      .then((res) => (res.ok ? res.json() : { goals: [] }))
      .then((data) => setGoals(data.goals || []))
      .catch(() => setGoals([]));
  }, []);

  if (!goals || goals.length === 0) return null;

  const top = [...goals]
    .sort((a, b) => (a.eta_date && b.eta_date ? a.eta_date.localeCompare(b.eta_date) : a.progress - b.progress))
    .slice(0, 3);

  return (
    <Card sx={{ mb: 2, borderRadius: 2 }}>
      <CardHeader
        title="🎯 Obiettivi di risparmio"
        titleTypographyProps={{ variant: "subtitle2", fontWeight: 700 }}
        action={
          <Button component={Link} href="/goals" size="small">Vedi tutti</Button>
        }
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ pt: 0 }}>
        {top.map((g) => (
          <Box key={g.id} sx={{ mb: 1.5 }}>
            <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
              <Typography variant="body2" fontWeight={600}>{g.name}</Typography>
              <Chip label={g.score_label} color={scoreColor(g.score_label)} size="small" />
            </Box>
            <LinearProgress
              variant="determinate"
              value={Math.min(g.progress, 100)}
              sx={{ height: 6, borderRadius: 3 }}
            />
          </Box>
        ))}
      </CardContent>
    </Card>
  );
}
