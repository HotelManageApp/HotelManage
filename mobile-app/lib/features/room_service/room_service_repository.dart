import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show FutureProviderFamily;
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/notifications/notifications_controller.dart';
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

  /// The stay's orders, newest first (the backend returns at most 50).
  Future<List<FoodOrder>> myOrders() async {
    final data = await _api.get('/api/v1/guest/orders');
    return [
      for (final o in data as List)
        FoodOrder.fromJson(Map<String, dynamic>.from(o as Map)),
    ];
  }

  /// One order with its status history.
  Future<FoodOrder> order(String id) async {
    final data = await _api.get('/api/v1/guest/orders/$id');
    return FoodOrder.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// Allowed while the order is PENDING; otherwise `409`.
  Future<FoodOrder> cancel(String id) async {
    final data = await _api.post('/api/v1/guest/orders/$id/cancel');
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

final FutureProvider<List<FoodOrder>> myOrdersProvider =
    FutureProvider.autoDispose<List<FoodOrder>>((ref) {
      reloadOnPush(ref, 'FOOD_ORDER');
      return ref.watch(roomServiceRepositoryProvider).myOrders();
    }, retry: (retryCount, error) => null);

final FutureProviderFamily<FoodOrder, String> orderProvider = FutureProvider
    .autoDispose
    .family<FoodOrder, String>((ref, id) {
      reloadOnPush(ref, 'FOOD_ORDER');
      return ref.watch(roomServiceRepositoryProvider).order(id);
    }, retry: (retryCount, error) => null);
