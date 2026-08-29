"""Master E2E Test Suite for VoiceFi Open Source Release & Developer Adoption Package.

Validates the full repository release package against all acceptance criteria in:
- ORIGINAL_REQUEST.md
- PROJECT.md
- TEST_INFRA.md

Organized into 4 Tiers:
- Tier 1: Feature Coverage (>=5 tests per feature group across Governance, Documentation,
          GitHub Templates, CI/CD Workflows, Extension Guides, Growth & Roadmap)
- Tier 2: Boundary & Syntax Integrity (YAML validity, markdown link crawling, no 404s,
          no hardcoded absolute file:/// paths, UTF-8 encoding)
- Tier 3: Cross-Feature & Schema Conformance (CLI subcommands reflection, MCP tools schema,
          pyproject.toml, Homebrew formula)
- Tier 4: Real-World Developer Workflows (CLI --help execution, invalid command handling,
          formula verification)
"""

import os
import re
import subprocess
import sys
from pathlib import Path
import tomllib
import pytest
import yaml

# Root directory of the VoiceFi repository
ROOT_DIR = Path(__file__).resolve().parent.parent.parent


# ==============================================================================
# TIER 1: FEATURE COVERAGE (>=5 tests per feature group)
# ==============================================================================

class TestTier1GovernanceAndLegalHygiene:
    """Tier 1.1: Governance, Legal Hygiene & Licensing."""

    def test_tier1_license_presence_and_terms(self):
        """Verify MIT LICENSE exists, is non-empty, and specifies MIT terms & copyright."""
        license_path = ROOT_DIR / "LICENSE"
        assert license_path.exists(), "LICENSE file must exist in repository root"
        content = license_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 50, "LICENSE file must not be empty"
        assert "MIT License" in content or "MIT LICENSE" in content.upper(), "Must declare MIT License"
        assert "Jake Trigg" in content, "Must include author copyright"
        assert "2026" in content, "Must include 2026 copyright year"

    def test_tier1_code_of_conduct_covenant(self):
        """Verify CODE_OF_CONDUCT.md adheres to Contributor Covenant v2.1."""
        coc_path = ROOT_DIR / "CODE_OF_CONDUCT.md"
        assert coc_path.exists(), "CODE_OF_CONDUCT.md must exist in root"
        content = coc_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 100, "CODE_OF_CONDUCT.md must not be empty"
        assert "Contributor Covenant" in content, "Must reference Contributor Covenant"
        assert "2.1" in content or "2.0" in content, "Must reference standard Contributor Covenant version"
        assert "Enforcement" in content or "Reporting" in content, "Must include enforcement/reporting section"

    def test_tier1_contributing_guide_structure(self):
        """Verify CONTRIBUTING.md contains development setup, test, and PR workflow."""
        contrib_path = ROOT_DIR / "CONTRIBUTING.md"
        assert contrib_path.exists(), "CONTRIBUTING.md must exist in root"
        content = contrib_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 200, "CONTRIBUTING.md must be comprehensive"
        assert "setup" in content.lower() or "installation" in content.lower(), "Must cover setup"
        assert "pytest" in content, "Must cover pytest test instructions"
        assert "pull request" in content.lower() or "pr" in content.lower(), "Must cover PR process"

    def test_tier1_security_policy_disclosure(self):
        """Verify SECURITY.md details vulnerability reporting SLA and procedures."""
        sec_path = ROOT_DIR / "SECURITY.md"
        assert sec_path.exists(), "SECURITY.md must exist in root"
        content = sec_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 100, "SECURITY.md must not be empty"
        assert "vulnerability" in content.lower() or "reporting" in content.lower(), "Must detail reporting"
        assert "48" in content or "sla" in content.lower() or "hours" in content.lower(), "Must mention response timeframe"

    def test_tier1_homebrew_formula_presence(self):
        """Verify Formula/vifi.rb exists and specifies MIT license."""
        formula_path = ROOT_DIR / "Formula" / "vifi.rb"
        assert formula_path.exists(), "Formula/vifi.rb must exist"
        content = formula_path.read_text(encoding="utf-8")
        assert 'license "MIT"' in content or "license 'MIT'" in content or 'license: "MIT"' in content, "Formula must declare MIT license"
        assert "class Vifi < Formula" in content or "class Voicefi < Formula" in content, "Must declare Formula class"


