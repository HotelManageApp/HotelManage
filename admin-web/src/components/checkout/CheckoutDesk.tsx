"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ConfirmAction } from "@/components/ConfirmAction";
import { Link } from "@/i18n/navigation";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { PAYMENT_METHODS, type CheckoutDetail, type PaymentMethod } from "@/lib/checkout/types";
import { useStaffEvents } from "@/lib/realtime/useStaffEvents";
import { BillTable } from "./BillTable";
import { ChargeForm, type ChargeDraft } from "./ChargeForm";
import { PrintableBill } from "./PrintableBill";

/** Billing review of one express checkout request: adjust, verify (lock), print, complete or
 * reject. Every amount comes from the backend's bill. */
export function CheckoutDesk({ requestId }: { requestId: string }) {
  const t = useTranslations("Checkout");
  const { authFetch } = useAuth();
  const [detail, setDetail] = useState<CheckoutDetail | null>(null);
  const [hotelName, setHotelName] = useState<string>("");
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [roomCharge, setRoomCharge] = useState("");
  const [payment, setPayment] = useState<PaymentMethod | "">("");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await authFetch<CheckoutDetail>(`/api/v1/checkout-requests/${requestId}`);
      setDetail(data);
      const room = data.bill?.lines.find((l) => l.type === "ROOM");
      setRoomCharge(room ? String(room.amount_vnd) : "");
    } catch {
      setNotice({ ok: false, text: t("loadError") });
    }
  }, [authFetch, requestId, t]);

  useEffect(() => {
    void load();
    authFetch<{ hotel_name: string }>("/api/v1/settings/hotel")
      .then((info) => setHotelName(info.hotel_name))
      .catch(() => setHotelName(""));
  }, [load, authFetch]);

  useStaffEvents(
    (event) => {
      if (event.entity_type === "CHECKOUT" || event.entity_type === "FOOD_ORDER") void load();
    },
    () => void load(),
  );

  function explain(err: unknown): string {
    const code = err instanceof ApiError ? err.code : "";
    switch (code) {
      case "CONFLICT":
      case "INVALID_TRANSITION":
        return t("stale");
      case "OPEN_ORDERS_EXIST":
        return t("openOrdersBlock");
      case "BILL_LOCKED":
        return t("billLocked");
      case "NEGATIVE_TOTAL":
        return t("negativeTotal");
      default:
        return err instanceof ApiError && err.status === 400 ? t("invalid") : t("actionFailed");
    }
  }

  async function act(call: () => Promise<unknown>, done?: string): Promise<boolean> {
    setNotice(null);
    try {
      await call();
      if (done) setNotice({ ok: true, text: done });
      return true;
    } catch (err) {
      setNotice({ ok: false, text: explain(err) });
      return false;
    } finally {
      await load();
    }
  }

  if (!detail) {
    return <p className="text-slate-500">{notice?.text ?? t("loading")}</p>;
  }

  const editable = detail.status === "CHECKOUT_REQUESTED";
  const verified = detail.status === "BILLING_VERIFIED";
  const open = editable || verified;
  const blocked = detail.open_order_ids.length > 0;
  const base = `/api/v1/stays/${detail.stay_id}`;

  const addCharge = (charge: ChargeDraft) =>
    act(() => authFetch(`${base}/charges`, { method: "POST", body: charge }));
  const deleteCharge = (chargeId: string) =>
    void act(() => authFetch(`${base}/charges/${chargeId}`, { method: "DELETE" }));
  const saveRoomCharge = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = Number(roomCharge.replace(/\D/g, ""));
    if (!/\d/.test(roomCharge)) return;
    void act(() => authFetch(base, { method: "PATCH", body: { room_charge_vnd: value } }));
  };
  const step = (name: string, body: object) =>
    authFetch(`/api/v1/checkout-requests/${requestId}/${name}`, {
      method: "POST",
      body: { version: detail.version, ...body },
    });

  async function submitReject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reason.trim()) return;
    if (await act(() => step("reject", { reason: reason.trim() }), t("rejected"))) {
      setRejecting(false);
      setReason("");
    }
  }

  return (
    <section className="max-w-3xl space-y-5">
      <Link href="/reception/checkout" className="text-sm underline print:hidden">
        {t("back")}
      </Link>
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{t("deskTitle", { room: detail.room_number })}</h1>
        <p className="text-sm text-slate-600">
          {t(`status.${detail.status}`)} · {detail.guest_name ?? "—"}
          {detail.feedback_rating !== null && ` · ${"★".repeat(detail.feedback_rating)}`}
        </p>
        {detail.feedback_note && (
          <p className="rounded bg-slate-50 p-2 text-sm italic">“{detail.feedback_note}”</p>
        )}
        {detail.reject_reason && (
          <p className="text-sm text-amber-800">
            {t("rejectReasonShown", { reason: detail.reject_reason })}
          </p>
        )}
      </header>

      {notice && (
        <p
          role={notice.ok ? "status" : "alert"}
          className={`rounded p-2 text-sm ${notice.ok ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}
        >
          {notice.text}
        </p>
      )}

      {detail.bill ? (
        <div className="space-y-3 rounded border p-3">
          <h2 className="font-semibold">
            {detail.bill_is_snapshot ? t("billLockedTitle") : t("billTitle")}
          </h2>
          <BillTable bill={detail.bill} onDeleteCharge={editable ? deleteCharge : undefined} />
          {editable && (
            <>
              <form onSubmit={saveRoomCharge} className="flex flex-wrap items-end gap-2">
                <label className="text-sm">
                  {t("roomCharge")}
                  <input
                    value={roomCharge}
                    inputMode="numeric"
                    onChange={(e) => setRoomCharge(e.target.value)}
                    className="mt-1 block w-40 rounded border border-slate-300 px-2 py-1"
                  />
                </label>
                <button type="submit" className="rounded border px-3 py-1">
                  {t("saveRoomCharge")}
                </button>
              </form>
              <ChargeForm onAdd={addCharge} />
            </>
          )}
          <PrintableBill
            bill={detail.bill}
            hotelName={hotelName}
            paymentMethod={detail.payment_method}
          />
        </div>
      ) : (
        <p className="text-sm text-slate-500">{t("noBill")}</p>
      )}

      {editable && (
        <div className="space-y-2">
          {blocked && (
            <p className="text-sm font-semibold text-red-700">
              {t("openOrdersBlock")}{" "}
              <Link
                href={`/reception/orders?room=${encodeURIComponent(detail.room_number)}`}
                className="underline"
              >
                {t("seeOrders")}
              </Link>
            </p>
          )}
          <button
            type="button"
            disabled={blocked}
            onClick={() => void act(() => step("verify", {}), t("verifiedDone"))}
            className="rounded bg-teal-700 px-4 py-2 text-white disabled:opacity-50"
          >
            {t("verify")}
          </button>
        </div>
      )}

      {verified && (
        <div className="flex flex-wrap items-end gap-3">
          <button type="button" onClick={() => window.print()} className="rounded border px-4 py-2">
            {t("print")}
          </button>
          <label className="text-sm">
            {t("paymentMethod")}
            <select
              value={payment}
              onChange={(e) => setPayment(e.target.value as PaymentMethod | "")}
              className="mt-1 block rounded border border-slate-300 px-2 py-1"
            >
              <option value="">{t("choosePayment")}</option>
              {PAYMENT_METHODS.map((m) => (
                <option key={m} value={m}>
                  {t(`payment.${m}`)}
                </option>
              ))}
            </select>
          </label>
          {payment ? (
            <ConfirmAction
              tone="primary"
              label={t("complete")}
              question={t("completeQuestion", { room: detail.room_number })}
              onConfirm={async () => {
                await act(() => step("complete", { payment_method: payment }), t("completedDone"));
              }}
            />
          ) : (
            <button
              type="button"
              disabled
              className="rounded bg-teal-700 px-4 py-2 text-white opacity-50"
            >
              {t("complete")}
            </button>
          )}
        </div>
      )}

      {open &&
        (rejecting ? (
          <form onSubmit={submitReject} className="space-y-2">
            <label className="block text-sm">
              {t("rejectReason")}
              <input
                value={reason}
                maxLength={500}
                onChange={(e) => setReason(e.target.value)}
                className="mt-1 block w-full rounded border border-slate-300 px-2 py-1"
              />
            </label>
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={!reason.trim()}
                className="rounded bg-red-700 px-3 py-1 text-white disabled:opacity-50"
              >
                {t("reject")}
              </button>
              <button type="button" onClick={() => setRejecting(false)} className="underline">
                {t("cancel")}
              </button>
            </div>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setRejecting(true)}
            className="text-sm text-red-700 underline"
          >
            {t("rejectOpen")}
          </button>
        ))}
    </section>
  );
}
