"""Enterprise Agent OS — Phase 3 tests."""
import pytest
import uuid
import math
from datetime import datetime, timedelta
from graxia_tool.memory.layers import MemoryLayer, LAYER_CONFIG
from graxia_tool.memory.memory_os import MemoryOS


class TestMemoryLayers:
    def test_all_layers_defined(self):
        assert len(MemoryLayer) == 8

    def test_layer_values(self):
        expected = {"working", "short_term", "long_term", "episodic",
                    "semantic", "procedural", "failure", "preference"}
        actual = {l.value for l in MemoryLayer}
        assert actual == expected

    def test_layer_configs(self):
        for layer in MemoryLayer:
            assert layer in LAYER_CONFIG
            assert "ttl_seconds" in LAYER_CONFIG[layer]
            assert "storage" in LAYER_CONFIG[layer]
            assert "max_items" in LAYER_CONFIG[layer]

    def test_working_memory_short_ttl(self):
        assert LAYER_CONFIG[MemoryLayer.WORKING]["ttl_seconds"] <= 600

    def test_long_term_persistent(self):
        assert LAYER_CONFIG[MemoryLayer.LONG_TERM]["ttl_seconds"] == 0


class TestMemoryOS:
    def test_decay_calculation(self):
        os = MemoryOS()
        # Recent memory
        recent = datetime.utcnow()
        score = os._decay(recent, 0)
        assert 0.9 < score <= 1.0

    def test_decay_old_memory(self):
        os = MemoryOS()
        old = datetime.utcnow() - timedelta(days=60)
        score = os._decay(old, 0)
        # 60 days > 30 day half-life -> should be ~0.25
        assert score < 0.5

    def test_decay_access_boost(self):
        os = MemoryOS()
        old = datetime.utcnow() - timedelta(days=10)
        score_no_access = os._decay(old, 0)
        score_10_access = os._decay(old, 10)
        assert score_10_access > score_no_access

    def test_decay_max_one(self):
        os = MemoryOS()
        now = datetime.utcnow()
        score = os._decay(now, 1000)
        assert score <= 1.0

    def test_layer_configs_complete(self):
        # All layers should have storage config
        for layer, config in LAYER_CONFIG.items():
            assert "description" in config
            assert len(config["description"]) > 0
