import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';

/// Calls to /api/v1/guest/menu and /api/v1/guest/orders (SPEC-room-service).
/// Errors are AppException.
class RoomServiceRepository {
  const new(this._api);

  final ApiClient _api;

  Future<GuestMenu> menu() async {
    final data = await _api.get('/api/v1/guest/menu');
    return GuestMenu.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// [idempotencyKey] is created once per tap on "Place order" and reused
  /// when that same order is retried, so a retry never makes a second order.
  Future<FoodOrder> placeOrder({
    required List<NewOrderLine> items,
    required String idempotencyKey,
    String? orderNote,
  }) async {
    final data = await _api.post(
      '/api/v1/guest/orders',
      body: {
        'items': [for (final line in items) line.toJson()],
        if (orderNote != null && orderNote.isNotEmpty) 'order_note': orderNote,
        'source': 'APP',
      },
      headers: {'Idempotency-Key': idempotencyKey},
    );
    return FoodOrder.fromJson(Map<String, dynamic>.from(data as Map));
  }
}

final roomServiceRepositoryProvider = Provider<RoomServiceRepository>(
  (ref) => RoomServiceRepository(ref.watch(apiClientProvider)),
);

/// The menu in the guest's language. Refreshed by pull-to-refresh and after
/// an order fails because a dish is no longer served.
final FutureProvider<GuestMenu> menuProvider =
    FutureProvider.autoDispose<GuestMenu>(
      (ref) => ref.watch(roomServiceRepositoryProvider).menu(),
      retry: (retryCount, error) => null,
    );
