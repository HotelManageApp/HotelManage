import 'package:dio/dio.dart';

/// Error raised by `ApiClient` for every failed request.
///
/// Mirrors the backend error envelope:
/// `{"error": {"code", "message", "details", "request_id"}}` (SPEC-foundation).
class AppException implements Exception {
  const new({
    required this.status,
    required this.code,
    required this.message,
    this.details = const [],
    this.requestId,
  });

  /// Builds an [AppException] from whatever Dio reports.
  factory fromDio(DioException error) {
    final response = error.response;
    if (response == null) {
      final timedOut =
          error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout;
      return AppException(
        status: 0,
        code: timedOut ? 'TIMEOUT' : 'NETWORK_ERROR',
        message: error.message ?? 'Network request failed',
      );
    }

    final status = response.statusCode ?? 0;
    final headerRequestId = response.headers.value('x-request-id');
    final data = response.data;
    if (data is Map && data['error'] is Map) {
      final envelope = Map<String, dynamic>.from(data['error'] as Map);
      final code = envelope['code'];
      final message = envelope['message'];
      if (code is String && message is String) {
        final rawDetails = envelope['details'];
        return AppException(
          status: status,
          code: code,
          message: message,
          details: rawDetails is List
              ? rawDetails
                    .whereType<Map<dynamic, dynamic>>()
                    .map(Map<String, dynamic>.from)
                    .toList()
              : const [],
          requestId: envelope['request_id'] as String? ?? headerRequestId,
        );
      }
    }
    return AppException(
      status: status,
      code: _codeForStatus(status),
      message: response.statusMessage ?? 'HTTP $status',
      requestId: headerRequestId,
    );
  }

  final int status;
  final String code;
  final String message;
  final List<Map<String, dynamic>> details;
  final String? requestId;

  bool get isUnauthorized => status == 401;
  bool get isNetworkError => status == 0;

  static String _codeForStatus(int status) => switch (status) {
    400 => 'BAD_REQUEST',
    401 => 'UNAUTHORIZED',
    403 => 'FORBIDDEN',
    404 => 'NOT_FOUND',
    409 => 'CONFLICT',
    429 => 'RATE_LIMITED',
    >= 500 => 'INTERNAL_ERROR',
    _ => 'BAD_REQUEST',
  };

  @override
  String toString() =>
      'AppException($status $code: $message, requestId: $requestId)';
}
