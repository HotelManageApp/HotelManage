/// Express checkout as the guest sees it (SPEC-express-checkout, API khách).
/// Amounts are whole VND computed by the server; the app never adds them up.
library;

class BillLine {
  const new({
    required this.type,
    required this.description,
    required this.amountVnd,
  });

  factory fromJson(Map<String, dynamic> json) => BillLine(
    type: json['type'] as String,
    description: json['description'] as String,
    amountVnd: json['amount_vnd'] as int,
  );

  /// ROOM, FOOD, EXTRA or DISCOUNT (subtracted from the total).
  final String type;
  final String description;

  /// Always positive.
  final int amountVnd;

  bool get isDiscount => type == 'DISCOUNT';
}

class GuestBill {
  const new({
    required this.lines,
    required this.totalVnd,
    required this.openOrders,
    required this.isEstimate,
  });

  factory fromJson(Map<String, dynamic> json) => GuestBill(
    lines: [
      for (final line in json['lines'] as List)
        BillLine.fromJson(Map<String, dynamic>.from(line as Map)),
    ],
    totalVnd: json['total_vnd'] as int,
    openOrders: json['open_orders'] as int? ?? 0,
    isEstimate: json['is_estimate'] as bool? ?? true,
  );

  final List<BillLine> lines;
  final int totalVnd;

  /// Food orders still being prepared or delivered: not billed yet, and
  /// reception cannot verify the bill until they are done.
  final int openOrders;

  /// True for the live estimate, false for the bill reception verified.
  final bool isEstimate;
}

/// The stay's latest checkout request.
class CheckoutRequest {
  const new({
    required this.id,
    required this.status,
    required this.createdAt,
    this.rejectReason,
    this.bill,
  });

  factory fromJson(Map<String, dynamic> json) => CheckoutRequest(
    id: json['id'] as String,
    status: json['status'] as String,
    createdAt: DateTime.parse(json['created_at'] as String),
    rejectReason: json['reject_reason'] as String?,
    bill: json['bill'] == null
        ? null
        : GuestBill.fromJson(Map<String, dynamic>.from(json['bill'] as Map)),
  );

  final String id;

  /// CHECKOUT_REQUESTED, BILLING_VERIFIED, COMPLETED or REJECTED.
  final String status;
  final DateTime createdAt;
  final String? rejectReason;

  /// The frozen bill, once reception verified it.
  final GuestBill? bill;

  bool get isOpen =>
      status == 'CHECKOUT_REQUESTED' || status == 'BILLING_VERIFIED';
  bool get isRejected => status == 'REJECTED';
}

/// Sent → verified → completed; REJECTED is shown apart.
const checkoutProgress = [
  'CHECKOUT_REQUESTED',
  'BILLING_VERIFIED',
  'COMPLETED',
];
