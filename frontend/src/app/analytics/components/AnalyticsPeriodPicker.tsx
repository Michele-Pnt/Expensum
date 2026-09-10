"use client";

import { ToggleButton, ToggleButtonGroup } from "@mui/material";
import type { AnalyticsPeriod } from "../types";

type AnalyticsPeriodPickerProps = {
  period: AnalyticsPeriod;
  onPeriodChange: (period: AnalyticsPeriod) => void;
};

const periods: Array<{ id: Exclude<AnalyticsPeriod, "custom">; label: string }> = [
  { id: "current", label: "Questo mese" },
  { id: "three_months", label: "Ultimi 3 mesi" },
  { id: "year", label: "Anno in corso" },
];

/** Selettore di intenti temporali compatibile con le API esistenti basate sui mesi. */
export default function AnalyticsPeriodPicker({ period, onPeriodChange }: AnalyticsPeriodPickerProps) {
  const handleChange = (_event: React.MouseEvent<HTMLElement>, value: AnalyticsPeriod | null) => {
    if (value) onPeriodChange(value);
  };

  return (
    <ToggleButtonGroup
      value={period}
      exclusive
      onChange={handleChange}
      aria-label="Periodo analytics"
      size="small"
      sx={{ width: { xs: "100%", sm: "auto" }, flexWrap: "wrap" }}
    >
      {periods.map(({ id, label }) => (
        <ToggleButton key={id} value={id} sx={{ minHeight: 44, flex: { xs: 1, sm: "initial" }, px: 1.5 }}>
          {label}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}
