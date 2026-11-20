import "server-only";

/** Server-side configuration. Throws with the variable name when something is missing. */
export function backendUrl(): string {
  const value = process.env.BACKEND_URL;
  if (!value) throw new Error("Missing required environment variable: BACKEND_URL");
  return value;
}
