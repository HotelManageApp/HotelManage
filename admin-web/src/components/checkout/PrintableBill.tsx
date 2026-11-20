"use client";

import { useFormatter, useTranslations } from "next-intl";
import type { Bill } from "@/lib/checkout/types";
import { vnd } from "@/lib/orders/types";

/** The bill as printed on an 80 mm thermal roll (`.print-slip` in globals.css). Hidden on
 * screen; `window.print()` prints only this block. */
export function PrintableBill({
  bill,
  hotelName,
  paymentMethod,
}: {
  bill: Bill;
  hotelName?: string;
  paymentMethod?: string | null;
}) {
  const t = useTranslations("Checkout");
  const format = useFormatter();
  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: "short", timeStyle: "short" });
  return (
    <section
      className="print-slip hidden space-y-1 text-xs print:block"
      data-testid="printable-bill"
    >
      {hotelName && <h2 className="text-center text-sm font-bold">{hotelName}</h2>}
      <p className="text-center font-semibold">{t("printTitle")}</p>
      <p>
        {t("room")} {bill.stay.room_number}
        {bill.stay.guest_name ? ` · ${bill.stay.guest_name}` : ""}
      </p>
      <p>
        {when(bill.stay.checkin_at)} → {when(bill.stay.expected_checkout_at)}
      </p>
      <hr />
      {bill.lines.map((line, index) => (
        <p key={index} className="flex justify-between gap-2">
          <span>{line.description}</span>
          <span>
            {line.type === "DISCOUNT" ? "−" : ""}
            {vnd(line.amount_vnd)}
          </span>
        </p>
      ))}
      <hr />
      <p className="flex justify-between font-bold">
        <span>{t("total")}</span>
        <span>{vnd(bill.total_vnd)}</span>
      </p>
      {paymentMethod && (
        <p>
          {t("paidBy")}: {t(`payment.${paymentMethod}`)}
        </p>
      )}
      <p className="text-center">{when(bill.generated_at)}</p>
    </section>
  );
}
