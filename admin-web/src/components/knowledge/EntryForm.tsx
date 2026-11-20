"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { ENTRY_LIMITS, KB_TOPICS, type KbEntry, type KbTopic } from "@/lib/knowledge/types";

export type EntryDraft = Pick<
  KbEntry,
  "topic" | "title_vi" | "title_en" | "content_vi" | "content_en" | "is_published"
>;

export const emptyEntry: EntryDraft = {
  topic: "BREAKFAST",
  title_vi: "",
  title_en: "",
  content_vi: "",
  content_en: "",
  is_published: true,
};

/** Bilingual form: both languages are required; "copy from Vietnamese" fills the English
 * fields as a starting point. */
export function EntryForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initial: EntryDraft;
  onSubmit: (draft: EntryDraft) => Promise<boolean>;
  onCancel?: () => void;
  submitLabel: string;
}) {
  const t = useTranslations("Knowledge");
  const [draft, setDraft] = useState<EntryDraft>(initial);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<EntryDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const valid =
    draft.title_vi.trim() !== "" &&
    draft.title_en.trim() !== "" &&
    draft.content_vi.trim() !== "" &&
    draft.content_en.trim() !== "";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      if ((await onSubmit(draft)) && !onCancel) setDraft(emptyEntry);
    } finally {
      setBusy(false);
    }
  }

  const field = "mt-1 block w-full rounded border border-slate-300 px-2 py-1";
  return (
    <form onSubmit={submit} aria-label={submitLabel} className="space-y-2 rounded border p-3">
      <label className="block text-sm">
        {t("topic")}
        <select
          value={draft.topic}
          onChange={(e) => set({ topic: e.target.value as KbTopic })}
          className={field}
        >
          {KB_TOPICS.map((topic) => (
            <option key={topic} value={topic}>
              {t(`topics.${topic}`)}
            </option>
          ))}
        </select>
      </label>
      <div className="grid gap-2 md:grid-cols-2">
        <label className="block text-sm">
          {t("titleVi")}
          <input
            value={draft.title_vi}
            maxLength={ENTRY_LIMITS.title}
            onChange={(e) => set({ title_vi: e.target.value })}
            className={field}
          />
        </label>
        <label className="block text-sm">
          {t("titleEn")}
          <input
            value={draft.title_en}
            maxLength={ENTRY_LIMITS.title}
            onChange={(e) => set({ title_en: e.target.value })}
            className={field}
          />
        </label>
        <label className="block text-sm">
          {t("contentVi")}
          <textarea
            value={draft.content_vi}
            maxLength={ENTRY_LIMITS.content}
            rows={3}
            onChange={(e) => set({ content_vi: e.target.value })}
            className={field}
          />
        </label>
        <label className="block text-sm">
          {t("contentEn")}
          <textarea
            value={draft.content_en}
            maxLength={ENTRY_LIMITS.content}
            rows={3}
            onChange={(e) => set({ content_en: e.target.value })}
            className={field}
          />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => set({ title_en: draft.title_vi, content_en: draft.content_vi })}
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
