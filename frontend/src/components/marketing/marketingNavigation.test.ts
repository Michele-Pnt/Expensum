import assert from "node:assert/strict";
import test from "node:test";

test("desktop and mobile marketing navigation share every primary destination", async () => {
  const importedModule = await import("./marketingNavigation").catch(() => null);

  assert.ok(importedModule, "marketingNavigation must expose the shared navigation model");
  assert.deepEqual(
    importedModule.MARKETING_NAVIGATION.map((item: { href: string }) => item.href),
    ["/come-funziona", "/funzionalita", "/sicurezza", "/faq"],
  );
});

test("the public footer names the AI transparently without the retired assistant brand", async () => {
  const importedModule = await import("./marketingNavigation").catch(() => null);

  assert.ok(importedModule);
  assert.ok(importedModule.MARKETING_FOOTER_NAVIGATION.some(
    (item: { href: string; labelKey: string }) =>
      item.href === "/come-funziona-moneo" && item.labelKey === "footer.ai",
  ));
});
