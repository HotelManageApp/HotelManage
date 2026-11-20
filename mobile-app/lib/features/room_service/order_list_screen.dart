import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/core/auto_refresh.dart';
import 'package:hotel_guest/features/room_service/order_status.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:intl/intl.dart';
import 'package:material_ui/material_ui.dart';

/// The stay's food orders, newest first.
class OrderListScreen extends ConsumerWidget {
  const new({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final orders = ref.watch(myOrdersProvider);

    return AutoRefresh(
      onRefresh: () => ref.invalidate(myOrdersProvider),
      child: Scaffold(
        appBar: AppBar(title: Text(l10n.ordersTitle)),
        body: RefreshIndicator(
          onRefresh: () => ref.refresh(myOrdersProvider.future),
          child: orders.when(
            skipLoadingOnRefresh: true,
            skipLoadingOnReload: true,
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (error, _) => ListView(
              children: [
                Padding(
                  padding: const EdgeInsets.all(32),
                  child: Center(child: Text(l10n.ordersLoadError)),
                ),
              ],
            ),
            data: (list) => list.isEmpty
                ? ListView(
                    children: [
                      Padding(
                        padding: const EdgeInsets.all(32),
                        child: Center(child: Text(l10n.ordersEmpty)),
                      ),
                    ],
                  )
                : ListView.separated(
                    itemCount: list.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (context, index) =>
                        _OrderTile(order: list[index]),
                  ),
          ),
        ),
      ),
    );
  }
}

class _OrderTile extends StatelessWidget {
  const new({required this.order});

  final FoodOrder order;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context).toLanguageTag();
    final time = DateFormat.Hm(locale).format(order.createdAt.toLocal());
    final dishes = order.items
        .map((l) => '${l.quantity}× ${l.name}')
        .join(', ');
    return ListTile(
      key: Key('order-${order.id}'),
      leading: Icon(orderStatusIcon(order.status)),
      title: Text(orderStatusLabel(l10n, order.status)),
      subtitle: Text('$time · $dishes'),
      trailing: Text(formatVnd(order.totalVnd)),
      onTap: () => context.push('/requests/food_order/${order.id}'),
    );
  }
}
