"""
Pachetul tools.

Rolul acestui fisier (slide S7.9: "__init__.py exporta ToolWrapper"):

  1. Importa FIECARE modul de tool. Fara importul asta, decoratorul
     @register_tool nu ruleaza niciodata si TOOL_REGISTRY ramane gol.
     Un tool care nu e importat aici, pentru agent nu exista.

  2. Expune ToolWrapper, ca restul aplicatiei sa scrie doar:
         from tools import ToolWrapper

Cand adaugi un tool nou: creezi fisierul si adaugi o linie in blocul
de mai jos. Singurul loc care se atinge.
"""

from tools.wrapper import ToolWrapper

# --- Importurile care "aprind" tool-urile ---------------------------
# noqa: F401 = spune uneltelor de verificare "da, stiu ca nu folosesc
# numele importat; il import pentru efectul secundar al decoratorului".
from tools import calculator  # noqa: F401
from tools import datetime_tool  # noqa: F401
from tools import vehicul  # noqa: F401
from tools import disponibilitate  # noqa: F401
from tools import mentenanta  # noqa: F401
from tools import ofertare  # noqa: F401
from tools import matching  # noqa: F401

__all__ = ["ToolWrapper"]
