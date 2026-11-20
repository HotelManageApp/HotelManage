import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:hotel_guest/core/errors.dart';
import 'package:hotel_guest/core/idempotency.dart';
import 'package:hotel_guest/features/housekeeping/hk_labels.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_models.dart';
import 'package:hotel_guest/features/housekeeping/housekeeping_repository.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/features/stay_access/stay_repository.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:intl/intl.dart';
import 'package:material_ui/material_ui.dart';

/// "Housekeeping & amenities": Do Not Disturb, room cleaning (now or at a
/// time), extra amenities, and a way to the guest's requests.
class HousekeepingScreen extends ConsumerStatefulWidget {
  const new({super.key});

  @override
  ConsumerState<HousekeepingScreen> createState() => _HousekeepingScreenState();
}

class _HousekeepingScreenState extends ConsumerState<HousekeepingScreen> {
  bool _atTime = false;
  DateTime? _slot;
  final _cleaningNote = TextEditingController();
  final _amenityNote = TextEditingController();
  final Map<String, int> _amenities = {for (final c in amenityCodes) c: 0};
  bool _busy = false;
  bool _dndBusy = false;

  /// Kept only to retry the same request after a network failure.
  String? _cleaningKey;
  String? _amenityKey;

  @override
  void dispose() {
    _cleaningNote.dispose();
    _amenityNote.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final session = ref.watch(sessionProvider).value;
    if (session is! SignedIn) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final stay = session.stay;
    final requests = ref.watch(myHkRequestsProvider).value ?? const [];
    HkRequest? openCleaning;
    for (final r in requests) {
      if (r.type == 'CLEANING' && r.isOpen) {
        openCleaning = r;
        break;
      }
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.hkTitle),
        actions: [
          TextButton(
            key: const Key('my-hk-requests'),
            onPressed: () => context.push('/housekeeping/requests'),
            child: Text(l10n.hkMyRequests),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SwitchListTile(
            key: const Key('dnd-switch'),
            contentPadding: EdgeInsets.zero,
            title: Text(l10n.hkDnd),
            subtitle: Text(l10n.hkDndHint),
            value: stay.doNotDisturb,
            onChanged: _dndBusy || stay.checkoutPending ? null : _setDnd,
          ),
          if (stay.checkoutPending)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(l10n.hkCheckoutPending),
            ),
          const Divider(height: 32),
          Text(l10n.hkCleaning, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          if (openCleaning != null) ...[
            Text(l10n.hkCleaningOpen),
            const SizedBox(height: 8),
            OutlinedButton(
              key: const Key('view-open-cleaning'),
              onPressed: () =>
                  context.push('/requests/housekeeping/${openCleaning!.id}'),
              child: Text(l10n.hkViewRequest),
            ),
          ] else
            _cleaningForm(l10n, stay),
          const Divider(height: 32),
          Text(
            l10n.hkAmenities,
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          _amenityForm(l10n, stay.checkoutPending),
        ],
      ),
    );
  }

