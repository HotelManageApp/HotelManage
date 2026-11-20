import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/room_service/cart_controller.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// Cart: quantities and notes, an estimate, and placing the order. The total
/// the guest is told after ordering is the one the server returned.
class CartScreen extends ConsumerWidget {
  const new({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final cart = ref.watch(cartProvider);
    final controller = ref.read(cartProvider.notifier);
    final menu = ref.watch(menuProvider).value;
    final session = ref.watch(sessionProvider).value;
    final checkoutPending = session is SignedIn && session.stay.checkoutPending;
    final kitchenOpen = menu?.isOpenNow ?? true;
    final canPlace =
        !cart.isEmpty &&
        !cart.placing &&
        kitchenOpen &&
        !checkoutPending &&
        cart.unavailable.isEmpty;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.cartTitle)),
      body: cart.isEmpty
          ? Center(child: Text(l10n.cartEmpty))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (checkoutPending)
                  Text(l10n.menuCheckoutPending)
                else if (menu != null && !kitchenOpen)
                  Text(l10n.menuClosed(menu.serviceHours)),
                for (final line in cart.lines)
                  _LineCard(
                    line: line,
                    unavailable: cart.unavailable.contains(line.itemId),
                  ),
                const SizedBox(height: 8),
                TextFormField(
                  key: const Key('order-note'),
                  initialValue: cart.orderNote,
                  maxLength: 300,
                  decoration: InputDecoration(labelText: l10n.cartOrderNote),
                  onChanged: controller.setOrderNote,
                ),
                const SizedBox(height: 8),
                Text(
                  l10n.cartEstimate(formatVnd(cart.estimatedTotalVnd)),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Text(
                  l10n.cartEstimateHint,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
      bottomNavigationBar: cart.isEmpty
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: FilledButton(
                  key: const Key('place-order'),
                  onPressed: canPlace ? () => _place(context, ref) : null,
                  child: cart.placing
                      ? const SizedBox.square(
                          dimension: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Text(l10n.cartPlace),
                ),
              ),
            ),
    );
  }

  Future<void> _place(BuildContext context, WidgetRef ref) async {
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final router = GoRouter.of(context);
    try {
      final order = await ref.read(cartProvider.notifier).placeOrder();
      if (!context.mounted) return;
      await showDialog<void>(
        context: context,
        builder: (context) => _PlacedDialog(order: order),
      );
      router.go('/requests/food_order/${order.id}');
    } on AppException catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(_message(l10n, error))));
    }
  }

  static String _message(AppLocalizations l10n, AppException error) {
    if (error.isNetworkError) return l10n.errorOrderNetwork;
    return switch (error.code) {
      'KITCHEN_CLOSED' => l10n.errorKitchenClosed,
      'ITEM_UNAVAILABLE' => l10n.errorItemUnavailable,
      'TOO_MANY_PENDING_ORDERS' => l10n.errorTooManyPending,
      'STAY_CHECKOUT_PENDING' => l10n.errorCheckoutPending,
      _ => l10n.errorOrderFailed,
    };
  }
}

class _LineCard extends ConsumerWidget {
  const new({required this.line, required this.unavailable});

  final CartLine line;
  final bool unavailable;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final cart = ref.read(cartProvider.notifier);
    final error = Theme.of(context).colorScheme.error;

    return Card(
      key: Key('line-${line.itemId}'),
      shape: unavailable
          ? RoundedRectangleBorder(
              side: BorderSide(color: error, width: 2),
              borderRadius: BorderRadius.circular(12),
            )
          : null,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    line.name,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                IconButton(
                  tooltip: l10n.menuRemoveOne(line.name),
                  icon: const Icon(Icons.remove_circle_outline),
                  onPressed: () => cart.decrement(line.itemId),
                ),
                Text('${line.quantity}'),
                IconButton(
                  tooltip: l10n.menuAdd(line.name),
                  icon: const Icon(Icons.add_circle_outline),
                  onPressed: unavailable
                      ? null
                      : () {
                          if (!cart.increment(line.itemId)) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text(l10n.cartFull)),
                            );
                          }
                        },
                ),
                IconButton(
                  tooltip: l10n.cartRemove(line.name),
                  icon: const Icon(Icons.delete_outline),
                  onPressed: () => cart.remove(line.itemId),
                ),
              ],
            ),
            Text(formatVnd(line.unitPriceVnd * line.quantity)),
            if (unavailable)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  l10n.cartUnavailable,
                  style: TextStyle(color: error),
                ),
              ),
            TextFormField(
              key: Key('note-${line.itemId}'),
              initialValue: line.note,
              maxLength: 200,
              decoration: InputDecoration(labelText: l10n.cartLineNote),
              onChanged: (value) => cart.setNote(line.itemId, value),
            ),
          ],
        ),
      ),
    );
  }
}

class _PlacedDialog extends StatelessWidget {
  const new({required this.order});

  final FoodOrder order;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.orderPlacedTitle),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final line in order.items)
            Text(
              '${line.quantity} × ${line.name} — '
              '${formatVnd(line.lineTotalVnd)}',
            ),
          const SizedBox(height: 8),
          Text(
            l10n.orderPlacedTotal(formatVnd(order.totalVnd)),
            key: const Key('placed-total'),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Text(l10n.orderPlacedHint),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(l10n.ok),
        ),
      ],
    );
  }
}
