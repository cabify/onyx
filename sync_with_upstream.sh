#!/bin/bash

# Description: synchronizes your 'main' branch with the original repository (upstream)
# Run this script from the root folder of the project you want to synchronize

set -e  # Exit if there are errors

echo "📦 Switching to main branch..."
git checkout main

echo "🔄 Fetching upstream..."
git fetch upstream

echo "🔀 Merging upstream/main into your local main..."
git merge upstream/main

echo "⬆️ Pushing to your fork (origin/main)..."
git push origin main

echo "✅ Your branch is up to date with upstream/main!"