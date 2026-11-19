import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';

const maxLines = 20;
const maxQuantity = 20;

class CartLine {
  const new({
    required this.itemId,
    required this.name,
    required this.unitPriceVnd,
    this.quantity = 1,
    this.note = '',
  });

  factory fromJson(Map<String, dynamic> json) => CartLine(
    itemId: json['item_id'] as String,
    name: json['name'] as String,
    unitPriceVnd: json['unit_price_vnd'] as int,
    quantity: json['quantity'] as int,
    note: json['note'] as String? ?? '',
  );

  final String itemId;
  final String name;

  /// Menu price when added; for the estimate only. The order's prices come
  /// from the server.
  final int unitPriceVnd;
  final int quantity;
  final String note;

  CartLine copyWith({int? quantity, String? note}) => CartLine(
    itemId: itemId,
    name: name,
    unitPriceVnd: unitPriceVnd,
    quantity: quantity ?? this.quantity,
    note: note ?? this.note,
  );

  Map<String, Object> toJson() => {
    'item_id': itemId,
    'name': name,
    'unit_price_vnd': unitPriceVnd,
    'quantity': quantity,
    'note': note,
  };
}

class CartState {
  const new({
    this.lines = const [],
    this.orderNote = '',
    this.unavailable = const {},
    this.placing = false,
  });

  final List<CartLine> lines;
  final String orderNote;

  /// Dishes the kitchen no longer serves (from `409 ITEM_UNAVAILABLE`).
  final Set<String> unavailable;
  final bool placing;

  bool get isEmpty => lines.isEmpty;
  int get itemCount => lines.fold(0, (sum, line) => sum + line.quantity);

  /// Shown as "estimated"; the real total is the one the server returns.
  int get estimatedTotalVnd =>
      lines.fold(0, (sum, l) => sum + l.unitPriceVnd * l.quantity);

  int quantityOf(String itemId) {
    for (final line in lines) {
      if (line.itemId == itemId) return line.quantity;
    }
    return 0;
  }

  CartState copyWith({
    List<CartLine>? lines,
    String? orderNote,
    Set<String>? unavailable,
    bool? placing,
  }) => CartState(
    lines: lines ?? this.lines,
    orderNote: orderNote ?? this.orderNote,
    unavailable: unavailable ?? this.unavailable,
    placing: placing ?? this.placing,
  );
}

/// Where the cart survives app restarts. One cart, tagged with its stay.
abstract interface class CartStore {
  Future<String?> read();
  Future<void> write(String value);
  Future<void> clear();
}

class SecureCartStore implements CartStore {
  new([FlutterSecureStorage? storage])
    : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _key = 'cart';

  @override
  Future<String?> read() => _storage.read(key: _key);

  @override
  Future<void> write(String value) => _storage.write(key: _key, value: value);

  @override
  Future<void> clear() => _storage.delete(key: _key);
}

/// In-memory store for tests.
class MemoryCartStore implements CartStore {
  new([this.value]);

  String? value;

  @override
  Future<String?> read() async => value;

  @override
  Future<void> write(String value) async => this.value = value;

  @override
  Future<void> clear() async => value = null;
}

final cartStoreProvider = Provider<CartStore>((ref) => SecureCartStore());

/// 32 random [0-9a-f] characters, within the backend's `[A-Za-z0-9_-]{8,64}`.
String newIdempotencyKey([Random? random]) {
  final rng = random ?? Random.secure();
  return List.generate(32, (_) => rng.nextInt(16).toRadixString(16)).join();
}

/// The guest's cart for the current stay. Saved locally per stay and wiped
/// on sign-out.
class CartController extends Notifier<CartState> {
  String? _stayId;

  /// Key of the order being placed; kept only to retry that same order
  /// after a network failure, and dropped once the cart changes.
  String? _pendingKey;

  CartStore get _store => ref.read(cartStoreProvider);

  @override
  CartState build() {
    ref.listen(sessionProvider, (previous, next) {
      final session = next.value;
      if (session is SignedIn) {
        if (session.stayId != _stayId) unawaited(_restore(session.stayId));
      } else if (next.hasValue) {
        _stayId = null;
        _pendingKey = null;
        state = const CartState();
        // Wipe the saved cart when the guest signs out. Starting the app
        // signed out keeps it: a cart of another stay is dropped on restore.
        if (previous?.value is SignedIn) unawaited(_store.clear());
      }
    }, fireImmediately: true);
    return const CartState();
  }

