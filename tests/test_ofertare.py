"""
Devizul: durata minima, discounturi in cascada, rotunjiri, kilometri,
configurare lipsa si avertismente.

Testele citesc rezultatul asa cum il vede modelul - ca text. E si verificarea
ca informatia chiar AJUNGE in raspuns, nu doar ca se calculeaza corect undeva.
"""

import re

import pytest

from tools import ToolWrapper


def deviz(**params) -> str:
    return ToolWrapper.call("calculate_quote", params)


def _randul(text: str, eticheta: str) -> str:
    for linie in text.splitlines():
        if eticheta in linie:
            return linie
    raise AssertionError(f"nu am gasit {eticheta!r} in:\n{text}")


def _sume(linie: str) -> list[float]:
    return [
        float(s.replace(" ", "").replace(",", "."))
        for s in re.findall(r"-?\d[\d ]*[.,]\d\d", linie)
    ]


def numar(text: str, eticheta: str) -> float:
    """Ultima suma de pe randul cu eticheta ceruta (ex: 'SUBTOTAL: 560.00 EUR')."""
    return _sume(_randul(text, eticheta))[-1]


def valoare_discount(text: str, eticheta: str) -> float:
    """
    Cat s-a scazut efectiv. Randul arata asa:
        Durata (8 zile, prag 7+, extrasezon): -15% = -168.00 EUR  -> 952.00 EUR
    Ne intereseaza suma de dupa '=', nu restul de plata de la final.
    """
    linie = _randul(text, eticheta)
    dupa_egal = linie.split("=", 1)[1]
    return abs(_sume(dupa_egal)[0])


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
# Perioada, in sistemul partenerului
# ---------------------------------------------------------------------
def test_devizul_pe_zile_spune_zile(date_test):
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="GC-002", data_start="2026-10-13", data_sfarsit="2026-10-20")
    assert "(8 zile)" in r


def test_devizul_pe_nopti_spune_nopti(date_test):
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="AR-001", data_start="2026-10-13", data_sfarsit="2026-10-20")
    assert "(7 nopti)" in r


def test_preluarea_si_predarea_in_aceeasi_zi_nu_se_factureaza_pe_nopti(date_test):
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="AR-001", data_start="2026-10-13", data_sfarsit="2026-10-13")
    assert "nicio unitate facturabila" in r


def test_data_inversata_e_respinsa(date_reale):
    r = deviz(vehicul_id="GC-002", data_start="2026-10-20", data_sfarsit="2026-10-13")
    assert r.startswith("EROARE")


def test_data_in_format_gresit_e_respinsa_cu_indicatie(date_reale):
    r = deviz(vehicul_id="GC-002", data_start="13 octombrie", data_sfarsit="2026-10-20")
    assert "EROARE" in r and "AAAA-LL-ZZ" in r


# ---------------------------------------------------------------------
# Durata minima, dupa sezonul zilei de preluare
# ---------------------------------------------------------------------
def test_sub_durata_minima_nu_se_oferteaza(date_test):
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="AR-001", data_start="2026-10-20", data_sfarsit="2026-10-23")
    assert "NU SE POATE OFERTA" in r and "5 nopti" in r


def test_exact_durata_minima_se_oferteaza(date_test):
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="AR-001", data_start="2026-10-20", data_sfarsit="2026-10-25")
    assert "TOTAL DE PLATA" in r


def test_durata_minima_se_ia_dupa_ziua_de_preluare(date_test):
    """
    Preluare pe 30 oct = sezon (minim 5 nopti), desi aproape tot sejurul cade
    in extrasezon (minim 3). Conteaza ziua preluarii, nu majoritatea zilelor.
    """
    date_test.doar_rezervarile([])
    cinci_nopti = deviz(vehicul_id="AR-001", data_start="2026-10-30", data_sfarsit="2026-11-04")
    assert "TOTAL DE PLATA" in cinci_nopti

    trei_nopti = deviz(vehicul_id="AR-001", data_start="2026-10-30", data_sfarsit="2026-11-02")
    assert "NU SE POATE OFERTA" in trei_nopti and "5 nopti" in trei_nopti


