"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Box, Card, CardContent, CardHeader, Typography, Chip, Button, IconButton,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField,
  LinearProgress, Select, MenuItem, FormControl, InputLabel,
  ToggleButton, ToggleButtonGroup,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import { Lock, PiggyBank } from "lucide-react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { formatDateIt } from "@/lib/date";
import InfoButton from "@/components/InfoButton";
import SwipeDateField from "@/components/SwipeDateField";
import LoanWizard, { type MortgageSimulationDraft } from "./LoanWizard";
import { apiFetch, apiErrorMessage, ApiError } from "@/lib/api";
import { useSnackbar } from "@/components/feedback/useSnackbar";
import AppSnackbar from "@/components/feedback/AppSnackbar";
import PageLoader from "@/components/feedback/PageLoader";

// Stessa palette categoriale CVD-safe usata in tutta l'app (analytics/page.tsx),
// non i 4 colori brand: coerenza visiva coi grafici già esistenti.
const PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
const TOOLTIP_STYLE = { background: "#1C363D", border: "1px solid rgba(176,181,185,0.25)", borderRadius: 8, color: "#E9F1EA", fontSize: 12 };
const TICK_STYLE = { fontSize: 11, fill: "#B0B5B9" };
const LEGEND_STYLE = { color: "#B0B5B9", fontSize: 12 };

const LOAN_TYPE_LABELS: Record<string, string> = {
  mutuo_casa: "Mutuo casa",
  prestito_auto: "Prestito auto",
  prestito_personale: "Prestito personale",
  altro: "Altro",
};

interface Loan {
  id: number;
  name: string;
  loan_type: string;
  principal_amount: number;
  disbursement_date: string;
  duration_months: number;
  rate_type: string;
  tan: number;
  taeg: number | null;
  spread: number | null;
  euribor_current: number | null;
  review_frequency: string | null;
  next_review_date: string | null;
  origination_fee: number | null;
  monthly_fee: number | null;
  current_installment: number;
  residual_balance: number;
  pct_paid_off: number;
  remaining_months: number;
  estimated_end_date: string;
  remaining_interest: number;
  next_principal: number;
  next_interest: number;
  status: string;
}

interface SimpleOption { id: number; name: string }

interface ScheduleEntry { period: number; installment: number; interest: number; principal: number; residual_balance: number }

interface MortgageSimulation {
  id: number;
  name: string;
  input_snapshot: Record<string, unknown>;
  result_snapshot: { status?: string; total_monthly_payment?: number };
  status: "active" | "archived";
  converted_loan_id: number | null;
  created_at: string | null;
}

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

// Un punto ogni 12 rate: un piano trentennale renderebbe illeggibile il
// grafico a 360 punti, e all'utente interessa l'andamento, non il dettaglio
// mese per mese (già disponibile nella tabella se servisse in futuro).
function sampleSchedule(schedule: ScheduleEntry[]): ScheduleEntry[] {
  return schedule.filter((entry, index) => entry.period % 12 === 0 || index === schedule.length - 1);
}

