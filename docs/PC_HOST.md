# PC ko hi server banao (PC HOST lane)

Yeh lane free hai aur sabse taakatwar: research tumhaare PC par chalta hai, koi
cloud limit nahi, koi 512 MB ki chhat nahi. Kami sirf ek: PC band ho to server
bhi band.

## 1. Sirf isi PC par (sabse safe)

```
START_BACKEND.bat
```

Phir browser me `http://127.0.0.1:8000` kholo. Yeh sirf isi PC par khulta hai —
phone se nahi.

## 2. Usi Wi-Fi ke phone se bhi (LAN)

```
START_BACKEND_LAN.bat
```

Port badalna ho to `START_BACKEND_LAN.bat 8080`.

Script khud tumhaare Wi-Fi ke pate print kar deta hai, jaise
`http://192.168.1.5:8000`. Wahi phone ke browser me kholo — poori website
(chat, upload, sab) wahin chal jaayegi.

Pehli baar Windows Firewall poochhega. **"Private networks" par Allow** karo,
"Public networks" par nahi.

### Saaf baat (padhna zaroori)

Is backend par **koi login/password nahi hai**. LAN par chalane ka matlab: jo
bhi tumhaare Wi-Fi par hai, wo poora backend use kar sakta hai — tumhaare API
quota par. Isliye:

* Ghar ka apna Wi-Fi: theek hai.
* Hostel / cafe / college / hotel ka Wi-Fi: LAN script **mat chalao**.
* Bahar se (mobile data par) chahiye: LAN se nahi hoga. Uske do safe raste hain
  — Tailscale (private, sirf tumhaare device) ya Cloudflare Tunnel + login. Wo
  alag kaam hain (#105, #106).

`--reload` jaan-boojh kar nahi lagaya: wo file badalte hi server restart kar
deta hai, aur beech ka lamba research mar jaata hai.

## 3. Login ke saath apne aap chalu (autostart)

```
INSTALL_AUTOSTART.bat
```

Default **local** mode (sirf isi PC par). Phone bhi chahiye to:

```
INSTALL_AUTOSTART.bat lan
```

Yeh Startup folder me sirf ek chhoti file (`RV_AI_BACKEND.cmd`) rakhta hai — koi
admin rights nahi, koi registry nahi, koi Windows service nahi.

Band karna:

```
REMOVE_AUTOSTART.bat
```

Yeh us ek file ke alawa kuch nahi hataata — project ka data/setting safe rehta
hai.

## 4. Phone ke app me PC ka server

Android app me server URL ki screen abhi nahi bani (wo #107 hai). Aaj do raste
hain:

* Phone ke **browser** me `http://192.168.x.y:8000` kholo — wahi website hai.
* Emulator par app chala rahe ho to app ke code se
  `ServerConfig.setUserBase("http://10.0.2.2:8000")`.

App me `http://` sirf local pate par khulta hai (`10.0.2.2`, `localhost`,
`127.0.0.1`). Apna LAN IP daalna ho to Android project ki
`res/xml/network_security_config.xml` me ek `<domain>` line jodni padegi —
cloud ke liye HTTPS hi compulsory rehta hai.

## Kaun lane kab

| Chahiye | Lane |
|---|---|
| Sabse zyada taakat, ghar par | PC host (yeh doc) |
| PC band ho tab bhi chale | Railway (primary) + Render (backup) |
| Bahar se, private | Tailscale (#105) |
| Bahar se, kisi ko dena ho | Cloudflare Tunnel + login (#106) |

## Test

```
python tests\test_pc_host_scripts.py
```

Yeh check karta hai ki LAN script 0.0.0.0 par sunta hai par `--reload` ke bina,
warning likhta hai, data-drive safety nahi khoyi, autostart ka default local hai,
aur remove script sirf ek file hataata hai.
