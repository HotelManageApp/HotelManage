import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hotel_guest/features/concierge/chat_controller.dart';
import 'package:hotel_guest/features/concierge/chat_text.dart';
import 'package:hotel_guest/features/concierge/confirmation_card.dart';
import 'package:hotel_guest/features/concierge/suggested_action_button.dart';
import 'package:hotel_guest/features/stay_access/session_controller.dart';
import 'package:hotel_guest/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

/// The concierge chat: bubbles, quick questions on first open, suggestion
/// buttons, "answering…" indicator, retry of messages that did not leave.
class ChatScreen extends ConsumerStatefulWidget {
  const new({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    unawaited(Future.microtask(() => ref.read(chatProvider.notifier).load()));
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _send([String? text]) {
    final message = (text ?? _input.text).trim();
    if (message.isEmpty) return;
    _input.clear();
    unawaited(ref.read(chatProvider.notifier).send(message));
  }

  void _toBottom() {
    if (!_scroll.hasClients) return;
    _scroll.animateTo(
      _scroll.position.maxScrollExtent,
      duration: const Duration(milliseconds: 200),
      curve: Curves.easeOut,
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final chat = ref.watch(chatProvider);
    final session = ref.watch(sessionProvider).value;
    final lookupOnly = session is SignedIn && session.stay.checkoutPending;
    ref.listen(chatProvider.select((c) => c.entries.length), (_, _) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _toBottom());
    });

    final Widget body;
    if (chat.loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (chat.loadFailed) {
      body = Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(l10n.chatLoadError),
            TextButton(
              onPressed: () => ref.read(chatProvider.notifier).load(),
              child: Text(l10n.retry),
            ),
          ],
        ),
      );
    } else {
      body = ListView(
        controller: _scroll,
        padding: const EdgeInsets.all(12),
        children: [
          _Bubble(fromGuest: false, child: Text(l10n.chatIntro)),
          if (chat.isEmpty && chat.chatEnabled)
            Wrap(
              spacing: 8,
              children: [
                for (final q in [
                  l10n.chatQuick1,
                  l10n.chatQuick2,
                  l10n.chatQuick3,
                ])
                  ActionChip(label: Text(q), onPressed: () => _send(q)),
              ],
            ),
          for (final entry in chat.entries)
            _EntryView(
              entry: entry,
              receptionPhone: chat.receptionPhone,
              onEdit: _focus.requestFocus,
            ),
          if (chat.waiting)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(
                l10n.chatTyping,
                key: const Key('chat-typing'),
                style: const TextStyle(fontStyle: FontStyle.italic),
              ),
            ),
        ],
      );
    }

    return Scaffold(
      appBar: AppBar(title: Text(l10n.chatTitle)),
      body: Column(
        children: [
          Expanded(child: body),
          if (!chat.chatEnabled && !chat.loading)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Column(
                children: [
                  Text(l10n.chatDisabled, textAlign: TextAlign.center),
                  SuggestedActionButton(
                    target: 'CALL_RECEPTION',
                    receptionPhone: chat.receptionPhone,
                  ),
                ],
              ),
            )
          else
            SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 4, 4, 8),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (lookupOnly)
                      Text(
                        l10n.chatLookupOnly,
                        key: const Key('chat-lookup-only'),
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            key: const Key('chat-input'),
                            controller: _input,
                            focusNode: _focus,
                            maxLength: 1000,
                            minLines: 1,
                            maxLines: 4,
                            textInputAction: TextInputAction.send,
                            onSubmitted: (_) => _send(),
                            decoration: InputDecoration(
                              hintText: l10n.chatHint,
                              counterText: '',
                            ),
                          ),
                        ),
                        IconButton(
                          key: const Key('chat-send'),
                          tooltip: l10n.chatSend,
                          icon: const Icon(Icons.send),
                          onPressed: chat.waiting || chat.loading
                              ? null
                              : _send,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _EntryView extends ConsumerWidget {
  const new({
    required this.entry,
    required this.receptionPhone,
    required this.onEdit,
  });

  final ChatEntry entry;
  final String receptionPhone;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final launch = ref.read(linkLauncherProvider);
    final actions = [
      for (final a in entry.entityActions) EntityActionButton(action: a),
      for (final t in entry.targets)
        SuggestedActionButton(target: t, receptionPhone: receptionPhone),
    ];

    switch (entry.role) {
      case ChatRole.guest:
        final failed = entry.delivery == Delivery.failed;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            _Bubble(
              key: Key('bubble-${entry.key}'),
              fromGuest: true,
              faded: entry.delivery == Delivery.sending,
              child: Text(entry.text),
            ),
            if (failed)
              TextButton.icon(
                key: Key('retry-${entry.key}'),
                icon: const Icon(Icons.refresh, size: 16),
                label: Text(l10n.chatFailed),
                onPressed: () =>
                    ref.read(chatProvider.notifier).retry(entry.key),
              ),
          ],
        );
      case ChatRole.assistant:
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _Bubble(
              key: Key('bubble-${entry.key}'),
              fromGuest: false,
              child: ChatText(
                entry.text,
                onLink: (url) => launch(Uri.parse(url)),
              ),
            ),
            if (entry.pending != null)
              ConfirmationCard(entry: entry, onEdit: onEdit),
            if (actions.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Wrap(spacing: 8, runSpacing: 4, children: actions),
              ),
          ],
        );
      case ChatRole.notice:
        final text = switch (entry.notice) {
          NoticeKind.slowDown =>
            entry.retryAfterSeconds == null
                ? l10n.chatSlowDownNoTime
                : l10n.chatSlowDown(entry.retryAfterSeconds!),
          NoticeKind.disabled => l10n.chatDisabled,
          _ => l10n.chatBusy,
        };
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Column(
            children: [
              Text(
                text,
                key: Key('notice-${entry.key}'),
                textAlign: TextAlign.center,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              ...actions,
            ],
          ),
        );
    }
  }
}

class _Bubble extends StatelessWidget {
  const new({
    required this.fromGuest,
    required this.child,
    this.faded = false,
    super.key,
  });

  final bool fromGuest;
  final bool faded;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Align(
      alignment: fromGuest ? Alignment.centerRight : Alignment.centerLeft,
      child: Opacity(
        opacity: faded ? 0.6 : 1,
        child: Container(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.sizeOf(context).width * 0.8,
          ),
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: fromGuest
                ? scheme.primaryContainer
                : scheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(12),
          ),
          child: child,
        ),
      ),
    );
  }
}
