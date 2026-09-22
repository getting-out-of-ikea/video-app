# Piano di implementazione — Autenticazione con Supabase (SvelteKit + Svelte 5)

> Questo documento è una guida passo-passo. Ogni passo ha:
> - **Cosa fare** (descrizione)
> - **Perché** (spiegazione)
> - **Snippet** (codice di esempio) — non copiare alla cieca: leggi la spiegazione.
>
> Il progetto `temp` usa Svelte 5 con **runes obbligatorie** (vedi `vite.config.ts`), quindi
> useremo `$state`, `$props`, `$effect` e una "store" basata su rune.

---

## 0. Concetti di base (da leggere prima)

- **Client vs Server in SvelteKit**
  - Il codice dentro `+page.server.ts` / `+layout.server.ts` / `hooks.server.ts` gira **solo sul server**.
  - Il codice dentro `<script>` di un componente `.svelte` gira **sia sul server (SSR) sia nel browser**.
  - Si usa `$app/environment` (`browser`, `dev`) per distinguere.

- **Perché Supabase richiede due client**
  - Nel **browser** il client legge i cookie per sapere chi è loggato.
  - Sul **server** il client deve leggere/scrivere i cookie della richiesta HTTP in corso
    (non esiste `document` sul server). Per farlo usiamo `@supabase/ssr`.
  - Questi due client **condividono gli stessi cookie**, quindi la sessione è coerente.

- **Perché una "store" se la sessione è già nei cookie**
  - I cookie sono "server-side": il codice front-end non può leggerli in modo reattivo.
  - Uno store reattivo permette a un componente come `+page.svelte` di scrivere
    `{#if auth.user}...` e di aggiornarsi automaticamente al login/logout.

---

## 1. Prerequisiti: creare il progetto Supabase

1. Vai su <https://supabase.com>, crea un progetto.
2. Nel pannello **Project Settings → API** copia:
   - `Project URL` (es. `https://xxxx.supabase.co`)
   - `Publishable key` (una chiave pubblica, es. `sb_publishable_...`)
   - La `Service Role key` **non ci serve**: è pericolosa se finisce nel browser.
3. In **Authentication → Providers → Email**:
   - Attiva "Email".
   - Per iniziare, **disattiva "Confirm email"** così puoi loggarti subito dopo la registrazione.
     (Lo riattiveremo al Passo 14.)

> Non serve creare tabelle per fare login: Supabase gestisce l'autenticazione in un
> schema interno (`auth.users`). Le tabelle serviranno più avanti per i tuoi dati.

---

## 2. Variabili d'ambiente

Il progetto ha già `temp/.env.example`. Copialo e compila i valori reali.

```bash
cp .env.example .env
```

```dotenv
# temp/.env
PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_xxxxxxxxxxxx
LIVEKIT_URL=wss://video-app-fmw62hbn.livekit.cloud
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
```

**Perché il prefisso `PUBLIC_`?**
SvelteKit fa vedere solo le variabili con prefisso `PUBLIC_` al codice **client**.
Le altre (come `LIVEKIT_API_SECRET`) sono leggibili **solo sul server**.
Questo è il meccanismo di sicurezza che impedisce a un utente di leggere i tuoi segreti dal browser.

**Import nel codice**

- `$env/static/public` → valori inclusi nel bundle al momento del build. Si usa per le chiavi pubbliche.
- `$env/static/private` → valori disponibili **solo** sul server. Si usa per le chiavi segrete.

```ts
// esempio di import (non scriverlo ancora, lo useremo tra poco)
import { PUBLIC_SUPABASE_URL, PUBLIC_SUPABASE_PUBLISHABLE_KEY } from '$env/static/public';
```

> Se modifichi `.env`, riavvia `npm run dev` perché `$env/static/*` viene "cablato" al build.

---

## 3. Verificare le dipendenze

Le librerie necessarie sono già in `package.json`:

```json
"@supabase/ssr": "^0.12.7",
"@supabase/supabase-js": "^2.116.0"
```

Se non fossero presenti:

```bash
npm install @supabase/supabase-js @supabase/ssr
```

---

## 4. Client Supabase per il **browser**

