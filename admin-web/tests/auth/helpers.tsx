import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { vi } from "vitest";
import { AuthProvider } from "@/lib/auth/AuthProvider";
import viMessages from "../../messages/vi.json";

export const BASE = "http://web.test";

export const STAFF = {
  id: "11111111-2222-3333-4444-555555555555",
  email: "bep@hotel.test",
  full_name: "Bep Truong",
  role: "KITCHEN" as const,
};

export function session(token = "access-1", expiresIn = 900, staff = STAFF) {
  return { access_token: token, token_type: "bearer", expires_in: expiresIn, staff };
}

export function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function envelope(status: number, code: string, headers: Record<string, string> = {}) {
  return json({ error: { code, message: code, details: [], request_id: "r" } }, status, headers);
}

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

/** Stubs fetch; each call is routed by "METHOD /path". Returns the mock for assertions. */
export function mockBackend(routes: Record<string, Handler | Handler[]>) {
  const queues = new Map(
    Object.entries(routes).map(([key, value]) => [key, Array.isArray(value) ? [...value] : value]),
  );
  const fn = vi.fn(async (input: URL | string, init: RequestInit = {}) => {
    const url = new URL(input.toString());
    const key = `${init.method ?? "GET"} ${url.pathname}`;
    const entry = queues.get(key);
    if (!entry) throw new Error(`unexpected request ${key}`);
    const handler = Array.isArray(entry) ? (entry.length > 1 ? entry.shift() : entry[0]) : entry;
    if (!handler) throw new Error(`no response left for ${key}`);
    return handler(url.toString(), init);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export function renderWithAuth(ui: ReactNode) {
  return render(
    <NextIntlClientProvider locale="vi" messages={viMessages}>
      <AuthProvider baseUrl={BASE}>{ui}</AuthProvider>
    </NextIntlClientProvider>,
  );
}
