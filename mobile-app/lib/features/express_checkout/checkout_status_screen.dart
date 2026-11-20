import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/core/auto_refresh.dart';
import 'package:hotel_guest/features/express_checkout/bill_view.dart';
import 'package:hotel_guest/features/express_checkout/checkout_models.dart';
import 'package:hotel_guest/features/express_checkout/checkout_repository.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// Where a checkout request goes after it is sent, and where a CHECKOUT push
/// leads: progress, the verified bill, or why reception rejected it. The
/// stay's latest request is shown (a stay has at most one open request).
/// Once reception completes it, the next call gets 401 and the app returns
/// to the welcome screen with a thank-you.
class CheckoutStatusScreen extends ConsumerWidget {
  const new({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final request = ref.watch(currentCheckoutProvider);
    return AutoRefresh(
      onRefresh: () => ref.invalidate(currentCheckoutProvider),
      child: Scaffold(
        appBar: AppBar(title: Text(l10n.checkoutStatusTitle)),
        body: RefreshIndicator(
          onRefresh: () => ref.refresh(currentCheckoutProvider.future),
          child: request.when(
            skipLoadingOnRefresh: true,
            skipLoadingOnReload: true,
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (error, _) => _message(l10n.checkoutLoadError),
            data: (data) => data == null
                ? _message(l10n.checkoutNone)
                : _Status(request: data),
          ),
        ),
      ),
    );
  }

  Widget _message(String text) => ListView(
    children: [
      Padding(
        padding: const EdgeInsets.all(32),
        child: Center(child: Text(text)),
      ),
    ],
  );
}

class _Status extends StatelessWidget {
  const new({required this.request});

  final CheckoutRequest request;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final bill = request.bill;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (request.isRejected) ...[
          Row(
            children: [
              Icon(Icons.error_outline, color: theme.colorScheme.error),
              const SizedBox(width: 8),
              Text(
                l10n.checkoutStatusRejected,
                key: const Key('checkout-status'),
                style: theme.textTheme.titleLarge,
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (request.rejectReason != null)
            Text(
              l10n.checkoutRejectedReason(request.rejectReason!),
              key: const Key('checkout-reject-reason'),
            ),
          const SizedBox(height: 8),
          Text(l10n.checkoutRejectedHint),
          const SizedBox(height: 24),
          FilledButton(
            key: const Key('checkout-back-home'),
            onPressed: () => context.go('/home'),
            child: Text(l10n.checkoutBackHome),
          ),
        ] else ...[
          Text(
            checkoutStatusLabel(l10n, request.status),
            key: const Key('checkout-status'),
            style: theme.textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          _Progress(status: request.status),
          const SizedBox(height: 12),
          Text(
            request.status == 'BILLING_VERIFIED'
                ? l10n.checkoutVerifiedHint
                : l10n.checkoutRequestedHint,
          ),
          if (bill != null) ...[
            const Divider(height: 32),
            BillView(bill: bill),
          ],
        ],
      ],
    );
  }
}

String checkoutStatusLabel(AppLocalizations l10n, String status) =>
    switch (status) {
      'CHECKOUT_REQUESTED' => l10n.checkoutStatusRequested,
      'BILLING_VERIFIED' => l10n.checkoutStatusVerified,
      'COMPLETED' => l10n.checkoutStatusCompleted,
      'REJECTED' => l10n.checkoutStatusRejected,
      _ => status,
    };

/// Sent → verified → completed.
class _Progress extends StatelessWidget {
  const new({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final reached = checkoutProgress.indexOf(status);
    final scheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        LinearProgressIndicator(
          key: const Key('checkout-progress'),
          value: (reached + 1) / checkoutProgress.length,
          minHeight: 6,
          borderRadius: BorderRadius.circular(3),
        ),
        const SizedBox(height: 8),
        for (final (index, step) in checkoutProgress.indexed)
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
                checkoutStepLabel(l10n, step),
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

String checkoutStepLabel(AppLocalizations l10n, String status) =>
    switch (status) {
      'CHECKOUT_REQUESTED' => l10n.checkoutStepSent,
      'BILLING_VERIFIED' => l10n.checkoutStepVerified,
      _ => l10n.checkoutStepCompleted,
    };
