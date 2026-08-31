"""Resolving a free-text food name against the MAPO database.

The old `find_food_in_database` took the FIRST substring hit on `food_name`,
which produced confidently wrong answers — "dal" resolved to a sweet semolina
porridge, "poha" to a fried cutlet, "egg" to egg nog, "pav bhaji" to the spice
powder. A nutrition app quoting the wrong food's macros is worse than one that
admits it does not know.

It also never consulted `search_alias` or the local name in brackets, and when
it missed it fell through to a paid LLM lookup. That made a wrong answer and a
billable call the two possible outcomes of a typo.

This module replaces that with ranked matching and an honest failure:

    exact name  >  exact local name  >  whole-word  >  prefix  >  substring

Anything below the confidence floor is reported as unresolved, with spelling
suggestions, instead of being guessed at or sent to an LLM.
"""
from __future__ import annotations

import difflib
import re
from typing import List, Optional, Tuple

from mapo_data import FOOD_DF

_WORD = re.compile(r"[a-z0-9]+")
_VOWELS = set("aeiou")

# Confidence floor. Tiers at or above this are returned; below it, unresolved.
MIN_SCORE = 60


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _local_names(food_name: str, alias: str = "") -> List[str]:
    """Names in brackets plus the CSV's search_alias, split on / and ,."""
    out = []
    for chunk in re.findall(r"\(([^)]*)\)", food_name or ""):
        out += [p.strip() for p in re.split(r"[\/,]", chunk) if p.strip()]
    out += [p.strip() for p in re.split(r"[\/,]", str(alias or "")) if p.strip()]
    return [_norm(x) for x in out if x]


def _base(food_name: str) -> str:
    """The dish name without its bracketed local names."""
    return _norm((food_name or "").split("(")[0])


def looks_like_gibberish(term: str) -> bool:
    """Cheap plausibility check, used only to word the error message.

    Not a security control — rejection is driven by "did it match the database",
    not by this. It exists so "asdfgh" and "chicken tikka masala" get different
    messages.
    """
    t = _norm(term)
    if not t:
        return True
    words = _WORD.findall(t)
    if not words:
        return True
    for w in words:
        if len(w) >= 4:
            if not (_VOWELS & set(w)):
                return True                       # no vowel at all: "xkcdq"
            if re.search(r"[bcdfghjklmnpqrstvwxz]{5,}", w):
                return True                       # 5-consonant run
    if sum(c.isdigit() for c in t) > len(t) / 3:
        return True
    return False


def _score(term: str, base: str, locals_: List[str]) -> int:
    """0-100. Higher is a better match; MIN_SCORE is the acceptance floor."""
    if not term:
        return 0
    if term == base:
        return 100
    if term in locals_:
        # "(paneer)" tacked onto "Fried momos" is a qualifier, not the dish —
        # rank it below the dish's own name so the tie-break can prefer a
        # simpler, more direct match.
        return 90
    # whole-word match inside the dish name — "butter chicken" in
    # "Butter chicken masala", but not "dal" inside "daliya"
    if re.search(r"\b" + re.escape(term) + r"\b", base):
        return 85
    for loc in locals_:
        if re.search(r"\b" + re.escape(term) + r"\b", loc):
            return 80
    if base.startswith(term):
        return 70
    if any(loc.startswith(term) for loc in locals_):
        return 65
    # every word of the query appears somewhere: "aloo paratha" ->
    # "Potato parantha (Aloo ka parantha/paratha)"
    words = _WORD.findall(term)
    if len(words) > 1:
        hay = base + " " + " ".join(locals_)
        if all(re.search(r"\b" + re.escape(w), hay) for w in words):
            return 62
    return 0


_INDEX: Optional[List[tuple]] = None


def _index():
    """(base, local_names, row) for every row, built once."""
    global _INDEX
    if _INDEX is None:
        alias_col = "search_alias" if "search_alias" in FOOD_DF.columns else None
        _INDEX = [
            (_base(r["food_name"]),
             _local_names(r["food_name"], r[alias_col] if alias_col else ""),
             r)
            for _, r in FOOD_DF.iterrows()
        ]
    return _INDEX


