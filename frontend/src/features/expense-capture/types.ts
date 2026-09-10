import type { InputMethod } from "@/lib/analytics";

export type MessageRole = "user" | "bot";
export type MessageStatus = "sending" | "sent" | "error";

/** Modalità del picker conti: spesa/entrata (uno solo) oppure i due lati di un trasferimento. */
export type AccountPickMode = "single" | "from" | "to";

export interface Account {
  id: string;
  name: string;
  current_balance?: number;
}

export interface ParsedData {
  type?: string;
  amount?: number | null;
  category?: string | null;
  income_type?: string | null;
  income_category?: string | null;
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

/** Item come restituito da /api/chat/message|voice|photo dentro "transactions". */
export interface ChatTransaction {
  type: string;
  reply: string;
  parsed: ParsedData;
  awaiting_confirm?: boolean;
  needs_amount?: boolean;
  needs_second_account?: boolean;
  needs_account_pick?: "from" | "to";
  category_promotion?: { candidate_id: number; suggested_name: string } | null;
}

export interface CaptureMessage {
  id: string;
  role: MessageRole;
  text: string;
  timestamp: Date;
  status?: MessageStatus;
  parsed?: ParsedData;
  awaitingConfirm?: boolean;
  awaitingCategoryPick?: boolean;
  awaitingAccountPick?: AccountPickMode;
  awaitingAmount?: boolean;
  transcription?: string;
  noAccountAction?: boolean;
  categoryPromotion?: { candidateId: number; suggestedName: string };
  categoryPromotionResolved?: boolean;
  /** L'utente ha cambiato la categoria proposta dall'AI prima di confermare (spesa o entrata). */
  categoryWasCorrected?: boolean;
  savedTransaction?: boolean;
  /** Bubble generata dal client per un errore tecnico (rete, upload, permessi). */
  isError?: boolean;
}

/** Risposta grezza degli endpoint di parsing (/api/chat/message|voice|photo). */
export interface ParseResponse {
  ok: boolean;
  type?: string;
  transactions?: ChatTransaction[];
  reply?: string;
  saved?: boolean;
  transcription?: string;
}

/** Risposta di /api/chat/confirm. */
export interface ConfirmResponse {
  saved?: boolean;
  reply?: string;
  error?: string;
  is_first_expense?: boolean;
}

export interface SaveOptions {
  account_id?: string;
  from_account_id?: string;
  to_account_id?: string;
}

export type CapturePhase =
  | "idle"
  | "recording"
  | "uploading"
  | "awaiting_user"
  | "saved"
  | "error";

export interface CaptureSavedResult {
  saved: boolean;
  parsed: ParsedData;
  reply: string;
  inputMethod: InputMethod;
}

export interface ExpenseCaptureOptions {
  loadHistory: boolean;
  onSaved?: (result: CaptureSavedResult) => void;
}

export interface ExpenseCaptureController {
  messages: CaptureMessage[];
  inputText: string;
  phase: CapturePhase;
  isRecording: boolean;
  isLoading: boolean;
  showTypingIndicator: boolean;
  historyLoaded: boolean;
  setInputText(value: string): void;
  sendText(text?: string): Promise<void>;
  toggleVoice(): Promise<void>;
  sendPhoto(file: File): Promise<void>;
  confirm(messageId: string): Promise<void>;
  cancel(messageId: string): void;
  selectCategory(messageId: string, category: string): void;
  openCategoryPicker(messageId: string): void;
  closeCategoryPicker(messageId: string): void;
  selectAccount(messageId: string, accountId: string): Promise<void>;
  resolveCategoryPromotion(messageId: string, candidateId: number, decision: "yes" | "no"): Promise<void>;
  /** Salvataggio diretto (spese rapide): stesso endpoint /api/chat/confirm del flusso normale. */
  saveDirect(parsed: ParsedData, options: SaveOptions): Promise<void>;
  reset(): void;
}
