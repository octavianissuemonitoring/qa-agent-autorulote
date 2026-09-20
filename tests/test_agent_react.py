"""
Bucla ReAct, cu un model FALS.

De ce fals: un test nu are voie sa depinda de reteaua Google, de costuri sau de
ce raspunde modelul azi. LLMFals imita exact cat ne trebuie - un obiect cu
.invoke(mesaje) care intoarce un AIMessage, eventual cu tool_calls.

Se verifica cele patru plase de siguranta din S6.7 (runde, buget de tokeni,
timeout, circuit breaker), executia in paralel din S6.5 si mentiunea pe care
o primeste clientul cand tura se opreste la o limita.
"""

import time

import pytest
from langchain_core.messages import AIMessage

import config
from agent import QAAgent, execute_all_tools, execute_tool
from tools import ToolWrapper

UZ = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


class LLMFals:
    """Modelul de test: cere pe rand ce i se spune, apoi da un raspuns final."""

    def __init__(self, cereri: list[list[dict]] | None = None, final: str = "Raspuns final."):
        self.cereri = list(cereri or [])
        self.final = final
        self.apeluri = 0

    def invoke(self, mesaje):
        self.apeluri += 1
        if self.cereri:
            return AIMessage(content="", tool_calls=self.cereri.pop(0), usage_metadata=UZ)
        return AIMessage(content=self.final, usage_metadata=UZ)


class LLMInsistent(LLMFals):
    """Cere la nesfarsit acelasi tool, cu parametri usor diferiti."""

    def __init__(self, nume="check_availability", identici=False):
        super().__init__()
        self.nume = nume
        self.identici = identici

    def invoke(self, mesaje):
        self.apeluri += 1
        zi = 10 if self.identici else 10 + self.apeluri
        return AIMessage(
            content="",
            tool_calls=[{"name": self.nume, "args": {"data_start": f"2026-10-{zi:02d}"},
                         "id": f"c{self.apeluri}"}],
            usage_metadata=UZ,
        )


def agent_cu(llm_cu_unelte, llm_final=None) -> QAAgent:
    ag = QAAgent(verbose=False)
    ag.llm_cu_unelte = llm_cu_unelte
    ag.llm = llm_final or LLMFals(final="Raspuns final formulat fara unelte.")
    return ag


@pytest.fixture(autouse=True)
def unelte_de_test(monkeypatch):
    """Uneltele reale nu ne intereseaza aici; le inlocuim cu una previzibila."""
    monkeypatch.setattr(ToolWrapper, "call", staticmethod(lambda n, a: f"rezultat {n}"))


# ---------------------------------------------------------------------
# Traseul normal
# ---------------------------------------------------------------------
def test_fara_cereri_de_unelte_raspunde_direct():
    ag = agent_cu(LLMFals(final="Buna ziua!"))
    assert ag.react_loop("salut") == "Buna ziua!"


def test_o_runda_cu_o_unealta():
    llm = LLMFals([[{"name": "get_current_datetime", "args": {}, "id": "c1"}]])
    ag = agent_cu(llm)
    assert ag.react_loop("ce ora e?") == "Raspuns final."
    assert llm.apeluri == 2  # o runda cu unealta + raspunsul final


def test_rezultatul_uneltei_ajunge_inapoi_la_model(monkeypatch):
    vazute = []

    class LLMCareVede(LLMFals):
        def invoke(self, mesaje):
            vazute.append([type(m).__name__ for m in mesaje])
            return super().invoke(mesaje)

    ag = agent_cu(LLMCareVede([[{"name": "get_current_datetime", "args": {}, "id": "c1"}]]))
    ag.react_loop("ce ora e?")
    assert "ToolMessage" in vazute[-1]


def test_istoricul_retine_intrebarea_si_raspunsul():
    ag = agent_cu(LLMFals(final="Buna!"))
    ag.react_loop("salut")
    assert len(ag.istoric) == 2


