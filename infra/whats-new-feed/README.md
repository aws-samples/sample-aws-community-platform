# What's New in AWS — Feed Mirror Contract

**Applies to**: Module 11 (What's New in AWS Feed), stories US-11.1–11.7
**Consumer**: `frontend/src/features/whats-new/` in the AWS Community Portal SPA
**Status of this component**: **OUTSIDE application scope** (decision DW-7)

---

## Why this mirror exists

The portal fetches the feed **directly from the browser** with client-side JavaScript. There is no backend service, no server-side fetching, no caching and no persistence — that is the requirement (US-11.7), not an implementation shortcut.

A browser can only fetch a cross-origin URL if that origin returns an `Access-Control-Allow-Origin` header. **Measured on 2026-08-10, no AWS-published feed does:**

| Feed | HTTP | `Access-Control-Allow-Origin` |
|---|---|---|
| `https://aws.amazon.com/about-aws/whats-new/recent/feed/` | 200 | absent |
| `https://feeds.feedburner.com/AmazonWebServicesBlog` | 200 | absent |

Pointing the portal straight at either URL produces a feature that is permanently empty. Worse, a browser CORS rejection reaches JavaScript as an opaque `TypeError` with **no status code**, so it is indistinguishable from an outage — which is why this mirror exists rather than a "just configure the AWS URL" instruction.

So: someone republishes the upstream feed at a URL that **does** send CORS headers, and an Administrator points the portal at that URL in Settings.

## Scope boundary

Creating, hosting and refreshing this mirror is **not** part of the portal application (DW-7). This repository contains no publisher Lambda, no scheduler, no refresh script and no S3/CloudFront template for it. What this repository provides is:

- **this contract** — the shape the mirror must satisfy
- **`whats-new-sample.xml`** — a valid reference feed, also used as the portal's parser test fixture

The portal reads the feed URL from the `whatsNewFeedUrl` setting (Administrator → Settings), already shipped and deployed in the Settings service. Any CORS-enabled URL works; this mirror is simply the expected one.

---

## Hosting requirements

1. **Serve over HTTPS.** The portal is HTTPS; a plain-HTTP feed is blocked as mixed content.
2. **Send `Access-Control-Allow-Origin`.** Either the portal's CloudFront domain or `*`. The feed is public AWS announcement content, so `*` is acceptable.
3. **Send an XML content type** — `application/rss+xml` or `text/xml`.
4. **Return the feed body on a plain `GET`**, no authentication. The portal deliberately sends **no** credentials and **no** `Authorization` header (DW-13): the feed lives on a third-party origin, and attaching the caller's portal token to it would leak a bearer token to whatever URL an Administrator typed in.
5. **Do not redirect to a non-CORS origin.** A redirect target must also send the CORS header, or the browser blocks the request.

A typical implementation is an S3 object fronted by CloudFront, with a response headers policy adding the CORS header. Keep cache TTL low or zero — the portal re-fetches on every page load by requirement, and a long CDN TTL would silently reintroduce the caching that US-11.7 excludes.

### S3 + CloudFront: attaching the CORS header

This is the step that is easy to miss. Uploading the XML to S3 and putting CloudFront in front of it gives you a working URL that returns `200 text/xml` — and is **still unusable from a browser**, because neither service adds `Access-Control-Allow-Origin` by default. The portal then shows its "could not be reached / may not allow cross-origin requests" state even though `curl` looks perfectly healthy. Verify with the header check in the *Verifying a mirror* section below, not with a browser address bar or a plain `curl`.

The simplest fix is CloudFront's **managed `SimpleCORS` response headers policy**, which adds `Access-Control-Allow-Origin: *` to responses:

- **Policy ID**: `60669652-455b-4ae9-85a4-c4c02393f86c`
- Console: distribution → **Behaviors** → edit the behavior → **Response headers policy** → `SimpleCORS`
- CLI: include `ResponseHeadersPolicyId` on the cache behavior in `aws cloudfront update-distribution`

```bash
# Confirm which behaviour needs the policy, then verify after applying:
curl -sS -D - -o /dev/null -H 'Origin: https://<portal-domain>' <FEED_URL> \
  | grep -i access-control-allow-origin
# expected: access-control-allow-origin: *
```

The portal issues a **simple** cross-origin GET — no preflight — so `SimpleCORS` is sufficient. The heavier `CORS-With-Preflight` policy (`5cc3b908-e619-4b99-88e5-2cf7f45965bd`) is not needed. Response headers policies apply to cache hits as well as misses, so no invalidation is required for the header to take effect; you only need `aws cloudfront create-invalidation` after changing the **XML content** itself.

Note that both managed policies defer to the origin: if S3 already returns `Access-Control-Allow-Origin`, CloudFront passes that through instead. So an S3 bucket CORS configuration is an alternative, but it is the fiddlier route — S3 only emits the header when the request carries `Origin`, which means CloudFront must also forward that header (managed origin request policy `CORS-S3Origin`) and include it in the cache key. Prefer the response headers policy unless you need per-origin allow-listing.

### Refresh

Upstream carries the 100 most recent announcements and updates continuously. Refresh cadence is the mirror owner's decision. If the mirror goes stale the portal keeps working — it renders whatever the feed contains, and stale content is not an error state it can detect.

---

## Required feed format

**RSS 2.0.** The portal parses RSS 2.0 only (DW-4); an Atom document is rejected with a clear error. Minimum structure:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>AWS What's New - Community Portal Mirror</title>
    <link>https://aws.amazon.com/about-aws/whats-new/recent/</link>
    <description>Mirror of recent AWS announcements.</description>
    <item>
      <guid isPermaLink="false">stable-unique-id</guid>
      <title>Announcement title</title>
      <link>https://aws.amazon.com/about-aws/whats-new/2026/08/...</link>
      <pubDate>Fri, 07 Aug 2026 21:11:00 GMT</pubDate>
      <category>Compute</category>
      <category>Amazon EC2</category>
      <description><![CDATA[<p>Announcement body, may contain HTML.</p>]]></description>
    </item>
  </channel>
</rss>
```

### Field mapping

| Portal element | Source | Notes |
|---|---|---|
| Row title | `<title>` | Plain text |
| Row summary | derived from `<description>` | Portal strips markup and truncates to ~150 chars on a word boundary — publish the full text, do not pre-truncate |
| Expanded details | `<description>` | May contain HTML. **Always sanitized by the portal** before rendering (DV-1) |
| Sort order | `<pubDate>` | RFC-822. Newest first; items with no or unparseable `pubDate` sort last but remain visible |
| Category filter + badges | `<category>` | **One element per label** — see normalization below |
| "Read full announcement on AWS ↗" | `<link>` | Opens in a new tab |
| React identity | `<guid>`, else `<link>` | Should be stable across refreshes so expanded rows do not jump |

---

## Normalization the mirror must perform (DW-5)

This is the one place the mirror must **not** be a byte-faithful copy.

Upstream packs its entire taxonomy into a **single** `<category>` element as a comma-joined machine string:

```xml
<!-- UPSTREAM — do not republish as-is -->
<category>marketing:marchitecture/compute,general:products/amazon-ec2</category>
```

Republished unchanged, the portal's category filter offers users a single option reading `marketing:marchitecture/compute,general:products/amazon-ec2`. The mirror must instead emit **one `<category>` element per label, carrying a human-readable name**:

```xml
<!-- MIRROR — required shape -->
<category>Compute</category>
<category>Amazon EC2</category>
```

This is what RSS 2.0 intends and what US-11.4 assumes.

### Deriving labels

Upstream tokens come in two families:

| Family | Example token | Meaning | Example label |
|---|---|---|---|
| `marketing:marchitecture/<area>` | `marketing:marchitecture/compute` | service area | `Compute` |
| `general:products/<slug>` | `general:products/amazon-ec2` | product | `Amazon EC2` |

Mechanical derivation works for most tokens: take the part after the final `/`, replace hyphens with spaces, title-case, and correct known acronyms and casing (`aws` → `AWS`, `ec2` → `EC2`, `msk` → `MSK`, `s3` → `S3`, `iam` → `IAM`).

**Unmapped slugs must be emitted as the raw token, not dropped** (DW-6). AWS adds services faster than any mapping stays current, and a visibly wrong label such as `general:products/aws-newthing` gets reported and fixed, whereas a silently dropped one just erodes filter coverage with nobody noticing.

### Two things that will bite

**Labels may legitimately contain commas.** `Security, Identity & Compliance` is a real label. The portal therefore does **not** split category text on commas unless every comma-separated part looks like a machine taxonomy token — one containing both `:` and `/` (decision DW-12, a defensive fallback in case the portal is pointed at raw upstream). Do not assume commas are safe separators anywhere in this pipeline.

**Items may legitimately have no category.** 8 of 100 upstream items carry none. Emit no `<category>` element rather than an empty one; an empty element would put a blank entry in the filter dropdown.

---

## Reference sample

`whats-new-sample.xml` in this directory is a valid, correctly normalized 9-item feed. It doubles as the portal's parser test fixture (DW-15) — the tests read this exact file, so it and the contract cannot drift apart.

It deliberately includes cases a real feed will produce: entity-escaped and CDATA-wrapped descriptions, an item out of chronological order, an item with no `<category>`, very short and long descriptions, ampersands in a title, a category label containing a comma, and an item with no `<pubDate>`. Anything that parses this sample correctly will handle the real feed.

**Note**: the sample's item content is written for this repository. It is not real AWS announcement text and should not be published as though it were. Replace it with mirrored upstream content before serving it to users.

## Verifying a mirror

```bash
# 1. CORS header present?
curl -sS -D - -o /dev/null -H 'Origin: https://<portal-domain>' <FEED_URL> \
  | grep -i access-control-allow-origin

# 2. Valid RSS 2.0 with items?
curl -sS <FEED_URL> | python3 -c "import sys,xml.etree.ElementTree as ET; \
r=ET.fromstring(sys.stdin.buffer.read()); \
print('root:', r.tag, r.get('version')); \
print('items:', len(r.find('channel').findall('item')))"

# 3. Categories normalized? Expect several elements with readable labels,
#    NOT one element containing 'marketing:marchitecture/...'
curl -sS <FEED_URL> | grep -o '<category>[^<]*</category>' | head -20
```

Then set the URL in the portal: **Administrator → Settings → What's New in AWS Feed**. If the feed is unreachable or not CORS-enabled, the page says so explicitly rather than showing an empty list.
