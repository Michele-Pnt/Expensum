"use client";

import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Collapse,
  Divider,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { ChevronDown } from "lucide-react";
import InfoButton from "../../../components/InfoButton";
import LabelGroupingToggle, { GROUPING_DISCLAIMER } from "./LabelGroupingToggle";
import type { LabelFixMode, LabelFixTarget } from "./LabelFixDialog";
import { formatDateIt } from "@/lib/date";
import type { AnalyticsSelection, ExplorerDimension } from "../types";

export type ExplorerItem = { label: string; amount: number; secondaryLabel: string; incidenceLabel?: string; percentage?: number; clusterId?: number | null; categoryId?: number | null };
export type ExplorerTransaction = { id: number; date: string; name: string; amount: number; category: string };

type AnalyticsExplorerProps = {
  dimension: ExplorerDimension;
  expandedItem: string | null;
  items: ExplorerItem[];
  totalSpent: number;
  transactions: ExplorerTransaction[];
  transactionsLoading: boolean;
  hasMoreItems: boolean;
  hasMoreTransactions: boolean;
  onDimensionChange: (dimension: ExplorerDimension) => void;
  onSelect: (selection: AnalyticsSelection) => void;
  onLoadMoreItems: () => void;
  onLoadMoreTransactions: () => void;
  grouped: boolean;
  onGroupedChange: (grouped: boolean) => void;
  onFixLabel: (mode: LabelFixMode, target: LabelFixTarget) => void;
};