Crea un file dedicato nel browser client. Non va mai usato nel server.

```ts
// file da creare: src/lib/supabase/browser.ts
import { createBrowserClient } from '@supabase/ssr';
import {
	PUBLIC_SUPABASE_URL,
	PUBLIC_SUPABASE_PUBLISHABLE_KEY
} from '$env/static/public';

// Il client legge i cookie di sessione dal browser.
// Un solo client per tutta la vita dell'app: esportiamolo come singleton.
export const supabase = createBrowserClient(
	PUBLIC_SUPABASE_URL,
	PUBLIC_SUPABASE_PUBLISHABLE_KEY
);
```

**Spiegazione**
- `createBrowserClient` di `@supabase/ssr` è una versione di Supabase che legge i cookie
  automaticamente nel browser.
- Esportiamo un'**istanza unica**: creare più client in parallelo confonde la gestione dei cookie.

---

## 5. Client Supabase per il **server** (hooks)

Sul server **non** possiamo avere un singleton: ogni richiesta HTTP ha i suoi cookie.
Per questo creiamo un client nuovo a ogni richiesta e lo mettiamo in `event.locals`.

**File da creare:** `src/hooks.server.ts`

```ts
// src/hooks.server.ts
import { createServerClient } from '@supabase/ssr';
import type { Handle } from '@sveltejs/kit';
import {
	PUBLIC_SUPABASE_URL,
	PUBLIC_SUPABASE_PUBLISHABLE_KEY
} from '$env/static/public';

export const handle: Handle = async ({ event, resolve }) => {
	// 1) Creiamo un client Supabase legato AI COOKIE DI QUESTA RICHIESTA.
	event.locals.supabase = createServerClient(
		PUBLIC_SUPABASE_URL,
		PUBLIC_SUPABASE_PUBLISHABLE_KEY,
		{
			cookies: {
				// Leggo tutti i cookie della richiesta
				getAll: () => event.cookies.getAll(),
				// Scrivo i cookie quando Supabase rinnova la sessione
				setAll: (cookiesToSet) => {
					cookiesToSet.forEach(({ name, value, options }) => {
						event.cookies.set(name, value, { ...options, path: '/' });
					});
				}
			}
		}
	);

	// 2) Helper per leggere la sessione in modo SICURO.
	//    - getSession() legge solo il cookie (falso se il cookie è manomesso).
	//    - getUser() chiede conferma ai server di Supabase (fonte di verità).
	event.locals.safeGetSession = async () => {
		const {
			data: { session }
		} = await event.locals.supabase.auth.getSession();

		if (!session) return { session: null, user: null };

		const {
			data: { user },
			error
		} = await event.locals.supabase.auth.getUser();

		if (error) return { session: null, user: null };

		return { session, user };
	};

	return resolve(event, {
		// Lasciamo passare questi header al client (li usa Supabase)
		filterSerializedResponseHeaders: (name) =>
			name === 'content-range' || name === 'x-supabase-api-version'
	});
};
```

**Spiegazione dei punti chiave**
- `event.locals` è un contenitore che vive **per la durata di una singola richiesta**:
  è il posto giusto per dati "per richiesta" (client Supabase, utente loggato, ecc.).
- `setAll` è ciò che permette a Supabase di scrivere i cookie aggiornati quando
  rinnova il token: senza questo, l'utente verrebbe disconnesso ogni ora.
- `getUser()` fa un giro di rete verso Supabase. Non va chiamato in ogni componente:
  per questo lo esponiamo come funzione (`safeGetSession`) e lo invochiamo solo dove serve.

---

## 6. Tipizzare `locals` in `app.d.ts`

Senza tipi, TypeScript non sa che `event.locals.supabase` esiste.

**File da modificare:** `src/app.d.ts`

```ts
// src/app.d.ts
import type { SupabaseClient, Session, User } from '@supabase/supabase-js';

declare global {
	namespace App {
		interface Locals {
			supabase: SupabaseClient;
			safeGetSession: () => Promise<{ session: Session | null; user: User | null }>;
		}
	}
}

export {};
```

