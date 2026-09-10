"use client";

import { Box, Button, Card, CardContent, LinearProgress, Typography } from "@mui/material";
import Link from "next/link";
import InfoButton from "../../../components/InfoButton";

export type PlannerBudget = { category: string; budget: number; spent: number; percentage: number };

type AnalyticsPlannerProps = { budgets: PlannerBudget[]; isPro: boolean };

/** Trasforma la lettura dei budget in azioni comprensibili e non bloccanti. */
export default function AnalyticsPlanner({ budgets, isPro }: AnalyticsPlannerProps) {
  if (!isPro || budgets.length === 0) {
    return <Card><CardContent><Typography variant="subtitle2" fontWeight={600}>Dai una direzione alle tue spese</Typography><Typography variant="body2" color="text.secondary" my={1}>Usa la tua media recente come primo limite, senza rinunciare a osservare i dati.</Typography><Button component={Link} href="/spazio" variant="contained" sx={{ minHeight: 44 }}>Crea un budget</Button><Button component={Link} href="/analytics" variant="text" sx={{ minHeight: 44 }}>Non ora</Button></CardContent></Card>;
  }
  return <Card><CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}><Box display="flex" alignItems="center"><Typography variant="subtitle2" fontWeight={600}>Budget e previsione di fine mese</Typography><InfoButton label="Come calcoliamo Budget e previsione di fine mese" explanation="Per ogni categoria confrontiamo le uscite registrate nel mese in corso con il budget mensile che hai impostato. La barra si ferma al 100% anche se il budget è stato superato." /></Box><Typography variant="caption" color="text.secondary" display="block" mb={1.5}>Budget del mese: controlla quanto resta e prevedi l&apos;andamento.</Typography>{budgets.map((budget) => <Box key={budget.category} mb={1.25}><Box display="flex" flexDirection={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} justifyContent="space-between" gap={1}><Typography sx={{ minWidth: 0, overflowWrap: "anywhere" }}>{budget.category}</Typography><Typography color="text.secondary" whiteSpace="nowrap">{budget.spent.toLocaleString("it-IT", { style: "currency", currency: "EUR" })} / {budget.budget.toLocaleString("it-IT", { style: "currency", currency: "EUR" })}</Typography></Box><LinearProgress variant="determinate" value={Math.min(budget.percentage, 100)} sx={{ height: 6, borderRadius: 3, mt: 0.5 }} /></Box>)}</CardContent></Card>;
}
