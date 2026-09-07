"""Live verification of the materials-upload SigV4 fix (2026-08-07).

Reproduces the reported defect end-to-end against the deployed events-dev
Lambda: a UGL mints an upload URL for their led group's event, then the file
is PUT with a browser-style Content-Type header — the exact combination that
403'd (SignatureDoesNotMatch) while the URLs were SigV2.

Invokes the function directly with synthesized authorizer claims (the Cognito
authorizer needs a human password — same approach as the other verify tools).
Self-cleaning: deletes the uploaded object; no material row is ever confirmed,
so nothing becomes portal-visible.

Run:  python3 infra/tools/verify_materials_sigv4_deploy.py
"""
import json
import os
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import boto3

REGION = "us-east-1"
FN = "events-dev"
EVENT_ID = "ev-9cf50260-33b7-4b84-8af4-6bff514749e9"  # AWS meetup Kolkata (TBD)
UGL = {"sub": "smoke-ugl-sigv4", "role": "UserGroupLeader",
       "email": "ugl@smoke.test",
       "led_group_id": "g-41b20274-987b-4472-bc88-5180132572fc"}
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

lam = boto3.client("lambda", region_name=REGION)
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")


def invoke(method, path, body=None):
    event = {"httpMethod": method, "path": path, "queryStringParameters": None,
             "headers": {}, "requestContext": {"authorizer": {"claims": UGL}}}
    if body is not None:
        event["body"] = json.dumps(body)
    resp = lam.invoke(FunctionName=FN, Payload=json.dumps(event).encode())
    out = json.loads(resp["Payload"].read())
    return out.get("statusCode"), json.loads(out.get("body") or "{}")


def put(url, data, content_type=None):
    # `url` is a pre-signed S3 PUT URL returned by the Lambda under test, so it is
    # AWS-generated rather than operator input -- but it arrives in a response body
    # and goes straight to urlopen, which accepts file:// and custom schemes. This
    # call site carried no suppression and no guard at all, which is why bandit
    # reported it (B310) while the other two only tripped the tool-syntax mismatch.
    if not str(url).startswith("https://"):
        raise ValueError(f"refusing non-https presigned URL: {str(url)[:60]}")
    req = urllib.request.Request(url, data=data, method="PUT")  # noqa: S310  # nosec B310
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req) as r:  # noqa: S310  # nosec B310 - https checked above
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return -1  # connection reset — how the SigV2 403 surfaced mid-stream


SIZE = 42 * 1024 * 1024
data = os.urandom(SIZE)

# 1. Mint as the UGL (authz was never the problem — re-assert it).
sc, body = invoke("POST", f"/events/{EVENT_ID}/materials/upload-url",
                  {"fileName": "sigv4-verify.pptx", "sizeBytes": SIZE})
check("UGL mint -> 200", sc == 200, f"got {sc}")
if sc != 200:
    raise SystemExit(1)

# 2. The URL itself must be SigV4 and must sign the declared length.
q = parse_qs(urlparse(body["url"]).query)
check("URL is SigV4", q.get("X-Amz-Algorithm") == ["AWS4-HMAC-SHA256"],
      str(q.get("X-Amz-Algorithm")))
signed = (q.get("X-Amz-SignedHeaders") or [""])[0].split(";")
check("declared size is a signed header", "content-length" in signed, str(signed))

# 3. The reported scenario: 42 MB PUT with the PowerPoint Content-Type.
st = put(body["url"], data, PPTX)
check("42MB PUT with pptx Content-Type -> 200", st == 200, f"got {st}")

# 4. The new enforcement: same URL, wrong number of bytes -> rejected.
st = put(body["url"], data[: 1024 * 1024], PPTX)
check("size-mismatch PUT rejected", st in (400, 403, -1), f"got {st}")

# 5. Cleanup — the object; no material row was ever created.
sts = boto3.client("sts", region_name=REGION)
bucket = urlparse(body["url"]).netloc.split(".s3")[0]
boto3.client("s3", region_name=REGION).delete_object(
    Bucket=bucket, Key=body["key"])
check("cleanup: object deleted", True, f"s3://{bucket}/{body['key']}")

failed = results.count(False)
print(f"\n{len(results) - failed}/{len(results)} checks passed")
raise SystemExit(1 if failed else 0)
