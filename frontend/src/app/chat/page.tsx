"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Check, X, Pencil, FolderOpen, Undo2, Landmark, FileText, BarChart2, Target, Tags, ChevronRight, Info } from "lucide-react";
import styles from "./page.module.css";
import { buildExpenseAnalyticsHref, buildTransfersSpaceHref } from "@/lib/contextual-navigation";
import { SafeMarkdown } from "@/components/SafeMarkdown";
import { selectableAccounts } from "@/features/expense-capture/model";
import { buildHeaders } from "@/lib/apiHeaders";
import { useExpenseCaptureFlow } from "@/features/expense-capture/useExpenseCaptureFlow";
import type { Account } from "@/features/expense-capture/types";

// ─── Types ────────────────────────────────────────────────────────────────────

interface QuickExpense {
  id?: number; // solo per i bottoni personalizzati (source "custom"), serve a cancellarli
  label: string;
  name: string;
  category: string;
  account_id: string | null; // null = nessun conto preimpostato (personalizzato senza conto)
  account_name: string | null;
  source: "auto" | "custom";
}

interface CategorySpend {
  name: string;
  amount: number;
}

interface BudgetStatus {
  budget: number;
  spent: number;
}

interface ChatFinancialSummary {
  totalSpent: number;
  topCategory: CategorySpend | null;
  budgetRemaining: number | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(date: Date): string {
  return date.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

function formatCurrency(amount: number): string {
  return amount.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

// ─── Suggestions ──────────────────────────────────────────────────────────────

const SUGGESTIONS = [
  "Ho speso 24€ per il sushi",
  "Stipendio 1500€",
  "Netflix 12,99€",
  "Affitto 450€",
];

// ─── Component ────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const router = useRouter();

  const [quickExpenses, setQuickExpenses] = useState<QuickExpense[]>([]);
  const [quickExpenseModal, setQuickExpenseModal] = useState<{
    expense: QuickExpense;
    step: "amount" | "account";
    amount: string;
    accountId: string | null;
    accounts: Account[] | null;
    accountsLoading: boolean;
    submitting: boolean;
    error: string | null;
  } | null>(null);
  const [quickExpensesInfoOpen, setQuickExpensesInfoOpen] = useState(false);
  const [newShortcutModal, setNewShortcutModal] = useState<{
    name: string;
    categoryId: string;
    accountId: string;
    categories: { id: number; name: string }[] | null;
    accounts: Account[] | null;
    loading: boolean;
    submitting: boolean;
    error: string | null;
  } | null>(null);
  // Pressione prolungata sui bottoni spese rapide: entra in modalità modifica
  // (mostra la "x" per cancellare, abilita il trascinamento per riordinare i
  // personalizzati — l'automatico resta sempre primo e non si sposta).
  const [quickEditMode, setQuickEditMode] = useState(false);
  const [draggingChipId, setDraggingChipId] = useState<number | null>(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [liveOrder, setLiveOrder] = useState<number[] | null>(null);
  const chipRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const pointerMovedRef = useRef(false);
  const [financialSummary, setFinancialSummary] = useState<ChatFinancialSummary | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const quickExpensesRequestRef = useRef(0);
  const financialSummaryRequestRef = useRef(0);

  const refreshQuickExpenses = useCallback(async () => {
    const requestId = ++quickExpensesRequestRef.current;
    try {
      const headers = await buildHeaders();
      const response = await fetch("/api/chat/quick-expenses", { credentials: "same-origin", headers });
      const data = response.ok ? await response.json() : null;
      if (requestId === quickExpensesRequestRef.current) {
        setQuickExpenses(Array.isArray(data?.quick_expenses) ? data.quick_expenses : []);
      }
    } catch {
      // I chip sono un aiuto non bloccante: manteniamo quelli già visibili in caso di rete assente.
    }
  }, []);

  const refreshFinancialSummary = useCallback(async () => {
    const requestId = ++financialSummaryRequestRef.current;
    try {
      const headers = await buildHeaders();
      const [categoriesResponse, budgetResponse, preferencesResponse] = await Promise.all([
        fetch("/api/analytics/categories-expense?months=1", { credentials: "same-origin", headers }),
        fetch("/api/analytics/budget-status", { credentials: "same-origin", headers }),
        fetch("/api/user/preferences", { credentials: "same-origin", headers }),
      ]);
      if (!categoriesResponse.ok) return;

      const categoriesData = await categoriesResponse.json() as { by_category?: CategorySpend[] };
      const budgetData = budgetResponse.ok
        ? await budgetResponse.json() as { budget_status?: BudgetStatus[] }
        : { budget_status: [] };
      const preferencesData = preferencesResponse.ok
        ? await preferencesResponse.json() as { monthly_budget?: number | string | null }
        : { monthly_budget: null };
      const categories = Array.isArray(categoriesData.by_category) ? categoriesData.by_category : [];
      const topCategory = categories.reduce<CategorySpend | null>(
        (top, category) => !top || category.amount > top.amount ? category : top,
        null,
      );
      const budgets = Array.isArray(budgetData.budget_status) ? budgetData.budget_status : [];
      const totalSpent = categories.reduce((total, category) => total + category.amount, 0);

      // Stessa priorità della card "Budget disponibile" in Analytics
      // (buildTodaySummary in app/analytics/viewModels.ts): budget mensile
      // generale se impostato, altrimenti somma dei budget di categoria.
      const monthlyBudget = preferencesData.monthly_budget == null ? null : Number(preferencesData.monthly_budget);
      const hasMonthlyBudget = monthlyBudget != null && Number.isFinite(monthlyBudget) && monthlyBudget > 0;
      const budgetRemaining = hasMonthlyBudget
        ? monthlyBudget - totalSpent
        : budgets.length > 0
          ? budgets.reduce((total, budget) => total + budget.budget - budget.spent, 0)
          : null;

      if (requestId === financialSummaryRequestRef.current) {
        setFinancialSummary({
          totalSpent,
          topCategory,
          budgetRemaining,
        });
      }
    } catch {
      // Il riepilogo è complementare alla chat: non ne blocca mai l'uso.
    }
  }, []);

  // Flusso di acquisizione condiviso col composer globale: stesse chiamate API,
  // stessa conferma esplicita, stessa coda multi-transazione.
  const capture = useExpenseCaptureFlow({
    loadHistory: true,
    onSaved: (result) => {
      if (!result.saved) return;
      void refreshQuickExpenses();
      void refreshFinancialSummary();
    },
  });
  const {
    messages,
    inputText,
    isLoading,
    isRecording,
    showTypingIndicator,
    historyLoaded,
    setInputText,
    sendText,
    toggleVoice,
    sendPhoto,
    confirm,
    cancel,
    selectCategory,
    openCategoryPicker,
    closeCategoryPicker,
    selectAccount,
    resolveCategoryPromotion,
    saveDirect,
  } = capture;

  useEffect(() => {
    void refreshQuickExpenses();
  }, [refreshQuickExpenses]);

  useEffect(() => () => {
    if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
  }, []);

  useEffect(() => {
    void refreshFinancialSummary();
  }, [refreshFinancialSummary]);

  // Whether to show the welcome screen (no user/bot messages yet except welcome)
  const hasConversation = messages.length > 0 && historyLoaded;
  const onlyWelcome = hasConversation && messages.length === 1 && messages[0].id === "welcome";
  const showWelcome = !hasConversation || onlyWelcome;

  // ── Auto-scroll ───────────────────────────────────────────────────────────

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, showTypingIndicator]);

  // ── Auto-resize textarea ──────────────────────────────────────────────────

  const resizeTextarea = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, []);

