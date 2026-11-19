import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/core/auto_refresh.dart';
import 'package:hotel_guest/features/housekeeping/hk_labels.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_models.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_repository.dart';
import 'package:hotel_guest/features/room_service/order_status.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:intl/intl.dart';
import 'package:material_ui/material_ui.dart';

/// Signed-in home: who and where the guest is. Feature tiles (room service,
/// housekeeping, concierge) are added by their modules.
class HomeScreen extends ConsumerWidget {
  const new({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final session = ref.watch(sessionProvider).value;
    if (session is! SignedIn) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final stay = session.stay;
    final locale = Localizations.localeOf(context).toLanguageTag();
    final checkout = DateFormat.yMd(locale)
        .add_Hm()
        .format(stay.expectedCheckoutAt.toLocal());

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.homeRoom(stay.roomNumber)),
        actions: [
          IconButton(
            tooltip: l10n.logout,
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(sessionProvider.notifier).logout(),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            stay.guestName == null
                ? l10n.homeGreetingAnonymous
                : l10n.homeGreeting(stay.guestName!),
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          Text(l10n.homeCheckout(checkout)),
          const SizedBox(height: 16),
          const _OpenOrdersCard(),
          Card(
            child: ListTile(
              key: const Key('tile-order-food'),
              leading: const Icon(Icons.room_service),
              title: Text(l10n.homeOrderFood),
              subtitle: Text(l10n.homeOrderFoodHint),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/menu'),
            ),
          ),
          Card(
            child: ListTile(
              key: const Key('tile-my-orders'),
              leading: const Icon(Icons.receipt_long),
              title: Text(l10n.homeMyOrders),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/orders'),
            ),
          ),
          Card(
            child: ListTile(
              key: const Key('tile-housekeeping'),
              leading: const Icon(Icons.cleaning_services_outlined),
              title: Text(l10n.homeHousekeeping),
              subtitle: Text(l10n.homeHousekeepingHint),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/housekeeping'),
            ),
          ),
          if (stay.checkoutPending) ...[
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Text(l10n.homeCheckoutPending),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// "In progress": open food orders and housekeeping requests, each line
/// opening the one item directly or its list. Follows pushes, and refreshes
/// every 15 s while something is open.
class _OpenOrdersCard extends ConsumerWidget {
  const new();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final orders = <FoodOrder>[
      for (final order in ref.watch(myOrdersProvider).value ?? <FoodOrder>[])
        if (order.isOpen) order,
    ];
    final requests = <HkRequest>[
      for (final r in ref.watch(myHkRequestsProvider).value ?? <HkRequest>[])
        if (r.isOpen) r,
    ];
    if (orders.isEmpty && requests.isEmpty) return const SizedBox.shrink();
    return AutoRefresh(
      onRefresh: () => ref
        ..invalidate(myOrdersProvider)
        ..invalidate(myHkRequestsProvider),
      child: Card(
        color: Theme.of(context).colorScheme.primaryContainer,
        child: Column(
          children: [
            if (orders.isNotEmpty)
              ListTile(
                key: const Key('open-orders-card'),
                leading: Icon(orderStatusIcon(orders.first.status)),
                title: Text(l10n.homeOpenOrders(orders.length)),
                subtitle: Text(orderStatusLabel(l10n, orders.first.status)),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => context.push(
                  orders.length == 1
                      ? '/requests/food_order/${orders.first.id}'
                      : '/orders',
                ),
              ),
            if (requests.isNotEmpty)
              ListTile(
                key: const Key('open-hk-card'),
                leading: Icon(hkStatusIcon(requests.first.status)),
                title: Text(l10n.homeOpenHousekeeping(requests.length)),
                subtitle: Text(hkStatusLabel(l10n, requests.first.status)),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => context.push(
                  requests.length == 1
                      ? '/requests/housekeeping/${requests.first.id}'
                      : '/housekeeping/requests',
                ),
              ),
          ],
        ),
      ),
    );
  }
}
