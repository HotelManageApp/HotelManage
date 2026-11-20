import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/express_checkout/checkout_models.dart';
import 'package:hotel_guest/features/notifications/notifications_controller.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';

/// Calls to /api/v1/guest/checkout*. Errors are AppException.
class CheckoutRepository {
  const new(this._api);

  final ApiClient _api;

  /// The live estimate, built by the server.
  Future<GuestBill> preview() async {
    final data = await _api.get('/api/v1/guest/checkout/preview');
    return GuestBill.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// Sends the request; returns its id. No room, stay or amount is sent: the
  /// server decides those. `409` when one was already sent.
  Future<String> create({int? rating, String? note}) async {
    final data = await _api.post(
      '/api/v1/guest/checkout-requests',
      body: {
        'guest_confirmed': true,
        'feedback_rating': ?rating,
        if (note != null && note.trim().isNotEmpty)
          'feedback_note': note.trim(),
        'source': 'APP',
      },
    );
    return (data as Map)['checkout_request_id'] as String;
  }

  /// The stay's latest request, or null when there is none yet.
  Future<CheckoutRequest?> current() async {
    try {
      final data = await _api.get('/api/v1/guest/checkout-requests/current');
      return CheckoutRequest.fromJson(Map<String, dynamic>.from(data as Map));
    } on AppException catch (error) {
      if (error.status == 404) return null;
      rethrow;
    }
  }
}

final checkoutRepositoryProvider = Provider<CheckoutRepository>(
  (ref) => CheckoutRepository(ref.watch(apiClientProvider)),
);

final FutureProvider<GuestBill> checkoutPreviewProvider =
    FutureProvider.autoDispose<GuestBill>(
      (ref) => ref.watch(checkoutRepositoryProvider).preview(),
      retry: (retryCount, error) => null,
    );

/// The latest request; follows CHECKOUT pushes. When it disagrees with the
/// stay status the app holds (e.g. reception rejected it, so ordering is
/// allowed again), the stay is re-read so every screen unlocks or locks.
final FutureProvider<CheckoutRequest?> currentCheckoutProvider =
    FutureProvider.autoDispose<CheckoutRequest?>((ref) async {
      reloadOnPush(ref, 'CHECKOUT');
      final request = await ref.watch(checkoutRepositoryProvider).current();
      if (!ref.mounted) return request;
      final session = ref.read(sessionProvider).value;
      if (session is SignedIn &&
          session.stay.checkoutPending != (request?.isOpen ?? false)) {
        unawaited(_refreshStay(ref.read(sessionProvider.notifier)));
      }
      return request;
    }, retry: (retryCount, error) => null);

Future<void> _refreshStay(SessionController session) async {
  try {
    await session.refreshStay();
  } on AppException {
    // A 401 already signs out; anything else waits for the next refresh.
  }
}
