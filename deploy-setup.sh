#!/bin/bash
set -e

echo "=========================================="
echo "Mutual Fund Analysis - Deployment Setup"
echo "=========================================="
echo ""

# Check prerequisites
if ! command -v git &> /dev/null; then
    echo "❌ Git not found. Please install Git first."
    exit 1
fi

# Initialize git if needed
if [ ! -d ".git" ]; then
    echo "📦 Initializing Git repository..."
    git init
    git branch -M main
else
    echo "✅ Git repository already initialized"
fi

# Check for uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  Uncommitted changes detected"
    echo "Would you like to commit them? (y/n)"
    read -r response
    if [ "$response" = "y" ]; then
        git add .
        git commit -m "Deployment configuration update"
    fi
fi

# Get GitHub repo URL
echo ""
echo "Enter your GitHub repository URL"
echo "(format: https://github.com/username/repo-name.git)"
read -r GITHUB_URL

# Set remote and push
if git remote | grep -q origin; then
    git remote set-url origin "$GITHUB_URL"
else
    git remote add origin "$GITHUB_URL"
fi

echo ""
echo "📤 Pushing to GitHub..."
git push -u origin main || {
    echo "⚠️  Push failed. Make sure:"
    echo "  1. Repository exists on GitHub"
    echo "  2. You have push permissions"
    echo "  3. You have Git credentials configured"
    exit 1
}

echo ""
echo "=========================================="
echo "✅ Repository pushed to GitHub!"
echo "=========================================="
echo ""
echo "Next steps for free deployment:"
echo ""
echo "1️⃣  Backend (Render):"
echo "   a. Go to https://render.com"
echo "   b. Sign up with GitHub"
echo "   c. Create PostgreSQL database"
echo "   d. Create Web Service from this repo"
echo "   e. Copy PostgreSQL connection string to env vars"
echo ""
echo "2️⃣  Frontend (Vercel):"
echo "   a. Go to https://vercel.com"
echo "   b. Sign up with GitHub"
echo "   c. Import this project"
echo "   d. Select 'frontend' as root directory"
echo "   e. Set NEXT_PUBLIC_API_URL environment variable"
echo ""
echo "3️⃣  Database Migrations (on Render console):"
echo "   Run: alembic upgrade head"
echo ""
echo "📖 See DEPLOYMENT.md for detailed instructions"
