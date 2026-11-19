import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "@/lib/api-client";

const BASE = "http://backend.test";

function mockFetch(response: Response | Error) {
  const fn = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

async function catchError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected ApiError");
}

afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("returns parsed JSON on success and sends auth + JSON body", async () => {
    const fetchMock = mockFetch(json({ id: 1 }));
    const data = await apiFetch<{ id: number }>(BASE, "/api/v1/things", {
      method: "POST",
      body: { name: "x" },
      token: "tok",
    });

    expect(data).toEqual({ id: 1 });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(url.toString()).toBe("http://backend.test/api/v1/things");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ name: "x" }));
    expect(init.headers).toMatchObject({
      Authorization: "Bearer tok",
      "Content-Type": "application/json",
    });
  });

  it("returns null for an empty 204 body", async () => {
    mockFetch(new Response(null, { status: 204 }));
    expect(await apiFetch(BASE, "/x", { method: "DELETE" })).toBeNull();
  });

  it("parses the error envelope", async () => {
    mockFetch(
      json(
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "Dữ liệu gửi lên không hợp lệ",
            details: [{ field: "items[0].quantity", issue: "must be >= 1" }],
            request_id: "req-123",
          },
        },
        400,
      ),
    );
    const error = await catchError(apiFetch(BASE, "/x"));
    expect(error.status).toBe(400);
    expect(error.code).toBe("VALIDATION_ERROR");
    expect(error.message).toBe("Dữ liệu gửi lên không hợp lệ");
    expect(error.details).toEqual([{ field: "items[0].quantity", issue: "must be >= 1" }]);
    expect(error.requestId).toBe("req-123");
  });

  it("falls back to a code from the status when the body is not an envelope", async () => {
    mockFetch(
      new Response("<html>slow down</html>", {
        status: 429,
        statusText: "Too Many Requests",
        headers: { "X-Request-ID": "hdr-1" },
      }),
    );
    const error = await catchError(apiFetch(BASE, "/x"));
    expect(error.code).toBe("RATE_LIMITED");
    expect(error.requestId).toBe("hdr-1");
  });

  it("maps unknown 5xx to INTERNAL_ERROR and keeps the body", async () => {
    mockFetch(json({ status: "degraded" }, 503));
    const error = await catchError(apiFetch(BASE, "/x"));
    expect(error.code).toBe("INTERNAL_ERROR");
    expect(error.body).toEqual({ status: "degraded" });
  });

  it("wraps network failures as NETWORK_ERROR", async () => {
    mockFetch(new TypeError("fetch failed"));
    const error = await catchError(apiFetch(BASE, "/x"));
    expect(error.status).toBe(0);
    expect(error.code).toBe("NETWORK_ERROR");
  });
});
