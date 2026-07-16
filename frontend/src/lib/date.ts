/** Formatta una data ISO ("YYYY-MM-DD") in formato italiano "GG-MM-AAAA" per la sola visualizzazione. */
export function formatDateIt(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const [year, month, day] = isoDate.split("-");
  if (!year || !month || !day) return isoDate;
  return `${day}-${month}-${year}`;
}
