"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Image from "next/image";
import styles from "./page.module.css";
import MoneoWidget, { type MoneoState } from "@/components/MoneoWidget";
import { getCsrfToken } from "@/lib/csrf";
import {
  trackExpenseTracked,
  trackExpenseTrackingFailed,
  trackFirstExpenseTracked,
  type InputMethod,
} from "@/lib/analytics";

// ─── Types ────────────────────────────────────────────────────────────────────

type MessageRole = "user" | "bot";
type MessageStatus = "sending" | "sent" | "error";

interface ParsedData {
  type?: string;
  amount?: number | null;
  category?: string | null;
  income_type?: string | null;
  name?: string | null;
  date?: string;
  // report metadata
  report_type?: string;
  share_token?: string;
}

interface Message {
  id: string;
  role: MessageRole;
  text: string;
  timestamp: Date;
  status?: MessageStatus;
  parsed?: ParsedData;
  awaitingConfirm?: boolean;   // true = mostra bottoni ✅/❌
  transcription?: string;      // testo trascritto dal vocale
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

// ─── Component ────────────────────────────────────────────────────────────────

export default function ChatPage() {
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

  // Whether to show the welcome screen (no user/bot messages yet except welcome)
  const hasConversation = messages.length > 0 && historyLoaded;
  const onlyWelcome = hasConversation && messages.length === 1 && messages[0].id === "welcome";
  const showWelcome = !hasConversation || onlyWelcome;

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

  // ── Handle API response (parse-only) ─────────────────────────────────────

  const handleParseResponse = useCallback(
    (data: {
      ok: boolean;
      type?: string;
      parsed?: ParsedData;
      reply?: string;
      saved?: boolean;
      transcription?: string;
    }, userMsgId: string) => {
      setShowTypingIndicator(false);

      const botMsg: Message = {
        id: `bot-${Date.now()}`,
        role: "bot",
        text: data.reply || "Non ho capito. Riprova con una descrizione più chiara.",
        timestamp: new Date(),
        status: "sent",
        parsed: data.parsed,
        // Mostra conferma se il server ha parsato correttamente ma non ha ancora salvato
        awaitingConfirm: data.ok && data.type !== "unknown" && data.type !== "error" && !data.saved,
        transcription: data.transcription,
      };

      setMessages((prev) => [
        ...prev.map((m) => (m.id === userMsgId ? { ...m, status: "sent" as MessageStatus } : m)),
        botMsg,
      ]);
    },
    []
  );

  // ── Confirm / Cancel ──────────────────────────────────────────────────────

  const handleConfirm = useCallback(async (botMsgId: string, parsed: ParsedData) => {
    const inputMethod = pendingInputMethodRef.current;
    setMessages((prev) =>
      prev.map((m) => (m.id === botMsgId ? { ...m, awaitingConfirm: false } : m))
    );
    setShowTypingIndicator(true);

    try {
      const res = await fetch("/api/chat/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await buildHeaders()) },
        credentials: "same-origin",
        body: JSON.stringify({ parsed, input_method: inputMethod }),
      });
      const data = await res.json();
      setShowTypingIndicator(false);

      if (data.saved) {
        trackExpenseTracked(inputMethod);
        if (data.is_first_expense) trackFirstExpenseTracked(inputMethod);
      } else {
        trackExpenseTrackingFailed("save_error", inputMethod);
      }

      const confirmMsg: Message = {
        id: `confirm-${Date.now()}`,
        role: "bot",
        text: data.reply || "✅ Registrato!",
        timestamp: new Date(),
        status: "sent",
        parsed: data.saved ? parsed : undefined,
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
    }
  }, []);

  const handleCancel = useCallback((botMsgId: string) => {
    trackExpenseTrackingFailed("user_cancelled", pendingInputMethodRef.current);
    setMessages((prev) =>
      prev.map((m) =>
        m.id === botMsgId
          ? { ...m, awaitingConfirm: false, text: "❌ Operazione annullata." }
          : m
      )
    );
  }, []);

  // ── Send text message ─────────────────────────────────────────────────────

  const sendMessage = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isLoading) return;

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
  }, [isLoading, handleParseResponse]);

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
          <div className={styles.messagesArea}>
            <div className={styles.messagesInner}>
              {messages.map((msg) => (
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

                    {/* Confirm buttons */}
                    {msg.awaitingConfirm && msg.parsed && (
                      <div className={styles.confirmRow}>
                        <button
                          className={`${styles.confirmBtn} ${styles.confirmBtnYes}`}
                          onClick={() => handleConfirm(msg.id, msg.parsed!)}
                        >
                          ✅ Conferma
                        </button>
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
