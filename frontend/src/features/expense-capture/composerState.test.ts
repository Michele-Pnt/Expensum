import assert from "node:assert/strict";
import test from "node:test";

import {
  hasCompletedSave,
  hasPendingCapture,
  isAwaitingUser,
  isNonFinancialReply,
} from "./composerState";
import type { CaptureMessage } from "./types";

const idle = { inputText: "", isLoading: false, isRecording: false, awaitingUser: false };

function bot(overrides: Partial<CaptureMessage> = {}): CaptureMessage {
  return { id: "bot-1", role: "bot", text: "ok", timestamp: new Date(0), status: "sent", ...overrides };
}

test("an untouched composer closes without asking anything", () => {
  assert.equal(hasPendingCapture(idle), false);
});

test("whitespace alone is not pending work", () => {
  assert.equal(hasPendingCapture({ ...idle, inputText: "   \n " }), false);
  assert.equal(hasPendingCapture({ ...idle, inputText: " 24 € spesa" }), true);
});

test("an upload, a recording or an open step all count as pending work", () => {
  assert.equal(hasPendingCapture({ ...idle, isLoading: true }), true);
  assert.equal(hasPendingCapture({ ...idle, isRecording: true }), true);
  assert.equal(hasPendingCapture({ ...idle, awaitingUser: true }), true);
});

test("a reply with no transaction and nothing pending sends the user back to the chat", () => {
  assert.equal(
    isNonFinancialReply({ lastBotMessage: bot(), awaitingUser: false, hasSaved: false, isLoading: false }),
    true,
  );
});

test("a transaction waiting for confirmation is never treated as a non-financial reply", () => {
  assert.equal(
    isNonFinancialReply({
      lastBotMessage: bot({ parsed: { type: "expense", amount: 24 }, awaitingConfirm: true }),
      awaitingUser: true,
      hasSaved: false,
      isLoading: false,
    }),
    false,
  );
});

test("neither a saved movement nor an in-flight request offers the chat shortcut", () => {
  assert.equal(
    isNonFinancialReply({ lastBotMessage: bot({ savedTransaction: true }), awaitingUser: false, hasSaved: true, isLoading: false }),
    false,
  );
  assert.equal(
    isNonFinancialReply({ lastBotMessage: bot(), awaitingUser: false, hasSaved: false, isLoading: true }),
    false,
  );
});

test("a technical error is not a command: no chat shortcut after a failed request", () => {
  assert.equal(
    isNonFinancialReply({
      lastBotMessage: bot({ isError: true, text: "Errore di rete." }),
      awaitingUser: false,
      hasSaved: false,
      isLoading: false,
    }),
    false,
  );
});

test("an empty conversation offers nothing", () => {
  assert.equal(isNonFinancialReply({ awaitingUser: false, hasSaved: false, isLoading: false }), false);
});

test("the success state appears only once every step is closed", () => {
  const saved = [bot({ savedTransaction: true })];
  assert.equal(hasCompletedSave(saved, false, false), true);
  assert.equal(hasCompletedSave(saved, true, false), false);
  assert.equal(hasCompletedSave(saved, false, true), false);
  assert.equal(hasCompletedSave([bot()], false, false), false);
});

test("any open step marks the flow as waiting for the user", () => {
  assert.equal(isAwaitingUser([bot({ awaitingConfirm: true })]), true);
  assert.equal(isAwaitingUser([bot({ awaitingAmount: true })]), true);
  assert.equal(isAwaitingUser([bot({ awaitingAccountPick: "single" })]), true);
  assert.equal(isAwaitingUser([bot({ awaitingCategoryPick: true })]), true);
  assert.equal(isAwaitingUser([bot()]), false);
});
