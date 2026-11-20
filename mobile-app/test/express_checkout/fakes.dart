import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/express_checkout/checkout_models.dart';
import 'package:hotel_guest/features/express_checkout/checkout_repository.dart';

const requestId = '6f1c2a3b-0000-4000-8000-0000000000e1';

GuestBill bill({bool estimate = true, int openOrders = 0}) => GuestBill(
  lines: const [
    BillLine(type: 'ROOM', description: 'Tiền phòng', amountVnd: 1200000),
    BillLine(type: 'FOOD', description: 'Đơn #A1B2 (2 món)', amountVnd: 130000),
    BillLine(type: 'EXTRA', description: 'Minibar', amountVnd: 60000),
    BillLine(type: 'DISCOUNT', description: 'Khách quen', amountVnd: 50000),
  ],
  // The server's total; the app shows it as is.
  totalVnd: 1340000,
  openOrders: openOrders,
  isEstimate: estimate,
);

CheckoutRequest checkoutRequest(
  String status, {
  String? reason,
  GuestBill? frozen,
}) => CheckoutRequest(
  id: requestId,
  status: status,
  createdAt: DateTime.now().toUtc(),
  rejectReason: reason,
  bill: frozen,
);

class CreateCall {
  const new(this.rating, this.note);

  final int? rating;
  final String? note;
}

/// Scripted backend for /guest/checkout*.
class FakeCheckoutRepository implements CheckoutRepository {
  new({this.currentResult, this.previewResult});

  /// What /checkout-requests/current returns: CheckoutRequest, null (404) or
  /// an AppException.
  Object? currentResult;
  Object? previewResult; // GuestBill or AppException
  final List<CreateCall> creates = [];
  AppException? createFailure;
  int currentLoads = 0;

  /// Runs before each current() result, e.g. to play the API client's 401
  /// handling.
  void Function(Object? result)? beforeCurrent;

  /// Called after a successful create, e.g. to change what /guest/me says.
  void Function()? onCreated;

  @override
  Future<GuestBill> preview() async {
    final result = previewResult;
    if (result is AppException) throw result;
    return result as GuestBill? ?? bill();
  }

  @override
  Future<String> create({int? rating, String? note}) async {
    creates.add(CreateCall(rating, note));
    final failure = createFailure;
    if (failure != null) throw failure;
    currentResult = checkoutRequest('CHECKOUT_REQUESTED');
    onCreated?.call();
    return requestId;
  }

  @override
  Future<CheckoutRequest?> current() async {
    currentLoads++;
    final result = currentResult;
    beforeCurrent?.call(result);
    if (result is AppException) throw result;
    return result as CheckoutRequest?;
  }
}
