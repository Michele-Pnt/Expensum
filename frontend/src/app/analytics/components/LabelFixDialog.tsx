"use client";

import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Radio,
  RadioGroup,
  Typography,
} from "@mui/material";
import { ChevronDown } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getCsrfToken } from "@/lib/csrf";
import { formatDateIt } from "@/lib/date";
import type { ExpenseLabelCluster, LabelVariant } from "../types";
import { buildMergeCandidates } from "../viewModels";

const euro = (value: number) => value.toLocaleString("it-IT", { style: "currency", currency: "EUR" });

export type LabelFixMode = "merge" | "split";

export type LabelFixTarget = {
  id: number;
  anchorText: string;
  categoryId: number | null;
};

type LabelFixDialogProps = {
  open: boolean;
  mode: LabelFixMode;
  target: LabelFixTarget | null;
  months: number;
  initData?: string;
  onClose: () => void;
  onDone: (message: string) => void;
};

/** Headers coerenti con il resto dell'area autenticata (mini-app o browser). */
async function mutationHeaders(initData?: string): Promise<HeadersInit> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (initData) headers["X-Telegram-Init-Data"] = initData;
  try {
    headers["X-CSRFToken"] = await getCsrfToken();
  } catch {
    // Nella WebView Telegram il token non serve: l'header initData basta al server.
  }
  return headers;
}

function readHeaders(initData?: string): HeadersInit {
  return initData ? { "X-Telegram-Init-Data": initData } : {};
}

/**
 * Percorso guidato per correggere il raggruppamento automatico delle voci di spesa.
 *
 * Due modalità, entrambe in 2-3 tap e senza mai far scrivere un nome a mano:
 * - "merge": scegli i gruppi da unire, poi quale etichetta tenere;
 * - "split": scegli le varianti testuali che non c'entrano e separale.
 *
 * L'unità del "dividi" è la variante testuale, non la singola spesa: spese scritte
 * allo stesso modo restano sempre insieme, e la correzione vale anche per quelle
 * future (il server registra una regola, non una riassegnazione una tantum).
 */
