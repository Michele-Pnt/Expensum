"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import styles from "./page.module.css";
import MoneoWidget, { type MoneoState } from "@/components/MoneoWidget";
import { getCsrfToken } from "@/lib/csrf";
import { useTour } from "@/context/TourContext";
import {
  trackExpenseTracked,
  trackExpenseTrackingFailed,
  trackFirstExpenseTracked,
  type InputMethod,
} from "@/lib/analytics";

// ─── Types ────────────────────────────────────────────────────────────────────

type MessageRole = "user" | "bot";
type MessageStatus = "sending" | "sent" | "error";

interface Account {
  id: string;
  name: string;
  current_balance?: number;
}

interface ParsedData {
  type?: string;
  amount?: number | null;
  category?: string | null;
  income_type?: string | null;
  name?: string | null;
  date?: string;
  accounts?: Account[];
  categories?: string[];
  resolved_from_account_id?: string | null;
  resolved_from_account_name?: string | null;
  resolved_to_account_id?: string | null;
  resolved_to_account_name?: string | null;
  // report metadata
  report_type?: string;
  share_token?: string;
}

// Item come restituito da /api/chat/message|voice|photo dentro "transactions"
interface ChatTransaction {
  type: string;
  reply: string;
  parsed: ParsedData;
  awaiting_confirm?: boolean;
  needs_amount?: boolean;
  needs_second_account?: boolean;
  needs_account_pick?: "from" | "to";
}

type AccountPickMode = "single" | "from" | "to";

