"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { Room, RoomStatus, SlipData } from "@/lib/reception/types";
import { CheckinForm } from "./CheckinForm";
import { CheckinSlip } from "./CheckinSlip";

const STATUS_STYLE: Record<RoomStatus, string> = {
  VACANT: "border-emerald-300 bg-emerald-50",
  OCCUPIED: "border-sky-300 bg-sky-50",
  CLEANING: "border-amber-300 bg-amber-50",
};

export function RoomBoard() {
  const t = useTranslations("RoomBoard");
  const { authFetch } = useAuth();
  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [error, setError] = useState(false);
  const [floor, setFloor] = useState<string>("all");
  const [checkingIn, setCheckingIn] = useState<Room | null>(null);
  const [slip, setSlip] = useState<SlipData | null>(null);

  const load = useCallback(async () => {
    try {
      setRooms(await authFetch<Room[]>("/api/v1/rooms"));
      setError(false);
    } catch {
      setError(true);
    }
  }, [authFetch]);

  useEffect(() => {
    void load();
  }, [load]);

  async function markVacant(room: Room) {
    try {
      await authFetch(`/api/v1/rooms/${room.id}/mark-vacant`, { method: "POST" });
    } finally {
      await load();
    }
  }

  const floors = useMemo(
    () => [...new Set((rooms ?? []).map((r) => r.floor ?? 0))].sort((a, b) => a - b),
    [rooms],
  );
  const visible = (rooms ?? []).filter(
    (r) => r.is_active && (floor === "all" || String(r.floor ?? 0) === floor),
  );

  if (error) return <p role="alert">{t("loadError")}</p>;
  if (!rooms) return <p className="text-slate-500">{t("loading")}</p>;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{t("title")}</h1>
        <label className="ml-auto text-sm">
          {t("floor")}{" "}
          <select
            value={floor}
            onChange={(e) => setFloor(e.target.value)}
            className="rounded border px-2 py-1"
          >
            <option value="all">{t("allFloors")}</option>
            {floors.map((f) => (
              <option key={f} value={String(f)}>
                {f}
              </option>
            ))}
          </select>
        </label>
        <Link href="/reception/rooms" className="text-sm underline">
          {t("manageRooms")}
        </Link>
      </div>

      {checkingIn && (
        <CheckinForm
          room={checkingIn}
          onCancel={() => setCheckingIn(null)}
          onDone={(data) => {
            setCheckingIn(null);
            setSlip(data);
            void load();
          }}
        />
      )}

      {visible.length === 0 ? (
        <p className="text-slate-500">{t("empty")}</p>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {visible.map((room) => (
            <li
              key={room.id}
              data-testid={`room-${room.number}`}
              data-status={room.status}
              className={`space-y-1 rounded border p-3 ${STATUS_STYLE[room.status]}`}
            >
              <p className="text-lg font-semibold">{room.number}</p>
              <p className="text-xs">{t(`status.${room.status}`)}</p>
              {room.open_stay?.guest_name && (
                <p className="truncate text-xs">{room.open_stay.guest_name}</p>
              )}
              {room.status === "VACANT" && (
                <button
                  type="button"
                  onClick={() => setCheckingIn(room)}
                  className="text-sm text-teal-800 underline"
                >
                  {t("checkin")}
                </button>
              )}
              {room.open_stay && (
                <Link
                  href={`/reception/stays/${room.open_stay.id}`}
                  className="text-sm text-teal-800 underline"
                >
                  {t("details")}
                </Link>
              )}
              {room.status === "CLEANING" && (
                <button
                  type="button"
                  onClick={() => void markVacant(room)}
                  className="text-sm text-teal-800 underline"
                >
                  {t("markVacant")}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {slip && <CheckinSlip slip={slip} onClose={() => setSlip(null)} />}
    </section>
  );
}
