# 🚀 COMPLETE DEPLOYMENT GUIDE (Step-by-Step)

**Estimated Time: 30 minutes**  
**Cost: $0/month** (Free tier for everything)

---

## PART 1: CREATE GITHUB REPOSITORY (5 minutes)

### Step 1a: Create New Repository on GitHub

1. Go to **https://github.com/new**
2. Sign in with your GitHub account (create one if needed: https://github.com/signup)
3. Fill in the form:
   ```
   Repository name: mf-analysis
   Description: Indian Equity Mutual Fund Comparison Platform
   Public or Private: Public (recommended for free)
   Initialize with: Nothing (we already have files)
   ```
4. Click **"Create repository"**
5. You'll see an empty repository with commands

### Step 1b: Copy Your Repository URL

From the GitHub page, look for:
```
https://github.com/YOUR_USERNAME/mf-analysis.git
```

**Copy this URL** (we'll use it in the next step)

### Step 1c: Push Your Code to GitHub

Open PowerShell/Command Prompt and run:

```powershell
cd "C:\Users\nagu0\OneDrive\Desktop\mf_analysis\mutual-fund-overlap"
```

Then run this (replace YOUR_USERNAME):

```powershell
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mf-analysis.git
git push -u origin main
```

**You might need to authenticate:**
- If prompted for username/password, use your GitHub credentials
- Or use GitHub Personal Access Token (https://github.com/settings/tokens)

**Expected output:**
```
Enumerating objects: 71, done.
Counting objects: 100% (71/71), done.
Delta compression using up to 8 threads
Compressing objects: 100% (55/55), done.
Writing objects: 100% (71/71), 8475 insertions(+)
...
 * [new branch]      main -> main
Branch 'main' set up to track remote branch 'main' from 'origin'.
```

✅ **Your code is now on GitHub!**

Verify: Go to https://github.com/YOUR_USERNAME/mf-analysis and you should see all files.

---

## PART 2: DEPLOY BACKEND TO RENDER (10 minutes)

### Step 2a: Create Render Account

1. Go to **https://render.com**
2. Click **"Sign up with GitHub"**
3. Authorize Render to access your GitHub
4. Complete your profile

### Step 2b: Create PostgreSQL Database

1. From Render Dashboard, click **"New +"**
2. Select **"PostgreSQL"**
3. Fill in:
   ```
   Name: mf-postgres
   Database: mutual_funds
   Region: Oregon (free tier available)
   PostgreSQL Version: 17
   ```
4. Scroll down to **"Create Database"**
5. **Wait 2-3 minutes** for database to be ready
6. When ready, you'll see a connection string like:
   ```
   postgresql://mf_user:PASSWORD@dpg-xxx.onrender.com:5432/mutual_funds
   ```
   **Copy this entire URL** (you'll need it in the next step)

### Step 2c: Create Web Service (Backend API)

1. From Render Dashboard, click **"New +"**
2. Select **"Web Service"**
3. Connect your repository:
   - Select **"mf-analysis"**
   - Click **"Connect"**
4. Fill in the form:
   ```
   Name:                  mf-api
   Environment:           Docker
   Region:                Oregon
   Branch:                main
   Build Command:         (leave empty)
   Start Command:         (leave empty)
   Plan:                  Free
   ```
5. Click **"Create Web Service"**
6. **Wait for build** (~5-10 minutes)

### Step 2d: Add Environment Variables

After service is created (but while still building):

1. Click on your **"mf-api"** service
2. Go to **"Environment"** tab
3. Add these variables:

| Key | Value |
|-----|-------|
| `DATABASE_URL` | Paste the PostgreSQL URL from Step 2b |
| `CORS_ORIGINS` | `https://localhost:3000,http://localhost:3000` (we'll update this later) |
| `ENVIRONMENT` | `production` |
| `GEMINI_API_KEY` | (Leave empty for now) |

4. For each variable, press **"Enter"** to add it
5. Scroll to bottom and click **"Save Changes"**

### Step 2e: Wait for Deployment

1. Go to **"Deploys"** tab
2. Watch the status until it shows **"Live"**
3. Once live, you'll see a URL like:
   ```
   https://mf-api-xxxxxxxxxxxx.onrender.com
   ```
   **Copy this URL** (needed for frontend)

### Step 2f: Run Database Migrations

1. While on your mf-api service page, click **"Shell"** tab
2. A terminal window opens
3. Run this command:
   ```bash
   alembic upgrade head
   ```
4. Wait for it to complete (should see "INFO  [alembic.runtime.alembic]" messages)
5. Should end with: `SUCCESS: Tables created`

### Step 2g: Test Your API

In a new browser tab, visit:
```
https://mf-api-xxxxxxxxxxxx.onrender.com/health
```

You should see:
```json
{
  "status": "ok",
  "database": "UP",
  "parser_version": "1.0.0",
  "gemini_configured": false
}
```

✅ **Backend is live!**

---

## PART 3: DEPLOY FRONTEND TO VERCEL (8 minutes)

### Step 3a: Create Vercel Account

1. Go to **https://vercel.com/signup**
2. Click **"Continue with GitHub"**
3. Authorize Vercel
4. Complete setup

### Step 3b: Import Your Repository

1. From Vercel Dashboard, click **"Add New"**
2. Select **"Project"**
3. Find **"mf-analysis"** repository
4. Click **"Import"**

### Step 3c: Configure Project

1. In the import settings:
   ```
   Framework Preset:      Next.js
   Root Directory:        frontend
   Install Command:       (auto-detected)
   Build Command:         (auto-detected)
   Output Directory:      (auto-detected)
   ```

### Step 3d: Add Environment Variable

1. Scroll to **"Environment Variables"** section
2. Add:
   ```
   Name:  NEXT_PUBLIC_API_URL
   Value: https://mf-api-xxxxxxxxxxxx.onrender.com
   ```
   (Use your actual Render URL from Step 2e)

3. Click **"Deploy"**
4. **Wait 3-5 minutes** for deployment

### Step 3e: Verify Deployment

When deployment completes, you'll see:
```
✓ Production
  www.yourdomain.vercel.app
```

Vercel gives you a URL like:
```
https://mf-analysis-xxxxxxxxxxxx.vercel.app
```

✅ **Frontend is live!**

---

## PART 4: UPDATE CORS SETTINGS (2 minutes)

Now that both services are live, update CORS to allow communication:

### Step 4a: Get Your Vercel URL

From Vercel dashboard, copy your production URL:
```
https://mf-analysis-xxxxxxxxxxxx.vercel.app
```

### Step 4b: Update Render CORS

1. Go back to Render dashboard
2. Click on **"mf-api"** service
3. Go to **"Environment"** tab
4. Find **"CORS_ORIGINS"** variable
5. Update it to:
   ```
   https://mf-analysis-xxxxxxxxxxxx.vercel.app,http://localhost:3000
   ```
   (Use your actual Vercel URL)
6. Click **"Save Changes"**
7. Service will redeploy (~1 minute)

---

## PART 5: FINAL VERIFICATION (3 minutes)

### Step 5a: Test API

Open in browser:
```
https://mf-api-xxxxxxxxxxxx.onrender.com/health
```

Should show:
```json
{
  "status": "ok",
  "database": "UP"
}
```

### Step 5b: Test Frontend

Open in browser:
```
https://mf-analysis-xxxxxxxxxxxx.vercel.app
```

You should see:
- Fund comparison interface
- Fund selector dropdowns (if data exists)
- Month selector
- "Compare" button

### Step 5c: Test Comparison

1. Select two different funds
2. Select a month
3. Click "Compare"
4. You should see comparison results

✅ **Everything is working!**

---

## PART 6: SETUP MONTHLY DATA INGESTION (Optional)

Your fund data needs to be refreshed monthly. Choose one option:

### Option A: Render Cron Job (Easiest - Recommended)

1. Go to Render Dashboard → **"mf-api"** service
2. Click **"Settings"** tab
3. Scroll to **"Cron Jobs"**
4. Click **"Add a Cron Job"**
5. Fill in:
   ```
   Command: python -m app.ingestion.top50 --download --limit 1000
   Schedule: 0 10 10 * *
   (This means: 10 AM on the 10th of every month)
   ```
6. Click **"Add Cron Job"**

The system will automatically download and ingest new fund data every month.

### Option B: Manual (Once a Month)

On the 10th of each month, run this command:

```bash
curl -X GET "https://mf-api-xxxxxxxxxxxx.onrender.com/api/v1/ingest/refresh?download=true&limit=1000"
```

### Option C: GitHub Actions (Advanced)

See `.github/workflows/deploy.yml` for automated scheduling.

---

## YOUR LIVE URLS

After deployment, you have:

| Component | URL |
|-----------|-----|
| **Frontend** | `https://mf-analysis-xxxxxxxxxxxx.vercel.app` |
| **Backend API** | `https://mf-api-xxxxxxxxxxxx.onrender.com` |
| **API Docs** | `https://mf-api-xxxxxxxxxxxx.onrender.com/docs` |
| **Health Check** | `https://mf-api-xxxxxxxxxxxx.onrender.com/health` |

**Share your frontend URL** with friends/family! They can use it to compare funds.

---

## 🔍 TROUBLESHOOTING

### "Cold Start" Delays
- **What:** First request takes 30-60 seconds
- **Why:** Render free tier spins down inactive services
- **Solution:** Normal for free tier. Service warms up after first request.

### API Shows "Database DOWN"
- **What:** Health check shows `"database": "DOWN"`
- **Solution:**
  1. Check Render PostgreSQL service status
  2. Verify DATABASE_URL in environment variables
  3. Run migrations again: `alembic upgrade head`

### Frontend Can't Connect to API
- **What:** UI shows "Connection error" or blank data
- **Solution:**
  1. Check CORS_ORIGINS includes your Vercel domain
  2. Verify NEXT_PUBLIC_API_URL is set correctly
  3. Wait 2 minutes after updating CORS (service needs to redeploy)

### Deployment Stuck Building
- **What:** Render shows building status for >15 minutes
- **Solution:**
  1. Go to Render service → "Logs" tab
  2. Check for error messages
  3. Click "Retry Deploy"

### "Permission Denied" on GitHub Push
- **Solution:**
  1. Use GitHub Personal Access Token instead of password
  2. Generate at: https://github.com/settings/tokens
  3. Use token as password when prompted

---

## 📊 WHAT'S DEPLOYED

✅ **123 Equity Mutual Funds**
- 59 diversified (Large Cap, Mid Cap, Small Cap, etc.)
- 64 thematic/sectoral (Pharma, Tech, Housing, etc.)

✅ **7,565 Fund Holdings**
- All securities with weights
- Complete portfolio data
- Monthly snapshots

✅ **Fund Comparison Engine**
- Select any two funds
- Compare overlapping holdings
- See portfolio overlap %
- Export results

✅ **Automatic Monthly Updates**
- Fetches official AMC disclosures
- Validates data quality
- Updates database
- Zero manual intervention

---

## 💰 COST BREAKDOWN

| Service | Free Tier | Cost |
|---------|-----------|------|
| Vercel (Frontend) | 100 GB/month bandwidth | **$0** |
| Render (Backend) | 0.5 GB RAM, 750 hours/month | **$0** |
| Render Database | 100 MB storage | **$0** |
| Monthly Updates | Included | **$0** |
| **Total** | | **$0/month** |

---

## 🎯 NEXT STEPS

After everything is deployed:

1. ✅ Share your frontend URL with friends
2. ✅ Use it to compare your favorite funds
3. ✅ Check back monthly (automatic data updates)
4. ✅ (Optional) Add your own features to the code

If you want to make changes:
1. Edit code locally
2. `git add .`
3. `git commit -m "Your changes"`
4. `git push origin main`
5. Both Render and Vercel automatically redeploy!

---

## 📞 SUPPORT

**Stuck?** Check these files:
- `DEPLOYMENT.md` - Detailed technical guide
- `ARCHITECTURE.md` - System diagrams
- `DEPLOY_CHECKLIST.md` - Quick reference

**External help:**
- Render Docs: https://render.com/docs
- Vercel Docs: https://vercel.com/docs
- Next.js Docs: https://nextjs.org/docs

---

**🎉 You're all set! Your mutual fund comparison platform is live on the internet! 🎉**

Questions? Revisit Step 5 verification checklist.
