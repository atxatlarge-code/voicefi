"""
Unit and integration tests for Voicegency Listening Skills, STT Biasing, and Proactive Triage.
"""

from pathlib import Path
import pytest

from voicegency.config import VoicegencyConfig, AmbientConfig, STTBiasingConfig, load_config
from voicegency.stt.biasing import ProjectContextExtractor, PhoneticNormalizer
from voicegency.integrations.proactive import (
    ProactiveTriageEngine,
    ProactiveDispatcher,
    ProactiveTask,
    TriageCategory,
)


class TestSTTBiasingAndNormalization:
    """Test STT biasing symbol extraction and phonetic normalizer."""

    def test_project_context_extractor(self, tmp_path):
        # Create a mock project tree
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "billing.py").write_text("# billing", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text('name = "mock-deal-flow"\n', encoding="utf-8")

        extractor = ProjectContextExtractor(root_dir=tmp_path)
        symbols = extractor.extract_symbols()
        assert "billing" in symbols or "src" in symbols
        assert "mock-deal-flow" in symbols

        prompt = extractor.get_bias_prompt(extra_words=["StripeWebhook"])
        assert "StripeWebhook" in prompt
        assert "pytest" in prompt
        assert "kubectl" in prompt

    def test_phonetic_normalizer_tech_terms(self):
        cases = [
            ("run pie test on test auth", "run pytest on test auth"),
            ("pi test dash v", "pytest dash v"),
            ("cube cuddle get pods", "kubectl get pods"),
            ("dock er compose up", "docker compose up"),
            ("fast a p i endpoint", "FastAPI endpoint"),
            ("next j s router", "Next.js router"),
            ("node j s server", "Node.js server"),
            ("push to get hub", "push to GitHub"),
            ("create a p r", "create a PR"),
            ("file main dot py", "file main .py"),
            ("component hero dot tsx", "component hero .tsx"),
        ]
        for spoken, expected in cases:
            assert PhoneticNormalizer.normalize(spoken) == expected

    def test_phonetic_casing_directives(self):
        assert PhoneticNormalizer.normalize("set variable camel case user id to 5") == "set variable userId to 5"
        assert PhoneticNormalizer.normalize("function snake case get user info returns dict") == "function get_user_info returns dict"
        assert PhoneticNormalizer.normalize("create file kebab case payment card") == "create file payment-card"


class TestProactiveTriageEngine:
    """Test proactive intent classification and workspace routing."""

    def test_scaffold_intent_routes_to_branch_workspace(self):
        utterance = "Let's build a Stripe customer portal with webhook retries"
        task = ProactiveTriageEngine.evaluate(utterance)
        assert task is not None
        assert task.category == TriageCategory.SCAFFOLD
        assert task.suggested_workspace == "branch"
        assert "isolated branch" in task.action_prompt

    def test_research_intent_routes_to_inherit_workspace(self):
        utterance = "What is the API for Stripe webhook signatures?"
        task = ProactiveTriageEngine.evaluate(utterance)
        assert task is not None
        assert task.category == TriageCategory.RESEARCH
        assert task.suggested_workspace == "inherit"

    def test_diagnose_intent_routes_to_inherit_workspace(self):
        utterance = "Why is the LCP performance so slow on the hero image?"
        task = ProactiveTriageEngine.evaluate(utterance)
        assert task is not None
        assert task.category == TriageCategory.DIAGNOSE
        assert task.suggested_workspace == "inherit"

    def test_ticket_action_item_intent(self):
        utterance = "Action item: Jake to add unit tests for auth middleware"
        task = ProactiveTriageEngine.evaluate(utterance)
        assert task is not None
        assert task.category == TriageCategory.TICKET

    def test_ignore_smalltalk_and_chitchat(self):
        ignores = [
            "Yeah that sounds good",
            "mhm",
            "ok",
            "What do you want for lunch today?",
            "The traffic was terrible",
        ]
        for phrase in ignores:
            assert ProactiveTriageEngine.evaluate(phrase) is None


class TestProactiveDispatcher:
    """Test task lifecycle and callbacks in dispatcher."""

    def test_dispatcher_lifecycle(self):
        created_tasks = []
        dispatcher = ProactiveDispatcher(on_task_created=lambda t: created_tasks.append(t))

        task = dispatcher.process_utterance("We should add dark mode support to the theme")
        assert task is not None
        assert len(created_tasks) == 1
        assert created_tasks[0].id == task.id
        assert task.status == "staged"

        staged = dispatcher.get_staged_tasks()
        assert len(staged) == 1

        # Complete task
        dispatcher.complete_task(task.id, "Generated dark mode CSS tokens.")
        assert task.status == "completed"
        assert task.result_summary == "Generated dark mode CSS tokens."
        assert len(dispatcher.get_staged_tasks()) == 0

        # Dismiss task
        task2 = dispatcher.process_utterance("Can we create a route for user profile?")
        assert task2 is not None
        dispatcher.dismiss_task(task2.id)
        assert task2.status == "dismissed"


class TestConfigAndSkillFiles:
    """Verify configuration schemas and skill documentation."""

    def test_ambient_config_defaults(self):
        config = VoicegencyConfig()
        assert config.ambient.enabled is False
        assert config.ambient.auto_triage is True
        assert config.stt_biasing.enabled is True
        assert config.stt_biasing.auto_scan_repo is True

    def test_skill_files_exist_and_valid(self):
        active_skill = Path(".agents/skills/active-listening/SKILL.md")
        ambient_skill = Path(".agents/skills/ambient-listener/SKILL.md")

        assert active_skill.is_file()
        assert ambient_skill.is_file()

        active_content = active_skill.read_text(encoding="utf-8")
        assert "name: active-listening" in active_content
        assert "Paraphrase Destructive Actions" in active_content

        ambient_content = ambient_skill.read_text(encoding="utf-8")
        assert "name: ambient-listener" in ambient_content
        assert "Workspace=\"branch\"" in ambient_content
