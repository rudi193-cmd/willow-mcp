#!/bin/bash
# Stop hook: catch commits on this branch that use GitHub's own auto-close
# keyword syntax (Closes/Fixes/Resolves #N, or "duplicate of #N") against an
# issue that GitHub still shows as OPEN. This is a narrow, mechanically sound
# check -- GitHub's own recognized close-on-merge convention, keyword
# immediately adjacent to the issue number -- not a general "did the
# assistant say something was resolved" detector. A Stop hook only supports
# command-type checks (no LLM judgment available at this event, see
# update-config skill docs), so it can't read chat reasoning the way a
# prompt/agent hook could. The miss that prompted this (issue #244:
# reconciled and closed via a direct API call after being told to, with no
# git artifact ever written) is a different failure mode this can't catch --
# what it *does* catch is the more common footgun of a typo'd issue number,
# a reference to the wrong repo, or a PR that merged without actually
# triggering GitHub's auto-close.

input=$(cat)

stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // empty' 2>/dev/null)
if [[ "$stop_hook_active" = "true" ]]; then
  exit 0
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

if [[ -z "$(git remote 2>/dev/null)" ]]; then
  exit 0
fi

# Only useful with a token that can read issues -- bail quietly rather than
# failing noisily on a repo/host with no GitHub credentials configured.
token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
if [[ -z "$token" ]]; then
  exit 0
fi

remote_url=$(git remote get-url origin 2>/dev/null) || exit 0
# Handle a plain github.com remote AND this environment's local git proxy
# form (http://.../git/<owner>/<repo>.git) -- same repo, different URL shape.
owner_repo=$(echo "$remote_url" | sed -E 's#^https?://[^/]*/git/##; s#^(https://github\.com/|git@github\.com:)##; s#\.git$##')
if [[ -z "$owner_repo" || "$owner_repo" == "$remote_url" ]]; then
  exit 0
fi

default_branch=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
default_branch="${default_branch:-master}"

current_branch=$(git branch --show-current 2>/dev/null)
if [[ -z "$current_branch" || "$current_branch" == "$default_branch" ]]; then
  exit 0
fi

if ! git rev-parse "origin/$default_branch" >/dev/null 2>&1; then
  exit 0
fi

# GitHub's own auto-close keyword form: verb immediately adjacent to #N.
# Plus "duplicate of #N", a convention this repo already uses in practice.
mapfile -t refs < <(
  git log --format='%B' "origin/$default_branch..HEAD" -- 2>/dev/null \
    | grep -ioE '\b(clos(e[sd]?|ing)|fix(e[sd]|ing)?|resolv(e[sd]?|ing))\b:?[[:space:]]+#[0-9]+|duplicate of #[0-9]+' \
    | grep -oE '#[0-9]+' \
    | tr -d '#' \
    | sort -un
)

if [[ ${#refs[@]} -eq 0 ]]; then
  exit 0
fi

mismatched=()
for n in "${refs[@]}"; do
  state=$(curl -s -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$owner_repo/issues/$n" | jq -r '.state // empty' 2>/dev/null)
  if [[ "$state" == "open" ]]; then
    mismatched+=("#$n")
  fi
done

if [[ ${#mismatched[@]} -gt 0 ]]; then
  echo "Commits on branch '$current_branch' use GitHub's close/fix/resolve syntax against issue(s) that are still OPEN: ${mismatched[*]}" >&2
  echo "Close them if the fix actually landed and the reference is correct, or fix the issue number/wording in the commit if it's wrong." >&2
  exit 2
fi

exit 0
