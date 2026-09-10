"use client";

import { Box, Card, CardContent, CardHeader, Typography } from "@mui/material";
import type { ReactNode } from "react";
import InfoButton from "../../../components/InfoButton";

type Props = {
  title: string;
  explanation: string;
  children: ReactNode;
  readout?: ReactNode;
};

/** Card per i grafici avanzati: il valore selezionato resta visibile fuori dal plot. */
export function AdvancedChartCard({ title, explanation, children, readout }: Props) {
  return (
    <Card sx={{ mb: 2, borderRadius: 2, minWidth: 0 }}>
      <CardHeader
        title={
          <Typography component="div" variant="subtitle2" fontWeight={600}>
            {title}
            <InfoButton explanation={explanation} label={`Informazioni su ${title}`} />
          </Typography>
        }
        sx={{ pb: 1, px: { xs: 1.5, sm: 2 } }}
      />
      <CardContent sx={{ pt: 0, px: { xs: 1.5, sm: 2 }, "&:last-child": { pb: 1.5 } }}>
        <div style={{ minHeight: 220, minWidth: 0, width: "100%" }}>{children}</div>
        {readout && (
          <Box component="div" color="text.secondary" sx={{ mt: 1, minHeight: 24, whiteSpace: "pre-line", fontSize: "0.875rem", lineHeight: 1.43 }}>
            {readout}
          </Box>
        )}
      </CardContent>
    </Card>
  );
}

export default AdvancedChartCard;
