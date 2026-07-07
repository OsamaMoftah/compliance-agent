"""Shared fixtures: a stubbed legaldrift module so drift paths test without ML deps."""

import sys
import types
from dataclasses import dataclass, field

import pytest


@dataclass
class FakeDriftResult:
    drift_detected: bool = True
    p_value: float = 0.01
    severity: float = 0.8
    effect_size: float = 0.5
    test_results: dict = field(default_factory=dict)


class FakeDetector:
    last_threshold = None

    def __init__(self, threshold=0.05):
        FakeDetector.last_threshold = threshold

    def detect(self, e1, e2):
        return FakeDriftResult()


class FakeEngine:
    def encode(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


@dataclass
class FakeChunk:
    text: str
    chunk_index: int = 0
    metadata: dict = field(default_factory=dict)


class FakeDocument:
    def __init__(self, text="", document_id=""):
        self.text = text
        self.document_id = document_id


def _fake_chunk_by_sections(doc):
    return [FakeChunk(text=doc.text, metadata={"header": "Section 1"})]


def _fake_align_chunks(chunks1, chunks2):
    return list(zip(chunks1, chunks2))


@pytest.fixture
def stub_legaldrift(monkeypatch):
    fake = types.ModuleType("legaldrift")
    fake.DriftDetector = FakeDetector
    fake.EmbeddingEngine = FakeEngine
    fake.LegalDocument = FakeDocument
    fake.chunk_by_sections = _fake_chunk_by_sections
    fake.align_chunks = _fake_align_chunks
    monkeypatch.setitem(sys.modules, "legaldrift", fake)
    return fake
