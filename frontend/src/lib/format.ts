const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const num = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatINR(v: unknown): string {
  const n = typeof v === "string" ? Number(v) : (v as number);
  return typeof n === "number" && Number.isFinite(n) ? inr.format(n) : "—";
}
export function formatNum(v: unknown): string {
  const n = typeof v === "string" ? Number(v) : (v as number);
  return typeof n === "number" && Number.isFinite(n) ? num.format(n) : "—";
}
/** "30 Oct 2026". Date-only strings are parsed without timezone shift. */
export function formatDate(v: unknown): string {
  if (!v) return "—";
  const s = String(v);
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}
export function humanize(s: unknown): string {
  if (s === undefined || s === null || s === "") return "—";
  return String(s).replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}
