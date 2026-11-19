import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/core/providers.dart';
import 'package:hotel_guest/features/stay_access/session_store.dart';
import 'package:hotel_guest/features/stay_access/stay_repository.dart';

/// Why the guest is on the welcome screen (shown as a one-line notice).
enum SignedOutReason { none, stayClosed, sessionEnded }

sealed class SessionState {
  const new();
}

class SignedOut extends SessionState {
  const new([this.reason = SignedOutReason.none]);

  final SignedOutReason reason;
}

class SignedIn extends SessionState {
  const new(this.stay);

  final GuestStay stay;
}

final sessionStoreProvider = Provider<SessionStore>(
  (ref) => SecureSessionStore(),
);

final stayRepositoryProvider = Provider<StayRepository>(
  (ref) => StayRepository(ref.watch(apiClientProvider)),
);

SignedOutReason reasonFor(AppException error) =>
    error.endReason == 'STAY_CLOSED'
    ? SignedOutReason.stayClosed
    : SignedOutReason.sessionEnded;

/// Owns the guest token: restores it at start-up, logs in with a room code,
/// and signs out on logout or on any 401 from an authenticated call.
class SessionController extends AsyncNotifier<SessionState> {
  SessionStore get _store => ref.read(sessionStoreProvider);
  StayRepository get _repo => ref.read(stayRepositoryProvider);

  @override
  Future<SessionState> build() async {
    final api = ref.read(apiClientProvider)
      ..onUnauthorized = (error) => unawaited(_end(reasonFor(error)));
    final token = await _store.readToken();
    if (token == null) return const SignedOut();
    api.token = token;
    try {
      return SignedIn(await _repo.me());
    } on AppException catch (error) {
      if (!error.isUnauthorized) rethrow;
      await _forget();
      return SignedOut(reasonFor(error));
    }
  }

  /// Throws [AppException] on failure; the caller shows the message.
  Future<void> login(String code, {required String lang}) async {
    final result = await _repo.loginWithCode(
      code: code,
      deviceId: await _store.deviceId(),
      lang: lang,
    );
    await _store.writeToken(result.token);
    ref.read(apiClientProvider).token = result.token;
    state = AsyncData(SignedIn(result.stay));
  }

  Future<void> logout() async {
    try {
      await _repo.logout();
    } on AppException {
      // Signing out locally is what matters.
    }
    await _forget();
    state = const AsyncData(SignedOut());
  }

  Future<void> _end(SignedOutReason reason) async {
    await _forget();
    state = AsyncData(SignedOut(reason));
  }

  Future<void> _forget() async {
    ref.read(apiClientProvider).token = null;
    await _store.clearToken();
  }
}

final sessionProvider = AsyncNotifierProvider<SessionController, SessionState>(
  SessionController.new,
);
