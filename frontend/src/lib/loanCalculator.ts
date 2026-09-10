/**
 * lib/loanCalculator.ts — reimplementazione TypeScript del motore di calcolo mutuo
 * (src/loan_calculator.py sul backend). Duplicazione deliberata: il calcolatore
 * pubblico è stateless e non deve fare alcuna chiamata al backend (vedi design
 * approvato). Stessa formula di ammortamento francese, stessa convenzione
 * (tan/taeg/spread in percentuale, es. 3.25 per 3,25%). Se cambia una delle due
 * implementazioni, l'altra va aggiornata in coppia.
 */

export interface AmortizationEntry {
  period: number;
  installment: number;
  interest: number;
  principal: number;
  residualBalance: number;
}

export interface LoanPreviewInput {
  principal: number;
  tanAnnual: number;
  durationMonths: number;
  providedTaeg?: number | null;
  upfrontFee?: number;
  monthlyFee?: number;
  startDate?: string | null;
  prepaymentAmount?: number;
  prepaymentDate?: string | null;
  prepaymentInstallment?: number;
  prepaymentMode?: "reduce_payment" | "reduce_term" | null;
}

export interface LoanPreview {
  installment: number;
  monthlyTotal: number;
  taeg: number;
  totalInterest: number;
  totalPaid: number;
  accessoryCosts: number;
  estimatedEndDate: string | null;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

/** Formats a local Date in the YYYY-MM-DD format accepted by native date inputs. */
export function formatDateInputValue(date: Date = new Date()): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function addMonthsToDate(value: string | null | undefined, months: number): string | null {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  const targetMonthIndex = date.getUTCMonth() + months;
  const targetYear = date.getUTCFullYear() + Math.floor(targetMonthIndex / 12);
  const targetMonth = ((targetMonthIndex % 12) + 12) % 12;
  const lastDayOfTargetMonth = new Date(Date.UTC(targetYear, targetMonth + 1, 0)).getUTCDate();
  const targetDay = Math.min(date.getUTCDate(), lastDayOfTargetMonth);

  return new Date(Date.UTC(targetYear, targetMonth, targetDay)).toISOString().slice(0, 10);
}

export function calculateInstallment(principal: number, tanAnnual: number, durationMonths: number): number {
  if (durationMonths <= 0) throw new Error("durationMonths deve essere positivo");
  const monthlyRate = tanAnnual / 100 / 12;
  if (monthlyRate === 0) return round2(principal / durationMonths);
  const installment = (principal * monthlyRate) / (1 - Math.pow(1 + monthlyRate, -durationMonths));
  return round2(installment);
}

export function buildAmortizationSchedule(
  principal: number,
  tanAnnual: number,
  durationMonths: number
): AmortizationEntry[] {
  const installment = calculateInstallment(principal, tanAnnual, durationMonths);
  const monthlyRate = tanAnnual / 100 / 12;
  let residual = principal;
  const schedule: AmortizationEntry[] = [];

  for (let period = 1; period <= durationMonths; period++) {
    const interest = residual * monthlyRate;
    let principalComponent: number;
    let payment: number;
    if (period === durationMonths) {
      principalComponent = residual;
      payment = principalComponent + interest;
    } else {
      principalComponent = installment - interest;
      payment = installment;
    }
    residual = Math.max(residual - principalComponent, 0);
    schedule.push({
      period,
      installment: round2(payment),
      interest: round2(interest),
      principal: round2(principalComponent),
      residualBalance: round2(residual),
    });
  }

  return schedule;
}

export function calculateTaeg(
  principal: number,
  tanAnnual: number,
  durationMonths: number,
  upfrontFee = 0,
  monthlyFee = 0
): number {
  const installment = calculateInstallment(principal, tanAnnual, durationMonths);
  const monthlyPayment = installment + monthlyFee;
  const netDisbursement = principal - upfrontFee;
  const n = durationMonths;

  const npv = (rate: number): number => {
    if (rate <= -1) return Infinity;
    let sum = 0;
    for (let t = 1; t <= n; t++) sum += monthlyPayment / Math.pow(1 + rate, t);
    return sum - netDisbursement;
  };

  let lo = 0;
  let hi = 1;
  while (npv(hi) > 0 && hi < 100) hi *= 2;

  for (let i = 0; i < 100; i++) {
    const mid = (lo + hi) / 2;
    const val = npv(mid);
    if (Math.abs(val) < 1e-9) {
      lo = hi = mid;
      break;
    }
    if (val > 0) lo = mid;
    else hi = mid;
  }

  const monthlyIrr = (lo + hi) / 2;
  const taeg = (Math.pow(1 + monthlyIrr, 12) - 1) * 100;
  return Math.round(taeg * 10000) / 10000;
}

/** Calcola l'anteprima locale, privilegiando il TAEG comunicato dalla banca. */
export function calculateLoanPreview({
  principal,
  tanAnnual,
  durationMonths,
  providedTaeg = null,
  upfrontFee = 0,
  monthlyFee = 0,
  startDate = null,
  prepaymentAmount = 0,
  prepaymentDate = null,
  prepaymentInstallment,
  prepaymentMode = null,
}: LoanPreviewInput): LoanPreview {
  const originalInstallment = calculateInstallment(principal, tanAnnual, durationMonths);
  let effectiveInstallment = originalInstallment;
  let effectiveDuration = durationMonths;
  let schedule = buildAmortizationSchedule(principal, tanAnnual, durationMonths);
  const amount = Math.min(Math.max(prepaymentAmount || 0, 0), principal);
  if (amount > 0 && prepaymentMode) {
    let period = Number.isFinite(prepaymentInstallment) && (prepaymentInstallment ?? 0) > 0
      ? Math.floor(prepaymentInstallment as number)
      : 1;
    if (prepaymentDate && startDate) {
      const start = new Date(`${startDate}T00:00:00Z`);
      const date = new Date(`${prepaymentDate}T00:00:00Z`);
      if (!Number.isNaN(start.getTime()) && !Number.isNaN(date.getTime())) {
        period = Math.floor((date.getUTCFullYear() - start.getUTCFullYear()) * 12
          + date.getUTCMonth() - start.getUTCMonth()) + 1;
      }
    }
    period = Math.min(Math.max(period, 1), durationMonths);
    const balance = Math.max(schedule[period - 1]?.residualBalance - amount, 0);
    const remaining = durationMonths - period;
    const postInstallment = prepaymentMode === "reduce_payment" && remaining > 0
      ? calculateInstallment(balance, tanAnnual, remaining)
      : originalInstallment;
    effectiveInstallment = postInstallment;
    if (remaining > 0 && balance > 0) {
      const postSchedule = buildAmortizationSchedule(balance, tanAnnual, remaining);
      if (prepaymentMode === "reduce_payment") {
        const monthlyRate = tanAnnual / 100 / 12;
        let residual = balance;
        for (let i = 0; i < postSchedule.length; i++) {
          const interest = residual * monthlyRate;
          const principalPart = i === postSchedule.length - 1
            ? residual : Math.max(postInstallment - interest, 0);
          residual = Math.max(residual - principalPart, 0);
          postSchedule[i] = { period: i + 1, installment: round2(principalPart + interest),
            interest: round2(interest), principal: round2(principalPart),
            residualBalance: round2(residual) };
        }
      }
      if (prepaymentMode === "reduce_term") {
        schedule = schedule.slice(0, period).concat(
          postSchedule.filter((entry) => entry.period <= remaining)
            .map((entry) => ({ ...entry, period: entry.period + period }))
        );
      } else {
        schedule = schedule.slice(0, period).concat(
          postSchedule.map((entry) => ({ ...entry, period: entry.period + period }))
        );
      }
      // For a reduced term, rebuild with the original payment and stop when paid.
      if (prepaymentMode === "reduce_term") {
        let residual = balance;
        const monthlyRate = tanAnnual / 100 / 12;
        const tail: AmortizationEntry[] = [];
        for (let i = 1; i <= remaining && residual > 0.005; i++) {
          const interest = residual * monthlyRate;
          const principalPart = Math.min(Math.max(originalInstallment - interest, 0), residual);
          residual -= principalPart;
          tail.push({ period: period + i, installment: round2(principalPart + interest),
            interest: round2(interest), principal: round2(principalPart),
            residualBalance: round2(Math.max(residual, 0)) });
        }
        schedule = schedule.slice(0, period).concat(tail);
        effectiveDuration = period + tail.length;
      }
      if (prepaymentMode === "reduce_payment") effectiveDuration = durationMonths;
    }
  }
  const installment = effectiveInstallment;
  const totalInterest = round2(schedule.reduce((sum, entry) => sum + entry.interest, 0));
  const accessoryCosts = round2(upfrontFee + monthlyFee * effectiveDuration);

  return {
    installment,
    monthlyTotal: round2(installment + monthlyFee),
    taeg: providedTaeg ?? calculateTaeg(
      principal, tanAnnual, durationMonths, upfrontFee, monthlyFee
    ),
    totalInterest,
    accessoryCosts,
    totalPaid: round2(principal + totalInterest + accessoryCosts),
    estimatedEndDate: addMonthsToDate(startDate, effectiveDuration),
  };
}
