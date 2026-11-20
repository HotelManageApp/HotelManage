import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/core/config.dart';

void main() {
  test('reads valid values', () {
    final config = AppConfig.fromMap({
      'API_BASE_URL': 'http://10.0.2.2:8000',
      'APP_ENV': 'dev',
    });
    expect(config.apiBaseUrl, 'http://10.0.2.2:8000');
    expect(config.isProd, isFalse);
  });

  test('names every missing key', () {
    expect(
      () => AppConfig.fromMap({}),
      throwsA(
        isA<StateError>().having(
          (e) => e.message,
          'message',
          allOf(contains('API_BASE_URL'), contains('APP_ENV')),
        ),
      ),
    );
  });

  test('rejects unknown APP_ENV', () {
    expect(
      () =>
          AppConfig.fromMap({'API_BASE_URL': 'http://x', 'APP_ENV': 'staging'}),
      throwsStateError,
    );
  });

  test('fromEnvironment fails without --dart-define in tests', () {
    expect(AppConfig.fromEnvironment, throwsStateError);
  });

  test('prod builds only accept https URLs', () {
    expect(
      () => AppConfig.fromMap({
        'API_BASE_URL': 'http://api.hotel.vn',
        'APP_ENV': 'prod',
      }),
      throwsA(
        isA<StateError>().having(
          (e) => e.message,
          'message',
          contains('https'),
        ),
      ),
    );
    expect(
      () => AppConfig.fromMap({
        'API_BASE_URL': 'https://api.hotel.vn',
        'AI_BASE_URL': 'http://ai.hotel.vn',
        'APP_ENV': 'prod',
      }),
      throwsStateError,
    );
    final ok = AppConfig.fromMap({
      'API_BASE_URL': 'https://api.hotel.vn',
      'APP_ENV': 'prod',
    });
    expect(ok.isProd, isTrue);
    expect(ok.aiBaseUrl, 'https://api.hotel.vn');
  });
}
