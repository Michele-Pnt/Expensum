"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { buildHeaders } from "@/lib/apiHeaders";
import {
  trackExpenseTracked,
  trackExpenseTrackingFailed,
  trackFirstExpenseTracked,
  type InputMethod,
} from "@/lib/analytics";
import {
  applyAmountAnswer,
  applyCancellation,
  applyCategorySelection,
  buildParseFailureMessage,
  buildSaveResultMessage,
  historyMsgToMessage,
  isParseFailure,
  partitionTransactions,
  resolveAccountSelection,
} from "./model";
import type {
  CaptureMessage,
  CapturePhase,
  ChatTransaction,
  ExpenseCaptureController,
  ExpenseCaptureOptions,
  MessageStatus,
  ParsedData,
  ParseResponse,
  SaveOptions,
} from "./types";

export const WELCOME_MESSAGE_ID = "welcome";

const WELCOME_TEXT =
  "Ciao! Le mie risposte sono generate automaticamente con Mistral AI europea: posso sbagliare, verifica sempre i dati finanziari importanti.\n\nDimmi una spesa o un'entrata e la registro subito. Prova con:\n• _«Ho speso 24€ per il sushi»_\n• _«Ho ricevuto lo stipendio 1500€»_\n• _«Netflix 12,99»_";

function buildWelcomeMessage(): CaptureMessage {
  return {
    id: WELCOME_MESSAGE_ID,
    role: "bot",
    text: WELCOME_TEXT,
    timestamp: new Date(),
    status: "sent",
  };
}

/**
 * Flusso di acquisizione di un movimento (testo, voce, foto) condiviso da Chat e
 * composer globale: stesse chiamate API, stessa conferma esplicita, stessa coda
 * multi-transazione. Nessun salvataggio avviene senza una conferma dell'utente.
 */