# ---------------------------------------------------------------------
# Tarife pe sezoane si treceri intre ele
# ---------------------------------------------------------------------
def test_fiecare_zi_se_taxeaza_la_sezonul_ei(date_test):
    """La GC, sezonul se termina pe 14 oct: 13-14 oct = Sezon, 15 oct = Extrasezon."""
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="GC-002", data_start="2026-10-12", data_sfarsit="2026-10-16")
    randuri = [l for l in r.splitlines() if l.strip().startswith("2026-10-")]
    assert "Sezon" in randuri[0] and "Extrasezon" in randuri[-1]
    assert numar(r, "SUBTOTAL") == 182 * 3 + 140 * 2


def test_subtotalul_e_suma_zilelor(date_test):
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05")
    # 4 zile de extrasezon la 140
    assert numar(r, "SUBTOTAL") == 560.00


def test_tariful_lipsa_opreste_devizul(date_test):
    date_test.vehicul("GC-002", tarife_sezon={"extrasezon": 140})
    r = deviz(vehicul_id="GC-002", data_start="2026-10-13", data_sfarsit="2026-10-20")
    assert r.startswith("EROARE DE CONFIGURARE")
    assert "sezon" in r


def test_tariful_lipsa_nu_produce_zile_gratuite(date_test):
    """Regresie: varianta veche folosea .get(cod, 0) si scotea un pret mai mic."""
    date_test.vehicul("GC-002", tarife_sezon={"extrasezon": 140})
    r = deviz(vehicul_id="GC-002", data_start="2026-10-13", data_sfarsit="2026-10-20")
    assert "TOTAL DE PLATA" not in r


def test_sezonul_nedefinit_opreste_devizul(date_test):
    p = date_test.citeste("parteneri.json")
    for partener in p["parteneri"]:
        if partener["id"] == "GC":
            partener["sezoane"] = [s for s in partener["sezoane"] if s["cod"] != "sezon"]
    date_test.scrie("parteneri.json", p)
    r = deviz(vehicul_id="GC-002", data_start="2026-10-13", data_sfarsit="2026-10-20")
    assert "EROARE" in r and "sezon" in r


# ---------------------------------------------------------------------
# Discounturi in cascada si rotunjiri
# ---------------------------------------------------------------------
def test_discountul_de_durata_se_aplica_peste_prag(date_test):
    """8 zile depasesc pragul de 7 din grila de extrasezon: -15%."""
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-09")
    assert valoare_discount(r, "Durata (") == round(numar(r, "SUBTOTAL") * 0.15, 2)


def test_sub_prag_nu_exista_discount_de_durata(date_test):
    """Pragul GC e 7 zile: o inchiriere de 3 zile nu primeste discount de durata."""
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-04")
    assert "Durata (" not in r


def test_discounturile_se_aplica_in_cascada_nu_prin_adunare(date_test):
    """
    Doua discounturi de 10% si 5% in cascada dau 14.5%, nu 15%. Diferenta e
    mica in procente si mare in bani - de aceea se verifica.
    """
    date_test.doar_rezervarile([])
    p = date_test.citeste("parteneri.json")
    for partener in p["parteneri"]:
        if partener["id"] == "GC":
            partener["discounturi"]["durata"]["extrasezon"] = [{"min_zile": 3, "procent": 10}]
            partener["discounturi"]["early_booking"]["extrasezon"] = {
                "min_zile_inainte": 1,
                "procent": 5,
            }
    date_test.scrie("parteneri.json", p)

    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05")
    subtotal = numar(r, "SUBTOTAL")  # 4 x 140 = 560
    durata = valoare_discount(r, "Durata (")  # 10% din 560 = 56
    early = valoare_discount(r, "Rezervare din timp")  # 5% din 504 = 25.20, nu 28
    assert subtotal == 560.00
    assert durata == 56.00
    assert early == 25.20


