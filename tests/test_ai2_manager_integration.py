import importlib


def test_manager_preserves_ai1_then_ai2_order_and_compact_history(monkeypatch):
    module = importlib.import_module("research_engine.agent_manager")
    manager = module.AgentManager()
    calls = []

    class FakeEngine:
        def research(self, question, depth_mode="DEEP", custom=None, job_id=None):
            return {"question": question, "answer": "core", "sources": [{"id": "S1"}], "mode": depth_mode}

    monkeypatch.setattr(manager, "get", lambda project_id="default": FakeEngine())

    def fake_ai1(question, result):
        calls.append("AI-1")
        result = dict(result)
        result["ai1_research_packet"] = {
            "validation": {"valid": True},
            "sections": {"14. Confidence in Research Packet /100": {"score": 88}},
        }
        return result

    def fake_ai2(question, result):
        calls.append("AI-2")
        assert "ai1_research_packet" in result
        result = dict(result)
        result["ai2_validation"] = {
            "packet_integrity": {"valid": True},
            "sections": {"16. Confidence /100": {"score": 75}},
        }
        return result

    monkeypatch.setattr(module, "attach_ai1_research_packet", fake_ai1)
    monkeypatch.setattr(module, "attach_ai2_validation", fake_ai2)

    out = manager.research("Q", project_id="P", depth_mode="DEEP")
    assert calls == ["AI-1", "AI-2"]
    assert out["answer"] == "core"
    assert out["ai1_research_packet"]["validation"]["valid"] is True
    assert out["ai2_validation"]["packet_integrity"]["valid"] is True

    history = manager.history("P")
    assert len(history) == 1
    assert history[0]["source_count"] == 1
    assert history[0]["ai1_packet_valid"] is True
    assert history[0]["ai1_packet_confidence"] == 88
    assert history[0]["ai2_packet_valid"] is True
    assert history[0]["ai2_packet_confidence"] == 75
    assert "ai1_research_packet" not in history[0]
    assert "ai2_validation" not in history[0]
