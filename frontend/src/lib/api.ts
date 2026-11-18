// Shared API client for the FastAPI backend. All network calls go through here.
export const API_BASE_URL: string = (
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

const SESSION_KEY = "irm.session";

export type User = Record<string, any> & {
  id?: number | string;
  email?: string;
  full_name?: string;
  permissions?: unknown;
  role?: unknown;
};
export type Session = { token: string; user: User };

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}
export function setSession(s: Session | null) {
  if (typeof window === "undefined") return;
  if (s) window.localStorage.setItem(SESSION_KEY, JSON.stringify(s));
  else window.localStorage.removeItem(SESSION_KEY);
  window.dispatchEvent(new Event("irm-session"));
}

function detailToString(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((d: any) => {
        const loc = Array.isArray(d?.loc) ? d.loc.filter((x: any) => x !== "body").join(".") : "";
        return loc ? `${loc}: ${d?.msg ?? ""}` : (d?.msg ?? JSON.stringify(d));
      })
      .join("; ");
  if (typeof detail === "object") return (detail as any).message ?? JSON.stringify(detail);
  return String(detail);
}

const STATUS_FALLBACK: Record<number, string> = {
  401: "Your session is invalid or has expired. Please sign in again.",
  403: "You don't have permission to access this.",
  404: "Not found.",
  429: "Too many requests. Please wait a moment and try again.",
};

type Opts = { method?: string; body?: unknown; auth?: boolean; query?: Record<string, unknown> };

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const { method = "GET", body, auth = true, query } = opts;
  const url = new URL(API_BASE_URL + path);
  if (query)
    for (const [k, v] of Object.entries(query))
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const session = getSession();
  if (auth && session?.token) headers["Authorization"] = `Bearer ${session.token}`;

  let res: Response;
  try {
    res = await fetch(url.toString(), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : null,
    });
  } catch {
    throw new ApiError(0, `Could not reach the server at ${API_BASE_URL}. Check that it is running.`);
  }
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail =
      detailToString(data?.detail ?? data?.message ?? (typeof data === "string" ? data : "")) ||
      STATUS_FALLBACK[res.status] ||
      `Request failed (${res.status})`;
    if (res.status === 401 && auth && session) {
      setSession(null);
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login"))
        window.location.assign("/login?expired=1");
    }
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

/** Accepts either a bare array or a paginated/wrapped object. */
export function asList<T = any>(data: any): T[] {
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object")
    for (const k of ["items", "results", "data", "rows", "users", "orders", "projects", "lines"])
      if (Array.isArray(data[k])) return data[k];
  return [];
}
export function totalOf(data: any): number | undefined {
  if (data && typeof data === "object" && !Array.isArray(data))
    for (const k of ["total", "count", "total_count"]) if (typeof data[k] === "number") return data[k];
  return undefined;
}

/** First defined value among candidate keys. */
export function pick(obj: any, ...keys: string[]): any {
  if (!obj) return undefined;
  for (const k of keys) {
    const v = k.split(".").reduce((o, p) => (o == null ? undefined : o[p]), obj);
    if (v !== undefined && v !== null) return v;
  }
  return undefined;
}

export function permissionsOf(user: User | null | undefined): string[] {
  if (!user) return [];
  const raw =
    (user.permissions as any) ??
    (user.role as any)?.permissions ??
    (user as any).permission_codes ??
    [];
  const list = Array.isArray(raw) ? raw : typeof raw === "object" ? Object.keys(raw).filter((k) => raw[k]) : [];
  return list.map((p: any) => (typeof p === "string" ? p : (p?.code ?? p?.name ?? ""))).filter(Boolean);
}
export const hasPermission = (u: User | null | undefined, code: string) => permissionsOf(u).includes(code);

export const endpoints = {
  login: (email: string, password: string) =>
    api<any>("/api/auth/login", { method: "POST", body: { email, password }, auth: false }),
  authOptions: () => api<any>("/api/auth/options", { auth: false }),
  signup: (body: Record<string, unknown>) => api<any>("/api/auth/signup", { method: "POST", body, auth: false }),
  dashboardSummary: () => api<any>("/api/dashboard/summary"),
  project: (id: number | string) => api<any>("/api/projects/" + encodeURIComponent(String(id))),
  projectRequirements: (id: number | string) => api<any>("/api/projects/" + encodeURIComponent(String(id)) + "/requirements"),
  projectRisk: (id: number | string) => api<any>("/api/risk/shortages", { query: { project_id: id } }),
  inventoryByMaterial: (id: number | string) => api<any>("/api/inventory", { query: { material_id: id, limit: 500, offset: 0 } }),
  riskSummary: () => api<any>("/api/risk/summary"),
  shortages: () => api<any>("/api/risk/shortages", { query: { exclude_ok: true } }),
  inventory: (q: Record<string, unknown>) => api<any>("/api/inventory", { query: q }),
  fulfillmentOptions: (lineId: number) => api<any>("/api/inventory/requirements/" + lineId + "/options"),
  allocateFreeStock: (lineId: number, body: Record<string, unknown>) => api<any>("/api/inventory/requirements/" + lineId + "/allocations", { method: "POST", body }),
  transferAllocation: (body: Record<string, unknown>) => api<any>("/api/inventory/transfers", { method: "POST", body }),
  transferHistory: (project_id?: number) => api<any>("/api/inventory/transfers", { query: { project_id } }),
  warehouses: () => api<any>("/api/warehouses"),
  purchaseOrders: () => api<any>("/api/purchase-orders", { query: { open_only: true } }),
  purchaseOrder: (id: string) => api<any>(`/api/purchase-orders/${encodeURIComponent(id)}`),
  estimateModel: () => api<any>("/api/estimates/model"),
  estimatePreview: (query: Record<string, unknown>) => api<any>("/api/estimates/preview", { query }),
  inventoryChat: (question: string, conversation_id?: string) =>
    api<any>("/api/assistant/chat", { method: "POST", body: { question, conversation_id: conversation_id ?? null } }),
  adminUsers: (status: string) => api<any>("/api/admin/users", { query: { status } }),
  adminAction: (id: string | number, action: "approve" | "reject" | "disable" | "enable", body?: unknown) =>
    api<any>(`/api/admin/users/${id}/${action}`, { method: "POST", body }),
  adminRole: (id: string | number, body: unknown) =>
    api<any>(`/api/admin/users/${id}/role`, { method: "POST", body }),
};
