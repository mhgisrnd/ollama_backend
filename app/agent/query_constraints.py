"""Enforce explicit scope constraints before model plans can be executed."""
import re

from app.agent.query_engine import Query


_ANY_VISIBILITY = re.compile(
    r"표시\s*여부(?:는|가|와|에)?\s*(?:상관\s*없|관계\s*없|무관)"
    r"|표시\s*여부(?:와|에)\s*(?:관계|상관)\s*없이",
    re.IGNORECASE,
)


def enforce_explicit_scope(query: Query, request: str) -> Query:
    if not _ANY_VISIBILITY.search(request):
        return query
    # No visibility predicate is equivalent to including both shown and hidden
    # layers. Neither != true nor != false means "ignore visibility".
    return query.model_copy(update={
        "where": [predicate for predicate in query.where if predicate.field != "visible"],
    })
