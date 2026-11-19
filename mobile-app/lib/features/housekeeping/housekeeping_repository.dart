import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show FutureProviderFamily;
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_models.dart';
import 'package:hotel_guest/features/notifications/notifications_controller.dart';

/// Calls to /api/v1/guest/housekeeping-requests and /guest/me/do-not-disturb.
/// Errors are AppException.
class HousekeepingRepository {
  const new(this._api);

  final ApiClient _api;

  /// [preferredTime] null means as soon as possible. No room, stay or
  /// assignee is sent: the server decides those.
  Future<HkRequest> create({
    required String type,
    required String idempotencyKey,
    List<AmenityLine> amenities = const [],
    DateTime? preferredTime,
    String? note,
  }) async {
    final data = await _api.post(
      '/api/v1/guest/housekeeping-requests',
      body: {
        'type': type,
        if (amenities.isNotEmpty)
          'amenities': [for (final a in amenities) a.toJson()],
        'preferred_time': preferredTime?.toUtc().toIso8601String() ?? 'ASAP',
        if (note != null && note.isNotEmpty) 'note': note,
        'source': 'APP',
      },
      headers: {'Idempotency-Key': idempotencyKey},
    );
    return HkRequest.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// The stay's requests, newest first.
  Future<List<HkRequest>> mine() async {
    final data = await _api.get('/api/v1/guest/housekeeping-requests');
    return [
      for (final r in data as List)
        HkRequest.fromJson(Map<String, dynamic>.from(r as Map)),
    ];
  }

  /// One request with its status history.
  Future<HkRequest> one(String id) async {
    final data = await _api.get('/api/v1/guest/housekeeping-requests/$id');
    return HkRequest.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// Allowed while REQUESTED; otherwise `409`.
  Future<HkRequest> cancel(String id) async {
    final data = await _api.post(
      '/api/v1/guest/housekeeping-requests/$id/cancel',
    );
    return HkRequest.fromJson(Map<String, dynamic>.from(data as Map));
  }

  Future<void> setDoNotDisturb({required bool enabled}) =>
      _api.put('/api/v1/guest/me/do-not-disturb', body: {'enabled': enabled});
}

final housekeepingRepositoryProvider = Provider<HousekeepingRepository>(
  (ref) => HousekeepingRepository(ref.watch(apiClientProvider)),
);

final FutureProvider<List<HkRequest>> myHkRequestsProvider =
    FutureProvider.autoDispose<List<HkRequest>>((ref) {
      reloadOnPush(ref, 'HOUSEKEEPING');
      return ref.watch(housekeepingRepositoryProvider).mine();
    }, retry: (retryCount, error) => null);

final FutureProviderFamily<HkRequest, String> hkRequestProvider = FutureProvider
    .autoDispose
    .family<HkRequest, String>((ref, id) {
      reloadOnPush(ref, 'HOUSEKEEPING');
      return ref.watch(housekeepingRepositoryProvider).one(id);
    }, retry: (retryCount, error) => null);