  Widget _cleaningForm(AppLocalizations l10n, GuestStay stay) {
    final slots = cleaningSlots(DateTime.now(), stay.expectedCheckoutAt);
    final locale = Localizations.localeOf(context).toLanguageTag();
    final format = DateFormat('E HH:mm', locale);
    final slot = _slot != null && slots.contains(_slot) ? _slot : null;
    final ready = !_busy && !stay.checkoutPending && (!_atTime || slot != null);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SegmentedButton<bool>(
          segments: [
            ButtonSegment(value: false, label: Text(l10n.hkNow)),
            ButtonSegment(value: true, label: Text(l10n.hkAtTime)),
          ],
          selected: {_atTime},
          onSelectionChanged: (value) => setState(() {
            _atTime = value.first;
            _cleaningKey = null;
          }),
        ),
        if (_atTime) ...[
          const SizedBox(height: 8),
          if (slots.isEmpty)
            Text(l10n.hkNoSlots)
          else
            DropdownButtonFormField<DateTime>(
              key: const Key('cleaning-slot'),
              initialValue: slot,
              decoration: InputDecoration(labelText: l10n.hkTime),
              items: [
                for (final s in slots)
                  DropdownMenuItem(value: s, child: Text(format.format(s))),
              ],
              onChanged: (value) => setState(() {
                _slot = value;
                _cleaningKey = null;
              }),
            ),
        ],
        const SizedBox(height: 8),
        TextField(
          key: const Key('cleaning-note'),
          controller: _cleaningNote,
          maxLength: 300,
          decoration: InputDecoration(labelText: l10n.hkNote),
          onChanged: (_) => _cleaningKey = null,
        ),
        if (stay.doNotDisturb)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(l10n.hkCleaningClearsDnd),
          ),
        FilledButton(
          key: const Key('send-cleaning'),
          onPressed: ready ? () => _sendCleaning(slot) : null,
          child: Text(l10n.hkSendCleaning),
        ),
      ],
    );
  }

  Widget _amenityForm(AppLocalizations l10n, bool checkoutPending) {
    final chosen = [
      for (final code in amenityCodes)
        if (_amenities[code]! > 0)
          AmenityLine(code: code, quantity: _amenities[code]!),
    ];
    final needsNote =
        _amenities['OTHER']! > 0 && _amenityNote.text.trim().isEmpty;
    final ready = !_busy && !checkoutPending && chosen.isNotEmpty && !needsNote;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final code in amenityCodes)
          ListTile(
            key: Key('amenity-$code'),
            contentPadding: EdgeInsets.zero,
            leading: Icon(amenityIcon(code)),
            title: Text(amenityLabel(l10n, code)),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  tooltip: '- ${amenityLabel(l10n, code)}',
                  icon: const Icon(Icons.remove_circle_outline),
                  onPressed: _amenities[code]! == 0
                      ? null
                      : () => _changeAmenity(code, -1),
                ),
                Text('${_amenities[code]}', key: Key('amenity-qty-$code')),
                IconButton(
                  tooltip: '+ ${amenityLabel(l10n, code)}',
                  icon: const Icon(Icons.add_circle_outline),
                  onPressed: _amenities[code]! >= maxAmenityQuantity
                      ? null
                      : () => _changeAmenity(code, 1),
                ),
              ],
            ),
          ),
        TextField(
          key: const Key('amenity-note'),
          controller: _amenityNote,
          maxLength: 300,
          decoration: InputDecoration(
            labelText: l10n.hkNote,
            errorText: needsNote ? l10n.hkOtherNeedsNote : null,
          ),
          onChanged: (_) => setState(() => _amenityKey = null),
        ),
        FilledButton(
          key: const Key('send-amenities'),
          onPressed: ready ? () => _sendAmenities(chosen) : null,
          child: Text(l10n.hkSendAmenities),
        ),
      ],
    );
  }

  void _changeAmenity(String code, int delta) => setState(() {
    _amenities[code] = (_amenities[code]! + delta).clamp(0, maxAmenityQuantity);
    _amenityKey = null;
  });

  Future<void> _setDnd(bool enabled) async {
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _dndBusy = true);
    try {
      await ref
          .read(housekeepingRepositoryProvider)
          .setDoNotDisturb(enabled: enabled);
      await ref.read(sessionProvider.notifier).refreshStay();
    } on AppException {
      messenger.showSnackBar(SnackBar(content: Text(l10n.hkDndFailed)));
    } finally {
      if (mounted) setState(() => _dndBusy = false);
    }
  }

  Future<void> _sendCleaning(DateTime? slot) async {
    final key = _cleaningKey ??= newIdempotencyKey();
    final created = await _send(
      () => ref
          .read(housekeepingRepositoryProvider)
          .create(
            type: 'CLEANING',
            idempotencyKey: key,
            preferredTime: _atTime ? slot : null,
            note: _cleaningNote.text.trim(),
          ),
      onSettled: (networkError) {
        if (!networkError) _cleaningKey = null;
      },
    );
    if (created == null) return;
    _cleaningNote.clear();
    // The server turns Do Not Disturb off when the guest asks for cleaning.
    try {
      await ref.read(sessionProvider.notifier).refreshStay();
    } on AppException {
      // The switch catches up on the next refresh.
    }
    _open(created);
  }

  Future<void> _sendAmenities(List<AmenityLine> chosen) async {
    final key = _amenityKey ??= newIdempotencyKey();
    final created = await _send(
      () => ref
          .read(housekeepingRepositoryProvider)
          .create(
            type: 'AMENITY',
            idempotencyKey: key,
            amenities: chosen,
            note: _amenityNote.text.trim(),
          ),
      onSettled: (networkError) {
        if (!networkError) _amenityKey = null;
      },
    );
    if (created == null) return;
    setState(() {
      for (final code in amenityCodes) {
        _amenities[code] = 0;
      }
      _amenityNote.clear();
    });
    _open(created);
  }

  /// Sends, explains failures, and returns the request the server created.
  Future<HkRequest?> _send(
    Future<HkRequest> Function() call, {
    required void Function(bool networkError) onSettled,
  }) async {
    final l10n = AppLocalizations.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    try {
      final created = await call();
      onSettled(false);
      ref.invalidate(myHkRequestsProvider);
      messenger.showSnackBar(SnackBar(content: Text(l10n.hkSent)));
      return created;
    } on AppException catch (error) {
      onSettled(error.isNetworkError);
      messenger.showSnackBar(SnackBar(content: Text(_message(l10n, error))));
      if (error.code == 'CONFLICT') ref.invalidate(myHkRequestsProvider);
      return null;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _open(HkRequest request) {
    if (mounted) {
      unawaited(context.push('/requests/housekeeping/${request.id}'));
    }
  }

  static String _message(AppLocalizations l10n, AppException error) {
    if (error.isNetworkError) return l10n.hkErrorNetwork;
    return switch (error.code) {
      'CONFLICT' => l10n.hkErrorOpenCleaning,
      'TOO_MANY_OPEN_REQUESTS' => l10n.hkErrorTooMany,
      'VALIDATION_ERROR' || 'BAD_REQUEST' => l10n.hkErrorInvalid,
      'STAY_CHECKOUT_PENDING' => l10n.hkCheckoutPending,
      _ => l10n.hkErrorFailed,
    };
  }
}
