"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import {
  defaultCheckoutInput,
  localInputToIso,
  type CheckInResponse,
  type Room,
  type SlipData,
} from "@/lib/reception/types";

export function CheckinForm({
  room,
  onDone,
  onCancel,
}: {
  room: Room;
  onDone: (slip: SlipData) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("Checkin");
  const { authFetch } = useAuth();
  const [guestName, setGuestName] = useState("");
  const [guestCount, setGuestCount] = useState(1);
  const [checkout, setCheckout] = useState(defaultCheckoutInput());
  const [charge, setCharge] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const roomCharge = Number(charge.replace(/\D/g, ""));
    if (!charge || !Number.isFinite(roomCharge)) {
      setError(t("errorCharge"));
      return;
    }
    setBusy(true);
    try {
      const result = await authFetch<CheckInResponse>("/api/v1/stays", {
        method: "POST",
        body: {
          room_id: room.id,
          guest_name: guestName.trim() || null,
          guest_count: guestCount,
          expected_checkout_at: localInputToIso(checkout),
          room_charge_vnd: roomCharge,
          note: note.trim() || null,
        },
      });
      onDone({
        room_code: result.room_code,
        qr_payload: result.qr_payload,
        roomNumber: result.stay.room_number,
        guestName: result.stay.guest_name,
        expectedCheckoutAt: result.stay.expected_checkout_at,
      });
    } catch (err) {
      if (err instanceof ApiError && err.code === "ROOM_NOT_VACANT") setError(t("errorNotVacant"));
      else if (err instanceof ApiError && err.status === 400) setError(t("errorInvalid"));
      else setError(t("errorUnknown"));
    } finally {
      setBusy(false);
    }
  }

  const input = "mt-1 w-full rounded border border-slate-300 px-3 py-2";
  return (
    <form onSubmit={onSubmit} className="space-y-3 rounded border border-slate-200 bg-white p-4">
      <h2 className="text-lg font-semibold">{t("title", { room: room.number })}</h2>
      <label className="block text-sm">
        {t("guestName")}
        <input className={input} value={guestName} onChange={(e) => setGuestName(e.target.value)} />
      </label>
      <label className="block text-sm">
        {t("guestCount")}
        <input
          type="number"
          min={1}
          max={20}
          className={input}
          value={guestCount}
          onChange={(e) => setGuestCount(Number(e.target.value))}
        />
      </label>
      <label className="block text-sm">
        {t("checkout")}
        <input
          type="datetime-local"
          required
          className={input}
          value={checkout}
          onChange={(e) => setCheckout(e.target.value)}
        />
      </label>
      <label className="block text-sm">
        {t("charge")}
        <input
          inputMode="numeric"
          required
          className={input}
          value={charge}
          onChange={(e) => setCharge(e.target.value)}
          placeholder="1.200.000"
        />
      </label>
      <label className="block text-sm">
        {t("note")}
        <textarea className={input} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
      <div className="flex gap-3">
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-teal-700 px-4 py-2 text-white disabled:opacity-50"
        >
          {t("submit")}
        </button>
        <button type="button" onClick={onCancel} className="rounded border px-4 py-2">
          {t("cancel")}
        </button>
      </div>
    </form>
  );
}