**Spiegazione**
- La cartella `src/app.d.ts` è il modo consigliato da SvelteKit per dichiarare tipi globali
  legati al framework (`App.Locals`, `App.PageData`, ecc.).
- Grazie a questa interfaccia, dentro `+page.server.ts` avrai l'autocompletamento
  su `locals.supabase` e `locals.safeGetSession`.

---

## 7. Lo store di autenticazione

Il progetto forza le **runes** di Svelte 5. Quindi:
- **NON** useremo `svelte/store` (`writable`, `readable`) — funziona ancora, ma è il pattern "vecchio".
- Useremo `$state` in un file `.svelte.ts`. Svelte compila `.svelte.ts` come un componente
  e quindi ammette le runes.

> ⚠️ **Perché non una semplice `export const store = $state(...)`?**
> In SvelteKit il codice di un modulo gira **anche sul server**, e sul server i moduli sono
> **condivisi tra tutte le richieste**. Se scrivessi l'utente A nello store, l'utente B
> potrebbe leggerlo (leak di sessione!). Per evitarlo, creiamo lo store come **fabbrica**
> e lo "agganciamo" al contesto del layout con `setContext`/`getContext`.

**File da creare:** `src/lib/auth.svelte.ts`

```ts
// src/lib/auth.svelte.ts
import { getContext, setContext } from 'svelte';
import type { Session, User } from '@supabase/supabase-js';

// Chiave unica per il contesto (Symbol evita collisioni con altre context).
const AUTH_KEY = Symbol('auth');

/**
 * Crea la store di autenticazione.
 * Riceve lo `session` iniziale (dal server) e ne espone una versione reattiva.
 */
export function createAuthStore(initialSession: Session | null) {
	let session = $state<Session | null>(initialSession);

	return {
		// getter → reattivi: i componenti si aggiornano automaticamente
		get session() {
			return session;
		},
		get user(): User | null {
			return session?.user ?? null;
		},
		get isLoggedIn() {
			return session !== null;
		},
		// permetti di aggiornare la store quando la sessione cambia
		setSession(next: Session | null) {
			session = next;
		}
	};
}

export type AuthStore = ReturnType<typeof createAuthStore>;

/** Chiama questo nel +layout.svelte (una sola volta). */
export function setAuth(store: AuthStore) {
	setContext(AUTH_KEY, store);
}

/** Chiama questo in qualsiasi componente figlio per leggere la store. */
export function useAuth(): AuthStore {
	return getContext(AUTH_KEY);
}
```

**Spiegazione**
- `$state` rende `session` reattivo: quando cambia, ogni componente che legge `auth.session`
  si ridisegna.
- I **getter** (`get user()`) sono reattivi anche loro e nascondono la logica
  (`user` è derivato da `session`).
- `setContext`/`getContext` sono funzioni Svelte che permettono di passare valori dal layout
  ai discendenti **senza** un singleton di modulo, quindi **sicuri per SSR**.

---

## 8. Caricare la sessione nel layout

Serve che il server legga la sessione dai cookie e la consegni al layout.

**File da creare:** `src/routes/+layout.server.ts`

```ts
// src/routes/+layout.server.ts
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals: { safeGetSession } }) => {
	const { session, user } = await safeGetSession();
	// `data.session`/`data.user` sarà disponibile in +layout.svelte
	return { session, user };
};
```

**Spiegazione**
- Questo `load` gira **a ogni richiesta**, anche quando navighi da una pagina all'altra.
- Restituisce `session`/`user` al component `+layout.svelte` come prop `data`.

**Poi aggiorna `src/routes/+layout.svelte`:**

```svelte
<!-- src/routes/+layout.svelte -->
<script lang="ts">
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import { browser } from '$app/environment';
	import { createAuthStore, setAuth } from '$lib/auth.svelte';
	import { supabase } from '$lib/supabase/browser';

	let { data, children } = $props();

	// 1) Inizializza la store con la sessione che arriva dal server.
	const auth = createAuthStore(data.session);
	// 2) Rendila disponibile a tutti i discendenti.
	setAuth(auth);

	// 3) Quando il server manda una nuova sessione (navigazione), aggiorna la store.
	$effect(() => {
		auth.setSession(data.session);
	});

	// 4) Ascolta i cambiamenti fatti nel browser (login / logout / refresh token).
	$effect(() => {
		if (!browser) return;
		const {
			data: { subscription }
		} = supabase.auth.onAuthStateChange((_event, session) => {
			auth.setSession(session);
		});
		return () => subscription.unsubscribe();
	});
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>

{@render children()}
```

