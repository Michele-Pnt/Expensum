import assert from "node:assert/strict";
import test from "node:test";

import { calculateLoanPreview, calculateTaeg, formatDateInputValue } from "./loanCalculator";

test("formats a local date for native date inputs", () => {
  assert.equal(formatDateInputValue(new Date(2026, 7, 24)), "2026-08-24");
});

test("returns total interest, total paid, accessory costs and estimated end date", () => {
  const preview = calculateLoanPreview({
    principal: 100_000,
    tanAnnual: 3,
    durationMonths: 120,
    upfrontFee: 1_000,
    monthlyFee: 5,
    startDate: "2026-08-24",
  });

  assert.equal(preview.totalInterest, 15_872.9);
  assert.equal(preview.accessoryCosts, 1_600);
  assert.equal(preview.totalPaid, 117_472.9);
  assert.equal(preview.estimatedEndDate, "2036-08-24");
});

test("clamps the estimated end date to the last valid day of the target month", () => {
  const preview = calculateLoanPreview({
    principal: 100_000,
    tanAnnual: 3,
    durationMonths: 1,
    startDate: "2027-01-31",
  });
  const leapYearPreview = calculateLoanPreview({
    principal: 100_000,
    tanAnnual: 3,
    durationMonths: 1,
    startDate: "2028-01-31",
  });

  assert.equal(preview.estimatedEndDate, "2027-02-28");
  assert.equal(leapYearPreview.estimatedEndDate, "2028-02-29");
});

test("does not let a provided TAEG change the installment or interest", () => {
  const withoutTaeg = calculateLoanPreview({
    principal: 100_000,
    tanAnnual: 3,
    durationMonths: 120,
    startDate: "2026-08-24",
  });
  const withTaeg = calculateLoanPreview({
    principal: 100_000,
    tanAnnual: 3,
    durationMonths: 120,
    providedTaeg: 4.25,
    startDate: "2026-08-24",
  });

  assert.equal(withTaeg.installment, withoutTaeg.installment);
  assert.equal(withTaeg.totalInterest, withoutTaeg.totalInterest);
  assert.equal(withTaeg.taeg, 4.25);
});

test("uses the TAEG provided by the user in the loan preview", () => {
  const preview = calculateLoanPreview({
    principal: 200_000,
    tanAnnual: 3,
    durationMonths: 300,
    providedTaeg: 3.72,
  });

  assert.equal(preview.taeg, 3.72);
  assert.ok(preview.installment > 0);
});

test("calculates the TAEG from upfront and monthly costs when it is not provided", () => {
  const preview = calculateLoanPreview({
    principal: 200_000,
    tanAnnual: 3,
    durationMonths: 300,
    upfrontFee: 500,
    monthlyFee: 3,
  });

  assert.equal(preview.taeg, calculateTaeg(200_000, 3, 300, 500, 3));
});

test("includes the monthly collection fee in the preview total", () => {
  const preview = calculateLoanPreview({
    principal: 200_000,
    tanAnnual: 3,
    durationMonths: 300,
    monthlyFee: 50,
  });

  assert.equal(preview.monthlyTotal, preview.installment + 50);
});
