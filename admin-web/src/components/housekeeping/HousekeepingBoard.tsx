"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { isOpen, type StaffHkRequest } from "@/lib/housekeeping/types";
import { useStaffEvents } from "@/lib/realtime/useStaffEvents";
import { RequestCard, type Move } from "./RequestCard";

type Tab = "waiting" | "mine";

/** Housekeeping queue: open jobs to claim, and the jobs this staff member holds. */
export function HousekeepingBoard() {
  const t = useTranslations("Housekeeping");
  const { state, authFetch } = useAuth();
  const myId = state.status === "authenticated" ? state.staff.id : "";
  const [requests, setRequests] = useState<StaffHkRequest[] | null>(null);
  const [tab, setTab] = useState<Tab>("waiting");
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

  const move: Move = async (request, to) => {
    setNotice(null);
    try {
      await authFetch(`/api/v1/housekeeping-requests/${request.id}/transition`, {
        method: "POST",
        body: { to, version: request.version },
      });
      if (to === "ASSIGNED") setTab("mine");
    } catch (err) {
      if (err instanceof ApiError && err.code === "FORBIDDEN") setNotice(t("notYours"));
      else if (
        err instanceof ApiError &&
        (err.code === "CONFLICT" || err.code === "INVALID_TRANSITION")
      )
        setNotice(t("stale"));
      else setNotice(t("actionFailed"));
    } finally {
      await load();
    }
  };

  if (!requests) return <p className="text-slate-500">{notice ?? t("loading")}</p>;

  // The backend already sorts by priority (turnover, amenities, cleaning that is due).
  const waiting = requests.filter((r) => r.status === "REQUESTED");
  const mine = requests.filter((r) => r.assigned_to === myId && isOpen(r));
  const others = requests.filter(
    (r) => r.status !== "REQUESTED" && isOpen(r) && r.assigned_to !== myId,
  );
  const shown = tab === "waiting" ? [...waiting, ...others] : mine;

  const tabClass = (active: boolean) =>
    `flex-1 rounded px-3 py-2 ${active ? "bg-teal-700 text-white" : "border border-slate-300"}`;

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <div role="tablist" aria-label={t("title")} className="flex gap-2">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "waiting"}
          onClick={() => setTab("waiting")}
          className={tabClass(tab === "waiting")}
        >
          {t("tab.waiting", { count: waiting.length })}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "mine"}
          onClick={() => setTab("mine")}
          className={tabClass(tab === "mine")}
        >
          {t("tab.mine", { count: mine.length })}
        </button>
      </div>
      {notice && (
        <p role="alert" className="rounded bg-amber-50 p-2 text-sm text-amber-900">
          {notice}
        </p>
      )}
      {shown.length === 0 ? (
        <p className="text-sm text-slate-500">
          {tab === "waiting" ? t("emptyWaiting") : t("emptyMine")}
        </p>
      ) : (
        <div role="tabpanel" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((r) => (
            <RequestCard key={r.id} request={r} myId={myId} move={move} />
          ))}
        </div>
      )}
    </section>
  );
}
