"""
Verificare LangSmith, cap-coada - NU face parte din tema.

Ce face, in ordine:
  [1] citeste configuratia din .env
  [2] verifica daca cheia e acceptata de serverul LangSmith
  [3] pune agentului o intrebare reala (care foloseste unelte)
  [4] descarca inapoi trace-ul din LangSmith si il afiseaza ca arbore

Pasul 4 e dovada: nu presupunem ca a mers, citim ce a ajuns efectiv pe server.

Rulare:
    .venv\\Scripts\\python.exe verifica_langsmith.py
"""

import sys
import time

import config

config.pregateste_consola()

INTREBARE = "Cat costa GC-001 intre 13 si 20 octombrie 2026, cu un gratar?"


def pas(numar: int, titlu: str) -> None:
    print(f"\n[{numar}] {titlu}")


print("=" * 64)
print("VERIFICARE LANGSMITH")
print("=" * 64)

# ---------------------------------------------------------------------
pas(1, "Configuratie")
print("    " + config.descrie().replace("\n", "\n    "))

if not config.LANGCHAIN_TRACING:
    print("\n    Tracing-ul e OPRIT. In .env pune LANGCHAIN_TRACING_V2=true.")
    sys.exit(1)
probleme = config.verifica()
if probleme:
    for p in probleme:
        print(f"    X {p}")
    sys.exit(1)

# ---------------------------------------------------------------------
pas(2, "Autentificare la LangSmith")
from langsmith import Client  # noqa: E402

client = Client(api_url=config.LANGSMITH_ENDPOINT, api_key=config.LANGSMITH_API_KEY)
try:
    next(iter(client.list_projects(limit=1)), None)
    print(f"    OK - cheia e acceptata de {config.LANGSMITH_ENDPOINT}")
except Exception as e:
    mesaj = str(e)
    print(f"    X Serverul a refuzat conexiunea: {type(e).__name__}")
    if "401" in mesaj or "403" in mesaj or "Unauthorized" in mesaj:
        print(
            "      Cheie respinsa. Cele doua cauze frecvente:\n"
            "        - cheia a fost copiata incomplet (verifica sa nu lipseasca caractere)\n"
            "        - contul e in regiunea UE, dar LANGCHAIN_ENDPOINT arata spre SUA\n"
            "          (pentru UE: https://eu.api.smith.langchain.com)"
        )
    else:
        print(f"      {mesaj[:300]}")
    sys.exit(1)

# ---------------------------------------------------------------------
pas(3, "Intrebare reala catre agent")
print(f"    CLIENT: {INTREBARE}")
from agent import QAAgent  # noqa: E402

agent = QAAgent()
start = time.time()
raspuns = agent.react_loop(INTREBARE)
print(f"    AGENT ({time.time() - start:.1f}s): {raspuns[:160].replace(chr(10), ' ')}...")

# Trace-urile pleaca spre server in fundal, ca sa nu incetineasca agentul.
# Inainte sa le citim inapoi, asteptam sa se goleasca coada de trimitere.
from langchain_core.tracers.langchain import wait_for_all_tracers  # noqa: E402

wait_for_all_tracers()
client.flush()

# ---------------------------------------------------------------------
pas(4, "Ce a ajuns efectiv in LangSmith")

import warnings  # noqa: E402

# list_runs() e marcata "deprecated" (va fi scoasa in 2027), dar e inca cea
# mai simpla cale sincrona. O folosim si ascundem avertismentul.
warnings.filterwarnings("ignore", message=".*is deprecated and will be removed.*")

# Agentul a retinut ID-ul trace-ului -> il cerem direct, fara filtre.
# Serverul are nevoie de cateva secunde sa indexeze, de aici reincercarile.
radacina = None
toate: list = []
for incercare in range(15):
    try:
        radacina = client.read_run(agent.ultimul_run_id)
        toate = list(
            client.list_runs(project_name=config.LANGCHAIN_PROJECT, trace_id=radacina.trace_id)
        )
        if len(toate) > 1 and radacina.end_time:  # radacina + cel putin un pas interior
            break
    except Exception:
        pass
    time.sleep(2)

if radacina is None:
    print("    X Trace-ul nu a aparut pe server dupa 30 de secunde.")
    print("      Verifica in interfata, poate dura mai mult la prima rulare.")
    sys.exit(1)

toate.sort(key=lambda r: r.start_time)

copii: dict = {}
for r in toate:
    copii.setdefault(r.parent_run_id, []).append(r)


def durata(r) -> str:
    if r.end_time and r.start_time:
        return f"{(r.end_time - r.start_time).total_seconds():.2f}s"
    return "?"


def afiseaza(r, nivel: int = 0) -> None:
    tokeni = f" | {r.total_tokens} tokeni" if getattr(r, "total_tokens", None) else ""
    stare = " | EROARE" if r.error else ""
    print(f"    {'   ' * nivel}{r.run_type.upper():6} {r.name:32} {durata(r):>7}{tokeni}{stare}")
    for copil in copii.get(r.id, []):
        afiseaza(copil, nivel + 1)


afiseaza(radacina)

meta = (radacina.extra or {}).get("metadata", {})
print(
    f"\n    Metadata: model={meta.get('model')} | "
    f"prompt system v{meta.get('prompt_system_versiune')} | "
    f"thread={str(meta.get('thread_id'))[:8]}..."
)

try:
    print(f"\n    Deschide in browser:\n    {client.get_run_url(run=radacina, project_name=config.LANGCHAIN_PROJECT)}")
except Exception:
    print(f"\n    Deschide proiectul '{config.LANGCHAIN_PROJECT}' in LangSmith.")

print("\n" + "=" * 64)
print("LANGSMITH FUNCTIONEAZA")
print("=" * 64)
