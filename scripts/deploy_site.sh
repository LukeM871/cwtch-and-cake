#!/usr/bin/env bash
# Upload site/ to the website bucket with an explicit content type and cache rule for every file,
# then remove anything that's no longer in site/. Used by GitHub Actions (and by hand if needed).
#
# Why explicit types: the AWS CLI guesses types from the operating system, and a wrong guess
# (a font or a JavaScript module sent as "binary/octet-stream") breaks a site that sends
# X-Content-Type-Options: nosniff, as this one does.
#
# Caching: photos and fonts can be cached for a long time (their names don't change);
# pages, styles and scripts are always revalidated, so a deploy is visible straight away.
#
# Usage: scripts/deploy_site.sh <bucket>
set -euo pipefail
bucket="$1"
cd "$(dirname "$0")/.."

put() { # put <pattern> <content-type> <cache-control>
  aws s3 sync site/ "s3://${bucket}/" --exclude "*" --include "$1" \
    --content-type "$2" --cache-control "$3" --only-show-errors
}

put "*.webp"  "image/webp"                       "public, max-age=2592000"
put "*.jpg"   "image/jpeg"                       "public, max-age=2592000"
put "*.png"   "image/png"                        "public, max-age=2592000"
put "*.woff2" "font/woff2"                       "public, max-age=31536000, immutable"
put "*.svg"   "image/svg+xml"                    "public, max-age=86400"
put "*.txt"   "text/plain; charset=utf-8"        "public, max-age=86400"
put "*.css"   "text/css; charset=utf-8"          "no-cache"
put "*.js"    "text/javascript; charset=utf-8"   "no-cache"
put "*.json"  "application/json; charset=utf-8"  "no-cache"
put "*.html"  "text/html; charset=utf-8"         "no-cache"

# Everything above is already up to date, so this only deletes files removed from site/.
aws s3 sync site/ "s3://${bucket}/" --delete --only-show-errors
echo "site/ deployed to s3://${bucket}"
