@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo Mutual Fund Analysis - Deployment Setup
echo ==========================================
echo.

REM Check if git is installed
git --version >nul 2>&1
if errorlevel 1 (
    echo Error: Git not found. Please install Git first.
    exit /b 1
)

REM Initialize git if needed
if not exist ".git" (
    echo Creating Git repository...
    git init
    git branch -M main
) else (
    echo Git repository already initialized
)

REM Check for uncommitted changes
git status --porcelain | findstr . >nul
if not errorlevel 1 (
    echo.
    echo Uncommitted changes detected.
    set /p response="Commit them now? (y/n): "
    if /i "!response!"=="y" (
        git add .
        git commit -m "Deployment configuration update"
    )
)

REM Get GitHub URL
echo.
echo Enter your GitHub repository URL
echo (format: https://github.com/username/repo-name.git)
set /p GITHUB_URL="GitHub URL: "

REM Set remote
git remote | findstr origin >nul
if errorlevel 1 (
    git remote add origin !GITHUB_URL!
) else (
    git remote set-url origin !GITHUB_URL!
)

REM Push to GitHub
echo.
echo Pushing to GitHub...
git push -u origin main
if errorlevel 1 (
    echo.
    echo Error: Push failed. Make sure:
    echo   1. Repository exists on GitHub
    echo   2. You have push permissions
    echo   3. You have Git credentials configured
    exit /b 1
)

echo.
echo ==========================================
echo Success! Repository pushed to GitHub
echo ==========================================
echo.
echo Next steps for free deployment:
echo.
echo 1. Backend (Render):
echo    a. Go to https://render.com
echo    b. Sign up with GitHub
echo    c. Create PostgreSQL database
echo    d. Create Web Service from this repo
echo    e. Copy PostgreSQL connection string to env vars
echo.
echo 2. Frontend (Vercel):
echo    a. Go to https://vercel.com
echo    b. Sign up with GitHub
echo    c. Import this project
echo    d. Select 'frontend' as root directory
echo    e. Set NEXT_PUBLIC_API_URL environment variable
echo.
echo 3. Database Migrations (on Render console):
echo    Run: alembic upgrade head
echo.
echo See DEPLOYMENT.md for detailed instructions
echo.