def test_statisticile_numara_rundele_si_uneltele():
    llm = LLMFals([[{"name": "a", "args": {}, "id": "c1"}, {"name": "b", "args": {}, "id": "c2"}]])
    ag = agent_cu(llm)
    ag.react_loop("test")
    assert ag._statistici["apeluri_unelte"] == 2


def test_tokenii_se_aduna_pe_tura():
    ag = agent_cu(LLMFals([[{"name": "a", "args": {}, "id": "c1"}]]))
    ag.react_loop("test")
    assert ag._tokeni["tokeni_intrare"] == 200  # doua apeluri la model


# ---------------------------------------------------------------------
# S6.5 - executie in paralel
# ---------------------------------------------------------------------
def test_uneltele_unei_runde_ruleaza_in_paralel(monkeypatch):
    monkeypatch.setattr(ToolWrapper, "call", staticmethod(lambda n, a: (time.sleep(0.4), n)[1]))
    cereri = [{"name": f"t{i}", "args": {}, "id": f"c{i}"} for i in range(3)]
    start = time.time()
    rezultate = execute_all_tools_sync(cereri)
    durata = time.time() - start
    assert len(rezultate) == 3
    assert durata < 0.9, f"par sa fi rulat pe rand: {durata:.2f}s"


def test_rezultatele_pastreaza_ordinea_cererilor(monkeypatch):
    intarzieri = {"lent": 0.3, "rapid": 0.0}
    monkeypatch.setattr(
        ToolWrapper, "call", staticmethod(lambda n, a: (time.sleep(intarzieri[n]), n)[1])
    )
    rezultate = execute_all_tools_sync(
        [{"name": "lent", "args": {}, "id": "a"}, {"name": "rapid", "args": {}, "id": "b"}]
    )
    assert [r["tool_call_id"] for r in rezultate] == ["a", "b"]


def test_execute_tool_deleaga_la_wrapper():
    assert execute_tool({"name": "get_current_datetime", "args": {}}) == "rezultat get_current_datetime"


# ---------------------------------------------------------------------
# S6.7 - timeout per tool
# ---------------------------------------------------------------------
def test_unealta_lenta_e_abandonata(monkeypatch):
    monkeypatch.setattr(config, "TOOL_TIMEOUT", 0.3)
    monkeypatch.setattr(ToolWrapper, "call", staticmethod(lambda n, a: (time.sleep(30), n)[1]))
    start = time.time()
    rezultate = execute_all_tools_sync([{"name": "lent", "args": {}, "id": "a"}])
    assert "nu a raspuns in" in rezultate[0]["content"]
    assert time.time() - start < 2


def test_o_unealta_blocata_nu_le_opreste_pe_celelalte(monkeypatch):
    monkeypatch.setattr(config, "TOOL_TIMEOUT", 0.3)
    intarzieri = {"lent": 30, "rapid": 0.0}
    monkeypatch.setattr(
        ToolWrapper, "call", staticmethod(lambda n, a: (time.sleep(intarzieri[n]), f"ok {n}")[1])
    )
    rezultate = execute_all_tools_sync(
        [{"name": "lent", "args": {}, "id": "a"}, {"name": "rapid", "args": {}, "id": "b"}]
    )
    assert "EROARE" in rezultate[0]["content"]
    assert rezultate[1]["content"] == "ok rapid"


# ---------------------------------------------------------------------
# S6.7 - repetari, circuit breaker, runde, buget
# ---------------------------------------------------------------------
def test_apelul_identic_repetat_nu_se_mai_executa(monkeypatch):
    executii = []
    monkeypatch.setattr(
        ToolWrapper, "call", staticmethod(lambda n, a: (executii.append(n), "ok")[1])
    )
    ag = agent_cu(LLMInsistent(identici=True))
    ag.react_loop("test")
    assert len(executii) == 1


