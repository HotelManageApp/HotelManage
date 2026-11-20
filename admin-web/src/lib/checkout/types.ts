/** Express checkout and bills as returned by backend-api (SPEC-express-checkout). */

export type CheckoutStatus = "CHECKOUT_REQUESTED" | "BILLING_VERIFIED" | "COMPLETED" | "REJECTED";

export type BillLineType = "ROOM" | "FOOD" | "EXTRA" | "DISCOUNT";

export interface BillLine {
  type: BillLineType;
  description: string;
  amount_vnd: number; // always positive; DISCOUNT is subtracted
  order_id: string | null;
  charge_id: string | null;
}

export interface Bill {
  stay: {
    room_number: string;
    guest_name: string | null;
    checkin_at: string;
    expected_checkout_at: string;
  };
  lines: BillLine[];
  total_vnd: number;
  open_orders: number;
  currency: "VND";
  generated_at: string;
}

export interface CheckoutRequest {
  id: string;
  stay_id: string;
  room_number: string;
  guest_name: string | null;
  status: CheckoutStatus;
  source: string;
  feedback_rating: number | null;
  feedback_note: string | null;
  total_vnd: number | null;
  payment_method: string | null;
  reject_reason: string | null;
  created_at: string;
  verified_at: string | null;
  completed_at: string | null;
  rejected_at: string | null;
  version: number;
  overdue: boolean;
  open_orders: number;
}

export interface CheckoutDetail extends CheckoutRequest {
  bill: Bill | null;
  bill_is_snapshot: boolean;
  open_order_ids: string[];
  history: {
    from_status: string | null;
    to_status: string;
    at: string;
    by: string;
    reason: string | null;
  }[];
}

export const PAYMENT_METHODS = ["CASH", "BANK_TRANSFER", "CARD", "OTHER"] as const;
export type PaymentMethod = (typeof PAYMENT_METHODS)[number];

export const OPEN_STATUSES: CheckoutStatus[] = ["CHECKOUT_REQUESTED", "BILLING_VERIFIED"];
