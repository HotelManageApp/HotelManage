/** Menu and room-service settings as returned by the staff menu API (spec/SPEC-room-service.md). */

export interface MenuCategory {
  id: string;
  code: string;
  name_vi: string;
  name_en: string;
  sort_order: number;
  is_active: boolean;
}

export interface MenuItem {
  id: string;
  category_id: string;
  name_vi: string;
  name_en: string;
  description_vi: string | null;
  description_en: string | null;
  price_vnd: number;
  available: boolean;
  is_archived: boolean;
  sort_order: number;
}

export interface RoomServiceSettings {
  /** "HH:MM:SS" in the hotel's time zone. */
  room_service_open: string;
  room_service_close: string;
  room_service_paused: boolean;
  default_prep_minutes: number;
}

/** "06:00:00" → "06:00", the value an <input type="time"> expects. */
export const hhmm = (value: string) => value.slice(0, 5);
