"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField,
  Select, MenuItem, FormControl, InputLabel, Box,
  ToggleButton, ToggleButtonGroup, Typography, Divider,
} from "@mui/material";
import { apiFetch, apiErrorMessage } from "@/lib/api";
import { formatDateIt } from "@/lib/date";
import SwipeDateField from "@/components/SwipeDateField";
import {
  calculateLoanPreview,
  formatDateInputValue,
} from "@/lib/loanCalculator";
import MortgageSustainabilityPanel, {
  type MortgageSustainabilityDraftInput,
} from "./MortgageSustainabilityPanel";
import InfoButton from "@/components/InfoButton";

interface SimpleOption { id: number; name: string }

export interface MortgageSimulationDraft {
  id: number;
  name: string;
  input_snapshot: Record<string, unknown>;
}

const LOAN_TYPE_LABELS: Record<string, string> = {
  mutuo_casa: "Mutuo casa",
  prestito_auto: "Prestito auto",
  prestito_personale: "Prestito personale",
  altro: "Altro",
};

const REVIEW_FREQUENCY_LABELS: Record<string, string> = {
  trimestrale: "Trimestrale",
  semestrale: "Semestrale",
  anniversario: "Anniversario del contratto",
};

const STEPS = ["Dati del prestito, tasso e costi"];

const EMPTY_FORM = {
  name: "",
  loan_type: "mutuo_casa",
  principal_amount: "",
  disbursement_date: "",
  duration_months: "",
  account_id: "",
  rate_type: "fisso" as "fisso" | "variabile",
  tan: "",
  taeg_mode: "calculated" as "provided" | "calculated",
  taeg: "",
  spread: "",
  euribor_current: "",
  euribor_tenor: "3m",
  review_frequency: "trimestrale",
  next_review_date: "",
  origination_fee: "",
  monthly_fee: "",
  payment_cadence: "monthly",
  prepayment_amount: "",
  prepayment_date: "",
  prepayment_installment: "",
  prepayment_mode: "reduce_payment" as "reduce_payment" | "reduce_term",
};

// Prefill facoltativo dal calcolatore pubblico sul sito (vedi
// frontend/src/app/[locale]/mutuo/MutuoCalculatorClient.tsx): la query string
// non sopravvive al redirect di /register (pagina Flask), quindi il passaggio
// avviene via localStorage con questa stessa chiave.
const HANDOFF_KEY = "expensum_mutuo_calc_handoff";

function readHandoff(): Partial<typeof EMPTY_FORM> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(HANDOFF_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    window.localStorage.removeItem(HANDOFF_KEY);
    return {
      principal_amount: String(data.principal ?? ""),
      duration_months: String(data.durationMonths ?? ""),
      rate_type: data.rateType === "variabile" ? "variabile" : "fisso",
      tan: String(data.tan ?? ""),
      origination_fee: data.originationFee ? String(data.originationFee) : "",
      monthly_fee: data.monthlyFee ? String(data.monthlyFee) : "",
    };
  } catch {
    return null;
  }
}

function parseAmount(value: string): number {
  return Number(value.replace(/\./g, "").replace(",", ".")) || 0;
}

function formatAmount(value: string): string {
  if (!value) return "";
  const [integer, decimals] = value.replace(/\./g, "").split(",");
  const formatted = Number(integer || 0).toLocaleString("it-IT");
  return decimals == null ? formatted : `${formatted},${decimals.slice(0, 2)}`;
}

function sustainabilityInputsEqual(
  left: MortgageSustainabilityDraftInput,
  right: MortgageSustainabilityDraftInput,
): boolean {
  return left.monthly_income === right.monthly_income
    && left.essential_monthly_expenses === right.essential_monthly_expenses
    && left.monthly_savings_target === right.monthly_savings_target
    && left.preserve_savings === right.preserve_savings
    && left.goal_strategy === right.goal_strategy
    && left.selected_category_ids.length === right.selected_category_ids.length
    && left.selected_category_ids.every((id, index) => id === right.selected_category_ids[index]);
}

