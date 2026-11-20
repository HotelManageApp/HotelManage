"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { hhmm, type RoomServiceSettings } from "@/lib/menu/types";

/** Reception sets room-service hours; pausing stays with the kitchen. */
export function RoomServiceSettingsForm() {
  const t = useTranslations("RoomServiceSettings");
  const { authFetch } = useAuth();
  const [settings, setSettings] = useState<RoomServiceSettings | null>(null);
  const [open, setOpen] = useState("");
  const [close, setClose] = useState("");
  const [prep, setPrep] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  function show(current: RoomServiceSettings) {
    setSettings(current);
    setOpen(hhmm(current.room_service_open));
    setClose(hhmm(current.room_service_close));
    setPrep(String(current.default_prep_minutes));
  }

  useEffect(() => {
    authFetch<RoomServiceSettings>("/api/v1/settings/room-service")
      .then(show)
      .catch(() => setMessage({ ok: false, text: t("loadError") }));
  }, [authFetch, t]);

  const prepValid = /^\d+$/.test(prep) && Number(prep) >= 5 && Number(prep) <= 180;
  const valid = open !== "" && close !== "" && prepValid;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    setMessage(null);
    try {
      show(
        await authFetch<RoomServiceSettings>("/api/v1/settings/room-service/hours", {
          method: "PATCH",
          body: { open, close, default_prep_minutes: Number(prep) },
        }),
      );
      setMessage({ ok: true, text: t("saved") });
    } catch (err) {
      const invalid = err instanceof ApiError && err.status === 400;
      setMessage({ ok: false, text: invalid ? t("invalid") : t("saveError") });
    }
  }

  if (!settings) return <p className="text-slate-500">{message?.text ?? t("loading")}</p>;

  const field = "rounded border border-slate-300 px-2 py-1 block";
  return (
    <section className="max-w-md space-y-4">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      {settings.room_service_paused && (
        <p className="rounded bg-red-50 p-2 text-sm text-red-800">{t("pausedByKitchen")}</p>
      )}
      <form onSubmit={save} className="space-y-3">
        <div className="flex gap-3">
          <label className="text-sm">
            {t("open")}
            <input
              type="time"
              value={open}
              onChange={(e) => setOpen(e.target.value)}
              className={field}
            />
          </label>
          <label className="text-sm">
            {t("close")}
            <input
              type="time"
              value={close}
              onChange={(e) => setClose(e.target.value)}
              className={field}
            />
          </label>
        </div>
        <p className="text-xs text-slate-500">{t("overnightHint")}</p>
        <label className="text-sm">
          {t("prep")}
          <input
            inputMode="numeric"
            value={prep}
            onChange={(e) => setPrep(e.target.value)}
            className={`${field} w-24`}
          />
        </label>
        <button
          type="submit"
          disabled={!valid}
          className="rounded bg-teal-700 px-4 py-2 text-white disabled:opacity-50"
        >
          {t("save")}
        </button>
      </form>
      {message && (
        <p
          role={message.ok ? "status" : "alert"}
          className={`text-sm ${message.ok ? "text-teal-800" : "text-red-700"}`}
        >
          {message.text}
        </p>
      )}
    </section>
  );
}
