from __future__ import annotations

import tempfile

import pytest
import yaml

from app.engine.profiles import PolicyProfile, load_profiles, default_profile


class TestLoadProfiles:
    def test_default_included(self):
        profiles = load_profiles("/nonexistent.yaml")
        assert "default" in profiles

    def test_default_thresholds(self):
        p = load_profiles("/nonexistent.yaml")["default"]
        assert p.challenge == 30
        assert p.block == 80

    def test_load_custom_profiles(self):
        content = yaml.dump({
            "profiles": {
                "default": {"thresholds": {"challenge": 30, "block": 80}},
                "checkout": {"thresholds": {"challenge": 20, "block": 60}, "weights": {"anonymizer": 40}},
                "newsletter": {"thresholds": {"challenge": 50, "block": 90}, "ignore": ["free_mail"]},
            }
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            profiles = load_profiles(path)
            assert sorted(profiles) == ["checkout", "default", "newsletter"]
            assert profiles["checkout"].challenge == 20
            assert profiles["checkout"].block == 60
            assert profiles["checkout"].weights == {"anonymizer": 40}
            assert profiles["newsletter"].ignore == frozenset(["free_mail"])
            # Overrides do not leak between profiles
            assert profiles["default"].weights == {}
            assert profiles["default"].ignore == frozenset()
        finally:
            import os
            os.unlink(path)

    def test_invalid_profile_skipped(self):
        content = yaml.dump({
            "profiles": {
                "default": {"thresholds": {"challenge": 30, "block": 80}},
                "bad": {"thresholds": {"challenge": 90, "block": 80}},  # challenge >= block
            }
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            profiles = load_profiles(path)
            assert "default" in profiles
            assert "bad" not in profiles
        finally:
            import os
            os.unlink(path)

    def test_broken_yaml_falls_back(self):
        content = "not: [valid: yaml: {{{{{{"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            path = f.name
        try:
            profiles = load_profiles(path)
            assert profiles == {"default": profiles["default"]}
        finally:
            import os
            os.unlink(path)


class TestDefaultProfile:
    def test_is_default(self):
        p = default_profile()
        assert p.name == "default"
        assert p.challenge == 30
        assert p.block == 80
