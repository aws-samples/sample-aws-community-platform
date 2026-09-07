"""Install-time SPA publisher (custom resource, D7).

Uploads the built React SPA bundle (packaged alongside this Lambda under ./spa/)
to the SPA S3 bucket, then writes a runtime config.json carrying the values the
SPA reads at load time (apiEndpoint, userPoolId, userPoolClientId). This is what
points the CloudFront-hosted SPA at the freshly-created API Gateway + Cognito.

On Delete it empties the bucket (best-effort) so the bucket can be removed.
Always signals CloudFormation via cfn.send so the stack never hangs.
"""
from __future__ import annotations

import json
import mimetypes
import os
import time

import boto3
import cfn
from botocore.exceptions import ClientError

PHYSICAL_ID = "community-portal-spa"
SPA_DIR = os.path.join(os.path.dirname(__file__), "spa")

# Explicit types for assets mimetypes may miss; falls back to guess/octet-stream.
_CONTENT_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain",
}


def _content_type(key: str) -> str:
    _, ext = os.path.splitext(key)
    if ext in _CONTENT_TYPES:
        return _CONTENT_TYPES[ext]
    guessed, _ = mimetypes.guess_type(key)
    return guessed or "application/octet-stream"


def _upload_spa(s3, bucket: str) -> int:
    if not os.path.isdir(SPA_DIR):
        print(f"no SPA bundle at {SPA_DIR}; skipping asset upload")
        return 0
    count = 0
    for root, _dirs, files in os.walk(SPA_DIR):
        for name in files:
            path = os.path.join(root, name)
            key = os.path.relpath(path, SPA_DIR).replace(os.sep, "/")
            # index.html must always be revalidated; hashed assets can cache long.
            cache = "no-cache" if key == "index.html" else "public,max-age=31536000,immutable"
            s3.upload_file(
                path, bucket, key,
                ExtraArgs={"ContentType": _content_type(key), "CacheControl": cache},
            )
            count += 1
    return count


def _write_config(s3, bucket: str) -> None:
    config = {
        "apiEndpoint": os.environ["API_ENDPOINT"],
        "userPoolId": os.environ["USER_POOL_ID"],
        "userPoolClientId": os.environ["USER_POOL_CLIENT_ID"],
    }
    s3.put_object(
        Bucket=bucket,
        Key="config.json",
        Body=json.dumps(config).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-store",
    )


def _invalidate_cdn() -> None:
    """Invalidate the CloudFront cache so the new index.html/config.json are
    served immediately instead of stale edge copies."""
    dist_id = os.environ.get("DISTRIBUTION_ID", "")
    if not dist_id:
        return
    cf = boto3.client("cloudfront")
    cf.create_invalidation(
        DistributionId=dist_id,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]},
            "CallerReference": str(time.time()),
        },
    )
    print(f"created CloudFront invalidation for {dist_id}")


def _empty_bucket(s3, bucket: str) -> None:
    paginator = s3.get_paginator("list_objects_v2")
    try:
        for page in paginator.paginate(Bucket=bucket):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objs})
    except ClientError as exc:  # best-effort; never block teardown
        print(f"empty bucket ignored: {exc}")


def handler(event, context):
    request_type = event.get("RequestType", "Create")
    bucket = os.environ["SPA_BUCKET"]
    s3 = boto3.client("s3")

    try:
        if request_type == "Delete":
            _empty_bucket(s3, bucket)
            return cfn.send(event, context, cfn.SUCCESS, physical_id=PHYSICAL_ID)

        uploaded = _upload_spa(s3, bucket)
        _write_config(s3, bucket)
        _invalidate_cdn()
        print(f"published {uploaded} SPA file(s) + config.json to {bucket}")
        return cfn.send(
            event, context, cfn.SUCCESS,
            data={"FilesUploaded": uploaded},
            physical_id=PHYSICAL_ID,
        )
    except Exception as exc:  # noqa: BLE001 — must report failure to CloudFormation
        print(f"spa deploy failed: {exc}")
        return cfn.send(event, context, cfn.FAILED, physical_id=PHYSICAL_ID, reason=str(exc))
