import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/config.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/express_checkout/checkout_repository.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:hotel_guest/features/stay_access/stay_repository.dart';

import '../express_checkout/fakes.dart';

final stay101 = GuestStay(
  roomNumber: '101',
  guestName: 'Tran Thi B',
  expectedCheckoutAt: DateTime.utc(2026, 11, 21, 5),
  status: 'ACTIVE',
);

AppException apiError(
  int status,
  String code, {
  String? reason,
  int? retryAfter,
}) => AppException(
  status: status,
  code: code,
  message: code,
  details: reason == null
      ? const []
      : [
          {'reason': reason},
        ],
  retryAfterSeconds: retryAfter,
);

/// Scripted backend for the guest endpoints.
class FakeStayRepository implements StayRepository {
  new({this.meResult, this.loginResult});

  Object? meResult; // GuestStay or AppException
  Object? loginResult; // GuestLogin or AppException
  final List<Map<String, String>> logins = [];
  int logouts = 0;

  @override
  Future<GuestLogin> loginWithCode({
    required String code,
    required String deviceId,
    required String lang,
  }) async {
    logins.add({'code': code, 'deviceId': deviceId, 'lang': lang});
    final result = loginResult;
    if (result is AppException) throw result;
    return result as GuestLogin? ?? GuestLogin(token: 'tok-1', stay: stay101);
  }

  @override
  Future<GuestStay> me() async {
    final result = meResult;
    if (result is AppException) throw result;
    return result as GuestStay? ?? stay101;
  }

  @override
  Future<void> logout() async => logouts++;
}

List<Override> sessionOverrides({
  required FakeStayRepository repo,
  required MemorySessionStore store,
  ApiClient? api,
  FakeCheckoutRepository? checkout,
}) => [
  appConfigProvider.overrideWithValue(
    const AppConfig(apiBaseUrl: 'http://backend.test', appEnv: 'test'),
  ),
  if (api != null) apiClientProvider.overrideWithValue(api),
  stayRepositoryProvider.overrideWithValue(repo),
  sessionStoreProvider.overrideWithValue(store),
  // No checkout request unless a test scripts one.
  checkoutRepositoryProvider.overrideWithValue(
    checkout ?? FakeCheckoutRepository(),
  ),
];
