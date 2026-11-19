"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { ETA_CHOICES, minutesSince, NEXT_STEP, type StaffOrder } from "@/lib/orders/types";

export interface OrderActions {
  advance: (order: StaffOrder, estimatedMinutes?: number) => Promise<void>;
  reject: (order: StaffOrder, reason: string) => Promise<void>;
}

/** One order on the kitchen board: big room number, dishes and notes, one main action. */
export function OrderCard({ order, actions }: { order: StaffOrder; actions: OrderActions }) {
  const t = useTranslations("Kitchen");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const next = NEXT_STEP[order.status];

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      data-testid={`order-${order.room_number}`}
      data-status={order.status}
      className={`space-y-2 rounded border bg-white p-3 shadow-sm ${
        order.overdue ? "border-2 border-red-600" : "border-slate-200"
      }`}
    >
      <header className="flex items-baseline justify-between">
        <h3 className="text-2xl font-bold">{t("room", { room: order.room_number })}</h3>
        <span
          className={`text-sm ${order.overdue ? "font-semibold text-red-700" : "text-slate-500"}`}
        >
          {t("minutesAgo", { minutes: minutesSince(order.created_at) })}
        </span>
      </header>
      <ul className="space-y-1 text-lg">
        {order.items.map((line) => (
          <li key={line.item_id}>
            <strong>{line.quantity} ×</strong> {line.name}
            {line.note && <span className="block text-base text-amber-800">↳ {line.note}</span>}
          </li>
        ))}
      </ul>
      {order.order_note && <p className="rounded bg-amber-50 p-2 text-sm">{order.order_note}</p>}
      {order.estimated_minutes && order.status !== "PENDING" && (
        <p className="text-xs text-slate-500">{t("eta", { minutes: order.estimated_minutes })}</p>
      )}

      {next === "CONFIRMED" ? (
        <div className="flex flex-wrap gap-2" role="group" aria-label={t("confirmWithEta")}>
          {ETA_CHOICES.map((minutes) => (
            <button
              key={minutes}
              type="button"
              disabled={busy}
              onClick={() => run(() => actions.advance(order, minutes))}
              className="flex-1 rounded bg-teal-700 px-3 py-3 text-white disabled:opacity-50"
            >
              {t("confirmEta", { minutes })}
            </button>
          ))}
        </div>
      ) : next ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => run(() => actions.advance(order))}
          className="w-full rounded bg-teal-700 px-3 py-3 text-lg text-white disabled:opacity-50"
        >
          {t(`next.${next}`)}
        </button>
      ) : null}

      {(order.status === "PENDING" || order.status === "CONFIRMED") &&
        (rejecting ? (
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (reason.trim()) void run(() => actions.reject(order, reason.trim()));
            }}
          >
            <label className="block text-sm">
              {t("rejectReason")}
              <input
                autoFocus
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="mt-1 w-full rounded border px-2 py-1"
              />
            </label>
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={!reason.trim() || busy}
                className="rounded bg-red-700 px-3 py-1 text-white disabled:opacity-50"
              >
                {t("rejectConfirm")}
              </button>
              <button type="button" onClick={() => setRejecting(false)} className="underline">
                {t("cancel")}
              </button>
            </div>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setRejecting(true)}
            className="text-sm text-red-700 underline"
          >
            {t("reject")}
          </button>
        ))}
    </article>
  );
}
