# Domanda ad aider:
scrivi in ./DEPLOY.md una lista di cose che servono per fare deploy su vercel di questa webapp, con il piano gratuito di vercel


# Deploy su Vercel (piano gratuito Hobby)

Checklist per pubblicare questa webapp (SvelteKit + Supabase + LiveKit) su Vercel con il piano **Hobby (gratuito)**.

---

## 1. Requisiti preliminari

- [ ] Repository del progetto su GitHub / GitLab / Bitbucket.
- [ ] Account Vercel: https://vercel.com/signup — piano **Hobby**.
- [ ] Account Supabase (piano Free).
- [ ] Account LiveKit Cloud (piano Free).
- [ ] Node.js **22.x** in locale (richiesto da `@supabase/supabase-js`), verifica con `node -v`.

---

## 2. Preparazione del progetto

### 2.1 Adapter per Vercel

Il progetto usa `@sveltejs/adapter-auto`. Su Vercel questo richiede che il pacchetto `@sveltejs/adapter-vercel` sia installato come devDependency.

- [ ] Installare l'adapter:

```sh
cd webapp
npm install --save-dev @sveltejs/adapter-vercel
```

Non serve modificare `vite.config.ts`: `adapter-auto` rileva Vercel e usa automaticamente `adapter-vercel`.

### 2.2 Build locale di prova

- [ ] Copia `.env.example` in `.env` e riempi i valori (vedi §3).
- [ ] Verifica che la build passi:

```sh
npm run build
npm run preview
```

- [ ] Test funzionali locali: login / registrazione, cambio password, creazione stanza, permessi camera e microfono.

### 2.3 Pulizia del repository

- [ ] Verifica che `.env` non sia committato (`.gitignore` è già configurato per escluderlo).
- [ ] Verifica che `.svelte-kit/` e `test-results/` non siano nel repo.

---

## 3. Servizi esterni

### 3.1 Supabase (autenticazione)

- [ ] Crea un progetto su https://supabase.com (piano Free).
- [ ] Da **Project Settings → API** recupera:
  - **Project URL** → `PUBLIC_SUPABASE_URL`
  - **Publishable key** (o **anon key**) → `PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- [ ] Abilita il provider **Email** in **Authentication → Providers**.
- [ ] In **Authentication → URL Configuration** imposta:
  - **Site URL**: `https://<tuo-progetto>.vercel.app` (o il tuo dominio custom)
  - **Redirect URLs**, aggiungi tutte queste:
    - `https://<tuo-progetto>.vercel.app/auth/confirm`
    - `https://<tuo-progetto>.vercel.app/auth/confirm?next=/account`
    - `https://tuodominio.it/auth/confirm` (se usi un dominio custom)
    - (Opzionale) `https://*-<tuo-team>.vercel.app/auth/confirm` per i preview deployment
- [ ] Decidi se la conferma email è obbligatoria (di default è attiva).

### 3.2 LiveKit Cloud (video)

- [ ] Crea un progetto su https://cloud.livekit.io (piano Free).
- [ ] Da **Project Settings → Keys** recupera:
  - **WebSocket URL** (es. `wss://xxx.livekit.cloud`) → `LIVEKIT_URL`
  - **API Key** → `LIVEKIT_API_KEY`
  - **API Secret** → `LIVEKIT_API_SECRET`
- [ ] Verifica che il piano Free copra i tuoi volumi attesi (minuti / partecipanti).

---

## 4. Variabili d'ambiente su Vercel

Le variabili vanno impostate **prima** del primo build: il progetto usa `$env/static/private` e `$env/static/public`, che vengono "inlinate" in fase di compilazione. Se le cambi dopo, serve un **redeploy**.

Vercel → **Project → Settings → Environment Variables**:

