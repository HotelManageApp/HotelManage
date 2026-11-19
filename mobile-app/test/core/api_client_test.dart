import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_guest/core/api_client.dart';
import 'package:hotel_guest/core/errors.dart';

/// Dio adapter that answers every request with a canned response (or throws).
class FakeAdapter implements HttpClientAdapter {
  new(this.respond);

  final ResponseBody Function(RequestOptions options) respond;
  final List<RequestOptions> requests = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    return respond(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody jsonBody(
  Object body,
  int status, {
  Map<String, String> headers = const {},
}) {
  return ResponseBody.fromString(
    jsonEncode(body),
    status,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
      for (final e in headers.entries) e.key: [e.value],
    },
  );
}

ApiClient clientWith(FakeAdapter adapter) {
  final dio = Dio(BaseOptions(baseUrl: 'http://backend.test'))
    ..httpClientAdapter = adapter;
  return ApiClient(dio);
}

Future<AppException> caught(Future<Object?> future) async {
  try {
    await future;
  } on AppException catch (e) {
    return e;
  }
  fail('expected AppException');
}

void main() {
  test('returns JSON and sends the bearer token', () async {
    final adapter = FakeAdapter((_) => jsonBody({'id': 1}, 200));
    final client = clientWith(adapter)..token = 'tok';

    final data = await client.post('/api/v1/things', body: {'name': 'x'});

    expect(data, {'id': 1});
    expect(adapter.requests.single.headers['Authorization'], 'Bearer tok');
    expect(adapter.requests.single.path, '/api/v1/things');
  });

  test('maps the error envelope to AppException', () async {
    final client = clientWith(
      FakeAdapter(
        (_) => jsonBody({
          'error': {
            'code': 'VALIDATION_ERROR',
            'message': 'Dữ liệu gửi lên không hợp lệ',
            'details': [
              {'field': 'items[0].quantity', 'issue': 'must be >= 1'},
            ],
            'request_id': 'req-1',
          },
        }, 400),
      ),
    );

    final error = await caught(client.get('/x'));

    expect(error.status, 400);
    expect(error.code, 'VALIDATION_ERROR');
    expect(error.message, 'Dữ liệu gửi lên không hợp lệ');
    expect(error.details.single['field'], 'items[0].quantity');
    expect(error.requestId, 'req-1');
  });

  test(
    'falls back to a code from the status for non-envelope bodies',
    () async {
      final client = clientWith(
        FakeAdapter(
          (_) => ResponseBody.fromString(
            'slow down',
            429,
            headers: {
              'x-request-id': ['hdr-1'],
            },
          ),
        ),
      );

      final error = await caught(client.get('/x'));

      expect(error.code, 'RATE_LIMITED');
      expect(error.requestId, 'hdr-1');
    },
  );

  test('marks 401 as unauthorized', () async {
    final client = clientWith(
      FakeAdapter(
        (_) => jsonBody({
          'error': {
            'code': 'UNAUTHORIZED',
            'message': 'x',
            'details': <Object>[],
            'request_id': 'r',
          },
        }, 401),
      ),
    );

    expect((await caught(client.delete('/x'))).isUnauthorized, isTrue);
  });

  test('connection failures become NETWORK_ERROR', () async {
    final client = clientWith(
      FakeAdapter(
        (options) => throw DioException.connectionError(
          requestOptions: options,
          reason: 'refused',
        ),
      ),
    );

    final error = await caught(client.put('/x', body: {}));

    expect(error.code, 'NETWORK_ERROR');
    expect(error.isNetworkError, isTrue);
  });

  test('timeouts become TIMEOUT', () async {
    final client = clientWith(
      FakeAdapter(
        (options) => throw DioException.connectionTimeout(
          requestOptions: options,
          timeout: const Duration(seconds: 5),
        ),
      ),
    );

    expect((await caught(client.get('/x'))).code, 'TIMEOUT');
  });

  group('health', () {
    test('parses a healthy response', () async {
      final client = clientWith(
        FakeAdapter(
          (_) => jsonBody({'status': 'ok', 'db': 'ok', 'version': 'v1'}, 200),
        ),
      );
      final health = await client.health();
      expect(health.ok, isTrue);
      expect(health.dbOk, isTrue);
      expect(health.version, 'v1');
    });

    test('503 is an unhealthy result, not an error', () async {
      final client = clientWith(
        FakeAdapter(
          (_) => jsonBody({
            'status': 'degraded',
            'db': 'error',
            'version': 'v1',
          }, 503),
        ),
      );
      final health = await client.health();
      expect(health.ok, isFalse);
      expect(health.dbOk, isFalse);
    });

    test('other failures are rethrown', () async {
      final client = clientWith(
        FakeAdapter(
          (o) => throw DioException.connectionError(
            requestOptions: o,
            reason: 'down',
          ),
        ),
      );
      expect(client.health(), throwsA(isA<AppException>()));
    });
  });
}
