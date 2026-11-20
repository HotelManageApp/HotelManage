import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/features/room_service/cart_controller.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// Room-service menu: category tabs, search, sold-out dishes greyed out, and
/// a banner while the kitchen is closed or the stay is checking out.
class MenuScreen extends ConsumerStatefulWidget {
  const new({super.key});

  @override
  ConsumerState<MenuScreen> createState() => _MenuScreenState();
}

class _MenuScreenState extends ConsumerState<MenuScreen> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final menu = ref.watch(menuProvider);
    final count = ref.watch(cartProvider.select((c) => c.itemCount));

    return Scaffold(
      appBar: AppBar(title: Text(l10n.menuTitle)),
      floatingActionButton: count == 0
          ? null
          : FloatingActionButton.extended(
              key: const Key('open-cart'),
              onPressed: () => context.push('/cart'),
              icon: const Icon(Icons.shopping_basket),
              label: Text(l10n.cartButton(count)),
            ),
      body: menu.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(l10n.menuLoadError),
              const SizedBox(height: 8),
              FilledButton(
                onPressed: () => ref.invalidate(menuProvider),
                child: Text(l10n.retry),
              ),
            ],
          ),
        ),
        data: (data) => _MenuBody(
          menu: data,
          query: _query,
          onQuery: (value) => setState(() => _query = value),
        ),
      ),
    );
  }
}

class _MenuBody extends ConsumerWidget {
  const new({required this.menu, required this.query, required this.onQuery});

  final GuestMenu menu;
  final String query;
  final ValueChanged<String> onQuery;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final session = ref.watch(sessionProvider).value;
    final checkoutPending = session is SignedIn && session.stay.checkoutPending;
    final canOrder = menu.isOpenNow && !checkoutPending;
    final tabs = [null, ...menu.categories];

    return DefaultTabController(
      length: tabs.length,
      child: Column(
        children: [
          if (checkoutPending)
            _Banner(l10n.menuCheckoutPending)
          else if (!menu.isOpenNow)
            _Banner(l10n.menuClosed(menu.serviceHours)),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: TextField(
              key: const Key('menu-search'),
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: l10n.menuSearch,
              ),
              onChanged: onQuery,
            ),
          ),
          TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: [for (final c in tabs) Tab(text: c?.name ?? l10n.menuAll)],
          ),
          Expanded(
            child: TabBarView(
              children: [
                for (final c in tabs)
                  RefreshIndicator(
                    onRefresh: () => ref.refresh(menuProvider.future),
                    child: _DishList(
                      items: _filter(menu.items, c?.code, query),
                      canOrder: canOrder,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static List<MenuItem> _filter(
    List<MenuItem> items,
    String? category,
    String query,
  ) {
    final q = query.trim().toLowerCase();
    return [
      for (final item in items)
        if ((category == null || item.category == category) &&
            (q.isEmpty || item.name.toLowerCase().contains(q)))
          item,
    ];
  }
}

class _Banner extends StatelessWidget {
  const new(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    color: Theme.of(context).colorScheme.errorContainer,
    padding: const EdgeInsets.all(12),
    child: Text(
      text,
      style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer),
    ),
  );
}

class _DishList extends ConsumerWidget {
  const new({required this.items, required this.canOrder});

  final List<MenuItem> items;
  final bool canOrder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    if (items.isEmpty) {
      return ListView(
        children: [
          Padding(
            padding: const EdgeInsets.all(32),
            child: Center(child: Text(l10n.menuEmpty)),
          ),
        ],
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.only(bottom: 96),
      itemCount: items.length,
      separatorBuilder: (_, _) => const Divider(height: 1),
      itemBuilder: (context, index) =>
          _DishTile(item: items[index], canOrder: canOrder),
    );
  }
}

class _DishTile extends ConsumerWidget {
  const new({required this.item, required this.canOrder});

  final MenuItem item;
  final bool canOrder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final quantity = ref.watch(
      cartProvider.select((c) => c.quantityOf(item.id)),
    );
    final cart = ref.read(cartProvider.notifier);

    Widget? trailing;
    if (!item.available) {
      trailing = Text(
        l10n.menuSoldOut,
        style: TextStyle(color: Theme.of(context).colorScheme.error),
      );
    } else if (canOrder) {
      trailing = quantity == 0
          ? IconButton.filledTonal(
              tooltip: l10n.menuAdd(item.name),
              icon: const Icon(Icons.add),
              onPressed: () => _add(context, cart),
            )
          : Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  tooltip: l10n.menuRemoveOne(item.name),
                  icon: const Icon(Icons.remove_circle_outline),
                  onPressed: () => cart.decrement(item.id),
                ),
                Text('$quantity', key: Key('qty-${item.id}')),
                IconButton(
                  tooltip: l10n.menuAdd(item.name),
                  icon: const Icon(Icons.add_circle_outline),
                  onPressed: () => _add(context, cart),
                ),
              ],
            );
    }

    return Opacity(
      opacity: item.available ? 1 : 0.5,
      child: ListTile(
        key: Key('dish-${item.id}'),
        title: Text(item.name),
        subtitle: Text(
          [
            formatVnd(item.priceVnd),
            if (item.description != null && item.description!.isNotEmpty)
              item.description!,
          ].join(' · '),
        ),
        trailing: trailing,
      ),
    );
  }

  void _add(BuildContext context, CartController cart) {
    if (!cart.add(item)) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(AppLocalizations.of(context).cartFull)),
      );
    }
  }
}
