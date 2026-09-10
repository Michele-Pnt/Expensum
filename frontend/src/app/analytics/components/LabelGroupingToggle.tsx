"use client";

import { Box, ToggleButton, ToggleButtonGroup } from "@mui/material";
import InfoButton from "../../../components/InfoButton";

export const GROUPING_DISCLAIMER =
  "Uniamo automaticamente le voci scritte in modo simile (es. «coca» e «coca cola»). " +
  "La classificazione può sbagliare: due voci diverse possono finire insieme, oppure " +
  "la stessa voce può restare divisa. Con Unisci e Dividi puoi correggerla, e la " +
  "correzione vale anche per le spese future.";

type LabelGroupingToggleProps = {
  grouped: boolean;
  onChange: (grouped: boolean) => void;
  disabled?: boolean;
};

/**
 * Switch tra vista raggruppata (etichetta normalizzata) e vista per nome originale.
 *
 * È anche la via di fuga immediata quando il raggruppamento automatico sbaglia:
 * "Per nome" mostra le descrizioni così come le ha scritte l'utente, senza alcuna
 * aggregazione. Il salvataggio della preferenza è a carico del chiamante.
 */
export default function LabelGroupingToggle({ grouped, onChange, disabled }: LabelGroupingToggleProps) {
  return (
    <Box display="flex" alignItems="center" gap={0.5}>
      <ToggleButtonGroup
        value={grouped ? "grouped" : "raw"}
        exclusive
        disabled={disabled}
        onChange={(_, value: string | null) => value && onChange(value === "grouped")}
        aria-label="Come raggruppare le voci di spesa"
        size="small"
        sx={{ flex: 1 }}
      >
        <ToggleButton value="grouped" sx={{ minHeight: 44, flex: 1 }}>Raggruppa</ToggleButton>
        <ToggleButton value="raw" sx={{ minHeight: 44, flex: 1 }}>Per nome</ToggleButton>
      </ToggleButtonGroup>
      <InfoButton label="Come raggruppiamo le voci di spesa" explanation={GROUPING_DISCLAIMER} />
    </Box>
  );
}
