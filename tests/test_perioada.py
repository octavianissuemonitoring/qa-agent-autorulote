"""
Perioada de inchiriere: zile vs nopti.

Aici se testeaza exact bug-ul care a motivat tools/perioada.py: matching
recomanda "5 zile" pentru un partener care factureaza nopti, iar ofertarea
citea aceeasi perioada ca 4 nopti si o refuza.
"""

from tools.perioada import PerioadaInchiriere

from conftest import zi


# ---------------------------------------------------------------------
# din_date: datele cerute de client -> cate unitati se factureaza
# ---------------------------------------------------------------------
def test_zile_numara_si_ziua_predarii(partener_zile):
    p = PerioadaInchiriere.din_date(partener_zile, zi("2026-10-13"), zi("2026-10-20"))
    assert p.unitati == 8
    assert p.eticheta == "zile"


def test_nopti_nu_numara_ziua_predarii(partener_nopti):
    p = PerioadaInchiriere.din_date(partener_nopti, zi("2026-10-13"), zi("2026-10-20"))
    assert p.unitati == 7
    assert p.eticheta == "nopti"


def test_o_singura_zi_inseamna_o_zi_dar_zero_nopti(partener_zile, partener_nopti):
    o_zi = (zi("2026-10-13"), zi("2026-10-13"))
    assert PerioadaInchiriere.din_date(partener_zile, *o_zi).unitati == 1
    assert PerioadaInchiriere.din_date(partener_nopti, *o_zi).unitati == 0


def test_perioada_inversata_nu_da_unitati_negative(partener_zile, partener_nopti):
    inversat = (zi("2026-10-20"), zi("2026-10-13"))
    assert PerioadaInchiriere.din_date(partener_zile, *inversat).unitati == 0
    assert PerioadaInchiriere.din_date(partener_nopti, *inversat).unitati == 0


# ---------------------------------------------------------------------
# din_unitati: durata dorita -> ce zi e predarea (bug-ul reparat)
# ---------------------------------------------------------------------
def test_cinci_zile_se_termina_a_cincea_zi(partener_zile):
    p = PerioadaInchiriere.din_unitati(partener_zile, zi("2026-09-29"), 5)
    assert p.predare == zi("2026-10-03")
    assert p.unitati == 5


def test_cinci_nopti_se_termina_a_sasea_zi(partener_nopti):
    p = PerioadaInchiriere.din_unitati(partener_nopti, zi("2026-09-29"), 5)
    assert p.predare == zi("2026-10-04")
    assert p.unitati == 5


def test_dus_intors_da_aceeasi_perioada(partener_nopti):
    """din_unitati si din_date trebuie sa fie inversul una alteia."""
    dus = PerioadaInchiriere.din_unitati(partener_nopti, zi("2026-09-29"), 5)
    intors = PerioadaInchiriere.din_date(partener_nopti, dus.preluare, dus.predare)
    assert intors.unitati == 5


def test_dus_intors_da_aceeasi_perioada_si_pe_zile(partener_zile):
    dus = PerioadaInchiriere.din_unitati(partener_zile, zi("2026-09-29"), 5)
    intors = PerioadaInchiriere.din_date(partener_zile, dus.preluare, dus.predare)
    assert intors.unitati == 5


# ---------------------------------------------------------------------
# Cele doua feluri de zile
# ---------------------------------------------------------------------
def test_pe_nopti_ziua_predarii_nu_se_factureaza(partener_nopti):
    p = PerioadaInchiriere.din_date(partener_nopti, zi("2026-10-13"), zi("2026-10-16"))
    assert p.zile_facturate == [zi("2026-10-13"), zi("2026-10-14"), zi("2026-10-15")]
    assert p.predare not in p.zile_facturate


def test_pe_nopti_ziua_predarii_ocupa_totusi_vehiculul(partener_nopti):
    p = PerioadaInchiriere.din_date(partener_nopti, zi("2026-10-13"), zi("2026-10-16"))
    assert p.predare in p.zile_ocupate
    assert len(p.zile_ocupate) == len(p.zile_facturate) + 1


def test_pe_zile_facturate_si_ocupate_coincid(partener_zile):
    p = PerioadaInchiriere.din_date(partener_zile, zi("2026-10-13"), zi("2026-10-16"))
    assert p.zile_facturate == p.zile_ocupate


# ---------------------------------------------------------------------
# Treceri peste luna si peste an
# ---------------------------------------------------------------------
def test_trecerea_peste_an(partener_zile):
    p = PerioadaInchiriere.din_date(partener_zile, zi("2026-12-29"), zi("2027-01-03"))
    assert p.unitati == 6
    assert p.zile_facturate[-1] == zi("2027-01-03")


def test_trecerea_peste_an_din_unitati(partener_nopti):
    p = PerioadaInchiriere.din_unitati(partener_nopti, zi("2026-12-30"), 5)
    assert p.predare == zi("2027-01-04")


def test_an_bisect(partener_zile):
    """2028 e bisect: 28 feb + 2 zile = 1 martie, nu 29 februarie sarita."""
    p = PerioadaInchiriere.din_unitati(partener_zile, zi("2028-02-28"), 3)
    assert p.predare == zi("2028-03-01")
    assert zi("2028-02-29") in p.zile_facturate


# ---------------------------------------------------------------------
# Cum o numim in fata clientului
# ---------------------------------------------------------------------
def test_descrierea_spune_nopti_pentru_partenerul_pe_nopti(partener_nopti):
    p = PerioadaInchiriere.din_unitati(partener_nopti, zi("2026-09-29"), 5)
    assert p.descriere == "2026-09-29 - 2026-10-04 (5 nopti)"


def test_descrierea_spune_zile_pentru_partenerul_pe_zile(partener_zile):
    p = PerioadaInchiriere.din_unitati(partener_zile, zi("2026-09-29"), 5)
    assert p.descriere == "2026-09-29 - 2026-10-03 (5 zile)"


def test_unitatea_la_singular(partener_nopti, partener_zile):
    o_zi = (zi("2026-10-13"), zi("2026-10-14"))
    assert PerioadaInchiriere.din_date(partener_nopti, *o_zi).unitate_singular == "noapte"
    assert PerioadaInchiriere.din_date(partener_zile, *o_zi).unitate_singular == "zi"
