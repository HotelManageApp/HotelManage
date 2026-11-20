"use client";

import { useTranslations } from "next-intl";
import type { Bill } from "@/lib/checkout/types";
import { vnd } from "@/lib/orders/types";

/** The lines of a bill and its total, exactly as the backend computed them. Charges can be
 * removed while the bill is still open (`onDeleteCharge`). */
export function BillTable({
  bill,
  onDeleteCharge,
}: {
  bill: Bill;
  onDeleteCharge?: (chargeId: string) => void;
}) {
  const t = useTranslations("Checkout");
  return (
    <table className="w-full text-left text-sm" aria-label={t("billTitle")}>
      <tbody>
        {bill.lines.map((line, index) => (
          <tr key={`${line.type}-${line.charge_id ?? line.order_id ?? index}`} className="border-b">
            <td className="py-1">
              <span className="mr-2 rounded bg-slate-100 px-1 text-xs">
                {t(`line.${line.type}`)}
              </span>
              {line.description}
            </td>
            <td
              className={`py-1 text-right tabular-nums ${line.type === "DISCOUNT" ? "text-emerald-700" : ""}`}
            >
              {line.type === "DISCOUNT" ? "−" : ""}
              {vnd(line.amount_vnd)}
            </td>
            <td className="w-16 text-right">
              {onDeleteCharge && line.charge_id && (
                <button
                  type="button"
                  onClick={() => line.charge_id && onDeleteCharge(line.charge_id)}
                  aria-label={t("deleteCharge", { name: line.description })}
                  className="text-xs text-red-700 underline"
                >
                  {t("delete")}
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <th className="py-2 text-base">{t("total")}</th>
          <td
            className="py-2 text-right text-base font-semibold tabular-nums"
            data-testid="bill-total"
          >
            {vnd(bill.total_vnd)}
          </td>
          <td />
        </tr>
      </tfoot>
    </table>
  );
}
