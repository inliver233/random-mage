import { getAdminToken } from "../auth/tokenStorage";

export type ApiErrorBody = {
  ok: false;
  code: string;
  message: string;
  request_id: string;
  details: Record<string, unknown>;
};

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody | null;

  constructor(message: string, options: { status: number; body?: ApiErrorBody | null }) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.body = options.body ?? null;
  }
}

function getApiBaseUrl(): string {
  const raw = (import.meta.env.VITE_API_BASE_URL || "").trim();
  return raw.endsWith("/") ? raw.slice(0, -1) : raw;
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const base = getApiBaseUrl();
  const url = base ? base + path : path;

  const headers = new Headers(init?.headers || {});
  const token = getAdminToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Content-Type") && init?.body) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(url, { ...init, headers });
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await apiFetch(path, init);
  const text = await resp.text();
  const contentType = resp.headers.get("content-type") || "";
  const isJson = contentType.toLowerCase().includes("application/json");

  let data: unknown = null;
  if (text && isJson) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (resp.ok) {
    if (!isJson) throw new ApiError("Response is not JSON", { status: resp.status });
    return data as T;
  }

  const body = data && typeof data === "object" ? (data as ApiErrorBody) : null;
  const msg =
    body && typeof body.message === "string" && body.message.trim()
      ? body.message
      : `HTTP ${resp.status}`;
  throw new ApiError(msg, { status: resp.status, body });
}
