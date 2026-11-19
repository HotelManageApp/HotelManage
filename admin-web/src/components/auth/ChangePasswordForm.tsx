"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";

const MIN_LENGTH = 10;

export function ChangePasswordForm() {
  const t = useTranslations("Account");
  const { authFetch } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (next.length < MIN_LENGTH) {
      setMessage({ ok: false, text: t("tooShort", { min: MIN_LENGTH }) });
      return;
    }
    if (next !== repeat) {
      setMessage({ ok: false, text: t("mismatch") });
      return;
    }
    try {
      await authFetch("/api/v1/staff/me/password", {
        method: "POST",
        body: { current_password: current, new_password: next },
        credentials: "same-origin",
      });
      setMessage({ ok: true, text: t("changed") });
      setCurrent("");
      setNext("");
      setRepeat("");
    } catch (err) {
      const wrongCurrent = err instanceof ApiError && err.code === "INVALID_CURRENT_PASSWORD";
      setMessage({ ok: false, text: wrongCurrent ? t("wrongCurrent") : t("failed") });
    }
  }

  const field = (label: string, value: string, set: (v: string) => void, auto: string) => (
    <label className="block text-sm">
      {label}
      <input
        type="password"
        autoComplete={auto}
        value={value}
        onChange={(e) => set(e.target.value)}
        className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
      />
    </label>
  );

  return (
    <form onSubmit={onSubmit} className="max-w-sm space-y-4">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      {field(t("current"), current, setCurrent, "current-password")}
      {field(t("new"), next, setNext, "new-password")}
      {field(t("repeat"), repeat, setRepeat, "new-password")}
      {message && (
        <p
          role={message.ok ? "status" : "alert"}
          className={message.ok ? "text-emerald-700" : "text-red-700"}
        >
          {message.text}
        </p>
      )}
      <button type="submit" className="rounded bg-teal-700 px-4 py-2 text-white">
        {t("submit")}
      </button>
    </form>
  );
}
