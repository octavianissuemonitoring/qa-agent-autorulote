"""
Fixtures comune.

IDEEA DE BAZA: testele nu au voie sa atinga data/. Fiecare test care schimba
datele primeste o COPIE, scrisa intr-un folder temporar, iar datastore e
indreptat catre ea. La finalul testului, cache-ul se goleste si agentul vede
din nou datele reale.

De ce copiem fisierele reale in loc sa inventam date de la zero: schema e
bogata (pachete km, discounturi in cascada, conditii sofer, extraoptiuni).
Pornind de la datele reale, un camp adaugat maine in flota.json nu strica
toate testele - fiecare test schimba doar ce il intereseaza.
"""

import json
import shutil
from datetime import date

import pytest

from tools import datastore

FISIERE = [
    "flota.json",
    "parteneri.json",
    "rezervari.json",
    "mentenanta.json",
    "nomenclatoare.json",
    "extraoptiuni.json",
]


class DateTest:
    """Datele de test: se citesc, se modifica in Python, se scriu, se reincarca."""

    def __init__(self, director):
        self.director = director

    def citeste(self, fisier: str) -> dict:
        return json.loads((self.director / fisier).read_text(encoding="utf-8"))

    def scrie(self, fisier: str, continut: dict) -> None:
        (self.director / fisier).write_text(
            json.dumps(continut, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        datastore.reincarca()

    # --- scurtaturi pentru modificarile cele mai dese ------------------
    def vehicul(self, vehicul_id: str, **campuri):
        date_flota = self.citeste("flota.json")
        for v in date_flota["vehicule"]:
            if v["id"] == vehicul_id:
                v.update(campuri)
        self.scrie("flota.json", date_flota)

    def doar_rezervarile(self, rezervari: list[dict]) -> None:
        """Inlocuieste TOATE rezervarile - calendarul devine previzibil."""
        self.scrie("rezervari.json", {"rezervari": rezervari})

    def mentenanta(self, vehicul_id: str, **campuri):
        date_m = self.citeste("mentenanta.json")
        for m in date_m["mentenanta"]:
            if m["vehicul_id"] == vehicul_id:
                m.update(campuri)
        self.scrie("mentenanta.json", date_m)


@pytest.fixture
def date_test(tmp_path, monkeypatch):
    """Copie izolata a datelor, pe care testul o poate strica in voie."""
    director = tmp_path / "data"
    director.mkdir()
    for fisier in FISIERE:
        shutil.copy(datastore.DATA / fisier, director / fisier)

    monkeypatch.setattr(datastore, "DATA", director)
    datastore.reincarca()
    yield DateTest(director)
    datastore.reincarca()  # testul urmator vede iar datele reale


@pytest.fixture
def date_reale():
    """Datele din data/, garantat curate (cache golit inainte si dupa)."""
    datastore.reincarca()
    yield datastore
    datastore.reincarca()


@pytest.fixture
def partener_nopti(date_reale):
    """MHC: factureaza nopti, buffer 1 zi, minim 5 nopti in sezon."""
    return date_reale.partener("MHC")


@pytest.fixture
def partener_zile(date_reale):
    """GC: factureaza zile calendaristice."""
    return date_reale.partener("GC")


def zi(text: str) -> date:
    """'2026-10-13' -> date(2026, 10, 13). Face testele mai usor de citit."""
    return date.fromisoformat(text)
