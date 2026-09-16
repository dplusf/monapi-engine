from __future__ import annotations

import re
import tempfile
from pathlib import Path

import yaml

from app.engine.signals import empty_catalogue, load_catalogue

ENGINE_ROOT = Path(__file__).resolve().parent.parent
CATALOGUE_PATH = ENGINE_ROOT / "app" / "data" / "signals.yaml"

# Signal ids are constructed in exactly two ways in the code: as a literal
# id="..." or as an f-string id=f"...". Both are matched here.
SIGNAL_ID_RE = re.compile(r'\bid=f?"([a-z_]+:[^"]*)"')


def _emitted_signal_ids() -> set[str]:
    """Every signal id literal the engine code can produce."""
    found: set[str] = set()
    for path in (ENGINE_ROOT / "app").rglob("*.py"):
        for match in SIGNAL_ID_RE.finditer(path.read_text(encoding="utf-8")):
            found.add(match.group(1))
    return found


class TestCatalogue:
    def test_ships_with_engine(self):
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        assert catalogue.version >= 1
        assert catalogue.signals

    def test_missing_file_degrades_to_empty(self):
        catalogue = load_catalogue("/nonexistent/signals.yaml")
        assert catalogue.signals == []
        assert catalogue.lookup("email:no_mx") is None

    def test_broken_file_degrades_to_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("signals: [unclosed\n")
            path = f.name
        assert load_catalogue(path).signals == []

    def test_every_entry_is_documented(self):
        for sig in load_catalogue(str(CATALOGUE_PATH)).signals:
            sid = sig.get("id") or sig.get("id_pattern")
            assert sid, f"entry without id or id_pattern: {sig}"
            for key in ("category", "weight", "severity", "source", "endpoints", "meaning", "guidance"):
                assert sig.get(key), f"{sid} is missing {key}"

    def test_every_category_has_a_source(self):
        """The bug this catches: `free_mail` was documented, ignored by a
        profile and referenced nowhere else — no feed produced it, so the
        profile ignored a category that could never appear."""
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        feeds = yaml.safe_load(
            (ENGINE_ROOT / "app" / "data" / "feeds.yaml").read_text(encoding="utf-8")
        )
        from_feeds = {str(f.get("category")) for f in (feeds.get("feeds") or [])}

        # Categories the code assigns directly, without a feed.
        code = (ENGINE_ROOT / "app").rglob("*.py")
        from_code = set()
        for path in code:
            for match in re.finditer(r'\bcategory="([a-z_]+)"', path.read_text(encoding="utf-8")):
                from_code.add(match.group(1))

        orphans = set(catalogue.categories) - from_feeds - from_code
        assert not orphans, (
            f"documented categories nothing can produce: {sorted(orphans)} — "
            "either wire up a source or drop them from signals.yaml"
        )

    def test_every_feed_category_is_documented(self):
        feeds = yaml.safe_load(
            (ENGINE_ROOT / "app" / "data" / "feeds.yaml").read_text(encoding="utf-8")
        )
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        undocumented = {
            str(f.get("category")) for f in (feeds.get("feeds") or [])
        } - set(catalogue.categories)
        assert not undocumented, f"feed categories missing from signals.yaml: {sorted(undocumented)}"

    def test_categories_referenced_by_profiles_exist(self):
        """A profile that ignores or reweights a category nobody documents
        is a silent no-op — the catalogue is where that gets caught."""
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        policies = yaml.safe_load(
            (ENGINE_ROOT / "app" / "data" / "policies.yaml").read_text(encoding="utf-8")
        )
        for name, spec in (policies.get("profiles") or {}).items():
            spec = spec or {}
            referenced = set(spec.get("ignore") or []) | set((spec.get("weights") or {}))
            unknown = referenced - set(catalogue.categories)
            assert not unknown, f"profile {name} references undocumented categories: {unknown}"


class TestEmittedIdsAreDocumented:
    def test_no_undocumented_signal_ids(self):
        """Catches the actual failure mode: a new check ships a signal id
        that no consumer can look up."""
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        undocumented = []
        for sid in _emitted_signal_ids():
            # f-string placeholders become a resolvable prefix at runtime
            probe = sid.replace("{cat}", "disposable").replace("{feed}", "somefeed").replace("{i}", "0")
            if catalogue.lookup(probe) is None:
                undocumented.append(sid)
        assert not undocumented, f"signal ids emitted but not in signals.yaml: {sorted(undocumented)}"

    def test_finds_the_known_ids(self):
        """Guard against the regex silently matching nothing."""
        emitted = _emitted_signal_ids()
        assert "email:no_mx" in emitted
        assert "email:domain_typo" in emitted


class TestLookup:
    def test_exact_id(self):
        entry = load_catalogue(str(CATALOGUE_PATH)).lookup("email:no_mx")
        assert entry["category"] == "mx"
        assert entry["weight"] == 30

    def test_pattern_by_prefix(self):
        entry = load_catalogue(str(CATALOGUE_PATH)).lookup("feed:firehol_level2:0")
        assert entry["id_pattern"] == "feed:<feed_name>:<n>"

    def test_email_domain_pattern(self):
        entry = load_catalogue(str(CATALOGUE_PATH)).lookup("email_domain:disposable")
        assert entry["id_pattern"] == "email_domain:<category>"

    def test_longest_prefix_wins(self):
        """`domain:` must not swallow `email_domain:` or vice versa."""
        catalogue = load_catalogue(str(CATALOGUE_PATH))
        assert catalogue.lookup("domain:phishing")["id_pattern"] == "domain:<category>"

    def test_unknown_id(self):
        assert load_catalogue(str(CATALOGUE_PATH)).lookup("nope:nothing") is None

    def test_blank_id(self):
        assert load_catalogue(str(CATALOGUE_PATH)).lookup("") is None
        assert empty_catalogue().lookup("email:no_mx") is None
