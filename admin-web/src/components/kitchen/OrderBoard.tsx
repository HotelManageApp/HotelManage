"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { BOARD_COLUMNS, NEXT_STEP, type StaffOrder } from "@/lib/orders/types";
import { useStaffEvents } from "@/lib/realtime/useStaffEvents";
import { OrderCard, type OrderActions } from "./OrderCard";

/** Kitchen queue: one column per open status, finished orders of the last hours below. */
export function OrderBoard() {
  const t = useTranslations("Kitchen");
  const { authFetch } = useAuth();
  const [orders, setOrders] = useState<StaffOrder[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setOrders(await authFetch<StaffOrder[]>("/api/v1/orders"));
    } catch {
      setNotice(t("loadError"));
    }
  }, [authFetch, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useStaffEvents(
    (event) => {
      if (event.entity_type === "FOOD_ORDER") void load();
    },
    () => void load(),
  );

  async function act(path: string, body: object) {
    setNotice(null);
    try {
      await authFetch(path, { method: "POST", body });
    } catch (err) {
      if (
        err instanceof ApiError &&
        (err.code === "CONFLICT" || err.code === "INVALID_TRANSITION")
      ) {
        setNotice(t("staleOrder"));
      } else {
        setNotice(t("actionFailed"));
      }
    } finally {
      await load();
    }
  }

  const actions: OrderActions = {
    advance: (order, estimatedMinutes) =>
      act(`/api/v1/orders/${order.id}/transition`, {
        to: NEXT_STEP[order.status],
        version: order.version,
        ...(estimatedMinutes ? { estimated_minutes: estimatedMinutes } : {}),
      }),
    reject: (order, reason) =>
      act(`/api/v1/orders/${order.id}/cancel`, { version: order.version, reason }),
  };

  if (!orders) return <p className="text-slate-500">{notice ?? t("loading")}</p>;
  const finished = orders.filter((o) => o.status === "COMPLETED" || o.status === "CANCELLED");

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      {notice && (
        <p role="alert" className="rounded bg-amber-50 p-2 text-sm text-amber-900">
          {notice}
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {BOARD_COLUMNS.map((status) => {
          const column = orders.filter((o) => o.status === status);
          return (
            <section key={status} aria-label={t(`column.${status}`)} className="space-y-3">
              <h2 className="font-semibold">
                {t(`column.${status}`)} <span className="text-slate-500">({column.length})</span>
              </h2>
              {column.length === 0 ? (
                <p className="text-sm text-slate-400">{t("emptyColumn")}</p>
              ) : (
                column.map((order) => <OrderCard key={order.id} order={order} actions={actions} />)
              )}
            </section>
          );
        })}
      </div>
      <details>
        <summary className="cursor-pointer text-sm">
          {t("finished", { count: finished.length })}
        </summary>
        <ul className="mt-2 space-y-1 text-sm">
          {finished.map((o) => (
            <li key={o.id}>
              {t("room", { room: o.room_number })} · {t(`status.${o.status}`)}
              {o.cancel_reason && ` · ${o.cancel_reason}`}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