export default function LabelFixDialog({ open, mode, target, months, initData, onClose, onDone }: LabelFixDialogProps) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<ExpenseLabelCluster[]>([]);
  const [variants, setVariants] = useState<LabelVariant[]>([]);
  // Selezione del merge: per ogni gruppo, quali voci spostare. Un gruppo assente non
  // è selezionato; con tutte le voci selezionate viene assorbito per intero.
  const [picked, setPicked] = useState<Record<number, string[]>>({});
  const [selectedVariants, setSelectedVariants] = useState<string[]>([]);
  const [expandedVariant, setExpandedVariant] = useState<string | null>(null);
  const [expandedCluster, setExpandedCluster] = useState<number | null>(null);
  const [step, setStep] = useState<"pick" | "anchor">("pick");
  const [anchor, setAnchor] = useState<string>("");
  // Etichetta vera del gruppo, presa dal server. In modalità "Per nome" la riga
  // cliccata porta il nome grezzo di una singola spesa, che può non essere il nome
  // del gruppo: mostrarlo qui farebbe credere all'utente di stare correggendo
  // un gruppo che non esiste con quel nome.
  const [groupName, setGroupName] = useState<string>("");

  const load = useCallback(async () => {
    if (!open || !target) return;
    setLoading(true);
    setError(null);
    try {
      if (mode === "merge") {
        const params = new URLSearchParams({ months: String(months) });
        if (target.categoryId !== null) params.set("category_id", String(target.categoryId));
        const response = await fetch(`/api/expense-labels/clusters?${params}`, {
          credentials: "same-origin",
          headers: readHeaders(initData),
        });
        if (!response.ok) throw new Error("Non riusciamo a caricare le altre voci.");
        const data = await response.json();
        const clusters: ExpenseLabelCluster[] = data.clusters ?? [];
        setGroupName(clusters.find((c) => c.id === target.id)?.anchor_text ?? target.anchorText);
        setCandidates(buildMergeCandidates(clusters, target.id, target.categoryId));
      } else {
        const response = await fetch(`/api/expense-labels/clusters/${target.id}/variants`, {
          credentials: "same-origin",
          headers: readHeaders(initData),
        });
        if (!response.ok) throw new Error("Non riusciamo a caricare le voci di questo gruppo.");
        const data = await response.json();
        setGroupName(data.anchor_text ?? target.anchorText);
        setVariants(data.variants ?? []);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Qualcosa è andato storto.");
    } finally {
      setLoading(false);
    }
  }, [open, target, mode, months, initData]);

  useEffect(() => {
    if (!open) return;
    setPicked({});
    setSelectedVariants([]);
    setExpandedVariant(null);
    setExpandedCluster(null);
    setStep("pick");
    setAnchor("");
    setGroupName(target?.anchorText ?? "");
    void load();
  }, [open, load, target]);

  /** Dettaglio dei movimenti, caricato solo per il gruppo che l'utente apre. */
  const openCluster = async (cluster: ExpenseLabelCluster) => {
    if (expandedCluster === cluster.id) {
      setExpandedCluster(null);
      return;
    }
    setExpandedCluster(cluster.id);
    if (cluster.variants.some((variant) => variant.expenses !== undefined)) return;
    try {
      const response = await fetch(`/api/expense-labels/clusters/${cluster.id}/variants`, {
        credentials: "same-origin",
        headers: readHeaders(initData),
      });
      if (!response.ok) return;
      const data = await response.json();
      const detailed: LabelVariant[] = data.variants ?? [];
      const byText = new Map(detailed.map((variant) => [variant.text, variant]));
      setCandidates((current) => current.map((item) => (
        item.id === cluster.id
          ? { ...item, variants: item.variants.map((v) => byText.get(v.text) ?? v) }
          : item
      )));
    } catch {
      // Il dettaglio è un di più: se non arriva, la selezione per voce resta usabile.
    }
  };

  /** Seleziona o deseleziona un intero gruppo (con tutte le sue voci). */
  const toggleCluster = (cluster: ExpenseLabelCluster) => {
    setPicked((current) => {
      const next = { ...current };
      if (next[cluster.id]) delete next[cluster.id];
      else next[cluster.id] = cluster.variants.map((variant) => variant.text);
      return next;
    });
  };

  /** Seleziona o deseleziona una voce: tutte le spese scritte così la seguono. */
  const toggleVariant = (cluster: ExpenseLabelCluster, text: string) => {
    setPicked((current) => {
      const chosen = current[cluster.id] ?? [];
      const next = chosen.includes(text)
        ? chosen.filter((item) => item !== text)
        : [...chosen, text];
      const updated = { ...current };
      if (next.length === 0) delete updated[cluster.id];
      else updated[cluster.id] = next;
      return updated;
    });
  };

  // Il nuovo gruppo prende il nome della variante con più spese tra quelle scelte:
  // è la forma che l'utente usa più spesso, quindi quella che riconosce nel grafico.
  const newAnchorPreview = selectedVariants.length > 0
    ? variants
        .filter((variant) => selectedVariants.includes(variant.text))
        .reduce((best, variant) => (variant.count > best.count ? variant : best)).text
    : "";

  const submit = async () => {
    if (!target) return;
    setSaving(true);
    setError(null);
    try {
      const headers = await mutationHeaders(initData);
      const endpoint = mode === "merge" ? "/api/expense-labels/merge" : "/api/expense-labels/split";
      // `anchor_text` blocca l'etichetta per sempre: si invia solo se l'utente ha
      // scelto qualcosa di diverso dal nome che il gruppo aveva già. Accettando il
      // default, l'etichetta continua a seguire la variante più frequente.
      const chosenAnchor = anchor === "" || anchor === groupName ? null : anchor;
      // `source_variants` viaggia solo per i gruppi presi in parte: per quelli presi
      // per intero si lascia decidere il server, che li assorbe e li cancella.
      const partial = Object.fromEntries(
        Object.entries(picked).filter(([clusterId, texts]) => {
          const cluster = candidates.find((item) => item.id === Number(clusterId));
          return cluster !== undefined && texts.length < cluster.variants.length;
        }),
      );
      const body = mode === "merge"
        ? {
            target_cluster_id: target.id,
            source_cluster_ids: Object.keys(picked).map(Number),
            anchor_text: chosenAnchor,
            ...(Object.keys(partial).length > 0 ? { source_variants: partial } : {}),
          }
        : { cluster_id: target.id, variants: selectedVariants, new_anchor: newAnchorPreview };
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers,
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error ?? "Non siamo riusciti a salvare la correzione.");
      onDone(mode === "merge" ? "Voci unite." : "Voci separate.");
      onClose();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Qualcosa è andato storto.");
    } finally {
      setSaving(false);
    }
  };

  const anchorOptions = mode === "merge"
    ? [groupName, ...candidates.filter((c) => picked[c.id]).map((c) => c.anchor_text)]
    : [];

  const canSubmit = mode === "merge"
    ? Object.keys(picked).length > 0
    : selectedVariants.length > 0 && selectedVariants.length < variants.length;

  const title = mode === "merge" ? "Unisci con…" : "Cosa non va insieme?";

  return (
    <Dialog open={open} onClose={saving ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers>
        {loading ? (
          <Box display="flex" justifyContent="center" py={4}><CircularProgress size={28} /></Box>
        ) : (
          <>
            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

            {mode === "merge" && step === "pick" && (
              candidates.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  Non ci sono altre voci della stessa categoria con cui unire «{groupName}».
                </Typography>
              ) : (
                <>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Quali gruppi vuoi unire a «{groupName}»? Apri un gruppo per
                    scegliere solo alcune voci. I numeri contano tutte le spese del
                    gruppo, anche fuori dal periodo che stai guardando: unendo si
                    spostano tutte.
                  </Typography>
                  <List disablePadding>
                    {candidates.map((cluster) => {
                      const chosen = picked[cluster.id] ?? [];
                      const isPartial = chosen.length > 0 && chosen.length < cluster.variants.length;
                      const isOpen = expandedCluster === cluster.id;
                      return (
                        <Box key={cluster.id}>
                          <Box display="flex" alignItems="center">
                            <ListItemButton
                              sx={{ minHeight: 44, flex: 1 }}
                              onClick={() => toggleCluster(cluster)}
                            >
                              <Checkbox
                                edge="start"
                                checked={chosen.length > 0}
                                indeterminate={isPartial}
                                tabIndex={-1}
                                disableRipple
                              />
                              <ListItemText
                                primary={cluster.anchor_text}
                                primaryTypographyProps={{ fontWeight: 600 }}
                                secondary={`${cluster.count} ${cluster.count === 1 ? "operazione" : "operazioni"} · ${euro(cluster.total)}${isPartial ? ` · ${chosen.length} di ${cluster.variants.length} voci` : ""}`}
                              />
                            </ListItemButton>
                            <IconButton
                              aria-label={`${isOpen ? "Nascondi" : "Mostra"} le spese di ${cluster.anchor_text}`}
                              aria-expanded={isOpen}
                              onClick={() => void openCluster(cluster)}
                              sx={{ width: 44, height: 44 }}
                            >
                              <ChevronDown
                                size={18}
                                aria-hidden="true"
                                style={{ transform: isOpen ? "rotate(180deg)" : "none" }}
                              />
                            </IconButton>
                          </Box>
                          <Collapse in={isOpen} timeout="auto">
                            <Box pl={2} pb={1}>
                              {cluster.variants.map((variant) => (
                                <Box key={variant.text}>
                                  <Box
                                    component="button"
                                    type="button"
                                    onClick={() => toggleVariant(cluster, variant.text)}
                                    sx={{ display: "flex", alignItems: "center", gap: 1, width: "100%", minHeight: 44, p: 0, border: 0, background: "transparent", color: "inherit", font: "inherit", textAlign: "left", cursor: "pointer" }}
                                  >
                                    <Checkbox size="small" checked={chosen.includes(variant.text)} tabIndex={-1} disableRipple />
                                    <Box flex={1} minWidth={0}>
                                      <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>{variant.text}</Typography>
                                      <Typography variant="caption" color="text.secondary">
                                        {variant.count} {variant.count === 1 ? "spesa" : "spese"} · {euro(variant.total)}
                                      </Typography>
                                    </Box>
                                  </Box>
                                  <Box pl={5} pb={0.5}>
                                    {(variant.expenses ?? []).map((expense) => (
                                      <Box key={expense.id} display="flex" justifyContent="space-between" gap={1} py={0.25}>
                                        <Typography variant="caption" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                                          {expense.name} · {formatDateIt(expense.date)}
                                        </Typography>
                                        <Typography variant="caption" whiteSpace="nowrap">{euro(expense.amount)}</Typography>
                                      </Box>
                                    ))}
                                  </Box>
                                </Box>
                              ))}
                            </Box>
                          </Collapse>
                          <Divider />
                        </Box>
                      );
                    })}
                  </List>
                </>
              )
            )}

            {mode === "merge" && step === "anchor" && (
              <>
                <Typography variant="body2" gutterBottom>Quale nome vuoi tenere?</Typography>
                <RadioGroup value={anchor} onChange={(event) => setAnchor(event.target.value)}>
                  {anchorOptions.map((option) => (
                    <FormControlLabel
                      key={option}
                      value={option}
                      control={<Radio />}
                      label={option}
                      sx={{ minHeight: 44 }}
                    />
                  ))}
                </RadioGroup>
              </>
            )}

            {mode === "split" && (
              <>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Tocca le voci che non c&apos;entrano con «{groupName}»: le sposteremo in
                  un gruppo a parte, ora e in futuro.
                </Typography>
                <Box display="flex" flexWrap="wrap" gap={1} mt={1.5}>
                  {variants.map((variant) => (
                    <Box key={variant.text} width="100%">
                      <Box display="flex" alignItems="center" gap={0.5}>
                        <Chip
                          label={`«${variant.text}» · ${variant.count} ${variant.count === 1 ? "spesa" : "spese"}`}
                          color={selectedVariants.includes(variant.text) ? "primary" : "default"}
                          variant={selectedVariants.includes(variant.text) ? "filled" : "outlined"}
                          onClick={() => setSelectedVariants((current) => (
                            current.includes(variant.text)
                              ? current.filter((text) => text !== variant.text)
                              : [...current, variant.text]
                          ))}
                          sx={{ minHeight: 44, flex: 1, minWidth: 0, justifyContent: "flex-start" }}
                        />
                        <IconButton
                          aria-label={`Mostra le spese di ${variant.text}`}
                          aria-expanded={expandedVariant === variant.text}
                          onClick={() => setExpandedVariant((current) => (
                            current === variant.text ? null : variant.text
                          ))}
                          sx={{ width: 44, height: 44, flexShrink: 0 }}
                        >
                          <ChevronDown
                            size={18}
                            aria-hidden="true"
                            style={{ transform: expandedVariant === variant.text ? "rotate(180deg)" : "none" }}
                          />
                        </IconButton>
                      </Box>
                      <Collapse in={expandedVariant === variant.text} timeout="auto">
                        <Box px={1.5} py={0.5}>
                          {(variant.expenses ?? []).map((expense, index) => (
                            <Box key={expense.id}>
                              {index > 0 && <Divider sx={{ my: 0.5 }} />}
                              <Box display="flex" justifyContent="space-between" gap={1} py={0.25}>
                                <Box minWidth={0}>
                                  <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>{expense.name}</Typography>
                                  <Typography variant="caption" color="text.secondary">
                                    {formatDateIt(expense.date)}
                                  </Typography>
                                </Box>
                                <Typography variant="caption" whiteSpace="nowrap">{euro(expense.amount)}</Typography>
                              </Box>
                            </Box>
                          ))}
                        </Box>
                      </Collapse>
                    </Box>
                  ))}
                </Box>
                {selectedVariants.length > 0 && selectedVariants.length < variants.length && (
                  <Typography variant="caption" color="text.secondary" display="block" mt={2}>
                    Il nuovo gruppo si chiamerà «{newAnchorPreview}».
                  </Typography>
                )}
                {selectedVariants.length > 0 && selectedVariants.length === variants.length && (
                  <Typography variant="caption" color="text.secondary" display="block" mt={2}>
                    Lascia almeno una voce nel gruppo di partenza.
                  </Typography>
                )}
              </>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving} sx={{ minHeight: 44 }}>Annulla</Button>
        {mode === "merge" && step === "pick" ? (
          <Button
            variant="contained"
            disabled={!canSubmit || loading}
            onClick={() => { if (!anchor) setAnchor(groupName); setStep("anchor"); }}
            sx={{ minHeight: 44 }}
          >
            Avanti
          </Button>
        ) : (
          <Button
            variant="contained"
            disabled={!canSubmit || loading || saving}
            onClick={() => void submit()}
            sx={{ minHeight: 44 }}
          >
            {mode === "merge" ? "Unisci" : "Separa"}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
