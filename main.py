"""
Interfata de linie de comanda a agentului QA.

Rulare:
    .venv\\Scripts\\python.exe main.py
    .venv\\Scripts\\python.exe main.py --verbose     (arata GANDESTE/ACTIONEAZA/OBSERVA)
    .venv\\Scripts\\python.exe main.py --model gemini-3.8-flash
"""

import argparse
import sys

import config
import modele
from agent import QAAgent
from prompts import get_prompt_registry
from tools import ToolWrapper, datastore

AJUTOR = """
Comenzi disponibile:
  /help              lista asta
  /tools             uneltele inregistrate, cu descrierea lor
  /prompts           prompturile din registry, cu versiunea lor
  /config            configuratia activa
  /history           conversatia de pana acum
  /reset             sterge istoricul conversatiei
  /verbose           porneste/opreste afisarea rationamentului
  /modele            modelele definite in .env: active, inactive, pret
  /model <nume|nr>   comuta pe alt model ACTIV, pastrand conversatia
  /reload            reciteste prompturile .yaml si datele .json de pe disc
  /trace             link LangSmith catre ultimul raspuns (daca tracing-ul e pornit)
  /quit              iesire
"""


def comanda(agent: QAAgent, linie: str) -> bool:
    """Trateaza o comanda care incepe cu '/'. Returneaza False la iesire."""
    parti = linie.split()
    cmd = parti[0].lower()

    if cmd in ("/quit", "/exit", "/q"):
        return False

    if cmd == "/help":
        print(AJUTOR)

    elif cmd == "/tools":
        print(f"\n{len(ToolWrapper.nume_tooluri())} unelte inregistrate:\n")
        print(ToolWrapper.rezumat())
        print()

    elif cmd == "/prompts":
        print()
        for t in get_prompt_registry().list_templates():
            print(f"  {t['nume']:20} v{t['versiune']:8} {t['fisier']}")
            print(f"    {t['descriere'].strip()}")
            print(f"    variabile: {t['variabile']}")
        print()

    elif cmd == "/config":
        print(f"\n{config.descrie(agent.model_ai)}\n")

    elif cmd == "/modele":
        print("\n  Nr  Stare     Model                                  $ intrare / iesire (per 1M)")
        for i, m in enumerate(modele.catalog(), start=1):
            stare = "ACTIV   " if m.activ else "inactiv "
            curent = "  <- in uz" if m.id == agent.model_ai.id else ""
            if m.provider == "ollama":
                pret = "gratuit (local)"
            elif m.pret:
                pret = f"{m.pret[0]:.2f} / {m.pret[1]:.2f}"
            else:
                pret = "necunoscut"
            print(f"  {i:>2}  {stare}  {m.id:38} {pret}{curent}")
        print("\n  Comuti cu /model <nr sau nume>. Activezi/dezactivezi din .env (MODELE_ACTIVE).\n")

    elif cmd == "/history":
        istoric = agent.get_history()
        if not istoric:
            print("\n  (istoricul e gol)\n")
        else:
            print()
            for m in istoric:
                print(f"  {m['rol']:10} {m['continut'][:200]}")
            print()

    elif cmd == "/reset":
        agent.clear_history()
        print("\n  Istoric sters.\n")

    elif cmd == "/verbose":
        agent.verbose = not agent.verbose
        print(f"\n  Afisarea rationamentului: {'PORNITA' if agent.verbose else 'OPRITA'}\n")

    elif cmd == "/model":
        if len(parti) < 2:
            print(f"\n  In uz: {agent.model_ai.id}. Foloseste: /model <nr sau nume> (vezi /modele)\n")
        else:
            try:
                nou = agent.schimba_model(parti[1])
                print(f"\n  Model comutat pe: {nou.id}. Conversatia continua neintrerupt.\n")
            except ValueError as e:
                print(f"\n  {e}\n")

    elif cmd == "/trace":
        if not config.LANGCHAIN_TRACING:
            print("\n  LangSmith e oprit. In .env: LANGCHAIN_TRACING_V2=true\n")
        elif not agent.ultimul_run_id:
            print("\n  Inca nu exista niciun raspuns de urmarit.\n")
        else:
            import warnings
            from langsmith import Client

            warnings.filterwarnings("ignore", message=".*is deprecated and will be removed.*")
            client = Client(api_url=config.LANGSMITH_ENDPOINT, api_key=config.LANGSMITH_API_KEY)
            try:
                run = client.read_run(agent.ultimul_run_id)
                url = client.get_run_url(run=run, project_name=config.LANGCHAIN_PROJECT)
                print(f"\n  {url}\n")
            except Exception:
                print("\n  Trace-ul nu e inca indexat pe server. Mai incearca in cateva secunde.\n")

    elif cmd == "/reload":
        n = get_prompt_registry().reload()
        datastore.reincarca()
        print(f"\n  Reincarcate: {n} prompturi + datele din data/")
        for problema in datastore.valideaza_configurarea():
            print(f"  PROBLEMA DE CONFIGURARE: {problema}")
        print()

    else:
        print(f"\n  Comanda necunoscuta: {cmd}. Scrie /help.\n")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent QA - inchiriere autorulote")
    parser.add_argument("--verbose", action="store_true", help="arata rationamentul agentului")
    parser.add_argument("--model", help="porneste pe un anume model activ (nume sau numar din /modele)")
    argumente = parser.parse_args()

    config.pregateste_consola()

    probleme = config.verifica()
    if probleme:
        print("Configuratie invalida:")
        for p in probleme:
            print(f"  - {p}")
        return 1

    print("=" * 62)
    print(f"  {config.NUME_AGENT} - asistent inchirieri autorulote {config.NUME_COMPANIE}")
    print("=" * 62)
    print(config.descrie())
    print(f"{len(ToolWrapper.nume_tooluri())} unelte | scrie /help pentru comenzi, /quit pentru iesire")
    print("=" * 62)

    # Integritatea datelor se verifica la FIECARE pornire, nu cand isi aminteste
    # cineva. Nu oprim agentul: cele mai multe probleme afecteaza un singur
    # vehicul, iar restul flotei ramane ofertabil.
    for problema in datastore.valideaza_configurarea():
        print(f"  PROBLEMA DE CONFIGURARE: {problema}")

    try:
        agent = QAAgent(model=argumente.model, verbose=argumente.verbose)
    except Exception as e:
        print(f"\nNu am putut porni agentul: {type(e).__name__}: {e}")
        return 1

    while True:
        try:
            linie = input("\nTu > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not linie:
            continue
        if linie.startswith("/"):
            if not comanda(agent, linie):
                break
            continue

        print()
        try:
            raspuns = agent.react_loop(linie)
        except Exception as e:
            # Agentul nu are voie sa moara dintr-o eroare de retea sau de model.
            print(f"\n{config.NUME_AGENT} > A aparut o problema tehnica: {type(e).__name__}: {e}")
            continue

        print(f"\n{config.NUME_AGENT} > {raspuns}")

    print("\nLa revedere.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
