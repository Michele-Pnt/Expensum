import type {
  Account,
  CaptureMessage,
  ChatTransaction,
  ConfirmResponse,
  ParsedData,
  ParseResponse,
  SaveOptions,
} from "./types";

// ─── Riepilogo / step successivo ──────────────────────────────────────────────
// Rispecchia _build_parse_reply e _build_transaction_payload lato server, così
// completare un importo mancante non richiede un altro round-trip.

export function buildConfirmText(parsed: ParsedData): string {
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
    return `Nuovo trasferimento riconosciuto:\n\nImporto: **${amountStr}**\nDa: **${from}**\nA: **${to}**\nDescrizione: **${name}**\n\nConfermi?`;
  }
  const incomeType = parsed.income_category || parsed.income_type || "Entrata";
  const name = parsed.name || "Entrata";
  return `Ho interpretato **${name}** (${incomeType}) di ${amountStr}. Confermi?`;
}

export interface NextStep {
  awaitingConfirm: boolean;
  awaitingAccountPick?: "from" | "to";
  text: string;
}

export function nextStepAfterAmount(parsed: ParsedData): NextStep {
  if (parsed.type === "transfer") {
    if ((parsed.accounts?.length || 0) < 2) {
      return {
        awaitingConfirm: false,
        text: "Ti servono almeno due conti per fare un trasferimento.\n\nAggiungine uno nella tab \"Conti\" del tuo spazio.",
      };
    }
    if (!parsed.resolved_from_account_id) {
      return { awaitingConfirm: false, awaitingAccountPick: "from", text: "Da quale conto vuoi spostare i soldi?" };
    }
    if (!parsed.resolved_to_account_id) {
      return { awaitingConfirm: false, awaitingAccountPick: "to", text: "Su quale conto vuoi spostare i soldi?" };
    }
  }
  return { awaitingConfirm: true, text: buildConfirmText(parsed) };
}

/** Stesso fallback regex di bot.py:1667-1675: normalizza e ricava il primo numero. */
export function parseAmountFallback(raw: string): number | null {
  const cleaned = raw.toLowerCase().replace(/\s/g, "").replace(/€/g, "").replace(/euro/g, "").replace(",", ".");
  const match = cleaned.match(/-?\d+(?:\.\d+)?/);
  return match ? parseFloat(match[0]) : null;
}

// ─── Risposte di parsing ──────────────────────────────────────────────────────

export function buildParseFailureMessage(data: ParseResponse): CaptureMessage {
  return {
    id: `bot-${Date.now()}`,
    role: "bot",
    text: data.reply || "Non ho capito. Riprova con una descrizione più chiara.",
    timestamp: new Date(),
    status: "sent",
    transcription: data.transcription,
    noAccountAction: data.type === "no_account" ? true : undefined,
  };
}

export function isParseFailure(data: ParseResponse): boolean {
  return !data.ok || data.type === "error" || data.type === "unknown" || data.type === "no_account";
}

/**
 * Le transazioni "pronte" si mostrano subito come bubble indipendenti; quelle che
 * richiedono un'altra domanda (importo, conto) vanno in coda e si presentano una
 * alla volta — mirror di expense_queue in bot.py.
 */
export function partitionTransactions(transactions: ChatTransaction[]): {
  immediate: ChatTransaction[];
  sequential: ChatTransaction[];
} {
  return {
    immediate: transactions.filter((tx) => tx.awaiting_confirm || tx.needs_second_account),
    sequential: transactions.filter((tx) => !tx.awaiting_confirm && !tx.needs_second_account),
  };
}

// ─── Transizioni di stato di una singola bubble ───────────────────────────────

export type AmountAnswerOutcome =
  | { status: "invalid_amount"; message: CaptureMessage }
  | { status: "resolved"; message: CaptureMessage; terminal: boolean };

/** Risposta testuale a "quanto hai speso/vuoi trasferire?" (mirror di waiting_for_amount). */
export function applyAmountAnswer(message: CaptureMessage, text: string): AmountAnswerOutcome {
  const amount = parseAmountFallback(text);
  if (amount === null || !message.parsed) {
    return { status: "invalid_amount", message };
  }

  const parsed: ParsedData = { ...message.parsed, amount };
  const step = nextStepAfterAmount(parsed);
  return {
    status: "resolved",
    terminal: !step.awaitingConfirm && !step.awaitingAccountPick,
    message: {
      ...message,
      parsed,
      awaitingAmount: false,
      awaitingConfirm: step.awaitingConfirm,
      awaitingAccountPick: step.awaitingAccountPick,
      text: step.text,
    },
  };
}

