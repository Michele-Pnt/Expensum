"use client";

import { Box, Button, Card, CardContent, Typography } from "@mui/material";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import InfoButton from "../../../components/InfoButton";
import type { AnalyticsSelection } from "../types";
import type { MonthlySpendingTrend, MonthEndProjection, SpendingChange, TodaySummary } from "../viewModels";

type AnalyticsTodayProps = {
  summary: TodaySummary;
  projection?: MonthEndProjection | null;
  changes?: SpendingChange[];
  spendingTrend?: MonthlySpendingTrend | null;
  showAttentions?: boolean;
  onSelect: (selection: AnalyticsSelection) => void;
};

const formatCurrency = (amount: number): string => amount.toLocaleString("it-IT", {
  style: "currency",
  currency: "EUR",
});

const monthLabels = new Intl.DateTimeFormat("it-IT", { month: "long" });

const budgetToneSx = {
  neutral: {
    borderColor: "success.main",
    background: "rgba(22, 163, 74, 0.12)",
  },
  warning: {
    borderColor: "warning.main",
    background: "rgba(240, 169, 62, 0.14)",
  },
  critical: {
    borderColor: "error.main",
    background: "rgba(220, 38, 38, 0.12)",
  },
};

function SpendingChangeRow({
  change,
  previousMonth,
  tone,
  onSelect,
}: {
  change: SpendingChange;
  previousMonth: string;
  tone: "improved" | "worsened";
  onSelect: (selection: AnalyticsSelection) => void;
}) {
  const isImproved = tone === "improved";
  const Icon = isImproved ? ArrowDownRight : ArrowUpRight;
  const color = isImproved ? "success.main" : "error.main";
  const delta = formatCurrency(Math.abs(change.increase));

  return (
    <Button
      fullWidth
      variant="text"
      onClick={() => onSelect({ category: change.label })}
      sx={{
        alignItems: { xs: "flex-start", sm: "center" },
        gap: 1.5,
        justifyContent: "space-between",
        minHeight: 58,
        px: 0,
        py: 1,
        textAlign: "left",
      }}
    >
      <Box component="span" sx={{ minWidth: 0 }}>
        <Typography component="span" display="block" color="text.primary" sx={{ overflowWrap: "anywhere" }}>
          {change.label}
        </Typography>
        <Typography component="span" variant="caption" color="text.secondary" display="block">
          {formatCurrency(change.amount)} questo mese
        </Typography>
      </Box>
      <Box
        component="span"
        sx={{
          alignItems: "center",
          color,
          display: "inline-flex",
          flexShrink: 0,
          gap: 0.5,
          justifyContent: "flex-end",
          whiteSpace: "nowrap",
        }}
      >
        <Icon size={16} aria-hidden="true" />
        <Typography component="span" variant="body2" fontWeight={600}>
          {isImproved ? "-" : "+"}{delta}
        </Typography>
        <Typography component="span" variant="caption" color="text.secondary">
          vs {previousMonth}
        </Typography>
      </Box>
    </Button>
  );
}

