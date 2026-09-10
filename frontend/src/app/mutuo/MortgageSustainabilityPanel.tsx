"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Box, Card, CardContent, Chip, FormControlLabel, Switch,
  TextField, Typography, Slider,
} from "@mui/material";
import InfoButton from "@/components/InfoButton";
import { apiFetch, apiErrorMessage } from "@/lib/api";

type Category = { id: number; name: string; monthly_budget: number | null };
type Result = {
  installment: number;
  taeg: number;
  total_monthly_payment: number;
  monthly_margin_before_savings: number;
  monthly_savings_after_mortgage: number;
  confidence: "high" | "limited" | "low";
  status: "sostenibile" | "da_valutare" | "a_rischio";
  explanations: string[];
  prefill?: {
    monthly_income?: number;
    essential_monthly_expenses?: number;
    monthly_savings_target?: number;
    history_months?: number;
    source?: string;
    active_goals?: { id: number; name: string; monthly_commitment: number; extension_months?: number }[];
    goal_strategy?: string;
  };
  stress_scenarios: { rate_increase: number; total_monthly_payment: number; monthly_margin_after_savings: number }[];
  budget_reallocation: { required_reduction: number; uncovered_reduction: number; items: { category_id: number; name: string; historical_monthly_spend: number; reduction: number; proposed_budget: number }[] };
};

export type MortgageSustainabilityLoan = {
  principal: number;
  tanAnnual: number;
  durationMonths: number;
  rateType: "fisso" | "variabile";
  monthlyFee?: number;
  upfrontFee?: number;
};

export type MortgageSustainabilityDraftInput = {
  monthly_income?: string;
  essential_monthly_expenses?: string;
  monthly_savings_target?: string;
  preserve_savings: boolean;
  selected_category_ids: number[];
  goal_strategy?: "maintain" | "extend" | "abandon";
};

