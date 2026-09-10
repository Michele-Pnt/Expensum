"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Box, Card, CardContent, CardHeader, Typography, LinearProgress, Chip,
  Button, Dialog, DialogTitle, DialogContent, DialogActions, TextField,
  Select, MenuItem, FormControl, InputLabel, IconButton,
  ToggleButton, ToggleButtonGroup, Collapse,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import { Lock, PiggyBank, Landmark, Wallet, Percent, TrendingDown, ChevronLeft, ChevronDown, Shield } from "lucide-react";
import { formatDateIt } from "@/lib/date";
import SwipeDateField from "@/components/SwipeDateField";
import { apiFetch, apiErrorMessage, ApiError } from "@/lib/api";
import { useSnackbar } from "@/components/feedback/useSnackbar";
import AppSnackbar from "@/components/feedback/AppSnackbar";
import PageLoader from "@/components/feedback/PageLoader";

// ---------------------------------------------------------------------------
// Tipi
// ---------------------------------------------------------------------------

const GOAL_TYPE_LABELS: Record<string, string> = {
  net_savings: "Risparmio netto",
  account_balance: "Saldo di un conto",
  net_worth: "Capitale totale",
  savings_rate: "Tasso di risparmio mensile (%)",
  category_spending_reduction: "Riduzione spesa categoria",
  emergency_fund: "Fondo emergenza",
};

// Spiegano cosa misura ciascun tipo, non solo come si chiama: mostrate nella
// selezione guidata del nuovo obiettivo, così l'utente sceglie sapendo a cosa va
// incontro invece di indovinare dal nome nel dropdown.
const GOAL_TYPE_DESCRIPTIONS: Record<string, string> = {
  net_savings: "Somma di entrate meno uscite da quando crei l'obiettivo: adatto per un obiettivo di risparmio generico, come una vacanza o un acquisto.",
  account_balance: "Segue il saldo di un conto specifico: scegli questo se il tuo obiettivo è far crescere (o mantenere) i soldi su un conto preciso.",
  net_worth: "Somma i saldi di tutti i tuoi conti collegati: usalo per un obiettivo di patrimonio complessivo, non legato a un conto in particolare.",
  savings_rate: "Percentuale del reddito che risparmi ogni mese: si ricalcola ogni mese, non è un importo che si accumula.",
  category_spending_reduction: "Tieni la spesa mensile di una categoria sotto una soglia: usalo per obiettivi di contenimento spesa, non di risparmio.",
  emergency_fund: "Target calcolato automaticamente: mediana delle tue spese mensili (ultimi 6 mesi) moltiplicata per i mesi di copertura che scegli, ricalcolato ogni mese in base alle tue spese reali.",
};

const GOAL_TYPE_ICONS: Record<string, typeof PiggyBank> = {
  net_savings: PiggyBank,
  account_balance: Landmark,
  net_worth: Wallet,
  savings_rate: Percent,
  category_spending_reduction: TrendingDown,
  emergency_fund: Shield,
};

interface SavingsGoal {
  id: number;
  goal_type: string;
  name: string;
  target_amount: number;
  account_id: number | null;
  category_id: number | null;
  emergency_fund_months: number | null;
  target_date: string | null;
  status: string;
  progress: number;
  current_value: number | null;
  eta_date: string | null;
  score_label: string;
  explanation: string;
}

interface GoalsResponse {
  goals: SavingsGoal[];
  error?: string;
  plan_type?: string;
}

interface SimpleOption { id: number; name: string }

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

function scoreColor(label: string): "success" | "info" | "warning" | "error" | "default" {
  if (label === "In anticipo" || label === "Ottimo mese" || label === "Obiettivo centrato") return "success";
  if (label === "In linea" || label === "Vicino all'obiettivo") return "info";
  if (label === "In ritardo" || label === "Sotto obiettivo") return "warning";
  if (label === "A rischio") return "error";
  return "default";
}