/** Dashboard operativo: una decisione, due insight testuali e due attenzioni. */
export default function AnalyticsToday({
  summary,
  projection = null,
  changes = [],
  spendingTrend = null,
  showAttentions = true,
  onSelect,
}: AnalyticsTodayProps) {
  const amount = summary.availableAmount === null ? "—" : formatCurrency(summary.availableAmount);
  const today = new Date();
  const monthName = monthLabels.format(today);
  const lastDay = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const previousMonth = monthLabels.format(new Date(today.getFullYear(), today.getMonth() - 1, 1));
  const worsenedChanges = changes
    .filter((change) => change.increase > 0)
    .sort((left, right) => right.increase - left.increase)
    .slice(0, 2);
  const improvedChanges = changes
    .filter((change) => change.increase < 0)
    .sort((left, right) => left.increase - right.increase)
    .slice(0, 2);
  const spendingTrendLabel = spendingTrend
    ? `${spendingTrend.direction === "up" ? "Aumento delle spese" : spendingTrend.direction === "down" ? "Diminuzione delle spese" : "Spese stabili"} del ${spendingTrend.percentage}% rispetto al mese scorso`
    : "";

  return (
    <Box display="grid" gap={2}>
      <Card sx={budgetToneSx[summary.budgetTone]}>
        <CardContent>
          <Box sx={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 2 }}>
            <Box sx={{ minWidth: 0 }}>
              <Box display="flex" alignItems="center">
                <Typography variant="overline" color="text.secondary">Budget disponibile questo mese</Typography>
                <Box sx={{ ml: -1.25 }}>
                  <InfoButton label="Cos'è il budget disponibile" explanation="Il budget rimasto per questo mese." />
                </Box>
              </Box>
              <Typography variant="h4" fontWeight={400}>{amount}</Typography>
            </Box>
            <Box sx={{ borderLeft: "1px solid", borderColor: "divider", minWidth: 0, pl: 2 }}>
              <Box display="flex" alignItems="center">
                <Typography variant="overline" color="text.secondary">Totale speso questo mese</Typography>
                <Box sx={{ ml: -1.25 }}>
                  <InfoButton label="Cos'è il totale speso" explanation="Il totale speso e il confronto con il mese scorso." />
                </Box>
              </Box>
              <Typography variant="h4" fontWeight={400}>{formatCurrency(summary.totalSpent)}</Typography>
              {spendingTrend && (
                <Box aria-label={spendingTrendLabel} alignItems="center" color={spendingTrend.direction === "up" ? "error.main" : spendingTrend.direction === "down" ? "success.main" : "text.secondary"} display="flex" gap={0.5} mt={0.5} role="status">
                  {spendingTrend.direction === "up" ? <ArrowUpRight size={16} aria-hidden="true" /> : spendingTrend.direction === "down" ? <ArrowDownRight size={16} aria-hidden="true" /> : <Minus size={16} aria-hidden="true" />}
                  <Typography variant="body2" fontWeight={600}>{spendingTrend.percentage}%</Typography>
                </Box>
              )}
            </Box>
          </Box>
        </CardContent>
      </Card>

      {projection && (
        <Card>
          <CardContent>
            <Box display="flex" alignItems="center" mb={1}>
              <Typography variant="subtitle2" fontWeight={600}>Stima di fine mese</Typography>
              <InfoButton label="Come calcoliamo Stima di fine mese" explanation="Calcoliamo la media giornaliera delle uscite dalle spese registrate fino a oggi e la applichiamo ai giorni rimanenti del mese. Non includiamo entrate future, spese non registrate o movimenti non ancora inseriti." />
            </Box>
            <Typography>Il tuo bilancio mensile attuale è di {formatCurrency(projection.currentAmount)}</Typography>
            <Typography variant="body2" color="text.secondary">
              Stima al {lastDay} {monthName}: {formatCurrency(projection.projectedEndAmount)}
            </Typography>
          </CardContent>
        </Card>
      )}

      {changes.length > 0 && (worsenedChanges.length > 0 || improvedChanges.length > 0) && (
        <Card>
          <CardContent>
            <Box display="flex" alignItems="center" mb={1}>
              <Typography variant="subtitle2" fontWeight={600}>Due cose da seguire</Typography>
              <InfoButton label="Come calcoliamo categorie migliorate e peggiorate" explanation="Confrontiamo le spese per categoria del mese corrente con il mese precedente e mostriamo le variazioni più rilevanti, in aumento e in diminuzione." />
            </Box>
            {worsenedChanges.length > 0 && (
              <Box>
                <Typography variant="caption" color="error.main" fontWeight={600}>Stai spendendo più del mese scorso</Typography>
                {worsenedChanges.map((change) => (
                  <SpendingChangeRow key={`worse-${change.label}`} change={change} previousMonth={previousMonth} tone="worsened" onSelect={onSelect} />
                ))}
              </Box>
            )}
            {improvedChanges.length > 0 && (
              <Box sx={{ mt: worsenedChanges.length > 0 ? 1.5 : 0 }}>
                <Typography variant="caption" color="success.main" fontWeight={600}>Stai spendendo meno del mese scorso</Typography>
                {improvedChanges.map((change) => (
                  <SpendingChangeRow key={`better-${change.label}`} change={change} previousMonth={previousMonth} tone="improved" onSelect={onSelect} />
                ))}
              </Box>
            )}
          </CardContent>
        </Card>
      )}

      {showAttentions && summary.attentions.length > 0 && (
        <Card>
          <CardContent>
            <Box display="flex" alignItems="center" mb={1}>
              <Typography variant="subtitle2" fontWeight={600}>Categorie da monitorare</Typography>
              <InfoButton label="Come calcoliamo le categorie da monitorare" explanation="Mostriamo fino a cinque categorie con la percentuale di budget più alta nel mese in corso. Soglie: attenzione dall'85%, budget superato dal 100%." />
            </Box>
            {summary.attentions.map((attention) => (
              <Button
                key={attention.label}
                fullWidth
                variant="text"
                aria-label={`${attention.label}: ${attention.value}. ${attention.tone === "critical" ? "Budget superato" : attention.tone === "warning" ? "Attenzione: budget quasi esaurito" : "Budget sotto controllo"}`}
                onClick={() => onSelect({ category: attention.label })}
                sx={{ justifyContent: "space-between", gap: 1, minHeight: 44, textAlign: "left", color: attention.tone === "critical" ? "error.main" : "text.primary" }}
              >
                <Typography component="span" sx={{ overflowWrap: "anywhere", textAlign: "left", minWidth: 0 }}>{attention.tone === "critical" ? "Sforato · " : attention.tone === "warning" ? "Attenzione · " : ""}{attention.label}</Typography>
                <Typography component="span" sx={{ textAlign: "right", flexShrink: 0 }}>{attention.value}</Typography>
              </Button>
            ))}
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
