# Deployment Guide

Deploy this app for **FREE** on Render + Vercel in under 15 minutes.

## Prerequisites

- GitHub account
- Render.com account (free)
- Vercel account (free)
- Code pushed to GitHub

## Step 1: Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mf-analysis.git
git push -u origin main
```

## Step 2: Deploy Backend to Render

### 2.1 Create Render Account
- Go to https://render.com
- Sign up with GitHub

### 2.2 Create Database
1. Dashboard → PostgreSQL
2. Click "New PostgreSQL"
3. Name: `mf-postgres`
4. Region: Oregon (free tier)
5. PostgreSQL Version: 17
6. Click "Create"
7. Copy the connection string (save for next step)

### 2.3 Create Web Service
1. Dashboard → Web Services
2. Click "New Web Service"
3. Connect your GitHub repository
4. Settings:
   - **Name:** `mf-api`
   - **Runtime:** Docker
   - **Region:** Oregon
   - **Plan:** Free
   - **Build Command:** (leave blank)
   - **Start Command:** (leave blank)

### 2.4 Set Environment Variables
In the Web Service settings, add:

```
DATABASE_URL=your_postgres_connection_string_from_step_2.2
CORS_ORIGINS=https://your-frontend.vercel.app,https://localhost:3000
ENVIRONMENT=production
GEMINI_API_KEY=(optional - leave blank for now)
```

### 2.5 Deploy
Click "Create Web Service" - Render will automatically build and deploy

**Get your backend URL:** Shows as `https://mf-api-xxxx.onrender.com`

## Step 3: Deploy Frontend to Vercel

### 3.1 Create Vercel Account
- Go to https://vercel.com
- Sign up with GitHub

### 3.2 Deploy
1. Dashboard → Add New → Project
2. Select your GitHub repository
3. Framework: Next.js
4. Root Directory: `./frontend`
5. Environment Variables:
   ```
   NEXT_PUBLIC_API_URL=https://mf-api-xxxx.onrender.app
   ```
6. Click "Deploy"

**Get your frontend URL:** Shows after deployment completes

## Step 4: Update CORS

Go back to Render Web Service settings and update:
```
CORS_ORIGINS=https://your-frontend-xxx.vercel.app,https://localhost:3000
```

## Step 5: Run Database Migrations

After first deployment, run migrations on Render:

1. Go to Render Dashboard → mf-api Web Service
2. Click "Shell" tab
3. Run:
   ```bash
   alembic upgrade head
   ```

## URLs After Deployment

- **Frontend:** `https://your-frontend-xxx.vercel.app`
- **Backend API:** `https://mf-api-xxxx.onrender.com`
- **API Health Check:** `https://mf-api-xxxx.onrender.com/health`

## Free Tier Limitations

- **Render:** Free service spins down after 15 min of inactivity (cold start ~30s on first request)
- **Vercel:** Auto-deploys on push to main
- **Database:** 100 MB storage limit (sufficient for ~1 year of fund data)
- **No custom domain** (use render.onrender.com and vercel.app)

## Monthly Data Ingestion

### Option 1: GitHub Actions (Automated - Recommended)
1. Set up GitHub Actions secrets:
   - `RENDER_DEPLOY_HOOK`: From Render Web Service settings
   - `VERCEL_TOKEN`: From Vercel account settings

2. Workflow runs monthly (configure schedule in `.github/workflows/deploy.yml`)

### Option 2: Manual (Every Month on 10th)
```bash
curl -X POST https://mf-api-xxxx.onrender.com/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"download": true}'
```

### Option 3: Render Cron Job
1. Render → Web Service → Events
2. Add Scheduled Job (Free tier limited to once per month)
3. Command: `python -m app.ingestion.top50 --download --limit 1000`

## Troubleshooting

### Cold Start Issues
- Normal on free tier. First request takes 30-60 seconds.
- Add a lightweight health check curl to keep service warm

### Database Connection Issues
- Verify DATABASE_URL format: `postgresql+psycopg://user:password@host:5432/dbname`
- Check Render PostgreSQL service is running

### Frontend Can't Connect to Backend
- Verify `NEXT_PUBLIC_API_URL` in Vercel environment variables
- Check CORS_ORIGINS in Render includes your Vercel domain

### Out of Free Tier Storage
- Render free PostgreSQL: 100 MB limit
- Upgrade to Render Pro ($7/month) or migrate to Supabase

## Next Steps

1. ✅ Deploy backend and frontend
2. ✅ Run migrations
3. 📊 Access at frontend URL
4. 📈 First ingestion happens automatically or manually
5. 💳 (Optional) Upgrade to Pro for better performance

## Cost Summary

| Component | Cost |
|-----------|------|
| Vercel (Next.js) | Free ✅ |
| Render (FastAPI + PostgreSQL) | Free ✅ |
| Playwright (for web scraping) | Included ✅ |
| Monthly data ingestion | Free ✅ |
| **Total** | **$0** |

## Upgrade Path (If Needed)

When free tier hits limits:
- Render Web Service: $7/month (0.5 GB RAM → 2 GB)
- Render PostgreSQL: $7/month (100 MB → 1 GB)
- Keep everything else free = **~$14/month**

---

🎉 Your mutual fund comparison platform is now live!
