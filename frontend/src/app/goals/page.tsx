"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Box, Card, CardContent, CardHeader, Typography, LinearProgress, Chip,
  Button, Dialog, DialogTitle, DialogContent, DialogActions, TextField,
  Select, MenuItem, FormControl, InputLabel, IconButton, Snackbar, Alert,
  CircularProgress,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import { getCsrfToken } from "@/lib/csrf";
import { formatDateIt } from "@/lib/date";

// ---------------------------------------------------------------------------
// Tipi
// ---------------------------------------------------------------------------

const GOAL_TYPE_LABELS: Record<string, string> = {
  net_savings: "Risparmio netto",
  account_balance: "Saldo di un conto",
  net_worth: "Capitale totale",
  savings_rate: "Tasso di risparmio mensile (%)",
  category_spending_reduction: "Riduzione spesa categoria",
};

interface SavingsGoal {
  id: number;
  goal_type: string;
  name: string;
  target_amount: number;
  account_id: number | null;
  category_id: number | null;
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

function getTelegramInitData(): string {
  if (typeof window === "undefined") return "";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (window as any).Telegram?.WebApp?.initData ?? "";
}

async function buildHeaders(): Promise<HeadersInit> {
  const init = getTelegramInitData();
  const csrfToken = await getCsrfToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken,
  };
  if (init) headers["X-Telegram-Init-Data"] = init;
  return headers;
}

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

