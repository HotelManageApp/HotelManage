"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { useRouter } from "@/i18n/navigation";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { roleHome } from "@/lib/auth/roles";

export function LoginForm() {
  const t = useTranslations("Login");
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const staff = await login(email.trim(), password);
      router.replace(roleHome(staff.role));
    } catch (err) {
      setError(messageFor(err));
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  function messageFor(err: unknown): string {
    if (!(err instanceof ApiError)) return t("errorUnknown");
    switch (err.status) {
      case 0:
        return t("errorNetwork");
      case 400:
        return t("errorInvalidInput");
      case 401:
        return t("errorInvalidCredentials");
      case 429:
        return t("errorTooManyAttempts", {
          minutes: Math.max(1, Math.ceil((err.retryAfterSeconds ?? 60) / 60)),
        });
      default:
        return t("errorUnknown");
    }
  }

  return (
    <form onSubmit={onSubmit} className="mx-auto mt-10 max-w-sm space-y-4" noValidate>
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <label className="block text-sm">
        {t("email")}
        <input
          type="email"
          name="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
        />
      </label>
      <label className="block text-sm">
        {t("password")}
        <input
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
        />
      </label>
      {error && (
        <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting || !email || !password}
        className="w-full rounded bg-teal-700 px-4 py-2 font-medium text-white disabled:opacity-50"
      >
        {submitting ? t("submitting") : t("submit")}
      </button>
    </form>
  );
}
