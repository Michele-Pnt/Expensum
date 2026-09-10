import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const page = readFileSync(resolve(import.meta.dirname, "page.tsx"), "utf8");

test("groups expense and income catalogues inside the Categorie tab", () => {
  assert.match(page, /const \[categoryKind, setCategoryKind\] = useState<"expense" \| "income">\("expense"\)/);
  assert.match(page, /value=\{categoryKind\}/);
  assert.match(page, /onChange=\{\(_, kind\) => kind && setCategoryKind\(kind\)\}/);
  assert.match(page, /<ToggleButton value="expense">Spese<\/ToggleButton>/);
  assert.match(page, /<ToggleButton value="income">Entrate<\/ToggleButton>/);
  assert.match(page, /categoryKind === "expense" \? renderExpenseCategories\(\) : renderIncomeCategories\(\)/);
  assert.match(page, /label="Categorie di spesa"/);
  assert.match(page, /label="Categorie di entrata"/);
});

test("keeps the income tab navigation-only for category management", () => {
  assert.match(page, /onClick=\{\(\) => \{ setTab\(1\); setCategoryKind\("income"\); \}\}/);
  assert.match(page, /Gestisci categorie/);
  assert.match(page, /setCategoryKind\("income"\); \}\} sx=\{\{ minHeight: 44 \}\}/);
  assert.doesNotMatch(page, /incomeCategoryManagerOpen/);
});

test("lets people edit income-category context and delete with the expense-category action", () => {
  assert.match(page, /if \(entity === "incomeCategory"\) return \(/);
  assert.match(page, /label="Descrizione \(facoltativa\)"/);
  assert.match(page, /helperText="Aiuta l'assistente a classificare meglio entrate ambigue"/);
  assert.match(page, /onDelete=\{\(\) => handleDelete\("incomeCategory", row.id\)\}/);
  assert.doesNotMatch(page, /setIncomeCategoryArchived/);
});
