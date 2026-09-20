"""
Datastore: tarife, statusuri, documente si validarea configurarii.

Tema comuna: ce se intampla cand datele sunt GRESITE. Regula proiectului e
"fail closed" - mai bine refuzam o oferta decat sa trimitem un pret inventat
sau sa inchiriem de doua ori acelasi vehicul.
"""

import pytest

from tools import datastore

from conftest import zi


def rez(id_: str, status: str) -> dict:
    return {
        "id": id_,
        "vehicul_id": "AR-001",
        "client": "C-TEST",
        "data_start": "2026-10-10",
        "data_sfarsit": "2026-10-12",
        "status": status,
    }


# ---------------------------------------------------------------------
# Tarife: lipsa NU inseamna zero
# ---------------------------------------------------------------------
def test_tariful_existent_se_intoarce_ca_numar(date_reale):
    v = datastore.vehicul("AR-001")
    assert datastore.tarif_sezon(v, "sezon") == 176.0


def test_tariful_lipsa_arunca(date_reale):
    v = datastore.vehicul("AR-001")
    with pytest.raises(KeyError):
        datastore.tarif_sezon(v, "inexistent")


def test_mesajul_de_eroare_spune_ce_sezoane_exista(date_reale):
    v = datastore.vehicul("AR-001")
    with pytest.raises(KeyError) as e:
        datastore.tarif_sezon(v, "inexistent")
    mesaj = e.value.args[0]
    assert "AR-001" in mesaj and "extrasezon" in mesaj and "flota.json" in mesaj


def test_tariful_zero_ramane_zero(date_test):
    """Zero explicit e o decizie comerciala valida; doar LIPSA e problema."""
    date_test.vehicul("AR-001", tarife_sezon={"sezon": 0})
    assert datastore.tarif_sezon(datastore.vehicul("AR-001"), "sezon") == 0.0


# ---------------------------------------------------------------------
# Statusuri
# ---------------------------------------------------------------------
def test_statusul_cunoscut_se_citeste_din_nomenclator(date_reale):
    assert datastore.status_rezervare("contractat")["blocheaza_calendar"] is True
    assert datastore.status_rezervare("oferta")["blocheaza_calendar"] is False


def test_statusul_necunoscut_blocheaza(date_reale):
    fisa = datastore.status_rezervare("confirmatt")
    assert fisa["blocheaza_calendar"] is True
    assert fisa["avertizeaza"] is True
    assert fisa["necunoscut"] is True


def test_statusul_necunoscut_nu_ancoreaza_matching(date_reale):
    """Nu construim reduceri comerciale pe baza unei date gresite."""
    assert datastore.status_rezervare("confirmatt")["ancoreaza_matching"] is False


def test_status_necunoscut_recunoaste_rezervarea(date_reale):
    assert datastore.status_necunoscut(rez("R1", "confirmatt")) is True
    assert datastore.status_necunoscut(rez("R2", "contractat")) is False


# ---------------------------------------------------------------------
# Documente
# ---------------------------------------------------------------------
def test_documentul_expirat_inainte_de_predare_se_raporteaza(date_test):
    date_test.mentenanta("AR-001", rca_expira="2026-09-30")
    probleme = datastore.documente_expirate("AR-001", zi("2026-10-24"))
    assert any("RCA" in p for p in probleme)


def test_documentul_valabil_nu_se_raporteaza(date_test):
    date_test.mentenanta("AR-001", rca_expira="2027-01-01")
    probleme = datastore.documente_expirate("AR-001", zi("2026-10-24"))
    assert not any("RCA" in p for p in probleme)


def test_documentul_care_expira_in_timpul_inchirierii(date_test):
    """Preluare 20 oct, predare 25 oct, ITP expira pe 22: trebuie semnalat."""
    date_test.mentenanta("AR-001", itp_expira="2026-10-22")
    probleme = datastore.documente_expirate("AR-001", zi("2026-10-25"))
    assert any("ITP" in p for p in probleme)


def test_documentul_care_expira_fix_in_ziua_predarii_e_acceptat(date_test):
    """Valabil pana la predare inclusiv - masina se intoarce in aceeasi zi."""
    date_test.mentenanta("AR-001", itp_expira="2026-10-25")
    probleme = datastore.documente_expirate("AR-001", zi("2026-10-25"))
    assert not any("ITP" in p for p in probleme)


def test_data_lipsa_din_fisa_se_raporteaza(date_test):
    date_test.mentenanta("AR-001", rovinieta_expira=None)
    probleme = datastore.documente_expirate("AR-001", zi("2026-10-25"))
    assert any("Rovinieta" in p and "lipseste" in p for p in probleme)


def test_data_invalida_se_raporteaza_fara_sa_crape(date_test):
    date_test.mentenanta("AR-001", casco_expira="candva")
    probleme = datastore.documente_expirate("AR-001", zi("2026-10-25"))
    assert any("invalida" in p for p in probleme)


def test_vehicul_fara_fisa_de_mentenanta_nu_crapa(date_reale):
    assert datastore.documente_expirate("NU-EXISTA", zi("2026-10-25")) == []


# ---------------------------------------------------------------------
# Validarea configurarii, rulata la fiecare pornire
# ---------------------------------------------------------------------
def test_datele_reale_sunt_valide(date_reale):
    assert datastore.valideaza_configurarea() == []


def test_tariful_lipsa_apare_la_validare(date_test):
    date_test.vehicul("GC-002", tarife_sezon={"extrasezon": 140, "varf": 200})
    probleme = datastore.valideaza_configurarea()
    assert any("GC-002" in p and "sezon" in p for p in probleme)


def test_statusul_inventat_apare_la_validare(date_test):
    date_test.doar_rezervarile([rez("R1", "confirmatt")])
    probleme = datastore.valideaza_configurarea()
    assert any("R1" in p and "status necunoscut" in p for p in probleme)


def test_vehiculul_inexistent_dintr_o_rezervare_apare_la_validare(date_test):
    r = rez("R1", "contractat")
    r["vehicul_id"] = "XX-999"
    date_test.doar_rezervarile([r])
    assert any("XX-999" in p for p in datastore.valideaza_configurarea())


def test_partenerul_inexistent_apare_la_validare(date_test):
    date_test.vehicul("AR-001", partener_id="NU-EXISTA")
    assert any("AR-001" in p and "partener" in p for p in datastore.valideaza_configurarea())


def test_validarea_le_raporteaza_pe_toate_deodata(date_test):
    """Operatorul vrea lista completa, nu prima problema si apoi inca o rulare."""
    date_test.vehicul("GC-002", tarife_sezon={})
    date_test.doar_rezervarile([rez("R1", "confirmatt")])
    probleme = datastore.valideaza_configurarea()
    assert len(probleme) >= 4


# ---------------------------------------------------------------------
# Integritate referentiala
# ---------------------------------------------------------------------
def test_vehiculul_fara_partener_arunca_la_citire(date_test):
    date_test.vehicul("AR-001", partener_id="NU-EXISTA")
    with pytest.raises(KeyError):
        datastore.partenerul_vehiculului(datastore.vehicul("AR-001"))