function formatCurrency(value: number): string {
  return value.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

export default function MortgageSustainabilityPanel({
  loan,
  onDraftInputChange,
  initialDraftInput,
}: {
  loan: MortgageSustainabilityLoan;
  onDraftInputChange?: (input: MortgageSustainabilityDraftInput) => void;
  initialDraftInput?: MortgageSustainabilityDraftInput;
}) {
  const [income, setIncome] = useState("");
  const [essential, setEssential] = useState("");
  const [saving, setSaving] = useState("");
  const [preserveSavings, setPreserveSavings] = useState(true);
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [totalExpenseReduction, setTotalExpenseReduction] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeGoals, setActiveGoals] = useState<{ id: number; name: string; monthly_commitment: number; extension_months?: number }[]>([]);
  const [lastAppliedDraftSignature, setLastAppliedDraftSignature] = useState<string | null>(null);
  const prefillAppliedRef = useRef(false);
  const lastNotifiedDraftSignatureRef = useRef<string | null>(null);

  const initialDraftSignature = useMemo(() => JSON.stringify({
    monthly_income: initialDraftInput?.monthly_income ?? "",
    essential_monthly_expenses: initialDraftInput?.essential_monthly_expenses ?? "",
    monthly_savings_target: initialDraftInput?.monthly_savings_target ?? "",
    preserve_savings: initialDraftInput?.preserve_savings ?? true,
    selected_category_ids: initialDraftInput?.selected_category_ids ?? [],
  }), [
    initialDraftInput?.essential_monthly_expenses,
    initialDraftInput?.monthly_income,
    initialDraftInput?.monthly_savings_target,
    initialDraftInput?.preserve_savings,
    initialDraftInput?.selected_category_ids,
  ]);

  // Adegua lo stato del form al prop `initialDraftInput` durante il render (pattern
  // React consigliato per derivare stato da un prop) invece che in un useEffect: evita
  // il giro extra di render/commit e il set-state-in-effect segnalato dal linter.
  if (initialDraftInput && lastAppliedDraftSignature !== initialDraftSignature) {
    const hasDraftValues = initialDraftInput.monthly_income != null
      || initialDraftInput.essential_monthly_expenses != null
      || initialDraftInput.monthly_savings_target != null
      || initialDraftInput.preserve_savings !== true
      || initialDraftInput.selected_category_ids.length > 0
      ;
    if (hasDraftValues) {
      setLastAppliedDraftSignature(initialDraftSignature);
      setIncome(initialDraftInput.monthly_income ?? "");
      setEssential(initialDraftInput.essential_monthly_expenses ?? "");
      setSaving(initialDraftInput.monthly_savings_target ?? "");
      setPreserveSavings(initialDraftInput.preserve_savings);
      setSelectedIds(initialDraftInput.selected_category_ids);
    }
  }

  useEffect(() => {
    if (lastAppliedDraftSignature !== null) {
      prefillAppliedRef.current = true;
    }
  }, [lastAppliedDraftSignature]);

  useEffect(() => {
    apiFetch<{ categories: Category[] }>("/api/space/categories")
      .then((data) => setCategories(data?.categories ?? []))
      .catch(() => setCategories([]));
  }, []);

  const payload = useMemo(() => ({
    principal: loan.principal,
    tan_annual: loan.tanAnnual,
    duration_months: loan.durationMonths,
    rate_type: loan.rateType,
    monthly_fee: loan.monthlyFee ?? 0,
    upfront_fee: loan.upfrontFee ?? 0,
    monthly_income: income || undefined,
    essential_monthly_expenses: essential || undefined,
    monthly_savings_target: saving || undefined,
    preserve_savings: preserveSavings,
    selected_category_ids: selectedIds,
    expense_reduction_target: totalExpenseReduction,
  }), [essential, income, loan, preserveSavings, saving, selectedIds, totalExpenseReduction]);

  useEffect(() => {
    const input = {
      monthly_income: income || undefined,
      essential_monthly_expenses: essential || undefined,
      monthly_savings_target: saving || undefined,
      preserve_savings: preserveSavings,
      selected_category_ids: selectedIds,
    };
    const signature = JSON.stringify(input);
    if (lastNotifiedDraftSignatureRef.current === signature) return;
    lastNotifiedDraftSignatureRef.current = signature;
    onDraftInputChange?.(input);
  }, [essential, income, onDraftInputChange, preserveSavings, saving, selectedIds]);

  useEffect(() => {
    if (loan.principal <= 0 || loan.durationMonths <= 0 || loan.tanAnnual < 0) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      try {
        const data = await apiFetch<{
          result: Result;
          prefill?: Result["prefill"];
        }>("/api/mortgage-simulations/evaluate", { method: "POST", body: payload, signal: controller.signal });
        const prefill = data.prefill as Result["prefill"] | undefined;
        if (prefill?.active_goals) {
          setActiveGoals(prefill.active_goals);
        }
        if (!prefillAppliedRef.current) {
          prefillAppliedRef.current = true;
          if (prefill) {
            if (prefill.monthly_income != null) setIncome((prev) => prev === "" ? String(prefill.monthly_income) : prev);
            if (prefill.essential_monthly_expenses != null) setEssential((prev) => prev === "" ? String(prefill.essential_monthly_expenses) : prev);
            if (prefill.monthly_savings_target != null) setSaving((prev) => prev === "" ? String(prefill.monthly_savings_target) : prev);
          }
        }
        setResult(data.result); setError(null);
      } catch (cause) {
        if ((cause as Error).name !== "AbortError") {
          setError(apiErrorMessage(cause, "Impossibile calcolare la sostenibilità"));
        }
      }
    }, 300);
    return () => { controller.abort(); window.clearTimeout(timeout); };
  }, [loan, payload]);

  const severity = result?.status === "sostenibile" ? "success" : result?.status === "a_rischio" ? "error" : "warning";
  const scenarioTitle = loan.rateType === "fisso"
    ? "Confronto tra preventivi"
    : "Stress test di possibili revisioni del tasso";
  return (
    <Card variant="outlined" sx={{ borderRadius: 3, mt: 1, flexShrink: 0, minWidth: 0 }}>
      <CardContent sx={{ display: "flex", flexDirection: "column", gap: 1.25, minWidth: 0, p: { xs: 1.5, sm: 2 } }}>
        <Box><Typography variant="h6">Sostenibilità del mutuo</Typography><Typography variant="body2" color="text.secondary">Analisi locale e spiegabile: non è una delibera bancaria.</Typography></Box>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(3, 1fr)" }, gap: 1 }}>
          <TextField sx={{ minWidth: 0, "& .MuiInputBase-root": { minHeight: 44 } }} label="Reddito netto mensile" type="number" value={income} onChange={(e) => setIncome(e.target.value)} InputProps={{ endAdornment: <InfoButton label="Spiega reddito precompilato" explanation="Campo precompilato con la mediana mensile delle entrate di tipo Stipendio presenti su Expensum; puoi modificarlo." /> }} />
          <TextField sx={{ minWidth: 0, "& .MuiInputBase-root": { minHeight: 44 } }} label="Spesa mensile osservata" type="number" value={essential} onChange={(e) => setEssential(e.target.value)} InputProps={{ endAdornment: <InfoButton label="Spiega spesa precompilata" explanation="Campo precompilato con la mediana mensile di tutte le uscite presenti su Expensum, senza distinguere tra essenziali e non essenziali; puoi modificarlo." /> }} />
          <TextField
            sx={{ minWidth: 0, "& .MuiInputBase-root": { minHeight: 44 } }}
            label="Risparmio mensile"
            type="number"
            value={saving}
            onChange={(e) => setSaving(e.target.value)}
            InputProps={{
              endAdornment: <InfoButton label="Spiega risparmio precompilato" explanation="È la somma che oggi riesci mediamente a mettere da parte ogni mese: entrate da stipendio meno uscite totali. Puoi cambiarla." />,
            }}
          />
        </Box>
        <FormControlLabel sx={{ m: 0, minHeight: 44, alignItems: "center" }} control={<Switch checked={preserveSavings} onChange={(e) => setPreserveSavings(e.target.checked)} />} label={<Box sx={{ display: "flex", alignItems: "center" }}>Voglio mantenere il risparmio<InfoButton label="Spiega mantenimento del risparmio" explanation="Se attivo, la valutazione verifica se la rata permette di continuare ad accantonare il risparmio scelto." /></Box>} />
        {preserveSavings && <Box sx={{ minWidth: 0 }}><Typography variant="body2" gutterBottom sx={{ display: "flex", alignItems: "center" }}>Scegli dove spendere meno, se serve<InfoButton label="Spiega categorie riducibili" explanation="Seleziona le categorie su cui vuoi valutare una riduzione. La proposta è indicativa e richiede la tua conferma." /></Typography><Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75 }}>{categories.map((category) => { const selected = selectedIds.includes(category.id); return <Chip key={category.id} label={category.name} clickable color={selected ? "primary" : "default"} variant={selected ? "filled" : "outlined"} onClick={() => setSelectedIds((ids) => ids.includes(category.id) ? ids.filter((id) => id !== category.id) : [...ids, category.id])} sx={{ m: 0, minHeight: 44, maxWidth: "100%", ...(selected ? { boxShadow: "0 0 0 2px rgba(91, 199, 210, 0.8)", fontWeight: 600 } : {}), "& .MuiChip-label": { whiteSpace: "normal", overflowWrap: "anywhere" } }} />; })}</Box></Box>}
        {preserveSavings && selectedIds.length > 0 && result && <Box sx={{ minWidth: 0, overflowWrap: "anywhere" }}><Typography variant="body2">Quanto vuoi ridurre le spese totali?</Typography><Slider aria-label="Riduzione totale delle spese" value={totalExpenseReduction} min={0} max={Math.max(result.budget_reallocation.items.reduce((sum, item) => sum + item.historical_monthly_spend, 0), 1)} step={1} onChange={(_, value) => setTotalExpenseReduction(Array.isArray(value) ? value[0] : value)} valueLabelDisplay="auto" valueLabelFormat={(value) => formatCurrency(value)} /><Typography variant="caption" display="block">Il taglio viene distribuito automaticamente in base alla spesa media di ogni categoria selezionata.</Typography>{result.budget_reallocation.items.map((item) => <Typography key={item.category_id} variant="caption" display="block">{item.name}: media {formatCurrency(item.historical_monthly_spend)} · riduzione {formatCurrency(item.reduction)} · nuova spesa {formatCurrency(item.proposed_budget)}</Typography>)}</Box>}
        {activeGoals.length > 0 && <Typography variant="caption" color="text.secondary">Gli obiettivi attivi verranno rivalutati automaticamente in base al margine dopo il mutuo.</Typography>}
        {error && <Alert severity="error">{error}</Alert>}
        {result && <>
          <Alert severity={severity} icon={false} sx={{ display: "flex", alignItems: "center" }}><strong>{result.status.replaceAll("_", " ")}</strong> · Affidabilità {result.confidence === "high" ? "alta" : result.confidence === "limited" ? "limitata" : "bassa"}<InfoButton label="Spiega stato e affidabilità" explanation="Lo stato dice se, dopo rata e spese, ti rimane abbastanza denaro. L'affidabilità indica quanto è completo lo storico usato per la stima." /></Alert>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(3, minmax(0, 1fr))" }, gap: 2, minWidth: 0 }}>
            <Typography sx={{ minWidth: 0, overflowWrap: "anywhere", display: "flex", alignItems: "center" }}><span><strong>Rata totale</strong><br />{formatCurrency(result.total_monthly_payment)}</span><InfoButton label="Spiega rata totale" explanation="È la rata mensile stimata del mutuo, comprensiva della quota capitale, degli interessi e dell'eventuale costo mensile indicato." /></Typography>
            <Typography sx={{ minWidth: 0, overflowWrap: "anywhere", display: "flex", alignItems: "center" }}><span><strong>Margine dopo il mutuo</strong><br />{formatCurrency(result.monthly_savings_after_mortgage)}</span><InfoButton label="Spiega margine dopo il mutuo" explanation="È il denaro che resta ogni mese dopo entrate, spese, rata, costi ricorrenti del mutuo e, se scelto, il risparmio da mantenere." /></Typography>
          </Box>
          {result.stress_scenarios.length > 0 && <Box>
            <Typography variant="body2" color="text.secondary" gutterBottom sx={{ display: "flex", alignItems: "center" }}><strong>{scenarioTitle}</strong><InfoButton label={`Spiega ${scenarioTitle}`} explanation={loan.rateType === "fisso" ? "Confronta preventivi ipotetici con una rata diversa; il tasso fisso del contratto non cambia." : "Mostra come cambierebbero rata e margine se il tasso aumentasse rispetto a quello attuale."} /></Typography>
            {result.stress_scenarios.map((scenario) => {
              const sustainable = scenario.monthly_margin_after_savings >= 0;
              return <Typography key={scenario.rate_increase} variant="body2" color="text.secondary" sx={{ minWidth: 0, overflowWrap: "anywhere" }}>
                +{scenario.rate_increase}% · {formatCurrency(scenario.total_monthly_payment)} · Margine: {formatCurrency(scenario.monthly_margin_after_savings)} · {sustainable ? "sostenibile" : "a rischio"}
              </Typography>;
            })}
          </Box>}
          {result.explanations.map((item) => <Typography key={item} variant="body2" color="text.secondary">{item}</Typography>)}
        </>}
      </CardContent>
    </Card>
  );
}
