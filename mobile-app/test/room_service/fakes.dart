import 'dart:convert';

import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';

const networkError = AppException(
  status: 0,
  code: 'NETWORK_ERROR',
  message: 'Network request failed',
);

/// `409 ITEM_UNAVAILABLE` as the backend sends it, listing the dishes.
AppException itemUnavailable(List<String> ids) => AppException(
  status: 409,
  code: 'ITEM_UNAVAILABLE',
  message: 'Một số món hiện không phục vụ',
  details: [
    for (final id in ids) {'item_id': id},
  ],
);

/// A token shaped like the backend's stay JWT, carrying [stayId].
String tokenFor(String stayId) {
  String part(Map<String, Object> json) =>
      base64Url.encode(utf8.encode(jsonEncode(json))).replaceAll('=', '');
  final header = part({'alg': 'HS256'});
  final claims = part({'stay_id': stayId, 'jti': 'j'});
  return '$header.$claims.sig';
}

const pho = MenuItem(
  id: 'item-pho',
  name: 'Phở bò',
  category: 'MAIN',
  priceVnd: 65000,
  available: true,
  description: 'Bò tái',
);
const coffee = MenuItem(
  id: 'item-coffee',
  name: 'Cà phê sữa',
  category: 'DRINK',
  priceVnd: 35000,
  available: true,
);
const soldOut = MenuItem(
  id: 'item-bun',
  name: 'Bún chả',
  category: 'MAIN',
  priceVnd: 70000,
  available: false,
);

GuestMenu menuOf({bool open = true, List<MenuItem>? items}) => GuestMenu(
  serviceHours: '06:00–22:00',
  isOpenNow: open,
  categories: const [
    MenuCategory(code: 'MAIN', name: 'Món chính'),
    MenuCategory(code: 'DRINK', name: 'Đồ uống'),
  ],
  items: items ?? const [pho, coffee, soldOut],
);

FoodOrder orderFrom(List<NewOrderLine> lines, {int unitPrice = 60000}) {
  final items = [
    for (final l in lines)
      OrderLine(
        itemId: l.itemId,
        name: l.itemId,
        quantity: l.quantity,
        unitPriceVnd: unitPrice,
        lineTotalVnd: unitPrice * l.quantity,
        note: l.note,
      ),
  ];
  return FoodOrder(
    id: '6f1c2a3b-0000-4000-8000-0000000000aa',
    status: 'PENDING',
    items: items,
    totalVnd: items.fold(0, (sum, l) => sum + l.lineTotalVnd),
    createdAt: DateTime.utc(2026, 11, 19, 7),
    version: 0,
  );
}

class PlaceCall {
  const new(this.items, this.orderNote, this.key);

  final List<NewOrderLine> items;
  final String? orderNote;
  final String key;
}

/// Scripted backend for /guest/menu and /guest/orders.
class FakeRoomServiceRepository implements RoomServiceRepository {
  new({GuestMenu? menu}) : menu_ = menu ?? menuOf();

  GuestMenu menu_;
  int menuLoads = 0;
  final List<PlaceCall> calls = [];

  /// Errors to throw on the next place calls, in order; then succeed.
  final List<AppException> failures = [];

  /// Unit price the "server" charges, to prove the app shows its total.
  int serverUnitPrice = 60000;

  @override
  Future<GuestMenu> menu() async {
    menuLoads++;
    return menu_;
  }

  @override
  Future<FoodOrder> placeOrder({
    required List<NewOrderLine> items,
    required String idempotencyKey,
    String? orderNote,
  }) async {
    calls.add(PlaceCall(items, orderNote, idempotencyKey));
    if (failures.isNotEmpty) throw failures.removeAt(0);
    return orderFrom(items, unitPrice: serverUnitPrice);
  }
}
