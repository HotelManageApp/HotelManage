"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { ConfirmAction } from "@/components/ConfirmAction";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import {
  KB_TOPICS,
  PLACE_CATEGORIES,
  type KbEntry,
  type KbTopic,
  type Place,
  type PlaceCategory,
} from "@/lib/knowledge/types";
import { EntryForm, emptyEntry, type EntryDraft } from "./EntryForm";
import { PlaceForm, emptyPlace, placeBody, placeDraft, type PlaceDraft } from "./PlaceForm";
import { TryQuestion } from "./TryQuestion";

type Tab = "entries" | "places";

/** Reception's knowledge base: what the concierge may answer from (SPEC-concierge-guide). */
export function KnowledgeManager() {
  const t = useTranslations("Knowledge");
  const { authFetch } = useAuth();
  const [tab, setTab] = useState<Tab>("entries");
  const [topic, setTopic] = useState<KbTopic | "">("");
  const [category, setCategory] = useState<PlaceCategory | "">("");
  const [entries, setEntries] = useState<KbEntry[] | null>(null);
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [e, p] = await Promise.all([
        authFetch<KbEntry[]>(`/api/v1/kb/entries${topic ? `?topic=${topic}` : ""}`),
        authFetch<Place[]>(`/api/v1/kb/places${category ? `?category=${category}` : ""}`),
      ]);
      setEntries(e);
      setPlaces(p);
    } catch {
      setNotice(t("loadError"));
    }
  }, [authFetch, topic, category, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(
    path: string,
    method: "POST" | "PATCH" | "DELETE",
    body?: object,
  ): Promise<boolean> {
    setNotice(null);
    try {
      await authFetch(path, { method, body });
      setEditing(null);
      await load();
      return true;
    } catch (err) {
      setNotice(err instanceof ApiError && err.status === 400 ? t("invalid") : t("saveError"));
      return false;
    }
  }

  const saveEntry = (draft: EntryDraft, id?: string) =>
    save(id ? `/api/v1/kb/entries/${id}` : "/api/v1/kb/entries", id ? "PATCH" : "POST", {
      ...draft,
      title_vi: draft.title_vi.trim(),
      title_en: draft.title_en.trim(),
      content_vi: draft.content_vi.trim(),
      content_en: draft.content_en.trim(),
    });

  const savePlace = (draft: PlaceDraft, id?: string) =>
    save(
      id ? `/api/v1/kb/places/${id}` : "/api/v1/kb/places",
      id ? "PATCH" : "POST",
      placeBody(draft),
    );

  const tabClass = (active: boolean) =>
    `rounded px-3 py-1 ${active ? "bg-teal-700 text-white" : "border border-slate-300"}`;
  const filter = "rounded border border-slate-300 px-2 py-1";

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      <p className="text-sm text-slate-600">{t("intro")}</p>
      <div role="tablist" aria-label={t("title")} className="flex gap-2">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "entries"}
          onClick={() => setTab("entries")}
          className={tabClass(tab === "entries")}
        >
          {t("tabEntries")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "places"}
          onClick={() => setTab("places")}
          className={tabClass(tab === "places")}
        >
          {t("tabPlaces")}
        </button>
      </div>
      {notice && (
        <p role="alert" className="rounded bg-amber-50 p-2 text-sm text-amber-900">
          {notice}
        </p>
      )}

      {tab === "entries" ? (
        <div role="tabpanel" className="space-y-3">
          <EntryForm
            initial={emptyEntry}
            onSubmit={(d) => saveEntry(d)}
            submitLabel={t("addEntry")}
          />
          <label className="text-sm">
            {t("filterTopic")}{" "}
            <select
              value={topic}
              onChange={(e) => setTopic(e.target.value as KbTopic | "")}
              className={filter}
            >
              <option value="">{t("all")}</option>
              {KB_TOPICS.map((value) => (
                <option key={value} value={value}>
                  {t(`topics.${value}`)}
                </option>
              ))}
            </select>
          </label>
          {entries?.length === 0 && <p className="text-sm text-slate-500">{t("emptyEntries")}</p>}
          <ul className="space-y-2">
            {entries?.map((entry) =>
              editing === entry.id ? (
                <li key={entry.id}>
                  <EntryForm
                    initial={entry}
                    onSubmit={(d) => saveEntry(d, entry.id)}
                    onCancel={() => setEditing(null)}
                    submitLabel={t("save")}
                  />
                </li>
              ) : (
                <li
                  key={entry.id}
                  data-testid={`entry-${entry.id}`}
                  className={`rounded border p-3 ${entry.is_published ? "" : "bg-slate-50 opacity-70"}`}
                >
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="rounded bg-slate-100 px-2 text-xs">
                      {t(`topics.${entry.topic}`)}
                    </span>
                    <strong>{entry.title_vi}</strong>
                    <span className="text-sm text-slate-500">/ {entry.title_en}</span>
                    {!entry.is_published && (
                      <span className="text-xs text-amber-800">{t("hidden")}</span>
                    )}
                  </div>
                  <p className="mt-1 whitespace-pre-line text-sm">{entry.content_vi}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
                    <label className="inline-flex items-center gap-1">
                      <input
                        type="checkbox"
                        role="switch"
                        aria-label={t("publishOf", { name: entry.title_vi })}
                        checked={entry.is_published}
                        onChange={(e) =>
                          void save(`/api/v1/kb/entries/${entry.id}`, "PATCH", {
                            is_published: e.target.checked,
                          })
                        }
                      />
                      {t("published")}
                    </label>
                    <button
                      type="button"
                      onClick={() => setEditing(entry.id)}
                      className="underline"
                      aria-label={t("editOf", { name: entry.title_vi })}
                    >
                      {t("edit")}
                    </button>
                    <ConfirmAction
                      label={t("delete")}
                      question={t("deleteQuestion", { name: entry.title_vi })}
                      onConfirm={() =>
                        save(`/api/v1/kb/entries/${entry.id}`, "DELETE").then(() => {})
                      }
                    />
                  </div>
                </li>
              ),
            )}
          </ul>
        </div>
      ) : (
        <div role="tabpanel" className="space-y-3">
          <PlaceForm
            initial={emptyPlace}
            onSubmit={(d) => savePlace(d)}
            submitLabel={t("addPlace")}
          />
          <label className="text-sm">
            {t("filterCategory")}{" "}
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as PlaceCategory | "")}
              className={filter}
            >
              <option value="">{t("all")}</option>
              {PLACE_CATEGORIES.map((value) => (
                <option key={value} value={value}>
                  {t(`categories.${value}`)}
                </option>
              ))}
            </select>
          </label>
          {places?.length === 0 && <p className="text-sm text-slate-500">{t("emptyPlaces")}</p>}
          <ul className="space-y-2">
            {places?.map((place) =>
              editing === place.id ? (
                <li key={place.id}>
                  <PlaceForm
                    initial={placeDraft(place)}
                    onSubmit={(d) => savePlace(d, place.id)}
                    onCancel={() => setEditing(null)}
                    submitLabel={t("save")}
                  />
                </li>
              ) : (
                <li
                  key={place.id}
                  data-testid={`place-${place.id}`}
                  className={`rounded border p-3 ${place.is_published ? "" : "bg-slate-50 opacity-70"}`}
                >
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="rounded bg-slate-100 px-2 text-xs">
                      {t(`categories.${place.category}`)}
                    </span>
                    <strong>{place.name}</strong>
                    {place.distance_km !== null && (
                      <span className="text-sm text-slate-500">{place.distance_km} km</span>
                    )}
                    {place.open_hours && (
                      <span className="text-sm text-slate-500">· {place.open_hours}</span>
                    )}
                  </div>
                  {place.description_vi && <p className="mt-1 text-sm">{place.description_vi}</p>}
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
                    <label className="inline-flex items-center gap-1">
                      <input
                        type="checkbox"
                        role="switch"
                        aria-label={t("publishOf", { name: place.name })}
                        checked={place.is_published}
                        onChange={(e) =>
                          void save(`/api/v1/kb/places/${place.id}`, "PATCH", {
                            is_published: e.target.checked,
                          })
                        }
                      />
                      {t("published")}
                    </label>
                    <button
                      type="button"
                      onClick={() => setEditing(place.id)}
                      className="underline"
                      aria-label={t("editOf", { name: place.name })}
                    >
                      {t("edit")}
                    </button>
                    <ConfirmAction
                      label={t("delete")}
                      question={t("deleteQuestion", { name: place.name })}
                      onConfirm={() =>
                        save(`/api/v1/kb/places/${place.id}`, "DELETE").then(() => {})
                      }
                    />
                  </div>
                </li>
              ),
            )}
          </ul>
        </div>
      )}

      <TryQuestion />
    </section>
  );
}