**Spiegazione**
- `$effect` gira **solo nel browser**: è il posto giusto per iscriversi agli eventi.
- La funzione di cleanup (`return () => subscription.unsubscribe()`) evita memory leak.
- Ora `useAuth()` funziona in qualsiasi pagina figlia.

---

## 9. Usare la store in una pagina

Modifica la home per mostrare lo stato di login e un bottone di logout.

```svelte
<!-- src/routes/+page.svelte -->
<script lang="ts">
	import { useAuth } from '$lib/auth.svelte';

	const auth = useAuth();
</script>

<h1>Benvenuto</h1>

{#if auth.user}
	<p>Ciao <strong>{auth.user.email}</strong>!</p>

	<!-- Il logout è una POST: protegge da click/prefetch accidentali -->
	<form method="POST" action="/logout">
		<button type="submit">Esci</button>
	</form>
{:else}
	<p>
		<a href="/login">Accedi</a>
		o
		<a href="/signup">Registrati</a>
	</p>
{/if}
```

**Spiegazione**
- `auth.user` è reattivo: appena la sessione cambia, la pagina si aggiorna senza reload.
- `useAuth()` legge la store dal contesto impostato nel layout.
- `action="/logout"` punterà a `src/routes/logout/+server.ts` (lo creiamo al Passo 12).

---

## 10. Pagina di **login**

### 10a. Logica server — `src/routes/login/+page.server.ts`

```ts
// src/routes/login/+page.server.ts
import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';

// Se l'utente è già loggato, mandalo in home.
export const load: PageServerLoad = async ({ locals: { safeGetSession } }) => {
	const { user } = await safeGetSession();
	if (user) redirect(303, '/');
	return {};
};

export const actions: Actions = {
	default: async ({ request, locals: { supabase } }) => {
		const formData = await request.formData();
		const email = String(formData.get('email') ?? '');
		const password = String(formData.get('password') ?? '');

		if (!email || !password) {
			return fail(400, { email, message: 'Email e password obbligatorie' });
		}

		const { error } = await supabase.auth.signInWithPassword({ email, password });

		if (error) {
			// NB: non diciamo "email non esiste" o "password errata", per non
			// facilitare il phishing. Messaggio generico.
			return fail(400, { email, message: 'Credenziali non valide' });
		}

		// redirect lancia un'eccezione: non serve `return`.
		redirect(303, '/');
	}
};
```

**Spiegazione**
- `actions.default` è il gestore del submit del form (POST sulla stessa route).
- `fail(400, {...})` restituisce dati al form (li leggeremo come `form` in +page.svelte).
- `redirect(303, '/')` è una risposta HTTP che dice al browser di ricaricare su `/`.
  Il codice `303` è corretto dopo una POST (evita di replicare la POST).
- **Punto chiave**: la **password non arriva mai nel browser** dopo il submit, perché
  il form è gestito da `+page.server.ts`.

### 10b. Interfaccia client — `src/routes/login/+page.svelte`

```svelte
<!-- src/routes/login/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import type { ActionData } from './$types';

	let { form }: { form: ActionData } = $props();
</script>

<h1>Accedi</h1>

<form method="POST" use:enhance>
	<label for="email">Email</label>
	<input
		id="email"
		name="email"
		type="email"
		autocomplete="email"
		value={form?.email ?? ''}
		required
	/>

	<label for="password">Password</label>
	<input
		id="password"
		name="password"
		type="password"
		autocomplete="current-password"
		required
	/>

	{#if form?.message}
		<p role="alert" style="color: crimson;">{form.message}</p>
	{/if}

	<button type="submit">Accedi</button>
</form>

<p>Non hai un account? <a href="/signup">Registrati</a></p>
```

**Spiegazione**
- `use:enhance` fa sì che il form non ricarichi l'intera pagina: SvelteKit intercetta
  la POST e aggiorna lo stato client.
