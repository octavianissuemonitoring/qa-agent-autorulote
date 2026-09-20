"""
Stratul de tool-uri: registry, wrapper si cele patru cazuri de eroare din S6.6,
plus disponibilitate si matching vazute ca text, asa cum le primeste modelul.
"""

from tools import ToolWrapper
from tools.registry import TOOL_REGISTRY


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
# Registry si catalog (S7.2)
# ---------------------------------------------------------------------
def test_toate_tool_urile_sunt_inregistrate():
    assert len(TOOL_REGISTRY) == 7


def test_fiecare_tool_are_functie_model_si_descriere():
    for nume, tool in TOOL_REGISTRY.items():
        assert callable(tool["functie"]), nume
        assert tool["descriere"].strip(), nume
        assert hasattr(tool["model_params"], "model_json_schema"), nume


def test_catalogul_are_o_definitie_per_tool():
    catalog = ToolWrapper.catalog()
    assert len(catalog) == len(TOOL_REGISTRY)
    assert {c["function"]["name"] for c in catalog} == set(TOOL_REGISTRY)


def test_catalogul_contine_descrierile_campurilor():
    """Field(description=...) ajunge in JSON Schema, de acolo la model (S7.5)."""
    d = [c for c in ToolWrapper.catalog() if c["function"]["name"] == "check_availability"][0]
    proprietati = d["function"]["parameters"]["properties"]
    assert "description" in proprietati["data_start"]


def test_catalogul_nu_trimite_titlurile_generate_de_pydantic():
    for c in ToolWrapper.catalog():
        schema = c["function"]["parameters"]
        assert "title" not in schema
        for camp in schema.get("properties", {}).values():
            assert "title" not in camp


# ---------------------------------------------------------------------
# Error handling in tools (S6.6), toate cele patru cazuri
# ---------------------------------------------------------------------
def test_tool_inexistent_primeste_lista_celor_valide():
    r = ToolWrapper.call("get_weather", {})
    assert r.startswith("EROARE") and "check_availability" in r


def test_parametru_obligatoriu_lipsa():
    r = ToolWrapper.call("get_vehicle_details", {})
    assert "EROARE de validare" in r and "vehicul_id" in r


def test_parametru_in_afara_intervalului():
    """locuri_dormit_min are ge=1, le=10 in modelul Pydantic."""
    r = ToolWrapper.call(
        "check_availability",
        {"data_start": "2026-11-02", "data_sfarsit": "2026-11-05", "locuri_dormit_min": 99},
    )
    assert "EROARE de validare" in r


def test_executie_esuata_nu_arunca_ci_intoarce_text(monkeypatch):
    def crapa(_params):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setitem(TOOL_REGISTRY["calculator"], "functie", crapa)
    r = ToolWrapper.call("calculator", {"expression": "1+1"})
    assert r.startswith("EROARE la executia") and "ZeroDivisionError" in r


def test_rezultatul_gol_e_tratat_ca_eroare(monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY["calculator"], "functie", lambda p: "")
    r = ToolWrapper.call("calculator", {"expression": "1+1"})
    assert "rezultat gol" in r


def test_rezultatul_none_e_tratat_ca_eroare(monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY["calculator"], "functie", lambda p: None)
    assert "rezultat gol" in ToolWrapper.call("calculator", {"expression": "1+1"})


def test_rezultatul_zero_e_valid(monkeypatch):
    """Zero e un rezultat, nu o lipsa - calculatorul are voie sa intoarca 0."""
    monkeypatch.setitem(TOOL_REGISTRY["calculator"], "functie", lambda p: 0)
    assert ToolWrapper.call("calculator", {"expression": "1-1"}) == "0"


def test_erorile_nu_sunt_stack_trace_uri():
    """Regula S6.6: mesaje pe care le intelege un model, nu urme de Python."""
    r = ToolWrapper.call("get_vehicle_details", {"vehicul_id": "GC-999"})
    assert "Traceback" not in r and "EROARE" in r and "GC-001" in r


# ---------------------------------------------------------------------
# check_availability
# ---------------------------------------------------------------------
def test_vehiculul_liber_apare_ca_disponibil(date_test):
    date_test.doar_rezervarile([])
    r = ToolWrapper.call(
        "check_availability",
        {"data_start": "2026-11-02", "data_sfarsit": "2026-11-05", "vehicul_id": "GC-002"},
    )
    assert "DISPONIBILE (1)" in r


