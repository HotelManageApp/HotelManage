"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

export interface ChargeDraft {
  kind: "EXTRA" | "DISCOUNT";
  description: string;
  amount_vnd: number;
}

/** Add an extra (minibar, late check-out…) or a discount; a description is required. */
export function ChargeForm({ onAdd }: { onAdd: (charge: ChargeDraft) => Promise<boolean> }) {
  const t = useTranslations("Checkout");
  const [kind, setKind] = useState<"EXTRA" | "DISCOUNT">("EXTRA");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const value = Number(amount.replace(/\D/g, ""));
  const valid = description.trim() !== "" && /\d/.test(amount) && value > 0;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      if (await onAdd({ kind, description: description.trim(), amount_vnd: value })) {
        setDescription("");
        setAmount("");
      }
    } finally {
      setBusy(false);
    }
  }

  const field = "mt-1 block rounded border border-slate-300 px-2 py-1";
  return (
    <form onSubmit={submit} aria-label={t("addCharge")} className="flex flex-wrap items-end gap-2">
      <label className="text-sm">
        {t("chargeKind")}
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as "EXTRA" | "DISCOUNT")}
          className={field}
        >
          <option value="EXTRA">{t("line.EXTRA")}</option>
          <option value="DISCOUNT">{t("line.DISCOUNT")}</option>
        </select>
      </label>
      <label className="flex-1 text-sm">
        {t("chargeDescription")}
        <input
          value={description}
          maxLength={200}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t("chargePlaceholder")}
          className={`${field} w-full`}
        />
      </label>
      <label className="text-sm">
        {t("chargeAmount")}
        <input
          value={amount}
          inputMode="numeric"
          onChange={(e) => setAmount(e.target.value)}
          className={`${field} w-32`}
        />
      </label>
      <button
        type="submit"
        disabled={!valid || busy}
        className="rounded bg-teal-700 px-3 py-1 text-white disabled:opacity-50"
      >
        {t("addCharge")}
      </button>
    </form>
  );
}
