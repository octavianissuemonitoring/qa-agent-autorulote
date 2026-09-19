"""
Pachetul prompts.

Restul aplicatiei scrie doar:
    from prompts import get_prompt_registry

Spre deosebire de tools/__init__.py, aici nu e nevoie sa importam nimic ca sa
"aprindem" ceva: prompturile nu sunt cod, sunt fisiere .yaml pe care registry-ul
le descopera singur scanand folderul.
"""

from prompts.registry import (
    PromptRegistry,
    PromptTemplate,
    PromptVariable,
    get_prompt_registry,
)

__all__ = [
    "PromptRegistry",
    "PromptTemplate",
    "PromptVariable",
    "get_prompt_registry",
]