export default function LoanWizard({
  open, onClose, onSaved, accounts, mode = "create", draft,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  accounts: SimpleOption[];
  mode?: "create" | "import" | "simulate";
  draft?: MortgageSimulationDraft | null;
}) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [draftSustainabilityInput, setDraftSustainabilityInput] =
    useState<MortgageSustainabilityDraftInput>({
      preserve_savings: true,
      selected_category_ids: [],
      goal_strategy: "maintain",
    });

  const handleDraftSustainabilityInputChange = useCallback(
    (input: MortgageSustainabilityDraftInput) => {
      setDraftSustainabilityInput((current) => (
        sustainabilityInputsEqual(current, input) ? current : input
      ));
    },
    [],
  );

  useEffect(() => {
    if (open) {
      const handoff = readHandoff();
      const saved = draft?.input_snapshot;
      const initialSustainabilityInput: MortgageSustainabilityDraftInput = saved ? {
        monthly_income: saved.monthly_income == null ? undefined : String(saved.monthly_income),
        essential_monthly_expenses: saved.essential_monthly_expenses == null
          ? undefined : String(saved.essential_monthly_expenses),
        monthly_savings_target: saved.monthly_savings_target == null
          ? undefined : String(saved.monthly_savings_target),
        preserve_savings: saved.preserve_savings == null ? true : Boolean(saved.preserve_savings),
        selected_category_ids: Array.isArray(saved.selected_category_ids)
          ? saved.selected_category_ids.filter((id): id is number => typeof id === "number")
          : [],
        goal_strategy: saved.goal_strategy === "extend" || saved.goal_strategy === "abandon" ? saved.goal_strategy : "maintain",
      } : { preserve_savings: true, selected_category_ids: [], goal_strategy: "maintain" };
      const restored = saved ? {
        name: draft.name,
        loan_type: String(saved.loan_type || "mutuo_casa"),
        principal_amount: String(saved.principal ?? saved.principal_amount ?? ""),
        disbursement_date: String(saved.disbursement_date || ""),
        duration_months: String(saved.duration_months || ""),
        account_id: saved.account_id == null ? "" : String(saved.account_id),
        rate_type: saved.rate_type === "variabile" ? "variabile" as const : "fisso" as const,
        tan: String(saved.tan_annual ?? saved.tan ?? ""),
        taeg_mode: saved.taeg ? "provided" as const : "calculated" as const,
        taeg: saved.taeg == null ? "" : String(saved.taeg),
        spread: saved.spread == null ? "" : String(saved.spread),
        euribor_current: saved.euribor_current == null ? "" : String(saved.euribor_current),
        euribor_tenor: String(saved.euribor_tenor || "3m"),
        review_frequency: String(saved.review_frequency || "trimestrale"),
        next_review_date: String(saved.next_review_date || ""),
        origination_fee: String(saved.upfront_fee ?? saved.origination_fee ?? ""),
        monthly_fee: String(saved.monthly_fee ?? ""),
        prepayment_amount: saved.prepayment_amount == null ? "" : String(saved.prepayment_amount),
        prepayment_date: String(saved.prepayment_date || ""),
        prepayment_installment: saved.prepayment_installment == null ? "" : String(saved.prepayment_installment),
        prepayment_mode: saved.prepayment_mode === "reduce_term" ? "reduce_term" as const : "reduce_payment" as const,
      } : null;
      const initialForm = { ...EMPTY_FORM, ...(handoff || restored || {}) };
      if (mode === "simulate" && !initialForm.disbursement_date) {
        initialForm.disbursement_date = formatDateInputValue();
      }
      setForm(initialForm);
      setStep(0);
      setError(null);
      setDraftSustainabilityInput(initialSustainabilityInput);
    }
  }, [open, draft, mode]);

  const set = (field: keyof typeof EMPTY_FORM, value: string) => setForm((f) => ({ ...f, [field]: value }));
  const effectiveTan = form.rate_type === "variabile"
    ? (Number(form.euribor_current) || 0) + (Number(form.spread) || 0)
    : Number(form.tan);

  const preview = useMemo(() => {
    const principal = parseAmount(form.principal_amount);
    const durationMonths = Number(form.duration_months);
    const hasRate = form.rate_type === "variabile"
      ? form.euribor_current.trim() && form.spread.trim()
      : form.tan.trim();
    if (principal <= 0 || durationMonths <= 0 || !hasRate || effectiveTan < 0) return null;

    return calculateLoanPreview({
      principal,
      tanAnnual: effectiveTan,
      durationMonths,
      providedTaeg: form.taeg_mode === "provided" && form.taeg ? Number(form.taeg) : null,
      upfrontFee: Number(form.origination_fee) || 0,
      monthlyFee: Number(form.monthly_fee) || 0,
      startDate: form.disbursement_date || null,
      prepaymentAmount: Number(form.prepayment_amount) || 0,
      prepaymentDate: form.prepayment_date || null,
      prepaymentInstallment: Number(form.prepayment_installment) || undefined,
      prepaymentMode: form.prepayment_amount ? form.prepayment_mode : null,
    });
  }, [
    form.duration_months,
    effectiveTan,
    form.monthly_fee,
    form.origination_fee,
    form.principal_amount,
    form.rate_type,
    form.euribor_current,
    form.spread,
    form.tan,
    form.taeg,
    form.taeg_mode,
    form.disbursement_date,
    form.prepayment_amount,
    form.prepayment_date,
    form.prepayment_installment,
    form.prepayment_mode,
  ]);

  const buildPayload = () => ({
    name: form.name,
    loan_type: form.loan_type,
    principal_amount: parseAmount(form.principal_amount),
    disbursement_date: form.disbursement_date,
    duration_months: Number(form.duration_months) || 0,
    account_id: form.account_id || null,
    rate_type: form.rate_type,
    tan: effectiveTan || 0,
    taeg: form.taeg_mode === "provided" && form.taeg
      ? Number(form.taeg)
      : preview?.taeg ?? null,
    spread: form.rate_type === "variabile" && form.spread ? Number(form.spread) : null,
    euribor_current: form.rate_type === "variabile" && form.euribor_current ? Number(form.euribor_current) : null,
    euribor_tenor: form.rate_type === "variabile" ? form.euribor_tenor : null,
    review_frequency: form.rate_type === "variabile" ? form.review_frequency : null,
    next_review_date: form.rate_type === "variabile" ? (form.next_review_date || null) : null,
    origination_fee: form.origination_fee ? Number(form.origination_fee) : null,
    monthly_fee: form.monthly_fee ? Number(form.monthly_fee) : null,
    payment_cadence: form.payment_cadence,
    prepayment_amount: form.prepayment_amount ? Number(form.prepayment_amount) : null,
    prepayment_date: form.prepayment_date || null,
    prepayment_installment: form.prepayment_installment ? Number(form.prepayment_installment) : null,
    prepayment_mode: form.prepayment_amount ? form.prepayment_mode : null,
  });

  const handleNext = () => {
    setError(null);
    if (step === 0) {
      if (!form.principal_amount || !form.duration_months || (
        mode !== "simulate" && (!form.name.trim() || !form.disbursement_date)
      )) {
        setError("Compila tutti i campi obbligatori.");
        return;
      }
    }
    if (step === 0) {
      if (form.rate_type === "fisso" && !form.tan.trim()) {
        setError("Il TAN è obbligatorio.");
        return;
      }
      if (form.rate_type === "variabile" && (!form.euribor_current.trim() || !form.spread.trim())) {
        setError("Inserisci Euribor e spread per calcolare il TAN.");
        return;
      }
      if (form.rate_type === "variabile" && !form.review_frequency) {
        setError("Scegli la frequenza di revisione del tasso.");
        return;
      }
    }
    if (step === 1 && form.taeg_mode === "provided" && !form.taeg.trim()) {
      setError("Inserisci il TAEG indicato dalla banca.");
      return;
    }
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };

  const handleBack = () => setStep((s) => Math.max(s - 1, 0));

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const simulationPayload = {
        name: form.name || "Simulazione mutuo",
        principal: parseAmount(form.principal_amount),
        tan_annual: effectiveTan || 0,
        duration_months: Number(form.duration_months) || 0,
        rate_type: form.rate_type,
        loan_type: form.loan_type,
        disbursement_date: form.disbursement_date || null,
        account_id: form.account_id || null,
        tan: effectiveTan || 0,
        taeg: form.taeg_mode === "provided" && form.taeg ? Number(form.taeg) : preview?.taeg ?? null,
        spread: form.rate_type === "variabile" && form.spread ? Number(form.spread) : null,
        euribor_current: form.rate_type === "variabile" && form.euribor_current ? Number(form.euribor_current) : null,
        euribor_tenor: form.rate_type === "variabile" ? form.euribor_tenor : null,
        review_frequency: form.rate_type === "variabile" ? form.review_frequency : null,
        next_review_date: form.rate_type === "variabile" ? (form.next_review_date || null) : null,
        monthly_fee: Number(form.monthly_fee) || 0,
        payment_cadence: form.payment_cadence,
        upfront_fee: Number(form.origination_fee) || 0,
        prepayment_amount: form.prepayment_amount ? Number(form.prepayment_amount) : null,
        prepayment_date: form.prepayment_date || null,
        prepayment_installment: form.prepayment_installment ? Number(form.prepayment_installment) : null,
        prepayment_mode: form.prepayment_amount ? form.prepayment_mode : null,
        ...draftSustainabilityInput,
      };
      const simulationUrl = draft ? `/api/mortgage-simulations/${draft.id}` : "/api/mortgage-simulations";
      await apiFetch(mode === "simulate" ? simulationUrl : "/api/loans", {
        method: mode === "simulate" && draft ? "PUT" : "POST",
        body: mode === "simulate" ? simulationPayload : buildPayload(),
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, "Errore di rete"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      sx={{
        "& .MuiDialog-paper": {
          m: { xs: 0, sm: 4 },
          width: { xs: "100%", sm: "calc(100% - 64px)" },
          maxHeight: { xs: "100%", sm: "calc(100% - 64px)" },
          borderRadius: { xs: 0, sm: 1 },
        },
      }}
    >
      <DialogTitle sx={{ minWidth: 0, overflowWrap: "anywhere" }}>
        {mode === "simulate" ? "Simula mutuo" : mode === "import" ? "Importa mutuo esistente" : "Nuovo mutuo/finanziamento"}
      </DialogTitle>
      <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 1.25, mt: 0, minWidth: 0, pb: { xs: 10, sm: 2 } }}>
        {step === 0 && (
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))" }, gap: 2, alignItems: "start" }}>
            <TextField sx={{ gridColumn: "span 2" }} label="Nome" value={form.name} onChange={(e) => set("name", e.target.value)} fullWidth />
            <FormControl fullWidth sx={{ gridColumn: "span 2" }}>
              <InputLabel>Tipo</InputLabel>
              <Select value={form.loan_type ?? "mutuo_casa"} label="Tipo" onChange={(e) => set("loan_type", e.target.value)}>
                {Object.entries(LOAN_TYPE_LABELS).map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField
              label={mode === "import" ? "Debito residuo (€)" : "Importo erogato (€)"} type="text" inputMode="decimal" value={formatAmount(form.principal_amount)}
              onChange={(e) => set("principal_amount", e.target.value.replace(/[^0-9,]/g, ""))} fullWidth
            />
            <SwipeDateField
              label="Data di erogazione" value={form.disbursement_date}
              onChange={iso => set("disbursement_date", iso)}
              fullWidth
            />
            <TextField
              label="Durata (mesi)" type="number" value={form.duration_months}
              onChange={(e) => set("duration_months", e.target.value)} fullWidth
            />
            <FormControl fullWidth>
              <InputLabel>Cadenza della rata</InputLabel>
              <Select value={form.payment_cadence ?? "monthly"} label="Cadenza della rata"
                onChange={(e) => set("payment_cadence", e.target.value)}>
                <MenuItem value="monthly">Mensile</MenuItem>
                <MenuItem value="quarterly">Trimestrale</MenuItem>
                <MenuItem value="semiannual">Semestrale</MenuItem>
                <MenuItem value="yearly">Annuale</MenuItem>
              </Select>
            </FormControl>
            <FormControl fullWidth sx={{ gridColumn: "span 2" }}>
              <InputLabel>Conto collegato (opzionale)</InputLabel>
              <Select
                value={form.account_id ?? ""} label="Conto collegato (opzionale)"
                onChange={(e) => set("account_id", e.target.value)}
              >
                <MenuItem value="">Nessuno</MenuItem>
                {accounts.map((a) => <MenuItem key={a.id} value={String(a.id)}>{a.name}</MenuItem>)}
              </Select>
            </FormControl>
            <Box sx={{ gridColumn: "span 2", border: "1px solid", borderColor: "divider", borderRadius: 2, p: 1.5 }}>
              <Typography variant="subtitle2" sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                Rimborso anticipato (facoltativo)
                <InfoButton label="Spiega rimborso anticipato" explanation="Puoi indicare una somma che vuoi versare in anticipo per ridurre il debito. Il calcolo mostra l'effetto sulla rata o sulla durata; potrai confermare il versamento anche in seguito dalla gestione del mutuo." />
              </Typography>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))" }, gap: 1.5, mt: 1.5 }}>
                <TextField label="Somma da versare in anticipo (€)" type="number" value={form.prepayment_amount ?? ""} onChange={(e) => set("prepayment_amount", e.target.value)} fullWidth slotProps={{ htmlInput: { min: 0, step: 0.01 } }} />
                <SwipeDateField label="Data del versamento (facoltativa)" value={form.prepayment_date ?? ""} onChange={(iso) => set("prepayment_date", iso)} fullWidth />
                <TextField label="Oppure numero della rata" type="number" value={form.prepayment_installment ?? ""} onChange={(e) => set("prepayment_installment", e.target.value)} fullWidth slotProps={{ htmlInput: { min: 1, step: 1 } }} />
                <FormControl fullWidth>
                  <InputLabel>Dopo il versamento voglio</InputLabel>
                  <Select value={form.prepayment_mode ?? "reduce_payment"} label="Dopo il versamento voglio" onChange={(e) => set("prepayment_mode", e.target.value as typeof form.prepayment_mode)}>
                    <MenuItem value="reduce_payment">Una rata più bassa</MenuItem>
                    <MenuItem value="reduce_term">Finire prima il mutuo</MenuItem>
                  </Select>
                </FormControl>
              </Box>
            </Box>
            <ToggleButtonGroup
              exclusive fullWidth value={form.rate_type ?? "fisso"} sx={{ gridColumn: "span 2" }}
              onChange={(_, v) => v && set("rate_type", v)}
            >
              <ToggleButton value="fisso">Fisso</ToggleButton>
              <ToggleButton value="variabile">Variabile</ToggleButton>
            </ToggleButtonGroup>
            {form.rate_type === "fisso" && <TextField
              label="TAN (%)" type="number" value={form.tan}
              onChange={(e) => set("tan", e.target.value)}
              onWheel={(event) => { event.preventDefault(); event.currentTarget.blur(); }}
              onTouchStart={(event) => event.stopPropagation()}
              onTouchMove={(event) => event.preventDefault()}
              sx={{ "& input": { touchAction: "none" } }}
              InputProps={{ endAdornment: <InfoButton label="Spiega TAN" explanation="È il tasso annuo applicato al mutuo. Insieme all'importo e alla durata serve a calcolare la rata." /> }} fullWidth
            />}
            {form.rate_type === "variabile" && (
              <>
                <Divider sx={{ gridColumn: { sm: "span 2" } }} />
                <TextField
                  label="Spread (%)" type="number" value={form.spread}
                  onChange={(e) => set("spread", e.target.value)} fullWidth
                />
                <TextField
                  label="Euribor attuale (%)" type="number" value={form.euribor_current}
                  onChange={(e) => set("euribor_current", e.target.value)}
                  InputProps={{ endAdornment: <InfoButton label="Spiega Euribor" explanation="È il valore di riferimento del mercato. Inseriscilo come riportato nel preventivo della banca: Expensum non lo aggiorna automaticamente." /> }} fullWidth
                />
                <Typography variant="body2" color="text.secondary" sx={{ display: "flex", alignItems: "center" }}>Tasso applicato oggi: {effectiveTan.toFixed(2)}%<InfoButton label="Spiega tasso applicato" explanation="È il tasso di oggi, ottenuto sommando Euribor e spread indicati nel preventivo." /></Typography>
                <FormControl fullWidth>
                  <InputLabel>Frequenza di revisione</InputLabel>
                  <Select
                    value={form.review_frequency ?? "trimestrale"} label="Frequenza di revisione"
                    onChange={(e) => set("review_frequency", e.target.value)}
                  >
                    {Object.entries(REVIEW_FREQUENCY_LABELS).map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
                  </Select>
                </FormControl>
                <SwipeDateField
                  label="Prossima data di revisione" value={form.next_review_date}
                  onChange={iso => set("next_review_date", iso)} fullWidth
                />
              </>
            )}
          </Box>
        )}

        {step === 0 && (
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", sm: "repeat(2, minmax(0, 1fr))" }, gap: 2, alignItems: "start" }}>
            <Typography variant="body2" color="text.secondary" sx={{ gridColumn: "span 2" }}>
              Come vuoi indicare il TAEG?
            </Typography>
            <ToggleButtonGroup
              exclusive fullWidth value={form.taeg_mode ?? "calculated"} sx={{ gridColumn: "span 2" }}
              onChange={(_, value) => value && set("taeg_mode", value)}
              aria-label="Modalità di inserimento del TAEG"
            >
              <ToggleButton value="provided">Inserisco il TAEG</ToggleButton>
              <ToggleButton value="calculated">Calcola dai costi</ToggleButton>
            </ToggleButtonGroup>

            {form.taeg_mode === "provided" ? (
              <TextField
                label="TAEG (%)" type="number" value={form.taeg}
                onChange={(e) => set("taeg", e.target.value)}
                InputProps={{ endAdornment: <InfoButton label="Spiega TAEG" explanation="È il costo complessivo annuo del mutuo, comprese molte spese. Usa il valore indicato dalla banca." /> }}
                slotProps={{ htmlInput: { step: 0.01, min: 0 } }} fullWidth
              />
            ) : (
              <>
                <TextField
                  label="Istruttoria (€ una tantum)" type="number" value={form.origination_fee}
                  onChange={(e) => set("origination_fee", e.target.value)}
                  InputProps={{ endAdornment: <InfoButton label="Spiega istruttoria" explanation="È una spesa pagata una sola volta per la pratica del mutuo." /> }}
                  slotProps={{ htmlInput: { step: 0.01, min: 0 } }} fullWidth
                />
                <TextField
                  label="Spese incasso rata (€/mese)" type="number" value={form.monthly_fee}
                  onChange={(e) => set("monthly_fee", e.target.value)}
                  InputProps={{ endAdornment: <InfoButton label="Spiega spese rata" explanation="È il costo aggiunto ogni mese per l'incasso della rata." /> }}
                  slotProps={{ htmlInput: { step: 0.01, min: 0 } }} fullWidth
                />
              </>
            )}
          </Box>
        )}

        {preview && (
            <Box sx={{
            p: 2,
            minWidth: 0,
            overflowWrap: "anywhere",
            borderRadius: 2,
            bgcolor: "rgba(95,196,203,0.08)",
            border: "1px solid rgba(95,196,203,0.3)",
          }}>
            <Typography variant="subtitle1" fontWeight={700}>Effetto della tua scelta</Typography>
            <Typography variant="caption" color="text.secondary">
              Si aggiorna appena cambi durata, TAN, Euribor, spread o costi.
            </Typography>
            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))" }, gap: 1.5, mt: 1.5 }}>
              <Box>
                <Typography variant="body2" color="text.secondary">Rata mutuo</Typography>
                <Typography variant="h6">
                  {preview.installment.toLocaleString("it-IT", { style: "currency", currency: "EUR" })}
                </Typography>
              </Box>
              <Box>
                <Typography variant="body2" color="text.secondary">Totale mensile</Typography>
                <Typography variant="h6" color="primary.main">
                  {preview.monthlyTotal.toLocaleString("it-IT", { style: "currency", currency: "EUR" })}
                </Typography>
              </Box>
              <Box>
                <Typography variant="body2" color="text.secondary">Interessi totali</Typography>
                <Typography variant="body1" fontWeight={600}>
                  {preview.totalInterest.toLocaleString("it-IT", { style: "currency", currency: "EUR" })}
                </Typography>
              </Box>
              <Box>
                <Typography variant="body2" color="text.secondary">Costo complessivo</Typography>
                <Typography variant="body1" fontWeight={600}>
                  {preview.totalPaid.toLocaleString("it-IT", { style: "currency", currency: "EUR" })}
                </Typography>
              </Box>
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Costi accessori: {preview.accessoryCosts.toLocaleString("it-IT", {
                style: "currency", currency: "EUR",
              })} (istruttoria + spese rata)
            </Typography>
            <Divider sx={{ my: 1.5 }} />
            <Typography variant="body2" color="text.secondary">
              Fine stimata: {preview.estimatedEndDate ? formatDateIt(preview.estimatedEndDate) : "inserisci la data di erogazione"}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {form.taeg_mode === "provided" && form.taeg
                ? "TAEG indicato"
                : "TAEG calcolato"}: {preview.taeg.toFixed(2)}%
            </Typography>
          </Box>
        )}

        {preview && (
          <MortgageSustainabilityPanel
            loan={{
              principal: parseAmount(form.principal_amount),
              tanAnnual: effectiveTan,
              durationMonths: Number(form.duration_months),
              rateType: form.rate_type,
              monthlyFee: Number(form.monthly_fee) || 0,
              upfrontFee: Number(form.origination_fee) || 0,
            }}
            onDraftInputChange={handleDraftSustainabilityInputChange}
            initialDraftInput={draftSustainabilityInput}
          />
        )}

        {error && <Typography color="error" variant="body2">{error}</Typography>}
      </DialogContent>
      <DialogActions sx={{
        flexWrap: "wrap", gap: 0.5, minHeight: 44,
        px: { xs: 2, sm: 3 }, pb: "max(8px, env(safe-area-inset-bottom))",
      }}>
        <Button sx={{ minHeight: 44, flex: { xs: "1 1 42%", sm: "initial" } }} onClick={onClose}>Annulla</Button>
        {step > 0 && <Button sx={{ minHeight: 44, flex: { xs: "1 1 42%", sm: "initial" } }} onClick={handleBack}>Indietro</Button>}
        {step < STEPS.length - 1 && <Button sx={{ minHeight: 44, flex: { xs: "1 1 42%", sm: "initial" } }} variant="contained" onClick={handleNext}>Avanti</Button>}
        {step === STEPS.length - 1 && (
          mode === "simulate"
            ? <Button sx={{ minHeight: 44, flex: { xs: "1 1 42%", sm: "initial" } }} variant="contained" onClick={handleSave} disabled={saving}>
                {saving ? "Salvataggio…" : draft ? "Aggiorna bozza" : "Salva bozza"}
              </Button>
            : <Button sx={{ minHeight: 44, flex: { xs: "1 1 42%", sm: "initial" } }} variant="contained" onClick={handleSave} disabled={saving}>
                {saving ? "Salvataggio…" : mode === "import" ? "Importa" : "Crea"}
              </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
