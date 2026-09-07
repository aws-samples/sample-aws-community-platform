#!/usr/bin/env python3
"""Generate infra/api-edge.yaml — the shared API Gateway (REST) whose full route
table is derived from the frozen service contracts (contracts/services/*/openapi.yaml).

Why centralized here (not per-service stacks): a shared REST API needs a single
deployment that contains all methods. Defining every route in the API Edge stack
(which owns the Serverless::Api) means one deployment covers everything and avoids
the cross-stack "methods added but never redeployed" problem. Service teams don't
add new APIs (contracts are frozen), so this stays in lockstep by regeneration.

Each base path (first URL segment) is proxied to that service's Lambda by its
deterministic function name `<service>-<stage>` via an AWS_PROXY integration, plus
a MOCK OPTIONS method for CORS preflight. `/auth/*` is public (pre-login); all other
routes require the Cognito authorizer.

Run:  python3 infra/tools/gen_api_edge.py   (rewrites infra/api-edge.yaml)
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "contracts" / "services"

# Unauthenticated base paths. A base path maps to exactly ONE service (see
# base_to_service below), so an unauthenticated route cannot share a base path
# with an authenticated one and each public surface must be added here
# deliberately — which is the friction we want for public write paths.
#   auth          — login/register/reset/otp (Identity & Access)
#   public        — pre-login public settings read (Settings)
#   event-uploads — token-authorized presigned-PUT mint for US-2.21 external
#                   uploads (Events). It could NOT live under /public: that base
#                   path already belongs to Settings and this generator aborts on
#                   collision (Unit 4 finding F1). Write-only: one POST that mints
#                   a single-object upload URL after validating a hashed token,
#                   expiry, revocation and an upload cap. No GET, list or delete.
PUBLIC_BASES = {"auth", "public", "event-uploads"}

# Base paths emitted ONLY into the PRIVATE API, never into the internet-facing
# one. These carry no Cognito authorizer for the same reason /public does not —
# the caller is another Lambda in this account making a same-account HTTP call
# and has no JWT to present. The protection is network-level, not token-level:
# the route exists only on the PRIVATE REST API, which is reachable solely
# through the execute-api interface endpoint and whose resource policy denies
# any principal not arriving via that VPCE. There is no internet path to it.
#
#   internal — service-to-service reads of admin config that must NOT be
#              disclosed pre-login (Settings). Split out of /public/settings on
#              2026-08-28: that route is unauthenticated and internet-reachable,
#              so every field in it is world-readable. It was returning
#              allowedEmailDomains (which corporate domains may self-register —
#              recon value for targeting) and otpIntervalDays (the
#              re-verification window, i.e. how long a departed employee's
#              access persists) to anonymous callers, neither of which the
#              pre-login UI uses.
PRIVATE_ONLY_BASES = {"internal"}

if PUBLIC_BASES & PRIVATE_ONLY_BASES:
    raise SystemExit(
        "a base path cannot be both public and private-only: "
        f"{sorted(PUBLIC_BASES & PRIVATE_ONLY_BASES)}"
    )


def base_to_service() -> dict[str, str]:
    """Map first-URL-segment -> service name, derived from each contract's paths."""
    mapping: dict[str, str] = {}
    for svc_dir in sorted(CONTRACTS.iterdir()):
        if not svc_dir.is_dir():
            continue
        svc = svc_dir.name
        spec = yaml.safe_load((svc_dir / "openapi.yaml").read_text())
        for path in (spec.get("paths") or {}):
            seg = [p for p in path.split("/") if p and not p.startswith("{")]
            if not seg:
                continue
            base = seg[0]
            if base in mapping and mapping[base] != svc:
                raise SystemExit(f"base-path collision: /{base} claimed by {mapping[base]} and {svc}")
            mapping[base] = svc
    return mapping


