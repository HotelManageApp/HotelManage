"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { StaffHkRequest } from "@/lib/housekeeping/types";
import { minutesSince } from "@/lib/orders/types";
import { useStaffEvents } from "@/lib/realtime/useStaffEvents";

/** Reception overview of housekeeping jobs: who is on them, and cancelling unclaimed ones. */
export function HousekeepingList() {
  const t = useTranslations("ReceptionHousekeeping");
  const tHk = useTranslations("Housekeeping");
  const { authFetch } = useAuth();
  const [requests, setRequests] = useState<StaffHkRequest[] | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRequests(await authFetch<StaffHkRequest[]>("/api/v1/housekeeping-requests"));
    } catch {
      setNotice(t("loadError"));
    }
  }, [authFetch, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useStaffEvents(
    (event) => {
      if (event.entity_type === "HOUSEKEEPING" || event.event === "do_not_disturb") void load();
    },
    () => void load(),
  );

  async function cancel(request: StaffHkRequest) {
    setNotice(null);
    try {
      await authFetch(`/api/v1/housekeeping-requests/${request.id}/cancel`, {
        method: "POST",
        body: { version: request.version, reason: reason.trim() },
      });
      setCancelling(null);
      setReason("");
    } catch (err) {
      const stale =
        err instanceof ApiError && (err.code === "CONFLICT" || err.code === "INVALID_TRANSITION");
      setNotice(stale ? t("stale") : t("cancelError"));
    } finally {
      await load();
    }
  }

  if (!requests) return <p className="text-slate-500">{notice ?? t("loading")}</p>;

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      {notice && (
        <p role="alert" className="rounded bg-amber-50 p-2 text-sm text-amber-900">
          {notice}
        </p>
      )}
      {requests.length === 0 ? (
        <p className="text-sm text-slate-500">{t("empty")}</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b">
              <th className="py-2">{t("room")}</th>
              <th>{t("type")}</th>
              <th>{t("status")}</th>
              <th>{t("assignee")}</th>
              <th>{t("created")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {requests.map((r) => (
              <tr
                key={r.id}
                data-testid={`hk-row-${r.id}`}
                className={`border-b align-top ${r.overdue ? "bg-red-50" : ""}`}
              >
                <td className="py-2 font-semibold">
                  {r.room_number}
                  {r.do_not_disturb && (
                    <span className="ml-1 rounded bg-red-100 px-1 text-xs text-red-800">
                      {t("dnd")}
                    </span>
                  )}
                  {r.guest_name && (
                    <span className="block text-xs font-normal text-slate-500">{r.guest_name}</span>
                  )}
                </td>
                <td>
                  {tHk(`type.${r.type}`)}
                  {r.amenities.length > 0 && (
                    <span className="block text-xs text-slate-500">
                      {r.amenities
                        .map((a) => `${a.quantity}× ${tHk(`amenity.${a.code}`)}`)
                        .join(", ")}
                    </span>
                  )}
                </td>
                <td>
                  {t(`statusName.${r.status}`)}
                  {r.overdue && <span className="ml-1 text-red-700">· {t("overdue")}</span>}
                  {r.cancel_reason && (
                    <span className="block text-xs text-slate-500">{r.cancel_reason}</span>
                  )}
                </td>
                <td>{r.assignee_full_name ?? "—"}</td>
                <td>{tHk("minutesAgo", { minutes: minutesSince(r.created_at) })}</td>
                <td className="text-right">
                  {r.status === "REQUESTED" &&
                    (cancelling === r.id ? (
                      <form
                        className="space-y-1"
                        onSubmit={(e) => {
                          e.preventDefault();
                          if (reason.trim()) void cancel(r);
                        }}
                      >
                        <label className="block text-left text-xs">
                          {t("cancelReason")}
                          <input
                            autoFocus
                            value={reason}
                            maxLength={300}
                            onChange={(e) => setReason(e.target.value)}
                            className="mt-1 block w-full rounded border px-2 py-1"
                          />
                        </label>
                        <button
                          type="submit"
                          disabled={!reason.trim()}
                          className="rounded bg-red-700 px-2 py-1 text-white disabled:opacity-50"
                        >
                          {t("confirmCancel")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setCancelling(null)}
                          className="ml-2 underline"
                        >
                          {t("keep")}
                        </button>
                      </form>
                    ) : (
                      <button
                        type="button"
                        aria-label={t("cancelOf", { room: r.room_number })}
                        onClick={() => {
                          setCancelling(r.id);
                          setReason("");
                        }}
                        className="text-red-700 underline"
                      >
                        {t("cancel")}
                      </button>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
