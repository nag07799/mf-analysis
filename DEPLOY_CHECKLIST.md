# Deployment Checklist

## ✅ Deployment Files Created

- [x] `Dockerfile` - Container image for backend
- [x] `render.yaml` - Render.com service configuration
- [x] `frontend/vercel.json` - Vercel deployment configuration
- [x] `.dockerignore` - Files to exclude from Docker build
- [x] `.github/workflows/deploy.yml` - CI/CD pipeline
- [x] `DEPLOYMENT.md` - Detailed deployment guide
- [x] `deploy-setup.sh` - Automated setup for Mac/Linux
- [x] `deploy-setup.bat` - Automated setup for Windows
- [x] `.env.example` - Updated with all environment variables

## 🚀 Quick Start (Choose One)

### Option A: Automated Setup (Recommended)

**Windows:**
```cmd
deploy-setup.bat
```

**Mac/Linux:**
```bash
bash deploy-setup.sh
```

This will:
1. Initialize Git repo (if needed)
2. Commit all deployment files
3. Push to GitHub
4. Show you next steps

### Option B: Manual Setup

```bash
# Initialize git
git init
git add .
git commit -m "Add deployment configuration"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

## 📋 Step-by-Step Deployment

### 1. GitHub Setup (Done if using setup script)
```bash
# Your code is now on GitHub at:
# https://github.com/YOUR_USERNAME/mf-analysis
```

### 2. Deploy Backend (Render)

1. Go to https://render.com → Sign up with GitHub
2. Create → PostgreSQL database
   - Name: `mf-postgres`
   - Region: Oregon (free)
3. Dashboard → Web Services → New Web Service
   - Repository: Your GitHub repo
   - Runtime: Docker
   - Region: Oregon
   - Plan: Free
4. Environment Variables:
   ```
   DATABASE_URL=<paste postgres connection string>
   CORS_ORIGINS=https://your-vercel-app.vercel.app,http://localhost:3000
   ENVIRONMENT=production
   ```
5. Click "Create Web Service"
6. Wait for build to complete
7. Copy the service URL (e.g., `https://mf-api-xxxx.onrender.com`)

### 3. Run Database Migrations

1. Render → mf-api Web Service → Shell tab
2. Run:
   ```bash
   alembic upgrade head
   ```

### 4. Deploy Frontend (Vercel)

1. Go to https://vercel.com → Sign up with GitHub
2. Add New → Project
3. Select your GitHub repository
4. Settings:
   - Framework: Next.js
   - Root Directory: `frontend`
5. Environment Variables:
   ```
   NEXT_PUBLIC_API_URL=https://mf-api-xxxx.onrender.com
   ```
6. Click "Deploy"
7. Wait for deployment
8. Copy the Vercel URL (e.g., `https://mf-comparison-xxx.vercel.app`)

### 5. Update CORS on Render

1. Render → mf-api → Environment
2. Update `CORS_ORIGINS`:
   ```
   https://your-vercel-app.vercel.app,http://localhost:3000
   ```
3. Click "Save"

## ✨ Your URLs

After deployment, you'll have:

- **Frontend:** `https://your-app-xxx.vercel.app`
- **Backend API:** `https://mf-api-xxxx.onrender.com`
- **API Docs:** `https://mf-api-xxxx.onrender.com/docs`
- **Health Check:** `https://mf-api-xxxx.onrender.com/health`

## 📊 Verify Everything Works

### Test Backend
```bash
curl https://mf-api-xxxx.onrender.com/health
```

Expected response:
```json
{
  "status": "ok",
  "database": "UP",
  "parser_version": "1.0.0",
  "gemini_configured": false
}
```

### Test Frontend
Open `https://your-app-xxx.vercel.app` in browser

Should see:
- Fund selector dropdowns
- Month selector
- "Compare" button
- If database has funds, they should list

## 🔄 Monthly Data Ingestion Setup

### Option 1: Render Cron Job (Easiest)
1. Render Dashboard → Web Services → mf-api
2. Settings → Cron Jobs
3. New Cron Job:
   - Schedule: `0 10 10 * *` (10 AM on 10th)
   - Command: `python -m app.ingestion.top50 --download --limit 1000`

### Option 2: GitHub Actions (Automated)
1. GitHub → Settings → Secrets and variables → Actions
2. Add secrets:
   - `RENDER_DEPLOY_HOOK`: Get from Render web service settings
   - `VERCEL_TOKEN`: Get from Vercel account settings → Tokens
3. Update `.github/workflows/deploy.yml` with your schedule
4. Push to main branch

### Option 3: Manual (Once a Month)
```bash
curl -X GET "https://mf-api-xxxx.onrender.com/api/v1/ingest/refresh?download=true&limit=1000"
```

## 🐛 Troubleshooting

### "Cold Start" Delays (Normal on Free Tier)
- First request to Render takes 30-60 seconds
- This is normal for free tier services
- Add a health check endpoint to keep it warm

### Database Connection Error
- Check DATABASE_URL format in Render env vars
- Verify PostgreSQL service is running
- Run `alembic upgrade head` from Render shell

### Frontend Shows "Cannot Connect to API"
- Verify `NEXT_PUBLIC_API_URL` is set in Vercel
- Check CORS_ORIGINS includes your Vercel domain
- Verify Render service is running

### "Out of Storage" (After ~1 Year)
- Render free tier: 100 MB PostgreSQL storage
- Options:
  1. Upgrade Render PostgreSQL to Pro ($7/month)
  2. Switch to Supabase (also free tier)
  3. Archive old months to save space

## 💰 Cost Breakdown

| Service | Free Tier | When to Upgrade |
|---------|-----------|-----------------|
| Vercel | ✅ Unlimited | Very high traffic |
| Render API | ✅ 0.5 GB RAM | Out of memory errors |
| Render PostgreSQL | ✅ 100 MB | Full after ~12 months |
| **Total** | **$0** | ~$14/mo if needed |

## 🎯 Next Steps

1. ✅ Run `deploy-setup.bat` or `deploy-setup.sh`
2. ✅ Follow deployment guide in `DEPLOYMENT.md`
3. ✅ Test your live URLs
4. ✅ Set up monthly ingestion
5. 🎉 Start comparing funds!

## 📞 Support

Common issues are documented in `DEPLOYMENT.md`

For GitHub Actions or specific Render/Vercel issues:
- Render docs: https://render.com/docs
- Vercel docs: https://vercel.com/docs
- Next.js docs: https://nextjs.org/docs

---

**Questions?** Check the detailed guide: [`DEPLOYMENT.md`](./DEPLOYMENT.md)
