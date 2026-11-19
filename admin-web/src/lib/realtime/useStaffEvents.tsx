"use client";

/**
 * Live staff events from GET /api/v1/staff/events (spec/SPEC-notifications.md).
 *
 * Uses fetch + ReadableStream instead of EventSource so the Authorization header can be sent.
 * Reconnects with backoff 1 s → 2 s → 5 s → 10 s; the server also closes the stream when the
 * access token expires, so every reconnect asks AuthProvider for a fresh token. After each
 * successful (re)connect `onReconnect` lets the screen reload its list (no replay in V1).
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
import { useAuth } from "@/lib/auth/AuthProvider";
import { SseParser } from "./sseParser";

export interface StaffEvent {
  event: string;
  entity_type: "FOOD_ORDER" | "HOUSEKEEPING" | "CHECKOUT" | "STAY";
  entity_id: string;
  status: string;
  room_number: string;
  actor: string;
  occurred_at: string;
}

export type ConnectionState = "connecting" | "open" | "closed";

type Listener = (event: StaffEvent) => void;

interface RealtimeContextValue {
  state: ConnectionState;
  subscribe: (listener: Listener) => () => void;
  onReconnect: (listener: () => void) => () => void;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

export const BACKOFF_MS = [1000, 2000, 5000, 10000];

export function StaffEventsProvider({
  children,
  baseUrl,
}: {
  children: ReactNode;
  baseUrl?: string;
}) {
  const { state: auth, getAccessToken } = useAuth();
  const [state, setState] = useState<ConnectionState>("connecting");
  const listeners = useRef(new Set<Listener>());
  const reconnectListeners = useRef(new Set<() => void>());
  const signedIn = auth.status === "authenticated";

  useEffect(() => {
    if (!signedIn) return;
    const origin = baseUrl ?? window.location.origin;
    let stopped = false;
    let attempt = 0;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const schedule = () => {
      if (stopped) return;
      const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
      attempt += 1;
      timer = setTimeout(() => void connect(), delay);
    };

    const connect = async () => {
      if (stopped) return;
      setState("connecting");
      const token = await getAccessToken();
      if (!token || stopped) {
        setState("closed");
        return;
      }
      controller = new AbortController();
      try {
        const response = await fetch(new URL("/api/v1/staff/events", origin), {
          headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
        setState("open");
        attempt = 0;
        reconnectListeners.current.forEach((listener) => listener());
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const parser = new SseParser();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          for (const item of parser.push(decoder.decode(value, { stream: true }))) {
            try {
              const payload = JSON.parse(item.data) as StaffEvent;
              listeners.current.forEach((listener) => listener({ ...payload, event: item.event }));
            } catch {
              // ignore a malformed event; the next reconnect reloads lists anyway
            }
          }
        }
      } catch {
        // network error or abort; fall through to reconnect
      }
      if (!stopped) {
        setState("closed");
        schedule();
      }
    };

    void connect();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [signedIn, baseUrl, getAccessToken]);

  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);
  const onReconnect = useCallback((listener: () => void) => {
    reconnectListeners.current.add(listener);
    return () => {
      reconnectListeners.current.delete(listener);
    };
  }, []);
  const value = useMemo(() => ({ state, subscribe, onReconnect }), [state, subscribe, onReconnect]);
  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

function useRealtime(): RealtimeContextValue {
  const value = useContext(RealtimeContext);
  if (!value) throw new Error("useStaffEvents must be used inside <StaffEventsProvider>");
  return value;
}

/** Calls `handler` for each staff event, and `onReconnect` after every (re)connection. */
export function useStaffEvents(handler: Listener, onReconnect?: () => void): ConnectionState {
  const { state, subscribe, onReconnect: listenReconnect } = useRealtime();
  const handlerRef = useRef(handler);
  const reconnectRef = useRef(onReconnect);
  handlerRef.current = handler;
  reconnectRef.current = onReconnect;

  useEffect(() => subscribe((event) => handlerRef.current(event)), [subscribe]);
  useEffect(() => listenReconnect(() => reconnectRef.current?.()), [listenReconnect]);
  return state;
}

export function useConnectionState(): ConnectionState {
  return useRealtime().state;
}