  useEffect(() => {
    resizeTextarea();
  }, [inputText, resizeTextarea]);

  // ── Spese rapide ──────────────────────────────────────────────────────────

  // Apre il mini-modale con nome/categoria già compilati (dal metadato di
  // normalizzazione, non dal nome grezzo dell'ultima occorrenza) — 2 step: prima
  // l'importo, poi la scelta del conto (mai precompilato: la spesa rapida ricorda
  // "cosa" si compra di solito, non "da quale conto" lo si paga ogni volta).
  const handleQuickExpense = useCallback((quickExpense: QuickExpense) => {
    setQuickExpenseModal({
      expense: quickExpense, step: "amount", amount: "",
      accountId: null, accounts: null, accountsLoading: false,
      submitting: false, error: null,
    });
  }, []);

  const closeQuickExpenseModal = useCallback(() => setQuickExpenseModal(null), []);

  const isValidQuickAmount = (amount: string): boolean => {
    const value = Number(amount.replace(",", "."));
    return !!amount.trim() && Number.isFinite(value) && value > 0;
  };

  // Un tap su un conto seleziona E registra insieme (l'accountId viene passato
  // direttamente, non letto dallo stato — eviterebbe la corsa tra il click e il
  // successivo render dello stato aggiornato). Riusa il salvataggio del controller,
  // lo stesso percorso di conferma del flusso normale (/api/chat/confirm): stessa
  // bubble di riepilogo in chat, stesso tracking/gamification.
  const submitQuickExpense = useCallback(async (accountId: string) => {
    const current = quickExpenseModal;
    if (!current || !isValidQuickAmount(current.amount)) return;
    // Il modale si chiude subito (un tap sul conto = selezione + registrazione,
    // per design): non c'è uno stato "submitting" visibile da mostrare, la
    // conferma arriva come bubble in chat via saveDirect qui sotto.
    const amountValue = Number(current.amount.replace(",", "."));
    setQuickExpenseModal(null);
    await saveDirect({
      type: "expense",
      amount: amountValue,
      name: current.expense.name,
      category: current.expense.category,
      date: new Date().toISOString().slice(0, 10),
    }, { account_id: accountId });
  }, [quickExpenseModal, saveDirect]);

