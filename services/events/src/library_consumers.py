"""EventBridge consumer for ContributionApproved — Path 2 Library opt-in (US-2.24).

The Contributions service publishes ContributionApproved when a CL/UGL approves
a member submission. When addToLibrary=True, this consumer creates a Library
resource. Failures are silent to the caller (EventBridge redelivers via DLQ)
but surfaced via the LibraryContributionConsumerFailures CloudWatch metric.
"""
from __future__ import annotations

from _conventions.logger import get_logger, log

_logger = get_logger("events.library_consumers")


class ContributionApprovedConsumer:
    """Consume ContributionApproved events and create Library resources (BR-LIB-P7)."""

    def __init__(self, library_service, idempotency=None):
        self._library = library_service
        self._idem = idempotency

    def handle(self, envelope: dict) -> dict:
        # Extract payload from EventBridge envelope.
        # The contributions service wraps the payload in a platform envelope:
        # {"id":..., "type":..., "data": {"contributionId":..., "addToLibrary":...}}
        # The actual fields are under "data".
        detail = envelope.get("detail") or {}
        raw = detail if isinstance(detail, dict) and detail else envelope

        # Unwrap platform envelope
        if isinstance(raw.get("data"), dict):
            payload = raw["data"]
        else:
            payload = raw

        contribution_id = payload.get("contributionId") or payload.get("submissionId")
        add_to_library = bool(payload.get("addToLibrary", False))

        if not add_to_library:
            return {"contributionId": contribution_id, "ignored": True}

        if not contribution_id:
            log(_logger, 30, "ContributionApproved without contributionId — ignoring")
            return {"contributionId": None, "ignored": True}

        result: dict = {}

        def run():
            try:
                self._library.add_from_contribution(payload)
                result["added"] = True
            except Exception as exc:  # noqa: BLE001
                # Fail silently — EventBridge will redeliver; metric surfaces
                # the failure operationally (LibraryContributionConsumerFailures).
                log(_logger, 40, "Failed to add contribution to Library",
                    contributionId=contribution_id, error=str(exc))
                _emit_failure_metric()
                result["added"] = False

        envelope_id = envelope.get("id") or contribution_id
        if self._idem and envelope_id:
            self._idem.run_once(envelope_id, run)
        else:
            run()

        return {"contributionId": contribution_id, "added": result.get("added", False)}


def _emit_failure_metric() -> None:
    """Emit a CloudWatch custom metric for the alarm (service-events-app.yaml)."""
    try:
        import boto3
        import os
        stage = os.environ.get("STAGE", "dev")
        boto3.client("cloudwatch").put_metric_data(
            Namespace=f"CommunityPortal/events-{stage}",
            MetricData=[{
                "MetricName": "LibraryContributionConsumerFailures",
                "Value": 1,
                "Unit": "Count",
            }],
        )
    except Exception as exc:  # noqa: BLE001
        log(_logger, 30, "metric emit failed (LibraryContributionConsumerFailures)", error=str(exc))
