# Failover setup — ek URL, do server, ₹0

Kyun: Railway ka free credit khatam hone par app band ho jaata hai. Yeh setup
wahi code ek doosre free host (Render) par bhi chalata hai, aur beech mein ek
free Cloudflare Worker rakhta hai jo Railway girte hi khud Render par bhej deta
hai.

Kharcha: **₹0**. Render free web service ke liye card nahi lagta, Cloudflare
Worker free plan ke liye bhi nahi.

Kuch bhi hataaya nahi gaya hai. Railway ka maujooda setup, `requirements.txt`,
saare features — sab jaise the waise hain. Yeh sirf jodne wala kaam hai.

## Kya-kya banega

```
        user
         |
   Cloudflare Worker  (ek hi URL, free)
     /            \
Railway          Render
(primary)        (backup, 24/7 available)
```

## Hissa 1 — Render par backup khada karo (card nahi chahiye)

1. https://render.com → **Get Started** → GitHub se sign in.
2. **New +** → **Web Service** → repo `ra7-cyber6565/rv-ai-backend` chuno.
3. Render `render.yaml` khud padh lega. Confirm karo ki:
   - Build Command: `pip install -r requirements-slim.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Instance Type: **Free**
   - Health Check Path: `/health`
4. **Environment** mein yeh daalo (naam wahi jo Railway par hain — value wahin
   se copy karo, kahin likho nahi):
   - `GEMINI_API_KEY`
   - `GEMINI_ZERO_COST_CONFIRMED` = `true`
   - `ZERO_COST_ONLY` = `true`
   - Railway par jo bhi extra keys hain (`GEMINI_API_KEY_2`, `GEMINI_API_KEYS`,
     `USPTO_ODP_API_KEY`, `TAVILY_API_KEY`) — jo maujood hain wahi daalo.
5. Deploy hone par URL milega, jaise `https://rv-ai-backend.onrender.com`.
   `<URL>/health` kholo — JSON aana chahiye.

Render free ki do imaandaar seemaayein: 15 minute khaali rehne par service so
jaati hai (pehli request 30–60 second leti hai — Worker ka cron isi ko rokta
hai), aur 512 MB RAM hai, isliye wahan `requirements-slim.txt` chalta hai jisme
se `chromadb` aur `sentence-transformers` nikale gaye hain. Iska seedha matlab:
**backup par tumhaari khud upload ki hui PDF ka vector search band rahega**,
baaki poora research chalega. Primary (Railway) par yeh feature jaisa hai waisa
hi hai.

## Hissa 2 — Cloudflare Worker (ek URL jo khud switch kare)

1. https://dash.cloudflare.com → sign up (card nahi lagta).
2. Left menu → **Workers & Pages** → **Create application** → **Create Worker**.
   Naam: `rv-ai`. **Deploy** dabao.
3. **Edit code** → jo sample code hai use hata kar `deploy/cloudflare_worker.js`
   ka poora content paste karo → **Deploy**.
4. Worker → **Settings** → **Variables and Secrets** → do variable jodo
   (**Text**, Secret nahi — ye public URL hain, koi key nahi):
   - `RV_PRIMARY_BASE` = `https://web-production-0dd45.up.railway.app`
   - `RV_BACKUP_BASE`  = `https://rv-ai-backend.onrender.com`
5. Worker → **Settings** → **Trigger Events** → **Cron Triggers** → **Add** →
   `*/10 * * * *` (har 10 minute). Yeh dono host ka `/health` chhoo kar Render ko
   jagaye rakhta hai.
6. Ab tumhara asli URL yeh hai: `https://rv-ai.<tumhara-subdomain>.workers.dev`
   Website isi se kholo, aur Android app mein bhi yahi daalo.

Check karne ka tareeka: browser ke DevTools → Network → koi request → Response
Headers mein `X-RV-Origin` dekho. `primary` = Railway ne diya, `backup` = Render
ne diya. Chupke se switch kabhi nahi hota.

## Hissa 3 — website/app ki apni parat

`web/index.html` boot par `/__rv/failover.json` maangta hai (Worker deta hai).
Backup ka pata mil gaya to primary ke jawab na dene par page khud backup par
chala jaata hai aur chat mein saaf likh deta hai ki server badla hai aur lamba
research dobara bhejna padega. Worker na ho to yeh call fail ho jaati hai aur
page bilkul aaj jaisa hi chalta hai.

## Niyam jo jaan-boojh kar aise hain

- Failover **sirf** tab hota hai jab primary ne request padhi hi nahi — network
  error ya gateway 502/503/504. App ne khud 500 diya to backup par dobara nahi
  bhejte, warna ek hi kaam do baar ho sakta tha.
- Beech mein chal raha lamba research backup par **maujood nahi** hota. App
  saaf-saaf bolta hai aur dobara chalane ko kehta hai. Adhoora jawab poora
  bataana mana hai.
- Worker mein koi API key, token ya secret nahi hai. Wahan sirf do public URL
  hain; keys server ke environment mein hi rehti hain.
- Dono host ek hi git repo se chalte hain, isliye code kabhi alag nahi hota.
