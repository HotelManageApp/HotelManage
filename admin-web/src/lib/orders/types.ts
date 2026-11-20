/** Food orders as returned by GET /api/v1/orders (spec/SPEC-room-service.md). */

export type OrderStatus =
  "PENDING" | "CONFIRMED" | "PREPARING" | "DELIVERING" | "COMPLETED" | "CANCELLED";

export interface OrderLine {
  item_id: string;
  name: string;
  quantity: number;
  unit_price_vnd: number;
  line_total_vnd: number;
  note: string | null;
}

export interface HistoryEntry {
  from_status: string | null;
  to_status: string;
  at: string;
  by: string;
  reason: string | null;
}

export interface StaffOrder {
  id: string;
  status: OrderStatus;
  items: OrderLine[];
  total_vnd: number;
  order_note: string | null;
  source: string;
  estimated_minutes: number | null;
  cancel_reason: string | null;
  created_at: string;
  updated_at: string;
  version: number;
  room_number: string;
  guest_name: string | null;
  overdue: boolean;
  history?: HistoryEntry[] | null;
}

export const BOARD_COLUMNS: OrderStatus[] = ["PENDING", "CONFIRMED", "PREPARING", "DELIVERING"];

/** The one-tap next step for the kitchen, or null when the order is finished. */
export const NEXT_STEP: Partial<Record<OrderStatus, OrderStatus>> = {
  PENDING: "CONFIRMED",
  CONFIRMED: "PREPARING",
  PREPARING: "DELIVERING",
  DELIVERING: "COMPLETED",
};

export const ETA_CHOICES = [15, 25, 40] as const;

export function minutesSince(iso: string, now: Date = new Date()): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 60000));
}

export const vnd = (amount: number) => new Intl.NumberFormat("vi-VN").format(amount) + " ₫";
