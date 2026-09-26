#!/usr/bin/env bash
# Check that the index jars are signed by the repo key and write the key's
# SHA-256 fingerprint, the add-repo URL and the published versions to the
# job summary (or stdout outside Actions).
# Usage: summary.sh <repo dir> <expected.json>
set -euo pipefail

repo_dir=$1
expected=$2
out=${GITHUB_STEP_SUMMARY:-/dev/stdout}
repo_url=https://blauertee.github.io/fdroid/repo

sha256_of() { grep -m1 -oE 'SHA256: [0-9A-F:]+' | cut -d' ' -f2 | tr -d ':'; }

fingerprint=$(keytool -list -v -keystore "$FDROID_KEYSTORE_PATH" \
  -storepass:env FDROID_KEYSTORE_PASSWORD -alias fdroidrepo | sha256_of)
[[ ${#fingerprint} -eq 64 ]] || { echo "::error::could not read repo key fingerprint" >&2; exit 1; }

for jar in entry.jar index-v1.jar; do
  signer=$(keytool -printcert -jarfile "$repo_dir/$jar" | sha256_of)
  if [[ "$signer" != "$fingerprint" ]]; then
    echo "::error::$jar is not signed by the repo key (signer: ${signer:-none})" >&2
    exit 1
  fi
done

{
  echo "## F-Droid repo"
  echo
  echo "Repo key SHA-256 fingerprint: \`$fingerprint\`"
  echo
  echo "Add repo: <$repo_url?fingerprint=$fingerprint>"
  echo
  echo "| App | Tag | versionCodes |"
  echo "|---|---|---|"
  jq -r 'to_entries[] | .key as $app | .value[]
    | "| \($app) | \(.tag) | \(.versionCodes | join(", ")) |"' "$expected"
} >> "$out"
