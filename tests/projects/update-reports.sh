#!/bin/sh
# Regenerate the Duvet reports of the test projects.
set -e
cd "$(dirname "$0")"
for project in */; do
    (cd "$project" && duvet report --json-v2 report.json && echo >> report.json && rm -rf .duvet/reports .duvet/requirements .duvet/snapshot.txt)
done
