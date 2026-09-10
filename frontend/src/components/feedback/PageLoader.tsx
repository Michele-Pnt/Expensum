"use client";

import { Box, CircularProgress, type SxProps, type Theme } from "@mui/material";

interface PageLoaderProps {
  size?: number;
  sx?: SxProps<Theme>;
}

/** Spinner centrato standard per il caricamento di una pagina o sezione intera,
 * prima duplicato in ~8 pagine. `sx` sovrascrive lo spazio verticale di default
 * (`mt: 8`), utile per varianti più compatte dentro una pagina già renderizzata. */
export default function PageLoader({ size = 40, sx }: PageLoaderProps) {
  return (
    <Box sx={{ display: "flex", justifyContent: "center", mt: 8, ...sx }}>
      <CircularProgress size={size} />
    </Box>
  );
}
