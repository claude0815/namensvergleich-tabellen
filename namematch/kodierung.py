"""Zeichenkodierung: Plausibilität, verdächtige Zeichen und Reparatur von Zeichensalat.

Hintergrund: CSV-Dateien kommen in verschiedenen Kodierungen vor – UTF-8, Windows-1252
(Excel unter Windows), Mac Roman (Excel für Mac, Format „CSV“) oder CP850 (alte DOS-Programme).
Wird eine Datei mit der falschen Kodierung gelesen, werden aus Umlauten andere Zeichen
(„Ã¼“, „Ÿ“ …). Namen mit mehreren Umlauten werden dann nicht mehr gefunden.
"""

from __future__ import annotations

import codecs
import re

#: Deutsche Umlaute – starkes Zeichen für die richtige Kodierung
_DEUTSCH = frozenset("äöüÄÖÜß")
#: andere übliche Buchstaben mit Akzent
_AKZENTE = frozenset("éèêëáàâãåíìîïóòôõúùûçñýÉÈÊËÁÀÂÃÅÍÌÎÏÓÒÔÕÚÙÛÇÑÝæøÆØœŒšžŠŽ")
#: Zeichen, die in Namenslisten praktisch nie vorkommen, aber bei falscher Kodierung entstehen
_VERDAECHTIG = frozenset(
    "Ÿ†‡‰ˆ¸¨¯˜¤¦¶¬±÷¿¡ªº°¹²³¼½¾µ∂∑∏π∫Ω√≈≠≤≥◊ﬁﬂ�"
    "═║╔╗╚╝╠╣╦╩╬─│┌┐└┘├┤┬┴┼░▒▓█▄▀■"
) | frozenset(chr(c) for c in range(0x80, 0xA0))  # C1-Steuerzeichen

#: UTF-8-Zeichensalat: „Ã¼“ statt „ü“ (UTF-8-Bytes als Windows-1252 gelesen)
_ZEICHENSALAT = re.compile("[ÂÃÅ][\u0080-¿ŒœŠšŸŽžƒ"
                           "ˆ˜–—‘’‚“”„†‡•"
                           "…‰‹›€™]")

#: gültige UTF-8-Mehrbytefolgen (zur Erkennung „überwiegend UTF-8“)
_UTF8_FOLGE = re.compile(rb"[\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3}")
_HOHES_BYTE = re.compile(rb"[\x80-\xff]")

#: Kandidaten für Dateien ohne gültiges UTF-8 (Reihenfolge = Vorrang bei Gleichstand)
EINBYTE_KODIERUNGEN = ("cp1252", "mac_roman", "cp850")


def plausibilitaet(text: str) -> int:
    """Wertung, wie „deutsch-plausibel“ ein Text ist (Umlaute +3, Akzente +1, Verdächtiges −5)."""
    wertung = 0
    for zeichen in text:
        if zeichen < "\x80":
            continue
        if zeichen in _DEUTSCH:
            wertung += 3
        elif zeichen in _VERDAECHTIG:
            wertung -= 5
        elif zeichen in _AKZENTE:
            wertung += 1
    return wertung


def verdaechtig(text: str) -> bool:
    """True, wenn der Text Zeichen enthält, die auf eine falsche Kodierung hindeuten."""
    return bool(_ZEICHENSALAT.search(text)) or any(z in _VERDAECHTIG for z in text if z >= "\x80")


def _cp1252_ersatz(fehler: UnicodeError) -> tuple[str, int]:
    """Fehlerbehandlung: ungültige UTF-8-Bytes einzeln als Windows-1252 lesen."""
    assert isinstance(fehler, UnicodeDecodeError)
    stueck = fehler.object[fehler.start:fehler.end]
    return stueck.decode("cp1252", errors="replace"), fehler.end


codecs.register_error("namematch_cp1252", _cp1252_ersatz)


def ueberwiegend_utf8(daten: bytes) -> bool:
    """True, wenn die meisten Nicht-ASCII-Bytes gültige UTF-8-Folgen bilden (gemischte Datei)."""
    folgen = _UTF8_FOLGE.findall(daten)
    if not folgen:
        return False
    in_folgen = sum(len(f) for f in folgen)
    return in_folgen >= 0.5 * len(_HOHES_BYTE.findall(daten))


def gemischt_dekodieren(daten: bytes) -> str:
    """UTF-8 dekodieren, einzelne ungültige Bytes als Windows-1252."""
    return daten.decode("utf-8", errors="namematch_cp1252")


def einbyte_waehlen(daten: bytes) -> tuple[str, str]:
    """Wählt unter Windows-1252, Mac Roman und CP850 die plausibelste Lesart.

    Windows-1252 hat Vorrang, solange dabei keine verdächtigen Zeichen entstehen – so bleiben
    z. B. tschechische Namen („Košek“) in Windows-1252-Dateien korrekt.
    """
    kandidaten: list[tuple[int, int, str, str]] = []
    for rang, name in enumerate(EINBYTE_KODIERUNGEN):
        try:
            text = daten.decode(name)
        except UnicodeDecodeError:
            continue
        if name == "cp1252" and not any(z in _VERDAECHTIG for z in text if z >= "\x80"):
            return name, text
        kandidaten.append((plausibilitaet(text), -rang, name, text))
    if not kandidaten:
        return "latin-1", daten.decode("latin-1")
    _wertung, _rang, name, text = max(kandidaten)
    return name, text


def zeichensalat_reparieren(text: str) -> str:
    """Repariert UTF-8-Zeichensalat („BÃ¼lÃ¼kÃ¶z“ → „Bülüköz“) – nur für den Vergleich verwenden."""
    if not _ZEICHENSALAT.search(text):
        return text

    def ersetzen(treffer: re.Match[str]) -> str:
        try:
            return treffer.group(0).encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            try:
                return treffer.group(0).encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                return treffer.group(0)

    return _ZEICHENSALAT.sub(ersetzen, text)
