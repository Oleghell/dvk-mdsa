"""Exact matching of OBSERVED city labels. No OCR, device I/O or taps.

A future UI adapter must bind all labels to one fresh, fully inspected visible
result set. These decisions alone do not authorize a physical action. Unknown,
loading, clipped labels and duplicate exact matches never select a row.
"""
from dataclasses import dataclass
import unicodedata
from limited_scenario import CITIES


def _label(value):
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize('NFC', value)
    return ' '.join(value.split()).casefold()


def _complete(value):
    return bool(_label(value)) and '…' not in value and '...' not in value


@dataclass(frozen=True)
class CityRow:
    name: str
    subtitle: str
    # A reader can mark a clipped row even if no ellipsis character is exposed.
    labels_complete: bool = True


@dataclass(frozen=True)
class CityDecision:
    index: int | None
    reason: str

    @property
    def selectable(self):
        return self.index is not None


def resolve_city(city, region, rows, *, query, results_ready, labels_complete):
    """Require one exact city + region + Russia match in the visible snapshot.

    Region must be explicitly supplied/verified. Do not guess the region from a
    city name (e.g. Благовещенск). Never collapse two visually identical rows or
    infer a stable location ID from screen text. Return an index only if unique.
    """
    if results_ready is not True or labels_complete is not True:
        return CityDecision(None, 'results_not_ready_or_incomplete')
    if not _complete(city) or not _complete(region) or not _complete(query):
        return CityDecision(None, 'missing_or_clipped_target')
    requested = _label(city)
    if requested not in {_label(c) for c in CITIES}:
        return CityDecision(None, 'city_not_allowlisted')
    if _label(query) != requested:
        return CityDecision(None, 'query_mismatch')
    # Limit refers to a complete extraction of visible rows, not the entire
    # remote search database. Unsupported observations must not authorize taps.
    if not isinstance(rows, (tuple, list)) or len(rows) > 200:
        return CityDecision(None, 'unsupported_rows')
    matches = []
    for index, row in enumerate(rows):
        if not isinstance(row, CityRow):
            return CityDecision(None, 'unsupported_rows')
        if row.labels_complete is not True or not _complete(row.name) or not _complete(row.subtitle):
            # A hidden/clipped label could be another exact match. Fail the
            # whole observation rather than treating it as a harmless nonmatch.
            return CityDecision(None, 'clipped_or_missing_row')
        if _label(row.name) != requested:
            continue
        parts = row.subtitle.split('·')
        if (len(parts) == 2 and _label(parts[0]) == _label(region)
                and _label(parts[1]) == 'россия'):
            matches.append(index)
    if len(matches) > 1:
        return CityDecision(None, 'ambiguous_exact_matches')
    if not matches:
        return CityDecision(None, 'no_exact_match')
    return CityDecision(matches[0], 'unique_exact_match')