  Future<void> _restore(String? stayId) async {
    _stayId = stayId;
    _pendingKey = null;
    state = const CartState();
    if (stayId == null) return;
    final raw = await _store.read();
    if (raw == null || _stayId != stayId) return;
    try {
      final saved = jsonDecode(raw) as Map<String, dynamic>;
      if (saved['stay_id'] != stayId) {
        await _store.clear();
        return;
      }
      state = CartState(
        lines: [
          for (final l in saved['lines'] as List)
            CartLine.fromJson(Map<String, dynamic>.from(l as Map)),
        ],
        orderNote: saved['order_note'] as String? ?? '',
      );
    } on Object {
      // A cart we cannot read is not worth an error screen.
      await _store.clear();
    }
  }

  void _update(CartState next) {
    _pendingKey = null;
    state = next;
    final stayId = _stayId;
    if (stayId == null) return;
    unawaited(
      _store.write(
        jsonEncode({
          'stay_id': stayId,
          'lines': [for (final l in next.lines) l.toJson()],
          'order_note': next.orderNote,
        }),
      ),
    );
  }

  /// Adds one of [item]; false when the cart or the line is full.
  bool add(MenuItem item) {
    final index = state.lines.indexWhere((l) => l.itemId == item.id);
    if (index >= 0) return increment(item.id);
    if (state.lines.length >= maxLines) return false;
    _update(
      state.copyWith(
        lines: [
          ...state.lines,
          CartLine(
            itemId: item.id,
            name: item.name,
            unitPriceVnd: item.priceVnd,
          ),
        ],
      ),
    );
    return true;
  }

  bool increment(String itemId) {
    final line = _line(itemId);
    if (line == null || line.quantity >= maxQuantity) return false;
    _replace(line.copyWith(quantity: line.quantity + 1));
    return true;
  }

  void decrement(String itemId) {
    final line = _line(itemId);
    if (line == null) return;
    if (line.quantity <= 1) {
      remove(itemId);
    } else {
      _replace(line.copyWith(quantity: line.quantity - 1));
    }
  }

  void remove(String itemId) => _update(
    state.copyWith(
      lines: [
        for (final l in state.lines)
          if (l.itemId != itemId) l,
      ],
      unavailable: {...state.unavailable}..remove(itemId),
    ),
  );

  void setNote(String itemId, String note) {
    final line = _line(itemId);
    if (line != null) _replace(line.copyWith(note: note.trim()));
  }

  void setOrderNote(String note) =>
      _update(state.copyWith(orderNote: note.trim()));

  /// Places the cart as one order. Returns the order as the server made it
  /// and empties the cart. Throws [AppException]; on `ITEM_UNAVAILABLE` the
  /// dishes concerned are marked and the menu is reloaded.
  Future<FoodOrder> placeOrder() async {
    if (state.isEmpty || state.placing) {
      throw StateError('Nothing to order or already placing');
    }
    final key = _pendingKey ??= newIdempotencyKey();
    state = state.copyWith(placing: true);
    try {
      final order = await ref
          .read(roomServiceRepositoryProvider)
          .placeOrder(
            items: [
              for (final l in state.lines)
                NewOrderLine(
                  itemId: l.itemId,
                  quantity: l.quantity,
                  note: l.note,
                ),
            ],
            orderNote: state.orderNote,
            idempotencyKey: key,
          );
      _update(const CartState());
      return order;
    } on AppException catch (error) {
      // Only a request that may not have reached the server is retried with
      // the same key; any answer from the server ends this attempt.
      if (!error.isNetworkError) _pendingKey = null;
      state = state.copyWith(placing: false);
      if (error.code == 'ITEM_UNAVAILABLE') {
        state = state.copyWith(
          unavailable: {
            for (final detail in error.details)
              if (detail['item_id'] is String) detail['item_id'] as String,
          },
        );
        ref.invalidate(menuProvider);
      }
      rethrow;
    }
  }

  CartLine? _line(String itemId) {
    for (final line in state.lines) {
      if (line.itemId == itemId) return line;
    }
    return null;
  }

  void _replace(CartLine line) => _update(
    state.copyWith(
      lines: [
        for (final l in state.lines)
          if (l.itemId == line.itemId) line else l,
      ],
    ),
  );
}

final cartProvider = NotifierProvider<CartController, CartState>(
  CartController.new,
);