- Il valore `value={form?.email ?? ''}` mantiene quello che l'utente aveva scritto
  in caso di errore (buona UX).

---

## 11. Pagina di **registrazione**

### 11a. `src/routes/signup/+page.server.ts`

```ts
// src/routes/signup/+page.server.ts
import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals: { safeGetSession } }) => {
	const { user } = await safeGetSession();
	if (user) redirect(303, '/');
	return {};
};

export const actions: Actions = {
	default: async ({ request, locals: { supabase } }) => {
		const formData = await request.formData();
		const email = String(formData.get('email') ?? '');
		const password = String(formData.get('password') ?? '');

		if (!email || password.length < 6) {
			return fail(400, { email, message: 'Password di almeno 6 caratteri' });
		}

		const { data, error } = await supabase.auth.signUp({ email, password });

		if (error) {
			return fail(400, { email, message: error.message });
		}

		// Se Supabase ha "Confirm email" attivo, `session` è null e
		// bisogna confermare via email prima di poter accedere.
		if (!data.session) {
			return { email, message: 'Controlla la tua email per confermare l’account' };
		}

		redirect(303, '/');
	}
};
```

### 11b. `src/routes/signup/+page.svelte`

```svelte
<!-- src/routes/signup/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import type { ActionData } from './$types';

	let { form }: { form: ActionData } = $props();
</script>

<h1>Registrati</h1>

<form method="POST" use:enhance>
	<label for="email">Email</label>
	<input id="email" name="email" type="email" autocomplete="email"
		value={form?.email ?? ''} required />

	<label for="password">Password</label>
	<input id="password" name="password" type="password"
		autocomplete="new-password" minlength="6" required />

	{#if form?.message}
		<p role="alert" style="color: crimson;">{form.message}</p>
	{/if}

	<button type="submit">Crea account</button>
</form>

<p>Hai già un account? <a href="/login">Accedi</a></p>
```

---

## 12. Logout

Il logout **non** si fa da un `<a>` ma da una POST, per evitare click accidentali e
perché modifica lo stato sul server.

**File da creare:** `src/routes/logout/+server.ts`

```ts
// src/routes/logout/+server.ts
import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ locals: { supabase } }) => {
	await supabase.auth.signOut();
	redirect(303, '/');
};
```

Il form in `+page.svelte` (Passo 9) che punta a `/logout` funziona già.

---

## 13. Proteggere le route

SvelteKit non ha "middleware per route" tipico; il pattern canonico è usare il `load`.

### 13a. Bloccare un gruppo di route con un layout dedicato

Crea una cartella `(protected)` in `src/routes`. Le **parentesi** indicano un
**route group**: non aggiungono un segmento all'URL, servono solo a dividere
logica e layout.

```
src/routes/
├── (protected)/
│   ├── +layout.server.ts
│   ├── dashboard/
│   │   └── +page.svelte
│   └── account/
│       └── +page.svelte
├── login/
└── signup/
```

**File da creare:** `src/routes/(protected)/+layout.server.ts`

```ts
// src/routes/(protected)/+layout.server.ts
import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals: { safeGetSession }, url }) => {
	const { user } = await safeGetSession();
	if (!user) {
		// Salva dove stava andando l'utente, per riportarlo lì dopo il login (opzionale)
		redirect(303, `/login?next=${encodeURIComponent(url.pathname)}`);
	}
	return {};
};
```

**Spiegazione**
- Ogni route dentro `(protected)` esegue **prima** questo `load`: se non c'è `user`,
  viene emesso un redirect al login.
- Futuro miglioramento opzionale (fuori scope): leggere `?next=` nel login per
  rimandare l'utente alla pagina che voleva aprire.

### 13b. Protezione "a granulometria fine"

Per proteggere una singola pagina, ripeti la stessa logica in
`src/routes/foo/+page.server.ts`:

```ts
import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals: { safeGetSession } }) => {
	const { user } = await safeGetSession();
	if (!user) redirect(303, '/login');
	return { user };
};
```

---

## 14. Opzionale — Conferma email

