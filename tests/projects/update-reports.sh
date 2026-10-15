#!/bin/sh
# Regenerate the Duvet reports of the test projects.
# A project with a site-packages folder has installed dependencies.
set -e
cd "$(dirname "$0")"
for project in */; do
    root="$PWD/${project%/}"
    PYTHONPATH="$root/site-packages" uv run --project ../.. sphinx-duvet export --root "$root" "$root/report.json"
    rm -rf "$root/.duvet/reports" "$root/.duvet/requirements" "$root/.duvet/snapshot.txt"
done
