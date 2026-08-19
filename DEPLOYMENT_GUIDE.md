# 🚀 DEPLOYMENT INSTRUCTIONS

## OPTION 1: Render.com (Recommended - Free)

### Step 1: Create GitHub Repository
```bash
cd C:\Users\intel\Music\infinity-research-ai-main\infinity-research-ai-main\backend

# Initialize git (if not already)
git init
git add .
git commit -m "Initial commit - RV AI Backend"

# Create repo on GitHub.com
# Then push:
git remote add origin https://github.com/YOUR_USERNAME/rv-ai-backend.git
git branch -M main
git push -u origin main
```

### Step 2: Deploy on Render.com
1. Go to: https://render.com/
2. Sign up with GitHub
3. Click: **New → Web Service**
4. Connect your `rv-ai-backend` repository
5. Settings:
   - **Name:** rv-ai-backend
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add Environment Variables:
   - `GEMINI_API_KEY` = your_key_here
   - `OPENAI_API_KEY` = your_key_here (optional)
7. Click: **Create Web Service**

### Step 3: Wait for Deployment (5-10 min)
- Render will build and deploy
- You'll get URL: `https://rv-ai-backend-xxxxx.onrender.com`

### Step 4: Update Android App
```kotlin
// File: RetrofitClient.kt
private const val BASE_URL = "https://rv-ai-backend-xxxxx.onrender.com/"
```

---

## OPTION 2: Railway.app (Alternative - Free)

### Similar process:
1. https://railway.app/
2. New Project → Deploy from GitHub
3. Select backend repo
4. Add environment variables
5. Get URL: `https://rv-ai-backend.railway.app/`

---

## OPTION 3: PythonAnywhere (Slower but Stable)

1. https://www.pythonanywhere.com/
2. Upload code
3. Configure WSGI
4. Get URL: `https://yourusername.pythonanywhere.com/`

---

## ⚠️ IMPORTANT: Environment Variables

**Must set these on deployment platform:**
```
GEMINI_API_KEY=your_actual_gemini_key
OPENAI_API_KEY=your_actual_openai_key (optional)
```

**Get Gemini key:** https://aistudio.google.com/apikey

---

## ✅ VERIFICATION:

After deployment, test:
```
https://your-deployed-url.onrender.com/health

Response: {"status": "healthy", "service": "RV AI Backend"}
```

---

## 🎯 NEXT: Update Android App

Main tumhe exact URL de dunga deployment ke baad!
