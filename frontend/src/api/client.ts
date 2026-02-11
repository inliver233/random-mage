import { getAdminToken } from "../auth/tokenStorage";

export type ApiErrorBody = {
  ok: false;
  code: string;
  message: string;
  request_id: string;
  details: Record<string, unknown>;
};

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