def test_sumele_sunt_rotunjite_la_doi_zecimali(date_test):
    date_test.doar_rezervarile([])
    p = date_test.citeste("parteneri.json")
    for partener in p["parteneri"]:
        if partener["id"] == "GC":
            partener["discounturi"]["durata"]["extrasezon"] = [{"min_zile": 3, "procent": 7}]
    date_test.scrie("parteneri.json", p)
    date_test.vehicul("GC-002", tarife_sezon={"extrasezon": 99.99, "sezon": 182, "varf": 240})

    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05")
    for suma in re.findall(r"\d+[.,]\d+", r):
        assert len(suma.split(".")[-1].split(",")[-1]) <= 2


def test_taxa_de_curatenie_apare_in_total(date_test):
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05")
    assert "curatenie" in r.lower()


# ---------------------------------------------------------------------
# Kilometri
# ---------------------------------------------------------------------
def test_pachetul_de_km_inexistent_e_respins_cu_optiunile_valide(date_reale):
    r = deviz(
        vehicul_id="GC-002",
        data_start="2026-11-02",
        data_sfarsit="2026-11-05",
        pachet_km="nelimitatt",
    )
    assert "EROARE" in r and "standard" in r


def test_depasirea_plafonului_de_km_se_taxeaza(date_test):
    date_test.doar_rezervarile([])
    fara = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05", km_estimati=100)
    cu = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05", km_estimati=9000)
    assert numar(cu, "TOTAL DE PLATA") > numar(fara, "TOTAL DE PLATA")


def test_fara_km_estimati_se_avertizeaza(date_test):
    date_test.doar_rezervarile([])
    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05")
    assert "kilometri" in r.lower()


# ---------------------------------------------------------------------
# Avertismente: disponibilitate, documente, cereri provizorii
# ---------------------------------------------------------------------
def test_perioada_ocupata_da_deviz_informativ_cu_avertisment(date_test):
    date_test.doar_rezervarile([rez("R1", "GC-002", "2026-11-03", "2026-11-04")])
    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05")
    assert "NU E DISPONIBILA" in r and "TOTAL DE PLATA" in r


def test_documentul_expirat_apare_ca_avertisment_nu_ca_refuz(date_test):
    date_test.doar_rezervarile([])
    date_test.mentenanta("GC-002", rca_expira="2026-10-01")
    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05")
    assert "DOCUMENTE" in r and "RCA" in r
    assert "TOTAL DE PLATA" in r


def test_cererea_provizorie_se_semnaleaza(date_test):
    date_test.doar_rezervarile([rez("R1", "GC-002", "2026-11-03", "2026-11-04", "oferta")])
    r = deviz(vehicul_id="GC-002", data_start="2026-11-02", data_sfarsit="2026-11-05")
    assert "interes" in r.lower()


def test_soferul_prea_tanar_e_respins(date_reale):
    r = deviz(
        vehicul_id="GC-002",
        data_start="2026-11-02",
        data_sfarsit="2026-11-05",
        varsta_sofer=19,
    )
    assert "sub minimul" in r


# ---------------------------------------------------------------------
# Extraoptiuni
# ---------------------------------------------------------------------
def test_extraoptiunea_inexistenta_e_respinsa_cu_lista_valida(date_reale):
    r = deviz(
        vehicul_id="GC-002",
        data_start="2026-11-02",
        data_sfarsit="2026-11-05",
        extraoptiuni=["gratar_portabil"],
    )
    assert "EROARE" in r and "gratar" in r


def test_extraoptiunea_valida_intra_in_deviz(date_test):
    date_test.doar_rezervarile([])
    r = deviz(
        vehicul_id="GC-002",
        data_start="2026-11-02",
        data_sfarsit="2026-11-05",
        extraoptiuni=["gratar"],
    )
    assert "TOTAL DE PLATA" in r


# ---------------------------------------------------------------------
# Regresie: cifra care nu are voie sa se schimbe
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "vehicul, start, sfarsit, total",
    [
        ("GC-002", "2026-10-13", "2026-10-20", 1158.60),
        ("AR-001", "2026-09-28", "2026-10-03", 896.00),
    ],
)
def test_totaluri_cunoscute(date_reale, vehicul, start, sfarsit, total):
    r = deviz(vehicul_id=vehicul, data_start=start, data_sfarsit=sfarsit)
    assert numar(r, "TOTAL DE PLATA") == total
