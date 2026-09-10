"use client";

import type { ReactNode } from "react";
import {
  Box, Card, CircularProgress, FormControl, IconButton, InputLabel, MenuItem, Select,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TableSortLabel,
  Tooltip, Typography, useMediaQuery, useTheme,
} from "@mui/material";
import { ArrowDownAZ, ArrowUpAZ } from "lucide-react";

export type Column<T> = {
  key: string;
  header: string;
  align?: "left" | "right";
  sortable?: boolean;
  /** Non ripetuta nella card mobile (es. già inclusa in mobilePrimary/mobileSecondary). */
  hideOnMobileCard?: boolean;
  width?: number | string;
  render: (row: T) => ReactNode;
};

type ResponsiveDataTableProps<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  loading?: boolean;
  emptyLabel?: string;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  onSort?: (field: string) => void;
  mobilePrimary: (row: T) => ReactNode;
  mobileSecondary?: (row: T) => ReactNode;
  mobileAmount?: (row: T) => ReactNode;
  actions?: (row: T) => ReactNode;
  ariaLabel: string;
  minWidth?: number;
};

/** Tabella su desktop, lista di card impilate su mobile: stessa fonte dati/sort, niente scroll orizzontale sotto sm. */
export default function ResponsiveDataTable<T>({
  columns, rows, rowKey, loading, emptyLabel = "Nessun elemento trovato",
  sortBy, sortDir = "asc", onSort, mobilePrimary, mobileSecondary, mobileAmount,
  actions, ariaLabel, minWidth = 600,
}: ResponsiveDataTableProps<T>) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const sortableColumns = columns.filter(c => c.sortable);

  if (isMobile) {
    return (
      <Box role="region" aria-label={ariaLabel}>
        {sortableColumns.length > 0 && onSort && (
          <Box sx={{ px: 2, pt: 1.5, pb: 0.5, display: "flex", alignItems: "center", gap: 1 }}>
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel sx={{ fontSize: "0.75rem" }}>Ordina per</InputLabel>
              <Select
                label="Ordina per"
                value={sortBy ?? sortableColumns[0].key}
                onChange={e => onSort(e.target.value as string)}
                sx={{ fontSize: "0.8rem" }}
              >
                {sortableColumns.map(c => (
                  <MenuItem key={c.key} value={c.key} sx={{ fontSize: "0.85rem" }}>
                    {c.header}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Tooltip title={sortDir === "asc" ? "Crescente" : "Decrescente"}>
              {/* Il click chiama onSort con lo stesso campo già selezionato: la logica
                  di toggle asc/desc vive nei gestori onSort di ciascuna tab (stessa
                  usata da TableSortLabel su desktop) — qui serve solo a invocarla
                  quando la select non cambia valore (nessun onChange in quel caso). */}
              <IconButton
                aria-label={sortDir === "asc" ? "Ordine crescente, tocca per invertire" : "Ordine decrescente, tocca per invertire"}
                onClick={() => onSort(sortBy ?? sortableColumns[0].key)}
                sx={{ width: 44, height: 44, color: "primary.main" }}
              >
                {sortDir === "asc" ? <ArrowUpAZ size={18} /> : <ArrowDownAZ size={18} />}
              </IconButton>
            </Tooltip>
          </Box>
        )}
        <Box sx={{ display: "grid", gap: 1, p: 1.5 }}>
          {rows.map(row => (
            <Card key={rowKey(row)} sx={{ p: 1.5 }}>
              <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 1.5 }}>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography component="div" fontWeight={600} sx={{ overflowWrap: "anywhere" }}>
                    {mobilePrimary(row)}
                  </Typography>
                  {mobileSecondary && (
                    <Typography component="div" variant="body2" color="text.secondary" sx={{ mt: 0.25, overflowWrap: "anywhere" }}>
                      {mobileSecondary(row)}
                    </Typography>
                  )}
                </Box>
                {mobileAmount && (
                  <Typography component="div" fontWeight={600} whiteSpace="nowrap">
                    {mobileAmount(row)}
                  </Typography>
                )}
              </Box>
              {actions && (
                <Box sx={{ display: "flex", justifyContent: "flex-end", mt: 1 }}>
                  {actions(row)}
                </Box>
              )}
            </Card>
          ))}
          {!loading && rows.length === 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center", py: 4 }}>
              {emptyLabel}
            </Typography>
          )}
          {loading && (
            <Box sx={{ display: "flex", justifyContent: "center", py: 3 }}>
              <CircularProgress size={20} sx={{ color: "text.secondary" }} />
            </Box>
          )}
        </Box>
      </Box>
    );
  }

  return (
    <TableContainer sx={{ overflowX: "auto" }}>
      <Table size="small" sx={{ minWidth }} aria-label={ariaLabel}>
        <TableHead>
          <TableRow>
            {columns.map(col => (
              <TableCell
                key={col.key}
                sx={{
                  fontSize: "0.75rem", fontWeight: 500, color: "text.secondary", py: 1,
                  textAlign: col.align ?? "left", width: col.width,
                }}
              >
                {col.sortable && onSort ? (
                  <TableSortLabel
                    active={sortBy === col.key}
                    direction={sortBy === col.key ? sortDir : "asc"}
                    onClick={() => onSort(col.key)}
                    sx={{ fontSize: "inherit", fontWeight: "inherit", color: "inherit", "&.Mui-active": { color: "primary.main" } }}
                  >
                    {col.header}
                  </TableSortLabel>
                ) : col.header}
              </TableCell>
            ))}
            {actions && <TableCell sx={{ width: 96 }} />}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map(row => (
            <TableRow key={rowKey(row)} hover>
              {columns.map(col => (
                <TableCell key={col.key} sx={{ fontSize: "0.8rem", py: 1, textAlign: col.align ?? "left" }}>
                  {col.render(row)}
                </TableCell>
              ))}
              {actions && (
                <TableCell sx={{ fontSize: "0.8rem", py: 1 }}>
                  {actions(row)}
                </TableCell>
              )}
            </TableRow>
          ))}
          {!loading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={columns.length + (actions ? 1 : 0)} sx={{ textAlign: "center", py: 4, color: "text.secondary", fontSize: "0.85rem" }}>
                {emptyLabel}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