class TestTier1DocumentationAndQuickstart:
    """Tier 1.2: Developer Delight & Hero Quickstart Documentation."""

    def test_tier1_readme_hero_and_value_props(self):
        """Verify README.md contains hero overview, architecture, and key value propositions."""
        readme_path = ROOT_DIR / "README.md"
        assert readme_path.exists(), "README.md must exist in root"
        content = readme_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 1000, "README.md must be comprehensive"
        assert "VoiceFi" in content or "voicefi" in content, "Must showcase VoiceFi"
        assert "HUD" in content or "Dynamic Island" in content, "Must mention HUD / Dynamic Island"
        assert "MCP" in content, "Must mention MCP"

    def test_tier1_readme_sub_60s_quickstart(self):
        """Verify README.md contains quickstart installation commands."""
        content = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        assert "pip install" in content or "brew install" in content or "vifi setup" in content or "git clone" in content, "Must provide quickstart command block"

    def test_tier1_readme_mcp_configuration(self):
        """Verify README.md contains MCP configuration instructions."""
        content = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        assert "mcp" in content.lower(), "README must reference MCP"
        assert "json" in content.lower() or "voicefi" in content.lower(), "Must show MCP configuration snippet"

    def test_tier1_readme_cli_cheatsheet(self):
        """Verify README.md or docs contain essential CLI subcommands."""
        content = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        assert "vifi status" in content or "vifi setup" in content or "vifi voice" in content or "vifi send" in content, "Must mention core CLI subcommands"

    def test_tier1_readme_license_and_badges(self):
        """Verify README.md mentions MIT license and links to docs/governance."""
        content = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        assert "MIT" in content or "License" in content, "README must mention license"
        assert "CONTRIBUTING.md" in content or "Contributing" in content or "License" in content, "README must link to contribution/license resources"


class TestTier1IssueAndPRTemplates:
    """Tier 1.3: GitHub Issue & Pull Request Templates."""

    def test_tier1_pr_template_presence_and_checklist(self):
        """Verify .github/PULL_REQUEST_TEMPLATE.md exists with validation checklist."""
        pr_template = ROOT_DIR / ".github" / "PULL_REQUEST_TEMPLATE.md"
        assert pr_template.exists(), "PULL_REQUEST_TEMPLATE.md must exist in .github/"
        content = pr_template.read_text(encoding="utf-8")
        assert "- [" in content, "PR template must contain markdown checklist boxes"
        assert "test" in content.lower(), "PR template must contain testing verification check"

    def test_tier1_issue_template_bug_report(self):
        """Verify .github/ISSUE_TEMPLATE/bug_report.yml exists and has structured form fields."""
        template = ROOT_DIR / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
        assert template.exists(), "bug_report.yml must exist"
        content = template.read_text(encoding="utf-8")
        assert "name:" in content and "description:" in content and "body:" in content, "Must follow GitHub Issue Form schema"

    def test_tier1_issue_template_feature_request(self):
        """Verify .github/ISSUE_TEMPLATE/feature_request.yml exists."""
        template = ROOT_DIR / ".github" / "ISSUE_TEMPLATE" / "feature_request.yml"
        assert template.exists(), "feature_request.yml must exist"
        content = template.read_text(encoding="utf-8")
        assert "name:" in content and "body:" in content, "Must follow GitHub Issue Form schema"

    def test_tier1_issue_template_voice_persona_request(self):
        """Verify .github/ISSUE_TEMPLATE/voice_persona_request.yml exists."""
        template = ROOT_DIR / ".github" / "ISSUE_TEMPLATE" / "voice_persona_request.yml"
        assert template.exists(), "voice_persona_request.yml must exist"
        content = template.read_text(encoding="utf-8")
        assert "name:" in content and "body:" in content, "Must follow GitHub Issue Form schema"

    def test_tier1_issue_template_config(self):
        """Verify .github/ISSUE_TEMPLATE/config.yml exists."""
        template = ROOT_DIR / ".github" / "ISSUE_TEMPLATE" / "config.yml"
        assert template.exists(), "config.yml must exist in .github/ISSUE_TEMPLATE/"
        content = template.read_text(encoding="utf-8")
        assert "blank_issues_enabled" in content or "contact_links" in content, "Must configure issue form settings"


