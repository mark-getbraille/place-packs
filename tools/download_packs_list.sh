#!/usr/bin/env bash
# Downloads packs.json, the list of published packs, from the release $RELEASE_TAG ("packs") of $GITHUB_REPOSITORY
# into the folder given: bash tools/download_packs_list.sh old  ->  old/packs.json. Used by build-packs.yml (plan,
# build and publish), with GH_TOKEN set.
#
# Why it is careful: a list that could not be downloaded must never be taken for "there is no list". The publish
# would then write a list of only the new packs, and delete the files of every other pack. So:
# - the releases, and the files of the "packs" release, are listed through the GitHub API; when GitHub does not
#   answer, it tries again (three times), then stops with exit 1;
# - when the release has a packs.json, it is downloaded (five tries); if it never arrives whole, it stops (exit 1);
# - only when there is no "packs" release yet, or it truly has no packs.json (the first publish), does it end
#   without a list (exit 0, no file).
# It prints "found" or "none" as its last line.
set -euo pipefail

dir="$1"
release="${RELEASE_TAG:?RELEASE_TAG is not set}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is not set}"
mkdir -p "$dir"
rm -f "$dir/packs.json"

# Run a command up to three times, 30 seconds apart; the last failure stops the script.
retry() {
  local attempt
  for attempt in 1 2 3; do
    if "$@"; then return 0; fi
    if [ "$attempt" = 3 ]; then return 1; fi
    echo "GitHub did not answer; trying again." >&2
    sleep 30
  done
}

# Every release tag, page by page (gh exits with an error when any page fails).
tags_file=$(mktemp)
assets_file=$(mktemp)
trap 'rm -f "$tags_file" "$assets_file"' EXIT
list_tags() { gh api "repos/$repo/releases?per_page=100" --paginate --jq '.[].tag_name' > "$tags_file"; }
if ! retry list_tags; then
  echo "::error::The releases of $repo could not be listed, so the list of packs could not be checked." >&2
  exit 1
fi
if ! grep -qxF "$release" "$tags_file"; then
  echo "There is no \"$release\" release yet, so there is no list of packs."
  echo none
  exit 0
fi

# Every file of the release, page by page.
list_assets() {
  local id
  id=$(gh api "repos/$repo/releases/tags/$release" --jq '.id') || return 1
  gh api "repos/$repo/releases/$id/assets?per_page=100" --paginate --jq '.[].name' > "$assets_file"
}
if ! retry list_assets; then
  echo "::error::The files of the \"$release\" release could not be listed, so the list of packs could not be checked." >&2
  exit 1
fi
if ! grep -qxF packs.json "$assets_file"; then
  echo "The \"$release\" release has no packs.json yet (the first publish)."
  echo none
  exit 0
fi

# The release has a list: it must be downloaded, whole.
for attempt in 1 2 3 4 5; do
  if gh release download "$release" --repo "$repo" --pattern packs.json --dir "$dir" --clobber && [ -s "$dir/packs.json" ] &&
      python3 -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8')); sys.exit(0 if isinstance(d, dict) and isinstance(d.get('packs'), dict) else 1)" "$dir/packs.json"; then
    echo found
    exit 0
  fi
  rm -f "$dir/packs.json"
  if [ "$attempt" = 5 ]; then break; fi
  echo "The download of packs.json failed or was not whole; trying again." >&2
  sleep 30
done
echo "::error::The \"$release\" release has a packs.json, but it could not be downloaded. Stopping, so that no pack is lost." >&2
exit 1
