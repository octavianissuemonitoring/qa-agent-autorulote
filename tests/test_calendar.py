"""
Motorul de calendar: sezoane, zile blocate, buffer, ferestre libere, ancore.

Aproape toate testele isi scriu singure rezervarile (date_test.doar_rezervarile),
ca sa nu depinda de continutul real al lui data/rezervari.json - care se schimba.
"""

from tools import calendar_flota as cal
from tools import datastore

from conftest import zi


def rez(id_: str, vehicul: str, start: str, sfarsit: str, status: str = "contractat") -> dict:
    return {
        "id": id_,
        "vehicul_id": vehicul,
        "client": "C-TEST",
        "data_start": start,
        "data_sfarsit": sfarsit,
        "status": status,
    }


# ---------------------------------------------------------------------
# 1. Sezonul unei zile
# ---------------------------------------------------------------------
def test_sezonul_de_vara_e_varf(partener_nopti):
    assert cal.sezon_pentru_zi(partener_nopti, zi("2026-07-15"))["cod"] == "varf"


def test_sezonul_de_toamna_e_sezon(partener_nopti):
    assert cal.sezon_pentru_zi(partener_nopti, zi("2026-10-15"))["cod"] == "sezon"


def test_extrasezonul_trece_peste_an(partener_nopti):
    """Extrasezonul e 11-01 -> 03-31, deci intervalul sare peste 31 decembrie."""
    assert cal.sezon_pentru_zi(partener_nopti, zi("2026-12-20"))["cod"] == "extrasezon"
    assert cal.sezon_pentru_zi(partener_nopti, zi("2027-02-10"))["cod"] == "extrasezon"


def test_prima_si_ultima_zi_de_sezon_sunt_incluse(partener_nopti):
    assert cal.sezon_pentru_zi(partener_nopti, zi("2026-07-01"))["cod"] == "varf"
    assert cal.sezon_pentru_zi(partener_nopti, zi("2026-08-31"))["cod"] == "varf"
    assert cal.sezon_pentru_zi(partener_nopti, zi("2026-09-01"))["cod"] == "sezon"


def test_durata_minima_difera_pe_sezon(partener_nopti):
    varf = cal.sezon_pentru_zi(partener_nopti, zi("2026-07-15"))
    extrasezon = cal.sezon_pentru_zi(partener_nopti, zi("2026-12-15"))
    assert varf["durata_minima_zile"] > extrasezon["durata_minima_zile"]


# ---------------------------------------------------------------------
# 2. Zile blocate si buffer
# ---------------------------------------------------------------------
def test_zilele_rezervarii_sunt_blocate(date_test, partener_nopti):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12")])
    blocate = cal.zile_blocate("AR-001", partener_nopti)
    for z in ("2026-10-10", "2026-10-11", "2026-10-12"):
        assert zi(z) in blocate


def test_buffer_dupa_rezervare(date_test, partener_nopti):
    """MHC are buffer 1: ziua de dupa ramane blocata pentru curatenie."""
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12")])
    blocate = cal.zile_blocate("AR-001", partener_nopti)
    assert zi("2026-10-13") in blocate
    assert "buffer" in blocate[zi("2026-10-13")]


def test_buffer_inainte_de_rezervare(date_test, partener_nopti):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12")])
    blocate = cal.zile_blocate("AR-001", partener_nopti)
    assert zi("2026-10-09") in blocate


def test_prima_zi_libera_dupa_buffer(date_test, partener_nopti):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12")])
    blocate = cal.zile_blocate("AR-001", partener_nopti)
    assert zi("2026-10-14") not in blocate


def test_buffer_mai_mare_blocheaza_mai_multe_zile(date_test):
    p = date_test.citeste("parteneri.json")
    for partener in p["parteneri"]:
        if partener["id"] == "MHC":
            partener["reguli_operationale"]["zile_buffer"] = 3
    date_test.scrie("parteneri.json", p)
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12")])

    blocate = cal.zile_blocate("AR-001", datastore.partener("MHC"))
    assert zi("2026-10-15") in blocate
    assert zi("2026-10-16") not in blocate


