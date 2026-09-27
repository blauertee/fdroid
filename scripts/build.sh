#!/usr/bin/env bash
# Build the signed F-Droid repo into <site dir>/repo.
# Needs FDROID_KEYSTORE_BASE64 and FDROID_KEYSTORE_PASSWORD in the
# environment. Keystore and config live in <work dir>, never in the site.
# Usage: build.sh <work dir> <site dir>
set -euo pipefail

work=$1
site=$2
checkout=$(pwd)

if [[ -z "${FDROID_KEYSTORE_BASE64:-}" || -z "${FDROID_KEYSTORE_PASSWORD:-}" ]]; then
  echo "::error::FDROID_KEYSTORE_BASE64 and FDROID_KEYSTORE_PASSWORD must be set; refusing to build without the repo key" >&2
  exit 1
fi

rm -rf "$work" "$site"
mkdir -p "$work/secrets" "$work/fdroid/repo" "$site"
chmod 700 "$work/secrets"
umask 077
export FDROID_KEYSTORE_PATH="$work/secrets/repo.p12"
base64 -d <<<"$FDROID_KEYSTORE_BASE64" > "$FDROID_KEYSTORE_PATH"
keytool -list -keystore "$FDROID_KEYSTORE_PATH" -storepass:env FDROID_KEYSTORE_PASSWORD \
  -alias fdroidrepo > /dev/null \
  || { echo "::error::keystore cannot be opened or has no alias fdroidrepo" >&2; exit 1; }

cp "$checkout/config/config.yml" "$work/fdroid/config.yml"
chmod 600 "$work/fdroid/config.yml"
cp -r "$checkout/metadata" "$work/fdroid/metadata"
# fdroid looks for the repo icon at ./icon.png (config's default repo_icon)
# relative to its cwd below.
cp "$checkout/assets/icon.png" "$work/fdroid/icon.png"
umask 022

# Relative paths: fetch_sources.py reads their git history.
python3 scripts/fetch_sources.py --sources sources --metadata metadata \
  --out "$work/fdroid/repo" --expected "$work/expected.json" \
  --listings "$work/fdroid/build"

(cd "$work/fdroid" && fdroid update --use-date-from-apk)

python3 "$checkout/scripts/check_index.py" "$work/fdroid/repo" "$work/expected.json"
"$checkout/scripts/summary.sh" "$work/fdroid/repo" "$work/expected.json" "$work/fingerprint"

cp -r "$work/fdroid/repo" "$site/repo"
# fdroid's own web page and QR code are replaced by render_page.py's, and
# its build status is not published.
rm -rf "$site/repo/index.html" "$site/repo/index.css" "$site/repo/index.png" "$site/repo/status"
python3 "$checkout/scripts/render_page.py" "$checkout/config/config.yml" \
  "$(cat "$work/fingerprint")" "$site" "$checkout/README.md"
