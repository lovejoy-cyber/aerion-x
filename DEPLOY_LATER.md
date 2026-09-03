# AERION-X — Permanent Deployment (do this later)

Everything's already prepped: the GitHub repo, the Dockerfile (built and
tested this session), the config. This is the remaining "click through it
yourself" part — 10-15 minutes of your time, mostly waiting for a build.

**Repo**: https://github.com/lovejoy-cyber/aerion-x

---

## Recommended: Railway (simplest, free tier, auto-HTTPS)

1. Go to **railway.app** → Sign up (use "Login with GitHub" — one click, no separate password)
2. **New Project** → **Deploy from GitHub repo** → pick `lovejoy-cyber/aerion-x`
3. Railway auto-detects the `Dockerfile` and starts building. Let it run — this is the same build we did locally, takes ~10-15 min the first time (downloading PyTorch/OpenCV inside the container).
4. While it builds, go to your project's **Variables** tab and add:
   - `AERIONX_JWT_SECRET` — generate one by running this locally: `python -c "import secrets;print(secrets.token_hex(32))"` and paste the result
   - `AERIONX_SITE_PASSPHRASE` — optional, set any word/phrase if you want the "enter a password before you see anything" gate we tested today (e.g. `aerionx-preview` or pick your own)
5. Go to **Settings** → **Networking** → **Generate Domain**. Railway gives you a free `https://something.up.railway.app` link — permanent, real HTTPS, works from any phone or PC.
6. Open that link, register the first account (becomes ADMIN automatically), you're done.

**Cost**: Railway's free trial gives you some usage credit; after that it's usage-based billing (this app idling costs very little, but CPU inference runs use real compute — check their pricing page before leaving it running long-term).

---

## Alternative: Render (also free tier, but sleeps when idle)

1. **render.com** → Sign up with GitHub
2. **New** → **Web Service** → connect `lovejoy-cyber/aerion-x`
3. Render detects the Dockerfile automatically. Environment: **Docker**.
4. Add the same two environment variables as above (Railway steps 4)
5. Deploy — takes ~10-15 min first build
6. Render gives you a `https://aerion-x.onrender.com`-style link automatically

**Catch**: Render's free tier spins the container down after ~15 min of no traffic, and the next visitor waits ~30-60s for it to wake up. Fine for occasional friend testing, annoying if you want it always-instant.

---

## After either one is live

- Set `AERIONX_CORS_ORIGINS` to your actual deployed URL if you ever call the API from a *different* domain than the one serving the GUI (not needed if everyone just uses the one URL — same-origin, no CORS involved).
- Anyone can register an account once they have the link (and passphrase, if you set one) — the first registrant becomes ADMIN, so register yourself first before sharing the link.
- To update the live site later: just `git push` to the `main` branch on GitHub — both Railway and Render auto-redeploy on push.

## What this does NOT fix (still real, still documented)

Everything in `SECURITY.md` still applies once this is public: read endpoints
are unauthenticated (only the passphrase gate — if you set one — protects
them), no rate limiting beyond login/register, no CSRF protection. Fine for
sharing with friends/professors to try out; not something to treat as a
hardened production service without doing that work first.
