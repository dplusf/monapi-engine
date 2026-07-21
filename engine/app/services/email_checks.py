"""Signal helpers for the email check: role accounts and typo domains.

No network access here — reputation and MX lookups live in the endpoint.
"""
from __future__ import annotations

ROLE_LOCAL_PARTS = {
    "abuse", "admin", "administrator", "billing", "buchhaltung", "career",
    "contact", "hallo", "hello", "help", "hilfe", "hostmaster", "hr",
    "info", "jobs", "kontakt", "mail", "marketing", "media", "newsletter",
    "no-reply", "noreply", "office", "postmaster", "presse", "press",
    "sales", "service", "support", "team", "vertrieb", "webmaster", "welcome",
}

# Popular mailbox providers used for typo detection ("gamil.com" -> "gmail.com").
POPULAR_DOMAINS = {
    "gmail.com", "googlemail.com", "gmx.de", "gmx.net", "web.de", "t-online.de",
    "outlook.com", "hotmail.com", "hotmail.de", "live.com", "msn.com",
    "yahoo.com", "yahoo.de", "icloud.com", "me.com", "mac.com", "aol.com",
    "proton.me", "protonmail.com", "online.de", "freenet.de", "arcor.de",
    "mailbox.org", "posteo.de",
}


def is_role_account(local_part: str) -> bool:
    return local_part.strip().lower() in ROLE_LOCAL_PARTS


def _one_edit_away(a: str, b: str) -> bool:
    """True if a can be turned into b with at most one insertion,
    deletion, substitution or adjacent transposition."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diffs = [i for i in range(la) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        # adjacent transposition (gmial.com)
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        )
    # one insertion/deletion
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    i = j = 0
    skipped = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        elif not skipped:
            skipped = True
            j += 1
        else:
            return False
    return True


def typo_suggestion(domain: str) -> str | None:
    """Return the popular domain this is likely a typo of, else None."""
    d = domain.strip().lower()
    if d in POPULAR_DOMAINS:
        return None
    for candidate in POPULAR_DOMAINS:
        if _one_edit_away(d, candidate):
            return candidate
    return None