# ---------------------------------------------------------------------
# 3. Statusuri: ferme, provizorii, necunoscute
# ---------------------------------------------------------------------
def test_statusul_ferm_blocheaza(date_test, partener_nopti):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12", "contractat")])
    assert zi("2026-10-11") in cal.zile_blocate("AR-001", partener_nopti)


def test_statusul_provizoriu_nu_blocheaza(date_test, partener_nopti):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12", "oferta")])
    assert zi("2026-10-11") not in cal.zile_blocate("AR-001", partener_nopti)


def test_statusul_provizoriu_se_raporteaza_ca_suprapunere(date_test):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12", "oferta")])
    gasite = cal.suprapuneri_provizorii("AR-001", zi("2026-10-11"), zi("2026-10-14"))
    assert [r["id"] for r in gasite] == ["R1"]


def test_statusul_anulat_nu_blocheaza(date_test, partener_nopti):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12", "anulat")])
    assert cal.zile_blocate("AR-001", partener_nopti) == {}


def test_statusul_necunoscut_blocheaza_prudent(date_test, partener_nopti):
    """Regula de siguranta: o greseala de scriere nu are voie sa produca dubla rezervare."""
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12", "confirmatt")])
    blocate = cal.zile_blocate("AR-001", partener_nopti)
    assert zi("2026-10-11") in blocate
    assert "STATUS NECUNOSCUT" in blocate[zi("2026-10-11")]


# ---------------------------------------------------------------------
# 4. Ferestre libere
# ---------------------------------------------------------------------
def test_fara_rezervari_fereastra_e_tot_orizontul(date_test, partener_nopti):
    date_test.doar_rezervarile([])
    ferestre = cal.ferestre_libere("AR-001", partener_nopti, zi("2026-10-01"), zi("2026-10-31"))
    assert ferestre == [(zi("2026-10-01"), zi("2026-10-31"))]


def test_o_rezervare_taie_orizontul_in_doua(date_test, partener_nopti):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12")])
    ferestre = cal.ferestre_libere("AR-001", partener_nopti, zi("2026-10-01"), zi("2026-10-31"))
    assert ferestre == [
        (zi("2026-10-01"), zi("2026-10-08")),  # buffer 1 zi inainte
        (zi("2026-10-14"), zi("2026-10-31")),  # buffer 1 zi dupa
    ]


def test_doua_rezervari_lipite_nu_lasa_fereastra(date_test, partener_nopti):
    date_test.doar_rezervarile(
        [
            rez("R1", "AR-001", "2026-10-10", "2026-10-12"),
            rez("R2", "AR-001", "2026-10-14", "2026-10-16"),
        ]
    )
    ferestre = cal.ferestre_libere("AR-001", partener_nopti, zi("2026-10-13"), zi("2026-10-13"))
    assert ferestre == []


# ---------------------------------------------------------------------
# 5. Ancore de matching
# ---------------------------------------------------------------------
def test_reducerea_apare_langa_o_rezervare_ancora(date_test, partener_nopti):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12", "contractat")])
    reduceri = cal.reduceri_matching("AR-001", partener_nopti)
    assert zi("2026-10-14") in reduceri  # prima zi libera dupa buffer


def test_ziua_blocata_nu_primeste_reducere(date_test, partener_nopti):
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12", "contractat")])
    reduceri = cal.reduceri_matching("AR-001", partener_nopti)
    assert zi("2026-10-11") not in reduceri
    assert zi("2026-10-13") not in reduceri  # buffer


def test_fara_rezervari_nu_exista_reduceri(date_test, partener_nopti):
    date_test.doar_rezervarile([])
    assert cal.reduceri_matching("AR-001", partener_nopti) == {}


def test_reducerea_scade_cu_distanta(date_test, partener_nopti):
    """Scara e descrescatoare: ziua lipita ia mai mult decat cea urmatoare."""
    date_test.doar_rezervarile([rez("R1", "AR-001", "2026-10-10", "2026-10-12", "contractat")])
    reduceri = cal.reduceri_matching("AR-001", partener_nopti)
    prima = reduceri[zi("2026-10-14")]["procent"]
    a_doua = reduceri.get(zi("2026-10-15"), {"procent": 0})["procent"]
    assert prima > a_doua
