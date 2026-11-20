"use client";

import { useTranslations } from "next-intl";
import { useEffect, useId, useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { HotelInfo } from "@/lib/knowledge/types";

const PHONE = /^[0-9+() .-]{3,20}$/;

/** Hotel name, reception phone and default language (shown to guests and given to the bot),
 * and the switch that turns the concierge chatbot on or off. */
export function HotelInfoForm() {
  const t = useTranslations("HotelInfo");
  const { authFetch } = useAuth();
  const [info, setInfo] = useState<HotelInfo | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const phoneHintId = useId();

  useEffect(() => {
    authFetch<HotelInfo>("/api/v1/settings/hotel")
      .then(setInfo)
      .catch(() => setMessage({ ok: false, text: t("loadError") }));
  }, [authFetch, t]);

  async function patch(body: Partial<HotelInfo>, savedText: string) {
    setMessage(null);
    try {
      setInfo(await authFetch<HotelInfo>("/api/v1/settings/hotel", { method: "PATCH", body }));
      setMessage({ ok: true, text: savedText });
    } catch (err) {
      const invalid = err instanceof ApiError && err.status === 400;
      setMessage({ ok: false, text: invalid ? t("invalid") : t("saveError") });
    }
  }

  if (!info) return <p className="text-slate-500">{message?.text ?? t("loading")}</p>;

  const phoneOk = info.reception_phone === "" || PHONE.test(info.reception_phone.trim());
  const valid = info.hotel_name.trim() !== "" && phoneOk;
  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid) return;
    void patch(
      {
        hotel_name: info.hotel_name.trim(),
        reception_phone: info.reception_phone.trim(),
        default_lang: info.default_lang,
      },
      t("saved"),
    );
  };
  const field = "mt-1 block w-full rounded border border-slate-300 px-2 py-1";

  return (
    <section className="max-w-md space-y-3">
      <h2 className="text-lg font-semibold">{t("title")}</h2>
      <label className="flex items-center justify-between gap-3 rounded border p-3">
        <span>
          <span className="block font-medium">{t("chat")}</span>
          <span className="text-xs text-slate-500">
            {info.chat_enabled ? t("chatOn") : t("chatOff")}
          </span>
        </span>
        <input
          type="checkbox"
          role="switch"
          aria-label={t("chat")}
          checked={info.chat_enabled}
          onChange={(e) =>
            void patch(
              { chat_enabled: e.target.checked },
              e.target.checked ? t("chatEnabled") : t("chatDisabled"),
            )
          }
        />
      </label>
      <form onSubmit={save} className="space-y-2">
        <label className="block text-sm">
          {t("name")}
          <input
            value={info.hotel_name}
            maxLength={120}
            onChange={(e) => setInfo({ ...info, hotel_name: e.target.value })}
            className={field}
          />
        </label>
        <div>
          <label className="block text-sm">
            {t("phone")}
            <input
              value={info.reception_phone}
              inputMode="tel"
              onChange={(e) => setInfo({ ...info, reception_phone: e.target.value })}
              aria-invalid={!phoneOk}
              aria-describedby={phoneOk ? undefined : phoneHintId}
              className={field}
            />
          </label>
          {!phoneOk && (
            <span id={phoneHintId} className="text-xs text-red-700">
              {t("phoneHint")}
            </span>
          )}
        </div>
        <label className="block text-sm">
          {t("lang")}
          <select
            value={info.default_lang}
            onChange={(e) => setInfo({ ...info, default_lang: e.target.value as "vi" | "en" })}
            className={field}
          >
            <option value="vi">Tiếng Việt</option>
            <option value="en">English</option>
          </select>
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