def resolve(term: str) -> Tuple[Optional[dict], int]:
    """Best row for `term`, or (None, 0) if nothing clears the floor.

    Ties are broken by the shortest dish name. Without that, "paneer" matches
    the bracketed qualifier in "Fried momos (paneer)" just as strongly as it
    matches a plain paneer dish, and row order decides — which is how the old
    lookup ended up recommending momos to someone who said paneer. The simplest
    name that matches is almost always the dish the person meant.
    """
    t = _norm(term)
    if len(t) < 2:
        return None, 0
    best, best_score, best_len = None, 0, 10 ** 6
    for base, locals_, row in _index():
        s = _score(t, base, locals_)
        if s < MIN_SCORE:
            continue
        if s > best_score or (s == best_score and len(base) < best_len):
            best, best_score, best_len = row, s, len(base)
            if s == 100 and base == t:
                break
    if best is None:
        return None, 0
    return best, best_score


def suggest(term: str, limit: int = 3) -> List[str]:
    """'Did you mean...' — close spellings of real dishes.

    Matching is done per WORD, not per full name. Comparing "panner" against
    "Paneer soup" as whole strings scores badly and returns nothing, which is
    exactly the moment a user needs the help; comparing it against the word
    "paneer" scores 0.83 and lands.
    """
    t = _norm(term)
    if len(t) < 3:
        return []

    full_names, vocab = {}, {}
    for base, locals_, row in _index():
        display = row["food_name"].split("(")[0].strip()
        if base not in full_names or len(display) < len(full_names[base]):
            full_names[base] = display
        for phrase in [base] + locals_:
            for w in _WORD.findall(phrase):
                if len(w) >= 4 and (w not in vocab or len(display) < len(vocab[w])):
                    vocab[w] = display

    out, seen = [], set()

    def add(name):
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)

    # whole-name matches first — they are the most confident
    for h in difflib.get_close_matches(t, list(full_names), n=limit, cutoff=0.72):
        add(full_names[h])

    # then per-word, which is what catches ordinary typos
    if len(out) < limit:
        for word in _WORD.findall(t):
            if len(word) < 4:
                continue
            for h in difflib.get_close_matches(word, list(vocab), n=limit, cutoff=0.75):
                add(vocab[h])
                if len(out) >= limit:
                    break
            if len(out) >= limit:
                break

    return out[:limit]


# --------------------------------------------------------------------------
# Favourite foods
# --------------------------------------------------------------------------
class UnknownFoodError(Exception):
    """Raised when a favourite food cannot be resolved from the database.

    The old behaviour on a miss was to call a paid LLM and, failing that,
    silently insert a zero-calorie "Not Found" row into the user's plan. Both
    are worse than saying so: one bills you for a typo, the other quietly puts
    a wrong number in a nutrition plan.
    """

    def __init__(self, unresolved):
        self.unresolved = unresolved
        names = ", ".join(u["input"] for u in unresolved)
        super().__init__(f"Unrecognised food(s): {names}")

    def as_detail(self):
        """Shape returned to the client in a 422."""
        return {
            "error": "unknown_food",
            "message": ("We could not find these in the food database. "
                        "Check the spelling, or try a simpler name."),
            "unresolved": self.unresolved,
        }


def resolve_favourites(names, max_items: int = 10):
    """Resolve every favourite, or raise UnknownFoodError listing the failures.

    Nothing here calls out to a network. A name either matches the database
    with enough confidence to be trusted, or it is reported back to the user.
    """
    resolved, unresolved = [], []

    for raw in list(names or [])[:max_items]:
        term = _norm(raw)
        if not term:
            continue
        row, score = resolve(term)
        if row is not None:
            resolved.append({
                "input": str(raw),
                "name": row["food_name"],
                "serving": str(row["servings_unit"]),
                "energy": round(float(row["serv_energy"]), 1),
                "protein": round(float(row["serv_protein"]), 1),
                "carbs": round(float(row["serv_carb"]), 1),
                "fat": round(float(row["serv_fat"]), 1),
                "source": "MAPO food database",
                "match_score": score,
            })
        else:
            unresolved.append({
                "input": str(raw),
                "reason": ("That does not look like a food name."
                           if looks_like_gibberish(raw)
                           else "Not in the food database yet."),
                "suggestions": suggest(raw),
            })

    if unresolved:
        raise UnknownFoodError(unresolved)
    return resolved
