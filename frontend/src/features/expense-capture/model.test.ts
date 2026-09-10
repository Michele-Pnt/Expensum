import assert from "node:assert/strict";
import test from "node:test";

import {
  applyAmountAnswer,
  applyCancellation,
  applyCategorySelection,
  buildConfirmText,
  buildParseFailureMessage,
  buildSaveResultMessage,
  historyMsgToMessage,
  isParseFailure,
  nextStepAfterAmount,
  parseAmountFallback,
  partitionTransactions,
  resolveAccountSelection,
  selectableAccounts,
} from "./model";
import type { CaptureMessage, ChatTransaction, ParsedData } from "./types";

function botMessage(overrides: Partial<CaptureMessage> = {}): CaptureMessage {
  return {
    id: "bot-1",
    role: "bot",
    text: "",
    timestamp: new Date(0),
    status: "sent",
    ...overrides,
  };
}

const expense: ParsedData = {
  type: "expense",
  amount: 24,
  category: "Ristoranti",
  name: "Sushi",
  accounts: [
    { id: "acc-1", name: "Conto principale" },
    { id: "acc-2", name: "Contanti" },
  ],
  categories: ["Ristoranti", "Spesa"],
};

test("builds an explicit confirmation summary for an expense", () => {
  const text = buildConfirmText(expense);
  assert.match(text, /Sushi/);
  assert.match(text, /€24\.00/);
  assert.match(text, /Ristoranti/);
  assert.match(text, /Confermi\?/);
});

test("builds a confirmation summary for a transfer with both accounts", () => {
  const text = buildConfirmText({
    type: "transfer",
    amount: 100,
    name: "Giroconto",
    resolved_from_account_name: "Conto principale",
    resolved_to_account_name: "Contanti",
  });
  assert.match(text, /Da: \*\*Conto principale\*\*/);
  assert.match(text, /A: \*\*Contanti\*\*/);
});

test("builds a confirmation summary for an income using its category", () => {
  const text = buildConfirmText({ type: "income", amount: 1500, name: "Stipendio", income_category: "Lavoro" });
  assert.match(text, /Stipendio/);
  assert.match(text, /\(Lavoro\)/);
  assert.match(text, /€1500\.00/);
});

test("falls back to the income type, then to a generic label, when no category is given", () => {
  assert.match(buildConfirmText({ type: "income", amount: 10, income_type: "Bonus" }), /\(Bonus\)/);
  assert.match(buildConfirmText({ type: "income", amount: 10 }), /\*\*Entrata\*\* \(Entrata\)/);
});

test("treats errors, unknown replies and the missing-account case as parse failures", () => {
  assert.equal(isParseFailure({ ok: false }), true);
  assert.equal(isParseFailure({ ok: true, type: "error" }), true);
  assert.equal(isParseFailure({ ok: true, type: "unknown" }), true);
  assert.equal(isParseFailure({ ok: true, type: "no_account" }), true);
  assert.equal(isParseFailure({ ok: true, type: "expense", transactions: [] }), false);
});

test("rebuilds a stored history message with its role, timestamp and metadata", () => {
  const restored = historyMsgToMessage({
    id: 42,
    role: "user",
    text: "Ho speso 24€",
    created_at: "2026-09-01T10:30:00Z",
    metadata: { type: "expense", amount: 24 },
  });
  assert.equal(restored.id, "hist-42");
  assert.equal(restored.role, "user");
  assert.equal(restored.status, "sent");
  assert.equal(restored.parsed?.amount, 24);
  assert.equal(restored.timestamp.toISOString(), "2026-09-01T10:30:00.000Z");
});

test("treats any non-user history role as a bot message and undated ones as the oldest", () => {
  const restored = historyMsgToMessage({ id: "x", role: "assistant", text: "ok" });
  assert.equal(restored.role, "bot");
  assert.equal(restored.timestamp.getTime(), 0);
});

test("turns an unknown reply into a single bubble without any pending step", () => {
  const message = buildParseFailureMessage({ ok: true, type: "unknown", reply: "Non ho capito." });
  assert.equal(message.role, "bot");
  assert.equal(message.text, "Non ho capito.");
  assert.equal(message.awaitingConfirm, undefined);
  assert.equal(message.noAccountAction, undefined);
});

test("flags the missing-account case so the UI can offer the accounts shortcut", () => {
  const message = buildParseFailureMessage({ ok: true, type: "no_account", reply: "Nessun conto." });
  assert.equal(message.noAccountAction, true);
});

test("shows ready transactions immediately and queues the ones still missing data", () => {
  const transactions: ChatTransaction[] = [
    { type: "expense", reply: "pronta", parsed: expense, awaiting_confirm: true },
    { type: "expense", reply: "quanto?", parsed: { type: "expense" }, needs_amount: true },
    { type: "transfer", reply: "quale conto?", parsed: { type: "transfer" }, needs_account_pick: "from" },
  ];
  const { immediate, sequential } = partitionTransactions(transactions);
  assert.deepEqual(immediate.map((tx) => tx.reply), ["pronta"]);
  assert.deepEqual(sequential.map((tx) => tx.reply), ["quanto?", "quale conto?"]);
});

test("reads the missing amount from free text and moves the expense to confirmation", () => {
  const pending = botMessage({ parsed: { type: "expense", name: "Sushi" }, awaitingAmount: true });
  const outcome = applyAmountAnswer(pending, "24,50 €");
  assert.equal(outcome.status, "resolved");
  assert.equal(outcome.message.parsed?.amount, 24.5);
  assert.equal(outcome.message.awaitingAmount, false);
  assert.equal(outcome.message.awaitingConfirm, true);
});

