import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Where the guest token and the device id live between app launches.
abstract class SessionStore {
  Future<String?> readToken();
  Future<void> writeToken(String token);
  Future<void> clearToken();

  /// A random id for this install, created once (used for per-device
  /// sessions and rate limits on the backend).
  Future<String> deviceId();
}

/// Android Keystore-backed storage (never SharedPreferences).
class SecureSessionStore implements SessionStore {
  new([FlutterSecureStorage? storage])
    : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _tokenKey = 'stay_token';
  static const _deviceKey = 'device_id';

  @override
  Future<String?> readToken() => _storage.read(key: _tokenKey);

  @override
  Future<void> writeToken(String token) =>
      _storage.write(key: _tokenKey, value: token);

  @override
  Future<void> clearToken() => _storage.delete(key: _tokenKey);

  @override
  Future<String> deviceId() async {
    final existing = await _storage.read(key: _deviceKey);
    if (existing != null) return existing;
    final created = newDeviceId();
    await _storage.write(key: _deviceKey, value: created);
    return created;
  }
}

/// 32 random characters from [A-Za-z0-9], matching the backend's
/// `^[A-Za-z0-9-]{8,64}$`.
String newDeviceId([Random? random]) {
  const chars =
      'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  final rng = random ?? Random.secure();
  return List.generate(32, (_) => chars[rng.nextInt(chars.length)]).join();
}

/// In-memory store for tests.
class MemorySessionStore implements SessionStore {
  new({this.token, this.device = 'test-device-0001'});

  String? token;
  final String device;

  @override
  Future<String?> readToken() async => token;

  @override
  Future<void> writeToken(String value) async => token = value;

  @override
  Future<void> clearToken() async => token = null;

  @override
  Future<String> deviceId() async => device;
}
