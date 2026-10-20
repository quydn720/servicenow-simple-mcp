"""Runbooks stay in sync with the alert rules, the deployment guide and the code."""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[1]
RUNBOOKS = (ROOT / "docs" / "runbooks.md").read_text()


def anchors(markdown: str) -> set[str]:
    """GitHub-style heading slugs."""
    slugs = set()
    for heading in re.findall(r"^#{1,6} (.+)$", markdown, re.M):
        slug = re.sub(r"[^\w\s-]", "", heading.strip().lower())
        slugs.add(re.sub(r"\s", "-", slug))
    return slugs


def rules():
    return yaml.safe_load((ROOT / "deploy" / "monitoring" / "alerts.yml").read_text())["groups"][0]["rules"]


def test_every_alert_links_to_an_existing_runbook_section():
    available = anchors(RUNBOOKS)
    for rule in rules():
        link = rule["annotations"]["runbook"]
        path, _, anchor = link.partition("#")
        assert path == "docs/runbooks.md", rule["alert"]
        assert anchor in available, f"{rule['alert']} links to missing #{anchor}"


def test_every_alert_is_named_in_the_runbooks():
    for rule in rules():
        assert f"`{rule['alert']}`" in RUNBOOKS, rule["alert"]


def test_links_into_the_deployment_guide_resolve():
    deployment = anchors((ROOT / "docs" / "deployment.md").read_text())
    for anchor in re.findall(r"\(deployment\.md#([\w-]+)\)", RUNBOOKS):
        assert anchor in deployment, anchor


def test_every_setting_named_in_the_runbooks_exists():
    code = " ".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    for setting in set(re.findall(r"\b(MCP_[A-Z_]+|FORWARDED_ALLOW_IPS)\b", RUNBOOKS)):
        base = setting.removesuffix("_FILE")
        assert setting == "FORWARDED_ALLOW_IPS" or base in code or setting in code, setting