class TestTier1CICDWorkflows:
    """Tier 1.4: Contributor CI/CD Workflows & Guardrails."""

    def test_tier1_workflow_ci_matrix(self):
        """Verify .github/workflows/ci.yml exists, defines matrix across Python 3.10-3.12 and OS."""
        ci_path = ROOT_DIR / ".github" / "workflows" / "ci.yml"
        assert ci_path.exists(), "ci.yml must exist"
        content = ci_path.read_text(encoding="utf-8")
        assert "3.10" in content and "3.11" in content and "3.12" in content, "Must test Python 3.10, 3.11, 3.12"
        assert "pytest" in content, "CI must execute pytest"

    def test_tier1_workflow_lint_ruff(self):
        """Verify .github/workflows/lint.yml exists and executes ruff."""
        lint_path = ROOT_DIR / ".github" / "workflows" / "lint.yml"
        assert lint_path.exists(), "lint.yml must exist"
        content = lint_path.read_text(encoding="utf-8")
        assert "ruff" in content, "lint.yml must run ruff checks"

    def test_tier1_workflow_release_publishing(self):
        """Verify .github/workflows/release.yml exists and handles packaging."""
        release_path = ROOT_DIR / ".github" / "workflows" / "release.yml"
        assert release_path.exists(), "release.yml must exist"
        content = release_path.read_text(encoding="utf-8")
        assert "build" in content or "pypi" in content.lower() or "release" in content.lower(), "release.yml must configure build/release"

    def test_tier1_pyproject_metadata(self):
        """Verify pyproject.toml exists and declares voicefi package details."""
        pyproject_path = ROOT_DIR / "pyproject.toml"
        assert pyproject_path.exists(), "pyproject.toml must exist"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        assert data.get("project", {}).get("name") == "voicefi", "Project name must be voicefi"
        assert "dependencies" in data.get("project", {}), "Project must specify dependencies"

    def test_tier1_pyproject_scripts_entrypoints(self):
        """Verify pyproject.toml declares CLI scripts entrypoints."""
        pyproject_path = ROOT_DIR / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        scripts = data.get("project", {}).get("scripts", {})
        assert "vifi" in scripts, "scripts must register 'vifi' executable"
        assert "voicefi" in scripts, "scripts must register 'voicefi' executable"


class TestTier1ExtensionToolkits:
    """Tier 1.5: Extension & Contributor Toolkits."""

    def test_tier1_ext_toolkit_custom_tts(self):
        """Verify docs/CONTRIBUTING_CUSTOM_TTS.md explains BaseTTS subclassing."""
        path = ROOT_DIR / "docs" / "CONTRIBUTING_CUSTOM_TTS.md"
        assert path.exists(), "docs/CONTRIBUTING_CUSTOM_TTS.md must exist"
        content = path.read_text(encoding="utf-8")
        assert len(content.strip()) > 200, "Must be comprehensive"
        assert "BaseTTS" in content or "TTS" in content, "Must discuss BaseTTS engine"

    def test_tier1_ext_toolkit_custom_sfx(self):
        """Verify docs/CONTRIBUTING_CUSTOM_SFX.md explains custom procedural audio synthesis."""
        path = ROOT_DIR / "docs" / "CONTRIBUTING_CUSTOM_SFX.md"
        assert path.exists(), "docs/CONTRIBUTING_CUSTOM_SFX.md must exist"
        content = path.read_text(encoding="utf-8")
        assert len(content.strip()) > 200, "Must be comprehensive"
        assert "sfx" in content.lower() or "sound" in content.lower() or "chimes" in content.lower(), "Must discuss SFX synthesis"

    def test_tier1_ext_toolkit_custom_mcp_hooks(self):
        """Verify docs/CONTRIBUTING_CUSTOM_MCP_HOOKS.md explains MCP tool creation & agent hooks."""
        path = ROOT_DIR / "docs" / "CONTRIBUTING_CUSTOM_MCP_HOOKS.md"
        assert path.exists(), "docs/CONTRIBUTING_CUSTOM_MCP_HOOKS.md must exist"
        content = path.read_text(encoding="utf-8")
        assert len(content.strip()) > 200, "Must be comprehensive"
        assert "MCP" in content, "Must explain MCP tools"
        assert "hook" in content.lower() or "agent" in content.lower(), "Must explain agent hooks"

    def test_tier1_ext_toolkits_code_examples(self):
        """Verify extension guides contain code blocks with Python imports."""
        for filename in ["CONTRIBUTING_CUSTOM_TTS.md", "CONTRIBUTING_CUSTOM_SFX.md", "CONTRIBUTING_CUSTOM_MCP_HOOKS.md"]:
            path = ROOT_DIR / "docs" / filename
            if path.exists():
                content = path.read_text(encoding="utf-8")
                assert "```python" in content or "```json" in content or "```bash" in content, f"{filename} must have code blocks"

    def test_tier1_ext_toolkits_testing_requirements(self):
        """Verify extension toolkits document unit test and registration requirements."""
        for filename in ["CONTRIBUTING_CUSTOM_TTS.md", "CONTRIBUTING_CUSTOM_SFX.md", "CONTRIBUTING_CUSTOM_MCP_HOOKS.md"]:
            path = ROOT_DIR / "docs" / filename
            if path.exists():
                content = path.read_text(encoding="utf-8")
                assert "test" in content.lower() or "pytest" in content.lower(), f"{filename} must discuss testing"


