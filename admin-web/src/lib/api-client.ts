/**
 * Thin fetch wrapper for backend-api. Every non-2xx response becomes an ApiError carrying the
 * shared error envelope: {"error": {"code", "message", "details", "request_id"}} (SPEC-foundation).
 */

export interface ApiErrorDetail {
  field?: string;
  issue?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorDetail[];
  readonly requestId: string | null;
  /** Parsed response body, kept for endpoints whose error body is not an envelope (e.g. /health). */
  readonly body: unknown;

  constructor(
    status: number,
    code: string,
    message: string,
    details: ApiErrorDetail[] = [],
    requestId: string | null = null,
    body: unknown = undefined,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
    this.body = body;
  }
}

const STATUS_CODES: Record<number, string> = {
  400: "BAD_REQUEST",
  401: "UNAUTHORIZED",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  409: "CONFLICT",
  429: "RATE_LIMITED",
};

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  cache?: RequestCache;
}

function isEnvelope(value: unknown): value is {
  error: { code: string; message: string; details?: ApiErrorDetail[]; request_id?: string };
} {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

export async function apiFetch<T>(
  baseUrl: string,
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.token) headers.Authorization = `Bearer ${options.token}`;

  let response: Response;
  try {
    response = await fetch(new URL(path, baseUrl), {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      cache: options.cache,
    });
  } catch (cause) {
    const error = new ApiError(0, "NETWORK_ERROR", "Network request failed");
    error.cause = cause;
    throw error;
  }

  const payload = await readJson(response);
  if (response.ok) return payload as T;

  const headerRequestId = response.headers.get("X-Request-ID");
  if (isEnvelope(payload)) {
    const { code, message, details, request_id } = payload.error;
    throw new ApiError(
      response.status,
      code,
      message,
      details ?? [],
      request_id ?? headerRequestId,
      payload,
    );
  }
  const fallback =
    STATUS_CODES[response.status] ?? (response.status >= 500 ? "INTERNAL_ERROR" : "BAD_REQUEST");
  throw new ApiError(
    response.status,
    fallback,
    response.statusText || fallback,
    [],
    headerRequestId,
    payload,
  );
}
