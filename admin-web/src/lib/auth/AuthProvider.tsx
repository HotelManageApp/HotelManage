"use client";

/**
 * Staff session in the browser (spec/SPEC-staff-auth.md, admin-web).
 *
 * - The access token lives only in memory (a ref), never in localStorage/sessionStorage/cookies.
 * - The refresh token is an HttpOnly cookie set by the backend; we only call /auth/refresh.
 * - On page load we try /auth/refresh to restore the session; we refresh ~1 minute before expiry.
 * - `authFetch` retries once after refreshing on 401, then signs the user out.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, apiFetch, type ApiRequestOptions } from "@/lib/api-client";
import type { Role } from "./roles";

export interface StaffProfile {
  id: string;
  email: string;
  full_name: string;
  role: Role;
}

interface TokenResponse {
  access_token: string;
  expires_in: number;
  staff: StaffProfile;
}

export type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; staff: StaffProfile };

export interface AuthContextValue {
  state: AuthState;
  login: (email: string, password: string) => Promise<StaffProfile>;
  logout: () => Promise<void>;
  authFetch: <T>(path: string, options?: Omit<ApiRequestOptions, "token">) => Promise<T>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const REFRESH_EARLY_SECONDS = 60;

function defaultBaseUrl(): string {
  return typeof window === "undefined" ? "http://localhost" : window.location.origin;
}

export function AuthProvider({
  children,
  baseUrl = defaultBaseUrl(),
}: {
  children: ReactNode;
  baseUrl?: string;
}) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const tokenRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshing = useRef<Promise<string | null> | null>(null);

  const clearTimer = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  };

  const signOutLocally = useCallback(() => {
    clearTimer();
    tokenRef.current = null;
    setState({ status: "anonymous" });
  }, []);

  const accept = useCallback((session: TokenResponse, scheduleRefresh: () => void) => {
    tokenRef.current = session.access_token;
    setState({ status: "authenticated", staff: session.staff });
    clearTimer();
    const delay = Math.max(5, session.expires_in - REFRESH_EARLY_SECONDS) * 1000;
    timerRef.current = setTimeout(scheduleRefresh, delay);
  }, []);

  // One refresh at a time; concurrent callers share the same promise.
  const refresh = useCallback((): Promise<string | null> => {
    if (refreshing.current) return refreshing.current;
    const run = (async () => {
      try {
        const session = await apiFetch<TokenResponse>(baseUrl, "/api/v1/staff/auth/refresh", {
          method: "POST",
          credentials: "same-origin",
        });
        accept(session, () => void refresh());
        return session.access_token;
      } catch {
        signOutLocally();
        return null;
      } finally {
        refreshing.current = null;
      }
    })();
    refreshing.current = run;
    return run;
  }, [accept, baseUrl, signOutLocally]);

  useEffect(() => {
    void refresh();
    return clearTimer;
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await apiFetch<TokenResponse>(baseUrl, "/api/v1/staff/auth/login", {
        method: "POST",
        body: { email, password },
        credentials: "same-origin",
      });
      accept(session, () => void refresh());
      return session.staff;
    },
    [accept, baseUrl, refresh],
  );

  const logout = useCallback(async () => {
    try {
      await apiFetch(baseUrl, "/api/v1/staff/auth/logout", {
        method: "POST",
        credentials: "same-origin",
      });
    } catch {
      // Signing out locally is what matters; the refresh token expires on its own.
    } finally {
      signOutLocally();
    }
  }, [baseUrl, signOutLocally]);

  const authFetch = useCallback(
    async <T,>(path: string, options: Omit<ApiRequestOptions, "token"> = {}): Promise<T> => {
      const token = tokenRef.current ?? (await refresh());
      if (!token) throw new ApiError(401, "UNAUTHORIZED", "Not signed in");
      try {
        return await apiFetch<T>(baseUrl, path, { ...options, token });
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        const renewed = await refresh();
        if (!renewed) throw error;
        return apiFetch<T>(baseUrl, path, { ...options, token: renewed });
      }
    },
    [baseUrl, refresh],
  );

  const value = useMemo(
    () => ({ state, login, logout, authFetch }),
    [state, login, logout, authFetch],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