def test_repetarea_duce_la_raspuns_final():
    ag = agent_cu(LLMInsistent(identici=True))
    assert "Raspuns final formulat fara unelte." in ag.react_loop("test")


def test_circuit_breaker_opreste_unealta_care_esueaza(monkeypatch):
    monkeypatch.setattr(config, "TOOL_MAX_ERORI", 2)
    executii = []
    monkeypatch.setattr(
        ToolWrapper,
        "call",
        staticmethod(lambda n, a: (executii.append(n), "EROARE: baza de date nu raspunde")[1]),
    )
    ag = agent_cu(LLMInsistent())
    ag.react_loop("test")
    assert len(executii) == 2, "unealta a fost apelata si dupa prag"


def test_circuit_breaker_duce_la_raspuns_final(monkeypatch):
    monkeypatch.setattr(config, "TOOL_MAX_ERORI", 2)
    monkeypatch.setattr(ToolWrapper, "call", staticmethod(lambda n, a: "EROARE: cade"))
    ag = agent_cu(LLMInsistent())
    raspuns = ag.react_loop("test")
    assert "Raspuns final formulat fara unelte." in raspuns
    assert ag._statistici["runde"] < config.MAX_ITERATIONS


def test_bugetul_de_tokeni_opreste_tura(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOKENS_TURA", 300)
    ag = agent_cu(LLMInsistent())
    ag.react_loop("test")
    assert ag._statistici["runde"] <= 3


def test_limita_de_runde_e_respectata(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOKENS_TURA", 10**9)
    monkeypatch.setattr(config, "TOOL_MAX_ERORI", 10**9)
    ag = agent_cu(LLMInsistent())
    ag.max_iteratii = 3
    ag.react_loop("test")
    assert ag._statistici["runde"] == 3


# ---------------------------------------------------------------------
# Ce primeste clientul cand tura s-a oprit la o limita
# ---------------------------------------------------------------------
def test_raspunsul_dupa_limita_are_mentiunea_pentru_client(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOKENS_TURA", 300)
    ag = agent_cu(LLMInsistent())
    raspuns = ag.react_loop("test")
    assert "Mențiune" in raspuns


def test_raspunsul_normal_nu_are_mentiunea():
    ag = agent_cu(LLMFals(final="Buna ziua!"))
    assert "Mențiune" not in ag.react_loop("salut")


def test_mentiunea_nu_vorbeste_despre_tokeni_sau_unelte(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOKENS_TURA", 300)
    ag = agent_cu(LLMInsistent())
    raspuns = ag.react_loop("test").lower()
    for cuvant in ("token", "unealta", "runda", "eroare"):
        assert cuvant not in raspuns.split("mențiune")[-1]


def test_raspunsul_gol_e_inlocuit_cu_textul_de_rezerva(monkeypatch):
    """Modelele care 'gandesc' pot consuma tot MAX_TOKENS pe rationament."""
    monkeypatch.setattr(config, "MAX_TOKENS_TURA", 300)
    ag = agent_cu(LLMInsistent(), llm_final=LLMFals(final=""))
    # Textul din YAML e scris pe mai multe randuri, deci comparam pe cuvinte.
    raspuns = " ".join(ag.react_loop("test").split())
    assert "nu am reușit să duc verificarea până la capăt" in raspuns


def test_clientul_primeste_raspuns_si_la_epuizarea_rundelor(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOKENS_TURA", 10**9)
    monkeypatch.setattr(config, "TOOL_MAX_ERORI", 10**9)
    ag = agent_cu(LLMInsistent())
    ag.max_iteratii = 2
    raspuns = ag.react_loop("test")
    assert "Raspuns final formulat fara unelte." in raspuns


# ---------------------------------------------------------------------
# Ajutor: rulam bucla asincrona dintr-un test sincron
# ---------------------------------------------------------------------
def execute_all_tools_sync(cereri: list[dict]) -> list[dict]:
    import asyncio

    return asyncio.run(execute_all_tools(cereri))
