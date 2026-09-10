import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

test("does not feed sustainability draft updates back into panel initialization", () => {
  const wizardSource = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");
  const panelSource = readFileSync(
    join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"),
    "utf8",
  );

  assert.match(wizardSource, /const handleDraftSustainabilityInputChange = useCallback/);
  assert.match(wizardSource, /sustainabilityInputsEqual\(current, input\) \? current : input/);
  assert.match(wizardSource, /onDraftInputChange=\{handleDraftSustainabilityInputChange\}/);
  assert.match(panelSource, /const initialDraftSignature = useMemo/);
  assert.match(panelSource, /lastAppliedDraftSignature !== initialDraftSignature/);
});
