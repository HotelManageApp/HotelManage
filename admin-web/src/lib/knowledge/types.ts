/** Knowledge base, nearby places and hotel info (backend /kb/*, /settings/hotel). */

export const KB_TOPICS = [
  "BREAKFAST",
  "FACILITIES",
  "SERVICES",
  "POLICIES",
  "WIFI",
  "TRANSPORT",
  "OTHER",
] as const;
export type KbTopic = (typeof KB_TOPICS)[number];

export const PLACE_CATEGORIES = [
  "ATTRACTION",
  "FOOD_NEARBY",
  "TRANSPORT",
  "SHOPPING",
  "HEALTH",
] as const;
export type PlaceCategory = (typeof PLACE_CATEGORIES)[number];

/** Topics of the chatbot tool, used by "Try a question". */
export const TOOL_TOPICS = [
  "OTHER",
  "BREAKFAST",
  "FACILITIES",
  "SERVICES",
  "POLICIES",
  "WIFI",
  "TRANSPORT",
  "ATTRACTIONS",
  "FOOD_NEARBY",
] as const;
export type ToolTopic = (typeof TOOL_TOPICS)[number];

export interface KbEntry {
  id: string;
  topic: KbTopic;
  title_vi: string;
  title_en: string;
  content_vi: string;
  content_en: string;
  is_published: boolean;
  updated_at: string;
}

export interface Place {
  id: string;
  category: PlaceCategory;
  name: string;
  description_vi: string | null;
  description_en: string | null;
  distance_km: number | null;
  open_hours: string | null;
  map_url: string | null;
  is_published: boolean;
  updated_at: string;
}

export interface HotelInfo {
  hotel_name: string;
  reception_phone: string;
  default_lang: "vi" | "en";
  chat_enabled: boolean;
}

export interface SearchResult {
  found: boolean;
  entries: { id: string; title: string; content: string }[];
  places: {
    name: string;
    category: string;
    distance_km: number | null;
    open_hours: string | null;
    note: string | null;
  }[];
}

/** The only map links guests may open (same allow-list as the backend). */
export const MAP_URL_PREFIXES = ["https://maps.google.com/", "https://maps.app.goo.gl/"];

export const isAllowedMapUrl = (value: string) =>
  value === "" || (MAP_URL_PREFIXES.some((p) => value.startsWith(p)) && !/\s/.test(value));

export const ENTRY_LIMITS = { title: 200, content: 2000 } as const;