const EMPTY_FORM = {
  goal_type: "net_savings",
  name: "",
  target_amount: "",
  account_id: "",
  category_id: "",
  target_date: "",
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
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [snack, setSnack] = useState<{ open: boolean; msg: string; severity: "success" | "error" }>({
    open: false, msg: "", severity: "success",
  });

  const loadGoals = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/savings-goals", { headers: await buildHeaders() });
      const data: GoalsResponse = await res.json();
      if (!res.ok || data.error) {
        setGateError({ error: data.error || "Errore nel caricamento degli obiettivi", plan_type: data.plan_type });
        setGoals([]);
      } else {
        setGateError(null);
        setGoals(data.goals || []);
      }
    } catch {
      setGateError({ error: "Errore di rete nel caricamento degli obiettivi" });
    } finally {
      setLoading(false);
    }
  }, []);

  const loadOptions = useCallback(async () => {
    try {
      const headers = await buildHeaders();
      const [accRes, catRes] = await Promise.all([
        fetch("/api/space/accounts", { headers }),
        fetch("/api/space/categories", { headers }),
      ]);
      // Gli endpoint incapsulano la lista: {"accounts": [...]} / {"categories": [...]}.
      // Assegnare l'oggetto intero lasciava i select vuoti.
      if (accRes.ok) setAccounts((await accRes.json()).accounts ?? []);
      if (catRes.ok) {
        const { categories } = await catRes.json();
        // Le archiviate non sono selezionabili per un obiettivo nuovo.
        setCategories((categories ?? []).filter((c: { archived?: boolean }) => !c.archived));
      }
    } catch {
      // opzioni non critiche: se falliscono, i select restano vuoti ma la pagina resta usabile
    }
  }, []);

  useEffect(() => {
    loadGoals();
    loadOptions();
  }, [loadGoals, loadOptions]);

  const openCreateDialog = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
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
    });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    const payload: Record<string, unknown> = {
      goal_type: form.goal_type,
      name: form.name,
      target_amount: form.target_amount,
      target_date: form.target_date || null,
    };
    if (form.goal_type === "account_balance") payload.account_id = form.account_id || null;
    if (form.goal_type === "category_spending_reduction") payload.category_id = form.category_id || null;

    try {
      const url = editingId ? `/api/savings-goals/${editingId}` : "/api/savings-goals";
      const method = editingId ? "PUT" : "POST";
      const res = await fetch(url, { method, headers: await buildHeaders(), body: JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok) {
        setSnack({ open: true, msg: data.error || "Errore nel salvataggio", severity: "error" });
        return;
      }
      setSnack({ open: true, msg: editingId ? "Obiettivo aggiornato" : "Obiettivo creato", severity: "success" });
      setDialogOpen(false);
      loadGoals();
    } catch {
      setSnack({ open: true, msg: "Errore di rete", severity: "error" });
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Eliminare questo obiettivo? L'operazione non è reversibile.")) return;
    try {
      const res = await fetch(`/api/savings-goals/${id}`, { method: "DELETE", headers: await buildHeaders() });
      if (!res.ok) {
        const data = await res.json();
        setSnack({ open: true, msg: data.error || "Errore nell'eliminazione", severity: "error" });
        return;
      }
      setSnack({ open: true, msg: "Obiettivo eliminato", severity: "success" });
      loadGoals();
    } catch {
      setSnack({ open: true, msg: "Errore di rete", severity: "error" });
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", mt: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (gateError) {
    const isStorageIssue = gateError.error?.toLowerCase().includes("postgresql");
    return (
      <Box sx={{ maxWidth: 480, mx: "auto", mt: 8, textAlign: "center" }}>
        <Typography variant="h6" fontWeight={700} mb={1}>
          🔒 Obiettivi di risparmio
        </Typography>
        <Typography color="text.secondary" mb={2}>
          {isStorageIssue
            ? "Questa funzionalità richiede la migrazione a PostgreSQL. Contatta il supporto per passare da Notion a PostgreSQL."
            : "Funzionalità riservata al piano Pro. Passa a Pro per fissare i tuoi obiettivi di risparmio e tracciarne l'avanzamento."}
        </Typography>
        <Chip label={gateError.plan_type === "pro" ? "Aggiorna storage" : "PRO"} color="warning" />
      </Box>
    );
  }

  return (
    <Box sx={{ maxWidth: 720, mx: "auto", p: 2 }}>
      <Box data-tour="goals-header" sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
        <Typography variant="h5" fontWeight={700}>🎯 Obiettivi di risparmio</Typography>
        <Button variant="contained" onClick={openCreateDialog}>Nuovo obiettivo</Button>
      </Box>

      {goals.length === 0 && (
        <Typography color="text.secondary">
          Non hai ancora nessun obiettivo attivo. Creane uno per iniziare a tracciare i tuoi progressi.
        </Typography>
      )}

      {goals.map((g) => (
        <Card key={g.id} sx={{ mb: 2, borderRadius: 2 }}>
          <CardHeader
            title={g.name}
            subheader={GOAL_TYPE_LABELS[g.goal_type] || g.goal_type}
            action={
              <>
                <IconButton size="small" onClick={() => openEditDialog(g)}><EditIcon fontSize="small" /></IconButton>
                <IconButton size="small" onClick={() => handleDelete(g.id)}><DeleteIcon fontSize="small" /></IconButton>
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
        <DialogTitle>{editingId ? "Modifica obiettivo" : "Nuovo obiettivo"}</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, mt: 1 }}>
          <FormControl fullWidth disabled={!!editingId}>
            <InputLabel>Tipo di obiettivo</InputLabel>
            <Select
              value={form.goal_type}
              label="Tipo di obiettivo"
              onChange={(e) => setForm({ ...form, goal_type: e.target.value })}
            >
              {Object.entries(GOAL_TYPE_LABELS).map(([value, label]) => (
                <MenuItem key={value} value={value}>{label}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            label="Nome obiettivo"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            fullWidth
          />

          <TextField
            label={form.goal_type === "savings_rate" ? "Obiettivo (%)" : "Importo target (€)"}
            type="number"
            value={form.target_amount}
            onChange={(e) => setForm({ ...form, target_amount: e.target.value })}
            fullWidth
          />

          {form.goal_type === "account_balance" && (
            <FormControl fullWidth>
              <InputLabel>Conto</InputLabel>
              <Select
                value={form.account_id}
                label="Conto"
                onChange={(e) => setForm({ ...form, account_id: e.target.value })}
              >
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
            <TextField
              label="Scadenza (opzionale)"
              type="date"
              value={form.target_date}
              onChange={(e) => setForm({ ...form, target_date: e.target.value })}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Annulla</Button>
          <Button variant="contained" onClick={handleSave}>Salva</Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snack.open}
        autoHideDuration={4000}
        onClose={() => setSnack({ ...snack, open: false })}
      >
        <Alert severity={snack.severity} onClose={() => setSnack({ ...snack, open: false })}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
}
