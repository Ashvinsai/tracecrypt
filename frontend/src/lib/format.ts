/** Display helpers. Exact strings in, exact strings out; no amount arithmetic. */

/** Exact base-unit -> decimal string, never via Number. */
export function formatBaseUnits(baseUnits: string | null | undefined, decimals: number): string {
  if (baseUnits === null || baseUnits === undefined || baseUnits === "") return "—";
  if (decimals === 0) return baseUnits;
  const negative = baseUnits.startsWith("-");
  const digits = (negative ? baseUnits.slice(1) : baseUnits).padStart(decimals + 1, "0");
  const whole = digits.slice(0, digits.length - decimals);
  const fraction = digits.slice(digits.length - decimals);
  return `${negative ? "-" : ""}${whole}.${fraction}`;
}

/** Truncate a long address / hash for a table cell; the full value stays copyable. */
export function truncate(value: string | null | undefined, head = 6, tail = 4): string {
  if (!value) return "—";
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/** Compact UTC timestamp for dense tables. */
export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const iso = date.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)}Z`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().slice(0, 10);
}

/** Relative age from now, coarse and quiet (e.g. "3d ago"). */
export function relativeAge(value: string | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replace(/_/g, " ");
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function chainShort(key: string | null | undefined): string {
  switch ((key || "").toLowerCase()) {
    case "tron":
      return "TRON";
    case "ethereum":
    case "eth":
      return "ETH";
    case "bsc":
      return "BSC";
    case "base":
      return "BASE";
    default:
      return (key || "—").toUpperCase();
  }
}
