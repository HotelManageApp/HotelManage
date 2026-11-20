"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { Role } from "@/lib/auth/roles";
import { useConnectionState, useStaffEvents, type StaffEvent } from "@/lib/realtime/useStaffEvents";

const SOUND_KEY = "staff-sound-enabled";
const TOAST_MS = 6000;

/** Events that deserve a toast (and a beep) for each role. */
export function toastFor(role: Role, event: StaffEvent): string | null {
  const newOrder = event.entity_type === "FOOD_ORDER" && event.status === "PENDING";
  const newHk = event.entity_type === "HOUSEKEEPING" && event.status === "REQUESTED";
  const newCheckout = event.entity_type === "CHECKOUT" && event.status === "CHECKOUT_REQUESTED";
  const overdue = event.event === "order_overdue" || event.event === "housekeeping_overdue";
  if (event.event === "order_overdue") return role !== "HOUSEKEEPING" ? "orderOverdue" : null;
  if (event.event === "housekeeping_overdue")
    return role !== "KITCHEN" ? "housekeepingOverdue" : null;
  if (overdue) return null;
  if (newOrder && (role === "KITCHEN" || role === "RECEPTION")) return "newOrder";
  if (newHk && (role === "HOUSEKEEPING" || role === "RECEPTION")) return "newHousekeeping";
  if (newCheckout && role === "RECEPTION") return "newCheckout";
  return null;
}

function readSoundPreference(): boolean {
  try {
    return window.localStorage.getItem(SOUND_KEY) === "1";
  } catch {
    return false;
  }
}

function beep() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    osc.frequency.value = 880;
    osc.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
  } catch {
    // no audio available; the toast is enough
  }
}

interface Toast {
  id: number;
  text: string;
}

/** Connection dot, sound toggle and toasts for new work. Lives in the staff layout. */
export function RealtimeBar() {
  const t = useTranslations("Realtime");
  const { state } = useAuth();
  const connection = useConnectionState();
  const [sound, setSound] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const role = state.status === "authenticated" ? state.staff.role : null;

  useEffect(() => setSound(readSoundPreference()), []);

  const onEvent = useCallback(
    (event: StaffEvent) => {
      if (!role) return;
      const key = toastFor(role, event);
      if (!key) return;
      const id = Date.now() + Math.random();
      setToasts((list) => [...list, { id, text: t(key, { room: event.room_number }) }]);
      setTimeout(() => setToasts((list) => list.filter((toast) => toast.id !== id)), TOAST_MS);
      if (readSoundPreference()) beep();
    },
    [role, t],
  );
  useStaffEvents(onEvent);

  function toggleSound() {
    const next = !sound;
    setSound(next);
    try {
      window.localStorage.setItem(SOUND_KEY, next ? "1" : "0");
    } catch {
      // private mode: keep it for this page only
    }
  }

  return (
    <>
      <span
        className="flex items-center gap-2 text-xs"
        data-testid="connection"
        data-state={connection}
      >
        <span
          aria-hidden
          className={`inline-block h-2 w-2 rounded-full ${
            connection === "open"
              ? "bg-emerald-500"
              : connection === "connecting"
                ? "bg-amber-400"
                : "bg-red-500"
          }`}
        />
        {t(`connection.${connection}`)}
      </span>
      <button
        type="button"
        onClick={toggleSound}
        aria-pressed={sound}
        className="text-xs underline"
      >
        {sound ? t("soundOn") : t("soundOff")}
      </button>
      <div aria-live="polite" className="fixed right-4 bottom-4 z-20 space-y-2">
        {toasts.map((toast) => (
          <p
            key={toast.id}
            role="status"
            className="rounded bg-slate-900 px-4 py-2 text-sm text-white shadow"
          >
            {toast.text}
          </p>
        ))}
      </div>
    </>
  );
}
