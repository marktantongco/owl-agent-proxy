#!/usr/bin/env bash
# Build the source tarball PKGBUILD expects.
#
#   bash packaging/make-source.sh [git-ref]     (default: HEAD)
#
# The tarball is a plain `git archive` of a committed tree, so it packages an
# exact commit rather than whatever a branch points at later. Uncommitted
# changes are NOT included — commit first.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
ref="${1:-HEAD}"

pkgver="$(sed -n 's/^pkgver=//p' "$here/PKGBUILD")"
[[ -n "$pkgver" ]] || { echo "could not read pkgver from PKGBUILD" >&2; exit 1; }

if [[ -n "$(git -C "$root" status --porcelain)" ]]; then
    echo "warning: working tree is dirty; the tarball will contain $ref only" >&2
fi

# `git archive --format=tar.gz` shells out to gzip. Minimal containers (the
# archlinux image, some CI runners) do not ship it, and the failure surfaces as
# a bare "exit 128" from git rather than anything actionable.
if ! command -v gzip >/dev/null 2>&1; then
    echo "error: gzip not found — required by 'git archive --format=tar.gz'" >&2
    echo "       install it (Arch: pacman -S gzip; Debian: apt install gzip)" >&2
    exit 1
fi

out="$here/owl-agent-proxy-$pkgver.tar.gz"
# --prefix is mandatory: makepkg strips exactly one leading directory.
git -C "$root" archive --format=tar.gz \
    --prefix="owl-agent-proxy-$pkgver/" -o "$out" "$ref"

echo "wrote $out ($(du -h "$out" | cut -f1)) from $(git -C "$root" rev-parse --short "$ref")"
