"""Minimal CloudFormation custom-resource response helper.

Packaged Lambdas don't get the inline `cfnresponse` module, so we implement the
same contract with urllib: PUT a JSON result to the pre-signed ResponseURL so the
CREATE/UPDATE/DELETE of the AWS::CloudFormation::CustomResource can complete
(otherwise the stack blocks until the 1-hour timeout).
"""
from __future__ import annotations

import json
import urllib.request

SUCCESS = "SUCCESS"
FAILED = "FAILED"


def send(event, context, status, data=None, physical_id=None, reason=None):
    """Signal CloudFormation with the outcome of a custom-resource invocation."""
    response_url = event["ResponseURL"]
    # Scheme guard (bandit B310). ResponseURL comes from the CloudFormation service
    # and is always a pre-signed https S3 URL, so this never fires in practice --
    # but it is read straight out of an event payload and handed to urlopen, and
    # urllib will happily open file:// or a custom scheme. Failing here blocks the
    # stack until its timeout, which is the correct outcome: if this URL is ever
    # not https, something is badly wrong and PUTting the payload anyway is worse.
    if not response_url.startswith("https://"):
        raise ValueError(
            f"ResponseURL must be https, refusing to send to scheme: "
            f"{response_url.split(':', 1)[0]}:")
    body = {
        "Status": status,
        "Reason": reason or f"See CloudWatch log stream: {getattr(context, 'log_stream_name', 'n/a')}",
        "PhysicalResourceId": physical_id or getattr(context, "log_stream_name", "seed-resource"),
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "NoEcho": False,
        "Data": data or {},
    }
    encoded = json.dumps(body).encode("utf-8")
    # Both `# noqa: S310` (ruff) and `# nosec B310` (bandit) are needed. They are
    # the same finding in two tools with different comment syntax; carrying only
    # the ruff one is why bandit kept reporting this line.
    req = urllib.request.Request(  # noqa: S310  # nosec B310 - scheme checked above
        response_url,
        data=encoded,
        method="PUT",
        headers={"content-type": "", "content-length": str(len(encoded))},
    )
    urllib.request.urlopen(req)  # noqa: S310  # nosec B310 - https-only, checked above
