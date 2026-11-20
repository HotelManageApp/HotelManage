import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/core/auto_refresh.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/room_service/order_status.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/features/room_service/room_service_repository.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:intl/intl.dart';
import 'package:material_ui/material_ui.dart';

/// One order: progress, dishes and the server's total, cancel while PENDING.
/// Also where a food-order notification leads.
class OrderDetailScreen extends ConsumerWidget {
  const new({required this.orderId, super.key});

  final String orderId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final order = ref.watch(orderProvider(orderId));

    return AutoRefresh(
      onRefresh: () => ref.invalidate(orderProvider(orderId)),
      child: Scaffold(
        appBar: AppBar(
          title: Text(
            order.value == null
                ? l10n.ordersTitle
                : l10n.orderTitle(
                    DateFormat.Hm(
                      Localizations.localeOf(context).toLanguageTag(),
                    ).format(order.value!.createdAt.toLocal()),
                  ),
          ),
        ),
        body: RefreshIndicator(
          onRefresh: () => ref.refresh(orderProvider(orderId).future),
          child: order.when(
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
            data: (data) => _Detail(order: data),
          ),
        ),
      ),
    );
  }
}

class _Detail extends ConsumerWidget {
  const new({required this.order});

  final FoodOrder order;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final cancelled = order.status == 'CANCELLED';

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            Icon(
              orderStatusIcon(order.status),
              color: cancelled ? theme.colorScheme.error : null,
            ),
            const SizedBox(width: 8),
            Text(
              orderStatusLabel(l10n, order.status),
              key: const Key('order-status'),
              style: theme.textTheme.titleLarge,
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (cancelled) ...[
          if (order.cancelReason != null)
            Text(l10n.orderCancelledReason(order.cancelReason!)),
        ] else
          _Progress(status: order.status),
        if (order.estimatedMinutes != null && order.isOpen) ...[
          const SizedBox(height: 8),
          Text(l10n.orderEta(order.estimatedMinutes!)),
        ],
        const Divider(height: 32),
        for (final line in order.items)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    [
                      '${line.quantity} × ${line.name}',
                      if (line.note != null && line.note!.isNotEmpty)
                        '↳ ${line.note}',
                    ].join('\n'),
                  ),
                ),
                Text(formatVnd(line.lineTotalVnd)),
              ],
            ),
          ),
        if (order.orderNote != null && order.orderNote!.isNotEmpty)
          Text(l10n.orderNote(order.orderNote!)),
        const SizedBox(height: 8),
        Text(
          l10n.orderTotal(formatVnd(order.totalVnd)),
          key: const Key('order-total'),
          style: theme.textTheme.titleMedium,
        ),
        if (order.guestCanCancel) ...[
          const SizedBox(height: 24),
          OutlinedButton.icon(
            key: const Key('cancel-order'),
            icon: const Icon(Icons.close),
            label: Text(l10n.orderCancel),
            style: OutlinedButton.styleFrom(
              foregroundColor: theme.colorScheme.error,
            ),
            onPressed: () => _cancel(context, ref),
          ),
        ],
      ],
    );
  }

  Future<void> _cancel(BuildContext context, WidgetRef ref) async {
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: Text(l10n.orderCancelQuestion),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(l10n.orderCancelNo),
          ),
          FilledButton(
            key: const Key('confirm-cancel'),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(l10n.orderCancelYes),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(roomServiceRepositoryProvider).cancel(order.id);
      messenger.showSnackBar(SnackBar(content: Text(l10n.orderCancelled)));
    } on AppException catch (error) {
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            error.status == 409
                ? l10n.orderCancelTooLate
                : l10n.orderCancelFailed,
          ),
        ),
      );
    } finally {
      ref
        ..invalidate(orderProvider(order.id))
        ..invalidate(myOrdersProvider);
    }
  }
}

/// PENDING → CONFIRMED → PREPARING → DELIVERING → COMPLETED.
class _Progress extends StatelessWidget {
  const new({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final reached = orderProgress.indexOf(status);
    final scheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        LinearProgressIndicator(
          key: const Key('order-progress'),
          value: (reached + 1) / orderProgress.length,
          minHeight: 6,
          borderRadius: BorderRadius.circular(3),
        ),
        const SizedBox(height: 8),
        for (final (index, step) in orderProgress.indexed)
          Row(
            children: [
              Icon(
                index <= reached
                    ? Icons.check_circle
                    : Icons.radio_button_unchecked,
                size: 18,
                color: index <= reached ? scheme.primary : scheme.outline,
              ),
              const SizedBox(width: 8),
              Text(
                orderStatusLabel(l10n, step),
                style: index == reached
                    ? const TextStyle(fontWeight: FontWeight.bold)
                    : null,
              ),
            ],
          ),
      ],
    );
  }
}
