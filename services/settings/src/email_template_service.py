"""Email template management (US-8.5). Administrator-only writes.

Templates ship with sensible defaults (models.DEFAULT_TEMPLATES) so a fresh
deploy is never empty; the repository transparently falls back to those
defaults for any template id not yet overridden in the table.
"""
from __future__ import annotations

from _conventions.errors import NotFoundError
from _conventions.validation import require_str
from models import DEFAULT_TEMPLATES, template_public


class EmailTemplateService:
    def __init__(self, repo, events):
        self._repo = repo
        self._events = events

    def list_templates(self) -> dict:
        items = self._repo.list_templates()
        out = [template_public(t) for t in items]
        return {"items": out, "count": len(out)}

    def update_template(self, template_id: str, body: dict, *, actor: str) -> dict:
        existing = self._repo.get_template(template_id)
        if existing is None:
            raise NotFoundError(message="Template not found.")
        merged = dict(existing)
        if "subject" in body:
            merged["subject"] = require_str(body["subject"], "subject", max_len=200)
        if "body" in body:
            merged["body"] = require_str(body["body"], "body", max_len=20000)
        merged["id"] = template_id
        merged.setdefault("name", existing.get("name", template_id))
        self._repo.put_template(merged)
        self._events.publish("SettingsChanged", {"changedBy": actor, "emailTemplateId": template_id})
        return template_public(merged)

    @staticmethod
    def default_template_ids() -> set[str]:
        return {t["id"] for t in DEFAULT_TEMPLATES}
