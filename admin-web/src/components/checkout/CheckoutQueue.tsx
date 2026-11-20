"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { OPEN_STATUSES, type CheckoutRequest } from "@/lib/checkout/types";
import { minutesSince, vnd } from "@/lib/orders/types";
import { useStaffEvents } from "@/lib/realtime/useStaffEvents";

/** Reception's express checkout queue: open requests first, finished ones of the last day below. */
export function CheckoutQueue() {
  const t = useTranslations("Checkout");
  const { authFetch } = useAuth();
  const [requests, setRequests] = useState<CheckoutRequest[] | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      setRequests(await authFetch<CheckoutRequest[]>("/api/v1/checkout-requests"));
      setError(false);
    } catch {
      setError(true);
    }
  }, [authFetch]);

  useEffect(() => {
    void load();
  }, [load]);

  useStaffEvents(
    (event) => {
      if (event.entity_type === "CHECKOUT" || event.entity_type === "FOOD_ORDER") void load();
    },
    () => void load(),
  );

  if (error) return <p role="alert">{t("loadError")}</p>;
  if (!requests) return <p className="text-slate-500">{t("loading")}</p>;
  const open = requests.filter((r) => OPEN_STATUSES.includes(r.status));
  const finished = requests.filter((r) => !OPEN_STATUSES.includes(r.status));

  const card = (r: CheckoutRequest) => (
    <li key={r.id}>
      <Link
        href={`/reception/checkout/${r.id}`}
        data-testid={`checkout-${r.id}`}
        className={`block space-y-1 rounded border p-3 hover:bg-slate-50 ${
          r.overdue ? "border-2 border-red-600" : "border-slate-200"
        }`}
      >
        <span className="flex items-baseline justify-between gap-2">
          <strong className="text-xl">{t("roomLabel", { room: r.room_number })}</strong>
          <span className="rounded bg-slate-100 px-2 text-xs">{t(`status.${r.status}`)}</span>
        </span>
        <span className="block text-sm text-slate-600">
          {r.guest_name ?? "—"} · {t("sentAgo", { minutes: minutesSince(r.created_at) })}
          {r.feedback_rating !== null && ` · ${"★".repeat(r.feedback_rating)}`}
        </span>
        {r.open_orders > 0 && (
          <span className="block text-sm font-semibold text-red-700">
            {t("openOrders", { count: r.open_orders })}
          </span>
        )}
        {r.total_vnd !== null && <span className="block text-sm">{vnd(r.total_vnd)}</span>}
        {r.reject_reason && <span className="block text-xs text-slate-500">{r.reject_reason}</span>}
      </Link>
    </li>
  );

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{t("queueTitle")}</h1>
      {open.length === 0 ? (
        <p className="text-sm text-slate-500">{t("queueEmpty")}</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{open.map(card)}</ul>
      )}
      {finished.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm">
            {t("finished", { count: finished.length })}
          </summary>
          <ul className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{finished.map(card)}</ul>
        </details>
      )}
    </section>
  );
}