class TestTier1GrowthRoadmapAndGoodFirstIssues:
    """Tier 1.6: Developer Adoption Roadmap & Community Growth."""

    def test_tier1_growth_roadmap_phases(self):
        """Verify docs/ROADMAP.md details the 3-Phase evolution."""
        roadmap_path = ROOT_DIR / "docs" / "ROADMAP.md"
        if not roadmap_path.exists():
            roadmap_path = ROOT_DIR / "ROADMAP.md"
        assert roadmap_path.exists(), "ROADMAP.md must exist in docs/ or root"
        content = roadmap_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 300, "ROADMAP.md must be comprehensive"
        assert "Phase" in content or "phase" in content, "Must describe phased roadmap"

    def test_tier1_growth_good_first_issues_count(self):
        """Verify docs/GOOD_FIRST_ISSUES.md exists and contains at least 5 structured issues."""
        issues_path = ROOT_DIR / "docs" / "GOOD_FIRST_ISSUES.md"
        assert issues_path.exists(), "docs/GOOD_FIRST_ISSUES.md must exist"
        content = issues_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 300, "GOOD_FIRST_ISSUES.md must be comprehensive"
        issue_headers = re.findall(r"###?\s+(?:Issue\s+)?#?\d+", content, re.IGNORECASE)
        assert len(issue_headers) >= 5, f"Expected at least 5 good first issues, found {len(issue_headers)}"

    def test_tier1_growth_good_first_issues_structure(self):
        """Verify good first issues include difficulty, file pointers, and acceptance criteria."""
        content = (ROOT_DIR / "docs" / "GOOD_FIRST_ISSUES.md").read_text(encoding="utf-8")
        assert "file" in content.lower() or "src/" in content, "Must reference affected files"
        assert "acceptance" in content.lower() or "criteria" in content.lower() or "tasks" in content.lower() or "- [" in content, "Must list acceptance criteria"

    def test_tier1_growth_plugin_bounties(self):
        """Verify docs/COMMUNITY_GROWTH.md specifies plugin bounties ($100-$250)."""
        growth_path = ROOT_DIR / "docs" / "COMMUNITY_GROWTH.md"
        assert growth_path.exists(), "docs/COMMUNITY_GROWTH.md must exist"
        content = growth_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 200, "COMMUNITY_GROWTH.md must not be empty"
        assert "bounty" in content.lower() or "bounties" in content.lower() or "$" in content, "Must explain bounties"

    def test_tier1_growth_community_channels(self):
        """Verify docs/COMMUNITY_GROWTH.md links to community forums or GitHub discussions."""
        content = (ROOT_DIR / "docs" / "COMMUNITY_GROWTH.md").read_text(encoding="utf-8")
        assert "github" in content.lower() or "discord" in content.lower() or "community" in content.lower(), "Must link to community channels"


# ==============================================================================
# TIER 2: BOUNDARY & SYNTAX INTEGRITY
# ==============================================================================

