"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { Link } from "@/i18n/navigation";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { Bill } from "@/lib/checkout/types";
import { BillTable } from "./BillTable";
import { ChargeForm, type ChargeDraft } from "./ChargeForm";
import { PrintableBill } from "./PrintableBill";

/** The bill of any open stay, for check-out at the desk: same lines, extras and print. */
export function StayBill({ stayId }: { stayId: string }) {
  const t = useTranslations("Checkout");
  const { authFetch } = useAuth();
  const [bill, setBill] = useState<Bill | null>(null);
  const [hotelName, setHotelName] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBill(await authFetch<Bill>(`/api/v1/stays/${stayId}/bill`));
    } catch (err) {
      setNotice(
        err instanceof ApiError && err.code === "STAY_CLOSED" ? t("stayClosed") : t("loadError"),
      );
    }
  }, [authFetch, stayId, t]);

  useEffect(() => {
    void load();
    authFetch<{ hotel_name: string }>("/api/v1/settings/hotel")
      .then((info) => setHotelName(info.hotel_name))
      .catch(() => setHotelName(""));
  }, [load, authFetch]);

  async function run(call: () => Promise<unknown>): Promise<boolean> {
    setNotice(null);
    try {
      await call();
      return true;
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "";
      setNotice(
        code === "BILL_LOCKED"
          ? t("billLocked")
          : code === "NEGATIVE_TOTAL"
            ? t("negativeTotal")
            : t("actionFailed"),
      );
      return false;
    } finally {
      await load();
    }
  }

  const base = `/api/v1/stays/${stayId}/charges`;
  return (
    <section className="max-w-3xl space-y-4">
      <Link href={`/reception/stays/${stayId}`} className="text-sm underline print:hidden">
        {t("backToStay")}
      </Link>
      <h1 className="text-xl font-semibold">
        {bill ? t("deskTitle", { room: bill.stay.room_number }) : t("billTitle")}
      </h1>
      {notice && (
        <p role="alert" className="rounded bg-amber-50 p-2 text-sm text-amber-900">
          {notice}
        </p>
      )}
      {bill && (
        <div className="space-y-3 rounded border p-3">
          {bill.open_orders > 0 && (
            <p className="text-sm font-semibold text-red-700">
              {t("openOrders", { count: bill.open_orders })}
            </p>
          )}
          <BillTable
            bill={bill}
            onDeleteCharge={(id) =>
              void run(() => authFetch(`${base}/${id}`, { method: "DELETE" }))
            }
          />
          <ChargeForm
            onAdd={(charge: ChargeDraft) =>
              run(() => authFetch(base, { method: "POST", body: charge }))
            }
          />
          <button type="button" onClick={() => window.print()} className="rounded border px-4 py-2">
            {t("print")}
          </button>
          <PrintableBill bill={bill} hotelName={hotelName} />
        </div>
      )}
    </section>
  );
}
