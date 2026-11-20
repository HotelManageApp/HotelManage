/// Build-time configuration, passed with
/// `--dart-define-from-file=env/<env>.json`.
class AppConfig {
  const new({required this.apiBaseUrl, required this.appEnv, String? aiBaseUrl})
    : aiBaseUrl = aiBaseUrl ?? apiBaseUrl;

  /// Reads values compiled in via `--dart-define`.
  ///
  /// Throws naming the missing key.
  factory fromEnvironment() {
    return AppConfig.fromMap(const {
      'API_BASE_URL': String.fromEnvironment('API_BASE_URL'),
      'APP_ENV': String.fromEnvironment('APP_ENV'),
      'AI_BASE_URL': String.fromEnvironment('AI_BASE_URL'),
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
    final ai = values['AI_BASE_URL'] ?? '';
    if (env == 'prod') {
      // Release builds talk to the hotel over HTTPS only: tokens travel in
      // headers.
      for (final url in [values['API_BASE_URL']!, if (ai.isNotEmpty) ai]) {
        if (!url.startsWith('https://')) {
          throw StateError('APP_ENV=prod needs https:// URLs, got "$url"');
        }
      }
    }
    return AppConfig(
      apiBaseUrl: values['API_BASE_URL']!,
      appEnv: env,
      aiBaseUrl: ai.isEmpty ? null : ai,
    );
  }

  final String apiBaseUrl;
  final String appEnv;

  /// ai-service (`POST /api/v1/chat`). Optional: without it the app calls the
  /// API host, for deployments where a reverse proxy routes /api/v1/chat.
  final String aiBaseUrl;

  bool get isProd => appEnv == 'prod';
}
