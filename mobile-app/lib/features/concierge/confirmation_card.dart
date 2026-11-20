import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/features/concierge/chat_controller.dart';
import 'package:hotel_guest/features/concierge/chat_repository.dart';
import 'package:hotel_guest/features/room_service/room_service_models.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// The card under a concierge answer that shows a summary (an order, or an
/// express checkout) and waits for the guest's yes. The summary itself is in
/// the answer text, written by the server. "Xác nhận" sends the card's action
/// id with the message; "Sửa lại" locks the card so the guest types the
/// change. After 10 minutes, or once anything else was said, it locks too.
class ConfirmationCard extends ConsumerStatefulWidget {
  const new({required this.entry, required this.onEdit, super.key});

  final ChatEntry entry;
  final VoidCallback onEdit;

  @override
  ConsumerState<ConfirmationCard> createState() => _ConfirmationCardState();
}

class _ConfirmationCardState extends ConsumerState<ConfirmationCard> {
  Timer? _expiry;

  @override
  void initState() {
    super.initState();
    final at = widget.entry.receivedAt;
    if (at == null) return;
    final left = at
        .add(confirmationLifetime)
        .difference(ref.read(chatClockProvider)());
    if (left > Duration.zero) {
      // Rebuild when it expires so the buttons lock while the screen is open.
      _expiry = Timer(left, () {
        if (mounted) setState(() {});
      });
    }
  }

  @override
  void dispose() {
    _expiry?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final pending = widget.entry.pending!;
    final chat = ref.watch(chatProvider);
    final active = chat.canConfirm(widget.entry, ref.read(chatClockProvider)());
    final expired =
        !active &&
        !chat.dismissed.contains(widget.entry.key) &&
        chat.entries.last.key == widget.entry.key;
    final checkout = pending.kind == 'CHECKOUT';

    return Opacity(
      opacity: active ? 1 : 0.5,
      child: Card(
        key: Key('confirm-card-${widget.entry.key}'),
        margin: const EdgeInsets.only(bottom: 8),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                checkout
                    ? l10n.chatConfirmCheckoutTitle
                    : l10n.chatConfirmOrderTitle,
                style: Theme.of(context).textTheme.titleSmall,
              ),
              if (pending.totalVnd != null)
                Text(
                  l10n.chatConfirmTotal(formatVnd(pending.totalVnd!)),
                  key: const Key('confirm-total'),
                ),
              if (expired)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    l10n.chatConfirmExpired,
                    key: const Key('confirm-expired'),
                  ),
                ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: [
                  FilledButton(
                    key: const Key('confirm-yes'),
                    onPressed: active && !chat.waiting
                        ? () => ref
                              .read(chatProvider.notifier)
                              .confirm(widget.entry, l10n.chatConfirmMessage)
                        : null,
                    child: Text(l10n.chatConfirm),
                  ),
                  OutlinedButton(
                    key: const Key('confirm-edit'),
                    onPressed: active && !chat.waiting
                        ? () {
                            ref
                                .read(chatProvider.notifier)
                                .dismiss(widget.entry.key);
                            widget.onEdit();
                          }
                        : null,
                    child: Text(l10n.chatEdit),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Where each "open what was created" button leads.
const entityRoutes = {
  'OPEN_ORDER': '/requests/food_order/',
  'OPEN_HOUSEKEEPING': '/requests/housekeeping/',
  'OPEN_CHECKOUT': '/requests/checkout/',
};

/// "Xem đơn" / "Xem yêu cầu" under an answer that created something.
class EntityActionButton extends StatelessWidget {
  const new({required this.action, super.key});

  final EntityAction action;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final base = entityRoutes[action.target];
    if (base == null) return const SizedBox.shrink();
    return FilledButton.tonalIcon(
      key: Key('open-${action.target}'),
      icon: const Icon(Icons.open_in_new, size: 18),
      label: Text(
        action.target == 'OPEN_ORDER'
            ? l10n.actionOpenOrder
            : l10n.actionOpenRequest,
      ),
      onPressed: () => context.push('$base${action.entityId}'),
    );
  }
}
