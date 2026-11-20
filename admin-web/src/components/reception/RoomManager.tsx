"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "@/i18n/navigation";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { Room } from "@/lib/reception/types";

interface Draft {
  number: string;
  floor: string;
  roomType: string;
}

const EMPTY: Draft = { number: "", floor: "", roomType: "" };

function toBody(draft: Draft) {
  return {
    number: draft.number.trim(),
    floor: draft.floor.trim() === "" ? null : Number(draft.floor),
    room_type: draft.roomType.trim() || null,
  };
}

export function RoomManager() {
  const t = useTranslations("RoomManager");
  const { authFetch } = useAuth();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editing, setEditing] = useState<{ id: string; draft: Draft } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setRooms(await authFetch<Room[]>("/api/v1/rooms"));
  }, [authFetch]);

  useEffect(() => {
    void load();
  }, [load]);

  function explain(err: unknown) {
    if (err instanceof ApiError && err.code === "ROOM_NUMBER_TAKEN") return t("errorTaken");
    if (err instanceof ApiError && err.code === "ROOM_NOT_VACANT") return t("errorNotVacant");
    if (err instanceof ApiError && err.status === 400) return t("errorInvalid");
    return t("errorUnknown");
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await authFetch("/api/v1/rooms", { method: "POST", body: toBody(draft) });
      setDraft(EMPTY);
      await load();
    } catch (err) {
      setError(explain(err));
    }
  }

  async function patch(id: string, body: object) {
    setError(null);
    try {
      await authFetch(`/api/v1/rooms/${id}`, { method: "PATCH", body });
      setEditing(null);
      await load();
    } catch (err) {
      setError(explain(err));
    }
  }

  const cell = "rounded border border-slate-300 px-2 py-1 w-full";
  return (
    <section className="space-y-4">
      <Link href="/reception" className="text-sm underline">
        {t("back")}
      </Link>
      <h1 className="text-xl font-semibold">{t("title")}</h1>

      <form onSubmit={create} className="flex flex-wrap items-end gap-2" aria-label={t("add")}>
        <label className="text-sm">
          {t("number")}
          <input
            required
            className={cell}
            value={draft.number}
            onChange={(e) => setDraft({ ...draft, number: e.target.value })}
          />
        </label>
        <label className="text-sm">
          {t("floor")}
          <input
            inputMode="numeric"
            className={cell}
            value={draft.floor}
            onChange={(e) => setDraft({ ...draft, floor: e.target.value })}
          />
        </label>
        <label className="text-sm">
          {t("type")}
          <input
            className={cell}
            value={draft.roomType}
            onChange={(e) => setDraft({ ...draft, roomType: e.target.value })}
          />
        </label>
        <button type="submit" className="rounded bg-teal-700 px-4 py-2 text-white">
          {t("add")}
        </button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}

      <table className="w-full text-left text-sm">
        <thead>
          <tr>
            <th>{t("number")}</th>
            <th>{t("floor")}</th>
            <th>{t("type")}</th>
            <th>{t("inService")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rooms.map((room) =>
            editing?.id === room.id ? (
              <tr key={room.id}>
                <td>
                  <input
                    aria-label={t("number")}
                    className={cell}
                    value={editing.draft.number}
                    onChange={(e) =>
                      setEditing({
                        id: room.id,
                        draft: { ...editing.draft, number: e.target.value },
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={t("floor")}
                    className={cell}
                    value={editing.draft.floor}
                    onChange={(e) =>
                      setEditing({
                        id: room.id,
                        draft: { ...editing.draft, floor: e.target.value },
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={t("type")}
                    className={cell}
                    value={editing.draft.roomType}
                    onChange={(e) =>
                      setEditing({
                        id: room.id,
                        draft: { ...editing.draft, roomType: e.target.value },
                      })
                    }
                  />
                </td>
                <td />
                <td className="space-x-2">
                  <button
                    type="button"
                    className="underline"
                    onClick={() => void patch(room.id, toBody(editing.draft))}
                  >
                    {t("save")}
                  </button>
                  <button type="button" className="underline" onClick={() => setEditing(null)}>
                    {t("cancel")}
                  </button>
                </td>
              </tr>
            ) : (
              <tr key={room.id} data-testid={`row-${room.number}`}>
                <td>{room.number}</td>
                <td>{room.floor ?? "—"}</td>
                <td>{room.room_type ?? "—"}</td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={t("inServiceOf", { room: room.number })}
                    checked={room.is_active}
                    onChange={(e) => void patch(room.id, { is_active: e.target.checked })}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="underline"
                    onClick={() =>
                      setEditing({
                        id: room.id,
                        draft: {
                          number: room.number,
                          floor: room.floor === null ? "" : String(room.floor),
                          roomType: room.room_type ?? "",
                        },
                      })
                    }
                  >
                    {t("edit")}
                  </button>
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </section>
  );
}