function LoanCard({
  loan, onEdit, onDelete, onCloseLoan,
}: {
  loan: Loan;
  onEdit: (loan: Loan) => void;
  onDelete: (id: number) => void;
  onCloseLoan: (loan: Loan) => void;
}) {
  const [schedule, setSchedule] = useState<ScheduleEntry[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ schedule: ScheduleEntry[] }>(`/api/loans/${loan.id}/schedule`)
      .then((data) => { if (!cancelled) setSchedule(data.schedule || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [loan.id]);

  const currentSplit = schedule && schedule.length > 0
    ? [
        { name: "Capitale", value: schedule[0].principal },
        { name: "Interessi", value: schedule[0].interest },
      ]
    : [];

  const residualSeries = schedule
    ? [{ period: 0, residual_balance: loan.principal_amount }, ...sampleSchedule(schedule)]
    : [];
  const residualTicks = Array.from(
    { length: Math.floor(loan.duration_months / 60) + 1 },
    (_, index) => index * 60,
  );
  if (residualTicks[residualTicks.length - 1] !== loan.duration_months) {
    residualTicks.push(loan.duration_months);
  }

  return (
    <Card sx={{ mb: 3, borderRadius: 2, minWidth: 0, overflow: "hidden" }}>
      <CardHeader
        title={loan.name}
        subheader={`${LOAN_TYPE_LABELS[loan.loan_type] || loan.loan_type} · Tasso ${loan.rate_type}`}
        titleTypographyProps={{ sx: { minWidth: 0, overflowWrap: "anywhere" } }}
        subheaderTypographyProps={{ sx: { minWidth: 0, overflowWrap: "anywhere" } }}
        action={
          <Box sx={{ display: "flex", flexWrap: "wrap", justifyContent: "flex-end", flexShrink: 0 }}>
            <IconButton aria-label={`Modifica mutuo ${loan.name}`} onClick={() => onEdit(loan)} sx={{ width: 44, height: 44 }}><EditIcon fontSize="small" /></IconButton>
            {loan.status !== "closed" && <Button size="small" onClick={() => onCloseLoan(loan)}>Estinzione</Button>}
            <IconButton aria-label={`Elimina mutuo ${loan.name}`} onClick={() => onDelete(loan.id)} sx={{ width: 44, height: 44 }}><DeleteIcon fontSize="small" /></IconButton>
          </Box>
        }
      />
      <CardContent sx={{ pt: 0 }}>
        {loan.status === "closed" ? (
          <Chip label="Estinto" color="success" size="small" sx={{ mb: 1.5 }} />
        ) : loan.rate_type === "variabile" && loan.next_review_date ? (
          <Chip
            label={`Tasso da verificare: ${formatDateIt(loan.next_review_date)}`}
            color="warning" size="small" sx={{ mb: 1.5 }}
          />
        ) : null}

        <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5, alignItems: "center" }}>
          <Typography variant="body2">% estinto</Typography>
          <Box sx={{ display: "flex", alignItems: "center" }}>
            <Typography variant="body2">{loan.pct_paid_off.toFixed(1)}%</Typography>
            <InfoButton explanation="Quota di capitale già rimborsata rispetto all'importo erogato, calcolata dal piano di ammortamento francese sul TAN attuale." />
          </Box>
        </Box>
        <LinearProgress variant="determinate" value={Math.min(loan.pct_paid_off, 100)} sx={{ height: 8, borderRadius: 4, mb: 2 }} />

        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", md: "repeat(4, minmax(0, 1fr))" }, gap: { xs: 1.5, sm: 2 }, mb: 2 }}>
          <Box sx={{ minWidth: 0 }}>
            <Box sx={{ display: "flex", alignItems: "center" }}>
              <Typography variant="caption" color="text.secondary">Residuo</Typography>
              <InfoButton explanation="Capitale ancora da restituire alla banca, dedotto dalle rate già registrate." />
            </Box>
            <Typography variant="h6">{fmtCurrency(loan.residual_balance)}</Typography>
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Box sx={{ display: "flex", alignItems: "center" }}>
              <Typography variant="caption" color="text.secondary">Rata corrente</Typography>
              <InfoButton explanation="Rata di ammortamento francese sul TAN attuale. Per i tassi variabili viene ricalcolata a ogni revisione, sul saldo residuo e sulla durata rimanente." />
            </Box>
            <Typography variant="h6">{fmtCurrency(loan.current_installment)}</Typography>
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary">Tempo residuo</Typography>
            <Typography variant="h6">{loan.remaining_months} mesi</Typography>
            <Typography variant="caption" color="text.secondary">Fine stimata: {formatDateIt(loan.estimated_end_date)}</Typography>
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary">Interessi rimanenti stimati</Typography>
            <Typography variant="h6">{fmtCurrency(loan.remaining_interest)}</Typography>
          </Box>
        </Box>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Prossima rata: capitale {fmtCurrency(loan.next_principal)} · interessi {fmtCurrency(loan.next_interest)}
          {loan.rate_type === "variabile" ? ` · stima al TAN attuale (${loan.tan}%)` : ""}
        </Typography>

        {currentSplit.length > 0 && (
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "220px minmax(0, 1fr)" }, gap: 2, minWidth: 0 }}>
            <Box
              sx={{
                width: "100%",
                maxWidth: 220,
                height: 180,
                minWidth: 0,
                "& svg:focus": { outline: "none" },
                "& svg *:focus": { outline: "none" },
              }}
            >
              <Typography variant="caption" color="text.secondary">Composizione della rata</Typography>
              <ResponsiveContainer width="100%" height={150} minWidth={0}>
                <PieChart accessibilityLayer={false}>
                  <Pie activeShape={false} data={currentSplit} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={30} outerRadius={55} paddingAngle={3}>
                    {currentSplit.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                  </Pie>
                  <Tooltip cursor={false} formatter={(v: unknown) => fmtCurrency(v as number)} contentStyle={TOOLTIP_STYLE} />
                  <Legend iconType="circle" iconSize={10} wrapperStyle={LEGEND_STYLE} />
                </PieChart>
              </ResponsiveContainer>
            </Box>

            <Box sx={{ minWidth: 0, height: 180 }}>
              <Box sx={{ display: "flex", alignItems: "center" }}>
                <Typography variant="caption" color="text.secondary">Saldo residuo nel tempo</Typography>
                <InfoButton explanation="Proiezione del piano di ammortamento sul TAN attuale. Per i tassi variabili non prevede le revisioni future (dipendono dall'Euribor, non prevedibile)." />
              </Box>
              <ResponsiveContainer width="100%" height={150} minWidth={0}>
                <AreaChart data={residualSeries} accessibilityLayer={false}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(176,181,185,0.15)" />
                  <XAxis
                    dataKey="period"
                    type="number"
                    tick={TICK_STYLE}
                    ticks={residualTicks}
                    domain={[0, loan.duration_months]}
                    height={34}
                    label={{ value: "Mesi", position: "insideBottom", offset: 2, ...TICK_STYLE }}
                  />
                  <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${Math.round(v / 1000)}k`} />
                  <Tooltip cursor={false} formatter={(v: unknown) => fmtCurrency(v as number)} contentStyle={TOOLTIP_STYLE} />
                  <Area activeDot={false} type="monotone" dataKey="residual_balance" stroke="#5FC4CB" fill="rgba(95,196,203,0.2)" name="Residuo" />
                </AreaChart>
              </ResponsiveContainer>
            </Box>
          </Box>
        )}

        {schedule && schedule.length > 0 && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Piano di ammortamento</Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: { xs: "block", sm: "none" }, mb: 0.5 }}
            >
              Scorri orizzontalmente per vedere tutte le colonne.
            </Typography>
            <Box sx={{ overflowX: "auto" }}>
              <table style={{ width: "100%", minWidth: 560, borderCollapse: "collapse", fontSize: "0.8rem" }}>
                <caption style={{ textAlign: "left", paddingBottom: 8, color: "#B0B5B9" }}>Riepilogo annuale delle rate future</caption>
                <thead>
                  <tr><th scope="col">N. rata</th><th scope="col">Rata</th><th scope="col">Interessi</th><th scope="col">Capitale</th><th scope="col">Residuo</th></tr>
                </thead>
                <tbody>
                  {sampleSchedule(schedule).map((entry) => (
                    <tr key={entry.period}><td>{entry.period}</td><td>{fmtCurrency(entry.installment)}</td><td>{fmtCurrency(entry.interest)}</td><td>{fmtCurrency(entry.principal)}</td><td>{fmtCurrency(entry.residual_balance)}</td></tr>
                  ))}
                </tbody>
              </table>
            </Box>
            <Box component="details" sx={{ mt: 1.5 }}>
              <summary style={{ cursor: "pointer" }}>Dettaglio mensile</summary>
              <Box sx={{ overflowX: "auto", mt: 1 }}>
                <table style={{ width: "100%", minWidth: 560, borderCollapse: "collapse", fontSize: "0.8rem" }}>
                  <thead>
                    <tr><th scope="col">N. rata</th><th scope="col">Rata</th><th scope="col">Interessi</th><th scope="col">Capitale</th><th scope="col">Residuo</th></tr>
                  </thead>
                  <tbody>
                    {schedule.map((entry) => (
                      <tr key={entry.period}><td>{entry.period}</td><td>{fmtCurrency(entry.installment)}</td><td>{fmtCurrency(entry.interest)}</td><td>{fmtCurrency(entry.principal)}</td><td>{fmtCurrency(entry.residual_balance)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </Box>
            </Box>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}

function RateReviewDialog({
  loan, onClose, onSaved,
}: {
  loan: Loan;
  onClose: () => void;
  onSaved: () => void;
}) {
  // Stato inizializzato direttamente dalle prop (mai via effect): il genitore
  // passa `key={loan.id}` per rimontare il dialog quando cambia il mutuo
  // selezionato, invece di sincronizzare con un useEffect + setState.
  const [spread, setSpread] = useState(loan.spread != null ? String(loan.spread) : "");
  const [euribor, setEuribor] = useState(loan.euribor_current != null ? String(loan.euribor_current) : "");
  const [nextReview, setNextReview] = useState(loan.next_review_date || "");
  const [name, setName] = useState(loan.name);
  const [principal, setPrincipal] = useState(String(loan.principal_amount));
  const [duration, setDuration] = useState(String(loan.duration_months));
  const [tan, setTan] = useState(String(loan.tan));
  const [monthlyFee, setMonthlyFee] = useState(loan.monthly_fee != null ? String(loan.monthly_fee) : "");
  const [taeg, setTaeg] = useState(loan.taeg != null ? String(loan.taeg) : "");
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    const newTan = loan.rate_type === "variabile" ? (Number(spread) || 0) + (Number(euribor) || 0) : Number(tan);
    try {
      await apiFetch(`/api/loans/${loan.id}`, {
        method: "PUT",
        body: {
          spread: Number(spread) || 0,
          euribor_current: Number(euribor) || 0,
          tan: newTan,
          name,
          principal_amount: Number(principal),
          duration_months: Number(duration),
          monthly_fee: monthlyFee === "" ? null : Number(monthlyFee),
          taeg: taeg === "" ? null : Number(taeg),
          next_review_date: nextReview || null,
        },
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, "Errore di rete"));
    }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm" sx={{
      "& .MuiDialog-container": { p: { xs: 0, sm: 2 } },
      "& .MuiDialog-paper": { m: { xs: 0, sm: 2 }, width: { xs: "100%", sm: "calc(100% - 32px)" }, maxHeight: { xs: "100%", sm: "calc(100% - 64px)" } },
    }}>
      <DialogTitle>Modifica mutuo: {loan.name}</DialogTitle>
      <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, mt: 1 }}>
        <Typography variant="body2" color="text.secondary">
          Per il fisso, correggere il TAN ricostruisce il piano di riferimento; per il variabile aggiorna il futuro.
        </Typography>
        <TextField label="Nome" value={name} onChange={(e) => setName(e.target.value)} fullWidth />
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))" }, gap: 1 }}><TextField label="Capitale (€)" type="number" value={principal} onChange={(e) => setPrincipal(e.target.value)} fullWidth /><TextField label="Durata (mesi)" type="number" value={duration} onChange={(e) => setDuration(e.target.value)} fullWidth /></Box>
        {loan.rate_type === "variabile" ? <><TextField label="Spread (%)" type="number" value={spread} onChange={(e) => setSpread(e.target.value)} fullWidth /><TextField label="Euribor attuale (%)" type="number" value={euribor} onChange={(e) => setEuribor(e.target.value)} fullWidth /></> : <TextField label="TAN (%)" type="number" value={tan} onChange={(e) => setTan(e.target.value)} fullWidth />}
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))" }, gap: 1 }}><TextField label="TAEG (%)" type="number" value={taeg} onChange={(e) => setTaeg(e.target.value)} fullWidth /><TextField label="Spese incasso (€/mese)" type="number" value={monthlyFee} onChange={(e) => setMonthlyFee(e.target.value)} fullWidth /></Box>
        <SwipeDateField
          label="Prossima data di revisione" value={nextReview}
          onChange={setNextReview} fullWidth
        />
        {error && <Typography color="error" variant="body2">{error}</Typography>}
      </DialogContent>
      <DialogActions sx={{ flexWrap: "wrap", gap: 0.5 }}>
        <Button sx={{ minHeight: 44 }} onClick={onClose}>Annulla</Button>
        <Button sx={{ minHeight: 44 }} variant="contained" onClick={handleSave}>Salva</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function MutuoPage() {
  const [loans, setLoans] = useState<Loan[]>([]);
  const [simulations, setSimulations] = useState<MortgageSimulation[]>([]);
  const [accounts, setAccounts] = useState<SimpleOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [gateError, setGateError] = useState<{ error: string; plan_type?: string } | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardMode, setWizardMode] = useState<"create" | "import" | "simulate">("create");
  const [editingLoan, setEditingLoan] = useState<Loan | null>(null);
  const [editingDraft, setEditingDraft] = useState<MortgageSimulationDraft | null>(null);
  const [convertingDraft, setConvertingDraft] = useState<MortgageSimulation | null>(null);
  const [conversionDate, setConversionDate] = useState("");
  const [bufferGoalOpen, setBufferGoalOpen] = useState(false);
  const [bufferGoalLoanId, setBufferGoalLoanId] = useState("");
  const [bufferGoalMonths, setBufferGoalMonths] = useState("3");
  const [bufferGoalDate, setBufferGoalDate] = useState("");
  const [savingBufferGoal, setSavingBufferGoal] = useState(false);
  const [closingLoan, setClosingLoan] = useState<Loan | null>(null);
  const [closureMode, setClosureMode] = useState<"total" | "partial">("total");
  const [closurePrincipal, setClosurePrincipal] = useState("");
  const [closureInterest, setClosureInterest] = useState("");
  const [closureOverdue, setClosureOverdue] = useState("");
  const [closureCosts, setClosureCosts] = useState("");
  const [closureInsuranceRefund, setClosureInsuranceRefund] = useState("");
  const [partialAmount, setPartialAmount] = useState("");
  const [partialMode, setPartialMode] = useState<"reduce_payment" | "reduce_term">("reduce_payment");
  const [closureSummary, setClosureSummary] = useState<{
    remaining_installments: number; applied_tan: number; remaining_principal: number;
    avoided_future_interest: number;
  } | null>(null);
  const [closureDate, setClosureDate] = useState("");
  const { snack, showSuccess, showError, close: closeSnack } = useSnackbar();

  const loadLoans = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ loans: Loan[] }>("/api/loans");
      setGateError(null);
      setLoans(data.loans || []);
    } catch (e) {
      if (e instanceof ApiError) {
        const body = e.body && typeof e.body === "object" ? (e.body as { error?: string; plan_type?: string }) : null;
        setGateError({ error: body?.error || "Errore nel caricamento", plan_type: body?.plan_type });
      } else {
        setGateError({ error: "Errore di rete nel caricamento" });
      }
      setLoans([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSimulations = useCallback(async () => {
    try {
      const data = await apiFetch<{ simulations: MortgageSimulation[] }>("/api/mortgage-simulations");
      setSimulations(data.simulations || []);
    } catch {
      setSimulations([]);
    }
  }, []);

  useEffect(() => {
    loadLoans();
    loadSimulations();
    apiFetch<{ accounts: SimpleOption[] }>("/api/space/accounts")
      .then((data) => setAccounts(data.accounts || []))
      .catch(() => {});
  }, [loadLoans, loadSimulations]);

  const handleDelete = async (id: number) => {
    try {
      await apiFetch(`/api/loans/${id}`, { method: "DELETE" });
      showSuccess("Mutuo/finanziamento eliminato");
      loadLoans();
    } catch (e) {
      showError(apiErrorMessage(e, "Errore nell'eliminazione"));
    }
  };

  const handleCloseLoan = async () => {
    if (!closingLoan || !closureDate) return;
    const endpoint = closureMode === "partial" ? `/api/loans/${closingLoan.id}/partial-repayment` : `/api/loans/${closingLoan.id}/close`;
    const body = closureMode === "partial"
      ? { repayment_date: closureDate, amount: Number(partialAmount), mode: partialMode }
      : { closure_date: closureDate, residual_principal: Number(closurePrincipal) || undefined,
        accrued_interest: Number(closureInterest) || 0, overdue_installments: Number(closureOverdue) || 0,
        administrative_costs: Number(closureCosts) || 0, insurance_refund: Number(closureInsuranceRefund) || 0 };
    try {
      const data = await apiFetch<{
        remaining_installments: number; applied_tan: number; remaining_principal: number;
        avoided_future_interest: number;
      }>(endpoint, { method: "POST", body });
      setClosureSummary(data); setClosingLoan(null); setClosureDate(""); await loadLoans();
      showSuccess("Mutuo estinto: le rate future sono state fermate");
    } catch (e) {
      showError(apiErrorMessage(e, "Errore"));
    }
  };

  const handleDeleteDraft = async (id: number) => {
    if (!confirm("Eliminare questa bozza? L'operazione non può essere annullata.")) return;
    try {
      await apiFetch(`/api/mortgage-simulations/${id}`, { method: "DELETE" });
      showSuccess("Bozza eliminata");
      loadSimulations();
    } catch (e) {
      showError(apiErrorMessage(e, "Errore nell'eliminazione"));
    }
  };

  const handleDuplicateDraft = async (id: number) => {
    try {
      await apiFetch(`/api/mortgage-simulations/${id}/duplicate`, { method: "POST" });
      showSuccess("Bozza duplicata");
      loadSimulations();
    } catch (e) {
      showError(apiErrorMessage(e, "Errore nella duplicazione"));
    }
  };

  const handleConvertDraft = async () => {
    if (!convertingDraft || !conversionDate) return;
    const input = convertingDraft.input_snapshot;
    const payload = {
      name: convertingDraft.name,
      loan_type: String(input.loan_type || "mutuo_casa"),
      principal_amount: Number(input.principal ?? input.principal_amount ?? 0),
      disbursement_date: conversionDate,
      duration_months: Number(input.duration_months || 0),
      rate_type: input.rate_type === "variabile" ? "variabile" : "fisso",
      tan: Number(input.tan_annual ?? input.tan ?? 0),
      taeg: input.taeg ?? null,
      spread: input.spread ?? null,
      euribor_current: input.euribor_current ?? null,
      euribor_tenor: input.euribor_tenor ?? null,
      review_frequency: input.rate_type === "variabile" ? input.review_frequency : null,
      next_review_date: input.rate_type === "variabile" ? input.next_review_date : null,
      account_id: input.account_id ?? null,
      // La conversione non registra costi retroattivi: la bozza resta un what-if.
      origination_fee: null,
      monthly_fee: input.monthly_fee ?? null,
    };
    try {
      await apiFetch(`/api/mortgage-simulations/${convertingDraft.id}/convert`, {
        method: "POST", body: payload,
      });
      setConvertingDraft(null);
      showSuccess("Bozza trasformata in mutuo");
      loadLoans();
      loadSimulations();
    } catch (e) {
      showError(apiErrorMessage(e, "Errore nella conversione"));
    }
  };

  const activeLoans = loans.filter((l) => l.status === "active");
  const bufferGoalLoan = activeLoans.find((l) => String(l.id) === bufferGoalLoanId) ?? null;
  const bufferGoalMonthsNumber = Number(bufferGoalMonths) || 0;
  const bufferGoalPreviewAmount = bufferGoalLoan
    ? (bufferGoalLoan.current_installment + (bufferGoalLoan.monthly_fee || 0)) * bufferGoalMonthsNumber
    : 0;

  const openBufferGoalDialog = () => {
    setBufferGoalLoanId(activeLoans.length === 1 ? String(activeLoans[0].id) : "");
    setBufferGoalMonths("3");
    setBufferGoalDate("");
    setBufferGoalOpen(true);
  };

  const handleCreateBufferGoal = async () => {
    if (!bufferGoalLoanId || bufferGoalMonthsNumber <= 0) return;
    setSavingBufferGoal(true);
    try {
      await apiFetch(`/api/loans/${bufferGoalLoanId}/buffer-goal`, {
        method: "POST",
        body: { months: bufferGoalMonthsNumber, target_date: bufferGoalDate || null },
      });
      setBufferGoalOpen(false);
      showSuccess("Obiettivo Fondo Emergenza Mutuo creato: lo trovi in Obiettivi di risparmio");
    } catch (e) {
      showError(apiErrorMessage(e, "Errore nella creazione dell'obiettivo"));
    } finally {
      setSavingBufferGoal(false);
    }
  };

  if (loading) {
    return <PageLoader />;
  }

  if (gateError) {
    const isStorageIssue = gateError.error?.toLowerCase().includes("postgresql");
    return (
      <Box sx={{ maxWidth: 480, mx: "auto", mt: 8, textAlign: "center" }}>
        <Typography variant="h6" mb={1} sx={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 1 }}>
          <Lock size={18} strokeWidth={1.75} aria-hidden="true" />
          Mutuo/finanziamento
        </Typography>
        <Typography color="text.secondary" mb={2}>
          {isStorageIssue
            ? "Questa funzionalità richiede il DB interno. Contatta il supporto per passare da Notion al DB interno."
            : "Funzionalità riservata al piano Pro. Passa a Pro per tracciare i tuoi mutui e finanziamenti."}
        </Typography>
        <Chip label={gateError.plan_type === "pro" ? "Aggiorna storage" : "PRO"} color="warning" />
      </Box>
    );
  }

  return (
      <Box sx={{ maxWidth: 780, width: "100%", boxSizing: "border-box", mx: "auto", p: { xs: 1.5, sm: 2 }, minWidth: 0, overflowX: "hidden" }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: { xs: "flex-start", sm: "center" }, flexDirection: { xs: "column", sm: "row" }, gap: 1.5, mb: 2 }}>
        <Typography component="h1" variant="h5" sx={{ fontWeight: 300, letterSpacing: "0.015em", display: "flex", alignItems: "center", gap: 1 }}>
          Mutuo/finanziamento
        </Typography>
        <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", justifyContent: { xs: "stretch", sm: "flex-end" }, width: { xs: "100%", sm: "auto" } }}>
          <Button sx={{ flex: { xs: "1 1 calc(50% - 4px)", sm: "initial" }, minWidth: { xs: 0, sm: "auto" }, minHeight: 44 }} variant="outlined" onClick={() => { setEditingDraft(null); setWizardMode("simulate"); setWizardOpen(true); }}>Simula</Button>
          <Button sx={{ flex: { xs: "1 1 calc(50% - 4px)", sm: "initial" }, minWidth: { xs: 0, sm: "auto" }, minHeight: 44 }} variant="outlined" onClick={() => { setWizardMode("import"); setWizardOpen(true); }}>Importa mutuo</Button>
          <Button sx={{ flex: { xs: "1 1 calc(50% - 4px)", sm: "initial" }, minWidth: { xs: 0, sm: "auto" }, minHeight: 44 }} variant="contained" onClick={() => { setWizardMode("create"); setWizardOpen(true); }}>Crea mutuo</Button>
        </Box>
      </Box>

      {loans.length === 0 && (
        <Typography color="text.secondary">
          Non hai ancora nessun mutuo o finanziamento tracciato. Aggiungine uno per vedere rata, piano di ammortamento e impatto sulle tue spese.
        </Typography>
      )}

      {loans.map((loan) => (
        <LoanCard key={loan.id} loan={loan} onEdit={setEditingLoan} onDelete={handleDelete} onCloseLoan={(item) => { setClosingLoan(item); setClosureDate(new Date().toISOString().slice(0, 10)); }} />
      ))}

      {simulations.some((simulation) => simulation.status === "active") && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>Bozze salvate</Typography>
          {simulations.filter((simulation) => simulation.status === "active").map((simulation) => (
            <Card key={simulation.id} variant="outlined" sx={{ mb: 1.5, borderRadius: 2, minWidth: 0, overflow: "hidden" }}>
              <CardContent sx={{ minWidth: 0 }}>
                <Typography fontWeight={600} sx={{ overflowWrap: "anywhere" }}>{simulation.name}</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                  {fmtCurrency(Number(simulation.input_snapshot.principal ?? simulation.input_snapshot.principal_amount))} · {String(simulation.input_snapshot.tan_annual ?? simulation.input_snapshot.tan ?? "—")}% · {String(simulation.input_snapshot.duration_months ?? "—")} mesi
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Rata totale: {fmtCurrency(simulation.result_snapshot.total_monthly_payment)} · {simulation.result_snapshot.status?.replaceAll("_", " ") || "in valutazione"}
                </Typography>
                <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, max-content)" }, gap: 1, mt: 1.5 }}>
                  <Button sx={{ justifyContent: "flex-start", minHeight: 44 }} size="small" onClick={() => { setEditingDraft(simulation); setWizardMode("simulate"); setWizardOpen(true); }}>Apri bozza</Button>
                  <Button sx={{ justifyContent: "flex-start", minHeight: 44 }} size="small" onClick={() => handleDuplicateDraft(simulation.id)}>Duplica bozza</Button>
                  <Button sx={{ justifyContent: "flex-start", minHeight: 44 }} size="small" color="error" onClick={() => handleDeleteDraft(simulation.id)}>Elimina bozza</Button>
                  <Button sx={{ justifyContent: "flex-start", minHeight: 44 }} size="small" variant="contained" onClick={() => { setConvertingDraft(simulation); setConversionDate(""); }}>Trasforma in mutuo</Button>
                </Box>
              </CardContent>
            </Card>
          ))}
        </Box>
      )}

      {simulations.some((simulation) => simulation.status === "archived") && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>Storico simulazioni</Typography>
          {simulations.filter((simulation) => simulation.status === "archived").map((simulation) => (
            <Card key={simulation.id} variant="outlined" sx={{ mb: 1.5, borderRadius: 2, opacity: 0.8 }}>
              <CardContent>
                <Typography fontWeight={600}>{simulation.name}</Typography>
                <Typography variant="body2" color="text.secondary">
                  Trasformata in mutuo {simulation.converted_loan_id ? `#${simulation.converted_loan_id}` : ""}. La simulazione resta in sola lettura.
                </Typography>
              </CardContent>
            </Card>
          ))}
        </Box>
      )}

      {loans.some((l) => l.status === "active") && (
        <Card sx={{ mb: 3, borderRadius: 2, borderColor: "rgba(95,196,203,0.3)" }}>
          <CardContent sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 2, flexWrap: "wrap" }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, minWidth: 0 }}>
              <PiggyBank size={22} strokeWidth={1.5} aria-hidden="true" />
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body2" fontWeight={600} sx={{ minWidth: 0, overflowWrap: "anywhere" }}>Fondo cuscinetto</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                  Metti da parte qualche mese di rate come riserva, così un imprevisto non ti coglie impreparato.
                </Typography>
              </Box>
            </Box>
            <Button variant="outlined" onClick={openBufferGoalDialog} sx={{ width: { xs: "100%", sm: "auto" }, minHeight: 44 }}>Crea un obiettivo</Button>
          </CardContent>
        </Card>
      )}

      <LoanWizard
        open={wizardOpen}
        onClose={() => { setWizardOpen(false); setEditingDraft(null); }}
        onSaved={() => {
          showSuccess(wizardMode === "simulate" ? "Bozza salvata" : "Mutuo salvato");
          loadLoans();
          loadSimulations();
        }}
        accounts={accounts}
        mode={wizardMode}
        draft={editingDraft}
      />

      <Dialog open={Boolean(convertingDraft)} onClose={() => setConvertingDraft(null)} fullWidth maxWidth="xs" sx={{
        "& .MuiDialog-container": { p: { xs: 0, sm: 2 } },
        "& .MuiDialog-paper": { m: { xs: 0, sm: 2 }, width: { xs: "100%", sm: "calc(100% - 32px)" }, maxHeight: { xs: "100%", sm: "calc(100% - 64px)" } },
      }}>
        <DialogTitle>Trasforma in mutuo</DialogTitle>
        <DialogContent>
          <Typography color="text.secondary" sx={{ mb: 2 }}>
            Verrà creato il contratto senza generare rate o spese passate. La bozza resterà nello storico e non sarà più modificabile.
          </Typography>
          <SwipeDateField label="Data di erogazione" value={conversionDate}
            onChange={setConversionDate} fullWidth required />
        </DialogContent>
        <DialogActions sx={{ flexWrap: "wrap", gap: 0.5 }}>
          <Button sx={{ minHeight: 44 }} onClick={() => setConvertingDraft(null)}>Annulla</Button>
          <Button sx={{ minHeight: 44 }} variant="contained" onClick={handleConvertDraft} disabled={!conversionDate}>Conferma conversione</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={bufferGoalOpen} onClose={() => setBufferGoalOpen(false)} fullWidth maxWidth="xs" sx={{
        "& .MuiDialog-container": { p: { xs: 0, sm: 2 } },
        "& .MuiDialog-paper": { m: { xs: 0, sm: 2 }, width: { xs: "100%", sm: "calc(100% - 32px)" }, maxHeight: { xs: "100%", sm: "calc(100% - 64px)" } },
      }}>
        <DialogTitle>Fondo Emergenza Mutuo</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, mt: 1 }}>
          <Typography color="text.secondary">
            Mettiamo da parte qualche mese di rate come riserva: calcoliamo l&apos;importo target sommando rata e spese di incasso mensili, moltiplicate per i mesi che scegli.
          </Typography>
          {activeLoans.length > 1 && (
            <FormControl fullWidth>
              <InputLabel>Mutuo</InputLabel>
              <Select
                value={bufferGoalLoanId}
                label="Mutuo"
                onChange={(e) => setBufferGoalLoanId(e.target.value)}
              >
                {activeLoans.map((l) => <MenuItem key={l.id} value={String(l.id)}>{l.name}</MenuItem>)}
              </Select>
            </FormControl>
          )}
          <Box>
            <Typography variant="body2" sx={{ mb: 1 }}>Quanti mesi vuoi coprire?</Typography>
            <ToggleButtonGroup
              exclusive fullWidth value={bufferGoalMonths}
              onChange={(_, value) => { if (value) setBufferGoalMonths(value); }}
            >
              <ToggleButton value="3" sx={{ minHeight: 44 }}>3 mesi</ToggleButton>
              <ToggleButton value="6" sx={{ minHeight: 44 }}>6 mesi</ToggleButton>
              <ToggleButton value="12" sx={{ minHeight: 44 }}>12 mesi</ToggleButton>
            </ToggleButtonGroup>
          </Box>
          <SwipeDateField label="Scadenza (opzionale)" value={bufferGoalDate}
            onChange={setBufferGoalDate} fullWidth />
          {bufferGoalLoan && bufferGoalMonthsNumber > 0 && (
            <Typography variant="body2" color="text.secondary">
              Importo target stimato: {fmtCurrency(bufferGoalPreviewAmount)}
            </Typography>
          )}
        </DialogContent>
        <DialogActions sx={{ flexWrap: "wrap", gap: 0.5 }}>
          <Button sx={{ minHeight: 44 }} onClick={() => setBufferGoalOpen(false)}>Annulla</Button>
          <Button
            sx={{ minHeight: 44 }} variant="contained" onClick={handleCreateBufferGoal}
            disabled={!bufferGoalLoanId || bufferGoalMonthsNumber <= 0 || savingBufferGoal}
          >
            Crea obiettivo
          </Button>
        </DialogActions>
      </Dialog>

      {editingLoan && (
        <RateReviewDialog
          key={editingLoan.id}
          loan={editingLoan}
          onClose={() => setEditingLoan(null)}
          onSaved={() => { showSuccess("Tasso aggiornato"); loadLoans(); }}
        />
      )}

      {closingLoan && <Dialog open onClose={() => setClosingLoan(null)} fullWidth maxWidth="xs">
        <DialogTitle>Estinzione anticipata</DialogTitle>
        <DialogContent>
          <TextField select label="Tipo di estinzione" value={closureMode} onChange={(e) => setClosureMode(e.target.value as "total" | "partial")} fullWidth sx={{ mb: 2 }}>
            <MenuItem value="total">Totale</MenuItem><MenuItem value="partial">Parziale: anticipo di capitale</MenuItem>
          </TextField>
          <TextField label="Data di estinzione" type="date" value={closureDate} onChange={(e) => setClosureDate(e.target.value)} InputLabelProps={{ shrink: true }} fullWidth />
          {closureMode === "total" ? <>
            <TextField label="Capitale residuo (€)" type="number" value={closurePrincipal} onChange={(e) => setClosurePrincipal(e.target.value)} fullWidth sx={{ mt: 2 }} />
            <TextField label="Interessi dall'ultima rata (€)" type="number" value={closureInterest} onChange={(e) => setClosureInterest(e.target.value)} fullWidth sx={{ mt: 2 }} />
            <TextField label="Rate scadute e non pagate (€)" type="number" value={closureOverdue} onChange={(e) => setClosureOverdue(e.target.value)} fullWidth sx={{ mt: 2 }} />
            <TextField label="Costi amministrativi o di estinzione (€)" type="number" value={closureCosts} onChange={(e) => setClosureCosts(e.target.value)} fullWidth sx={{ mt: 2 }} />
            <TextField label="Rimborso assicurazione (€), se previsto" type="number" value={closureInsuranceRefund} onChange={(e) => setClosureInsuranceRefund(e.target.value)} fullWidth sx={{ mt: 2 }} />
          </> : <>
            <TextField label="Capitale da versare in anticipo (€)" type="number" value={partialAmount} onChange={(e) => setPartialAmount(e.target.value)} fullWidth sx={{ mt: 2 }} required />
            <TextField select label="Dopo il versamento voglio" value={partialMode} onChange={(e) => setPartialMode(e.target.value as typeof partialMode)} fullWidth sx={{ mt: 2 }}>
              <MenuItem value="reduce_payment">Pagare una rata più bassa</MenuItem><MenuItem value="reduce_term">Finire prima il mutuo</MenuItem>
            </TextField>
          </>}
        </DialogContent>
        <DialogActions><Button onClick={() => setClosingLoan(null)}>Annulla</Button><Button variant="contained" onClick={handleCloseLoan} disabled={!closureDate || (closureMode === "partial" && !partialAmount)}>Conferma estinzione</Button></DialogActions>
      </Dialog>}
      {closureSummary && <Dialog open onClose={() => setClosureSummary(null)} fullWidth maxWidth="xs">
        <DialogTitle>Estinzione registrata</DialogTitle>
        <DialogContent>
          <Typography>Capitale da rimborsare: <strong>{fmtCurrency(closureSummary.remaining_principal)}</strong></Typography>
          <Typography>Rate ancora previste: <strong>{closureSummary.remaining_installments}</strong></Typography>
          <Typography>Tasso applicato: <strong>{closureSummary.applied_tan.toFixed(2)}%</strong></Typography>
          <Typography>Interessi futuri evitati: <strong>{fmtCurrency(closureSummary.avoided_future_interest)}</strong></Typography>
        </DialogContent>
        <DialogActions><Button onClick={() => setClosureSummary(null)}>Chiudi</Button></DialogActions>
      </Dialog>}

      <AppSnackbar snack={snack} onClose={closeSnack} />
    </Box>
  );
}
