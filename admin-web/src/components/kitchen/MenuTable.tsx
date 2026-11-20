"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { MenuCategory, MenuItem, RoomServiceSettings } from "@/lib/menu/types";
import { vnd } from "@/lib/orders/types";

interface Draft {
  category_id: string;
  name_vi: string;
  name_en: string;
  description_vi: string;
  price_vnd: string;
}

const emptyDraft = (categoryId = ""): Draft => ({
  category_id: categoryId,
  name_vi: "",
  name_en: "",
  description_vi: "",
  price_vnd: "",
});

const fromItem = (item: MenuItem): Draft => ({
  category_id: item.category_id,
  name_vi: item.name_vi,
  name_en: item.name_en,
  description_vi: item.description_vi ?? "",
  price_vnd: String(item.price_vnd),
});

function toBody(draft: Draft) {
  return {
    category_id: draft.category_id,
    name_vi: draft.name_vi.trim(),
    name_en: draft.name_en.trim() || draft.name_vi.trim(),
    description_vi: draft.description_vi.trim() || null,
    price_vnd: Number(draft.price_vnd),
  };
}

const isValid = (draft: Draft) =>
  draft.category_id !== "" && draft.name_vi.trim() !== "" && /^\d+$/.test(draft.price_vnd.trim());

/** Kitchen menu: availability switch, edit, archive, and pausing room service as a whole. */
export function MenuTable() {
  const t = useTranslations("Menu");
  const { authFetch } = useAuth();
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [items, setItems] = useState<MenuItem[] | null>(null);
  const [settings, setSettings] = useState<RoomServiceSettings | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [editing, setEditing] = useState<{ id: string; draft: Draft } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [cats, all, current] = await Promise.all([
        authFetch<MenuCategory[]>("/api/v1/menu/categories"),
        authFetch<MenuItem[]>("/api/v1/menu/items?include_archived=true"),
        authFetch<RoomServiceSettings>("/api/v1/settings/room-service"),
      ]);
      setCategories(cats);
      setItems(all);
      setSettings(current);
      setDraft((d) => (d.category_id || !cats[0] ? d : { ...d, category_id: cats[0].id }));
    } catch {
      setError(t("loadError"));
    }
  }, [authFetch, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(call: () => Promise<unknown>) {
    setError(null);
    try {
      await call();
      await load();
      return true;
    } catch (err) {
      setError(err instanceof ApiError && err.status === 400 ? t("invalid") : t("saveError"));
      return false;
    }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isValid(draft)) return;
    const ok = await run(() =>
      authFetch("/api/v1/menu/items", { method: "POST", body: toBody(draft) }),
    );
    if (ok) setDraft(emptyDraft(draft.category_id));
  }

  const patch = (id: string, body: object) =>
    run(() => authFetch(`/api/v1/menu/items/${id}`, { method: "PATCH", body }));

  const setAvailable = (item: MenuItem, available: boolean) =>
    run(() =>
      authFetch(`/api/v1/menu/items/${item.id}/availability`, {
        method: "POST",
        body: { available },
      }),
    );

  const setPaused = (paused: boolean) =>
    run(() => authFetch("/api/v1/settings/room-service", { method: "PATCH", body: { paused } }));

  if (!items) return <p className="text-slate-500">{error ?? t("loading")}</p>;

  const categoryName = (id: string) => categories.find((c) => c.id === id)?.name_vi ?? "—";
  const active = items.filter((i) => !i.is_archived);
  const archived = items.filter((i) => i.is_archived);
  const field = "rounded border border-slate-300 px-2 py-1";

  const fields = (value: Draft, onChange: (d: Draft) => void, prefix: string) => (
    <>
      <label className="text-sm">
        {t("category")}
        <select
          aria-label={`${prefix}${t("category")}`}
          value={value.category_id}
          onChange={(e) => onChange({ ...value, category_id: e.target.value })}
          className={`${field} block`}
        >
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name_vi}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        {t("nameVi")}
        <input
          aria-label={`${prefix}${t("nameVi")}`}
          value={value.name_vi}
          onChange={(e) => onChange({ ...value, name_vi: e.target.value })}
          className={`${field} block`}
        />
      </label>
      <label className="text-sm">
        {t("nameEn")}
        <input
          aria-label={`${prefix}${t("nameEn")}`}
          value={value.name_en}
          onChange={(e) => onChange({ ...value, name_en: e.target.value })}
          className={`${field} block`}
        />
      </label>
      <label className="text-sm">
        {t("price")}
        <input
          aria-label={`${prefix}${t("price")}`}
          inputMode="numeric"
          value={value.price_vnd}
          onChange={(e) => onChange({ ...value, price_vnd: e.target.value })}
          className={`${field} block w-28`}
        />
      </label>
      <label className="text-sm">
        {t("description")}
        <input
          aria-label={`${prefix}${t("description")}`}
          value={value.description_vi}
          onChange={(e) => onChange({ ...value, description_vi: e.target.value })}
          className={`${field} block`}
        />
      </label>
    </>
  );

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{t("title")}</h1>
      {error && (
        <p role="alert" className="rounded bg-amber-50 p-2 text-sm text-amber-900">
          {error}
        </p>
      )}

      {settings && (
        <div
          className={`flex flex-wrap items-center gap-3 rounded border p-3 ${
            settings.room_service_paused ? "border-red-300 bg-red-50" : "border-slate-200"
          }`}
        >
          <p className="text-sm">
            {settings.room_service_paused ? t("pausedNotice") : t("openNotice")}
          </p>
          <button
            type="button"
            onClick={() => void setPaused(!settings.room_service_paused)}
            className={`ml-auto rounded px-3 py-1 text-white ${
              settings.room_service_paused ? "bg-teal-700" : "bg-red-700"
            }`}
          >
            {settings.room_service_paused ? t("resume") : t("pause")}
          </button>
        </div>
      )}

      <form
        onSubmit={create}
        aria-label={t("add")}
        className="flex flex-wrap items-end gap-2 rounded border border-slate-200 p-3"
      >
        {fields(draft, setDraft, "")}
        <button
          type="submit"
          disabled={!isValid(draft)}
          className="rounded bg-teal-700 px-3 py-1 text-white disabled:opacity-50"
        >
          {t("add")}
        </button>
      </form>

      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b">
            <th className="py-2">{t("nameVi")}</th>
            <th>{t("category")}</th>
            <th>{t("price")}</th>
            <th>{t("available")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {active.map((item) =>
            editing?.id === item.id ? (
              <tr key={item.id} className="border-b bg-slate-50">
                <td colSpan={5} className="py-2">
                  <div className="flex flex-wrap items-end gap-2">
                    {fields(
                      editing.draft,
                      (d) => setEditing({ id: item.id, draft: d }),
                      `${item.name_vi}: `,
                    )}
                    <button
                      type="button"
                      disabled={!isValid(editing.draft)}
                      onClick={async () => {
                        if (await patch(item.id, toBody(editing.draft))) setEditing(null);
                      }}
                      className="rounded bg-teal-700 px-3 py-1 text-white disabled:opacity-50"
                    >
                      {t("save")}
                    </button>
                    <button type="button" onClick={() => setEditing(null)} className="underline">
                      {t("cancel")}
                    </button>
                  </div>
                </td>
              </tr>
            ) : (
              <tr key={item.id} className="border-b" data-testid={`item-${item.id}`}>
                <td className="py-2">
                  <span className="font-medium">{item.name_vi}</span>
                  <span className="block text-xs text-slate-500">{item.name_en}</span>
                </td>
                <td>{categoryName(item.category_id)}</td>
                <td>{vnd(item.price_vnd)}</td>
                <td>
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      role="switch"
                      aria-label={t("availableOf", { name: item.name_vi })}
                      checked={item.available}
                      onChange={(e) => void setAvailable(item, e.target.checked)}
                    />
                    <span className={item.available ? "" : "text-red-700"}>
                      {item.available ? t("inStock") : t("soldOut")}
                    </span>
                  </label>
                </td>
                <td className="space-x-3 text-right">
                  <button
                    type="button"
                    onClick={() => setEditing({ id: item.id, draft: fromItem(item) })}
                    className="underline"
                  >
                    {t("edit")}
                  </button>
                  <button
                    type="button"
                    aria-label={t("archiveOf", { name: item.name_vi })}
                    onClick={() => void patch(item.id, { is_archived: true })}
                    className="text-red-700 underline"
                  >
                    {t("archive")}
                  </button>
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
      {active.length === 0 && <p className="text-sm text-slate-500">{t("empty")}</p>}

      {archived.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm">
            {t("archived", { count: archived.length })}
          </summary>
          <ul className="mt-2 space-y-1 text-sm">
            {archived.map((item) => (
              <li key={item.id} className="flex items-center gap-3">
                <span>{item.name_vi}</span>
                <button
                  type="button"
                  aria-label={t("restoreOf", { name: item.name_vi })}
                  onClick={() => void patch(item.id, { is_archived: false })}
                  className="underline"
                >
                  {t("restore")}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