test("rejects an unreadable amount without losing the pending step", () => {
  const pending = botMessage({ parsed: { type: "expense" }, awaitingAmount: true });
  const outcome = applyAmountAnswer(pending, "boh");
  assert.equal(outcome.status, "invalid_amount");
  assert.equal(outcome.message.awaitingAmount, true);
});

test("parses Italian amount formats", () => {
  assert.equal(parseAmountFallback("20"), 20);
  assert.equal(parseAmountFallback("20,50"), 20.5);
  assert.equal(parseAmountFallback("€ 12,99 euro"), 12.99);
  assert.equal(parseAmountFallback("niente"), null);
});

test("blocks a transfer when the user has fewer than two accounts", () => {
  const step = nextStepAfterAmount({ type: "transfer", amount: 50, accounts: [{ id: "acc-1", name: "Unico" }] });
  assert.equal(step.awaitingConfirm, false);
  assert.equal(step.awaitingAccountPick, undefined);
  assert.match(step.text, /almeno due conti/);
});

test("asks for the source account and then the destination account of a transfer", () => {
  const accounts = [
    { id: "acc-1", name: "Conto principale" },
    { id: "acc-2", name: "Contanti" },
  ];
  const fromStep = nextStepAfterAmount({ type: "transfer", amount: 50, accounts });
  assert.equal(fromStep.awaitingAccountPick, "from");

  const toStep = nextStepAfterAmount({
    type: "transfer",
    amount: 50,
    accounts,
    resolved_from_account_id: "acc-1",
    resolved_from_account_name: "Conto principale",
  });
  assert.equal(toStep.awaitingAccountPick, "to");
});

test("changing the category rebuilds the summary and returns to confirmation", () => {
  const message = botMessage({ parsed: expense, awaitingCategoryPick: true });
  const updated = applyCategorySelection(message, "Spesa");
  assert.equal(updated.parsed?.category, "Spesa");
  assert.equal(updated.awaitingCategoryPick, false);
  assert.equal(updated.awaitingConfirm, true);
  assert.equal(updated.categoryWasCorrected, true);
  assert.match(updated.text, /Spesa/);
});

test("changing the category of an income updates income_type/income_category, not category", () => {
  const income: ParsedData = {
    type: "income",
    amount: 1500,
    income_type: "Stipendio",
    name: "Stipendio",
    categories: ["Stipendio", "Regalo", "Rimborso"],
  };
  const message = botMessage({ parsed: income, awaitingCategoryPick: true });
  const updated = applyCategorySelection(message, "Regalo");
  assert.equal(updated.parsed?.income_type, "Regalo");
  assert.equal(updated.parsed?.income_category, "Regalo");
  assert.equal(updated.parsed?.category, undefined);
  assert.equal(updated.awaitingCategoryPick, false);
  assert.equal(updated.awaitingConfirm, true);
  assert.equal(updated.categoryWasCorrected, true);
  assert.match(updated.text, /Regalo/);
});

test("picking the single account of an expense triggers the save with that account", () => {
  const message = botMessage({ parsed: expense, awaitingAccountPick: "single" });
  const outcome = resolveAccountSelection(message, { id: "acc-1", name: "Conto principale" });
  assert.equal(outcome.action, "save");
  assert.deepEqual(outcome.saveOptions, { account_id: "acc-1" });
});

test("picking the source account only advances to the destination step", () => {
  const message = botMessage({ parsed: { ...expense, type: "transfer" }, awaitingAccountPick: "from" });
  const outcome = resolveAccountSelection(message, { id: "acc-1", name: "Conto principale" });
  assert.equal(outcome.action, "continue");
  assert.equal(outcome.message.awaitingAccountPick, "to");
  assert.equal(outcome.message.parsed?.resolved_from_account_id, "acc-1");
});

test("picking the destination account saves the transfer with both accounts", () => {
  const message = botMessage({
    parsed: {
      ...expense,
      type: "transfer",
      resolved_from_account_id: "acc-1",
      resolved_from_account_name: "Conto principale",
    },
    awaitingAccountPick: "to",
  });
  const outcome = resolveAccountSelection(message, { id: "acc-2", name: "Contanti" });
  assert.equal(outcome.action, "save");
  assert.deepEqual(outcome.saveOptions, { from_account_id: "acc-1", to_account_id: "acc-2" });
});

test("never offers the source account as destination of the same transfer", () => {
  const message = botMessage({
    parsed: {
      ...expense,
      type: "transfer",
      resolved_from_account_id: "acc-1",
    },
    awaitingAccountPick: "to",
  });
  assert.deepEqual(
    selectableAccounts(message).map((account) => account.id),
    ["acc-2"],
  );
});

test("cancelling clears every pending step of that message", () => {
  const message = botMessage({ parsed: expense, awaitingConfirm: true, awaitingAccountPick: "single" });
  const cancelled = applyCancellation(message);
  assert.equal(cancelled.awaitingConfirm, false);
  assert.equal(cancelled.awaitingAccountPick, undefined);
  assert.equal(cancelled.awaitingAmount, false);
  assert.equal(cancelled.awaitingCategoryPick, false);
  assert.match(cancelled.text, /annullat/i);
});

test("a successful save produces a saved bubble carrying the stored transaction", () => {
  const message = buildSaveResultMessage({ saved: true, reply: "Registrato!" }, expense);
  assert.equal(message.savedTransaction, true);
  assert.equal(message.text, "Registrato!");
  assert.equal(message.parsed?.type, "expense");
});

test("a failed save keeps the transaction out of the bubble and flags the missing account", () => {
  const message = buildSaveResultMessage({ saved: false, error: "no_account", reply: "Nessun conto." }, expense);
  assert.equal(message.savedTransaction, false);
  assert.equal(message.parsed, undefined);
  assert.equal(message.noAccountAction, true);
});