  // Dopo l'importo: se il bottone ha già un conto preimpostato (un personalizzato
  // creato scegliendolo) si registra subito, senza chiederlo di nuovo — solo
  // l'automatico (mai precompilato by design) e i personalizzati senza conto
  // passano dallo step di scelta.
  const proceedFromAmountStep = useCallback(async () => {
    if (quickExpenseModal && isValidQuickAmount(quickExpenseModal.amount) && quickExpenseModal.expense.account_id) {
      await submitQuickExpense(quickExpenseModal.expense.account_id);
      return;
    }

    setQuickExpenseModal((prev) => {
      if (!prev) return prev;
      if (!isValidQuickAmount(prev.amount)) return { ...prev, error: "Inserisci un importo valido." };
      return { ...prev, step: "account", error: null, accountsLoading: prev.accounts === null };
    });

    if (quickExpenseModal?.accounts !== null) return;
    try {
      const res = await fetch("/api/space/accounts", { credentials: "same-origin", headers: await buildHeaders() });
      const data = res.ok ? await res.json() : null;
      const accounts: Account[] = Array.isArray(data?.accounts) ? data.accounts : [];
      setQuickExpenseModal((prev) => (prev ? { ...prev, accounts, accountsLoading: false } : prev));
    } catch {
      setQuickExpenseModal((prev) =>
        prev ? { ...prev, accountsLoading: false, error: "Non riesco a caricare i conti. Riprova." } : prev
      );
    }
  }, [quickExpenseModal, submitQuickExpense]);

  // Bottone "+": l'utente crea un bottone spesa rapida permanente, con i campi
  // che sceglie lui (a differenza di quello automatico, che li pesca dallo storico
  // e cambia da solo). Carica categorie/conti al volo, solo quando serve.
  const openNewShortcutModal = useCallback(async () => {
    setNewShortcutModal({
      name: "", categoryId: "", accountId: "",
      categories: null, accounts: null, loading: true, submitting: false, error: null,
    });
    try {
      const headers = await buildHeaders();
      const [catRes, accRes] = await Promise.all([
        fetch("/api/space/categories", { credentials: "same-origin", headers }),
        fetch("/api/space/accounts", { credentials: "same-origin", headers }),
      ]);
      const catData = catRes.ok ? await catRes.json() : null;
      const accData = accRes.ok ? await accRes.json() : null;
      const categories: { id: number; name: string; archived?: boolean }[] =
        Array.isArray(catData?.categories) ? catData.categories : [];
      const accounts: Account[] = Array.isArray(accData?.accounts) ? accData.accounts : [];
      setNewShortcutModal((prev) => prev && {
        ...prev,
        loading: false,
        categories: categories.filter((c) => !c.archived),
        accounts,
      });
    } catch {
      setNewShortcutModal((prev) => prev && { ...prev, loading: false, error: "Non riesco a caricare categorie/conti." });
    }
  }, []);

  const closeNewShortcutModal = useCallback(() => setNewShortcutModal(null), []);

