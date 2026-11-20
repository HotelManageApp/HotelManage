"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { TOOL_TOPICS, type SearchResult, type ToolTopic } from "@/lib/knowledge/types";

/** Shows which entries and places the bot would get for a question. No LLM call (no cost). */
export function TryQuestion() {
  const t = useTranslations("Knowledge");
  const { authFetch } = useAuth();
  const [question, setQuestion] = useState("");
  const [topic, setTopic] = useState<ToolTopic>("OTHER");
  const [lang, setLang] = useState<"vi" | "en">("vi");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState(false);

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(false);
    const query = new URLSearchParams({ topic, q: question.trim(), lang });
    try {
      setResult(await authFetch<SearchResult>(`/api/v1/kb/search?${query}`));
    } catch {
      setError(true);
      setResult(null);
    }
  }

  const field = "rounded border border-slate-300 px-2 py-1";
  return (
    <section aria-label={t("tryTitle")} className="space-y-2 rounded border border-dashed p-3">
      <h2 className="font-semibold">{t("tryTitle")}</h2>
      <p className="text-xs text-slate-500">{t("tryHint")}</p>
      <form onSubmit={ask} className="flex flex-wrap items-end gap-2">
        <label className="flex-1 text-sm">
          {t("tryQuestion")}
          <input
            value={question}
            maxLength={300}
            onChange={(e) => setQuestion(e.target.value)}
            className={`${field} block w-full`}
          />
        </label>
        <label className="text-sm">
          {t("tryTopic")}
          <select
            value={topic}
            onChange={(e) => setTopic(e.target.value as ToolTopic)}
            className={`${field} block`}
          >
            {TOOL_TOPICS.map((value) => (
              <option key={value} value={value}>
                {t(`toolTopics.${value}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          {t("tryLang")}
          <select
            value={lang}
            onChange={(e) => setLang(e.target.value as "vi" | "en")}
            className={`${field} block`}
          >
            <option value="vi">Tiếng Việt</option>
            <option value="en">English</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={!question.trim()}
          className="rounded bg-teal-700 px-3 py-1 text-white disabled:opacity-50"
        >
          {t("tryAsk")}
        </button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {t("tryError")}
        </p>
      )}
      {result && (
        <div data-testid="try-result" className="space-y-1 text-sm">
          {!result.found ? (
            <p className="text-amber-800">{t("tryNothing")}</p>
          ) : (
            <>
              {result.entries.map((entry) => (
                <p key={entry.id}>
                  <strong>{entry.title}</strong>: {entry.content}
                </p>
              ))}
              {result.places.map((place) => (
                <p key={place.name}>
                  📍 <strong>{place.name}</strong>
                  {place.distance_km !== null && ` · ${place.distance_km} km`}
                  {place.open_hours && ` · ${place.open_hours}`}
                  {place.note && ` — ${place.note}`}
                </p>
              ))}
            </>
          )}
        </div>
      )}
    </section>
  );
}
