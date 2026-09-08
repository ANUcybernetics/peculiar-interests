const dateFormat = new Intl.DateTimeFormat("en-AU", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const longDateFormat = new Intl.DateTimeFormat("en-AU", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

/** "14 Aug 2026" from an ISO date; empty string for null. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  return dateFormat.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`));
}

export function formatDateLong(iso: string | null | undefined): string {
  if (!iso) return "";
  return longDateFormat.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`));
}

/** "Mary Aldred" from register-style "Aldred, Mary" parts. */
export function fullName(given: string, family: string): string {
  return `${given} ${family}`.trim();
}

export function pluralise(count: number, noun: string, plural = `${noun}s`): string {
  return `${count.toLocaleString("en-AU")} ${count === 1 ? noun : plural}`;
}

/** Collapse a free-text field to one line for tables and ledgers. */
export function oneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

const moneyFormat = new Intl.NumberFormat("en-AU", {
  style: "currency",
  currency: "AUD",
  maximumFractionDigits: 0,
});

/** "$3,837" from 3837.40. Rounds down: a total added up from declared values
 * is a floor, and rounding up would overstate it. */
export function formatMoney(amount: number): string {
  return moneyFormat.format(Math.floor(amount));
}
