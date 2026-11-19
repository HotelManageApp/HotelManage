/// Build-time configuration, passed with
/// `--dart-define-from-file=env/<env>.json`.
class AppConfig {
  const new({required this.apiBaseUrl, required this.appEnv});

  /// Reads values compiled in via `--dart-define`.
  ///
  /// Throws naming the missing key.
  factory fromEnvironment() {
    return AppConfig.fromMap(const {
      'API_BASE_URL': String.fromEnvironment('API_BASE_URL'),
      'APP_ENV': String.fromEnvironment('APP_ENV'),
    });
  }

  factory fromMap(Map<String, String> values) {
    final missing = [
      for (final key in const ['API_BASE_URL', 'APP_ENV'])
        if ((values[key] ?? '').isEmpty) key,
    ];
    if (missing.isNotEmpty) {
      throw StateError(
        'Missing required build setting(s): ${missing.join(', ')}. '
        'Run with --dart-define-from-file=env/dev.json',
      );
    }
    final env = values['APP_ENV']!;
    if (!const ['dev', 'test', 'prod'].contains(env)) {
      throw StateError('Invalid APP_ENV "$env" (expected dev, test or prod)');
    }
    return AppConfig(apiBaseUrl: values['API_BASE_URL']!, appEnv: env);
  }

  final String apiBaseUrl;
  final String appEnv;

  bool get isProd => appEnv == 'prod';
}