interface Message {
  id: string;
  role: MessageRole;
  text: string;
  timestamp: Date;
  status?: MessageStatus;
  parsed?: ParsedData;
  awaitingConfirm?: boolean;   // true = mostra bottoni ✅/❌
  awaitingCategoryPick?: boolean; // true = mostra il picker categorie al posto del riepilogo
  awaitingAccountPick?: AccountPickMode; // true = mostra il picker conti al posto del riepilogo
  awaitingAmount?: boolean;    // true = in attesa che l'utente scriva l'importo mancante
  pickedFromAccountId?: string; // conto origine già scelto (transfer), per escluderlo dal picker "to"
  transcription?: string;      // testo trascritto dal vocale
  noAccountAction?: boolean;   // true = mostra bottone "Vai ai Conti" (nessun conto configurato)
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getTelegramInitData(): string {
  if (typeof window === "undefined") return "";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (window as any).Telegram?.WebApp?.initData ?? "";
}

async function buildHeaders(): Promise<HeadersInit> {
  const init = getTelegramInitData();
  const csrfToken = await getCsrfToken();
  const headers: Record<string, string> = { "X-CSRFToken": csrfToken };
  if (init) headers["X-Telegram-Init-Data"] = init;
  return headers;
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

function parseMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/_(.+?)_/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

// ─── Riepilogo / step successivo (client-side, dopo che l'importo mancante è
// stato completato dall'utente) — rispecchia _build_parse_reply e
// _build_transaction_payload lato server, così non serve un altro round-trip. ──

function buildConfirmText(parsed: ParsedData): string {
  const amountStr = parsed.amount != null ? `€${Number(parsed.amount).toFixed(2)}` : "importo non specificato";
  if (parsed.type === "expense") {
    const cat = parsed.category || "Altro";
    const name = parsed.name || "Spesa";
    return `Ho interpretato **${name}** di ${amountStr} nella categoria _${cat}_. Confermi?`;
  }
  if (parsed.type === "transfer") {
    const from = parsed.resolved_from_account_name || "—";
    const to = parsed.resolved_to_account_name || "—";
    const name = parsed.name || "Trasferimento";
    return `📝 Nuovo trasferimento riconosciuto:\n\n💰 Importo: **${amountStr}**\n🏦 Da: **${from}**\n🏦 A: **${to}**\n📝 Descrizione: **${name}**\n\nConfermi?`;
  }
  const incomeType = parsed.income_type || "Entrata";
  const name = parsed.name || "Entrata";
  return `Ho interpretato **${name}** (${incomeType}) di ${amountStr}. Confermi?`;
}

interface NextStep {
  awaitingConfirm: boolean;
  awaitingAccountPick?: AccountPickMode;
  text: string;
}

function nextStepAfterAmount(parsed: ParsedData): NextStep {
  if (parsed.type === "transfer") {
    if ((parsed.accounts?.length || 0) < 2) {
      return {
        awaitingConfirm: false,
        text: "🏦 Ti servono almeno due conti per fare un trasferimento.\n\nAggiungine uno nella tab \"Conti\" del tuo spazio.",
      };
    }
    if (!parsed.resolved_from_account_id) {
      return { awaitingConfirm: false, awaitingAccountPick: "from", text: "🏦 Da quale conto vuoi spostare i soldi?" };
    }
    if (!parsed.resolved_to_account_id) {
      return { awaitingConfirm: false, awaitingAccountPick: "to", text: "🏦 Su quale conto vuoi spostare i soldi?" };
    }
  }
  return { awaitingConfirm: true, text: buildConfirmText(parsed) };
}

// Stesso fallback regex di bot.py:1667-1675: normalizza e ricava il primo numero.
function parseAmountFallback(raw: string): number | null {
  const cleaned = raw.toLowerCase().replace(/\s/g, "").replace(/€/g, "").replace(/euro/g, "").replace(",", ".");
  const match = cleaned.match(/-?\d+(?:\.\d+)?/);
  return match ? parseFloat(match[0]) : null;
}

function historyMsgToMessage(h: {
  id: string | number;
  role: string;
  text: string;
  created_at?: string;
  metadata?: ParsedData;
}): Message {
  return {
    id: `hist-${h.id}`,
    role: (h.role === "user" ? "user" : "bot") as MessageRole,
    text: h.text,
    timestamp: h.created_at ? new Date(h.created_at) : new Date(0),
    status: "sent",
    parsed: h.metadata,
  };
}

// ─── Suggestions ──────────────────────────────────────────────────────────────

const SUGGESTIONS = [
  "Ho speso 24€ per il sushi",
  "Stipendio 1500€",
  "Netflix 12,99€",
  "Affitto 450€",
];

// ─── Tour demo exchange ───────────────────────────────────────────────────────

const TOUR_DEMO_MESSAGES: Message[] = [
  {
    id: "tour-demo-user",
    role: "user",
    text: "Ho speso 24€ per il sushi",
    timestamp: new Date(Date.now() - 30000),
    status: "sent",
  },
  {
    id: "tour-demo-bot",
    role: "bot",
    text: "Ho capito! Ecco cosa ho rilevato:\n\n📝 **Sushi** · **€24.00**\n📂 _Ristoranti & Fast Food_ · 📅 _Oggi_\n\nConfermi l'inserimento?",
    timestamp: new Date(Date.now() - 28000),
    parsed: { type: "expense", amount: 24, category: "Ristoranti & Fast Food", name: "Sushi", date: "oggi" },
    awaitingConfirm: true,
  },
];

// ─── Component ────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const { isActive: isTourActive, currentStep: tourStep } = useTour();
  const isTourChatStep = isTourActive && tourStep === 1;
  const router = useRouter();

  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [showTypingIndicator, setShowTypingIndicator] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [moneoState, setMoneoState] = useState<MoneoState>("idle");


  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const pendingInputMethodRef = useRef<InputMethod>("text");

  // Coda locale delle transazioni "sequenziali" (importo mancante o conto trasferimento
  // da chiedere) rilevate in un messaggio multi-transazione: presentate una alla volta,
  // mirror di expense_queue/waiting_for_amount in bot.py.
  const sequentialQueueRef = useRef<ChatTransaction[]>([]);
  const activeSequentialIdRef = useRef<string | null>(null);
  // "amount" = il prossimo testo libero digitato va interpretato come importo
  // (mirror di waiting_for_amount in bot.py); "account" = si aspetta un click sui bottoni.
  const activeSequentialKindRef = useRef<"amount" | "account" | null>(null);

  // Whether to show the welcome screen (no user/bot messages yet except welcome)
  const hasConversation = messages.length > 0 && historyLoaded;
  const onlyWelcome = hasConversation && messages.length === 1 && messages[0].id === "welcome";
  const showWelcome = !isTourChatStep && (!hasConversation || onlyWelcome);
  const displayMessages = isTourChatStep ? TOUR_DEMO_MESSAGES : messages;

  // ── Init: carica history dal server ───────────────────────────────────────

  useEffect(() => {
    const greeting: Message = {
      id: "welcome",
      role: "bot",
      text: "Ciao! Le mie risposte sono generate automaticamente con Mistral AI europea: posso sbagliare, verifica sempre i dati finanziari importanti.\n\nDimmi una spesa o un'entrata e la registro subito. Prova con:\n• _«Ho speso 24€ per il sushi»_\n• _«Ho ricevuto lo stipendio 1500€»_\n• _«Netflix 12,99»_",
      timestamp: new Date(),
      status: "sent",
    };

    buildHeaders()
      .then((headers) => fetch("/api/chat/history", { credentials: "same-origin", headers }))
      .then((r) => r.json())
      .then((data) => {
        const histMsgs: Message[] = (data.messages || []).map(historyMsgToMessage);
        setMessages([greeting, ...histMsgs]);
        setHistoryLoaded(true);
      })
      .catch(() => {
        setMessages([greeting]);
        setHistoryLoaded(true);
      });
  }, []);

  // ── Moneo state derivation ────────────────────────────────────────────────

  useEffect(() => {
    if (isRecording) {
      setMoneoState("recording");
    } else if (showTypingIndicator) {
      setMoneoState("thinking");
    } else {
      setMoneoState((prev) => (prev === "happy" || prev === "error" ? prev : "idle"));
    }
  }, [isRecording, showTypingIndicator]);

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

  // ── Coda sequenziale (importo mancante / conto trasferimento da chiedere) ──

  const presentNextSequential = useCallback(() => {
    if (activeSequentialIdRef.current) return; // uno alla volta, come expense_queue in bot.py
    const next = sequentialQueueRef.current.shift();
    if (!next) return;
    const msgId = `bot-seq-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    activeSequentialIdRef.current = msgId;
    activeSequentialKindRef.current = next.needs_amount ? "amount" : "account";
    setMessages((prev) => [
      ...prev,
      {
        id: msgId,
        role: "bot",
        text: next.reply,
        timestamp: new Date(),
        status: "sent",
        parsed: next.parsed,
        awaitingAmount: !!next.needs_amount,
        awaitingAccountPick: next.needs_account_pick,
      },
    ]);
  }, []);

  // ── Handle API response (parse-only, multi-transazione) ──────────────────

  const handleParseResponse = useCallback(
    (data: {
      ok: boolean;
      type?: string;
      transactions?: ChatTransaction[];
      reply?: string;
      saved?: boolean;
      transcription?: string;
    }, userMsgId: string) => {
      setShowTypingIndicator(false);
      setMessages((prev) => prev.map((m) => (m.id === userMsgId ? { ...m, status: "sent" as MessageStatus } : m)));

      // Errore, nessuna transazione riconosciuta, o nessun conto configurato: un'unica bubble.
      if (!data.ok || data.type === "error" || data.type === "unknown" || data.type === "no_account") {
        setMessages((prev) => [
          ...prev,
          {
            id: `bot-${Date.now()}`,
            role: "bot",
            text: data.reply || "Non ho capito. Riprova con una descrizione più chiara.",
            timestamp: new Date(),
            status: "sent",
            transcription: data.transcription,
            noAccountAction: data.type === "no_account",
          },
        ]);
        return;
      }

      const transactions = data.transactions || [];
      const immediate = transactions.filter((tx) => tx.awaiting_confirm || tx.needs_second_account);
      const sequential = transactions.filter((tx) => !tx.awaiting_confirm && !tx.needs_second_account);

      // Le transazioni "pronte" (importo noto, conti risolti o già bloccate per <2 conti)
      // vengono mostrate tutte subito come bubble indipendenti — bot.py:1769-1791.
      if (immediate.length > 0) {
        setMessages((prev) => [
          ...prev,
          ...immediate.map((tx, i) => ({
            id: `bot-${Date.now()}-${i}`,
            role: "bot" as MessageRole,
            text: tx.reply,
            timestamp: new Date(),
            status: "sent" as MessageStatus,
            parsed: tx.parsed,
            awaitingConfirm: !!tx.awaiting_confirm,
            transcription: data.transcription,
          })),
        ]);
      }

      // Quelle che richiedono un'ulteriore domanda (importo, conto) vanno in coda
      // e si presentano una alla volta — expense_queue in bot.py.
      sequentialQueueRef.current.push(...sequential);
      presentNextSequential();
    },
    [presentNextSequential]
  );

  // ── Salvataggio effettivo (dopo che conto/i sono stati scelti) ───────────

  const saveTransaction = useCallback(async (
    botMsgId: string,
    parsed: ParsedData,
    opts: { account_id?: string; from_account_id?: string; to_account_id?: string }
  ) => {
    const inputMethod = pendingInputMethodRef.current;
    setMessages((prev) =>
      prev.map((m) => (m.id === botMsgId ? { ...m, awaitingConfirm: false, awaitingAccountPick: undefined, awaitingCategoryPick: false } : m))
    );
    setShowTypingIndicator(true);

    if (activeSequentialIdRef.current === botMsgId) {
      activeSequentialIdRef.current = null;
      activeSequentialKindRef.current = null;
    }

    try {
      const res = await fetch("/api/chat/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await buildHeaders()) },
        credentials: "same-origin",
        body: JSON.stringify({ parsed, input_method: inputMethod, ...opts }),
      });
      const data = await res.json();
      setShowTypingIndicator(false);

      if (data.saved) {
        trackExpenseTracked(inputMethod);
        if (data.is_first_expense) trackFirstExpenseTracked(inputMethod);
      } else {
        trackExpenseTrackingFailed(data.error === "no_account" ? "no_account" : "save_error", inputMethod);
      }

      const confirmMsg: Message = {
        id: `confirm-${Date.now()}`,
        role: "bot",
        text: data.reply || "✅ Registrato!",
        timestamp: new Date(),
        status: "sent",
        parsed: data.saved ? parsed : undefined,
        noAccountAction: data.error === "no_account",
      };
      setMessages((prev) => [...prev, confirmMsg]);
      setMoneoState("happy");
      setTimeout(() => setMoneoState((prev) => prev === "happy" ? "idle" : prev), 3000);
    } catch {
      setShowTypingIndicator(false);
      setMessages((prev) => [
        ...prev,
        {
          id: `err-confirm-${Date.now()}`,
          role: "bot",
          text: "⚠️ Errore durante il salvataggio. Riprova.",
          timestamp: new Date(),
          status: "sent",
        },
      ]);
    } finally {
      presentNextSequential();
    }
  }, [presentNextSequential]);

  // ── Confirm / Cancel ──────────────────────────────────────────────────────

  const handleConfirm = useCallback((botMsgId: string, parsed: ParsedData) => {
    if (parsed.type === "transfer") {
      // Qui arriviamo solo quando entrambi i conti sono già risolti dagli hint LLM
      // (altrimenti la transazione sarebbe stata messa in coda con awaitingAccountPick).
      saveTransaction(botMsgId, parsed, {
        from_account_id: parsed.resolved_from_account_id ?? undefined,
        to_account_id: parsed.resolved_to_account_id ?? undefined,
      });
      return;
    }
    // Mai skip automatico: si chiede sempre il conto, anche con un solo conto — bot.py:2472-2508.
    setMessages((prev) =>
      prev.map((m) => (m.id === botMsgId ? { ...m, awaitingConfirm: false, awaitingAccountPick: "single" } : m))
    );
  }, [saveTransaction]);

  const handleCancel = useCallback((botMsgId: string) => {
    trackExpenseTrackingFailed("user_cancelled", pendingInputMethodRef.current);
    setMessages((prev) =>
      prev.map((m) =>
        m.id === botMsgId
          ? { ...m, awaitingConfirm: false, awaitingAccountPick: undefined, awaitingCategoryPick: false, awaitingAmount: false, text: "❌ Operazione annullata." }
          : m
      )
    );
    if (activeSequentialIdRef.current === botMsgId) {
      activeSequentialIdRef.current = null;
      activeSequentialKindRef.current = null;
      presentNextSequential();
    }
  }, [presentNextSequential]);

  // ── Cambio conto (single/from/to) ─────────────────────────────────────────

  const handleAccountPick = useCallback((botMsgId: string, parsed: ParsedData, mode: AccountPickMode, account: Account) => {
    if (mode === "single") {
      saveTransaction(botMsgId, parsed, { account_id: account.id });
      return;
    }
    if (mode === "from") {
      // Passa allo step "conto destinazione", escludendo quello appena scelto.
      setMessages((prev) =>
        prev.map((m) =>
          m.id === botMsgId
            ? {
                ...m,
                parsed: { ...parsed, resolved_from_account_id: account.id, resolved_from_account_name: account.name },
                awaitingAccountPick: "to",
              }
            : m
        )
      );
      return;
    }
    // mode === "to"
    saveTransaction(botMsgId, { ...parsed, resolved_to_account_id: account.id, resolved_to_account_name: account.name }, {
      from_account_id: parsed.resolved_from_account_id ?? undefined,
      to_account_id: account.id,
    });
  }, [saveTransaction]);

  // ── Cambio categoria rapido (solo spese) ──────────────────────────────────

  const handleCategoryEditOpen = useCallback((botMsgId: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === botMsgId ? { ...m, awaitingConfirm: false, awaitingCategoryPick: true } : m))
    );
  }, []);

  const handleCategoryEditBack = useCallback((botMsgId: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === botMsgId ? { ...m, awaitingCategoryPick: false, awaitingConfirm: true } : m))
    );
  }, []);

  const handleCategoryPick = useCallback((botMsgId: string, category: string) => {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== botMsgId || !m.parsed) return m;
        const parsed = { ...m.parsed, category };
        return { ...m, parsed, awaitingCategoryPick: false, awaitingConfirm: true, text: buildConfirmText(parsed) };
      })
    );
  }, []);

  // ── Risposta a "quanto vuoi trasferire/spendere?" (importo mancante) ─────

  const answerPendingAmount = useCallback((botMsgId: string, text: string) => {
    const amount = parseAmountFallback(text);
    const userMsg: Message = { id: `user-${Date.now()}`, role: "user", text, timestamp: new Date(), status: "sent" };
    setInputText("");

    if (amount === null) {
      setMessages((prev) => [
        ...prev,
        userMsg,
        {
          id: `err-amount-${Date.now()}`,
          role: "bot",
          text: "📝 Non ho capito l'importo. Prova a ridirmelo, scrivendo solo il numero (es. 20 o 20,50).",
          timestamp: new Date(),
          status: "sent",
        },
      ]);
      return;
    }

    let terminal = false;
    setMessages((prev) => [
      ...prev.map((m) => {
        if (m.id !== botMsgId || !m.parsed) return m;
        const parsed = { ...m.parsed, amount };
        const step = nextStepAfterAmount(parsed);
        terminal = !step.awaitingConfirm && !step.awaitingAccountPick;
        return {
          ...m,
          parsed,
          awaitingAmount: false,
          awaitingConfirm: step.awaitingConfirm,
          awaitingAccountPick: step.awaitingAccountPick,
          text: step.text,
        };
      }),
      userMsg,
    ]);

    if (terminal) {
      // Blocco terminale (es. servono almeno 2 conti per il trasferimento): nessuna
      // ulteriore interazione possibile, libera lo slot e passa alla prossima in coda.
      activeSequentialIdRef.current = null;
      activeSequentialKindRef.current = null;
      presentNextSequential();
    } else {
      activeSequentialKindRef.current = "account"; // il prossimo step si conferma coi bottoni, non più a testo
    }
  }, [presentNextSequential]);

  // ── Send text message ─────────────────────────────────────────────────────

  const sendMessage = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isLoading) return;

    // Una transazione in coda sta aspettando l'importo mancante: il testo libero
    // viene interpretato come importo invece di rilanciare un nuovo parsing NLP
    // (mirror di waiting_for_amount in bot.py:1659-1694).
    if (activeSequentialIdRef.current && activeSequentialKindRef.current === "amount") {
      answerPendingAmount(activeSequentialIdRef.current, trimmed);
      return;
    }

    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      text: trimmed,
      timestamp: new Date(),
      status: "sending",
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputText("");
    setIsLoading(true);
    setShowTypingIndicator(true);
    pendingInputMethodRef.current = "text";

    try {
      const res = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await buildHeaders()) },
        credentials: "same-origin",
        body: JSON.stringify({ text: trimmed }),
      });
      const data = await res.json();
      handleParseResponse(data, userMsg.id);
    } catch {
      setMessages((prev) =>
        prev.map((m) => (m.id === userMsg.id ? { ...m, status: "error" } : m))
      );
      setShowTypingIndicator(false);
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "bot",
          text: "⚠️ Errore di rete. Controlla la connessione e riprova.",
          timestamp: new Date(),
          status: "sent",
        },
      ]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  }, [isLoading, handleParseResponse, answerPendingAmount]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputText);
    }
  };

  // ── Voice recording ───────────────────────────────────────────────────────

  const handleMicClick = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });

        const userMsg: Message = {
          id: `user-voice-${Date.now()}`,
          role: "user",
          text: "🎤 Messaggio vocale inviato",
          timestamp: new Date(),
          status: "sending",
        };
        setMessages((prev) => [...prev, userMsg]);
        setIsLoading(true);
        setShowTypingIndicator(true);

        try {
          pendingInputMethodRef.current = "voice";
          const formData = new FormData();
          formData.append("audio", blob, "voice.webm");
          const res = await fetch("/api/chat/voice", {
            method: "POST",
            headers: await buildHeaders(),
            credentials: "same-origin",
            body: formData,
          });
          const data = await res.json();

          // Aggiorna testo messaggio utente con trascrizione
          if (data.transcription) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === userMsg.id
                  ? { ...m, text: `🎤 ${data.transcription}`, status: "sent" }
                  : m
              )
            );
          } else {
            setMessages((prev) =>
              prev.map((m) => (m.id === userMsg.id ? { ...m, status: "sent" } : m))
            );
          }
          handleParseResponse(data, userMsg.id);
        } catch {
          setMessages((prev) =>
            prev.map((m) => (m.id === userMsg.id ? { ...m, status: "error" } : m))
          );
          setShowTypingIndicator(false);
          setMessages((prev) => [
            ...prev,
            {
              id: `err-voice-${Date.now()}`,
              role: "bot",
              text: "⚠️ Errore durante la trascrizione audio. Riprova o scrivi il messaggio.",
              timestamp: new Date(),
              status: "sent",
            },
          ]);
        } finally {
          setIsLoading(false);
        }
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
    } catch {
      alert("Non ho potuto accedere al microfono. Verifica i permessi del browser.");
    }
  };

  // ── Image / Receipt ───────────────────────────────────────────────────────

  const handleImageClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    const isImage = file.type.startsWith("image/");
    const userMsg: Message = {
      id: `user-img-${Date.now()}`,
      role: "user",
      text: isImage ? "📷 Foto scontrino inviata" : `📎 File inviato: ${file.name}`,
      timestamp: new Date(),
      status: "sending",
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);
    setShowTypingIndicator(true);

    try {
      pendingInputMethodRef.current = "photo";
      const formData = new FormData();
      formData.append("image", file);
      const res = await fetch("/api/chat/photo", {
        method: "POST",
        headers: await buildHeaders(),
        credentials: "same-origin",
        body: formData,
      });
      const data = await res.json();
      setMessages((prev) =>
        prev.map((m) => (m.id === userMsg.id ? { ...m, status: "sent" } : m))
      );
      handleParseResponse(data, userMsg.id);
    } catch {
      setMessages((prev) =>
        prev.map((m) => (m.id === userMsg.id ? { ...m, status: "error" } : m))
      );
      setShowTypingIndicator(false);
      setMessages((prev) => [
        ...prev,
        {
          id: `err-img-${Date.now()}`,
          role: "bot",
          text: "⚠️ Errore durante l'analisi dell'immagine. Riprova.",
          timestamp: new Date(),
          status: "sent",
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={styles.chatRoot}>
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

          <h1 className={styles.welcomeTitle}>
            Come Posso Aiutarti Oggi?
          </h1>

          <p className={styles.welcomeSubtitle}>
            Dimmi una spesa o un&apos;entrata e la registro subito
          </p>

          <div className={styles.suggestionsRow}>
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                className={styles.suggestionChip}
                onClick={() => sendMessage(s)}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          {/* ── Messages ───────────────────────────────────────────────── */}
          <div className={styles.messagesArea} data-tour="chat-messages">
            <div className={styles.messagesInner}>
              {displayMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`${styles.messageRow} ${msg.role === "user" ? styles.messageRowUser : styles.messageRowBot}`}
                >
                  <div className={`${styles.bubble} ${msg.role === "user" ? styles.bubbleUser : styles.bubbleBot}`}>
                    <p
                      className={styles.bubbleText}
                      dangerouslySetInnerHTML={{
                        __html:
                          (msg.role === "bot" ? "🤖 Moneo (AI): " : "") +
                          parseMarkdown(msg.text).replace(/\n/g, "<br/>"),
                      }}
                    />

                    {/* Parsed transaction pill */}
                    {msg.parsed?.amount != null && (
                      <div className={styles.parsedPill}>
                        <span className={msg.parsed.type === "income" ? styles.pillIncome : styles.pillExpense}>
                          {msg.parsed.type === "income" ? "+" : "-"}€{Number(msg.parsed.amount).toFixed(2)}
                        </span>
                        {msg.parsed.category && (
                          <span className={styles.pillCategory}>{msg.parsed.category}</span>
                        )}
                        {msg.parsed.income_type && !msg.parsed.category && (
                          <span className={styles.pillCategory}>{msg.parsed.income_type}</span>
                        )}
                      </div>
                    )}

                    {/* Report generato: link diretto alla tab Report */}
                    {msg.parsed?.share_token && (
                      <div className={styles.confirmRow}>
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnYes}`}
                          onClick={() => router.push(`/reports/${msg.parsed!.share_token}`)}
                        >
                          📊 Vedi il report
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
                          🏦 Vai ai Conti
                        </button>
                      </div>
                    )}

