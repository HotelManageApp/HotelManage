/// Housekeeping requests as the guest sees them (SPEC-housekeeping).
library;

const amenityCodes = [
  'TOWEL',
  'WATER',
  'TOILETRIES',
  'PILLOW',
  'BLANKET',
  'SLIPPERS',
  'OTHER',
];

const maxAmenityQuantity = 5;

/// The happy path, for the progress bar.
const hkProgress = ['REQUESTED', 'ASSIGNED', 'IN_PROGRESS', 'DONE'];

class AmenityLine {
  const new({required this.code, required this.quantity});

  factory fromJson(Map<String, dynamic> json) => AmenityLine(
    code: json['code'] as String,
    quantity: json['quantity'] as int,
  );

  final String code;
  final int quantity;

  Map<String, Object> toJson() => {'code': code, 'quantity': quantity};
}

class HkStep {
  const new({required this.toStatus, required this.at, this.reason});

  factory fromJson(Map<String, dynamic> json) => HkStep(
    toStatus: json['to_status'] as String,
    at: DateTime.parse(json['at'] as String),
    reason: json['reason'] as String?,
  );

  final String toStatus;
  final DateTime at;
  final String? reason;
}

class HkRequest {
  const new({
    required this.id,
    required this.type,
    required this.status,
    required this.createdAt,
    this.amenities = const [],
    this.preferredTime,
    this.note,
    this.assignee,
    this.cancelReason,
    this.history = const [],
  });

  factory fromJson(Map<String, dynamic> json) => HkRequest(
    id: json['id'] as String,
    type: json['type'] as String,
    status: json['status'] as String,
    createdAt: DateTime.parse(json['created_at'] as String),
    amenities: [
      for (final a in (json['amenities'] as List?) ?? const [])
        AmenityLine.fromJson(Map<String, dynamic>.from(a as Map)),
    ],
    preferredTime: json['preferred_time'] == null
        ? null
        : DateTime.parse(json['preferred_time'] as String),
    note: json['note'] as String?,
    assignee: json['assignee'] as String?,
    cancelReason: json['cancel_reason'] as String?,
    history: [
      for (final h in (json['history'] as List?) ?? const [])
        HkStep.fromJson(Map<String, dynamic>.from(h as Map)),
    ],
  );

  final String id;

  /// CLEANING or AMENITY (guests never see TURNOVER).
  final String type;
  final String status;
  final DateTime createdAt;
  final List<AmenityLine> amenities;

  /// null = as soon as possible.
  final DateTime? preferredTime;
  final String? note;

  /// Short name of the staff member on it ("Lan").
  final String? assignee;
  final String? cancelReason;

  /// Only filled by the detail endpoint.
  final List<HkStep> history;

  bool get isOpen => status != 'DONE' && status != 'CANCELLED';

  /// Guests may cancel only before housekeeping claims it (domain-rules §4).
  bool get guestCanCancel => status == 'REQUESTED';
}

/// Times a guest may pick for cleaning: every 30 minutes, from the first
/// half hour at least 30 minutes away, up to 24 hours ahead and not after
/// check-out (the backend enforces the same window).
List<DateTime> cleaningSlots(DateTime now, DateTime checkout) {
  final local = now.toLocal();
  var slot = DateTime(
    local.year,
    local.month,
    local.day,
    local.hour,
    local.minute < 30 ? 30 : 60,
  );
  if (slot.difference(local) < const Duration(minutes: 30)) {
    slot = slot.add(const Duration(minutes: 30));
  }
  final end = local.add(const Duration(hours: 24));
  final last = checkout.toLocal().isBefore(end) ? checkout.toLocal() : end;
  final slots = <DateTime>[];
  for (var t = slot; !t.isAfter(last); t = t.add(const Duration(minutes: 30))) {
    slots.add(t);
  }
  return slots;
}
