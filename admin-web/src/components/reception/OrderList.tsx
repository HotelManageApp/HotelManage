"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { minutesSince, vnd, type OrderStatus, type StaffOrder } from "@/lib/orders/types";
import { useStaffEvents } from "@/lib/realtime/useStaffEvents";

const STATUSES: OrderStatus[] = [
  "PENDING",
  "CONFIRMED",
  "PREPARING",
  "DELIVERING",
  "COMPLETED",
  "CANCELLED",
];

/** Reception may cancel only before the kitchen starts cooking (docs/domain-rules.md §3). */
const CANCELLABLE: OrderStatus[] = ["PENDING", "CONFIRMED"];

/** Reception overview of food orders: filter, details with history, cancel with a reason. */
export function OrderList() {
  const t = useTranslations("ReceptionOrders");
  const tStatus = useTranslations("OrderStatus");
  const format = useFormatter();
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<OrderStatus | "">("");
  // `?room=101` (e.g. from the checkout desk) pre-fills the room filter.
  const params = useSearchParams();
  const [room, setRoom] = useState(params?.get("room") ?? "");
  const [orders, setOrders] = useState<StaffOrder[] | null>(null);
  const [selected, setSelected] = useState<StaffOrder | null>(null);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const query = new URLSearchParams();
    if (status) query.set("status", status);
    if (room.trim()) query.set("room", room.trim());
    const suffix = query.size ? `?${query}` : "";
    try {
      setOrders(await authFetch<StaffOrder[]>(`/api/v1/orders${suffix}`));
    } catch {
      setNotice(t("loadError"));
    }
  }, [authFetch, status, room, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const open = useCallback(
    async (id: string) => {
      setReason("");
      try {
        setSelected(await authFetch<StaffOrder>(`/api/v1/orders/${id}`));
      } catch {
        setNotice(t("loadError"));
      }
    },
    [authFetch, t],
  );

  useStaffEvents(
    (event) => {
      if (event.entity_type !== "FOOD_ORDER") return;
      void load();
      if (selected && event.entity_id === selected.id) void open(selected.id);
    },
    () => void load(),
  );

  async function cancel(order: StaffOrder) {
    setNotice(null);
    try {
      const updated = await authFetch<StaffOrder>(`/api/v1/orders/${order.id}/cancel`, {
        method: "POST",
        body: { version: order.version, reason: reason.trim() },
      });
      setSelected(updated);
      setReason("");
    } catch (err) {
      const stale =
        err instanceof ApiError && (err.code === "CONFLICT" || err.code === "INVALID_TRANSITION");
      setNotice(stale ? t("stale") : t("cancelError"));
      await open(order.id);
    } finally {
      await load();
    }
  }

  const field = "rounded border border-slate-300 px-2 py-1";
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          {t("filterStatus")}
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as OrderStatus | "")}
            className={`${field} block`}
          >
            <option value="">{t("openAndRecent")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {tStatus(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          {t("filterRoom")}
          <input
            value={room}
            onChange={(e) => setRoom(e.target.value)}
            className={`${field} block w-24`}
          />
        </label>
      </div>
      {notice && (
        <p role="alert" className="rounded bg-amber-50 p-2 text-sm text-amber-900">
          {notice}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div>
          {!orders ? (
            <p className="text-slate-500">{t("loading")}</p>
          ) : orders.length === 0 ? (
            <p className="text-sm text-slate-500">{t("empty")}</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="py-2">{t("room")}</th>
                  <th>{t("guest")}</th>
                  <th>{t("items")}</th>
                  <th>{t("total")}</th>
                  <th>{t("status")}</th>
                  <th>{t("waiting")}</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr
                    key={o.id}
                    data-testid={`order-row-${o.id}`}
                    className={`border-b ${o.overdue ? "bg-red-50" : ""} ${
                      selected?.id === o.id ? "bg-teal-50" : ""
                    }`}
                  >
                    <td className="py-2">
                      <button
                        type="button"
                        onClick={() => void open(o.id)}
                        className="font-semibold underline"
                        aria-label={t("openOrder", { room: o.room_number })}
                      >
                        {o.room_number}
                      </button>
                    </td>
                    <td>{o.guest_name ?? "—"}</td>
                    <td>{o.items.map((i) => `${i.quantity}× ${i.name}`).join(", ")}</td>
                    <td>{vnd(o.total_vnd)}</td>
                    <td>
                      {tStatus(o.status)}
                      {o.overdue && <span className="ml-1 text-red-700">· {t("overdue")}</span>}
                    </td>
                    <td>{t("minutes", { minutes: minutesSince(o.created_at) })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {selected && (
          <aside
            aria-label={t("detail", { room: selected.room_number })}
            className="space-y-3 rounded border border-slate-200 p-3 text-sm"
          >
            <header className="flex items-baseline justify-between">
              <h2 className="text-lg font-semibold">
                {t("detail", { room: selected.room_number })}
              </h2>
              <button type="button" onClick={() => setSelected(null)} className="underline">
                {t("close")}
              </button>
            </header>
            <p>
              {tStatus(selected.status)}
              {selected.cancel_reason && ` · ${selected.cancel_reason}`}
            </p>
            <ul className="space-y-1">
              {selected.items.map((line) => (
                <li key={line.item_id}>
                  {line.quantity} × {line.name} — {vnd(line.line_total_vnd)}
                  {line.note && <span className="block text-amber-800">↳ {line.note}</span>}
                </li>
              ))}
            </ul>
            <p className="font-semibold">
              {t("total")}: {vnd(selected.total_vnd)}
            </p>
            {selected.order_note && (
              <p className="rounded bg-amber-50 p-2">{selected.order_note}</p>
            )}
            {selected.history && selected.history.length > 0 && (
              <ol className="space-y-1 border-l pl-3 text-xs text-slate-600">
                {selected.history.map((h, index) => (
                  <li key={index}>
                    {format.dateTime(new Date(h.at), { timeStyle: "short" })} ·{" "}
                    {tStatus(h.to_status as OrderStatus)}
                    {h.reason && ` · ${h.reason}`}
                  </li>
                ))}
              </ol>
            )}
            {CANCELLABLE.includes(selected.status) && (
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (reason.trim()) void cancel(selected);
                }}
              >
                <label className="block">
                  {t("cancelReason")}
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    maxLength={300}
                    className={`${field} mt-1 block w-full`}
                  />
                </label>
                <button
                  type="submit"
                  disabled={!reason.trim()}
                  className="rounded bg-red-700 px-3 py-1 text-white disabled:opacity-50"
                >
                  {t("cancelOrder")}
                </button>
              </form>
            )}
          </aside>
        )}
      </div>
    </section>
  );
}
