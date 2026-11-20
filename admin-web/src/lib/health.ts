import { ApiError, apiFetch } from "./api-client";

export interface BackendHealth {
  status: "ok" | "degraded";
  db: "ok" | "error";
  version: string;
}

function isBackendHealth(value: unknown): value is BackendHealth {
  return (
    typeof value === "object" &&
    value !== null &&
    "status" in value &&
    "db" in value &&
    "version" in value
  );
}

export type HealthResult = { reachable: true; health: BackendHealth } | { reachable: false };

/** Calls backend /health. A 503 still carries a health body (db down), so it is not "unreachable". */
export async function getBackendHealth(baseUrl: string): Promise<HealthResult> {
  try {
    const health = await apiFetch<BackendHealth>(baseUrl, "/health", { cache: "no-store" });
    return { reachable: true, health };
  } catch (error) {
    if (error instanceof ApiError && error.status === 503 && isBackendHealth(error.body)) {
      return { reachable: true, health: error.body };
    }
    return { reachable: false };
  }
}
