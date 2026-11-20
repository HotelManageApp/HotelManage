/** Housekeeping requests as returned by GET /api/v1/housekeeping-requests (SPEC-housekeeping). */

import type { HistoryEntry } from "@/lib/orders/types";

export type HkType = "CLEANING" | "AMENITY" | "TURNOVER";
export type HkStatus = "REQUESTED" | "ASSIGNED" | "IN_PROGRESS" | "DONE" | "CANCELLED";
export type AmenityCode =
  "TOWEL" | "WATER" | "TOILETRIES" | "PILLOW" | "BLANKET" | "SLIPPERS" | "OTHER";

export interface StaffHkRequest {
  id: string;
  type: HkType;
  status: HkStatus;
  amenities: { code: AmenityCode; quantity: number }[];
  /** null = as soon as possible. */
  preferred_time: string | null;
  note: string | null;
  source: string;
  assignee: string | null;
  cancel_reason: string | null;
  created_at: string;
  updated_at: string;
  version: number;
  room_number: string;
  do_not_disturb: boolean;
  guest_name: string | null;
  assigned_to: string | null;
  assignee_full_name: string | null;
  overdue: boolean;
  history?: HistoryEntry[] | null;
}

export const OPEN_HK: HkStatus[] = ["REQUESTED", "ASSIGNED", "IN_PROGRESS"];

export const isOpen = (r: StaffHkRequest) => OPEN_HK.includes(r.status);

/** Housekeeping state of each room, for the reception room board. */
export interface RoomHousekeeping {
  doNotDisturb: boolean;
  /** "cleaning" while someone is in the room, "waiting" while a request is open. */
  work: "cleaning" | "waiting" | null;
}

export function byRoom(requests: StaffHkRequest[]): Map<string, RoomHousekeeping> {
  const rooms = new Map<string, RoomHousekeeping>();
  for (const r of requests) {
    const current = rooms.get(r.room_number) ?? { doNotDisturb: false, work: null };
    if (r.do_not_disturb && isOpen(r)) current.doNotDisturb = true;
    if (r.status === "IN_PROGRESS") current.work = "cleaning";
    else if (isOpen(r) && current.work === null) current.work = "waiting";
    rooms.set(r.room_number, current);
  }
  return rooms;
}