export function useExpenseCaptureFlow(options: ExpenseCaptureOptions): ExpenseCaptureController {
  const { loadHistory, onSaved } = options;

  const [messages, setMessages] = useState<CaptureMessage[]>([]);
  const [inputText, setInputText] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [showTypingIndicator, setShowTypingIndicator] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [savedOnce, setSavedOnce] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const pendingInputMethodRef = useRef<InputMethod>("text");
  const onSavedRef = useRef(onSaved);
  onSavedRef.current = onSaved;

  // Copia sempre aggiornata dei messaggi: le decisioni di flusso si prendono qui,
  // mai dentro un updater di setState (non è garantito sincrono e assegnare
  // variabili esterne da lì produce letture stantie).
  const messagesRef = useRef<CaptureMessage[]>([]);
  messagesRef.current = messages;

  // Registrazione abbandonata (reset/unmount): l'audio non va né inviato né
  // aggiunto alla conversazione — `onstop` scatta comunque quando le tracce
  // vengono fermate.
  const discardRecordingRef = useRef(false);
  // Salvataggi in volo, per id di messaggio: evita che un doppio tap sullo stesso
  // bottone conto registri due movimenti identici.
  const inFlightSavesRef = useRef<Set<string>>(new Set());
  // Il salvataggio diretto (spesa rapida) non ha un id di messaggio stabile:
  // gli serve una guardia dedicata contro il doppio tap.
  const directSaveInFlightRef = useRef(false);

  // Sessione di acquisizione: `reset()` la incrementa, così le risposte di
  // richieste partite prima vengono scartate invece di riapparire in un composer
  // che l'utente aveva abbandonato.
  const sessionRef = useRef(0);

  // Coda locale delle transazioni "sequenziali" (importo mancante o conto da
  // scegliere) rilevate in un messaggio multi-transazione: presentate una alla
  // volta, mirror di expense_queue/waiting_for_amount in bot.py.
  const sequentialQueueRef = useRef<ChatTransaction[]>([]);
  const activeSequentialIdRef = useRef<string | null>(null);
  // "amount" = il prossimo testo libero va interpretato come importo;
  // "account" = si aspetta un click sui bottoni.
  const activeSequentialKindRef = useRef<"amount" | "account" | null>(null);

  // ── Microfono: fermare sempre tutte le tracce (registrazione, errore, reset, unmount) ──

  const stopMicrophone = useCallback(() => {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    mediaRecorderRef.current = null;
    audioChunksRef.current = [];
  }, []);

  /** Interrompe e scarta una registrazione in corso: niente upload, niente bubble. */
  const discardRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      discardRecordingRef.current = true;
      mediaRecorderRef.current.stop();
    }
    stopMicrophone();
  }, [stopMicrophone]);

  useEffect(() => () => discardRecording(), [discardRecording]);

  // ── History ────────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!loadHistory) {
      setHistoryLoaded(true);
      return;
    }

    let cancelled = false;
    const greeting = buildWelcomeMessage();

    buildHeaders()
      .then((headers) => fetch("/api/chat/history", { credentials: "same-origin", headers }))
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        const history: CaptureMessage[] = (data.messages || []).map(historyMsgToMessage);
        setMessages([greeting, ...history]);
        setHistoryLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        setMessages([greeting]);
        setHistoryLoaded(true);
      });

    return () => {
      cancelled = true;
    };
  }, [loadHistory]);

  const appendMessage = useCallback((message: CaptureMessage) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const appendErrorMessage = useCallback((id: string, text: string) => {
    setHasError(true);
    setMessages((prev) => [
      ...prev,
      { id, role: "bot", text, timestamp: new Date(), status: "sent", isError: true },
    ]);
  }, []);

  // ── Coda sequenziale ───────────────────────────────────────────────────────

  const presentNextSequential = useCallback(() => {
    if (activeSequentialIdRef.current) return; // uno alla volta, come expense_queue in bot.py
    const next = sequentialQueueRef.current.shift();
    if (!next) return;
    const msgId = `bot-seq-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    activeSequentialIdRef.current = msgId;
    activeSequentialKindRef.current = next.needs_amount ? "amount" : "account";
    appendMessage({
      id: msgId,
      role: "bot",
      text: next.reply,
      timestamp: new Date(),
      status: "sent",
      parsed: next.parsed,
      awaitingAmount: !!next.needs_amount,
      awaitingAccountPick: next.needs_account_pick,
    });
  }, [appendMessage]);

  // ── Risposta di parsing (multi-transazione) ────────────────────────────────

  const handleParseResponse = useCallback(
    (data: ParseResponse, userMsgId: string, session: number) => {
      // Risposta di una sessione abbandonata (composer chiuso e resettato mentre
      // la richiesta era in volo): va scartata, non riaperta sotto il naso dell'utente.
      if (session !== sessionRef.current) return;
      setShowTypingIndicator(false);
      setMessages((prev) => prev.map((m) => (m.id === userMsgId ? { ...m, status: "sent" as MessageStatus } : m)));

      if (isParseFailure(data)) {
        appendMessage(buildParseFailureMessage(data));
        return;
      }

      const transactions = data.transactions || [];
      const { immediate, sequential } = partitionTransactions(transactions);

      if (immediate.length > 0) {
        setMessages((prev) => [
          ...prev,
          ...immediate.map((tx, i) => ({
            id: `bot-${Date.now()}-${i}`,
            role: "bot" as const,
            text: tx.reply,
            timestamp: new Date(),
            status: "sent" as MessageStatus,
            parsed: tx.parsed,
            awaitingConfirm: !!tx.awaiting_confirm,
            transcription: data.transcription,
          })),
        ]);
      }

      sequentialQueueRef.current.push(...sequential);
      presentNextSequential();

      // Categorizzazione adattiva: bubble dedicata con bottoni Sì/No, stessa UX del bot.
      const promotions = transactions
        .map((tx) => tx.category_promotion)
        .filter((p): p is { candidate_id: number; suggested_name: string } => !!p);
      if (promotions.length > 0) {
        setMessages((prev) => [
          ...prev,
          ...promotions.map((p, i) => ({
            id: `bot-catpromote-${Date.now()}-${i}`,
            role: "bot" as const,
            text: `Ho notato che scrivi spesso spese simili, vuoi che crei una categoria dedicata «${p.suggested_name}»?`,
            timestamp: new Date(),
            status: "sent" as MessageStatus,
            categoryPromotion: { candidateId: p.candidate_id, suggestedName: p.suggested_name },
          })),
        ]);
      }
    },
    [appendMessage, presentNextSequential],
  );

  // ── Salvataggio (dopo la conferma esplicita e la scelta del conto) ─────────

  const saveTransaction = useCallback(
    async (
      botMsgId: string,
      parsed: ParsedData,
      opts: SaveOptions,
      method?: InputMethod,
      categoryWasCorrected?: boolean,
    ) => {
      // Doppio tap sullo stesso bottone: senza questa guardia partirebbero due
      // POST e verrebbero registrati due movimenti identici.
      if (inFlightSavesRef.current.has(botMsgId)) return;
      inFlightSavesRef.current.add(botMsgId);

      const inputMethod = method ?? pendingInputMethodRef.current;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === botMsgId
            ? { ...m, awaitingConfirm: false, awaitingAccountPick: undefined, awaitingCategoryPick: false }
            : m,
        ),
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
          body: JSON.stringify({
            parsed,
            input_method: inputMethod,
            category_was_corrected: !!categoryWasCorrected,
            ...opts,
          }),
        });
        const data = await res.json();
        setShowTypingIndicator(false);

        if (data.saved) {
          trackExpenseTracked(inputMethod);
          if (data.is_first_expense) trackFirstExpenseTracked(inputMethod);
          setSavedOnce(true);
          setHasError(false);
        } else {
          trackExpenseTrackingFailed(data.error === "no_account" ? "no_account" : "save_error", inputMethod);
          setHasError(true);
          setSavedOnce(false);
        }

        appendMessage(buildSaveResultMessage(data, parsed));
        onSavedRef.current?.({
          saved: data.saved === true,
          parsed,
          reply: data.reply || "",
          inputMethod,
        });
      } catch {
        setShowTypingIndicator(false);
        appendErrorMessage(`err-confirm-${Date.now()}`, "Errore durante il salvataggio. Riprova.");
      } finally {
        inFlightSavesRef.current.delete(botMsgId);
        presentNextSequential();
      }
    },
    [appendErrorMessage, appendMessage, presentNextSequential],
  );

  // ── Risposta all'importo mancante ─────────────────────────────────────────

  const answerPendingAmount = useCallback(
    (botMsgId: string, text: string) => {
      const userMsg: CaptureMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        text,
        timestamp: new Date(),
        status: "sent",
      };
      setInputText("");

      // L'esito si calcola qui, non dentro l'updater: un updater con effetti
      // collaterali verrebbe eseguito al render successivo e lascerebbe la coda
      // in uno stato incoerente (l'importo non più atteso dopo un errore).
      const target = messagesRef.current.find((m) => m.id === botMsgId);
      if (!target) {
        // Il messaggio in attesa non esiste più (reset a metà flusso): libera lo
        // slot, altrimenti la coda resterebbe bloccata su una domanda sparita.
        activeSequentialIdRef.current = null;
        activeSequentialKindRef.current = null;
        setMessages((prev) => [...prev, userMsg]);
        presentNextSequential();
        return;
      }

      const outcome = applyAmountAnswer(target, text);

      if (outcome.status === "invalid_amount") {
        setMessages((prev) => [
          ...prev,
          userMsg,
          {
            id: `err-amount-${Date.now()}`,
            role: "bot",
            text: "Non ho capito l'importo. Prova a ridirmelo, scrivendo solo il numero (es. 20 o 20,50).",
            timestamp: new Date(),
            status: "sent",
          },
        ]);
        return; // l'importo resta atteso: il prossimo testo è ancora un importo
      }

      setMessages((prev) => [...prev.map((m) => (m.id === botMsgId ? outcome.message : m)), userMsg]);

      if (outcome.terminal) {
        // Blocco terminale (es. servono almeno 2 conti): libera lo slot e passa alla prossima.
        activeSequentialIdRef.current = null;
        activeSequentialKindRef.current = null;
        presentNextSequential();
      } else {
        activeSequentialKindRef.current = "account";
      }
    },
    [presentNextSequential],
  );

  // ── Invio testo ────────────────────────────────────────────────────────────

  const sendText = useCallback(
    async (text?: string) => {
      const trimmed = (text ?? inputText).trim();
      if (!trimmed || isLoading) return;

      // Una transazione in coda aspetta l'importo: il testo libero è quell'importo,
      // non un nuovo parsing NLP (mirror di waiting_for_amount in bot.py).
      if (activeSequentialIdRef.current && activeSequentialKindRef.current === "amount") {
        answerPendingAmount(activeSequentialIdRef.current, trimmed);
        return;
      }

      const userMsg: CaptureMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        text: trimmed,
        timestamp: new Date(),
        status: "sending",
      };

      const session = sessionRef.current;
      appendMessage(userMsg);
      setInputText("");
      setIsLoading(true);
      setShowTypingIndicator(true);
      setHasError(false);
      setSavedOnce(false);
      pendingInputMethodRef.current = "text";

      try {
        const res = await fetch("/api/chat/message", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await buildHeaders()) },
          credentials: "same-origin",
          body: JSON.stringify({ text: trimmed }),
        });
        const data = await res.json();
        handleParseResponse(data, userMsg.id, session);
      } catch {
        if (session !== sessionRef.current) return;
        setMessages((prev) => prev.map((m) => (m.id === userMsg.id ? { ...m, status: "error" } : m)));
        setShowTypingIndicator(false);
        appendErrorMessage(`err-${Date.now()}`, "Errore di rete. Controlla la connessione e riprova.");
      } finally {
        setIsLoading(false);
      }
    },
    [answerPendingAmount, appendErrorMessage, appendMessage, handleParseResponse, inputText, isLoading],
  );

  // ── Registrazione vocale ───────────────────────────────────────────────────

  const toggleVoice = useCallback(async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Il riferimento va salvato PRIMA di costruire il recorder: se il costruttore
      // lancia (codec non supportato in alcune WebView), il catch deve poter
      // fermare le tracce, altrimenti il microfono resterebbe aperto.
      mediaStreamRef.current = stream;
      discardRecordingRef.current = false;
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        stopMicrophone();

        // Registrazione abbandonata (reset o pagina smontata): l'audio non viene
        // né caricato né mostrato — l'utente ha lasciato quel movimento.
        if (discardRecordingRef.current) {
          discardRecordingRef.current = false;
          return;
        }

        const userMsg: CaptureMessage = {
          id: `user-voice-${Date.now()}`,
          role: "user",
          text: "Messaggio vocale inviato",
          timestamp: new Date(),
          status: "sending",
        };
        const session = sessionRef.current;
        appendMessage(userMsg);
        setIsLoading(true);
        setShowTypingIndicator(true);
        setHasError(false);
        setSavedOnce(false);

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

          setMessages((prev) =>
            prev.map((m) =>
              m.id === userMsg.id
                ? { ...m, text: data.transcription || m.text, status: "sent" as MessageStatus }
                : m,
            ),
          );
          handleParseResponse(data, userMsg.id, session);
        } catch {
          if (session !== sessionRef.current) return;
          setMessages((prev) => prev.map((m) => (m.id === userMsg.id ? { ...m, status: "error" } : m)));
          setShowTypingIndicator(false);
          appendErrorMessage(
            `err-voice-${Date.now()}`,
            "Errore durante la trascrizione audio. Riprova o scrivi il messaggio.",
          );
        } finally {
          setIsLoading(false);
        }
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
    } catch {
      stopMicrophone();
      setIsRecording(false);
      appendErrorMessage(
        `err-mic-${Date.now()}`,
        "Non ho potuto accedere al microfono. Verifica i permessi del browser.",
      );
    }
  }, [appendErrorMessage, appendMessage, handleParseResponse, isRecording, stopMicrophone]);

  // ── Foto scontrino ─────────────────────────────────────────────────────────

  const sendPhoto = useCallback(
    async (file: File) => {
      const isImage = file.type.startsWith("image/");
      const userMsg: CaptureMessage = {
        id: `user-img-${Date.now()}`,
        role: "user",
        text: isImage ? "Foto scontrino inviata" : `File inviato: ${file.name}`,
        timestamp: new Date(),
        status: "sending",
      };
      const session = sessionRef.current;
      appendMessage(userMsg);
      setIsLoading(true);
      setShowTypingIndicator(true);
      setHasError(false);
      setSavedOnce(false);

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
        setMessages((prev) => prev.map((m) => (m.id === userMsg.id ? { ...m, status: "sent" } : m)));
        handleParseResponse(data, userMsg.id, session);
      } catch {
        if (session !== sessionRef.current) return;
        setMessages((prev) => prev.map((m) => (m.id === userMsg.id ? { ...m, status: "error" } : m)));
        setShowTypingIndicator(false);
        appendErrorMessage(`err-img-${Date.now()}`, "Errore durante l'analisi dell'immagine. Riprova.");
      } finally {
        setIsLoading(false);
      }
    },
    [appendErrorMessage, appendMessage, handleParseResponse],
  );

  // ── Conferma / annullamento / picker ──────────────────────────────────────

  const confirm = useCallback(
    async (messageId: string) => {
      const message = messagesRef.current.find((m) => m.id === messageId);
      if (!message?.parsed) return;

      if (message.parsed.type === "transfer") {
        // Qui si arriva solo con entrambi i conti già risolti dagli hint LLM.
        await saveTransaction(messageId, message.parsed, {
          from_account_id: message.parsed.resolved_from_account_id ?? undefined,
          to_account_id: message.parsed.resolved_to_account_id ?? undefined,
        });
        return;
      }

      // Mai skip automatico: il conto si chiede sempre, anche se ce n'è uno solo.
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, awaitingConfirm: false, awaitingAccountPick: "single" } : m)),
      );
    },
    [saveTransaction],
  );

  const cancel = useCallback(
    (messageId: string) => {
      trackExpenseTrackingFailed("user_cancelled", pendingInputMethodRef.current);
      setMessages((prev) => prev.map((m) => (m.id === messageId ? applyCancellation(m) : m)));
      if (activeSequentialIdRef.current === messageId) {
        activeSequentialIdRef.current = null;
        activeSequentialKindRef.current = null;
        presentNextSequential();
      }
    },
    [presentNextSequential],
  );

  const selectCategory = useCallback((messageId: string, category: string) => {
    setMessages((prev) => prev.map((m) => (m.id === messageId ? applyCategorySelection(m, category) : m)));
  }, []);

  const openCategoryPicker = useCallback((messageId: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, awaitingConfirm: false, awaitingCategoryPick: true } : m)),
    );
  }, []);

  const closeCategoryPicker = useCallback((messageId: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, awaitingCategoryPick: false, awaitingConfirm: true } : m)),
    );
  }, []);

  const selectAccount = useCallback(
    async (messageId: string, accountId: string) => {
      const message = messagesRef.current.find((m) => m.id === messageId);
      if (!message) return;
      const account = message.parsed?.accounts?.find((a) => a.id === accountId);
      if (!account) return;

      const outcome = resolveAccountSelection(message, account);
      if (outcome.action === "continue") {
        setMessages((prev) => prev.map((m) => (m.id === messageId ? outcome.message : m)));
        return;
      }
      await saveTransaction(messageId, outcome.parsed, outcome.saveOptions, undefined, message.categoryWasCorrected);
    },
    [saveTransaction],
  );

  const resolveCategoryPromotion = useCallback(
    async (messageId: string, candidateId: number, decision: "yes" | "no") => {
      setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, categoryPromotionResolved: true } : m)));

      try {
        const res = await fetch("/api/chat/category-confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await buildHeaders()) },
          credentials: "same-origin",
          body: JSON.stringify({ candidate_id: candidateId, decision }),
        });
        const data = await res.json();
        appendMessage({
          id: `catpromote-result-${Date.now()}`,
          role: "bot",
          text: data.reply || (decision === "yes" ? "Categoria creata!" : "Nessun problema."),
          timestamp: new Date(),
          status: "sent",
        });
      } catch {
        appendErrorMessage(`catpromote-err-${Date.now()}`, "Errore durante la richiesta. Riprova più tardi.");
      }
    },
    [appendErrorMessage, appendMessage],
  );

  const saveDirect = useCallback(
    async (parsed: ParsedData, saveOptions: SaveOptions) => {
      // Il canale è quello del salvataggio diretto (spesa rapida), non l'ultimo
      // usato in chat: altrimenti un vocale precedente lo farebbe tracciare "voice".
      // L'id cambia a ogni chiamata, quindi la guardia anti-doppio-tap è qui.
      if (directSaveInFlightRef.current) return;
      directSaveInFlightRef.current = true;
      try {
        await saveTransaction(`direct-${Date.now()}`, parsed, saveOptions, "text");
      } finally {
        directSaveInFlightRef.current = false;
      }
    },
    [saveTransaction],
  );

  const reset = useCallback(() => {
    discardRecording();
    sessionRef.current += 1; // le risposte in volo appartengono alla sessione precedente
    sequentialQueueRef.current = [];
    activeSequentialIdRef.current = null;
    activeSequentialKindRef.current = null;
    pendingInputMethodRef.current = "text";
    inFlightSavesRef.current.clear();
    directSaveInFlightRef.current = false;
    setMessages(loadHistory ? [buildWelcomeMessage()] : []);
    setInputText("");
    setIsLoading(false);
    setIsRecording(false);
    setShowTypingIndicator(false);
    setHasError(false);
    setSavedOnce(false);
  }, [discardRecording, loadHistory]);

  const awaitingUser = messages.some(
    (m) => m.awaitingConfirm || m.awaitingAmount || m.awaitingAccountPick || m.awaitingCategoryPick,
  );

  let phase: CapturePhase = "idle";
  if (isRecording) phase = "recording";
  else if (isLoading) phase = "uploading";
  else if (awaitingUser) phase = "awaiting_user";
  else if (hasError) phase = "error";
  else if (savedOnce) phase = "saved";

  return {
    messages,
    inputText,
    phase,
    isRecording,
    isLoading,
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
    reset,
  };
}
