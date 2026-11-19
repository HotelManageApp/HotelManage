import 'package:dio/dio.dart';

import 'package:hotel_guest/core/errors.dart';

/// Backend health as returned by `GET /health`.
class BackendHealth {
  const new({required this.ok, required this.dbOk, required this.version});

  factory fromJson(Map<String, dynamic> json) => BackendHealth(
    ok: json['status'] == 'ok',
    dbOk: json['db'] == 'ok',
    version: json['version'] as String? ?? '?',
  );

  final bool ok;
  final bool dbOk;
  final String version;
}

/// The only way the app talks to backend-api.
///
/// Every failure surfaces as [AppException].
///
/// Widgets never call this directly; they go through Riverpod providers.
class ApiClient {
  new(this._dio);

  /// Creates a client with the app's default timeouts.
  factory create(String baseUrl) => ApiClient(
    Dio(
      BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: const Duration(seconds: 5),
        receiveTimeout: const Duration(seconds: 15),
        sendTimeout: const Duration(seconds: 15),
        headers: {'Accept': 'application/json'},
      ),
    ),
  );

  final Dio _dio;

  /// Bearer token of the logged-in stay; set by the stay-access feature (T18).
  String? token;

  /// Called when an authenticated request gets 401: the stay ended, the code
  /// was re-issued or the session was revoked. The session controller signs
  /// out.
  void Function(AppException error)? onUnauthorized;

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) => _send(
    () => _dio.get<dynamic>(path, queryParameters: query, options: _options()),
  );

  Future<dynamic> post(
    String path, {
    Object? body,
    Map<String, String>? headers,
  }) => _send(
    () => _dio.post<dynamic>(path, data: body, options: _options(headers)),
  );

  Future<dynamic> put(String path, {Object? body}) =>
      _send(() => _dio.put<dynamic>(path, data: body, options: _options()));

  Future<dynamic> delete(String path) =>
      _send(() => _dio.delete<dynamic>(path, options: _options()));

  /// `GET /health`. A 503 still carries a health body (database down), so it
  /// is returned
  /// as an unhealthy result instead of an error.
  Future<BackendHealth> health() async {
    try {
      final data = await get('/health');
      return BackendHealth.fromJson(Map<String, dynamic>.from(data as Map));
    } on AppException catch (error) {
      if (error.status == 503) {
        return const BackendHealth(ok: false, dbOk: false, version: '?');
      }
      rethrow;
    }
  }

  Options _options([Map<String, String>? extra]) => Options(
    headers: {if (token != null) 'Authorization': 'Bearer $token', ...?extra},
  );

  Future<dynamic> _send(Future<Response<dynamic>> Function() request) async {
    try {
      final response = await request();
      return response.data;
    } on DioException catch (error) {
      final failure = AppException.fromDio(error);
      if (failure.isUnauthorized && token != null) {
        onUnauthorized?.call(failure);
      }
      throw failure;
    }
  }
}