def test_vehiculul_ocupat_apare_cu_motivul(date_test):
    date_test.doar_rezervarile([rez("R1", "GC-002", "2026-11-03", "2026-11-04")])
    r = ToolWrapper.call(
        "check_availability",
        {"data_start": "2026-11-02", "data_sfarsit": "2026-11-05", "vehicul_id": "GC-002"},
    )
    assert "INDISPONIBILE" in r and "R1" in r


def test_perioada_sub_durata_minima_are_lista_separata(date_test):
    date_test.doar_rezervarile([])
    r = ToolWrapper.call(
        "check_availability",
        {"data_start": "2026-10-20", "data_sfarsit": "2026-10-23", "vehicul_id": "AR-001"},
    )
    assert "SUB DURATA MINIMA" in r


def test_documentul_expirat_se_vede_in_disponibilitate(date_test):
    date_test.doar_rezervarile([])
    date_test.mentenanta("GC-002", rca_expira="2026-10-01")
    r = ToolWrapper.call(
        "check_availability",
        {"data_start": "2026-11-02", "data_sfarsit": "2026-11-05", "vehicul_id": "GC-002"},
    )
    assert "DISPONIBILE (1)" in r and "RCA" in r


def test_tariful_lipsa_scoate_vehiculul_din_disponibile(date_test):
    date_test.doar_rezervarile([])
    date_test.vehicul("GC-002", tarife_sezon={"sezon": 182})
    r = ToolWrapper.call(
        "check_availability",
        {"data_start": "2026-11-02", "data_sfarsit": "2026-11-05", "vehicul_id": "GC-002"},
    )
    assert "EROARE DE CONFIGURARE" in r
    assert "DISPONIBILE: niciuna" in r


def test_filtrul_pe_locuri_de_dormit(date_test):
    date_test.doar_rezervarile([])
    r = ToolWrapper.call(
        "check_availability",
        {"data_start": "2026-11-02", "data_sfarsit": "2026-11-05", "locuri_dormit_min": 6},
    )
    assert "AR-002" not in r  # camper van cu 2 locuri


# ---------------------------------------------------------------------
# find_matching_opportunities
# ---------------------------------------------------------------------
def test_recomandarea_pe_nopti_e_ofertabila(date_reale):
    """
    Regresia care a motivat tools/perioada.py: perioada recomandata trebuie
    acceptata de calculate_quote cu exact acele date.
    """
    import re

    r = ToolWrapper.call(
        "find_matching_opportunities",
        {"data_de_la": "2026-09-25", "data_pana_la": "2026-10-10", "durata_zile": 5},
    )
    gasite = re.findall(
        r"(\w+-\d+) - .*?\n\s+Perioada recomandata: (\d{4}-\d\d-\d\d) - (\d{4}-\d\d-\d\d)", r
    )
    assert gasite, f"nicio recomandare in:\n{r}"
    for vehicul, start, sfarsit in gasite:
        deviz = ToolWrapper.call(
            "calculate_quote",
            {"vehicul_id": vehicul, "data_start": start, "data_sfarsit": sfarsit},
        )
        assert "TOTAL DE PLATA" in deviz, f"{vehicul} {start}-{sfarsit}: {deviz[:120]}"


def test_recomandarea_pentru_partener_pe_nopti_spune_nopti(date_reale):
    r = ToolWrapper.call(
        "find_matching_opportunities",
        {"data_de_la": "2026-09-25", "data_pana_la": "2026-10-10", "durata_zile": 5,
         "vehicul_id": "AR-001"},
    )
    assert "nopti)" in r


def test_fara_rezervari_nu_exista_oportunitati(date_test):
    date_test.doar_rezervarile([])
    r = ToolWrapper.call(
        "find_matching_opportunities",
        {"data_de_la": "2026-11-01", "data_pana_la": "2026-11-30"},
    )
    assert "Nu am gasit" in r


def test_tariful_lipsa_opreste_matching_ul(date_test):
    date_test.vehicul("AR-001", tarife_sezon={"extrasezon": 135})
    r = ToolWrapper.call(
        "find_matching_opportunities",
        {"data_de_la": "2026-09-25", "data_pana_la": "2026-10-10", "vehicul_id": "AR-001"},
    )
    assert "EROARE DE CONFIGURARE" in r


# ---------------------------------------------------------------------
# check_fleet_status
# ---------------------------------------------------------------------
def test_documentul_expirat_apare_in_starea_flotei(date_test):
    date_test.mentenanta("GC-002", itp_expira="2020-01-01")
    r = ToolWrapper.call("check_fleet_status", {"vehicul_id": "GC-002"})
    assert "ITP" in r and "EXPIRAT" in r
