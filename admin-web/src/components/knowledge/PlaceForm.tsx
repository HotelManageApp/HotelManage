"use client";

import { useTranslations } from "next-intl";
import { useId, useState, type FormEvent } from "react";
import {
  isAllowedMapUrl,
  PLACE_CATEGORIES,
  type Place,
  type PlaceCategory,
} from "@/lib/knowledge/types";

export interface PlaceDraft {
  category: PlaceCategory;
  name: string;
  description_vi: string;
  description_en: string;
  distance_km: string;
  open_hours: string;
  map_url: string;
  is_published: boolean;
}

export const emptyPlace: PlaceDraft = {
  category: "ATTRACTION",
  name: "",
  description_vi: "",
  description_en: "",
  distance_km: "",
  open_hours: "",
  map_url: "",
  is_published: true,
};

export const placeDraft = (p: Place): PlaceDraft => ({
  category: p.category,
  name: p.name,
  description_vi: p.description_vi ?? "",
  description_en: p.description_en ?? "",
  distance_km: p.distance_km === null ? "" : String(p.distance_km),
  open_hours: p.open_hours ?? "",
  map_url: p.map_url ?? "",
  is_published: p.is_published,
});

/** Empty optional fields are sent as null, so editing can clear them. */
export function placeBody(d: PlaceDraft) {
  const text = (value: string) => value.trim() || null;
  return {
    category: d.category,
    name: d.name.trim(),
    description_vi: text(d.description_vi),
    description_en: text(d.description_en),
    distance_km: d.distance_km.trim() === "" ? null : Number(d.distance_km.replace(",", ".")),
    open_hours: text(d.open_hours),
    map_url: text(d.map_url),
    is_published: d.is_published,
  };
}

export function PlaceForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initial: PlaceDraft;
  onSubmit: (draft: PlaceDraft) => Promise<boolean>;
  onCancel?: () => void;
  submitLabel: string;
}) {
  const t = useTranslations("Knowledge");
  const [draft, setDraft] = useState<PlaceDraft>(initial);
  const [busy, setBusy] = useState(false);
  const mapHintId = useId();
  const set = (patch: Partial<PlaceDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const distanceOk = draft.distance_km.trim() === "" || /^\d+([.,]\d+)?$/.test(draft.distance_km);
  const mapOk = isAllowedMapUrl(draft.map_url.trim());
  const valid = draft.name.trim() !== "" && distanceOk && mapOk;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      if ((await onSubmit(draft)) && !onCancel) setDraft(emptyPlace);
    } finally {
      setBusy(false);
    }
  }

  const field = "mt-1 block w-full rounded border border-slate-300 px-2 py-1";
  return (
    <form onSubmit={submit} aria-label={submitLabel} className="space-y-2 rounded border p-3">
      <div className="grid gap-2 md:grid-cols-2">
        <label className="block text-sm">
          {t("category")}
          <select
            value={draft.category}
            onChange={(e) => set({ category: e.target.value as PlaceCategory })}
            className={field}
          >
            {PLACE_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`categories.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          {t("name")}
          <input
            value={draft.name}
            maxLength={200}
            onChange={(e) => set({ name: e.target.value })}
            className={field}
          />
        </label>
        <label className="block text-sm">
          {t("descriptionVi")}
          <input
            value={draft.description_vi}
            maxLength={1000}
            onChange={(e) => set({ description_vi: e.target.value })}
            className={field}
          />
        </label>
        <label className="block text-sm">
          {t("descriptionEn")}
          <input
            value={draft.description_en}
            maxLength={1000}
            onChange={(e) => set({ description_en: e.target.value })}
            className={field}
          />
        </label>
        <label className="block text-sm">
          {t("distance")}
          <input
            inputMode="decimal"
            value={draft.distance_km}
            onChange={(e) => set({ distance_km: e.target.value })}
            aria-invalid={!distanceOk}
            className={field}
          />
        </label>
        <label className="block text-sm">
          {t("openHours")}
          <input
            value={draft.open_hours}
            maxLength={100}
            onChange={(e) => set({ open_hours: e.target.value })}
            className={field}
          />
        </label>
        <div className="md:col-span-2">
          <label className="block text-sm">
            {t("mapUrl")}
            <input
              value={draft.map_url}
              maxLength={500}
              onChange={(e) => set({ map_url: e.target.value })}
              aria-invalid={!mapOk}
              aria-describedby={mapOk ? undefined : mapHintId}
              className={field}
            />
          </label>
          {!mapOk && (
            <span id={mapHintId} className="text-xs text-red-700">
              {t("mapUrlHint")}
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => set({ description_en: draft.description_vi })}
          className="text-sm underline"
        >
          {t("copyFromVi")}
        </button>
        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.is_published}
            onChange={(e) => set({ is_published: e.target.checked })}
          />
          {t("published")}
        </label>
        <span className="ml-auto flex gap-2">
          {onCancel && (
            <button type="button" onClick={onCancel} className="underline">
              {t("cancel")}
            </button>
          )}
          <button
            type="submit"
            disabled={!valid || busy}
            className="rounded bg-teal-700 px-3 py-1 text-white disabled:opacity-50"
          >
            {submitLabel}
          </button>
        </span>
      </div>
    </form>
  );
}
