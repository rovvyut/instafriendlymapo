# Hosting MAPO

## What's in this folder

```
frontend/
├── index.html        markup — the scenes, the login gate, the coach panel
├── styles.css        all the styling
├── app.js            all the logic: plan generator, coach, dealer, log
├── data/
│   └── dishes.json   1,016 foods from your food_database.csv
├── assets/
│   └── bmw_m5_rev.mp3
└── standalone.html   the same page as ONE file, everything inlined
```

There is no build step and no `npm install`. It is plain HTML, CSS and JS — a
static host serves it exactly as it sits.

**Two builds, pick one.** The split files are the ones to edit and host. But
`app.js` fetches `data/dishes.json`, and browsers block `fetch` on `file://`
pages, so the split build must be served over http (see below). `standalone.html`
has all four files inlined into one, so it works by double-clicking — handy for
emailing someone or dropping on a USB stick. Both behave identically otherwise.
Edit the split files; regenerate standalone only if you need it.

---

## 1. Test it locally first

Google Sign-In will not run from a `file://` page, so serve it over HTTP:

```bash
cd frontend
python3 -m http.server 5173
# open http://localhost:5173
```

That one command is all the "server" this needs — it just hands the four files
to the browser. Everything except real Google sign-in works offline, including
the demo login.

If you open `index.html` directly instead, the page tells you so in orange and
points you at `standalone.html`.

---

## 2. Put the front end on the web

All three of these host a static file for free on a `*.pages.dev`,
`*.netlify.app` or `*.vercel.app` subdomain, with HTTPS included.

**Fastest — no account setup:** drag the `frontend` folder onto
<https://app.netlify.com/drop>. You get a live HTTPS URL in about ten seconds.
Good for showing someone today.

**Better — redeploys when you push:** put the repo on GitHub, then connect it to
**Cloudflare Pages**, **Vercel** or **Netlify**. For all three:

| Setting | Value |
|---|---|
| Build command | *(leave empty)* |
| Output / publish directory | `frontend` |
| Root directory | *(repo root)* |
| Framework preset | None / Other |

There is nothing to build, so the deploy takes seconds.

**GitHub Pages** also works: push `index.html`, then Settings → Pages → deploy
from branch. Note it serves from a subpath (`/<repo-name>/`), which is fine here
because nothing in the page uses absolute paths.

---

## 3. Turn on real Google sign-in

Right now the Google button signs you in as a demo guest. To make it real:

1. Google Cloud Console → **APIs & Services → Credentials** → Create OAuth
   client ID → **Web application**.
2. Under **Authorised JavaScript origins**, add your deployed origin exactly —
   scheme and host, no trailing slash and no path:
   - `https://mapo.pages.dev`
   - `http://localhost:5173` (for local testing)
3. Copy the client ID into `app.js` (and `standalone.html` if you use it).
   Search for:

   ```js
   const GOOGLE_CLIENT_ID = '';   // ← paste your OAuth client ID when you deploy
   ```

   The moment that string is non-empty the page loads Google Identity Services
   and swaps the demo button for the real one. No other change needed.
4. Put the **same** client ID into the backend's `GOOGLE_CLIENT_ID`. The server
   checks that the token was minted for your app; if the two IDs differ, every
   sign-in is rejected — correctly.

---

## 4. Point it at the backend (optional)

The page is fully self-contained today: the plan generator, the coach and the
log all run in the browser. Connect it to the API when you want accounts and
data to actually persist.

`render.yaml` already describes the backend deployment. In the Render dashboard
set every `sync: false` variable (see section 5), then set `CORS_ORIGINS` to
your **front-end** URL — comma-separated, no wildcards, no trailing slash:

```
CORS_ORIGINS=https://mapo.pages.dev
```

Then in `app.js`, replace the local `signIn()` call in the Google callback
with a POST to your API:

```js
const r = await fetch(API + '/api/auth/google', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({credential: response.credential})
});
const {token, user} = await r.json();
localStorage.setItem('mapo_token', token);
signIn(user.name, 'google');
```

and send `Authorization: Bearer <token>` on calls to `/api/diet/plan`,
`/api/diet/plan/week`, `/api/chat` and `/api/logs`.

---

## 5. Where the `.env` file goes

**Never in `frontend/`.** Anything shipped to a browser is readable by anyone
who opens DevTools. There is no such thing as a secret in a static site.

- **Locally:** `backend/.env` — where it already is. It stays on your machine.
- **In production:** you do not upload the file at all. You retype each value
  into the Render dashboard under **Environment → Environment Variables**.
  That is exactly what `sync: false` means in `render.yaml` — "this value is
  not in this file, a human enters it in the dashboard."

Variables to set on Render:

| Key | Where it comes from |
|---|---|
| `MONGO_URL` | MongoDB Atlas → Connect → Drivers |
| `DB_NAME` | `mapo` |
| `JWT_SECRET` | Generate a **new** one: `openssl rand -hex 32` — do not reuse the local one |
| `CORS_ORIGINS` | Your front-end URL |
| `GROQ_API_KEY` | Groq console |
| `GOOGLE_CLIENT_ID` | Step 3 above |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Your choice; password must be 12+ chars |
| `ENVIRONMENT` | `production` |
| `TRUST_PROXY_HEADERS` | `1` |

A `.gitignore` now sits next to the backend so `.env` cannot be committed by
accident. Check it is working before your first push:

```bash
git status --short   # .env must NOT appear
```

If `.env` was ever committed, rotating the secrets is the only real fix —
deleting the file in a later commit does not remove it from history.
