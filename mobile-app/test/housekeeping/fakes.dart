import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_models.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_repository.dart';
import 'package:hotel_guest/features/stay_access/stay_repository.dart';

GuestStay stayWith({bool dnd = false, String status = 'ACTIVE'}) => GuestStay(
  roomNumber: '101',
  guestName: 'Tran Thi B',
  expectedCheckoutAt: DateTime.now().toUtc().add(const Duration(days: 2)),
  status: status,
  doNotDisturb: dnd,
);

class CreateCall {
  const new({
    required this.type,
    required this.key,
    required this.amenities,
    required this.preferredTime,
    required this.note,
  });

  final String type;
  final String key;
  final List<AmenityLine> amenities;
  final DateTime? preferredTime;
  final String? note;
}

/// Scripted backend for /guest/housekeeping-requests and do-not-disturb.
class FakeHousekeepingRepository implements HousekeepingRepository {
  final List<HkRequest> requests = [];
  final List<CreateCall> creates = [];
  final List<bool> dndCalls = [];
  final List<String> cancels = [];
  final List<String> detailLoads = [];

  /// Thrown by the next create calls, in order.
  final List<AppException> createFailures = [];
  AppException? cancelFailure;

  /// Called after a successful create, e.g. to change what /guest/me says.
  void Function(CreateCall call)? onCreated;

  /// Called after the DND switch is saved.
  void Function(bool enabled)? onDnd;

  int _next = 1;

  @override
  Future<HkRequest> create({
    required String type,
    required String idempotencyKey,
    List<AmenityLine> amenities = const [],
    DateTime? preferredTime,
    String? note,
  }) async {
    final call = CreateCall(
      type: type,
      key: idempotencyKey,
      amenities: amenities,
      preferredTime: preferredTime,
      note: note,
    );
    creates.add(call);
    if (createFailures.isNotEmpty) throw createFailures.removeAt(0);
    final created = HkRequest(
      id: '6f1c2a3b-0000-4000-8000-${(_next++).toString().padLeft(12, '0')}',
      type: type,
      status: 'REQUESTED',
      createdAt: DateTime.now().toUtc(),
      amenities: amenities,
      preferredTime: preferredTime,
      note: note == null || note.isEmpty ? null : note,
    );
    requests.insert(0, created);
    onCreated?.call(call);
    return created;
  }

  @override
  Future<List<HkRequest>> mine() async => List.of(requests);

  @override
  Future<HkRequest> one(String id) async {
    detailLoads.add(id);
    return requests.firstWhere((r) => r.id == id);
  }

  @override
  Future<HkRequest> cancel(String id) async {
    cancels.add(id);
    final failure = cancelFailure;
    if (failure != null) throw failure;
    final index = requests.indexWhere((r) => r.id == id);
    requests[index] = withHkStatus(
      requests[index],
      'CANCELLED',
      reason: 'Khách hủy',
    );
    return requests[index];
  }

  @override
  Future<void> setDoNotDisturb({required bool enabled}) async {
    dndCalls.add(enabled);
    onDnd?.call(enabled);
  }
}

HkRequest withHkStatus(
  HkRequest r,
  String status, {
  String? assignee,
  String? reason,
}) => HkRequest(
  id: r.id,
  type: r.type,
  status: status,
  createdAt: r.createdAt,
  amenities: r.amenities,
  preferredTime: r.preferredTime,
  note: r.note,
  assignee: assignee ?? r.assignee,
  cancelReason: reason,
);

HkRequest cleaning(String id, {String status = 'REQUESTED'}) => HkRequest(
  id: id,
  type: 'CLEANING',
  status: status,
  createdAt: DateTime.now().toUtc().subtract(const Duration(minutes: 3)),
);
