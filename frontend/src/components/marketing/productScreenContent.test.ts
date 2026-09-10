import assert from "node:assert/strict";
import test from "node:test";

test("marketing previews use complete, anonymized data from real product flows", async () => {
  const importedModule = await import("./productScreenContent").catch(() => null);

  assert.ok(importedModule, "productScreenContent must expose the public preview data");
  const content = importedModule.PRODUCT_SCREEN_CONTENT;

  assert.deepEqual(Object.keys(content), ["capture", "overview", "goals", "report"]);
  assert.equal(content.capture.transaction.name, "Sushi");
  assert.equal(content.capture.transaction.category, "Ristoranti & Fast Food");
  assert.equal(content.overview.movements.length, 3);
  assert.equal(content.goals.items[0].name, "Weekend a Lisbona");
  assert.deepEqual(
    content.report.items.map((item: { type: string }) => item.type),
    ["Settimanale", "Mensile"],
  );
});
