/** Shapes returned by backend-api stay-access endpoints (spec/SPEC-stay-access.md). */

export type RoomStatus = "VACANT" | "OCCUPIED" | "CLEANING";
export type StayStatus = "ACTIVE" | "CHECKOUT_PENDING" | "CLOSED";

export interface StaySummary {
  id: string;
  guest_name: string | null;
  guest_count: number;
  checkin_at: string;
  expected_checkout_at: string;
  status: StayStatus;
}

export interface Room {
  id: string;
  number: string;
  floor: number | null;
  room_type: string | null;
  status: RoomStatus;
  is_active: boolean;
  open_stay: StaySummary | null;
}

export interface Stay {
  id: string;
  room_id: string;
  room_number: string;
  guest_name: string | null;
  guest_count: number;
  checkin_at: string;
  expected_checkout_at: string;
  room_charge_vnd: number;
  note: string | null;
  status: StayStatus;
  code_issued_at: string;
  closed_at: string | null;
}

export interface IssuedCode {
  room_code: string; // XXXX-XXXX, shown once
  qr_payload: string;
}

export interface CheckInResponse extends IssuedCode {
  stay: Stay;
}

/** Slip content: everything printed for the guest. Kept only in component state. */
export interface SlipData extends IssuedCode {
  roomNumber: string;
  guestName: string | null;
  expectedCheckoutAt: string;
}

/** "2026-11-21T12:00" (datetime-local, hotel's local time) -> ISO string with offset. */
export function localInputToIso(value: string): string {
  return new Date(value).toISOString();
}

/** Default checkout: tomorrow 12:00 local, in datetime-local format. */
export function defaultCheckoutInput(now: Date = new Date()): string {
  const d = new Date(now);
  d.setDate(d.getDate() + 1);
  d.setHours(12, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T12:00`;
}

export function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