1. In Supabase: **Authentication → Providers → Email → Confirm email = ON**.
2. In **Authentication → URL Configuration** imposta
   *Site URL* = `http://localhost:5173` (per lo sviluppo).
3. Supabase invierà una email il cui link contiene un `code`. Devi avere una route
   che scambia il `code` con la sessione.

**File da creare:** `src/routes/auth/confirm/+server.ts`

```ts
// src/routes/auth/confirm/+server.ts
import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import type { EmailOtpType } from '@supabase/supabase-js';

export const GET: RequestHandler = async ({ url, locals: { supabase } }) => {
	const token_hash = url.searchParams.get('token_hash');
	const type = url.searchParams.get('type') as EmailOtpType | null;

	if (token_hash && type) {
		const { error } = await supabase.auth.verifyOtp({ token_hash, type });
		if (!error) redirect(303, '/');
	}

	redirect(303, '/login?error=link_non_valido');
};
```

Imposta nel template email di Supabase il link in modo che punti a:
`{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email`.

---

## 15. Opzionale — Reset password

1. **`src/routes/password-reset/+page.server.ts`** con un'action che chiama
   `supabase.auth.resetPasswordForEmail(email, { redirectTo: '/account/update-password' })`.
2. **`src/routes/password-reset/confirm/+server.ts`** come al Passo 14, ma con
   `type=recovery`.
3. **`src/routes/account/update-password/+page.server.ts`** con un'action che chiama
   `supabase.auth.updateUser({ password })` (richiede che l'utente sia loggato
   tramite il link di recovery, cosa che avviene automaticamente dopo il `verifyOtp`).

Snippet essenziale per l'action di reset:

```ts
// dentro actions.default di src/routes/password-reset/+page.server.ts
await supabase.auth.resetPasswordForEmail(email, {
	redirectTo: `${url.origin}/auth/confirm?type=recovery&next=/account/update-password`
});
```

> Nota: `redirectTo` deve essere un URL "sicuro" configurato in Supabase,
> altrimenti Supabase lo rifiuta. In sviluppo va bene `http://localhost:5173/...`.

---

## 16. Verifica finale — lista di controllo

1. `npm run dev` e apri `http://localhost:5173`.
2. Crea un account su `/signup` → dovresti finire in `/` loggato.
3. In home, il nome della store mostra l'email. Ricarica la pagina: la sessione persiste.
4. Premendo il bottone di logout torni a "Accedi".
5. Crea una pagina `src/routes/(protected)/dashboard/+page.svelte` e visita
   `/dashboard`: senza login devi essere rimandato a `/login`.
6. `npx svelte-check`: nessun errore di tipi.

---

## 17. Errori comuni e come riconoscerli

- **`locals.supabase` non esiste**: hai dimenticato il `hooks.server.ts` o la dichiarazione
  in `app.d.ts`.
- **`PUBLIC_SUPABASE_URL is undefined`**: `.env` non ha le chiavi `PUBLIC_*` o non hai
  riavviato il dev server dopo averle aggiunte.
- **"Invalid API key"**: hai incollato la chiave sbagliata; sul client va la
  `Publishable key`, non la `service_role`.
- **Sessione persa ad ogni navigazione**: probabilmente `setAll` in `hooks.server.ts`
  non scrive i cookie (controlla il `path: '/'`).
- **"cannot use $state outside of .svelte.ts / .svelte"**: le runes funzionano solo in
  file con estensione `.svelte`, `.svelte.ts` o `.svelte.js`.
- **`useAuth() is not a function` / `undefined`**: stai chiamando `useAuth()` in un
  componente **fuori** dal layout, o hai dimenticato `setAuth(auth)` nel layout.

---

## 18. Prossimi passi (quando l'autenticazione funziona)

- Generare i tipi del database:
  `npx supabase gen types typescript --project-id <id> > src/lib/supabase/database.types.ts`
  e usare `createBrowserClient<Database>(...)` per una type-safety completa.
- Aggiungere una tabella `profiles` collegata a `auth.users.id`, con una policy RLS
  `user_id = auth.uid()`.
- Aggiungere un'UI più curata (Tailwind è già configurato).
- Test end-to-end (Playwright è già configurato) che coprano login/logout.
