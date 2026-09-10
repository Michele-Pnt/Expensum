"use client";

import { useState } from "react";
import { Box, IconButton, Typography } from "@mui/material";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { motion } from "framer-motion";

const WEEKDAY_LABELS = ["L", "M", "M", "G", "V", "S", "D"];
const SWIPE_THRESHOLD = 50;

function toIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function parseIso(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function monthLabel(d: Date): string {
  const label = new Intl.DateTimeFormat("it-IT", { month: "long", year: "numeric" }).format(d);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/** Griglia di 42 celle (6 settimane, lunedì-domenica): null per i giorni fuori dal mese. */
function buildMonthGrid(monthDate: Date): (Date | null)[] {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstDay = new Date(year, month, 1);
  // getDay(): 0=domenica..6=sabato → offset lunedì-first (0=lunedì..6=domenica)
  const leadingBlanks = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (Date | null)[] = [];
  for (let i = 0; i < leadingBlanks; i++) cells.push(null);
  for (let day = 1; day <= daysInMonth; day++) cells.push(new Date(year, month, day));
  while (cells.length % 7 !== 0) cells.push(null);
  while (cells.length < 42) cells.push(null);
  return cells;
}

type SwipeCalendarProps =
  | {
      mode: "single";
      /** ISO selezionato, stringa vuota se nessuna data ancora scelta. */
      value: string;
      onSelect: (iso: string) => void;
    }
  | {
      mode: "range";
      /** Intervallo già confermato (mostrato evidenziato finché non parte una nuova selezione). */
      start: string;
      end: string;
      /** Chiamata solo al completamento di una nuova coppia di tap (inizio + fine). */
      onRangeSelected: (start: string, end: string) => void;
    };

/** Calendario mensile con swipe orizzontale per cambiare mese: un tap in modalità
 * "single", due tap (inizio poi fine) in modalità "range". */
export default function SwipeCalendar(props: SwipeCalendarProps) {
  const anchor = props.mode === "single" ? (props.value || toIso(new Date())) : (props.end || props.start);
  const [visibleMonth, setVisibleMonth] = useState(() => parseIso(anchor));
  const [tentativeStart, setTentativeStart] = useState<string | null>(null);

  const effectiveStart = props.mode === "range" ? (tentativeStart ?? props.start) : props.value;
  const effectiveEnd = props.mode === "range" ? (tentativeStart ? null : props.end) : null;

  function changeMonth(delta: number) {
    setVisibleMonth(d => new Date(d.getFullYear(), d.getMonth() + delta, 1));
  }

  function handleDayClick(day: Date) {
    const iso = toIso(day);
    if (props.mode === "single") {
      props.onSelect(iso);
      return;
    }
    if (!tentativeStart) {
      setTentativeStart(iso);
      return;
    }
    if (iso < tentativeStart) {
      setTentativeStart(iso);
      return;
    }
    setTentativeStart(null);
    props.onRangeSelected(tentativeStart, iso);
  }

  const grid = buildMonthGrid(visibleMonth);
  const helperText = props.mode === "single"
    ? "Scorri per cambiare mese"
    : tentativeStart ? "Scegli la data di fine" : "Scegli la data di inizio · scorri per cambiare mese";

  return (
    <Box sx={{ width: 280 }}>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", px: 0.5, pb: 1 }}>
        <IconButton aria-label="Mese precedente" onClick={() => changeMonth(-1)} sx={{ width: 36, height: 36 }}>
          <ChevronLeft size={18} />
        </IconButton>
        <Typography variant="body2" fontWeight={600}>{monthLabel(visibleMonth)}</Typography>
        <IconButton aria-label="Mese successivo" onClick={() => changeMonth(1)} sx={{ width: 36, height: 36 }}>
          <ChevronRight size={18} />
        </IconButton>
      </Box>
      <motion.div
        key={`${visibleMonth.getFullYear()}-${visibleMonth.getMonth()}`}
        drag="x"
        dragConstraints={{ left: 0, right: 0 }}
        dragElastic={0.15}
        onDragEnd={(_e, info) => {
          if (info.offset.x < -SWIPE_THRESHOLD) changeMonth(1);
          else if (info.offset.x > SWIPE_THRESHOLD) changeMonth(-1);
        }}
        initial={{ opacity: 0.4 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.15 }}
      >
        <Box sx={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 0.5, px: 0.5 }}>
          {WEEKDAY_LABELS.map((label, i) => (
            <Typography key={i} variant="caption" color="text.secondary" sx={{ textAlign: "center" }}>
              {label}
            </Typography>
          ))}
          {grid.map((day, i) => {
            if (!day) return <Box key={i} />;
            const iso = toIso(day);
            const isStart = iso === effectiveStart;
            const isEnd = effectiveEnd != null && iso === effectiveEnd;
            const isInRange = effectiveEnd != null && iso > effectiveStart && iso < effectiveEnd;
            const isToday = iso === toIso(new Date());
            return (
              <Box
                key={i}
                component="button"
                type="button"
                onClick={() => handleDayClick(day)}
                aria-label={day.toLocaleDateString("it-IT", { day: "numeric", month: "long", year: "numeric" })}
                aria-pressed={isStart || isEnd}
                sx={{
                  minHeight: 36, minWidth: 36, border: "none", cursor: "pointer",
                  fontFamily: "inherit", fontSize: "0.85rem",
                  borderRadius: isInRange ? 0 : "50%",
                  bgcolor: isStart || isEnd ? "primary.main" : isInRange ? "rgba(95,196,203,0.15)" : "transparent",
                  color: isStart || isEnd ? "primary.contrastText" : "text.primary",
                  outline: isToday && !isStart && !isEnd ? "1px solid" : "none",
                  outlineColor: "primary.main",
                  "&:hover": { bgcolor: isStart || isEnd ? "primary.main" : "action.hover" },
                }}
              >
                {day.getDate()}
              </Box>
            );
          })}
        </Box>
      </motion.div>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", px: 0.5, pt: 1 }}>
        {helperText}
      </Typography>
    </Box>
  );
}
