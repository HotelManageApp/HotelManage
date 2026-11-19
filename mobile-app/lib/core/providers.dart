import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/config.dart';

/// Overridden in `main.dart` (from --dart-define) and in tests.
final appConfigProvider = Provider<AppConfig>(
  (ref) => AppConfig.fromEnvironment(),
);

final apiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient.create(ref.watch(appConfigProvider).apiBaseUrl),
);

/// No automatic retry: the welcome screen has a manual "retry" button.
final FutureProvider<BackendHealth> backendHealthProvider =
    FutureProvider.autoDispose<BackendHealth>(
      (ref) => ref.watch(apiClientProvider).health(),
      retry: (retryCount, error) => null,
    );

const supportedLocales = [Locale('vi'), Locale('en')];

/// Current UI language; Vietnamese by default.
class LocaleController extends Notifier<Locale> {
  @override
  Locale build() => const Locale('vi');

  void select(Locale locale) {
    if (supportedLocales.contains(locale)) state = locale;
  }
}

final localeProvider = NotifierProvider<LocaleController, Locale>(
  LocaleController.new,
);