  const submitNewShortcut = useCallback(async () => {
    const current = newShortcutModal;
    // Doppio tap rapido su "Crea": senza questa guardia partirebbero due POST e
    // due bottoni identici (la seconda chiamata leggerebbe comunque `submitting:
    // false` dalla closure catturata prima del primo aggiornamento di stato).
    if (!current || current.submitting || !current.name.trim()) {
      setNewShortcutModal((prev) => (prev && !prev.name.trim() ? { ...prev, error: "Dai un nome al bottone." } : prev));
      return;
    }
    setNewShortcutModal((prev) => (prev ? { ...prev, submitting: true, error: null } : prev));

    try {
      const res = await fetch("/api/chat/quick-expenses/custom", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await buildHeaders()) },
        credentials: "same-origin",
        body: JSON.stringify({
          name: current.name.trim(),
          category_id: current.categoryId || null,
          account_id: current.accountId || null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error || `HTTP ${res.status}`);
      }
      setNewShortcutModal(null);
      void refreshQuickExpenses();
    } catch (e) {
      const reason = e instanceof Error ? e.message : "Creazione non riuscita";
      setNewShortcutModal((prev) => prev && { ...prev, submitting: false, error: `${reason}. Riprova.` });
    }
  }, [newShortcutModal, refreshQuickExpenses]);

  const deleteShortcut = useCallback(async (id: number) => {
    try {
      const res = await fetch(`/api/chat/quick-expenses/custom/${id}`, {
        method: "DELETE",
        headers: await buildHeaders(),
        credentials: "same-origin",
      });
      if (res.ok) void refreshQuickExpenses();
    } catch {
      // best-effort: se fallisce, il bottone resta e l'utente può riprovare
    }
  }, [refreshQuickExpenses]);

  const customChipIds = useMemo(
    () => quickExpenses.filter((q) => q.source === "custom" && q.id != null).map((q) => q.id as number),
    [quickExpenses]
  );

  // Lista effettivamente renderizzata: durante un trascinamento usa l'ordine
  // provvisorio (`liveOrder`), altrimenti quello persistito in `quickExpenses`
  // (l'automatico resta sempre primo, non fa parte del riordino).
  const displayedQuickExpenses = useMemo(() => {
    const auto = quickExpenses.filter((q) => q.source === "auto");
    const customById = new Map(quickExpenses.filter((q) => q.source === "custom").map((q) => [q.id, q]));
    const order = liveOrder ?? customChipIds;
    const ordered = order.map((id) => customById.get(id)).filter((q): q is QuickExpense => !!q);
    return [...auto, ...ordered];
  }, [quickExpenses, liveOrder, customChipIds]);

  const persistShortcutOrder = useCallback(async (order: number[]) => {
    // Ottimistico: l'ordine visivo è già quello giusto (era `liveOrder`), lo
    // scrivo anche nello stato "vero" così sopravvive al prossimo refresh.
    setQuickExpenses((prev) => {
      const auto = prev.filter((q) => q.source === "auto");
      const customById = new Map(prev.filter((q) => q.source === "custom").map((q) => [q.id, q]));
      const ordered = order.map((id) => customById.get(id)).filter((q): q is QuickExpense => !!q);
      return [...auto, ...ordered];
    });
    try {
      await fetch("/api/chat/quick-expenses/custom/reorder", {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await buildHeaders()) },
        credentials: "same-origin",
        body: JSON.stringify({ order }),
      });
    } catch {
      void refreshQuickExpenses(); // il server resta la verità in caso di errore
    }
  }, [refreshQuickExpenses]);

  const handleChipPointerDown = useCallback((quickExpense: QuickExpense, e: React.PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    pointerMovedRef.current = false;
    dragStartRef.current = { x: e.clientX, y: e.clientY };
    // Cattura SUBITO, non dentro il timeout: se aspettassimo i 500ms, un dito che
    // si sposta di pochi px e viene rilasciato fuori dal wrapper prima che il
    // timer scatti non genera mai pointerup/pointercancel qui — il timer resta
    // vivo e la modalità modifica si attiva da sola più tardi, a dito già staccato.
    // `currentTarget` (il wrapper) è stabile; `target` può essere il bottone/svg
    // interno, smontato quando il render aggiunge la "x" in modalità modifica.
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* no-op */ }
    if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
    longPressTimerRef.current = setTimeout(() => {
      setQuickEditMode(true);
      if (quickExpense.source === "custom" && quickExpense.id != null) {
        setDraggingChipId(quickExpense.id);
        setLiveOrder(customChipIds);
      }
    }, 500);
  }, [customChipIds]);

  const handleChipPointerMove = useCallback((quickExpense: QuickExpense, e: React.PointerEvent<HTMLDivElement>) => {
    const { x: startX, y: startY } = dragStartRef.current;
    if (Math.hypot(e.clientX - startX, e.clientY - startY) > 6) {
      pointerMovedRef.current = true;
      if (longPressTimerRef.current) { clearTimeout(longPressTimerRef.current); longPressTimerRef.current = null; }
    }
    if (draggingChipId == null || draggingChipId !== quickExpense.id) return;

    setDragOffset({ x: e.clientX - startX, y: e.clientY - startY });

    // Confronto 2D (non solo clientX): con più di 3-4 bottoni la riga va a capo
    // (flex-wrap) e "il vicino nell'ordine" può stare fisicamente su un'altra riga,
    // a una X molto più piccola — un confronto solo orizzontale scambierebbe subito
    // in modo scorretto. Qui si cerca invece, tra tutti i personalizzati, quello
    // il cui rettangolo contiene davvero il punto sotto il dito.
    const order = liveOrder ?? customChipIds;
    const currentIdx = order.indexOf(draggingChipId);
    if (currentIdx === -1) return;

    let targetIdx: number | null = null;
    for (let i = 0; i < order.length; i++) {
      if (order[i] === draggingChipId) continue;
      const el = chipRefs.current.get(order[i]);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
        targetIdx = i;
        break;
      }
    }
    if (targetIdx !== null && targetIdx !== currentIdx) {
      const next = [...order];
      next.splice(currentIdx, 1);
      next.splice(targetIdx, 0, draggingChipId);
      setLiveOrder(next);
    }
  }, [draggingChipId, liveOrder, customChipIds]);

  const handleChipPointerUp = useCallback((quickExpense: QuickExpense) => {
    if (longPressTimerRef.current) { clearTimeout(longPressTimerRef.current); longPressTimerRef.current = null; }

    if (draggingChipId != null) {
      const finalOrder = liveOrder ?? customChipIds;
      setDraggingChipId(null);
      setDragOffset({ x: 0, y: 0 });
      setLiveOrder(null);
      // Pressione prolungata senza spostamento reale: non c'è nulla da salvare.
      const orderChanged = finalOrder.length !== customChipIds.length
        || finalOrder.some((id, i) => id !== customChipIds[i]);
      if (orderChanged) void persistShortcutOrder(finalOrder);
      return;
    }

    if (!quickEditMode && !pointerMovedRef.current) {
      handleQuickExpense(quickExpense);
    }
  }, [draggingChipId, liveOrder, customChipIds, persistShortcutOrder, quickEditMode, handleQuickExpense]);

  const exitQuickEditMode = useCallback(() => {
    setQuickEditMode(false);
    setDraggingChipId(null);
    setDragOffset({ x: 0, y: 0 });
    setLiveOrder(null);
  }, []);

  useEffect(() => {
    if (!quickEditMode) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") exitQuickEditMode();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [quickEditMode, exitQuickEditMode]);

  // ── Composer ──────────────────────────────────────────────────────────────

  const handleSend = useCallback(async (text?: string) => {
    await sendText(text);
    inputRef.current?.focus();
  }, [sendText]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const handleImageClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    await sendPhoto(file);
  };

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={styles.chatRoot}>
      <h1 className={styles.visuallyHidden}>Chat con Moneo</h1>
      {!showWelcome && (
        <nav className={styles.contextCards} aria-label="Scorciatoie finanziarie">
          <div className={styles.contextCard}>
            <BarChart2 size={18} aria-hidden="true" /><span><strong>Hai speso</strong><small>{financialSummary ? `${formatCurrency(financialSummary.totalSpent)} questo mese` : "Aggiornamento in corso"}</small></span>
            <button type="button" className={styles.contextCardAction} aria-label="Apri le categorie di spesa del mese" onClick={() => router.push(buildExpenseAnalyticsHref(null))}><ChevronRight size={18} aria-hidden="true" /></button>
          </div>
          <div className={styles.contextCard}>
            <Tags size={18} aria-hidden="true" /><span><strong>Categoria top</strong><small>{financialSummary?.topCategory ? `${financialSummary.topCategory.name} · ${formatCurrency(financialSummary.topCategory.amount)}` : "Nessuna spesa questo mese"}</small></span>
            <button type="button" className={styles.contextCardAction} aria-label="Apri la schermata Oggi di Analytics" onClick={() => router.push("/analytics")}><ChevronRight size={18} aria-hidden="true" /></button>
          </div>
          <div className={styles.contextCard}>
            <Target size={18} aria-hidden="true" /><span><strong>Budget rimasto</strong><small>{financialSummary?.budgetRemaining === null || financialSummary?.budgetRemaining === undefined ? "Imposta i limiti mensili" : formatCurrency(financialSummary.budgetRemaining)}</small></span>
            <button type="button" className={styles.contextCardAction} aria-label="Apri il piano budget in Analytics" onClick={() => router.push("/analytics?tab=plan")}><ChevronRight size={18} aria-hidden="true" /></button>
          </div>
        </nav>
      )}
      {showWelcome ? (
        /* ── Welcome Screen ─────────────────────────────────────────── */
        <div className={styles.welcomeScreen}>
          <div className={styles.welcomeLogo}>
            <Image
              src="/logo-expensum-icon.png"
              alt="Expensum"
              width={56}
              height={56}
              className={styles.welcomeLogoImg}
              priority
            />
          </div>

          <h2 className={styles.welcomeTitle}>
            Come Posso Aiutarti Oggi?
          </h2>

          <p className={styles.welcomeSubtitle}>
            Dimmi una spesa o un&apos;entrata e la registro subito
          </p>

          <div className={styles.suggestionsRow}>
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                className={styles.suggestionChip}
                onClick={() => void handleSend(s)}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          {/* ── Messages ───────────────────────────────────────────────── */}
          <div className={styles.messagesArea}>
            <div className={styles.messagesInner}>
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`${styles.messageRow} ${msg.role === "user" ? styles.messageRowUser : styles.messageRowBot}`}
                >
                  <div className={`${styles.bubble} ${msg.role === "user" ? styles.bubbleUser : styles.bubbleBot}`}>
                    <SafeMarkdown as="p" className={styles.bubbleText} text={msg.text} />

                    {/* Parsed transaction pill */}
                    {msg.parsed?.amount != null && (
                      <div className={styles.parsedPill}>
                        <span className={msg.parsed.type === "income" ? styles.pillIncome : styles.pillExpense}>
                          {msg.parsed.type === "income" ? "+" : "-"}€{Number(msg.parsed.amount).toFixed(2)}
                        </span>
                        {msg.parsed.category && (
                          <span className={styles.pillCategory}>{msg.parsed.category}</span>
                        )}
                        {(msg.parsed.income_category || msg.parsed.income_type) && !msg.parsed.category && (
                          <span className={styles.pillCategory}>{msg.parsed.income_category || msg.parsed.income_type}</span>
                        )}
                      </div>
                    )}

                    {/* Dopo il salvataggio, guida al prossimo passo senza interrompere la chat. */}
                    {msg.savedTransaction && msg.parsed?.type === "expense" && (
                      <div className={styles.confirmRow}>
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnYes}`}
                          onClick={() => router.push(buildExpenseAnalyticsHref(msg.parsed?.category))}
                        >
                          <BarChart2 size={15} strokeWidth={1.75} aria-hidden="true" /> Vedi le spese
                        </button>
                      </div>
                    )}
                    {msg.savedTransaction && msg.parsed?.type === "transfer" && (
                      <div className={styles.confirmRow}>
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnYes}`}
                          onClick={() => router.push(buildTransfersSpaceHref())}
                        >
                          <Landmark size={15} strokeWidth={1.75} aria-hidden="true" /> Vedi i trasferimenti
                        </button>
                      </div>
                    )}

                    {/* Report generato: link diretto alla tab Report */}
                    {msg.parsed?.share_token && (
                      <div className={styles.confirmRow}>
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnYes}`}
                          onClick={() => router.push(`/reports/${msg.parsed!.share_token}`)}
                        >
                          <FileText size={15} strokeWidth={1.75} aria-hidden="true" /> Vedi il report
                        </button>
                      </div>
                    )}

                    {/* Nessun conto configurato: link diretto alla tab Conti */}
                    {msg.noAccountAction && (
                      <div className={styles.confirmRow}>
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnYes}`}
                          onClick={() => router.push("/spazio")}
                        >
                          <Landmark size={15} strokeWidth={1.75} aria-hidden="true" /> Vai ai Conti
                        </button>
                      </div>
                    )}

                    {/* Confirm buttons (+ cambio categoria rapido per spese/entrate) */}
                    {msg.awaitingConfirm && msg.parsed && (
                      <>
                        {(msg.parsed.type === "expense" || msg.parsed.type === "income") && (
                          <div className={styles.confirmRow}>
                            <button
                              className={`${styles.confirmBtn} ${styles.confirmBtnNo}`}
                              onClick={() => openCategoryPicker(msg.id)}
                            >
                              <Pencil size={15} strokeWidth={1.75} aria-hidden="true" /> Cambia categoria
                            </button>
                          </div>
                        )}
                        <div className={styles.confirmRow}>
                          <button
                            className={`${styles.confirmBtn} ${styles.confirmBtnYes}`}
                            onClick={() => void confirm(msg.id)}
                          >
                            <Check size={15} strokeWidth={1.75} aria-hidden="true" /> Conferma
                          </button>
                          <button
                            className={`${styles.confirmBtn} ${styles.confirmBtnNo}`}
                            onClick={() => cancel(msg.id)}
                          >
                            <X size={15} strokeWidth={1.75} aria-hidden="true" /> Annulla
                          </button>
                        </div>
                      </>
                    )}

                    {/* Conferma creazione categoria (categorizzazione adattiva) */}
                    {msg.categoryPromotion && !msg.categoryPromotionResolved && (
                      <div className={styles.confirmRow}>
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnYes}`}
                          onClick={() =>
                            void resolveCategoryPromotion(msg.id, msg.categoryPromotion!.candidateId, "yes")
                          }
                        >
                          <Check size={15} strokeWidth={1.75} aria-hidden="true" /> Sì
                        </button>
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnNo}`}
                          onClick={() =>
                            void resolveCategoryPromotion(msg.id, msg.categoryPromotion!.candidateId, "no")
                          }
                        >
                          <X size={15} strokeWidth={1.75} aria-hidden="true" /> No
                        </button>
                      </div>
                    )}

                    {/* Picker categoria (cambio rapido) */}
                    {msg.awaitingCategoryPick && msg.parsed?.categories && (
                      <div className={styles.pickerCol}>
                        {msg.parsed.categories.map((cat) => (
                          <button
                            key={cat}
                            className={`${styles.confirmBtn} ${styles.pickerBtn}`}
                            onClick={() => selectCategory(msg.id, cat)}
                          >
                            <FolderOpen size={15} strokeWidth={1.75} aria-hidden="true" /> {cat}
                          </button>
                        ))}
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnNo}`}
                          onClick={() => closeCategoryPicker(msg.id)}
                        >
                          <Undo2 size={15} strokeWidth={1.75} aria-hidden="true" /> Indietro
                        </button>
                      </div>
                    )}

                    {/* Picker conto (single = spesa/entrata, from/to = trasferimento) */}
                    {msg.awaitingAccountPick && msg.parsed?.accounts && (
                      <div className={styles.pickerCol}>
                        {selectableAccounts(msg)
                          .map((acc) => (
                            <button
                              key={acc.id}
                              className={`${styles.confirmBtn} ${styles.pickerBtn}`}
                              onClick={() => void selectAccount(msg.id, acc.id)}
                            >
                              <Landmark size={15} strokeWidth={1.75} aria-hidden="true" /> {acc.name}
                              {acc.current_balance != null ? ` (€${Number(acc.current_balance).toFixed(2)})` : ""}
                            </button>
                          ))}
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnNo}`}
                          onClick={() => cancel(msg.id)}
                        >
                          <X size={15} strokeWidth={1.75} aria-hidden="true" /> Annulla
                        </button>
                      </div>
                    )}

                    <div className={styles.bubbleMeta}>
                      <span className={styles.bubbleTime}>{formatTime(msg.timestamp)}</span>
                      {msg.role === "user" && (
                        <span className={styles.bubbleCheck}>
                          {msg.status === "sending" ? "○" : msg.status === "error" ? "!" : "✓✓"}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {/* Typing indicator */}
              {showTypingIndicator && (
                <div className={`${styles.messageRow} ${styles.messageRowBot}`}>
                  <div className={`${styles.bubble} ${styles.bubbleBot}`}>
                    <div className={styles.typingDots}>
                      <span /><span /><span />
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>
        </>
      )}

      {/* ── Quick actions: 1 automatica + le personalizzate dell'utente ──── */}
      <div className={styles.quickSection}>
        <div className={styles.quickHeader}>
          <span>Spese rapide</span>
          <button
            type="button"
            className={styles.quickInfoBtn}
            aria-label="Cosa sono le spese rapide"
            aria-expanded={quickExpensesInfoOpen}
            onClick={() => setQuickExpensesInfoOpen((v) => !v)}
          >
            <Info size={13} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
        {quickExpensesInfoOpen && (
          <p className={styles.quickInfoPopover} role="note">
            Tocca un bottone, inserisci l&apos;importo e il gioco è fatto.
            Il primo bottone è la spesa che fai più spesso, automatico in base allo storico.
            Gli altri li crei tu, con i campi che preferisci.
          </p>
        )}
        <div className={styles.quickRow}>
          {displayedQuickExpenses.map((quickExpense) => {
            const isDragging = quickExpense.id != null && draggingChipId === quickExpense.id;
            return (
              <div
                key={`${quickExpense.source}-${quickExpense.id ?? quickExpense.name}-${quickExpense.account_id}`}
                ref={(el) => {
                  if (quickExpense.id == null) return;
                  if (el) chipRefs.current.set(quickExpense.id, el);
                  else chipRefs.current.delete(quickExpense.id);
                }}
                className={[
                  styles.quickChipWrap,
                  quickEditMode ? styles.quickChipWrapEditing : "",
                  isDragging ? styles.quickChipWrapDragging : "",
                ].filter(Boolean).join(" ")}
                style={isDragging ? { transform: `translate(${dragOffset.x}px, ${dragOffset.y}px)`, zIndex: 5 } : undefined}
                onPointerDown={(e) => handleChipPointerDown(quickExpense, e)}
                onPointerMove={(e) => handleChipPointerMove(quickExpense, e)}
                onPointerUp={() => handleChipPointerUp(quickExpense)}
                onPointerCancel={() => handleChipPointerUp(quickExpense)}
              >
                <button
                  type="button"
                  className={styles.quickChip}
                  tabIndex={quickEditMode ? -1 : 0}
                  onClick={(e) => {
                    // Invio/Spazio da tastiera generano un evento click sintetico
                    // (mai pointerdown/pointerup): senza questo, il bottone è
                    // focusabile ma inutilizzabile senza mouse/touch (WCAG 2.1.1).
                    // `e.detail === 0` è vero SOLO per un click da tastiera — un
                    // tap/click reale (già gestito da onPointerUp sul wrapper, per
                    // distinguere tap da drag) ha detail >= 1: senza questo guard
                    // ogni tap registrerebbe la spesa due volte.
                    if (!quickEditMode && e.detail === 0) handleQuickExpense(quickExpense);
                  }}
                >
                  {quickExpense.label}
                </button>
                {quickEditMode && quickExpense.source === "custom" && quickExpense.id != null && (
                  <button
                    type="button"
                    className={styles.quickChipRemove}
                    aria-label={`Rimuovi il bottone ${quickExpense.label}`}
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation();
                      void deleteShortcut(quickExpense.id!);
                    }}
                  >
                    <X size={11} strokeWidth={2} aria-hidden="true" />
                  </button>
                )}
              </div>
            );
          })}
          {quickEditMode ? (
            <button type="button" className={styles.quickDoneBtn} onClick={exitQuickEditMode}>
              Fatto
            </button>
          ) : (
            <button
              type="button"
              className={styles.quickAddBtn}
              aria-label="Crea un nuovo bottone spesa rapida"
              onClick={() => void openNewShortcutModal()}
            >
              +
            </button>
          )}
        </div>
      </div>

      {/* ── Input Bar ──────────────────────────────────────────────────── */}
      <div className={styles.inputBar}>
        <input
          ref={fileInputRef}
          type="file"
          aria-label="Seleziona un allegato"
          accept="image/*,application/pdf"
          style={{ display: "none" }}
          onChange={handleFileChange}
        />

        <button
          id="chat-attach-btn"
          className={styles.iconBtn}
          onClick={handleImageClick}
          title="Allega scontrino"
          aria-label="Allega immagine"
          disabled={isLoading}
        >
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
          </svg>
        </button>

        <textarea
          ref={inputRef}
          id="chat-input"
          className={styles.chatInput}
          placeholder="Scrivimi quanto e per cosa hai speso, o mandami un audio."
          aria-label="Scrivi un messaggio"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={isLoading}
        />

        {inputText.trim() ? (
          <button
            id="chat-send-btn"
            className={`${styles.iconBtn} ${styles.sendBtn}`}
            onClick={() => void handleSend()}
            disabled={isLoading}
            title="Invia"
            aria-label="Invia messaggio"
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
          </button>
        ) : (
          <button
            id="chat-mic-btn"
            className={`${styles.iconBtn} ${isRecording ? styles.micActive : ""}`}
            onClick={() => void toggleVoice()}
            title={isRecording ? "Ferma registrazione" : "Registra vocale"}
            aria-label="Registra messaggio vocale"
            disabled={isLoading}
          >
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
              <line x1="12" y1="19" x2="12" y2="23"/>
              <line x1="8" y1="23" x2="16" y2="23"/>
            </svg>
          </button>
        )}
      </div>

      {quickExpenseModal && (
        <div className={styles.quickModalOverlay} role="presentation" onClick={closeQuickExpenseModal}>
          <div
            className={styles.quickModalCard}
            role="dialog"
            aria-modal="true"
            aria-label={`Registra spesa rapida: ${quickExpenseModal.expense.label}`}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className={styles.quickModalTitle}>{quickExpenseModal.expense.label}</h3>
            <p className={styles.quickModalMeta}>
              {quickExpenseModal.expense.category || "Senza categoria"}
            </p>

            {quickExpenseModal.step === "amount" ? (
              <>
                <label className={styles.quickModalLabel} htmlFor="quick-expense-amount">Importo</label>
                <input
                  id="quick-expense-amount"
                  type="text"
                  inputMode="decimal"
                  autoFocus
                  className={styles.quickModalAmountInput}
                  placeholder="0,00 €"
                  value={quickExpenseModal.amount}
                  onChange={(e) =>
                    setQuickExpenseModal((prev) => (prev ? { ...prev, amount: e.target.value, error: null } : prev))
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void proceedFromAmountStep();
                  }}
                />
                {quickExpenseModal.error && <p className={styles.quickModalError}>{quickExpenseModal.error}</p>}
                <div className={styles.quickModalActions}>
                  <button type="button" className={styles.quickModalCancelBtn} onClick={closeQuickExpenseModal}>
                    Annulla
                  </button>
                  <button
                    type="button"
                    className={styles.quickModalConfirmBtn}
                    onClick={() => void proceedFromAmountStep()}
                  >
                    Avanti
                  </button>
                </div>
              </>
            ) : (
              <>
                <label className={styles.quickModalLabel}>Conto — tocca per registrare</label>
                {quickExpenseModal.accountsLoading ? (
                  <p className={styles.quickModalMeta}>Carico i conti…</p>
                ) : (
                  <div className={styles.quickModalAccountRow}>
                    {(quickExpenseModal.accounts ?? []).map((acc) => (
                      <button
                        key={acc.id}
                        type="button"
                        className={styles.quickModalAccountBtn}
                        disabled={quickExpenseModal.submitting}
                        onClick={() => void submitQuickExpense(acc.id)}
                      >
                        <Landmark size={15} strokeWidth={1.75} aria-hidden="true" />
                        <span className={styles.quickModalAccountName}>{acc.name}</span>
                      </button>
                    ))}
                  </div>
                )}
                {quickExpenseModal.error && <p className={styles.quickModalError}>{quickExpenseModal.error}</p>}
                <div className={styles.quickModalActions}>
                  <button
                    type="button"
                    className={styles.quickModalCancelBtn}
                    disabled={quickExpenseModal.submitting}
                    onClick={() => setQuickExpenseModal((prev) => (prev ? { ...prev, step: "amount", error: null } : prev))}
                  >
                    Indietro
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {newShortcutModal && (
        <div className={styles.quickModalOverlay} role="presentation" onClick={closeNewShortcutModal}>
          <div
            className={styles.quickModalCard}
            role="dialog"
            aria-modal="true"
            aria-label="Crea un nuovo bottone spesa rapida"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className={styles.quickModalTitle}>Nuovo bottone spesa rapida</h3>

            <label className={styles.quickModalLabel} htmlFor="new-shortcut-name">Nome</label>
            <input
              id="new-shortcut-name"
              type="text"
              autoFocus
              maxLength={60}
              className={styles.quickModalAmountInput}
              placeholder="Es. Palestra abbonamento"
              value={newShortcutModal.name}
              onChange={(e) =>
                setNewShortcutModal((prev) => (prev ? { ...prev, name: e.target.value, error: null } : prev))
              }
            />

            <label className={styles.quickModalLabel} htmlFor="new-shortcut-category">
              Categoria <span className={styles.quickModalOptional}>(facoltativa)</span>
            </label>
            <select
              id="new-shortcut-category"
              className={styles.quickModalSelect}
              value={newShortcutModal.categoryId}
              disabled={newShortcutModal.loading}
              onChange={(e) =>
                setNewShortcutModal((prev) => (prev ? { ...prev, categoryId: e.target.value } : prev))
              }
            >
              <option value="">{newShortcutModal.loading ? "Carico…" : "Nessuna categoria"}</option>
              {(newShortcutModal.categories ?? []).map((cat) => (
                <option key={cat.id} value={cat.id}>{cat.name}</option>
              ))}
            </select>

            <label className={styles.quickModalLabel} htmlFor="new-shortcut-account">
              Conto <span className={styles.quickModalOptional}>(facoltativo — se lo lasci vuoto te lo chiedo al momento)</span>
            </label>
            <select
              id="new-shortcut-account"
              className={styles.quickModalSelect}
              value={newShortcutModal.accountId}
              disabled={newShortcutModal.loading}
              onChange={(e) =>
                setNewShortcutModal((prev) => (prev ? { ...prev, accountId: e.target.value } : prev))
              }
            >
              <option value="">{newShortcutModal.loading ? "Carico…" : "Chiedimelo ogni volta"}</option>
              {(newShortcutModal.accounts ?? []).map((acc) => (
                <option key={acc.id} value={acc.id}>{acc.name}</option>
              ))}
            </select>

            {newShortcutModal.error && <p className={styles.quickModalError}>{newShortcutModal.error}</p>}
            <div className={styles.quickModalActions}>
              <button type="button" className={styles.quickModalCancelBtn} onClick={closeNewShortcutModal}>
                Annulla
              </button>
              <button
                type="button"
                className={styles.quickModalConfirmBtn}
                disabled={newShortcutModal.submitting || !newShortcutModal.name.trim()}
                onClick={() => void submitNewShortcut()}
              >
                {newShortcutModal.submitting ? "Creo…" : "Crea"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
