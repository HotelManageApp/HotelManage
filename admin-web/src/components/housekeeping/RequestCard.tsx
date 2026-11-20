"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import type { HkStatus, StaffHkRequest } from "@/lib/housekeeping/types";
import { minutesSince } from "@/lib/orders/types";

export type Move = (request: StaffHkRequest, to: HkStatus) => Promise<void>;

/** One housekeeping job: room, what to do, when, and the buttons this staff member may use. */
export function RequestCard({
  request,
  myId,
  move,
}: {
  request: StaffHkRequest;
  myId: string;
  move: Move;
}) {
  const t = useTranslations("Housekeeping");
  const format = useFormatter();
  const [busy, setBusy] = useState(false);
  const mine = request.assigned_to === myId;

  async function run(to: HkStatus) {
    setBusy(true);
    try {
      await move(request, to);
    } finally {
      setBusy(false);
    }
  }

  const button = (to: HkStatus, label: string, tone = "bg-teal-700 text-white") => (
    <button
      type="button"
      disabled={busy}
      onClick={() => void run(to)}
      className={`flex-1 rounded px-3 py-3 disabled:opacity-50 ${tone}`}
    >
      {label}
    </button>
  );

  return (
    <article
      data-testid={`hk-${request.id}`}
      className={`space-y-2 rounded border bg-white p-3 shadow-sm ${
        request.overdue ? "border-2 border-red-600" : "border-slate-200"
      }`}
    >
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="text-2xl font-bold">{t("room", { room: request.room_number })}</h3>
        <span className="rounded bg-slate-100 px-2 py-0.5 text-sm">
          {t(`type.${request.type}`)}
        </span>
      </header>

      {request.do_not_disturb && (
        <p className="rounded bg-red-100 px-2 py-1 text-sm font-semibold text-red-800">
          {t("dnd")}
        </p>
      )}

      {request.amenities.length > 0 && (
        <ul className="text-lg">
          {request.amenities.map((a) => (
            <li key={a.code}>
              <strong>{a.quantity} ×</strong> {t(`amenity.${a.code}`)}
            </li>
          ))}
        </ul>
      )}
      {request.note && <p className="rounded bg-amber-50 p-2 text-sm">{request.note}</p>}

      <p className={`text-sm ${request.overdue ? "font-semibold text-red-700" : "text-slate-500"}`}>
        {request.preferred_time
          ? t("preferredAt", {
              time: format.dateTime(new Date(request.preferred_time), { timeStyle: "short" }),
            })
          : t("asap")}
        {" · "}
        {t("minutesAgo", { minutes: minutesSince(request.created_at) })}
      </p>

      {request.status === "REQUESTED" && (
        <div className="flex">{button("ASSIGNED", t("action.claim"))}</div>
      )}
      {request.status !== "REQUESTED" && !mine && (
        <p className="text-sm text-slate-600">
          {t("takenBy", { name: request.assignee_full_name ?? "—" })}
        </p>
      )}
      {request.status === "ASSIGNED" && mine && (
        <div className="flex gap-2">
          {button("IN_PROGRESS", t("action.start"))}
          {button("REQUESTED", t("action.handBack"), "border border-slate-300 bg-white")}
        </div>
      )}
      {request.status === "IN_PROGRESS" && mine && (
        <div className="flex">{button("DONE", t("action.done"))}</div>
      )}
    </article>
  );
}
