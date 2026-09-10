"use client";

import { useState } from "react";
import { Box, Button, Menu, Typography } from "@mui/material";
import { CalendarDays } from "lucide-react";
import SwipeCalendar from "./SwipeCalendar";
import InfoButton from "./InfoButton";

function formatDisplay(iso: string): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

type SwipeDateFieldProps = {
  label: string;
  value: string;
  onChange: (iso: string) => void;
  fullWidth?: boolean;
  helperText?: string;
  required?: boolean;
  /** Spiegazione mostrata in un'icona (i) accanto al campo, per date il cui
   * significato non è ovvio dalla sola label (es. "scadenza" di cosa, esattamente). */
  infoExplanation?: string;
};

/** Sostituto di TextField type="date" senza il calendario nativo del browser:
 * stesso apice di scelta rapida, ma con lo SwipeCalendar (swipe, no preset). */
export default function SwipeDateField({ label, value, onChange, fullWidth, helperText, required, infoExplanation }: SwipeDateFieldProps) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);

  return (
    <Box sx={{ width: fullWidth ? "100%" : "auto" }}>
      <Box sx={{ display: "flex", alignItems: "stretch", gap: 0.5 }}>
        <Button
          variant="outlined"
          fullWidth={fullWidth}
          startIcon={<CalendarDays size={16} />}
          onClick={e => setAnchorEl(e.currentTarget)}
          sx={{
            justifyContent: "flex-start", textTransform: "none", fontWeight: 400,
            minHeight: 56, px: 1.75, borderColor: "divider", flex: 1, minWidth: 0,
          }}
        >
          <Box sx={{ textAlign: "left", minWidth: 0 }}>
            <Typography variant="caption" component="div" color="text.secondary">
              {label}{required ? " *" : ""}
            </Typography>
            <Typography variant="body1" component="div" color={value ? "text.primary" : "text.secondary"}>
              {value ? formatDisplay(value) : "Seleziona data"}
            </Typography>
          </Box>
        </Button>
        {infoExplanation && (
          <Box sx={{ display: "flex", alignItems: "center" }}>
            <InfoButton label={`Cosa significa ${label.toLowerCase()}`} explanation={infoExplanation} />
          </Box>
        )}
      </Box>
      {helperText && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5, ml: 1.75 }}>
          {helperText}
        </Typography>
      )}
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        <Box sx={{ p: 1 }}>
          <SwipeCalendar
            mode="single"
            value={value}
            onSelect={iso => { onChange(iso); setAnchorEl(null); }}
          />
        </Box>
      </Menu>
    </Box>
  );
}
