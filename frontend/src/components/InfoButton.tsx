"use client";

import { IconButton, Popover, Typography } from "@mui/material";
import { Info } from "lucide-react";
import { useState } from "react";

/**
 * Bottone "i" per spiegare valori calcolati, dati precompilati e scelte del form.
 * Vedi design mutuo/finanziamento — stesso pattern riusabile nelle card e nei form.
 */
type InfoButtonProps = {
  explanation: string;
  label?: string;
};

export default function InfoButton({ explanation, label }: InfoButtonProps) {
  const [anchorEl, setAnchorEl] = useState<HTMLButtonElement | null>(null);
  const isOpen = Boolean(anchorEl);

  return (
    <>
      <IconButton
        aria-label={label ?? "Scopri come viene calcolato questo dato"}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        onClick={(event) => setAnchorEl(isOpen ? null : event.currentTarget)}
        sx={{ width: 44, height: 44 }}
      >
        <Info size={14} strokeWidth={1.75} aria-hidden="true" />
      </IconButton>
      <Popover
        open={isOpen}
        anchorEl={anchorEl}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
        slotProps={{ paper: { sx: { maxWidth: 320, p: 1.5 } } }}
      >
        <Typography variant="body2">{explanation}</Typography>
      </Popover>
    </>
  );
}
