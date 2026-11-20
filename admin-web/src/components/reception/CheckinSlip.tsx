"use client";

import { useFormatter, useTranslations } from "next-intl";
import { QRCodeSVG } from "qrcode.react";
import type { SlipData } from "@/lib/reception/types";

/**
 * The only place a room code is ever displayed. Closing the slip drops it from memory;
 * a new code needs "Re-issue code" on the stay page.
 * Printing: styles in globals.css (`.print-slip`) fit an 80 mm thermal printer, A6 also works.
 */
export function CheckinSlip({ slip, onClose }: { slip: SlipData; onClose: () => void }) {
  const t = useTranslations("Slip");
  const format = useFormatter();

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("title")}
      className="fixed inset-0 z-10 flex items-start justify-center overflow-auto bg-black/40 p-4"
    >
      <div className="w-full max-w-sm space-y-4 rounded bg-white p-6 shadow-lg">
        <section className="print-slip space-y-3 text-center">
          <h2 className="text-lg font-semibold">{t("title")}</h2>
          <p>
            {t("room")} <strong className="text-2xl">{slip.roomNumber}</strong>
          </p>
          {slip.guestName && <p>{slip.guestName}</p>}
          <p className="text-sm">{t("codeLabel")}</p>
          <p className="font-mono text-4xl font-bold tracking-widest" data-testid="room-code">
            {slip.room_code}
          </p>
          <div className="flex justify-center">
            <QRCodeSVG value={slip.qr_payload} size={176} level="M" aria-label={t("qrAlt")} />
          </div>
          <p className="text-xs">{t("howTo")}</p>
          <p className="text-xs">
            {t("checkoutBy", {
              when: format.dateTime(new Date(slip.expectedCheckoutAt), {
                dateStyle: "short",
                timeStyle: "short",
              }),
            })}
          </p>
        </section>
        <p className="rounded bg-amber-50 p-2 text-xs text-amber-900 print:hidden">
          {t("onlyOnce")}
        </p>
        <div className="flex gap-3 print:hidden">
          <button
            type="button"
            onClick={() => window.print()}
            className="flex-1 rounded bg-teal-700 px-4 py-2 text-white"
          >
            {t("print")}
          </button>
          <button type="button" onClick={onClose} className="flex-1 rounded border px-4 py-2">
            {t("close")}
          </button>
        </div>
      </div>
    </div>
  );
}