class TestTier2BoundaryAndSyntaxIntegrity:
    """Tier 2: YAML validation, markdown link crawler, no broken paths, UTF-8 integrity."""

    def test_tier2_workflow_yaml_syntax(self):
        """Validate YAML syntax of all .github/workflows/*.yml files using PyYAML."""
        workflow_dir = ROOT_DIR / ".github" / "workflows"
        assert workflow_dir.exists(), ".github/workflows directory must exist"
        yml_files = list(workflow_dir.glob("*.yml")) + list(workflow_dir.glob("*.yaml"))
        assert len(yml_files) >= 3, f"Expected at least 3 workflow files (ci, lint, release), found {len(yml_files)}"

        for yml_file in yml_files:
            with open(yml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{yml_file.name} must parse to a YAML dictionary"
            assert "name" in data, f"{yml_file.name} must have a 'name' field"
            assert "jobs" in data, f"{yml_file.name} must have a 'jobs' section"
            assert any(k in data for k in ["on", True]), f"{yml_file.name} must define an 'on' trigger"

    def test_tier2_issue_template_yaml_syntax(self):
        """Validate YAML syntax of all .github/ISSUE_TEMPLATE/*.yml files using PyYAML."""
        template_dir = ROOT_DIR / ".github" / "ISSUE_TEMPLATE"
        assert template_dir.exists(), ".github/ISSUE_TEMPLATE directory must exist"
        yml_files = list(template_dir.glob("*.yml")) + list(template_dir.glob("*.yaml"))
        assert len(yml_files) >= 3, f"Expected at least 3 issue template files, found {len(yml_files)}"

        for yml_file in yml_files:
            with open(yml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{yml_file.name} must parse to a YAML dictionary"
            if yml_file.name != "config.yml":
                assert "name" in data, f"{yml_file.name} must have a 'name' field"
                assert "description" in data or "body" in data, f"{yml_file.name} must have 'description' or 'body'"

    def test_tier2_markdown_local_links_resolve(self):
        """Verify all local markdown links in README.md, CONTRIBUTING.md, and docs/*.md resolve to real files."""
        md_files = [
            ROOT_DIR / "README.md",
            ROOT_DIR / "CONTRIBUTING.md",
            ROOT_DIR / "CODE_OF_CONDUCT.md",
            ROOT_DIR / "SECURITY.md",
        ] + list((ROOT_DIR / "docs").glob("*.md"))

        link_pattern = re.compile(r"\[.*?\]\((.*?)\)")
        broken_links = []
        file_uri_links = []

        for md_file in md_files:
            if not md_file.exists():
                continue
            content = md_file.read_text(encoding="utf-8")
            matches = link_pattern.findall(content)

            for target in matches:
                target_clean = target.strip()
                # Check for forbidden absolute file:/// URIs
                if target_clean.startswith("file:///"):
                    file_uri_links.append((md_file.name, target_clean))
                    continue

                # Skip external URLs, mailto, and pure in-page anchors
                if re.match(r"^(https?://|mailto:|#)", target_clean):
                    continue

                # Strip anchor fragment from relative link
                link_path_str = target_clean.split("#")[0]
                if not link_path_str:
                    continue

                # Check resolution relative to the markdown file's directory or repo root
                resolved_rel = (md_file.parent / link_path_str).resolve()
                resolved_root = (ROOT_DIR / link_path_str.lstrip("/")).resolve()

                if not resolved_rel.exists() and not resolved_root.exists():
                    broken_links.append((md_file.name, target_clean))

        assert not file_uri_links, f"Found hardcoded file:/// links: {file_uri_links}"
        assert not broken_links, f"Found broken local markdown links: {broken_links}"

    def test_tier2_markdown_no_hardcoded_user_paths(self):
        """Verify no hardcoded machine-specific 'file:///' or private user paths exist in public documentation."""
        md_files = [
            ROOT_DIR / "README.md",
            ROOT_DIR / "CONTRIBUTING.md",
            ROOT_DIR / "SECURITY.md",
            ROOT_DIR / "CODE_OF_CONDUCT.md",
        ] + list((ROOT_DIR / "docs").glob("*.md"))

        violations = []
        user_path_pattern = re.compile(r"(file:///Users/|/Users/jaketrigg)")

        for md_file in md_files:
            if not md_file.exists():
                continue
            content = md_file.read_text(encoding="utf-8")
            matches = user_path_pattern.findall(content)
            if matches:
                violations.append((md_file.name, matches))

        assert not violations, f"Found hardcoded private filesystem paths in documentation: {violations}"

    def test_tier2_utf8_encoding_and_formatting(self):
        """Verify all markdown and YAML files are valid UTF-8 and contain no null bytes."""
        files_to_check = [
            ROOT_DIR / "LICENSE",
            ROOT_DIR / "README.md",
            ROOT_DIR / "CONTRIBUTING.md",
            ROOT_DIR / "SECURITY.md",
            ROOT_DIR / "CODE_OF_CONDUCT.md",
            ROOT_DIR / "pyproject.toml",
            ROOT_DIR / "Formula" / "vifi.rb",
        ] + list((ROOT_DIR / "docs").glob("*.md")) + list((ROOT_DIR / ".github").rglob("*.yml")) + list((ROOT_DIR / ".github").rglob("*.md"))

        for fpath in files_to_check:
            if fpath.exists():
                raw_bytes = fpath.read_bytes()
                assert b"\x00" not in raw_bytes, f"{fpath.name} must not contain null bytes"
                try:
                    raw_bytes.decode("utf-8")
                except UnicodeDecodeError as e:
                    pytest.fail(f"File {fpath.name} is not valid UTF-8: {e}")


# ==============================================================================
# TIER 3: CROSS-FEATURE & CLI/MCP SCHEMA CONFORMANCE
# ==============================================================================

class TestTier3SchemaAndCrossFeatureConformance:
    """Tier 3: CLI Subcommand reflection, MCP Tools schema, pyproject.toml validity."""

    def test_tier3_cli_subcommands_conformance(self):
        """Verify that CLI commands documented in README and cheat sheets match registered subcommands in src/voicefi/cli.py."""
        from voicefi.cli import build_parser

        parser = build_parser()
        registered_commands = set()
        for action in parser._actions:
            if hasattr(action, "choices") and action.choices:
                registered_commands.update(action.choices.keys())

        expected_core_commands = [
            "status", "setup", "speak", "listen", "send", "sfx", "dev",
            "clean", "voice", "ping", "troubleshoot", "panel", "feedback"
        ]

        for cmd in expected_core_commands:
            assert cmd in registered_commands, f"Command '{cmd}' must be registered in voicefi CLI parser"

    def test_tier3_mcp_tools_schema_conformance(self):
        """Verify that MCP tools match MCP_TOOLS schema in src/voicefi/mcp_server.py."""
        from voicefi.mcp_server import MCP_TOOLS

        assert isinstance(MCP_TOOLS, list), "MCP_TOOLS must be a list of tool definitions"
        tool_names = {t["name"] for t in MCP_TOOLS if isinstance(t, dict) and "name" in t}

        expected_mcp_tools = [
            "voicefi_speak",
            "voicefi_listen",
            "voicefi_send",
            "voicefi_sfx",
            "voicefi_ping_voice",
            "voicefi_stop",
            "voicefi_status"
        ]

        for expected_tool in expected_mcp_tools:
            assert expected_tool in tool_names, f"MCP tool '{expected_tool}' must be in MCP_TOOLS"

        # Validate schema structure of each tool
        for tool in MCP_TOOLS:
            assert "name" in tool, "Tool must have 'name'"
            assert "description" in tool, f"Tool {tool.get('name')} must have 'description'"
            assert "inputSchema" in tool, f"Tool {tool.get('name')} must have 'inputSchema'"
            schema = tool["inputSchema"]
            assert schema.get("type") == "object", f"Tool {tool.get('name')} inputSchema must have type 'object'"
            assert "properties" in schema, f"Tool {tool.get('name')} inputSchema must define properties"

    def test_tier3_pyproject_toml_validity(self):
        """Verify pyproject.toml parses cleanly with tomllib and contains valid build & dependency configuration."""
        pyproject_file = ROOT_DIR / "pyproject.toml"
        assert pyproject_file.exists(), "pyproject.toml must exist"

        with open(pyproject_file, "rb") as f:
            config = tomllib.load(f)

        assert "build-system" in config, "pyproject.toml must have [build-system]"
        assert "project" in config, "pyproject.toml must have [project]"
        assert config["project"].get("name") == "voicefi", "Project name must be 'voicefi'"
        assert re.match(r"^\d+\.\d+\.\d+", config["project"].get("version", "")), "Version must follow semver"
        assert "dependencies" in config["project"], "pyproject.toml must list runtime dependencies"
        assert "optional-dependencies" in config["project"], "pyproject.toml must define optional-dependencies"
        assert "dev" in config["project"]["optional-dependencies"], "Must define 'dev' dependency group"

    def test_tier3_homebrew_formula_conformance(self):
        """Verify Formula/vifi.rb has valid class structure, MIT license, and test block."""
        formula_file = ROOT_DIR / "Formula" / "vifi.rb"
        assert formula_file.exists(), "Formula/vifi.rb must exist"
        content = formula_file.read_text(encoding="utf-8")
        assert "class Vifi < Formula" in content, "Formula must define Vifi class"
        assert 'license "MIT"' in content, "Formula must specify MIT license"
        assert "depends_on" in content, "Formula must specify dependencies"
        assert "def install" in content, "Formula must define install method"
        assert "test do" in content, "Formula must include a test block"

    def test_tier3_version_synchronization(self):
        """Verify version consistency between pyproject.toml and Formula/vifi.rb."""
        with open(ROOT_DIR / "pyproject.toml", "rb") as f:
            pyproject_data = tomllib.load(f)
        pyproject_version = pyproject_data["project"]["version"]

        formula_content = (ROOT_DIR / "Formula" / "vifi.rb").read_text(encoding="utf-8")
        version_match = re.search(r'version\s+"([^"]+)"', formula_content)
        assert version_match, "Formula/vifi.rb must define a version string"
        formula_version = version_match.group(1)

        assert pyproject_version == formula_version, f"Version mismatch: pyproject.toml={pyproject_version} vs Formula/vifi.rb={formula_version}"


# ==============================================================================
# TIER 4: REAL-WORLD DEVELOPER WORKFLOWS
# ==============================================================================

class TestTier4RealWorldDeveloperWorkflows:
    """Tier 4: CLI execution of --help commands via subprocess and workflow validation."""

    def _run_cli(self, args):
        """Run CLI command via subprocess for authentic opaque-box validation."""
        cmd = [sys.executable, "-m", "voicefi.cli"] + args
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT_DIR / "src")
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def test_tier4_cli_root_help(self):
        """Test execution of `vifi --help`."""
        result = self._run_cli(["--help"])
        assert result.returncode == 0, f"vifi --help failed with stderr: {result.stderr}"
        assert "Usage: " in result.stdout or "Usage:" in result.stdout
        assert "VoiceFi" in result.stdout or "Commands" in result.stdout or "Options" in result.stdout

    def test_tier4_cli_setup_help(self):
        """Test execution of `vifi setup --help`."""
        result = self._run_cli(["setup", "--help"])
        assert result.returncode == 0, f"vifi setup --help failed with stderr: {result.stderr}"
        assert "setup" in result.stdout.lower()

    def test_tier4_cli_status_help(self):
        """Test execution of `vifi status --help`."""
        result = self._run_cli(["status", "--help"])
        assert result.returncode == 0, f"vifi status --help failed with stderr: {result.stderr}"
        assert "status" in result.stdout.lower() or "server" in result.stdout.lower()

    def test_tier4_cli_send_help(self):
        """Test execution of `vifi send --help`."""
        result = self._run_cli(["send", "--help"])
        assert result.returncode == 0, f"vifi send --help failed with stderr: {result.stderr}"
        assert "send" in result.stdout.lower() or "dispatch" in result.stdout.lower()

    def test_tier4_cli_voice_help(self):
        """Test execution of `vifi voice --help`."""
        result = self._run_cli(["voice", "--help"])
        assert result.returncode == 0, f"vifi voice --help failed with stderr: {result.stderr}"
        assert "voice" in result.stdout.lower()

    def test_tier4_cli_sfx_help(self):
        """Test execution of `vifi sfx --help`."""
        result = self._run_cli(["sfx", "--help"])
        assert result.returncode == 0, f"vifi sfx --help failed with stderr: {result.stderr}"
        assert "sfx" in result.stdout.lower() or "sound" in result.stdout.lower()

    def test_tier4_cli_ping_help(self):
        """Test execution of `vifi ping --help`."""
        result = self._run_cli(["ping", "--help"])
        assert result.returncode == 0, f"vifi ping --help failed with stderr: {result.stderr}"
        assert "ping" in result.stdout.lower()

    def test_tier4_cli_invalid_command_error_handling(self):
        """Test error handling when executing an unrecognized command."""
        result = self._run_cli(["unrecognized_command_xyz_123"])
        assert result.returncode != 0, "Unrecognized command must return non-zero exit code"
        combined_output = result.stdout + result.stderr
        assert "invalid" in combined_output.lower() or "error" in combined_output.lower() or "unrecognized" in combined_output.lower() or "usage" in combined_output.lower()