/**
 * Un tap sul picker categoria: per una spesa aggiorna `category`, per un'entrata
 * `income_type`/`income_category` (stesso campo `categories` in ParsedData per
 * entrambe — popolato dal backend con la lista giusta in base al tipo, vedi
 * `_build_transaction_payload` in app.py).
 */
export function applyCategorySelection(message: CaptureMessage, category: string): CaptureMessage {
  if (!message.parsed) return message;
  const parsed: ParsedData =
    message.parsed.type === "income"
      ? { ...message.parsed, income_type: category, income_category: category }
      : { ...message.parsed, category };
  return {
    ...message,
    parsed,
    awaitingCategoryPick: false,
    awaitingConfirm: true,
    categoryWasCorrected: true,
    text: buildConfirmText(parsed),
  };
}

export type AccountSelectionOutcome =
  | { action: "continue"; message: CaptureMessage }
  | { action: "save"; message: CaptureMessage; parsed: ParsedData; saveOptions: SaveOptions };

/**
 * Un tap su un conto: per una spesa/entrata salva subito, per un trasferimento
 * avanza da "conto origine" a "conto destinazione" e salva solo al secondo tap.
 */
export function resolveAccountSelection(message: CaptureMessage, account: Account): AccountSelectionOutcome {
  const parsed = message.parsed ?? {};

  if (message.awaitingAccountPick === "from") {
    return {
      action: "continue",
      message: {
        ...message,
        parsed: {
          ...parsed,
          resolved_from_account_id: account.id,
          resolved_from_account_name: account.name,
        },
        awaitingAccountPick: "to",
      },
    };
  }

  if (message.awaitingAccountPick === "to") {
    const resolved: ParsedData = {
      ...parsed,
      resolved_to_account_id: account.id,
      resolved_to_account_name: account.name,
    };
    return {
      action: "save",
      message: { ...message, parsed: resolved, awaitingAccountPick: undefined },
      parsed: resolved,
      saveOptions: {
        from_account_id: parsed.resolved_from_account_id ?? undefined,
        to_account_id: account.id,
      },
    };
  }

  return {
    action: "save",
    message: { ...message, parsed, awaitingAccountPick: undefined },
    parsed,
    saveOptions: { account_id: account.id },
  };
}

/**
 * Conti selezionabili nello step corrente: nella scelta del conto destinazione il
 * conto di origine è escluso, così un trasferimento non può puntare a se stesso.
 */
export function selectableAccounts(message: CaptureMessage): Account[] {
  const accounts = message.parsed?.accounts ?? [];
  if (message.awaitingAccountPick !== "to") return accounts;
  const fromId = message.parsed?.resolved_from_account_id;
  return accounts.filter((account) => account.id !== fromId);
}

export function applyCancellation(message: CaptureMessage): CaptureMessage {
  return {
    ...message,
    awaitingConfirm: false,
    awaitingAccountPick: undefined,
    awaitingCategoryPick: false,
    awaitingAmount: false,
    text: "Operazione annullata.",
  };
}

export function buildSaveResultMessage(data: ConfirmResponse, parsed: ParsedData): CaptureMessage {
  const saved = data.saved === true;
  return {
    id: `confirm-${Date.now()}`,
    role: "bot",
    text: data.reply || "Registrato!",
    timestamp: new Date(),
    status: "sent",
    parsed: saved ? parsed : undefined,
    noAccountAction: data.error === "no_account" ? true : undefined,
    savedTransaction: saved,
  };
}

export function historyMsgToMessage(h: {
  id: string | number;
  role: string;
  text: string;
  created_at?: string;
  metadata?: ParsedData;
}): CaptureMessage {
  return {
    id: `hist-${h.id}`,
    role: h.role === "user" ? "user" : "bot",
    text: h.text,
    timestamp: h.created_at ? new Date(h.created_at) : new Date(0),
    status: "sent",
    parsed: h.metadata,
  };
}
