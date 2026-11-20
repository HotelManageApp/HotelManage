import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/core/auto_refresh.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/housekeeping/hk_labels.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_models.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_repository.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:intl/intl.dart';
import 'package:material_ui/material_ui.dart';

String _when(BuildContext context, AppLocalizations l10n, HkRequest r) {
  final time = r.preferredTime;
  if (time == null) return l10n.hkWhenAsap;
  final locale = Localizations.localeOf(context).toLanguageTag();
  return l10n.hkWhenAt(DateFormat('E HH:mm', locale).format(time.toLocal()));
}

String _summary(AppLocalizations l10n, HkRequest r) => r.amenities.isEmpty
    ? hkTypeLabel(l10n, r.type)
    : r.amenities
          .map((a) => '${a.quantity}× ${amenityLabel(l10n, a.code)}')
          .join(', ');

/// The stay's housekeeping requests, newest first.
class HkRequestsScreen extends ConsumerWidget {
  const new({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final requests = ref.watch(myHkRequestsProvider);
    return AutoRefresh(
      onRefresh: () => ref.invalidate(myHkRequestsProvider),
      child: Scaffold(
        appBar: AppBar(title: Text(l10n.hkMyRequests)),
        body: RefreshIndicator(
          onRefresh: () => ref.refresh(myHkRequestsProvider.future),
          child: requests.when(
            skipLoadingOnRefresh: true,
            skipLoadingOnReload: true,
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (error, _) => ListView(
              children: [
                Padding(
                  padding: const EdgeInsets.all(32),
                  child: Center(child: Text(l10n.hkErrorFailed)),
                ),
              ],
            ),
            data: (list) => list.isEmpty
                ? ListView(
                    children: [
                      Padding(
                        padding: const EdgeInsets.all(32),
                        child: Center(child: Text(l10n.hkRequestsEmpty)),
                      ),
                    ],
                  )
                : ListView.separated(
                    itemCount: list.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final r = list[index];
                      return ListTile(
                        key: Key('hk-${r.id}'),
                        leading: Icon(hkStatusIcon(r.status)),
                        title: Text(hkStatusLabel(l10n, r.status)),
                        subtitle: Text(
                          '${_summary(l10n, r)} · ${_when(context, l10n, r)}',
                        ),
                        onTap: () =>
                            context.push('/requests/housekeeping/${r.id}'),
                      );
                    },
                  ),
          ),
        ),
      ),
    );
  }
}

/// One request: progress, who is on it, cancel while REQUESTED. Also where a
/// housekeeping notification leads.
class HkRequestDetailScreen extends ConsumerWidget {
  const new({required this.requestId, super.key});

  final String requestId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final request = ref.watch(hkRequestProvider(requestId));
    return AutoRefresh(
      onRefresh: () => ref.invalidate(hkRequestProvider(requestId)),
      child: Scaffold(
        appBar: AppBar(
          title: Text(
            request.value == null
                ? l10n.hkMyRequests
                : hkTypeLabel(l10n, request.value!.type),
          ),
        ),
        body: RefreshIndicator(
          onRefresh: () => ref.refresh(hkRequestProvider(requestId).future),
          child: request.when(
            skipLoadingOnRefresh: true,
            skipLoadingOnReload: true,
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (error, _) => ListView(
              children: [
                Padding(
                  padding: const EdgeInsets.all(32),
                  child: Center(child: Text(l10n.hkErrorFailed)),
                ),
              ],
            ),
            data: (data) => _Detail(request: data),
          ),
        ),
      ),
    );
  }
}

class _Detail extends ConsumerWidget {
  const new({required this.request});

  final HkRequest request;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final cancelled = request.status == 'CANCELLED';
    final reached = hkProgress.indexOf(request.status);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            Icon(
              hkStatusIcon(request.status),
              color: cancelled ? theme.colorScheme.error : null,
            ),
            const SizedBox(width: 8),
            Text(
              hkStatusLabel(l10n, request.status),
              key: const Key('hk-status'),
              style: theme.textTheme.titleLarge,
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (cancelled) ...[
          if (request.cancelReason != null)
            Text(l10n.orderCancelledReason(request.cancelReason!)),
        ] else
          LinearProgressIndicator(
            key: const Key('hk-progress'),
            value: (reached + 1) / hkProgress.length,
            minHeight: 6,
            borderRadius: BorderRadius.circular(3),
          ),
        if (request.assignee != null && !cancelled) ...[
          const SizedBox(height: 8),
          Text(l10n.hkAssignee(request.assignee!)),
        ],
        const Divider(height: 32),
        Text(_summary(l10n, request)),
        const SizedBox(height: 4),
        Text(_when(context, l10n, request)),
        if (request.note != null && request.note!.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(l10n.orderNote(request.note!)),
        ],
        if (request.guestCanCancel) ...[
          const SizedBox(height: 24),
          OutlinedButton.icon(
            key: const Key('cancel-hk'),
            icon: const Icon(Icons.close),
            label: Text(l10n.hkCancel),
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
        content: Text(l10n.hkCancelQuestion),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(l10n.orderCancelNo),
          ),
          FilledButton(
            key: const Key('confirm-cancel-hk'),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(l10n.hkCancel),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(housekeepingRepositoryProvider).cancel(request.id);
      messenger.showSnackBar(SnackBar(content: Text(l10n.hkCancelled)));
    } on AppException catch (error) {
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            error.status == 409 ? l10n.hkCancelTooLate : l10n.hkCancelFailed,
          ),
        ),
      );
    } finally {
      ref
        ..invalidate(hkRequestProvider(request.id))
        ..invalidate(myHkRequestsProvider);
    }
  }
}
