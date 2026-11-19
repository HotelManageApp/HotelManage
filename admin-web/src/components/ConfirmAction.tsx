"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

/** A button that asks for confirmation inline before running a consequential action. */
export function ConfirmAction({
  label,
  question,
  onConfirm,
  tone = "danger",
}: {
  label: string;
  question: string;
  onConfirm: () => Promise<void> | void;
  tone?: "danger" | "primary";
}) {
  const t = useTranslations("Confirm");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const colour = tone === "danger" ? "bg-red-700" : "bg-teal-700";

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        className={`rounded px-4 py-2 text-white ${colour}`}
      >
        {label}
      </button>
    );
  }
  return (
    <div role="alertdialog" aria-label={label} className="space-y-2 rounded border p-3">
      <p className="text-sm">{question}</p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
            } finally {
              setBusy(false);
              setAsking(false);
            }
          }}
          className={`rounded px-3 py-1 text-white disabled:opacity-50 ${colour}`}
        >
          {t("yes")}
        </button>
        <button type="button" onClick={() => setAsking(false)} className="rounded border px-3 py-1">
          {t("no")}
        </button>
      </div>
    </div>
  );
}