// Stessa tinta usata per la card "Budget disponibile" in Analytics
// (AnalyticsToday.tsx, budgetToneSx): bordo colorato + sfondo leggero, non solo
// il Chip, così lo stato dell'obiettivo si vede a colpo d'occhio anche scrollando veloce.
const GOAL_TONE_SX: Partial<Record<ReturnType<typeof scoreColor>, { borderColor: string; background: string }>> = {
  success: { borderColor: "success.main", background: "rgba(22, 163, 74, 0.12)" },
  info: { borderColor: "info.main", background: "rgba(95, 196, 203, 0.12)" },
  warning: { borderColor: "warning.main", background: "rgba(240, 169, 62, 0.14)" },
  error: { borderColor: "error.main", background: "rgba(220, 38, 38, 0.12)" },
};

const EMPTY_FORM = {
  goal_type: "net_savings",
  name: "",
  target_amount: "",
  account_id: "",
  category_id: "",
  target_date: "",
  emergency_fund_months: "6",
};

// ---------------------------------------------------------------------------
// Pagina
// ---------------------------------------------------------------------------

export default function GoalsPage() {
  const [goals, setGoals] = useState<SavingsGoal[]>([]);
  const [accounts, setAccounts] = useState<SimpleOption[]>([]);
  const [categories, setCategories] = useState<SimpleOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [gateError, setGateError] = useState<{ error: string; plan_type?: string } | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  // Step 0 = scelta del tipo (solo in creazione), step 1 = dettagli. In modifica
  // il tipo è bloccato (non lo si può cambiare) quindi si apre già allo step 1.
  const [step, setStep] = useState<0 | 1>(0);
  // Tipo con la descrizione aperta nello step 0 (compatto finché non lo tocchi).
  const [expandedType, setExpandedType] = useState<string | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const { snack, showSuccess, showError, close: closeSnack } = useSnackbar();

  const loadGoals = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<GoalsResponse>("/api/savings-goals");
      setGateError(null);
      setGoals(data.goals || []);
    } catch (e) {
      if (e instanceof ApiError) {
        const body = e.body && typeof e.body === "object" ? (e.body as GoalsResponse) : null;
        setGateError({ error: body?.error || "Errore nel caricamento degli obiettivi", plan_type: body?.plan_type });
      } else {
        setGateError({ error: "Errore di rete nel caricamento degli obiettivi" });
      }
      setGoals([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadOptions = useCallback(async () => {
    // Gli endpoint incapsulano la lista: {"accounts": [...]} / {"categories": [...]}.
    // Ogni chiamata è indipendente: se una fallisce, l'altra resta comunque applicata
    // e la pagina resta usabile (i select non critici restano solo vuoti).
    try {
      const { accounts } = await apiFetch<{ accounts: SimpleOption[] }>("/api/space/accounts");
      setAccounts(accounts ?? []);
    } catch {
      // opzione non critica
    }
    try {
      const { categories } = await apiFetch<{ categories: (SimpleOption & { archived?: boolean })[] }>("/api/space/categories");
      // Le archiviate non sono selezionabili per un obiettivo nuovo.
      setCategories((categories ?? []).filter((c) => !c.archived));
    } catch {
      // opzione non critica
    }
  }, []);

  useEffect(() => {
    loadGoals();
    loadOptions();
  }, [loadGoals, loadOptions]);

  const openCreateDialog = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
    setStep(0);
    setExpandedType(null);
    setDialogOpen(true);
  };

  const openEditDialog = (g: SavingsGoal) => {
    setEditingId(g.id);
    setForm({
      goal_type: g.goal_type,
      name: g.name,
      target_amount: String(g.target_amount),
      account_id: g.account_id ? String(g.account_id) : "",
      category_id: g.category_id ? String(g.category_id) : "",
      target_date: g.target_date || "",
      emergency_fund_months: g.emergency_fund_months ? String(g.emergency_fund_months) : "6",
    });
    setStep(1);
    setDialogOpen(true);
  };

  const handleSave = async () => {
    const payload: Record<string, unknown> = {
      goal_type: form.goal_type,
      name: form.name,
      target_date: form.target_date || null,
    };
    // Il target di "Fondo emergenza" è sempre calcolato server-side dalla
    // mediana di spesa: non va mai inviato un valore inserito dall'utente,
    // altrimenti si rischia di congelare un numero stantio in modifica.
    if (form.goal_type !== "emergency_fund") payload.target_amount = form.target_amount;
    if (form.goal_type === "account_balance") payload.account_id = form.account_id || null;
    if (form.goal_type === "category_spending_reduction") payload.category_id = form.category_id || null;
    if (form.goal_type === "emergency_fund") {
      payload.account_id = form.account_id || null;
      payload.emergency_fund_months = Number(form.emergency_fund_months);
    }

    try {
      const url = editingId ? `/api/savings-goals/${editingId}` : "/api/savings-goals";
      const method = editingId ? "PUT" : "POST";
      await apiFetch(url, { method, body: payload });
      showSuccess(editingId ? "Obiettivo aggiornato" : "Obiettivo creato");
      setDialogOpen(false);
      loadGoals();
    } catch (e) {
      showError(apiErrorMessage(e, "Errore nel salvataggio"));
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Eliminare questo obiettivo? L'operazione non è reversibile.")) return;
    try {
      await apiFetch(`/api/savings-goals/${id}`, { method: "DELETE" });
      showSuccess("Obiettivo eliminato");
      loadGoals();
    } catch (e) {
      showError(apiErrorMessage(e, "Errore nell'eliminazione"));
    }
  };

  if (loading) {
    return <PageLoader />;
  }

  if (gateError) {
    const isStorageIssue = gateError.error?.toLowerCase().includes("postgresql");
    return (
      <Box sx={{ maxWidth: 480, mx: "auto", mt: 8, textAlign: "center" }}>
        <Typography
          variant="h6"
          mb={1}
          sx={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 1 }}
        >
          <Lock size={18} strokeWidth={1.75} aria-hidden="true" />
          Obiettivi di risparmio
        </Typography>
        <Typography color="text.secondary" mb={2}>
          {isStorageIssue
            ? "Questa funzionalità richiede il DB interno. Contatta il supporto per passare da Notion al DB interno."
            : "Funzionalità riservata al piano Pro. Passa a Pro per fissare i tuoi obiettivi di risparmio e tracciarne l'avanzamento."}
        </Typography>
        <Chip label={gateError.plan_type === "pro" ? "Aggiorna storage" : "PRO"} color="warning" />
      </Box>
    );
  }

  return (
    <Box sx={{ maxWidth: 720, mx: "auto", p: 2 }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
        <Typography
          component="h1"
          variant="h5"
          sx={{ fontWeight: 300, letterSpacing: "0.015em", display: "flex", alignItems: "center", gap: 1 }}
        >
          Obiettivi di risparmio
        </Typography>
        <Button variant="contained" onClick={openCreateDialog}>Nuovo obiettivo</Button>
      </Box>

      {goals.length === 0 && (
        <Typography color="text.secondary">
          Non hai ancora nessun obiettivo attivo. Creane uno per iniziare a tracciare i tuoi progressi.
        </Typography>
      )}

      {goals.map((g) => (
        <Card key={g.id} sx={{ mb: 2, borderRadius: 2, ...GOAL_TONE_SX[scoreColor(g.score_label)] }}>
          <CardHeader
            title={g.name}
            subheader={GOAL_TYPE_LABELS[g.goal_type] || g.goal_type}
            action={
              <>
                <IconButton aria-label={`Modifica obiettivo ${g.name}`} onClick={() => openEditDialog(g)} sx={{ width: 44, height: 44 }}><EditIcon fontSize="small" /></IconButton>
                <IconButton aria-label={`Elimina obiettivo ${g.name}`} onClick={() => handleDelete(g.id)} sx={{ width: 44, height: 44 }}><DeleteIcon fontSize="small" /></IconButton>
              </>
            }
          />
          <CardContent sx={{ pt: 0 }}>
            <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
              <Typography variant="body2">
                {fmtCurrency(g.current_value)} {g.goal_type !== "savings_rate" && `/ ${fmtCurrency(g.target_amount)}`}
                {g.goal_type === "savings_rate" && ` / ${g.target_amount}%`}
              </Typography>
              <Chip label={g.score_label} color={scoreColor(g.score_label)} size="small" />
            </Box>
            <LinearProgress
              variant="determinate"
              value={Math.min(g.progress, 100)}
              sx={{ height: 8, borderRadius: 4, mb: 1 }}
            />
            <Typography variant="body2" color="text.secondary">{g.explanation}</Typography>
            {g.eta_date && (
              <Typography variant="caption" color="text.secondary">
                Stima raggiungimento: {formatDateIt(g.eta_date)}
              </Typography>
            )}
          </CardContent>
        </Card>
      ))}

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>
          {editingId ? "Modifica obiettivo" : step === 0 ? "Che obiettivo vuoi creare?" : "Nuovo obiettivo"}
        </DialogTitle>

        {step === 0 ? (
          <DialogContent sx={{ display: "grid", gap: 1, mt: 1 }}>
            {Object.entries(GOAL_TYPE_LABELS).map(([value, label]) => {
              const Icon = GOAL_TYPE_ICONS[value];
              const isOpen = expandedType === value;
              return (
                <Box key={value} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, overflow: "hidden" }}>
                  <Box
                    component="button"
                    type="button"
                    onClick={() => setExpandedType(isOpen ? null : value)}
                    aria-expanded={isOpen}
                    sx={{
                      display: "flex", alignItems: "center", gap: 1.5, width: "100%",
                      minHeight: 44, px: 1.5, py: 1, border: "none",
                      bgcolor: "transparent", color: "text.primary", textAlign: "left",
                      cursor: "pointer", font: "inherit", "&:hover": { bgcolor: "action.hover" },
                    }}
                  >
                    <Icon size={20} strokeWidth={1.75} aria-hidden="true" style={{ flexShrink: 0 }} />
                    <Typography fontWeight={600} sx={{ flex: 1, minWidth: 0 }}>{label}</Typography>
                    <ChevronDown size={18} aria-hidden="true" style={{ flexShrink: 0, transform: isOpen ? "rotate(180deg)" : "none", transition: "transform 150ms ease" }} />
                  </Box>
                  <Collapse in={isOpen} timeout="auto">
                    <Box sx={{ px: 1.5, pb: 1.5 }}>
                      <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere", mb: 1.5 }}>
                        {GOAL_TYPE_DESCRIPTIONS[value]}
                      </Typography>
                      <Button
                        variant="contained" fullWidth
                        onClick={() => { setForm({ ...form, goal_type: value }); setStep(1); }}
                        sx={{ minHeight: 44 }}
                      >
                        Continua
                      </Button>
                    </Box>
                  </Collapse>
                </Box>
              );
            })}
          </DialogContent>
        ) : (
          <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, mt: 1 }}>
            <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1.5, p: 1.5, borderRadius: 2, bgcolor: "action.hover" }}>
              {(() => { const Icon = GOAL_TYPE_ICONS[form.goal_type]; return <Icon size={20} strokeWidth={1.75} aria-hidden="true" style={{ flexShrink: 0, marginTop: 2 }} />; })()}
              <Box sx={{ minWidth: 0 }}>
                <Typography fontWeight={600}>{GOAL_TYPE_LABELS[form.goal_type]}</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                  {GOAL_TYPE_DESCRIPTIONS[form.goal_type]}
                </Typography>
              </Box>
            </Box>

            <Box>
              <TextField
                label="Nome obiettivo"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                fullWidth
              />
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5, ml: 1.75 }}>
                Il nome è solo per te (es. &quot;Vacanze estive&quot;): è il tipo scelto sopra a determinare come misuriamo l&apos;avanzamento.
              </Typography>
            </Box>

            {form.goal_type === "emergency_fund" ? (
              <Box>
                <Typography variant="body2" sx={{ mb: 1 }}>Quanti mesi vuoi coprire?</Typography>
                <ToggleButtonGroup
                  exclusive fullWidth value={form.emergency_fund_months}
                  onChange={(_, value) => { if (value) setForm({ ...form, emergency_fund_months: value }); }}
                >
                  <ToggleButton value="3" sx={{ minHeight: 44 }}>3 mesi</ToggleButton>
                  <ToggleButton value="6" sx={{ minHeight: 44 }}>6 mesi</ToggleButton>
                  <ToggleButton value="12" sx={{ minHeight: 44 }}>12 mesi</ToggleButton>
                </ToggleButtonGroup>
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                  L&apos;importo target non lo imposti tu: si calcola dalla mediana delle tue spese mensili e si aggiorna da solo ogni mese.
                </Typography>
              </Box>
            ) : (
              <TextField
                label={form.goal_type === "savings_rate" ? "Obiettivo (%)" : "Importo target (€)"}
                type="number"
                value={form.target_amount}
                onChange={(e) => setForm({ ...form, target_amount: e.target.value })}
                fullWidth
              />
            )}

            {(form.goal_type === "account_balance" || form.goal_type === "emergency_fund") && (
              <FormControl fullWidth>
                <InputLabel>{form.goal_type === "emergency_fund" ? "Conto da monitorare (opzionale)" : "Conto"}</InputLabel>
                <Select
                  value={form.account_id}
                  label={form.goal_type === "emergency_fund" ? "Conto da monitorare (opzionale)" : "Conto"}
                  onChange={(e) => setForm({ ...form, account_id: e.target.value })}
                >
                  {form.goal_type === "emergency_fund" && <MenuItem value=""><em>Tutti i conti</em></MenuItem>}
                  {accounts.map((a) => <MenuItem key={a.id} value={String(a.id)}>{a.name}</MenuItem>)}
                </Select>
              </FormControl>
            )}

            {form.goal_type === "category_spending_reduction" && (
              <FormControl fullWidth>
                <InputLabel>Categoria</InputLabel>
                <Select
                  value={form.category_id}
                  label="Categoria"
                  onChange={(e) => setForm({ ...form, category_id: e.target.value })}
                >
                  {categories.map((c) => <MenuItem key={c.id} value={String(c.id)}>{c.name}</MenuItem>)}
                </Select>
              </FormControl>
            )}

            {form.goal_type !== "savings_rate" && (
              <SwipeDateField
                label="Scadenza (opzionale)"
                value={form.target_date}
                onChange={(iso) => setForm({ ...form, target_date: iso })}
                fullWidth
                infoExplanation="Entro quando pensi di raggiungere l'importo target: la usiamo solo per calcolare il ritmo di risparmio necessario e il voto mensile, non blocca nulla se la sposti."
              />
            )}
          </DialogContent>
        )}

        <DialogActions>
          {step === 1 && !editingId && (
            <Button onClick={() => setStep(0)} startIcon={<ChevronLeft size={16} />} sx={{ mr: "auto" }}>
              Indietro
            </Button>
          )}
          <Button onClick={() => setDialogOpen(false)}>Annulla</Button>
          {step === 1 && <Button variant="contained" onClick={handleSave}>Salva</Button>}
        </DialogActions>
      </Dialog>

      <AppSnackbar snack={snack} onClose={closeSnack} />
    </Box>
  );
}
