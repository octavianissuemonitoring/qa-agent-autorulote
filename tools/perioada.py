"""
Perioada de inchiriere - NU e un tool, e un tip de domeniu (ca datastore.py).

DE CE EXISTA acest fisier:
    Partenerii nostri factureaza diferit. GC factureaza ZILE calendaristice
    (13-20 oct = 8 zile), MHC factureaza NOPTI, ca la hotel (13-20 oct = 7
    nopti). Pana acum fiecare tool isi facea singur socoteala, si nu la fel:

      matching  pornea de la durata si calcula  sfarsit = start + durata - 1
      ofertare  pornea de la date si calcula    unitati = numar_unitati(...)

    Pentru un partener pe nopti, cele doua nu se potriveau: matching recomanda
    o perioada de "5 zile" pe care ofertare o citea ca 4 nopti si o refuza,
    fiind sub durata minima. Clientul primea o recomandare imposibil de ofertat.

    Aici e singurul loc unde se traduce intre date calendaristice si unitati
    facturabile. Cele trei tool-uri primesc acelasi obiect si vorbesc despre
    aceeasi perioada.

DOUA FELURI DE ZILE, usor de confundat:
    zile_facturate - zilele care intra in pret. Pe nopti, ziua predarii NU se
                     factureaza: clientul pleaca in dimineata aceea.
    zile_ocupate   - zilele in care vehiculul e la client, deci nu poate fi dat
                     altcuiva. Include ziua predarii, in ambele sisteme.
"""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class PerioadaInchiriere:
    """
    O perioada de inchiriere, vazuta si ca date calendaristice, si ca unitati
    facturabile. Se construieste doar prin din_date() sau din_unitati().
    """

    preluare: date
    predare: date
    unitati: int
    pe_nopti: bool

    # -----------------------------------------------------------------
    # Constructoare
    # -----------------------------------------------------------------
    @staticmethod
    def din_date(partener: dict, start: date, sfarsit: date) -> "PerioadaInchiriere":
        """
        Din datele cerute de client (check_availability, calculate_quote).

          sistem 'zile'  -> 10-12 aug = 3 zile
          sistem 'nopti' -> 10-12 aug = 2 nopti
        """
        pe_nopti = _pe_nopti(partener)
        diferenta = (sfarsit - start).days
        unitati = max(diferenta, 0) if pe_nopti else max(diferenta + 1, 0)
        return PerioadaInchiriere(
            preluare=start, predare=sfarsit, unitati=unitati, pe_nopti=pe_nopti
        )

    @staticmethod
    def din_unitati(partener: dict, start: date, unitati: int) -> "PerioadaInchiriere":
        """
        Din durata dorita (find_matching_opportunities).

        Aici statea greseala pe care o repara fisierul asta: ziua predarii
        depinde de sistemul partenerului.

          5 zile  incepand cu 29 sept -> predare 3 oct  (start + 5 - 1)
          5 nopti incepand cu 29 sept -> predare 4 oct  (start + 5)
        """
        pe_nopti = _pe_nopti(partener)
        unitati = max(unitati, 0)
        zile_pana_la_predare = unitati if pe_nopti else max(unitati - 1, 0)
        return PerioadaInchiriere(
            preluare=start,
            predare=start + timedelta(days=zile_pana_la_predare),
            unitati=unitati,
            pe_nopti=pe_nopti,
        )

    # -----------------------------------------------------------------
    # Zilele
    # -----------------------------------------------------------------
    @property
    def zile_facturate(self) -> list[date]:
        """Zilele care intra in pret. Pe nopti, ziua predarii nu e printre ele."""
        return [self.preluare + timedelta(days=i) for i in range(self.unitati)]

    @property
    def zile_ocupate(self) -> list[date]:
        """
        Zilele in care vehiculul e la client, deci indisponibil pentru altcineva.
        Include ziua predarii: masina se intoarce abia atunci.
        """
        total = (self.predare - self.preluare).days + 1
        return [self.preluare + timedelta(days=i) for i in range(max(total, 0))]

    # -----------------------------------------------------------------
    # Cum o numim in fata clientului
    # -----------------------------------------------------------------
    @property
    def eticheta(self) -> str:
        """'nopti' sau 'zile' - pentru texte de forma '5 nopti'."""
        return "nopti" if self.pe_nopti else "zile"

    @property
    def unitate_singular(self) -> str:
        return "noapte" if self.pe_nopti else "zi"

    @property
    def descriere(self) -> str:
        """'2026-09-29 - 2026-10-04 (5 nopti)'."""
        return (
            f"{self.preluare.isoformat()} - {self.predare.isoformat()} "
            f"({self.unitati} {self.eticheta})"
        )


def _pe_nopti(partener: dict) -> bool:
    return partener["reguli_operationale"]["sistem_calcul"] == "nopti"
