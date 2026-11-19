"""Server-side check that facts in an answer come from the tool results (C2.1–C2.3).

Deliberately simple heuristics for the most common and most harmful inventions: clock times,
prices, distances and phone numbers. Every fact found in the reply must appear, after
normalisation, in the sources of this turn (tool results + the reception phone). Anything else
makes the answer ungrounded and the orchestrator replaces it.

    "06:30", "6h30", "6:30" -> time 06:30        "65.000đ", "65k", "65,000 VND" -> price 65000
    "1,2 km", "1.2km", "1200 m" -> 1200 m          "028 3822 1234" -> phone 02838221234
"""

import re
from dataclasses import dataclass

# Order matters: phones first (long digit runs), then prices, distances, times.
_PHONE = re.compile(r"(?<![\d.,:])\+?\d[\d .\-()]{7,}\d(?![\d.,:])")
_PRICE = re.compile(
    r"(?<![\d.,:])(\d{1,3}(?:[.,]\d{3})+|\d+)\s*"
    r"(k|nghìn|ngàn|nghin|ngan|đồng|dong|đ|₫|vnd|vnđ)(?![a-zà-ỹ])",
    re.IGNORECASE,
)
_DISTANCE = re.compile(r"(?<![\d.,:])(\d+(?:[.,]\d+)?)\s?(km|m)(?![a-zà-ỹ])", re.IGNORECASE)
_TIME = re.compile(
    r"(?<![\d.,:])([01]?\d|2[0-3])\s?(?::([0-5]\d)|h([0-5]\d)?|giờ(?:\s?([0-5]\d))?)(?![\d])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Fact:
    kind: str  # time | price | distance | phone
    value: str  # normalised

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"


def _number(text: str, *, thousands: bool) -> float:
    if thousands and re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", text):
        return float(re.sub(r"[.,]", "", text))
    return float(text.replace(",", "."))


def extract(text: str) -> set[Fact]:
    facts: set[Fact] = set()
    rest = text
    for match in _PHONE.finditer(rest):
        digits = re.sub(r"\D", "", match.group())
        if len(digits) >= 8:
            facts.add(Fact("phone", digits))
            rest = rest.replace(match.group(), " ")
    for match in _PRICE.finditer(rest):
        amount = _number(match.group(1), thousands=True)
        if match.group(2).lower() in {"k", "nghìn", "ngàn", "nghin", "ngan"}:
            amount *= 1000
        facts.add(Fact("price", str(int(amount))))
        rest = rest.replace(match.group(), " ")
    for match in _DISTANCE.finditer(rest):
        meters = _number(match.group(1), thousands=False) * (
            1000 if match.group(2).lower() == "km" else 1
        )
        facts.add(Fact("distance", str(round(meters))))
        rest = rest.replace(match.group(), " ")
    for match in _TIME.finditer(rest):
        minutes = match.group(2) or match.group(3) or match.group(4) or "00"
        facts.add(Fact("time", f"{int(match.group(1)):02d}:{minutes}"))
    return facts


def has_facts(text: str) -> bool:
    return bool(extract(text))


def _source_facts(sources: list[str]) -> set[Fact]:
    found: set[Fact] = set()
    for source in sources:
        found |= extract(source)
        # Bare numbers in structured data ("distance_km": 1.2, "price_vnd": 65000).
        for km in re.findall(r'"distance_km":\s*(\d+(?:\.\d+)?)', source):
            found.add(Fact("distance", str(round(float(km) * 1000))))
        for price in re.findall(r'"(?:price|amount|total)_vnd":\s*(\d+)', source):
            found.add(Fact("price", price))
    return found


def unsupported(reply: str, sources: list[str]) -> set[Fact]:
    """Facts in `reply` that none of `sources` contains."""
    claimed = extract(reply)
    if not claimed:
        return set()
    known = _source_facts(sources)
    digits_in_sources = {re.sub(r"\D", "", s) for s in sources}
    missing = set()
    for fact in claimed:
        if fact in known:
            continue
        if fact.kind == "phone" and any(fact.value in d for d in digits_in_sources):
            continue
        missing.add(fact)
    return missing