                    {/* Confirm buttons (+ cambio categoria rapido per le spese) */}
                    {msg.awaitingConfirm && msg.parsed && (
                      <>
                        {msg.parsed.type === "expense" && (
                          <div className={styles.confirmRow}>
                            <button
                              className={`${styles.confirmBtn} ${styles.confirmBtnNo}`}
                              onClick={() => !isTourChatStep && handleCategoryEditOpen(msg.id)}
                            >
                              ✏️ Cambia categoria
                            </button>
                          </div>
                        )}
                        <div className={styles.confirmRow}>
                          <button
                            className={`${styles.confirmBtn} ${styles.confirmBtnYes}`}
                            onClick={() => !isTourChatStep && handleConfirm(msg.id, msg.parsed!)}
                          >
                            ✅ Conferma
                          </button>
                          <button
                            className={`${styles.confirmBtn} ${styles.confirmBtnNo}`}
                            onClick={() => !isTourChatStep && handleCancel(msg.id)}
                          >
                            ❌ Annulla
                          </button>
                        </div>
                      </>
                    )}

                    {/* Picker categoria (cambio rapido) */}
                    {msg.awaitingCategoryPick && msg.parsed?.categories && (
                      <div className={styles.pickerCol}>
                        {msg.parsed.categories.map((cat) => (
                          <button
                            key={cat}
                            className={`${styles.confirmBtn} ${styles.pickerBtn}`}
                            onClick={() => handleCategoryPick(msg.id, cat)}
                          >
                            📂 {cat}
                          </button>
                        ))}
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnNo}`}
                          onClick={() => handleCategoryEditBack(msg.id)}
                        >
                          ↩️ Indietro
                        </button>
                      </div>
                    )}

                    {/* Picker conto (single = spesa/entrata, from/to = trasferimento) */}
                    {msg.awaitingAccountPick && msg.parsed?.accounts && (
                      <div className={styles.pickerCol}>
                        {msg.parsed.accounts
                          .filter((acc) =>
                            msg.awaitingAccountPick !== "to" || acc.id !== msg.parsed?.resolved_from_account_id
                          )
                          .map((acc) => (
                            <button
                              key={acc.id}
                              className={`${styles.confirmBtn} ${styles.pickerBtn}`}
                              onClick={() => handleAccountPick(msg.id, msg.parsed!, msg.awaitingAccountPick!, acc)}
                            >
                              🏦 {acc.name}
                              {acc.current_balance != null ? ` (€${Number(acc.current_balance).toFixed(2)})` : ""}
                            </button>
                          ))}
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnNo}`}
                          onClick={() => handleCancel(msg.id)}
                        >
                          ❌ Annulla
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

      {/* ── Moneo Widget ───────────────────────────────────────────────── */}

      {/* ── Moneo Widget ───────────────────────────────────────────────── */}
      <MoneoWidget state={moneoState} />

      {/* ── Input Bar ──────────────────────────────────────────────────── */}
      <div className={styles.inputBar}>
        <input
          ref={fileInputRef}
          type="file"
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
          data-tour="chat-input"
          className={styles.chatInput}
          placeholder="Scrivi un messaggio…"
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
            onClick={() => sendMessage(inputText)}
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
            onClick={handleMicClick}
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
    </div>
  );
}
