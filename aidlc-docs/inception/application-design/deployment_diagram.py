#!/usr/bin/env python3
"""Render the AS-BUILT deployment architecture for the AWS Community Portal.

Regenerates ./community-portal-deployment.png

    pip install diagrams          # only for its bundled official AWS icon set
    brew install graphviz         # provides `dot`
    python3 deployment_diagram.py

WHY THIS EMITS DOT DIRECTLY instead of using the `diagrams` DSL
---------------------------------------------------------------
The `diagrams` package is used ONLY as a source of official AWS icon PNGs. The
graph itself is written as Graphviz DOT because this topology has ~30 edges and
a third of them point "backwards" (CDC streams back into the Lambdas, SQS back
into a consumer, GuardDuty verdicts back onto the event bus). Handing those to
the DSL let graphviz choose ranks, and it scattered the clusters and produced a
7000px-tall ribbon with labels overlapping. Explicit `rank=same` groups pin each
architectural layer, so the backward edges can be drawn honestly without
dragging the layout apart.

EVERY node was verified against infra/ (root-template.yaml, keys.yaml,
foundation.yaml, api-edge.yaml, seed.yaml, services/*.yaml) rather than against
the original design intent. The counts in the labels are real resource counts
from a parse of those templates: 274 resources across 21 stacks.

WHAT THIS REVISION REMOVED, and why — the previous render showed a design that
was never built, or that has since been dismantled:

  * AWS WAF          — no AWS::WAFv2::WebACL exists in any template. Descoped
                        (architecture decision AC-1).
  * NAT Gateway and  — deleted ~2026-08-30 together with PublicSubnetA/B and
    public subnets      the InternetGateway. The VPC now has NO route to the
                        internet at all. This is the single biggest change: the
                        old picture showed an egress path labelled "MS Teams
                        API" that cannot exist any more.
  * Secrets Manager  — all Secrets Manager use was deleted. The seeder now
                        generates the admin password, sets it PERMANENT and
                        discards it; the operator arrives via "Forgot password".
  * Amazon Bedrock   — NOT deployed. No Bedrock resource, no bedrock:InvokeModel
                        grant, no bedrock VPC endpoint. The only trace is a
                        "bedrockModel" *string* among the Settings service
                        defaults (services/settings/src/models.py), which is
                        stored configuration, not an invocation.
  * Search, Help     — never built as services. `services/` holds exactly 8:
    Assistant,          identity-access, member-profiles, events, forums,
    Notifications,      certifications, contributions-scoring, announcements,
    Analytics           settings. Search became the OpenSearch collection plus
                        two DynamoDB-stream indexer Lambdas; the scoring rollup
                        absorbed Analytics; email is sent directly by
                        identity-access.

WHAT THIS REVISION ADDED — deployed, but missing from the old render:

  * A second, PRIVATE REST API carrying all internal service-to-service fan-out
    over the execute-api interface endpoint. The public API is for browsers
    only. This is load-bearing topology, not a detail.
  * Step Functions (JobsStateMachine) driving the nightly jobs.
  * 3 KMS customer managed keys (DynamoDB, SQS, CloudWatch Logs).
  * GuardDuty Malware Protection on FileShareBucket, with verdicts delivered
    back onto the event bus.
  * VPC Flow Logs, the SNS ops-alarm topic, and both log-destination buckets
    (AccessLogBucket, CloudFrontLogBucket).
  * The bootstrap custom resources (seeder, SPA deployer, AZ selector) — the
    only Lambdas that sit OUTSIDE the VPC.

OpenSearch Serverless is drawn dashed because every one of its resources is
condition-gated on EnableSemanticSearch, which defaults to 'false'. It is wired
and deployable, not on by default.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# --------------------------------------------------------------------------
# Icon resolution. `diagrams` ships the official AWS icon set; we only borrow
# the PNG paths from it.
# --------------------------------------------------------------------------
from diagrams.aws.analytics import ElasticsearchService
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb, DynamodbStreams
from diagrams.aws.devtools import XRay
from diagrams.aws.engagement import SimpleEmailServiceSes
from diagrams.aws.general import Users
from diagrams.aws.integration import SNS, SQS, Eventbridge, StepFunctions
from diagrams.aws.management import Cloudformation, Cloudwatch
from diagrams.aws.network import APIGateway, CloudFront, Endpoint
from diagrams.aws.security import Cognito, Guardduty, KeyManagementService
from diagrams.aws.storage import S3

OUT_BASE = "community-portal-deployment"
DOT_PATH = f"{OUT_BASE}.dot"
PNG_PATH = f"{OUT_BASE}.png"


def icon(cls) -> str:
    """Absolute path to the bundled official AWS icon for a diagrams class."""
    path = cls._load_icon(cls)
    if not os.path.exists(path):
        raise FileNotFoundError(f"icon missing for {cls.__name__}: {path}")
    return path


ICON = {
    "users": icon(Users),
    "cloudfront": icon(CloudFront),
    "s3": icon(S3),
    "cognito": icon(Cognito),
    "apigw": icon(APIGateway),
    "lambda": icon(Lambda),
    "endpoint": icon(Endpoint),
    "dynamodb": icon(Dynamodb),
    "streams": icon(DynamodbStreams),
    "opensearch": icon(ElasticsearchService),
    "eventbridge": icon(Eventbridge),
    "sqs": icon(SQS),
    "sfn": icon(StepFunctions),
    "sns": icon(SNS),
    "ses": icon(SimpleEmailServiceSes),
    "kms": icon(KeyManagementService),
    "guardduty": icon(Guardduty),
    "cloudwatch": icon(Cloudwatch),
    "xray": icon(XRay),
    "cfn": icon(Cloudformation),
}

# --------------------------------------------------------------------------
# Palette. Kept close to the previous render so the diagram still reads as a
# revision of the same document rather than an unrelated picture.
# --------------------------------------------------------------------------
TINT_BLUE = ("#eaf3fb", "#7098bb")
TINT_GREEN = ("#eef6e8", "#8aab74")
TINT_GREY = ("#f2f2f2", "#9a9a9a")
TINT_AMBER = ("#fdf4e3", "#c9a227")
TINT_RED = ("#fdeceb", "#c0564f")

C_REQ = "#1f6f3f"      # synchronous request path
C_INTERNAL = "#d97706"  # async / internal fan-out
C_DATA = "#1f3f8f"      # data plane
C_SEC = "#b03a2e"       # security
C_PLUMB = "#8a8a8a"     # encryption / telemetry plumbing

ICON_PX = 62


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def node(nid: str, icon_key: str, caption: str, sub: str = "") -> str:
    """An icon with a caption underneath, as an HTML-like label."""
    lines = "".join(
        f'<TR><TD><FONT POINT-SIZE="11.5"><B>{esc(l)}</B></FONT></TD></TR>'
        for l in caption.split("\n")
    )
    if sub:
        lines += "".join(
            f'<TR><TD><FONT POINT-SIZE="10" COLOR="#444444">{esc(l)}</FONT></TD></TR>'
            for l in sub.split("\n")
        )
    # NOTE: WIDTH/HEIGHT are illegal on <IMG> in graphviz — they belong on the
    # enclosing <TD> together with FIXEDSIZE. Putting them on <IMG> is silently
    # downgraded to a warning and the icon renders at its native ~256px, which
    # is what produced a 7649x4477 first render.
    return (
        f'  {nid} [label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="1">'
        f'<TR><TD FIXEDSIZE="TRUE" WIDTH="{ICON_PX}" HEIGHT="{ICON_PX}">'
        f'<IMG SCALE="TRUE" SRC="{ICON[icon_key]}"/></TD></TR>{lines}</TABLE>>];\n'
    )


def cluster(cid: str, label: str, tint, body: str, sublabel: str = "") -> str:
    fill, pen = tint
    head = esc(label)
    if sublabel:
        head += f'<BR/><FONT POINT-SIZE="12" COLOR="#555555">{esc(sublabel)}</FONT>'
    return (
        f"  subgraph cluster_{cid} {{\n"
        f"    style=filled; fillcolor=\"{fill}\"; color=\"{pen}\"; penwidth=1.6;\n"
        f"    labelloc=t; labeljust=l; margin=18;\n"
        f"    label=<<FONT POINT-SIZE=\"15\"><B>{head}</B></FONT>>;\n"
        f"{body}"
        f"  }}\n\n"
    )


def edge(src: str, dst: str, label: str = "", color: str = "#333333",
         style: str = "solid", rank: bool = True, width: str = "1.4") -> str:
    attrs = [f'color="{color}"', f'penwidth={width}', f'style={style}']
    if label:
        attrs.append(f'label=<<FONT POINT-SIZE="10.5" COLOR="{color}">'
                     f'{esc(label).replace(chr(10), "<BR/>")}</FONT>>')
    if not rank:
        attrs.append("constraint=false")
    return f"  {src} -> {dst} [{', '.join(attrs)}];\n"


# ==========================================================================
# Graph
# ==========================================================================
title = (
    "AWS Community Portal &#8212; AS-BUILT Deployment Architecture"
)
subtitle = (
    "single region &#183; 2 AZs &#183; 21 CloudFormation stacks &#183; 22 Lambdas "
    "&#183; 18 DynamoDB tables &#183; private subnets only (no InternetGateway, no NatGateway)"
)

dot = [
    "digraph community_portal {\n",
    "  compound=true;\n",
    "  newrank=true;\n",
    "  rankdir=TB;\n",
    "  splines=spline;\n",
    "  concentrate=false;\n",
    "  nodesep=0.55;\n",
    "  ranksep=1.05;\n",
    "  pad=0.5;\n",
    "  bgcolor=white;\n",
    "  labelloc=t;\n",
    f'  label=<<FONT POINT-SIZE="30"><B>{title}</B></FONT><BR/>'
    f'<FONT POINT-SIZE="16" COLOR="#444444">{subtitle}</FONT><BR/> >;\n',
    '  node [shape=plaintext, margin=0.04, fontname="Helvetica"];\n',
    '  edge [fontname="Helvetica", arrowsize=0.85];\n\n',
]

# ---- actors --------------------------------------------------------------
dot.append(node("users", "users", "Members / Group Leaders\nUGLs / Admins"))

# ---- edge / content delivery --------------------------------------------
body = (
    node("cloudfront", "cloudfront", "CloudFront SpaDistribution",
         "OAI origin access\nManaged-SecurityHeadersPolicy\nManaged-CachingOptimized\n403/404 -> /index.html")
    + node("spa_bucket", "s3", "SpaBucket", "React + Vite SPA\nprivate, OAI-only read")
    + node("cf_logs", "s3", "CloudFrontLogBucket", "prefix cloudfront/")
)
dot.append(cluster("edge", "Edge / Content delivery", TINT_BLUE, body,
                   "AWS-managed, outside the VPC"))

# ---- identity ------------------------------------------------------------
body = node("cognito", "cognito", "Cognito User Pool",
            "+ UserPoolClient\nJWT + custom-auth OTP\nTokenClaimsFunction trigger")
dot.append(cluster("identity", "Identity", TINT_RED, body, "AWS-managed"))

# ---- api layer -----------------------------------------------------------
body = (
    node("public_api", "apigw", "PUBLIC Api (REST)",
         "Cognito authorizer\n100 rps / 200 burst\nX-Ray + access logs")
    + node("private_api", "apigw", "PRIVATE Api (REST)",
           "EndpointConfiguration: PRIVATE\nreachable only via the\nexecute-api endpoint\n1000 rps - internal fan-out")
)
dot.append(cluster("api", "API Gateway — 2 REST APIs", TINT_BLUE, body,
                   "browser traffic and internal fan-out are separated"))

# ---- the VPC -------------------------------------------------------------
subnet_body = (
    node("svc_identity", "lambda", "Identity & Access",
         "3 fns: api, user-indexer,\nuser-export")
    + node("svc_profiles", "lambda", "Member Profiles",
           "3 fns: api, indexer, export")
    + node("svc_events", "lambda", "Events", "1 fn")
    + node("svc_forums", "lambda", "Forums", "1 fn")
    + node("svc_certs", "lambda", "Certifications", "1 fn")
    + node("svc_contrib", "lambda", "Contributions & Scoring",
           "6 fns: api, consumer, award,\nrollup, sweep, export")
    + node("svc_annc", "lambda", "Announcements", "1 fn")
    + node("svc_settings", "lambda", "Platform / Settings",
           "2 fns: api, job-runner")
    + node("token_claims", "lambda", "TokenClaimsFunction",
           "Cognito token trigger")
)
endpoint_body = (
    node("gw_ep", "endpoint", "Gateway endpoints", "S3, DynamoDB")
    + node("if_ep", "endpoint", "Interface endpoints / PrivateLink",
           "events, lambda, cognito-idp,\nemail (SES), monitoring, ssm,\nstates, execute-api, aoss-data")
)
vpc_body = (
    cluster("subnets",
            "Private subnets — 10.20.32.0/20 + 10.20.48.0/20",
            TINT_GREEN, subnet_body, "19 of the 22 Lambdas run here")
    + cluster("endpoints", "VPC endpoints — 11", TINT_GREY, endpoint_body,
              "the only way out of the VPC")
)
dot.append(cluster("vpc", "Amazon VPC — 2 AZs", TINT_BLUE, vpc_body,
                   "no InternetGateway, no NatGateway, no public subnets"))

# ---- data ----------------------------------------------------------------
body = (
    node("dynamodb", "dynamodb", "DynamoDB — 18 tables",
         "table-per-service + per-service\nidempotency table\nSSE-KMS (CMK), PITR")
    + node("streams", "streams", "DynamoDB Streams",
           "NEW_AND_OLD_IMAGES on 8 tables")
    + node("buckets", "s3", "S3 — 3 buckets",
           "FileShareBucket (versioned,\nno auto-expiry)\nUserExportBucket (1-day)\nAccessLogBucket (90-day)")
    + node("opensearch", "opensearch", "OpenSearch Serverless",
           "vector / semantic search\nOPTIONAL: gated on\nEnableSemanticSearch (default false)")
)
dot.append(cluster("data", "Data — table-per-service", TINT_BLUE, body))

# ---- async / integration -------------------------------------------------
body = (
    node("eventbus", "eventbridge", "EventBridge bus",
         "community-portal-<stage>\n13 rules")
    + node("scheduler", "eventbridge", "EventBridge Scheduler",
           "2 schedules: cert scan\nwatchdog, forums sweep")
    + node("sqs", "sqs", "SQS — 8 queues",
           "2 work queues (award, consumer)\n+ 6 DLQs - SSE-KMS (CMK)")
    + node("sfn", "sfn", "Step Functions",
           "JobsStateMachine\nnightly jobs")
)
dot.append(cluster("async", "Integration & Async", TINT_AMBER, body, "managed"))

# ---- messaging -----------------------------------------------------------
body = node("ses", "ses", "Amazon SES",
            "identity-access only:\nOTP / auth email")
dot.append(cluster("msg", "Messaging", TINT_BLUE, body, "managed"))

# ---- security & observability --------------------------------------------
body = (
    node("kms", "kms", "KMS — 3 customer managed keys",
         "DynamoDbKmsKey -> 18 tables\nSqsKmsKey -> 8 queues\nLogsKmsKey -> 13 log groups\nrotation enabled")
    + node("guardduty", "guardduty", "GuardDuty Malware Protection",
           "FileShareMalwareProtection\nQUARANTINED -> every object\nversion purged")
    + node("cloudwatch", "cloudwatch", "CloudWatch",
           "55 alarms - 13 log groups (CMK)\n20 metric filters")
    + node("flow_logs", "cloudwatch", "VPC Flow Logs", "VpcFlowLog")
    + node("xray", "xray", "X-Ray tracing",
           "both APIs + 5 service stacks")
    + node("ops_sns", "sns", "OpsAlarmTopic", "email subscription")
)
dot.append(cluster("secobs", "Security & Observability", TINT_GREY, body, "managed"))

# ---- deployment ----------------------------------------------------------
body = (
    node("root_stack", "cfn", "root-template.yaml",
         "21 stacks: keys, foundation,\napi-edge, seed, 8 x (data + app)")
    + node("seeder", "lambda", "SeederFunction",
           "admin + reference data,\npassword set PERMANENT\nthen discarded")
    + node("spa_deployer", "lambda", "SpaDeployerFunction",
           "uploads the SPA build")
    + node("az_selector", "lambda", "AzSelectorFunction",
           "picks AZs with endpoint coverage")
)
dot.append(cluster("deploy", "Deployment / bootstrap", TINT_GREY, body,
                   "the only Lambdas outside the VPC"))

# ==========================================================================
# Layers. These rank groups are what keep the diagram readable — without them
# graphviz ranks on the backward async edges and the layout collapses.
# ==========================================================================
dot.append("\n  // --- architectural layers, pinned ---\n")
layers = [
    ["users"],
    ["cloudfront", "cognito"],
    ["spa_bucket", "cf_logs", "public_api", "private_api"],
    ["svc_identity", "svc_profiles", "svc_events", "svc_forums", "svc_certs",
     "svc_contrib", "svc_annc", "svc_settings", "token_claims"],
    ["gw_ep", "if_ep"],
    ["dynamodb", "buckets", "opensearch", "eventbus", "scheduler", "sfn", "ses"],
    ["streams", "sqs", "kms", "guardduty", "cloudwatch", "flow_logs", "xray",
     "ops_sns", "root_stack", "seeder", "spa_deployer", "az_selector"],
]
for group in layers:
    dot.append("  {rank=same; " + "; ".join(group) + ";}\n")

# ==========================================================================
# Edges
# ==========================================================================
dot.append("\n  // --- synchronous request path ---\n")
dot.append(edge("users", "cloudfront", "HTTPS\n(SPA)", C_REQ))
dot.append(edge("users", "public_api", "REST /api\n(JWT)", C_REQ))
dot.append(edge("cloudfront", "spa_bucket", "OAI", C_REQ))
dot.append(edge("cloudfront", "cf_logs", "access logs", C_PLUMB, "dashed"))
dot.append(edge("public_api", "cognito", "authN", "#7d3c98", "dashed", rank=False))
dot.append(edge("cognito", "token_claims", "token trigger", "#7d3c98", "dashed"))

for svc in ("svc_identity", "svc_profiles", "svc_events", "svc_forums",
            "svc_certs", "svc_contrib", "svc_annc", "svc_settings"):
    dot.append(edge("public_api", svc, "", C_REQ, width="1.1"))

dot.append(edge("private_api", "svc_profiles",
                "internal service-to-service\nfan-out", C_INTERNAL))

dot.append("\n  // --- egress: every AWS call leaves through an endpoint ---\n")
dot.append(edge("svc_settings", "gw_ep",
                "all service Lambdas reach AWS APIs\nONLY via VPC endpoints", "#222222"))
dot.append(edge("svc_settings", "if_ep", "", "#222222"))
dot.append(edge("if_ep", "private_api", "execute-api", C_INTERNAL, "dashed", rank=False))

dot.append(edge("gw_ep", "dynamodb", "", C_DATA))
dot.append(edge("gw_ep", "buckets", "", C_DATA))
dot.append(edge("if_ep", "eventbus", "", C_INTERNAL))
dot.append(edge("if_ep", "sfn", "start execution", C_INTERNAL))
dot.append(edge("if_ep", "ses", "send email", "#2874a6"))
dot.append(edge("if_ep", "opensearch", "query", C_DATA, "dashed"))
dot.append(edge("if_ep", "cloudwatch", "metrics / logs", C_PLUMB, "dashed"))

dot.append("\n  // --- change data capture ---\n")
dot.append(edge("dynamodb", "streams", "CDC", C_DATA, "dashed"))
dot.append(edge("streams", "svc_identity", "user indexer", C_DATA, "dashed", rank=False))
dot.append(edge("streams", "svc_profiles", "member indexer", C_DATA, "dashed", rank=False))
dot.append(edge("streams", "svc_contrib", "scoring rollup", C_DATA, "dashed", rank=False))
dot.append(edge("svc_identity", "opensearch", "index documents", C_DATA, "dashed", rank=False))

dot.append("\n  // --- event-driven paths ---\n")
dot.append(edge("eventbus", "sqs", "award / domain events", C_INTERNAL))
dot.append(edge("sqs", "svc_contrib", "consumer + award worker\nBatchSize 10",
                C_INTERNAL, rank=False))
dot.append(edge("eventbus", "svc_certs", "13 rules -> targets\n(each with a DLQ)",
                C_INTERNAL, "dashed", rank=False))
dot.append(edge("eventbus", "svc_events", "", C_INTERNAL, "dashed", rank=False))
dot.append(edge("scheduler", "svc_certs", "cron", C_INTERNAL, "dashed", rank=False))
dot.append(edge("scheduler", "svc_forums", "", C_INTERNAL, "dashed", rank=False))
dot.append(edge("sfn", "svc_settings", "nightly job runner", C_INTERNAL, rank=False))

dot.append("\n  // --- security controls ---\n")
dot.append(edge("buckets", "guardduty", "object scan", C_SEC))
dot.append(edge("guardduty", "eventbus", "scan verdict", C_SEC, rank=False))
dot.append(edge("kms", "dynamodb", "encrypt", C_PLUMB, "dotted", rank=False))
dot.append(edge("kms", "sqs", "", C_PLUMB, "dotted", rank=False))
dot.append(edge("kms", "cloudwatch", "", C_PLUMB, "dotted", rank=False))
dot.append(edge("flow_logs", "cloudwatch", "", C_PLUMB, "dotted", rank=False))
dot.append(edge("cloudwatch", "ops_sns", "alarm actions", C_SEC, rank=False))
dot.append(edge("public_api", "xray", "", C_PLUMB, "dotted", rank=False))

dot.append("\n  // --- deployment / bootstrap ---\n")
dot.append(edge("root_stack", "az_selector", "deploys", C_PLUMB, "dotted", rank=False))
dot.append(edge("spa_deployer", "spa_bucket", "uploads build", C_PLUMB, "dotted", rank=False))
dot.append(edge("seeder", "cognito", "seeds admin", C_PLUMB, "dotted", rank=False))

dot.append("}\n")

# ==========================================================================
# Render
# ==========================================================================
with open(DOT_PATH, "w") as fh:
    fh.writelines(dot)

if shutil.which("dot") is None:
    sys.exit("graphviz `dot` not found on PATH — brew install graphviz")

proc = subprocess.run(
    ["dot", "-Tpng", "-Gdpi=110", DOT_PATH, "-o", PNG_PATH],
    capture_output=True, text=True,
)
if proc.returncode != 0:
    sys.stderr.write(proc.stderr)
    sys.exit(f"dot failed with {proc.returncode}")
if proc.stderr.strip():
    sys.stderr.write("graphviz warnings:\n" + proc.stderr)

os.remove(DOT_PATH)
print(f"wrote {PNG_PATH}")
