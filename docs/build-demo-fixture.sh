#!/usr/bin/env bash
# Build a small repository whose branches are in the states gitview exists to
# tell apart, so the demo in its README is real output from a real run rather
# than a mock-up. Nothing here is DBHQ work: this repo's own branch names
# include a client engagement, which is why its real output cannot ship.
set -euo pipefail

ROOT=${1:-/tmp/gitview-demo}
REMOTE="$ROOT/remote.git"
WORK="$ROOT/checkout-service"
rm -rf "$ROOT"
mkdir -p "$ROOT"

git init -q --bare "$REMOTE"
git clone -q "$REMOTE" "$WORK"
cd "$WORK"
git config user.email demo@example.com
git config user.name "Demo"
git config commit.gpgsign false

mkdir -p src docs
printf '# checkout-service\n\nPrices a basket and takes payment.\n' > README.md
printf 'def total(items):\n    return sum(i.price for i in items)\n' > src/cart.py
printf 'Rates are fetched hourly.\n' > docs/pricing.md
git add -A && git commit -q -m "checkout service, first cut"
git branch -M main
git push -q -u origin main

commit_on () {  # commit_on <branch> <file> <line> <message>
  git checkout -q -b "$1" main
  printf '%s\n' "$3" >> "$2"
  git add -A && git commit -q -m "$4"
}

# 1. SQUASH-MERGED. The whole reason the skill exists: the branch stays ahead
#    of the trunk forever while contributing nothing, so `git branch --merged`
#    never sees it and the commit count says it is still live.
commit_on feat/vat-rounding src/cart.py "    # round half up, per HMRC" "VAT rounds half up"
git push -q -u origin feat/vat-rounding
git checkout -q main
git merge -q --squash feat/vat-rounding
git commit -q -m "VAT rounds half up (#41)"
git push -q origin main

# 2. Another squash-merge, so the demo shows it is not a one-off.
commit_on chore/bump-sdk docs/pricing.md "SDK 4.2 changes the rate endpoint." "bump the payments SDK"
git push -q -u origin chore/bump-sdk
git checkout -q main
git merge -q --squash chore/bump-sdk
git commit -q -m "bump the payments SDK (#43)"
git push -q origin main

# 3. GENUINELY UNMERGED, with real content the trunk does not have.
commit_on fix/expired-card-retry src/cart.py "def retry(payment): ..." "retry an expired card once"
git push -q -u origin fix/expired-card-retry

# 4. UNPUSHED WORK. Deleting this loses the only copy.
commit_on spike/apple-pay docs/pricing.md "Apple Pay needs a merchant id." "spike: apple pay"

# 5. NO REMOTE AT ALL, and behind the trunk.
commit_on wip/rename-basket README.md "Renaming basket to cart throughout." "start the rename"

git checkout -q main
echo "built $WORK"
git -C "$WORK" branch -a | sed 's/^/  /'