/** Elenco progressivo: espande i movimenti nel punto esatto in cui l'utente li cerca. */
export default function AnalyticsExplorer({ dimension, expandedItem, items, totalSpent, transactions, transactionsLoading, hasMoreItems, hasMoreTransactions, onDimensionChange, onSelect, onLoadMoreItems, onLoadMoreTransactions, grouped, onGroupedChange, onFixLabel }: AnalyticsExplorerProps) {
  const explanation = dimension === "merchants"
    ? (grouped
        ? `Raggruppiamo le uscite registrate nel periodo selezionato per etichetta: voci diverse ma equivalenti (es. "coca cola" e "coca-cola") vengono unite sotto lo stesso nome. Sotto ogni etichetta trovi il numero di operazioni. Se il raggruppamento sbaglia, puoi correggerlo con Rinomina/Unisci/Dividi. ${GROUPING_DISCLAIMER}`
        : "Mostriamo le uscite registrate nel periodo selezionato per nome esatto, senza alcun raggruppamento automatico: ogni voce distinta compare separata, anche se si riferisce alla stessa spesa scritta in modo diverso.")
    : dimension === "categories"
      ? "Raggruppiamo le uscite registrate nel periodo selezionato per categoria. La percentuale indica l’incidenza sul totale della lente scelta."
      : "Raggruppiamo le uscite registrate nel periodo selezionato per conto di provenienza. La percentuale indica l’incidenza sul totale della lente scelta.";
  const select = (item: ExplorerItem) => {
    if (dimension === "categories") onSelect({ category: item.label });
    if (dimension === "merchants") onSelect({ merchant: item.label });
    if (dimension === "accounts") onSelect({ account: item.label });
  };

  return (
    <Box display="grid" gap={2}>
      <ToggleButtonGroup value={dimension} exclusive onChange={(_, value: ExplorerDimension | null) => value && onDimensionChange(value)} aria-label="Dimensione di esplorazione" fullWidth>
        <ToggleButton value="categories" sx={{ minHeight: 44 }}>Categorie</ToggleButton>
        <ToggleButton value="merchants" sx={{ minHeight: 44 }}>Voci</ToggleButton>
        <ToggleButton value="accounts" sx={{ minHeight: 44 }}>Conti</ToggleButton>
      </ToggleButtonGroup>
      {dimension === "merchants" && (
        <LabelGroupingToggle grouped={grouped} onChange={onGroupedChange} />
      )}
      <Card><CardContent>
        <Box display="flex" alignItems="center" mb={0.5}>
          <Typography variant="subtitle2" fontWeight={600}>Dove stai spendendo</Typography>
          <InfoButton label="Come calcoliamo Dove stai spendendo" explanation={explanation} />
        </Box>
        <Box mb={1.5}>
          <Typography variant="body2" color="text.secondary">
            Totale speso nel periodo selezionato: <strong>{totalSpent.toLocaleString("it-IT", { style: "currency", currency: "EUR" })}</strong>
          </Typography>
        </Box>
        {items.map((item, index) => {
          const isSelected = expandedItem === item.label;
          // L'apertura animata parte solo a dati pronti: evita lo scatto quando il contenuto
          // passa da placeholder di caricamento a lista transazioni con altezza diversa.
          const isExpanded = isSelected && !transactionsLoading;
          const detailsId = `explorer-details-${index}`;

          return (
            <Box key={item.label}>
              <Button
                fullWidth
                variant="text"
                disableRipple
                disableTouchRipple
                aria-expanded={isSelected}
                aria-busy={isSelected && transactionsLoading}
                aria-controls={detailsId}
                onClick={() => select(item)}
                sx={{
                  minHeight: 52,
                  display: "flex",
                  alignItems: "center",
                  columnGap: 2,
                  textAlign: "left",
                  "&:hover": { backgroundColor: "transparent" },
                }}
              >
                {/* Flex invece di griglia a colonne fisse: l'importo occupa solo la
                    larghezza che gli serve e non si restringe, il resto va al nome.
                    Con una colonna importo a minimo fisso (9rem) su schermi stretti
                    il nome veniva schiacciato e spezzato lettera per lettera. Gli
                    importi restano comunque allineati: finiscono tutti contro la
                    freccia, che ha larghezza fissa. */}
                <Box component="span" sx={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>
                  <strong>{item.label}</strong>
                  {item.secondaryLabel && (
                    <>
                      <br />
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ minWidth: 0, overflowWrap: "anywhere" }}>{item.secondaryLabel}</Typography>
                    </>
                  )}
                </Box>
                <Typography component="span" fontWeight={600} textAlign="right" whiteSpace="nowrap" sx={{ flexShrink: 0 }}>{item.amount.toLocaleString("it-IT", { style: "currency", currency: "EUR" })}</Typography>
                <Box component="span" sx={{ flexShrink: 0, width: 24, display: "inline-flex", justifyContent: "flex-end" }}>
                  {isSelected && transactionsLoading
                    ? <CircularProgress size={16} />
                    : <ChevronDown aria-hidden="true" size={18} style={{ transform: isSelected ? "rotate(180deg)" : "none" }} />}
                </Box>
              </Button>
              {item.percentage !== undefined && (
                <Box
                  aria-hidden="true"
                  sx={{
                    height: 4,
                    borderRadius: 2,
                    backgroundColor: "action.hover",
                    overflow: "hidden",
                    mt: -0.5,
                    mb: 1,
                  }}
                >
                  <Box
                    sx={{
                      height: "100%",
                      width: `${Math.min(100, Math.round(item.percentage))}%`,
                      borderRadius: 2,
                      backgroundColor: "primary.main",
                    }}
                  />
                </Box>
              )}
              <Collapse in={isExpanded} timeout="auto">
                <Box
                  id={detailsId}
                  role="region"
                  aria-label={`Operazioni: ${item.label}`}
                  sx={{
                    backgroundColor: "action.hover",
                    borderRadius: 1.5,
                    borderLeft: "3px solid",
                    borderLeftColor: "primary.main",
                    px: 1.25,
                    py: transactions.length === 0 ? 1 : 0.5,
                    mb: 1.5,
                  }}
                >
                  {item.incidenceLabel && (
                    <Typography variant="caption" color="text.secondary" display="block" pt={1} pb={0.5}>
                      {item.incidenceLabel}
                    </Typography>
                  )}
                  {transactions.length === 0 ? (
                    <Typography variant="caption" color="text.secondary" display="block" py={1}>Nessuna operazione nel periodo selezionato.</Typography>
                  ) : transactions.map((transaction, transactionIndex) => (
                    <Box key={transaction.id} py={0.75}>
                      {transactionIndex > 0 && <Divider sx={{ mb: 0.75 }} />}
                      <Box display="flex" justifyContent="space-between" gap={1}>
                        <Box component="span" sx={{ minWidth: 0, overflowWrap: "anywhere" }}>{transaction.name}<br /><Typography component="span" variant="caption" color="text.secondary" sx={{ minWidth: 0, overflowWrap: "anywhere" }}>{`${formatDateIt(transaction.date)} · ${transaction.category}`}</Typography></Box>
                        <Typography component="strong" whiteSpace="nowrap">−{transaction.amount.toLocaleString("it-IT", { style: "currency", currency: "EUR" })}</Typography>
                      </Box>
                    </Box>
                  ))}
                  {hasMoreTransactions && (
                    <Button fullWidth sx={{ minHeight: 44, mt: 0.5 }} onClick={onLoadMoreTransactions}>
                      Carica altro
                    </Button>
                  )}
                  {dimension === "merchants" && grouped && item.clusterId != null && (
                    <>
                      <Divider sx={{ my: 0.75 }} />
                      <Box display="flex" gap={1} py={0.5}>
                        <Button
                          size="small"
                          sx={{ minHeight: 44 }}
                          onClick={() => onFixLabel("rename", { id: item.clusterId as number, anchorText: item.label, categoryId: item.categoryId ?? null })}
                        >
                          Rinomina
                        </Button>
                        <Button
                          size="small"
                          sx={{ minHeight: 44 }}
                          onClick={() => onFixLabel("merge", { id: item.clusterId as number, anchorText: item.label, categoryId: item.categoryId ?? null })}
                        >
                          Unisci
                        </Button>
                        <Button
                          size="small"
                          sx={{ minHeight: 44 }}
                          onClick={() => onFixLabel("split", { id: item.clusterId as number, anchorText: item.label, categoryId: item.categoryId ?? null })}
                        >
                          Dividi
                        </Button>
                      </Box>
                    </>
                  )}
                </Box>
              </Collapse>
              {index < items.length - 1 && <Divider sx={{ my: 1 }} />}
            </Box>
          );
        })}
        {hasMoreItems && (
          <Button fullWidth sx={{ minHeight: 44, mt: 1 }} onClick={onLoadMoreItems}>
            Carica altro
          </Button>
        )}
      </CardContent></Card>
    </Box>
  );
}
