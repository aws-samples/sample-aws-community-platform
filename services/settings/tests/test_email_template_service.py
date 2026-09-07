"""EmailTemplateService tests (US-8.5)."""
import pytest
from _conventions.errors import NotFoundError


def test_list_templates_returns_defaults_when_empty(ctx):
    out = ctx.email_template_service.list_templates()
    assert out["count"] >= 3
    ids = {t["id"] for t in out["items"]}
    assert "tpl-welcome" in ids


def test_update_template_overrides_default(ctx):
    out = ctx.email_template_service.update_template("tpl-welcome", {"subject": "Hey there!"}, actor="admin-1")
    assert out["subject"] == "Hey there!"
    listed = ctx.email_template_service.list_templates()
    updated = next(t for t in listed["items"] if t["id"] == "tpl-welcome")
    assert updated["subject"] == "Hey there!"


def test_update_template_unknown_id_raises_not_found(ctx):
    with pytest.raises(NotFoundError):
        ctx.email_template_service.update_template("tpl-nonexistent", {"subject": "x"}, actor="admin-1")


def test_update_template_publishes_event(ctx):
    ctx.email_template_service.update_template("tpl-welcome", {"body": "new body"}, actor="admin-1")
    assert ctx.events.published[-1]["type"] == "SettingsChanged"