| Nome | Visibilità | Environment | Usata in |
|---|---|---|---|
| `PUBLIC_SUPABASE_URL` | Public | Production, Preview, Development | `+layout.svelte`, `hooks.server.ts` |
| `PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Public | Production, Preview, Development | `+layout.svelte`, `hooks.server.ts` |
| `LIVEKIT_URL` | Secret | Production, Preview, Development | `stanza/[nome]/+page.server.ts` |
| `LIVEKIT_API_KEY` | Secret | Production, Preview, Development | `api/token/+server.ts` |
| `LIVEKIT_API_SECRET` | Secret | Production, Preview, Development | `api/token/+server.ts` |

- [ ] Aggiungi tutte le variabili.
- [ ] Per ognuna seleziona gli environment corretti (di norma tutti e tre).
- [ ] Non mischiare valori di test con quelli di produzione: se hai un progetto Supabase / LiveKit di sviluppo, usa environment diversi su Vercel.

> Nota: se una variabile è definita solo per Production, i **preview deployments falliranno in build** perché `$env/static/*` la richiede comunque.

---

## 5. Deploy

### 5.1 Primo deploy via dashboard

- [ ] Vercel → **Add New → Project → Import Git Repository**.
- [ ] **Root Directory**: `webapp` (il progetto è in una sottocartella).
- [ ] **Framework Preset**: *SvelteKit* (di solito rilevato in automatico).
- [ ] **Build Command**: `npm run build` (default).
- [ ] **Output Directory**: lascia vuoto (lo gestisce l'adapter).
- [ ] **Install Command**: `npm install` (default).
- [ ] **Node.js Version**: `22.x` in *Project Settings → General → Node.js Version*.
- [ ] Clicca **Deploy**.

### 5.2 Deploy da CLI (alternativa)

```sh
npm i -g vercel
cd webapp
vercel         # primo link al progetto
vercel --prod  # deploy in produzione
```

---

## 6. Verifiche post-deploy

- [ ] La home `https://<progetto>.vercel.app` risponde e mostra nell'header il pulsante **Accedi**.
- [ ] **Registrazione**: crea un account, ricevi l'email, il link di conferma torna su `/auth/confirm` e logga l'utente.
- [ ] **Login / Logout** funzionano.
- [ ] **Account** → cambio password funziona (con validazione dei due campi).
- [ ] **Password dimenticata** → ricevi l'email e il link riporta su `/account` con sessione attiva.
- [ ] **Stanza** `/stanza/test-1`:
  - il browser chiede permessi per camera e microfono (serve HTTPS: Vercel lo fornisce);
  - il token viene generato dall'endpoint `POST /api/token`;
  - audio/video funziona tra due dispositivi o due browser.
- [ ] **Logs**: Vercel → *Project → Logs* — nessun errore nelle function (`/api/token`, `/auth/confirm`, `/logout`, form action).
- [ ] Test su **mobile** (Safari iOS, Chrome Android) per permessi e WebRTC.

---

## 7. Limiti del piano Hobby di Vercel (da tenere d'occhio)

I limiti cambiano nel tempo: verifica sempre su https://vercel.com/pricing.

- **Fast Data Transfer**: ~100 GB/mese. Il traffico audio/video **non passa** da Vercel (LiveKit è un SFU separato): incidono solo HTML, JS, CSS e chiamate API.
- **Serverless Functions**:
  - Durata massima per invocazione limitata (default 10s su Hobby). Le function di questo progetto sono veloci e rientrano ampiamente.
  - Invocazioni mensili limitate: ogni chiamata a `/api/token`, `/auth/confirm`, `/logout` e ad una form action ne consuma una.
- **Deployments**: illimitati, inclusi quelli di preview.
- **Build**: durata massima per build ~45 minuti, ampiamente sufficiente.
- **Domini**: 1 dominio custom gratuito per progetto, HTTPS automatico.
- **Uso commerciale**: il piano Hobby è ammesso solo per progetti **non commerciali** secondo i termini Vercel. Se diventa un prodotto a pagamento, valuta il piano Pro.

---

## 8. Note specifiche del progetto

- **`$env/static/*` risolte a build-time**: ogni modifica a una env var richiede un **redeploy** per essere effettiva.
- **Sessione Supabase**: gestita nei cookie tramite `@supabase/ssr`; funziona su Vercel senza configurazioni aggiuntive.
- **Redirect auth sui Preview Deployment**: l'URL dei preview cambia ad ogni deploy. Se ti serve testare la conferma email in preview, aggiungi il wildcard nelle Redirect URLs di Supabase (vedi §3.1) oppure usa un dominio di preview stabile.
- **CORS / WebSocket**: nessuna configurazione richiesta; il traffico WebRTC va direttamente verso LiveKit.
- **Adapter**: `adapter-auto` è già configurato; su Vercel usa `@sveltejs/adapter-vercel`, che va installato (§2.1).
- **Cold start**: le function SvelteKit possono avere qualche centinaio di ms di avvio a freddo; impatto trascurabile per l'utente finale.
