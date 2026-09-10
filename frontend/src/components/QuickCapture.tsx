"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Dialog, Drawer } from "@mui/material";
import {
  Check,
  FolderOpen,
  Landmark,
  MessageCircle,
  Mic,
  Paperclip,
  Pencil,
  Send,
  Undo2,
  X,
} from "lucide-react";

import { SafeMarkdown } from "@/components/SafeMarkdown";
import { selectableAccounts } from "@/features/expense-capture/model";
import {
  hasCompletedSave,
  hasPendingCapture,
  isAwaitingUser,
  isNonFinancialReply,
} from "@/features/expense-capture/composerState";
import { useExpenseCaptureFlow } from "@/features/expense-capture/useExpenseCaptureFlow";
import type { CaptureMessage } from "@/features/expense-capture/types";
import styles from "./QuickCapture.module.css";

const TITLE_ID = "quick-capture-title";

export type QuickCaptureProps = {
  open: boolean;
  onClose(): void;
  onOpenManage(): void;
  isMobile: boolean;
};

/**
 * Composer globale: registra un movimento da qualunque pagina riusando lo stesso
 * controller della Chat — stesse chiamate API, stessa conferma esplicita, nessuna
 * scorciatoia che salti conto, tracking o gamification.
 */
export default function QuickCapture({ open, onClose, onOpenManage, isMobile }: QuickCaptureProps) {
  const router = useRouter();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const keepEditingRef = useRef<HTMLButtonElement>(null);
  const [confirmExit, setConfirmExit] = useState(false);

  const {
    messages,
    inputText,
    isLoading,
    isRecording,
    showTypingIndicator,
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
    reset,
  } = useExpenseCaptureFlow({ loadHistory: false });

  const awaitingUser = isAwaitingUser(messages);
  const lastBotMessage = [...messages].reverse().find((m) => m.role === "bot");
  const hasSaved = hasCompletedSave(messages, awaitingUser, isLoading);
  // Risposta non finanziaria (comando, chiarimento): nel composer non si esegue,
  // si mostra e si rimanda alla Chat, che è la superficie giusta per proseguire.
  const showChatShortcut = isNonFinancialReply({ lastBotMessage, awaitingUser, hasSaved, isLoading });

  // Con testo digitato, un upload in corso o un passaggio aperto, uscire
  // perderebbe il movimento: si chiede conferma. Un composer vuoto si chiude subito.
  const hasPendingWork = hasPendingCapture({ inputText, isLoading, isRecording, awaitingUser });

  useEffect(() => {
    if (!open) return;
    // Focus iniziale sul campo di testo: il composer si usa scrivendo.
    // (`confirmExit` viene azzerato da chi chiude, non qui: un setState sincrono
    // dentro un effect innescherebbe render a cascata.)
    const timer = window.setTimeout(() => inputRef.current?.focus(), 80);
    return () => window.clearTimeout(timer);
  }, [open]);

  // Il focus segue la conferma d'uscita: l'azione meno distruttiva è quella attiva.
  useEffect(() => {
    if (confirmExit) keepEditingRef.current?.focus();
  }, [confirmExit]);

  const recordAnother = useCallback(() => {
    reset();
    inputRef.current?.focus();
  }, [reset]);

  const closeAndReset = useCallback(() => {
    setConfirmExit(false);
    reset();
    onClose();
  }, [onClose, reset]);

  const requestClose = useCallback(() => {
    if (hasPendingWork) {
      setConfirmExit(true);
      return;
    }
    closeAndReset();
  }, [closeAndReset, hasPendingWork]);

  const goToChat = useCallback(() => {
    closeAndReset();
    router.push("/chat");
  }, [closeAndReset, router]);

  const openManage = useCallback(() => {
    closeAndReset();
    onOpenManage();
  }, [closeAndReset, onOpenManage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendText();
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    await sendPhoto(file);
  };

  const renderMessage = (msg: CaptureMessage) => (
    <div
      key={msg.id}
      className={msg.role === "user" ? `${styles.bubble} ${styles.bubbleUser}` : styles.bubble}
    >
      <SafeMarkdown text={msg.text} />

      {msg.parsed?.amount != null && (
        <span className={styles.pill}>
          {msg.parsed.type === "income" ? "+" : "-"}€{Number(msg.parsed.amount).toFixed(2)}
          {msg.parsed.category ? ` · ${msg.parsed.category}` : ""}
        </span>
      )}

      {msg.awaitingConfirm && msg.parsed && (
        <div className={styles.actionRow}>
          <button type="button" className={`${styles.action} ${styles.actionPrimary}`} onClick={() => void confirm(msg.id)}>
            <Check size={15} strokeWidth={1.75} aria-hidden="true" /> Conferma
          </button>
          {(msg.parsed.type === "expense" || msg.parsed.type === "income") && (
            <button type="button" className={styles.action} onClick={() => openCategoryPicker(msg.id)}>
              <Pencil size={15} strokeWidth={1.75} aria-hidden="true" /> Cambia categoria
            </button>
          )}
          <button type="button" className={styles.action} onClick={() => cancel(msg.id)}>
            <X size={15} strokeWidth={1.75} aria-hidden="true" /> Annulla
          </button>
        </div>
      )}

      {msg.categoryPromotion && !msg.categoryPromotionResolved && (
        <div className={styles.actionRow}>
          <button
            type="button"
            className={`${styles.action} ${styles.actionPrimary}`}
            onClick={() => void resolveCategoryPromotion(msg.id, msg.categoryPromotion!.candidateId, "yes")}
          >
            <Check size={15} strokeWidth={1.75} aria-hidden="true" /> Sì
          </button>
          <button
            type="button"
            className={styles.action}
            onClick={() => void resolveCategoryPromotion(msg.id, msg.categoryPromotion!.candidateId, "no")}
          >
            <X size={15} strokeWidth={1.75} aria-hidden="true" /> No
          </button>
        </div>
      )}

      {msg.noAccountAction && (
        <div className={styles.actionRow}>
          <button type="button" className={styles.action} onClick={openManage}>
            <Landmark size={15} strokeWidth={1.75} aria-hidden="true" /> Vai ai Conti
          </button>
        </div>
      )}

      {msg.awaitingCategoryPick && msg.parsed?.categories && (
        <div className={styles.pickerColumn}>
          {msg.parsed.categories.map((category) => (
            <button
              key={category}
              type="button"
              className={styles.action}
              onClick={() => selectCategory(msg.id, category)}
            >
              <FolderOpen size={15} strokeWidth={1.75} aria-hidden="true" /> {category}
            </button>
          ))}
          <button type="button" className={styles.action} onClick={() => closeCategoryPicker(msg.id)}>
            <Undo2 size={15} strokeWidth={1.75} aria-hidden="true" /> Indietro
          </button>
        </div>
      )}

      {msg.awaitingAccountPick && msg.parsed?.accounts && (
        <div className={styles.pickerColumn}>
          {selectableAccounts(msg).map((account) => (
            <button
              key={account.id}
              type="button"
              className={styles.action}
              onClick={() => void selectAccount(msg.id, account.id)}
            >
              <Landmark size={15} strokeWidth={1.75} aria-hidden="true" /> {account.name}
              {account.current_balance != null ? ` (€${Number(account.current_balance).toFixed(2)})` : ""}
            </button>
          ))}
          <button type="button" className={styles.action} onClick={() => cancel(msg.id)}>
            <X size={15} strokeWidth={1.75} aria-hidden="true" /> Annulla
          </button>
        </div>
      )}
    </div>
  );

  const content = (
    <div className={styles.sheet}>
      <div className={styles.header}>
        <h2 className={styles.title} id={TITLE_ID}>Registra un movimento</h2>
        <div className={styles.headerActions}>
          <button type="button" className={styles.chatLink} onClick={goToChat}>
            <MessageCircle size={16} strokeWidth={1.75} aria-hidden="true" /> Apri la Chat
          </button>
          <button type="button" className={styles.closeButton} aria-label="Chiudi" onClick={requestClose}>
            <X size={20} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className={styles.body}>
        <p className={styles.hint}>
          Le risposte sono generate automaticamente con Mistral AI europea: verifica sempre
          gli importi prima di confermare.
        </p>

        {messages.length === 0 && (
          <p className={styles.hint}>
            Scrivi la spesa o l&apos;entrata, registra un vocale o allega la foto di uno scontrino.
            Prima di salvare ti chiedo sempre conferma.
          </p>
        )}

        {messages.map(renderMessage)}

        <div aria-live="polite">
          {showTypingIndicator && <p className={styles.status}>Sto analizzando…</p>}
          {isRecording && (
            <p className={styles.status}>Registrazione in corso… tocca il microfono per fermarla.</p>
          )}
        </div>

        {hasSaved && (
          <div className={styles.successBox}>
            <p className={styles.successTitle}>
              <Check size={16} strokeWidth={2} aria-hidden="true" /> Registrato
            </p>
            <div className={styles.actionRow}>
              <button
                type="button"
                className={`${styles.action} ${styles.actionPrimary}`}
                onClick={recordAnother}
              >
                Registra un altro
              </button>
              <button type="button" className={styles.action} onClick={openManage}>
                Apri Gestisci
              </button>
            </div>
          </div>
        )}

        {showChatShortcut && (
          <div className={styles.actionRow}>
            <button type="button" className={styles.action} onClick={goToChat}>
              <MessageCircle size={15} strokeWidth={1.75} aria-hidden="true" /> Continua in Chat
            </button>
          </div>
        )}

      </div>

      {confirmExit && (
        // Fuori dall'area scrollabile: una conferma in fondo alla conversazione
        // potrebbe restare invisibile proprio quando serve.
        <div className={styles.exitConfirm} role="alertdialog" aria-labelledby="quick-capture-exit">
          <p className={styles.error} id="quick-capture-exit">
            Vuoi uscire? Il movimento non è stato registrato.
          </p>
          <div className={styles.actionRow}>
            <button type="button" className={styles.action} onClick={closeAndReset}>
              Esci
            </button>
            <button
              ref={keepEditingRef}
              type="button"
              className={`${styles.action} ${styles.actionPrimary}`}
              onClick={() => setConfirmExit(false)}
            >
              Continua a registrare
            </button>
          </div>
        </div>
      )}

      <div className={styles.composer}>
        <input
          ref={fileInputRef}
          type="file"
          aria-label="Seleziona uno scontrino"
          accept="image/*,application/pdf"
          style={{ display: "none" }}
          onChange={handleFileChange}
        />
        <button
          type="button"
          className={styles.iconButton}
          aria-label="Allega scontrino"
          disabled={isLoading || isRecording}
          onClick={() => fileInputRef.current?.click()}
        >
          <Paperclip size={20} strokeWidth={1.75} aria-hidden="true" />
        </button>

        <textarea
          ref={inputRef}
          className={styles.input}
          rows={1}
          autoFocus
          placeholder="Es. 24 € al supermercato"
          aria-label="Descrivi il movimento"
          value={inputText}
          disabled={isLoading}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
        />

        {inputText.trim() ? (
          <button
            type="button"
            className={`${styles.iconButton} ${styles.sendButton}`}
            aria-label="Invia"
            disabled={isLoading}
            onClick={() => void sendText()}
          >
            <Send size={20} strokeWidth={1.75} aria-hidden="true" />
          </button>
        ) : (
          <button
            type="button"
            className={isRecording ? `${styles.iconButton} ${styles.iconButtonActive}` : styles.iconButton}
            aria-label={isRecording ? "Ferma la registrazione" : "Registra un vocale"}
            aria-pressed={isRecording}
            disabled={isLoading}
            onClick={() => void toggleVoice()}
          >
            <Mic size={20} strokeWidth={1.75} aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );

  // Stesso contenuto e stesso controller nelle due presentazioni: bottom sheet
  // quasi a tutta larghezza sotto i 900 px, dialog centrato da 900 px in su.
  if (isMobile) {
    return (
      <Drawer
        anchor="bottom"
        open={open}
        onClose={requestClose}
        aria-labelledby={TITLE_ID}
        slotProps={{
          paper: {
            role: "dialog",
            "aria-modal": true,
            "aria-labelledby": TITLE_ID,
            sx: {
              width: "100%",
              maxHeight: "88dvh",
              bgcolor: "var(--color-surface)",
              backgroundImage: "none",
              borderTopLeftRadius: 16,
              borderTopRightRadius: 16,
            },
          },
        }}
      >
        {content}
      </Drawer>
    );
  }

  return (
    <Dialog
      open={open}
      onClose={requestClose}
      fullWidth
      maxWidth="sm"
      aria-labelledby={TITLE_ID}
      slotProps={{
        paper: {
          sx: {
            bgcolor: "var(--color-surface)",
            backgroundImage: "none",
            border: "1px solid var(--color-border)",
            borderRadius: "16px",
            maxHeight: "80vh",
          },
        },
      }}
    >
      {content}
    </Dialog>
  );
}