def build() -> str:
    mapping = base_to_service()

    header = '''AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: >
  Community Portal - API Edge stack. Single shared API Gateway (REST) + Cognito
  authorizer + throttling. Full route table is GENERATED from the frozen service
  contracts by infra/tools/gen_api_edge.py (do not hand-edit routes). Each base
  path proxies to <service>-<stage> Lambda; /auth is public; OPTIONS = CORS mock.
  CloudFront + S3 serve the SPA. WAF omitted (AC-1); throttling via usage plan.

Parameters:
  Stage: { Type: String, Default: dev }
  UserPoolArn: { Type: String }
  # The execute-api interface endpoint from the foundation stack. A PRIVATE REST
  # API must name the endpoint it is reachable through.
  ExecuteApiVpcEndpointId: { Type: String }
  # CMK from the foundation stack, used by both access-log groups below. Required
  # (no Default): an empty string is not a valid KmsKeyId, so a missing value must
  # fail at deploy time rather than silently produce an unencrypted log group.
  LogsKmsKeyArn: { Type: String }
  # S3 server-access-log destination from the foundation stack (CKV_AWS_18). Both
  # buckets in this stack deliver their access logs there, alongside
  # FileShareBucket and UserExportBucket which already do. Required (no Default):
  # an empty DestinationBucketName is not valid, so a missing value must fail at
  # deploy time rather than silently produce an unlogged bucket.
  #
  # Foundation owns the destination and its AccessLogBucketPolicy (the
  # logging.s3.amazonaws.com PutObject grant), and Foundation completes before
  # this stack starts, so the grant is guaranteed to exist before S3 validates
  # the LoggingConfiguration below — no cross-stack DependsOn is needed.
  AccessLogBucketName: { Type: String }

Resources:
  Api:
    Type: AWS::Serverless::Api
    Properties:
      StageName: !Ref Stage
      TracingEnabled: true
      # MetricsEnabled so Latency and IntegrationLatency are published per API.
      # Added because migrating the fan-out to the private API raised a question
      # that could not be answered: whether the private path is slower than the
      # public one. It matters — the fan-out clients time out at 1500ms and
      # degrade SILENTLY, so a latency regression would show up as quietly
      # missing data, not as an error. Without these metrics there is nothing to
      # compare the two APIs against.
      MethodSettings:
        - { ResourcePath: '/*', HttpMethod: '*', ThrottlingBurstLimit: 200, ThrottlingRateLimit: 100, MetricsEnabled: true }
      AccessLogSetting:
        DestinationArn: !GetAtt ApiAccessLogGroup.Arn
        # $context.routeKey is an HTTP API (v2) variable and resolves to "-" on a
        # REST API, so this logged `route:"-"` for every request from the start.
        # REST APIs expose $context.resourcePath (the matched template, e.g.
        # /settings/{proxy+}) and $context.path (the concrete URL). Both are here:
        # the template tells you which integration ran, the path tells you what
        # the caller actually asked for.
        Format: '{"requestId":"$context.requestId","ip":"$context.identity.sourceIp","method":"$context.httpMethod","resource":"$context.resourcePath","path":"$context.path","status":"$context.status","latency":"$context.responseLatency"}'
      DefinitionBody:
        swagger: '2.0'
        info: { title: !Sub "community-portal-${Stage}", version: '1.0' }
        securityDefinitions:
          CognitoAuth:
            type: apiKey
            name: Authorization
            in: header
            x-amazon-apigateway-authtype: cognito_user_pools
            x-amazon-apigateway-authorizer:
              type: cognito_user_pools
              providerARNs: [ !Ref UserPoolArn ]
        # CORS on API Gateway's OWN error responses (401 from the Cognito
        # authorizer, 403, 5xx). Without these the browser blocks the response
        # and the SPA sees an opaque "Failed to fetch" instead of the real
        # status (e.g. an expired session).
        x-amazon-apigateway-gateway-responses:
          DEFAULT_4XX:
            responseParameters:
              gatewayresponse.header.Access-Control-Allow-Origin: "'*'"
              gatewayresponse.header.Access-Control-Allow-Headers: "'Authorization,Content-Type'"
          DEFAULT_5XX:
            responseParameters:
              gatewayresponse.header.Access-Control-Allow-Origin: "'*'"
              gatewayresponse.header.Access-Control-Allow-Headers: "'Authorization,Content-Type'"
        paths:
'''

    def integ(fn: str) -> str:
        # AWS_PROXY integration to <fn>-<stage> Lambda.
        return (
            "            x-amazon-apigateway-integration:\n"
            "              type: aws_proxy\n"
            "              httpMethod: POST\n"
            f"              uri: !Sub \"arn:aws:apigateway:${{AWS::Region}}:lambda:path/2015-03-31/functions/arn:aws:lambda:${{AWS::Region}}:${{AWS::AccountId}}:function:{fn}-${{Stage}}/invocations\"\n"
            "              passthroughBehavior: when_no_match\n"
        )

    def any_method(fn: str, public: bool, proxy: bool) -> str:
        s = "          x-amazon-apigateway-any-method:\n"
        s += "            produces: [ application/json ]\n"
        if proxy:
            s += "            parameters:\n"
            s += "              - { name: proxy, in: path, required: true, type: string }\n"
        if not public:
            s += "            security: [ { CognitoAuth: [] } ]\n"
        s += "            responses: {}\n"
        s += integ(fn)
        return s

    def options_method() -> str:
        # MOCK CORS preflight (no Lambda invoke). Always public.
        return (
            "          options:\n"
            "            consumes: [ application/json ]\n"
            "            produces: [ application/json ]\n"
            "            responses:\n"
            "              '200':\n"
            "                description: CORS preflight\n"
            "                headers:\n"
            "                  Access-Control-Allow-Origin: { type: string }\n"
            "                  Access-Control-Allow-Headers: { type: string }\n"
            "                  Access-Control-Allow-Methods: { type: string }\n"
            "            x-amazon-apigateway-integration:\n"
            "              type: mock\n"
            "              requestTemplates: { application/json: '{\"statusCode\": 200}' }\n"
            "              responses:\n"
            "                default:\n"
            "                  statusCode: '200'\n"
            "                  responseParameters:\n"
            "                    method.response.header.Access-Control-Allow-Origin: \"'*'\"\n"
            "                    method.response.header.Access-Control-Allow-Headers: \"'Authorization,Content-Type'\"\n"
            "                    method.response.header.Access-Control-Allow-Methods: \"'GET,POST,PUT,DELETE,OPTIONS'\"\n"
        )

    def ind2(block: str) -> str:
        # Nest method blocks one level (2 spaces) under their path key.
        return "".join(("  " + ln if ln.strip() else ln) for ln in block.splitlines(keepends=True))

    # ── The PRIVATE twin ─────────────────────────────────────────────────────
    # A second REST API carrying the SAME route table, reachable only through the
    # execute-api interface endpoint. It exists so service-to-service fan-out
    # calls stop leaving the VPC, which is what lets the NAT Gateways and the IGW
    # be deleted.
    #
    # Why a second API rather than making the existing one private: the SPA and
    # the browser reach the public API over the internet, so it has to stay
    # public. Private is an endpoint-configuration property of the API itself,
    # not something a single API can be both of.
    #
    # The route table below is the SAME `body` string emitted twice. That is
    # deliberate — generating it once and reusing it makes it impossible for the
    # public and private route tables to drift, which is the failure this
    # generator exists to prevent in the first place.
    #
    # Same CognitoAuth authorizer, same providerARNs. That is the whole reason
    # this approach needs no handler changes: requests arriving through the
    # private API still carry requestContext.authorizer.claims exactly as they do
    # today, so every service's Principal.from_claims keeps working untouched and
    # per-path authorisation is unchanged.
    private_header = '''
  # Reachable ONLY from inside the VPC, via the execute-api interface endpoint.
  PrivateApi:
    Type: AWS::Serverless::Api
    Properties:
      StageName: !Ref Stage
      TracingEnabled: true
      # NOTE the SAM spelling: singular `Type` and `VPCEndpointIds` with a
      # capital VPC. Raw CloudFormation's AWS::ApiGateway::RestApi uses `Types`
      # (plural) and `VpcEndpointIds`. Mixing them up is silently accepted by
      # neither.
      EndpointConfiguration:
        Type: PRIVATE
        VPCEndpointIds:
          - !Ref ExecuteApiVpcEndpointId
      # Deliberately far higher than the public API's 200/100. Those limits exist
      # to blunt external abuse of a public surface; this API only ever carries
      # internal fan-out, where ONE user action can trigger several calls (a
      # profile read fans out to four services). Throttling that at 100 rps would
      # turn a normal load into silent degradation, because fan_out_client
      # swallows failures and returns None.
      # MetricsEnabled here too, so private latency is directly comparable with
      # the public API's as services are migrated one at a time.
      MethodSettings:
        - { ResourcePath: '/*', HttpMethod: '*', ThrottlingBurstLimit: 2000, ThrottlingRateLimit: 1000, MetricsEnabled: true }
      # Its own log group, so private traffic can be told apart from public.
      # That separation is what later proves the fan-out has actually moved.
      AccessLogSetting:
        DestinationArn: !GetAtt PrivateApiAccessLogGroup.Arn
        # See the public API's format above: routeKey is v2-only and logged "-".
        # On this API that mattered more — the private-DNS incident was diagnosed
        # from this log group, where every entry showed a status but no path.
        Format: '{"requestId":"$context.requestId","vpce":"$context.identity.vpceId","method":"$context.httpMethod","resource":"$context.resourcePath","path":"$context.path","status":"$context.status","latency":"$context.responseLatency"}'
      DefinitionBody:
        swagger: '2.0'
        info: { title: !Sub "community-portal-private-${Stage}", version: '1.0' }
        # A private API with NO resource policy denies every request, so this is
        # required, not optional hardening. Two statements are both necessary:
        # the Deny pins access to our one VPC endpoint, and the Allow is what
        # actually permits the call — without it the default deny stands and
        # every request fails, including from inside the VPC.
        x-amazon-apigateway-policy:
          Version: '2012-10-17'
          Statement:
            - Effect: Deny
              Principal: '*'
              Action: execute-api:Invoke
              Resource: execute-api:/*
              Condition:
                StringNotEquals:
                  aws:SourceVpce: !Ref ExecuteApiVpcEndpointId
            - Effect: Allow
              Principal: '*'
              Action: execute-api:Invoke
              Resource: execute-api:/*
        securityDefinitions:
          CognitoAuth:
            type: apiKey
            name: Authorization
            in: header
            x-amazon-apigateway-authtype: cognito_user_pools
            x-amazon-apigateway-authorizer:
              type: cognito_user_pools
              providerARNs: [ !Ref UserPoolArn ]
        x-amazon-apigateway-gateway-responses:
          DEFAULT_4XX:
            responseParameters:
              gatewayresponse.header.Access-Control-Allow-Origin: "'*'"
              gatewayresponse.header.Access-Control-Allow-Headers: "'Authorization,Content-Type'"
          DEFAULT_5XX:
            responseParameters:
              gatewayresponse.header.Access-Control-Allow-Origin: "'*'"
              gatewayresponse.header.Access-Control-Allow-Headers: "'Authorization,Content-Type'"
        paths:
'''

    def emit_paths(bases) -> str:
        """Render the `paths:` entries for `bases`. Called twice with different
        base sets: the public API omits PRIVATE_ONLY_BASES entirely, the private
        API carries everything (fan-out callers use it for all routes)."""
        out = ""
        for base in sorted(bases):
            fn = mapping[base]
            # No authorizer for pre-login public routes, and none for
            # private-only routes (same-account service calls hold no JWT —
            # see PRIVATE_ONLY_BASES for why network isolation is the control).
            no_auth = base in PUBLIC_BASES or base in PRIVATE_ONLY_BASES
            # /base  and  /base/{proxy+}
            out += f"          /{base}:\n"
            out += ind2(any_method(fn, no_auth, proxy=False))
            out += ind2(options_method())
            out += f"          /{base}/{{proxy+}}:\n"
            out += ind2(any_method(fn, no_auth, proxy=True))
            out += ind2(options_method())
        return out

    public_body = emit_paths(b for b in mapping if b not in PRIVATE_ONLY_BASES)
    private_body = emit_paths(mapping)

    footer = '''
  ApiAccessLogGroup:
    Type: AWS::Logs::LogGroup
    Properties: { LogGroupName: !Sub "/apigw/community-portal-${Stage}", RetentionInDays: 30, KmsKeyId: !Ref LogsKmsKeyArn }
  PrivateApiAccessLogGroup:
    Type: AWS::Logs::LogGroup
    Properties: { LogGroupName: !Sub "/apigw/community-portal-private-${Stage}", RetentionInDays: 30, KmsKeyId: !Ref LogsKmsKeyArn }

  SpaBucket:
    Type: AWS::S3::Bucket
    DeletionPolicy: Retain
    UpdateReplacePolicy: Retain
    Properties:
      PublicAccessBlockConfiguration: { BlockPublicAcls: true, BlockPublicPolicy: true, IgnorePublicAcls: true, RestrictPublicBuckets: true }
      BucketEncryption:
        ServerSideEncryptionConfiguration: [{ ServerSideEncryptionByDefault: { SSEAlgorithm: AES256 } }]
      # S3 server access logging (CKV_AWS_18) to the foundation stack's dedicated
      # log bucket. CloudFront access logs are NOT a substitute here: CloudFront
      # records viewer READS, but the SPA deployer Lambda WRITES this bucket on
      # every deploy and the browser PUTs avatars into avatars/ via presigned
      # POST — neither passes through CloudFront, so server access logging is the
      # only place a change to this bucket's contents is recorded.
      LoggingConfiguration:
        DestinationBucketName: !Ref AccessLogBucketName
        LogFilePrefix: spa-access-logs/
      # Allow the browser to upload profile pictures straight to avatars/ via a
      # presigned POST (US-3.2). The bucket stays private (OAI-only read); the
      # presigned signature — not public access — authorises the write, and this
      # CORS rule just lets the cross-origin POST through.
      CorsConfiguration:
        CorsRules:
          - AllowedMethods: [ POST, PUT ]
            AllowedOrigins: [ "*" ]
            AllowedHeaders: [ "*" ]
            ExposedHeaders: [ ETag ]
            MaxAge: 3000

  SpaOai:
    Type: AWS::CloudFront::CloudFrontOriginAccessIdentity
    Properties: { CloudFrontOriginAccessIdentityConfig: { Comment: !Sub "community-portal-${Stage}" } }

  # Without this policy CloudFront's OAI gets AccessDenied on every object —
  # the bucket blocks all public access by design; only the OAI may read.
  SpaBucketPolicy:
    Type: AWS::S3::BucketPolicy
    Properties:
      Bucket: !Ref SpaBucket
      PolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal: { CanonicalUser: !GetAtt SpaOai.S3CanonicalUserId }
            Action: s3:GetObject
            Resource: !Sub "${SpaBucket.Arn}/*"
          # Reject any request that did not arrive over TLS. Safe for the OAI
          # read path: this is an S3 REST origin (S3OriginConfig), which
          # CloudFront reaches over HTTPS — only an S3 *website* endpoint would
          # be forced to plaintext and break here. s3:* rather than a subset
          # because the condition only ever matches plaintext, so narrowing it
          # would just leave bucket-level actions reachable in the clear. Both
          # ARNs: bare covers bucket-level actions, /* covers object-level.
          - Sid: DenyNonTlsRequests
            Effect: Deny
            Principal: "*"
            Action: s3:*
            Resource:
              - !GetAtt SpaBucket.Arn
              - !Sub "${SpaBucket.Arn}/*"
            Condition:
              Bool:
                aws:SecureTransport: false

  # Access-log destination for the CloudFront distribution (CKV_AWS_86).
  # CloudFront standard logging delivers log files via the awslogsdelivery ACL
  # grant (not a bucket policy), so ACLs must be enabled here
  # (ObjectOwnership: BucketOwnerPreferred). Public access stays fully blocked —
  # the awslogsdelivery grant is to a specific AWS canonical user, not public,
  # so BlockPublicAcls does not interfere. Logs are operational telemetry, so
  # they expire on a short cycle. SSE-S3 (AES256): CloudFront standard logging
  # does not support SSE-KMS.
  CloudFrontLogBucket:
    Type: AWS::S3::Bucket
    DeletionPolicy: Retain
    UpdateReplacePolicy: Retain
    Properties:
      OwnershipControls:
        Rules:
          - ObjectOwnership: BucketOwnerPreferred
      PublicAccessBlockConfiguration: { BlockPublicAcls: true, BlockPublicPolicy: true, IgnorePublicAcls: true, RestrictPublicBuckets: true }
      BucketEncryption:
        ServerSideEncryptionConfiguration: [{ ServerSideEncryptionByDefault: { SSEAlgorithm: AES256 } }]
      # S3 server access logging (CKV_AWS_18) to the foundation stack's dedicated
      # log bucket — a DIFFERENT bucket, so there is no recursion. Pointing a log
      # bucket at ITSELF is what creates the loop S3 warns about (each log write
      # is an access that generates another log write); delivering to the shared
      # destination is the same arrangement FileShareBucket and UserExportBucket
      # already use.
      #
      # Worth having rather than a box-tick: the objects here ARE an audit trail,
      # so recording who reads or deletes them is the tamper-detection you want on
      # this bucket specifically.
      LoggingConfiguration:
        DestinationBucketName: !Ref AccessLogBucketName
        LogFilePrefix: cloudfront-log-bucket-access-logs/
      LifecycleConfiguration:
        Rules:
          - Id: ExpireCloudFrontLogs
            Status: Enabled
            ExpirationInDays: 90
          - Id: AbortIncompleteUploads
            Status: Enabled
            AbortIncompleteMultipartUpload: { DaysAfterInitiation: 7 }

  # TLS-only enforcement for the CloudFront log destination. Note this bucket
  # receives logs via the awslogsdelivery ACL grant rather than a bucket policy,
  # so this adds a policy where there was none — the grant itself is untouched.
  # See DenyNonTlsRequests on SpaBucketPolicy for why s3:* and both ARNs.
  CloudFrontLogBucketPolicy:
    Type: AWS::S3::BucketPolicy
    Properties:
      Bucket: !Ref CloudFrontLogBucket
      PolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Sid: DenyNonTlsRequests
            Effect: Deny
            Principal: "*"
            Action: s3:*
            Resource:
              - !GetAtt CloudFrontLogBucket.Arn
              - !Sub "${CloudFrontLogBucket.Arn}/*"
            Condition:
              Bool:
                aws:SecureTransport: false

  SpaDistribution:
    Type: AWS::CloudFront::Distribution
    Properties:
      DistributionConfig:
        Enabled: true
        DefaultRootObject: index.html
        # Standard access logging to a dedicated S3 bucket (CKV_AWS_86).
        Logging:
          Bucket: !GetAtt CloudFrontLogBucket.RegionalDomainName
          Prefix: cloudfront/
          IncludeCookies: false
        Origins:
          - Id: spa-s3
            DomainName: !GetAtt SpaBucket.RegionalDomainName
            S3OriginConfig: { OriginAccessIdentity: !Sub "origin-access-identity/cloudfront/${SpaOai}" }
        DefaultCacheBehavior:
          TargetOriginId: spa-s3
          ViewerProtocolPolicy: redirect-to-https
          CachePolicyId: 658327ea-f89d-4fab-a63d-7e88639e58f6  # Managed-CachingOptimized
          ResponseHeadersPolicyId: 67f7725c-6f97-4210-82d7-5512b31e9d03  # Managed-SecurityHeadersPolicy
        # SPA client-side routing fix: the private S3 bucket returns 403 (not 404)
        # for any path that doesn't exist as an object (e.g. /events/123 on refresh).
        # CloudFront must intercept both error codes and serve index.html so React
        # Router can handle the route. ErrorCachingMinTTL: 0 prevents edge nodes
        # from caching the error across deploys.
        CustomErrorResponses:
          - ErrorCode: 403
            ResponseCode: 200
            ResponsePagePath: /index.html
            ErrorCachingMinTTL: 0
          - ErrorCode: 404
            ResponseCode: 200
            ResponsePagePath: /index.html
            ErrorCachingMinTTL: 0

Outputs:
  RestApiId: { Value: !Ref Api }
  RootResourceId: { Value: !GetAtt Api.RootResourceId }
  ApiEndpoint: { Value: !Sub "https://${Api}.execute-api.${AWS::Region}.amazonaws.com/${Stage}" }
  PrivateRestApiId: { Value: !Ref PrivateApi }
  # Same hostname SHAPE as the public API. Only usable once private DNS is
  # enabled on the execute-api endpoint — and enabling that is a VPC-WIDE switch
  # that simultaneously breaks access to every public API. Kept for the eventual
  # end state; NOT what clients should be pointed at during migration.
  PrivateApiEndpoint: { Value: !Sub "https://${PrivateApi}.execute-api.${AWS::Region}.amazonaws.com/${Stage}" }
  # THIS is the URL to migrate fan-out clients onto, one service at a time.
  #
  # The {api-id}-{vpce-id} form is a Route 53 alias created because this API
  # names the endpoint in its EndpointConfiguration.VPCEndpointIds. It resolves
  # straight to the endpoint's ENI private addresses inside the VPC, so it works
  # with private DNS OFF — which is what makes an incremental migration possible
  # at all: flipping private DNS would move every client at once and break every
  # public API call in the VPC in the same instant.
  #
  # It also needs no Host or x-apigw-api-id header, unlike the
  # *.execute-api.*.vpce.amazonaws.com form, so fan_out_client and the other
  # clients need NO code change — only this value in API_BASE_URL.
  PrivateApiVpceUrl: { Value: !Sub "https://${PrivateApi}-${ExecuteApiVpcEndpointId}.execute-api.${AWS::Region}.amazonaws.com/${Stage}" }
  SpaBucketName: { Value: !Ref SpaBucket }
  DistributionId: { Value: !Ref SpaDistribution }
  DistributionDomain: { Value: !GetAtt SpaDistribution.DomainName }
'''
    # The route table (`body`) is emitted TWICE — once per API — from the same
    # generated string, so the public and private surfaces cannot diverge.
    return header + public_body + private_header + private_body + footer


if __name__ == "__main__":
    out = REPO / "infra" / "api-edge.yaml"
    out.write_text(build())
    print(f"wrote {out}")
