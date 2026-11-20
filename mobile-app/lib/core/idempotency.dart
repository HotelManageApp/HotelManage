import 'dart:math';

/// 32 random [0-9a-f] characters, within the backend's `[A-Za-z0-9_-]{8,64}`.
String newIdempotencyKey([Random? random]) {
  final rng = random ?? Random.secure();
  return List.generate(32, (_) => rng.nextInt(16).toRadixString(16)).join();
}
