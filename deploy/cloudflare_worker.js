/**
 * RV AI — failover front door (Cloudflare Worker, free plan).
 *
 * Ek URL, do server. Normally sab kuch PRIMARY (Railway) par jaata hai. Jab
 * primary ka free credit khatam ho jaaye ya wo down ho, yeh worker usi request
 * ko BACKUP (Render) par bhej deta hai — user ko kuch karna nahi padta.
 *
 * Do niyam jaan-boojh kar aise hain, kyunki inke bina jhooth ban jaata:
 *
 *   1. Failover SIRF tab hota hai jab primary ne request PADHI hi nahi —
 *      network error, ya gateway-level 502/503/504. Agar app ne khud 500 diya
 *      (yaani code andar tak chala), to hum backup par dobara nahi bhejte:
 *      wo ek hi kaam do baar kara sakta hai.
 *   2. Har response par `X-RV-Origin: primary|backup` header lagta hai. App aur
 *      tum dono dekh sakte ho ki jawab kis server se aaya. Chupke se switch
 *      nahi hota.
 *
 * Isme koi API key, token ya secret nahi hai aur nahi hona chahiye. Yeh sirf
 * do public URL ke beech ka switch hai. Keys server par hi rehti hain.
 *
 * Setup: docs/FAILOVER_SETUP.md
 * Worker variables (Settings -> Variables, plain text, secret nahi):
 *   RV_PRIMARY_BASE  = https://web-production-0dd45.up.railway.app
 *   RV_BACKUP_BASE   = https://rv-ai-backend.onrender.com
 */

// Body itni badi ho to hum use memory me nahi rakhte, isliye us request par
// failover nahi ho sakta. Chup rehne se behtar hai saaf-saaf mana kar dena.
const MAX_BUFFERED_BODY = 24 * 1024 * 1024;

// Gateway ne bola "server hi nahi mila/uthaya" — app ne request dekhi bhi nahi.
const GATEWAY_DOWN = new Set([502, 503, 504]);

// Primary down mila to itni der tak dobara na poochho (har request par ek
// bekaar attempt bachata hai). Worker instance ke andar hi rehta hai.
const REMEMBER_DOWN_MS = 30 * 1000;
let primaryDownUntil = 0;

function trimBase(raw) {
  const text = String(raw || "").trim();
  if (!text) return "";
  return text.endsWith("/") ? text.slice(0, -1) : text;
}

function targetUrl(base, incoming) {
  const url = new URL(incoming.url);
  return trimBase(base) + url.pathname + url.search;
}

/** Request ko dobara bhejne layak banana: body ek baar padh kar rakh lena. */
async function bufferBody(request) {
  if (request.method === "GET" || request.method === "HEAD") {
    return { body: undefined, replayable: true };
  }
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_BUFFERED_BODY) {
    return { body: request.body, replayable: false };
  }
  const bytes = await request.arrayBuffer();
  if (bytes.byteLength > MAX_BUFFERED_BODY) {
    return { body: bytes, replayable: false };
  }
  return { body: bytes, replayable: true };
}

function forwardHeaders(request) {
  const headers = new Headers(request.headers);
  // Ye header sirf worker ke aage tak ka sach hai; origin ko bhejna galat hai.
  headers.delete("host");
  headers.delete("cf-connecting-ip");
  return headers;
}

function tagged(response, origin, note) {
  const out = new Response(response.body, response);
  out.headers.set("X-RV-Origin", origin);
  if (note) out.headers.set("X-RV-Failover-Note", note);
  return out;
}

async function callOrigin(base, request, body) {
  return fetch(targetUrl(base, request), {
    method: request.method,
    headers: forwardHeaders(request),
    body: body,
    redirect: "manual",
  });
}

/**
 * App/website ko batata hai ki backup kahan hai. Iski wajah: agar kisi ne
 * seedha primary ka purana URL bookmark kar rakha hai (worker ke bina), to page
 * khud isse padh kar backup par ja sakta hai. Fail hone par page bilkul aaj
 * jaisa hi chalta hai — yeh sirf ek extra parat hai, zaroorat nahi.
 */
