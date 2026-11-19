"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ConfirmAction } from "@/components/ConfirmAction";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import {
  isoToLocalInput,
  localInputToIso,
  type IssuedCode,
  type SlipData,
  type Stay,
} from "@/lib/reception/types";
import { CheckinSlip } from "./CheckinSlip";

export function StayDetail({ stayId }: { stayId: string }) {
  const t = useTranslations("StayDetail");
  const format = useFormatter();
  const { authFetch } = useAuth();
  const router = useRouter();
  const [stay, setStay] = useState<Stay | null>(null);
  const [missing, setMissing] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [slip, setSlip] = useState<SlipData | null>(null);
  const [form, setForm] = useState({
    guestName: "",
    guestCount: 1,
    checkout: "",
    charge: "",
    note: "",
  });

  const load = useCallback(async () => {
    try {
      const data = await authFetch<Stay>(`/api/v1/stays/${stayId}`);
      setStay(data);
      setForm({
        guestName: data.guest_name ?? "",
        guestCount: data.guest_count,
        checkout: isoToLocalInput(data.expected_checkout_at),
        charge: String(data.room_charge_vnd),
        note: data.note ?? "",
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setMissing(true);
      else setLoadFailed(true);
    }
  }, [authFetch, stayId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (missing) return <p role="alert">{t("notFound")}</p>;
  if (loadFailed) return <p role="alert">{t("loadFailed")}</p>;
  if (!stay) return <p className="text-slate-500">{t("loading")}</p>;
  const closed = stay.status === "CLOSED";

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const updated = await authFetch<Stay>(`/api/v1/stays/${stayId}`, {
        method: "PATCH",
        body: {
          guest_name: form.guestName.trim() || null,
          guest_count: form.guestCount,
          expected_checkout_at: localInputToIso(form.checkout),
          room_charge_vnd: Number(form.charge.replace(/\D/g, "")),
          note: form.note.trim() || null,
        },
      });
      setStay(updated);
      setMessage({ ok: true, text: t("saved") });
    } catch {
      setMessage({ ok: false, text: t("saveFailed") });
    }
  }

  async function reissue() {
    const issued = await authFetch<IssuedCode>(`/api/v1/stays/${stayId}/reissue-code`, {
      method: "POST",
    });
    if (!stay) return;
    setSlip({
      ...issued,
      roomNumber: stay.room_number,
      guestName: stay.guest_name,
      expectedCheckoutAt: stay.expected_checkout_at,
    });
  }

  async function checkout() {
    await authFetch(`/api/v1/stays/${stayId}/checkout`, { method: "POST" });
    router.push("/reception");
  }

  const input = "mt-1 w-full rounded border border-slate-300 px-3 py-2";
  const money = new Intl.NumberFormat("vi-VN").format(stay.room_charge_vnd);
  return (
    <section className="space-y-6">
      <Link href="/reception" className="text-sm underline">
        {t("back")}
      </Link>
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{t("title", { room: stay.room_number })}</h1>
        <p className="text-sm text-slate-600">
          {t(`status.${stay.status}`)} · {t("checkedIn")}{" "}
          {format.dateTime(new Date(stay.checkin_at), { dateStyle: "short", timeStyle: "short" })} ·{" "}
          {money} ₫
        </p>
      </header>

      <form onSubmit={save} className="grid max-w-xl gap-3 sm:grid-cols-2">
        <label className="text-sm">
          {t("guestName")}
          <input
            className={input}
            disabled={closed}
            value={form.guestName}
            onChange={(e) => setForm({ ...form, guestName: e.target.value })}
          />
        </label>
        <label className="text-sm">
          {t("guestCount")}
          <input
            type="number"
            min={1}
            max={20}
            className={input}
            disabled={closed}
            value={form.guestCount}
            onChange={(e) => setForm({ ...form, guestCount: Number(e.target.value) })}
          />
        </label>
        <label className="text-sm">
          {t("checkout")}
          <input
            type="datetime-local"
            className={input}
            disabled={closed}
            value={form.checkout}
            onChange={(e) => setForm({ ...form, checkout: e.target.value })}
          />
        </label>
        <label className="text-sm">
          {t("charge")}
          <input
            inputMode="numeric"
            className={input}
            disabled={closed}
            value={form.charge}
            onChange={(e) => setForm({ ...form, charge: e.target.value })}
          />
        </label>
        <label className="text-sm sm:col-span-2">
          {t("note")}
          <textarea
            className={input}
            disabled={closed}
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
          />
        </label>
        {!closed && (
          <button type="submit" className="rounded bg-teal-700 px-4 py-2 text-white sm:col-span-2">
            {t("save")}
          </button>
        )}
      </form>
      {message && (
        <p
          role={message.ok ? "status" : "alert"}
          className={message.ok ? "text-emerald-700" : "text-red-700"}
        >
          {message.text}
        </p>
      )}

      {!closed && (
        <div className="flex flex-wrap items-start gap-4">
          <ConfirmAction
            tone="primary"
            label={t("reissue")}
            question={t("reissueQuestion")}
            onConfirm={reissue}
          />
          <ConfirmAction
            label={t("checkoutAction")}
            question={t("checkoutQuestion")}
            onConfirm={checkout}
          />
        </div>
      )}

      {slip && <CheckinSlip slip={slip} onClose={() => setSlip(null)} />}
    </section>
  );
}
