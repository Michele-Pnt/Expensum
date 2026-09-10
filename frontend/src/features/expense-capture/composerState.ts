import type { CaptureMessage } from "./types";

export interface ComposerSnapshot {
  inputText: string;
  isLoading: boolean;
  isRecording: boolean;
  awaitingUser: boolean;
}

/**
 * C'è lavoro che andrebbe perso chiudendo il composer? Testo digitato, un upload
 * in corso, una registrazione aperta o un passaggio non concluso: in questi casi
 * la chiusura chiede conferma, altrimenti è immediata.
 */
export function hasPendingCapture(snapshot: ComposerSnapshot): boolean {
  return (
    snapshot.inputText.trim().length > 0 ||
    snapshot.isLoading ||
    snapshot.isRecording ||
    snapshot.awaitingUser
  );
}

export interface ReplyContext {
  lastBotMessage?: CaptureMessage;
  awaitingUser: boolean;
  hasSaved: boolean;
  isLoading: boolean;
}

/**
 * Risposta che non è un movimento da confermare né un salvataggio andato a buon
 * fine (comando, chiarimento, testo non riconosciuto): il composer la mostra e
 * rimanda alla Chat, senza eseguire nulla per conto proprio.
 */
export function isNonFinancialReply(context: ReplyContext): boolean {
  const { lastBotMessage, awaitingUser, hasSaved, isLoading } = context;
  if (!lastBotMessage || awaitingUser || hasSaved || isLoading) return false;
  // Un errore tecnico non è un comando: si riprova qui, non si rimanda in Chat.
  if (lastBotMessage.isError) return false;
  return !lastBotMessage.parsed && !lastBotMessage.savedTransaction;
}

/** Un movimento è stato registrato e non resta nulla in sospeso. */
export function hasCompletedSave(messages: CaptureMessage[], awaitingUser: boolean, isLoading: boolean): boolean {
  return messages.some((m) => m.savedTransaction) && !awaitingUser && !isLoading;
}

export function isAwaitingUser(messages: CaptureMessage[]): boolean {
  return messages.some(
    (m) => m.awaitingConfirm || m.awaitingAmount || m.awaitingAccountPick || m.awaitingCategoryPick,
  );
}
