import 'package:material_ui/material_ui.dart';

/// Hosts whose links the app opens (SPEC-concierge-guide: map links only).
const allowedLinkHosts = {'maps.google.com', 'maps.app.goo.gl'};

/// Only https links to an allowed host are opened; any other link is plain
/// text, so an answer can never send the guest to an arbitrary site.
bool isAllowedLink(String raw) {
  final uri = Uri.tryParse(raw);
  return uri != null &&
      uri.scheme == 'https' &&
      allowedLinkHosts.contains(uri.host) &&
      uri.userInfo.isEmpty;
}

/// One piece of a line: plain text, bold text or a link.
@immutable
class TextPiece {
  const new(this.text, {this.bold = false, this.link});

  final String text;
  final bool bold;
  final String? link; // set only for allowed links

  @override
  bool operator ==(Object other) =>
      other is TextPiece &&
      other.text == text &&
      other.bold == bold &&
      other.link == link;

  @override
  int get hashCode => Object.hash(text, bold, link);

  @override
  String toString() => 'TextPiece($text, bold: $bold, link: $link)';
}

class TextLine {
  const new(this.pieces, {this.bullet = false});

  final List<TextPiece> pieces;
  final bool bullet;
}

final _bulletPattern = RegExp(r'^\s*(?:[-*•]|\d+[.)])\s+');
final _inline = RegExp(
  r'\*\*(.+?)\*\*|\[([^\]]+)\]\((\S+?)\)|(https?://[^\s)]+)',
);

/// The small markdown subset the concierge uses: bullet lists, **bold** and
/// links. Everything else (headings, images, HTML) is shown as written.
List<TextLine> parseChatText(String text) {
  final lines = <TextLine>[];
  for (final raw in text.split('\n')) {
    final bullet = _bulletPattern.hasMatch(raw);
    final body = bullet ? raw.replaceFirst(_bulletPattern, '') : raw;
    final pieces = <TextPiece>[];
    var at = 0;
    for (final m in _inline.allMatches(body)) {
      if (m.start > at) pieces.add(TextPiece(body.substring(at, m.start)));
      if (m.group(1) != null) {
        pieces.add(TextPiece(m.group(1)!, bold: true));
      } else if (m.group(2) != null) {
        final url = m.group(3)!;
        pieces.add(
          isAllowedLink(url)
              ? TextPiece(m.group(2)!, link: url)
              : TextPiece('${m.group(2)} ($url)'),
        );
      } else {
        final url = m.group(4)!;
        pieces.add(
          isAllowedLink(url) ? TextPiece(url, link: url) : TextPiece(url),
        );
      }
      at = m.end;
    }
    if (at < body.length) pieces.add(TextPiece(body.substring(at)));
    lines.add(TextLine(pieces, bullet: bullet));
  }
  return lines;
}

/// Renders [parseChatText]; allowed links call [onLink].
class ChatText extends StatelessWidget {
  const new(this.text, {required this.onLink, this.style, super.key});

  final String text;
  final void Function(String url) onLink;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    final base = style ?? DefaultTextStyle.of(context).style;
    final linkColor = Theme.of(context).colorScheme.primary;
    Widget line(TextLine l) {
      final spans = [
        for (final p in l.pieces)
          if (p.link != null)
            WidgetSpan(
              alignment: PlaceholderAlignment.baseline,
              baseline: TextBaseline.alphabetic,
              child: InkWell(
                onTap: () => onLink(p.link!),
                child: Text(
                  p.text,
                  style: base.copyWith(
                    color: linkColor,
                    decoration: TextDecoration.underline,
                  ),
                ),
              ),
            )
          else
            TextSpan(
              text: p.text,
              style: p.bold
                  ? const TextStyle(fontWeight: FontWeight.bold)
                  : null,
            ),
      ];
      final rich = Text.rich(TextSpan(style: base, children: spans));
      return l.bullet
          ? Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('•  ', style: base),
                Expanded(child: rich),
              ],
            )
          : rich;
    }

    final lines = parseChatText(text);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [for (final l in lines) line(l)],
    );
  }
}
