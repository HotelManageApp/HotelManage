import 'package:intl/intl.dart';

/// Integer VND as shown to guests, e.g. "65.000 ₫".
String formatVnd(int amount) =>
    '${NumberFormat.decimalPattern('vi').format(amount)} ₫';

class MenuCategory {
  const new({required this.code, required this.name});

  factory fromJson(Map<String, dynamic> json) =>
      MenuCategory(code: json['code'] as String, name: json['name'] as String);

  final String code;
  final String name;
}

class MenuItem {
  const new({
    required this.id,
    required this.name,
    required this.category,
    required this.priceVnd,
    required this.available,
    this.description,
  });

  factory fromJson(Map<String, dynamic> json) => MenuItem(
    id: json['item_id'] as String,
    name: json['name'] as String,
    category: json['category'] as String,
    priceVnd: json['price_vnd'] as int,
    available: json['available'] as bool,
    description: json['description'] as String?,
  );

  final String id;
  final String name;
  final String category;
  final int priceVnd;
  final bool available;
  final String? description;
}

/// `GET /api/v1/guest/menu`.
class GuestMenu {
  const new({
    required this.serviceHours,
    required this.isOpenNow,
    required this.categories,
    required this.items,
  });

  factory fromJson(Map<String, dynamic> json) => GuestMenu(
    serviceHours: json['service_hours'] as String,
    isOpenNow: json['is_open_now'] as bool,
    categories: [
      for (final c in json['categories'] as List)
        MenuCategory.fromJson(Map<String, dynamic>.from(c as Map)),
    ],
    items: [
      for (final i in json['items'] as List)
        MenuItem.fromJson(Map<String, dynamic>.from(i as Map)),
    ],
  );

  final String serviceHours;
  final bool isOpenNow;
  final List<MenuCategory> categories;
  final List<MenuItem> items;
}

class OrderLine {
  const new({
    required this.itemId,
    required this.name,
    required this.quantity,
    required this.unitPriceVnd,
    required this.lineTotalVnd,
    this.note,
  });

  factory fromJson(Map<String, dynamic> json) => OrderLine(
    itemId: json['item_id'] as String,
    name: json['name'] as String,
    quantity: json['quantity'] as int,
    unitPriceVnd: json['unit_price_vnd'] as int,
    lineTotalVnd: json['line_total_vnd'] as int,
    note: json['note'] as String?,
  );

  final String itemId;
  final String name;
  final int quantity;
  final int unitPriceVnd;
  final int lineTotalVnd;
  final String? note;
}

/// A food order as the backend returns it. Prices and the total are the
/// server's, never computed by the app (C2.4).
class FoodOrder {
  const new({
    required this.id,
    required this.status,
    required this.items,
    required this.totalVnd,
    required this.createdAt,
    required this.version,
    this.orderNote,
    this.estimatedMinutes,
    this.cancelReason,
  });

  factory fromJson(Map<String, dynamic> json) => FoodOrder(
    id: json['id'] as String,
    status: json['status'] as String,
    items: [
      for (final l in json['items'] as List)
        OrderLine.fromJson(Map<String, dynamic>.from(l as Map)),
    ],
    totalVnd: json['total_vnd'] as int,
    createdAt: DateTime.parse(json['created_at'] as String),
    version: json['version'] as int,
    orderNote: json['order_note'] as String?,
    estimatedMinutes: json['estimated_minutes'] as int?,
    cancelReason: json['cancel_reason'] as String?,
  );

  final String id;
  final String status;
  final List<OrderLine> items;
  final int totalVnd;
  final DateTime createdAt;
  final int version;
  final String? orderNote;
  final int? estimatedMinutes;
  final String? cancelReason;
}

/// One line of the order being placed: no price, total, room or stay
/// (the server decides those).
class NewOrderLine {
  const new({required this.itemId, required this.quantity, this.note});

  final String itemId;
  final int quantity;
  final String? note;

  Map<String, Object> toJson() => {
    'item_id': itemId,
    'quantity': quantity,
    if (note != null && note!.isNotEmpty) 'note': note!,
  };
}
