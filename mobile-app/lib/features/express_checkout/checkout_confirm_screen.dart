import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/features/express_checkout/bill_view.dart';
import 'package:hotel_guest/features/express_checkout/checkout_repository.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// Express checkout: the estimate, an optional rating and note, then one
/// explicit "confirm" that sends the request (`guest_confirmed: true`).
class CheckoutConfirmScreen extends ConsumerStatefulWidget {
  const new({super.key});

  @override
  ConsumerState<CheckoutConfirmScreen> createState() =>
      _CheckoutConfirmScreenState();
}

class _CheckoutConfirmScreenState extends ConsumerState<CheckoutConfirmScreen> {
  final _note = TextEditingController();
  int? _rating;
  bool _busy = false;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final preview = ref.watch(checkoutPreviewProvider);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.checkoutTitle)),
      body: RefreshIndicator(
        onRefresh: () => ref.refresh(checkoutPreviewProvider.future),
        child: preview.when(
          skipLoadingOnRefresh: true,
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => ListView(
            children: [
              Padding(
                padding: const EdgeInsets.all(32),
                child: Center(child: Text(l10n.checkoutLoadError)),
              ),
            ],
          ),
          data: (bill) => ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (bill.openOrders > 0)
                Card(
                  key: const Key('checkout-open-orders'),
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Text(l10n.checkoutOpenOrders(bill.openOrders)),
                  ),
                ),
              BillView(bill: bill),
              const SizedBox(height: 24),
              Text(l10n.checkoutRatingLabel),
              Row(
                children: [
                  for (var star = 1; star <= 5; star++)
                    IconButton(
                      key: Key('star-$star'),
                      tooltip: l10n.checkoutStars(star),
                      icon: Icon(
                        _rating != null && star <= _rating!
                            ? Icons.star
                            : Icons.star_border,
                        color: Colors.amber.shade700,
                      ),
                      // Tapping the chosen star again clears the rating.
                      onPressed: () => setState(
                        () => _rating = _rating == star ? null : star,
                      ),
                    ),
                ],
              ),
              TextField(
                key: const Key('checkout-note'),
                controller: _note,
                maxLength: 500,
                maxLines: 3,
                decoration: InputDecoration(
                  labelText: l10n.checkoutNoteLabel,
                  border: const OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 8),
              Text(l10n.checkoutConfirmHint),
              const SizedBox(height: 12),
              FilledButton.icon(
                key: const Key('checkout-submit'),
                icon: _busy
                    ? const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.logout),
                label: Text(l10n.checkoutSubmit),
                onPressed: _busy ? null : _submit,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _submit() async {
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final router = GoRouter.of(context);
    setState(() => _busy = true);
    try {
      final id = await ref
          .read(checkoutRepositoryProvider)
          .create(rating: _rating, note: _note.text);
      await _afterSent();
      unawaited(router.pushReplacement('/requests/checkout/$id'));
    } on AppException catch (error) {
      // Already sent (from another phone or the chatbot): show that one.
      if (error.status == 409 && await _openExisting(router)) return;
      if (error.isUnauthorized) return;
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.checkoutSubmitFailed)),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _openExisting(GoRouter router) async {
    await _afterSent();
    try {
      final request = await ref.read(checkoutRepositoryProvider).current();
      if (request == null) return false;
      unawaited(router.pushReplacement('/requests/checkout/${request.id}'));
      return true;
    } on AppException {
      return false;
    }
  }

  /// The stay is now CHECKOUT_PENDING: ordering and housekeeping lock.
  Future<void> _afterSent() async {
    ref.invalidate(currentCheckoutProvider);
    try {
      await ref.read(sessionProvider.notifier).refreshStay();
    } on AppException {
      // The status screen re-reads the stay on its own.
    }
  }
}