function failoverInfo(env, serving) {
  return new Response(JSON.stringify({
    primary: trimBase(env.RV_PRIMARY_BASE),
    backup: trimBase(env.RV_BACKUP_BASE),
    serving: serving,
    note: "Backup host par tumhaari khud upload ki hui PDF ka vector search band rehta hai; baaki research poora chalta hai.",
  }), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function misconfigured(which) {
  return new Response(JSON.stringify({
    error: "failover_not_configured",
    detail: which + " worker variable set nahi hai. Cloudflare -> Worker -> Settings -> Variables me daalo.",
  }), { status: 500, headers: { "Content-Type": "application/json" } });
}

export default {
  async fetch(request, env, ctx) {
    const primary = trimBase(env.RV_PRIMARY_BASE);
    const backup = trimBase(env.RV_BACKUP_BASE);
    if (!primary) return misconfigured("RV_PRIMARY_BASE");

    const path = new URL(request.url).pathname;
    const skipPrimary = backup && Date.now() < primaryDownUntil;
    if (path === "/__rv/failover.json") {
      return failoverInfo(env, skipPrimary ? "backup" : "primary");
    }

    const { body, replayable } = await bufferBody(request);

    if (!skipPrimary) {
      let response = null;
      try {
        response = await callOrigin(primary, request, body);
      } catch (_) {
        response = null;                       // primary tak connection hi nahi
      }
      const gatewayDown = response && GATEWAY_DOWN.has(response.status);
      if (response && !gatewayDown) {
        return tagged(response, "primary", "");
      }
      // Primary ne jawab nahi diya. Aage sirf tab badh sakte hain jab backup
      // maujood ho AUR request dobara bheji ja sakti ho.
      if (!backup) {
        return response
          ? tagged(response, "primary", "no-backup-configured")
          : misconfigured("RV_BACKUP_BASE");
      }
      primaryDownUntil = Date.now() + REMEMBER_DOWN_MS;
      if (!replayable) {
        return new Response(JSON.stringify({
          error: "failover_body_too_large",
          detail: "Primary server ne jawab nahi diya, aur yeh upload itna bada hai ki isse backup par dobara bhejna safe nahi tha. Wahi file phir se bhejo — ab backup server par jaayegi.",
        }), {
          status: 503,
          headers: { "Content-Type": "application/json", "X-RV-Origin": "none" },
        });
      }
    }

    try {
      const response = await callOrigin(backup, request, body);
      return tagged(response, "backup", "primary-unavailable");
    } catch (_) {
      return new Response(JSON.stringify({
        error: "both_hosts_unreachable",
        detail: "Dono server abhi jawab nahi de rahe. Yeh network/host ki dikkat hai, tumhaare sawaal ki nahi — thodi der baad wahi sawaal dobara bhejo.",
      }), {
        status: 503,
        headers: { "Content-Type": "application/json", "X-RV-Origin": "none" },
      });
    }
  },

  /**
   * Cron trigger (free plan par bhi milta hai). Render ka free web service 15
   * minute khaali rehne par so jaata hai, aur so jaane ke baad pehli request
   * 30-60 second leti hai. Isliye hum dono ka /health har cron par chhoo lete
   * hain — backup jagta rehta hai, aur switch hone par user ko intezaar nahi.
   */
  async scheduled(event, env, ctx) {
    const bases = [trimBase(env.RV_PRIMARY_BASE), trimBase(env.RV_BACKUP_BASE)];
    await Promise.all(bases.filter(Boolean).map(async (base) => {
      try {
        await fetch(base + "/health", { method: "GET", cf: { cacheTtl: 0 } });
      } catch (_) {
        // Jaan-boojh kar chup: cron ka kaam sirf jagana hai. Kaun down hai wo
        // asli request ke waqt X-RV-Origin se pata chal jaata hai.
      }
    }));
  },
};
