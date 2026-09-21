# Piano: aggiungere l'autenticazione con Supabase a `temp/` — piano di implementazione

> **Ambito.** Tutto quanto segue riguarda l'app dentro `temp/` (SvelteKit 2, Svelte 5 runes, Tailwind 4,
> `adapter-auto`, Vitest + Playwright già configurati). L'app sorella in `webapp/` implementa già il
> pattern server di `@supabase/ssr` (`webapp/src/hooks.server.ts`, `webapp/src/app.d.ts`); questo piano
> **segue deliberatamente quelle convenzioni**, così le due app restano coerenti. Nessun file dentro
> `webapp/` viene toccato.
>
> **Stile del documento.** È una guida, non una patch. Gli snippet sono brevi e servono a essere
> digitati e adattati. Ogni snippet è seguito dal *perché*.

---

## Indice

0. [Presupposti](#0-presupposti)
1. [Modello mentale](#1-modello-mentale-leggi-prima-di-scrivere-codice)
2. [Passo per passo](#2-passo-per-passo)
3. [Checklist dei file](#3-checklist-dei-file)
4. [Ordine di lavoro consigliato](#4-ordine-di-lavoro-consigliato-ogni-passo-termina-in-uno-stato-verificabile)
5. [Errori tipici da evitare](#5-errori-tipici-da-evitare-riepilogo)
6. [Estensioni opzionali](#6-estensioni-opzionali-da-valutare-in-seguito)
7. [Fuori ambito, volutamente](#7-fuori-ambito-volutamente)
8. [Domande aperte](#8-domande-aperte)

---

## 0. Presupposti

| # | Presupposto |
|---|---|
| A1 | Hai già un progetto Supabase (org/ref) e puoi aprire la dashboard. |
| A2 | Metodo di autenticazione scelto: **email + password**. Magic link / OTP / OAuth sono trattati più avanti come blocchi opzionali. |
| A3 | La conferma email è **attiva** nella dashboard (è il default di Supabase). |
| A4 | Solo una parte delle route deve essere privata: il gruppo `(private)` e `/stanza/[nome]` — vedi `piano.md`, Fase 1. |
| A5 | La sessione è salvata in **cookie** tramite `@supabase/ssr` (non in localStorage), così la SSR può leggerla. |
| A6 | L'app è deployata da qualche parte con HTTPS in produzione. |
| A7 | Non esiste ancora uno schema di database; a questo stadio si usano solo `auth.users` e i suoi metadata. |

---

## 1. Modello mentale (leggi prima di scrivere codice)

Tre idee reggono tutto il disegno:

1. **Un client per contesto.**
   - Nel **browser**: un solo `createBrowserClient` creato in modo lazy, così lo stato di autenticazione
     e il timer di refresh non vengono duplicati.
   - Sul **server**: un *nuovo* `createServerClient` **per ogni richiesta**, collegato ai cookie di quella
     richiesta. Un client server a livello di modulo farebbe trapelare la sessione di un utente nella
     richiesta di un altro.

2. **La sessione vive nei cookie, la verità vive sul server di autenticazione.**
   `auth.getSession()` si limita a leggere e decodificare il cookie — quindi è controllabile da un
   attaccante. Solo `auth.getUser()` (o `getClaims()`) chiede al server Supabase Auth di validare il JWT.
   Quindi: **usa `getSession()` per letture di comodo, usa `getUser()` per ogni decisione di
   autorizzazione.**

3. **Il controllo lato server è il confine di sicurezza; i controlli lato client sono solo UX.**
   Nascondere un link non è una protezione. La protezione è un `redirect(303, …)` dentro una funzione
   `load` oppure in `hooks.server.ts`.

Flusso di una richiesta, una volta implementato tutto:

~~~
browser form POST
   → +page.server.ts action
   → locals.supabase.auth.signInWithPassword()
   → setAll() writes the session cookie onto the response
   → browser follows redirect
   → hooks.server.ts builds a fresh client from those cookies
   → locals.safeGetSession() → locals.user
   → +layout.server.ts / +page.server.ts loads see locals.user and gate the route
~~~

---

## 2. Passo per passo

### Step 1 — Dipendenze e variabili d'ambiente

~~~bash
npm install @supabase/supabase-js @supabase/ssr
~~~

Sono entrambe dipendenze **di runtime**, non devDependencies (finiscono nel bundle del browser).

Crea `temp/.env.local` (verifica che sia ignorato da git; `.env.example` resta versionato):

~~~ini
PUBLIC_SUPABASE_URL=https://<your-ref>.supabase.co
PUBLIC_SUPABASE_PUBLISHABLE_KEY=<your-publishable-key>
~~~

*Perché:* il prefisso `PUBLIC_` le rende leggibili sia dal codice server sia da quello client tramite
`$env/static/public`. Sono sicure da spedire al browser **solo** perché sono la publishable key. Una
chiave `service_role` non deve mai comparire in una variabile `PUBLIC_` e non deve mai essere importata
da codice client.

Opzionale ma consigliato — un modulo che fallisce subito, così una variabile mancante è un errore
chiaro e non un `fetch` fallito in modo misterioso a runtime:

~~~ts
// src/lib/supabase/env.ts
import { PUBLIC_SUPABASE_URL, PUBLIC_SUPABASE_PUBLISHABLE_KEY } from '$env/static/public';

if (!PUBLIC_SUPABASE_URL || !PUBLIC_SUPABASE_PUBLISHABLE_KEY) {
	throw new Error('Missing PUBLIC_SUPABASE_URL / PUBLIC_SUPABASE_PUBLISHABLE_KEY');
}

export const SUPABASE_URL = PUBLIC_SUPABASE_URL;
export const SUPABASE_KEY = PUBLIC_SUPABASE_PUBLISHABLE_KEY;
~~~

> `$env/static/public` incolla i valori in fase di build. Se vuoi un'unica build deployata su più
> ambienti, usa `$env/dynamic/public` (che è permesso *solo* sul server, a meno di passarlo verso il
> client attraverso un `load`). Per ora, la versione statica è più semplice.

**Verifica:** `npm run dev` parte ancora.

---

### Step 2 — Client browser (`src/lib/supabase/client.ts`)

~~~ts
import { createBrowserClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';
import { SUPABASE_URL, SUPABASE_KEY } from './env';

let client: SupabaseClient | undefined;

export function supabaseBrowserClient(): SupabaseClient {
	client ??= createBrowserClient(SUPABASE_URL, SUPABASE_KEY);
	return client;
}
~~~

*Perché:* il singleton con `??=` è importante. Creare un secondo client browser genera un secondo
listener di autenticazione e un secondo timer di refresh del token, cosa che produce logout casuali ed
eventi `onAuthStateChange` duplicati.

---

### Step 3 — Client server + helper di sessione (`src/hooks.server.ts`)

Questo è il file chiave di volta.

~~~ts
import { createServerClient } from '@supabase/ssr';
import type { Handle } from '@sveltejs/kit';
import { SUPABASE_URL, SUPABASE_KEY } from '$lib/supabase/env';

export const handle: Handle = async ({ event, resolve }) => {
	event.locals.supabase = createServerClient(SUPABASE_URL, SUPABASE_KEY, {
		cookies: {
			// read every cookie this request carries
			getAll: () => event.cookies.getAll(),
			// write back whatever Supabase asks for (initial set, refresh, clear)
			setAll: (cookiesToSet) => {
				cookiesToSet.forEach(({ name, value, options }) => {
					event.cookies.set(name, value, { ...options, path: '/' });
				});
			}
		}
	});

	// Cheap read (UX) + authoritative validation (security)
	event.locals.safeGetSession = async () => {
		const {
			data: { session },
			error
		} = await event.locals.supabase.auth.getSession();
		if (error) throw error;
		if (!session) return { session: null, user: null };

		const {
			data: { user },
			error: userError
		} = await event.locals.supabase.auth.getUser();
		if (userError) throw userError;

		return { session, user };
	};

	return resolve(event, {
		filterSerializedResponseHeaders(name) {
			// Supabase libraries use these headers; tell SvelteKit to pass them through
			return name === 'content-range' || name === 'x-supabase-api-version';
		}
	});
};
~~~

*Perché ogni pezzo:*
- `getAll`/`setAll` è l'API cookie attuale di `@supabase/ssr` (i tutorial vecchi usano `get`/`set`/`remove`
  e anche un argomento `cookieOptions` — se stai copiando da un post vecchio, quello è il segnale che è
  superato).
- `path: '/'` garantisce che un refresh scritto da una route profonda sia visibile ovunque.
- Il nome `safeGetSession` è quello già usato in `webapp/`; mantenerlo significa avere lo stesso modello
  mentale e la stessa forma in `app.d.ts` in entrambe le app.
- Il blocco `filterSerializedResponseHeaders` serve per le query con `count: 'exact'` e per l'header di
  versione dell'API Supabase.
- Se l'helper di Supabase dovesse mai scrivere un cookie durante il render di un *server component*,
  verrebbe lanciato l'errore "Cookies can only be modified in a server action or endpoint"; il corpo di
  `setAll` si può avvolgere in un `try/catch` per ignorare quel caso, perché la sessione verrà comunque
  salvata alla richiesta successiva.

**Verifica:** aggiungi temporaneamente `console.log(await event.locals.safeGetSession())` — con un
browser pulito dovresti vedere `{ session: null, user: null }`.

---

### Step 4 — Tipizzare i locals (`src/app.d.ts`)

~~~ts
import type { SupabaseClient, Session, User } from '@supabase/supabase-js';

declare global {
	namespace App {
		interface Locals {
			supabase: SupabaseClient;
			safeGetSession: () => Promise<{ session: Session | null; user: User | null }>;
			session: Session | null;
			user: User | null;
		}
		interface PageData {
			session: Session | null;
			user: User | null;
		}
	}
}

export {};
~~~

*Perché:* adesso `svelte-check` e l'editor ti completano `locals.user` e segnalano i refusi. La forma
corrisponde a quella di `webapp/src/app.d.ts`.

**Verifica:** `npm run check`.

---

### Step 5 — Rendere la sessione disponibile a ogni pagina

**5a. Dati del layout lato server — `src/routes/+layout.server.ts`**

~~~ts
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals }) => {
	const { session, user } = await locals.safeGetSession();
	locals.session = session;
	locals.user = user;

	return { session, user };
};
~~~

*Perché:* `safeGetSession` viene chiamata in un solo punto per ogni navigazione, ogni pagina e ogni
layout a valle può leggere `data.user`, e `locals.user` risulta popolato per i controlli di accesso.

**5b. Ri-validazione lato client — `src/routes/+layout.ts`**

~~~ts
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async ({ data, depends }) => {
	depends('supabase:auth');
	return { session: data.session, user: data.user };
};
~~~

*Perché:* `depends('supabase:auth')` ci permette di rieseguire tutte le funzioni `load` quando cambia
lo stato di autenticazione, senza ricaricare l'intera pagina.

**5c. Layout e navigazione — `src/routes/+layout.svelte`**

~~~svelte
<script lang="ts">
	import { invalidate } from '$app/navigation';
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import { supabaseBrowserClient } from '$lib/supabase/client';

	let { data, children } = $props();

	const supabase = supabaseBrowserClient();

	$effect(() => {
		const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
			// ignore the initial synthetic event, refresh only on a real change
			if (session?.expires_at !== data.session?.expires_at) {
				invalidate('supabase:auth');
			}
		});
		return () => subscription.unsubscribe();
	});
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>

<nav>
	{#if data.user}
		<a href="/account">Account</a>
		<form method="POST" action="/logout">
			<button type="submit">Log out</button>
		</form>
	{:else}
		<a href="/login">Log in</a>
	{/if}
</nav>

{@render children()}
~~~

*Perché:* `onAuthStateChange` è l'unico modo affidabile per accorgersi di un refresh del token o di un
logout avvenuto in un'altra scheda. Restituire la funzione di unsubscribe dall'`$effect` evita listener
che restano in memoria. Non chiamare mai metodi Supabase *dentro* il callback — imposta lo stato e lascia
che `invalidate` riesegua i `load`.

> Se preferisci lasciare intatto l'attuale `temp/src/routes/+layout.svelte` e togliere l'import di
> `supabaseBrowserClient`, tutto quanto descritto negli Step 6–10 continua a funzionare; perdi solo il
> refresh quando un'altra scheda fa logout.

**Verifica:** naviga l'app; senza sessione la nav mostra "Log in".

---

### Step 6 — Form di login basato su una server action

**`src/routes/login/+page.server.ts`**

~~~ts
import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';

// already logged in? don't show the form
export const load: PageServerLoad = async ({ locals, url }) => {
	const { user } = await locals.safeGetSession();
	if (user) redirect(303, url.searchParams.get('redirectTo') ?? '/');
	return {};
};

export const actions: Actions = {
	default: async ({ request, locals, url }) => {
		const formData = await request.formData();
		const email = String(formData.get('email') ?? '').trim();
		const password = String(formData.get('password') ?? '');

		const { error } = await locals.supabase.auth.signInWithPassword({ email, password });

		if (error) {
			return fail(400, { email, message: error.message });
		}

		const target = url.searchParams.get('redirectTo');
		redirect(303, target && target.startsWith('/') && !target.startsWith('//') ? target : '/');
	}
};
~~~

*Perché una server action invece di `supabase.auth.signInWithPassword()` nel browser?*
- Funziona prima e anche senza JavaScript (progressive enhancement).
- Il cookie viene scritto dall'helper server dentro `setAll`, quindi non c'è il "lampo" di contenuto
  non autenticato mentre la libreria client si avvia.
- Gli errori di validazione tornano come `form.message`, banali da mostrare.

*Due trappole:*
1. `redirect()` e `fail()` **lanciano un'eccezione**. Non chiamarli mai dentro un `try/catch` che
   inghiotte gli errori — oppure, se devi farlo, rilanciali con `isRedirect(e)` / `isHttpError(e)`.
2. `redirectTo` arriva dalla query string, quindi va validato (altrimenti è un open redirect). Basta il
   controllo minimo qui sopra, o l'helper riutilizzabile dello Step 10a.

**`src/routes/login/+page.svelte`**

~~~svelte
<script lang="ts">
	import { enhance } from '$app/forms';
	let { form } = $props();
</script>

<h1>Log in</h1>

<form method="POST" use:enhance>
	<label for="email">Email</label>
	<input id="email" name="email" type="email" autocomplete="email" required value={form?.email ?? ''} />

	<label for="password">Password</label>
	<input id="password" name="password" type="password" autocomplete="current-password" required />

	{#if form?.message}
		<p role="alert" aria-live="polite">{form.message}</p>
	{/if}

	<button type="submit">Log in</button>
</form>

<p>No account? <a href="/register">Sign up</a></p>
~~~

*Perché:* `use:enhance` trasforma un normale form HTML in un submit via fetch, con stato di caricamento,
ma il form continua a funzionare anche con JavaScript disattivato. Gli attributi `autocomplete` fanno
sì che i gestori di password del browser compilino e salvino le credenziali correttamente. `role="alert"`
annuncia gli errori agli screen reader.

---

### Step 7 — Registrazione

La registrazione ha la stessa forma del login, con `auth.signUp`:

~~~ts
import { fail } from '@sveltejs/kit';
import { safeRedirect } from '$lib/supabase/redirect';
import type { Actions } from './$types';

export const actions: Actions = {
	default: async ({ request, locals, url }) => {
		const formData = await request.formData();
		const email = String(formData.get('email') ?? '').trim();
		const password = String(formData.get('password') ?? '');
		const next = safeRedirect(String(formData.get('next') ?? '/'), '/');

		if (password.length < 8) {
			return fail(400, { email, message: 'Password must be at least 8 characters' });
		}

		const { data, error } = await locals.supabase.auth.signUp({
			email,
			password,
			options: {
				// where Supabase sends the user after they click the confirmation link
				emailRedirectTo: `${url.origin}/auth/confirm?next=${encodeURIComponent(next)}`
			}
		});

		if (error) {
			return fail(400, { email, message: error.message });
		}

		// confirmation ON → no session yet, the user must open the email
		if (!data.session) {
			return { email, message: 'Check your inbox to confirm your address.' };
		}

		// confirmation OFF → already signed in
		return { email, message: 'Account created.' };
	}
};
~~~

*Perché qui è diverso dal login:*
- **Non reindirizzare a una route protetta.** Con la conferma email attiva, `data.session` è `null` e
  `data.user` esiste ma non è confermato; un redirect rimbalzerebbe subito l'utente indietro con il
  `redirectTo`.
- **La stessa pagina deve gestire tre stati**: iniziale, errore e "controlla la casella di posta". Bastano
  un `form.message` e un blocco condizionale.
- Un controllo minimo sulla lunghezza della password lato server vale la pena anche se Supabase impone
  già un minimo — ti permette di mostrare un messaggio leggibile nella lingua della tua UI.

Alla `+page.svelte` corrispondente servono solo i campi aggiuntivi e il blocco condizionale:

~~~svelte
{#if form?.message}
	<p role="alert" aria-live="polite">{form.message}</p>
{/if}
~~~

*Perché `auth.signUp` e non l'API di amministrazione:* l'endpoint admin `createUser` richiede la chiave
`service_role`, che non deve mai essere raggiungibile da una route pubblica. La registrazione self-service
è l'unica opzione sensata qui.

---

### Step 8 — Logout (`src/routes/logout/+server.ts`)

~~~ts
import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ locals }) => {
	await locals.supabase.auth.signOut();
	redirect(303, '/login');
};
~~~

*Perché POST e non GET:* un logout via GET può essere innescato da un qualsiasi `<img src>` su un sito
qualunque (una seccatura in stile CSRF). Il form nella nav dello Step 5c usa già POST.

---

### Step 9 — Conferma email (dashboard + `/auth/confirm`)

**9a. Dashboard Supabase**
- *Auth → Providers → Email*: lascia attiva la conferma email.
- *Auth → URL Configuration*: **Site URL** = il tuo URL di sviluppo (`http://localhost:5173`), e aggiungi
  nelle **Redirect URLs** sia `http://localhost:5173/**` sia l'origine di produzione `https://…/**`.
  Qualunque URL non presente in allowlist ricade silenziosamente sulla Site URL.
- *Auth → Email Templates → Confirm sign up*: punta il link verso una tua route:

~~~html
<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email&next=/account">
  Confirm your email
</a>
~~~

*Perché `token_hash` e non il `{{ .ConfirmationURL }}` predefinito:* il link predefinito passa da Supabase,
che poi rimbalza indietro con `?code=`; se l'utente apre il link da un dispositivo diverso da quello con
cui si è registrato, manca il code verifier PKCE e lo scambio fallisce. Il flusso con `token_hash` funziona
da qualsiasi dispositivo.

**9b. `src/routes/auth/confirm/+server.ts`**

~~~ts
import { redirect } from '@sveltejs/kit';
import { safeRedirect } from '$lib/supabase/redirect';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ url, locals }) => {
	const token_hash = url.searchParams.get('token_hash');
	const type = url.searchParams.get('type');
	const next = safeRedirect(url.searchParams.get('next'), '/');

	if (token_hash && type) {
		const { error } = await locals.supabase.auth.verifyOtp({
			type: type as 'email' | 'recovery' | 'magiclink' | 'email_change',
			token_hash
		});
		if (!error) redirect(303, next);
	}

	redirect(303, '/auth/error');
};
~~~

*Nota:* `verifyOtp` supporta anche `type: 'recovery'` (reset password) e `'magiclink'`. Aggiungi una
pagina `/auth/error` con un messaggio chiaro e un link per richiedere di nuovo l'email:

~~~svelte
<!-- src/routes/auth/error/+page.svelte -->
<h1>Link non valido o scaduto</h1>
<p>Richiedi di nuovo l'email di conferma oppure <a href="/login">accedi</a>.</p>
~~~

**Verifica:** registrati con una casella reale, clicca il link e atterra su `/account` già autenticato.

---

### Step 10 — Proteggere le route

**10a. L'helper condiviso contro gli open redirect — `src/lib/supabase/redirect.ts`**

~~~ts
export function safeRedirect(target: string | null | undefined, fallback = '/'): string {
	if (!target) return fallback;
	if (!target.startsWith('/') || target.startsWith('//') || target.startsWith('/\\')) return fallback;
	return target;
}
~~~

*Perché:* `redirectTo` e `next` arrivano dalla query string o da un campo nascosto, quindi possono
contenere `//evil.com`. Centralizzare il controllo significa che la regola non può divergere tra l'azione
di login, l'endpoint di conferma e i guard. Inoltre è una funzione minuscola e testabile con Vitest, che
hai già configurato.

**10b. Opzione A — proteggere un gruppo di route (consigliata per A4).**

Sposta le pagine private in un gruppo e proteggile in un punto solo:

~~~ts
// src/routes/(private)/+layout.server.ts
import { redirect } from '@sveltejs/kit';
import { safeRedirect } from '$lib/supabase/redirect';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals, url }) => {
	const { session, user } = await locals.safeGetSession();
	locals.session = session;
	locals.user = user;

	if (!user) {
		const redirectTo = safeRedirect(url.pathname + url.search);
		redirect(303, `/login?redirectTo=${encodeURIComponent(redirectTo)}`);
	}

	return { session, user };
};
~~~

A quel punto `src/routes/(private)/account/+page.svelte` si limita a mostrare `data.user.email`; il layout
padre non sarebbe stato renderizzato se non ci fosse stato un utente. Le cartelle di gruppo tra parentesi
non compaiono nell'URL.

**10c. Proteggere la stanza video — `src/routes/stanza/[nome]/+page.server.ts`**

La Fase 1 di `piano.md` richiede che `/stanza/[nome]` sia raggiungibile solo da utenti autenticati e che
il nome della stanza sia valido. Questo controllo *non* è compito del solo endpoint del token: un utente
che riesce ad aprire la pagina pre-join con un nome non valido ottiene un errore confuso più tardi.

~~~ts
import { error, redirect } from '@sveltejs/kit';
import { safeRedirect } from '$lib/supabase/redirect';
import { isValidRoomName } from '$lib/rooms';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals, params, url }) => {
	const { session, user } = await locals.safeGetSession();
	locals.session = session;
	locals.user = user;

	if (!user) {
		redirect(303, `/login?redirectTo=${encodeURIComponent(safeRedirect(url.pathname + url.search))}`);
	}

	if (!isValidRoomName(params.nome)) {
		error(404, 'Stanza non trovata');
	}

	return { roomName: params.nome, displayName: user.email ?? 'Ospite' };
};
~~~

*Perché 404 e non 400:* per chi visita il sito un nome stanza malformato è indistinguibile da uno
inesistente, e il 404 riduce la superficie informativa. `src/lib/rooms.ts` esiste già in `webapp/`:
copialo in `temp/src/lib/` invece di scrivere la regex a mano, così l'endpoint del token e la pagina
validano con la *stessa* regola.

**10d. Opzione B — controllo centralizzato in `hooks.server.ts`** (solo se quasi tutto diventa privato):

~~~ts
const PUBLIC_PATHS = ['/login', '/register', '/auth'];
const isPublic = (p: string) => PUBLIC_PATHS.some((x) => p === x || p.startsWith(x + '/'));

// inside handle(), after locals.safeGetSession is defined:
const { user } = await event.locals.safeGetSession();
if (!user && !isPublic(event.url.pathname) && !event.url.pathname.startsWith('/api/')) {
	redirect(303, `/login?redirectTo=${encodeURIComponent(event.url.pathname + event.url.search)}`);
}
~~~

*Perché di solito A è meglio:* il controllo vive accanto alle pagine che protegge e non richiede una
allowlist mantenuta a mano che può andare fuori sincrono. L'opzione B è anche una mazzata per le route
API — ricorda che `redirect(303, '/login')` è la risposta sbagliata per un endpoint JSON; lì vuoi
`error(401, 'not authenticated')`.

---

### Step 11 — Insegnare all'endpoint del token LiveKit chi è l'utente

Il tuo `temp/.env.example` contiene già `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`, quindi
quando scriverai `src/routes/api/token/+server.ts` (Fase 2 di `piano.md`) dovrà ricavare l'identità dalla
sessione:

~~~ts
import { error, json } from '@sveltejs/kit';
import { AccessToken } from 'livekit-server-sdk';
import { LIVEKIT_API_KEY, LIVEKIT_API_SECRET } from '$env/static/private';
import { isValidRoomName } from '$lib/rooms';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ request, locals }) => {
	const { user } = await locals.safeGetSession();
	if (!user) error(401, 'not authenticated');

	const { roomName } = await request.json();
	if (!isValidRoomName(roomName)) error(400, 'invalid room name');

	const identity = user.id;
	const displayName = user.user_metadata?.display_name ?? user.email ?? 'guest';

	const token = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, {
		identity,
		name: displayName,
		ttl: '15m'
	});
	token.addGrant({ room: roomName, roomJoin: true, canPublish: true, canSubscribe: true });

	return json({ token: await token.toJwt() });
};
~~~

*Perché:* il token di accesso LiveKit concede i diritti di pubblicazione e sottoscrizione. Se `identity`
arrivasse dal body della richiesta, qualunque utente autenticato potrebbe impersonare un altro
partecipante. La stanza invece *può* legittimamente arrivare dal client (è l'utente che l'ha scelta), ma
va validata e, quando avrai un database, verificata contro una tabella di appartenenza. L'endpoint
`webapp/src/routes/api/token/+server.ts` è il pattern di riferimento. Tieni la scadenza breve (minuti,
non ore) e lascia che il client ne richieda uno nuovo.

---

### Step 12 — Test e controlli

1. **Unit (Vitest, già configurato in `temp/`)** — `src/lib/supabase/redirect.spec.ts`:

~~~ts
import { describe, expect, it } from 'vitest';
import { safeRedirect } from './redirect';

describe('safeRedirect', () => {
	it('keeps internal paths', () => expect(safeRedirect('/stanza/sala-1')).toBe('/stanza/sala-1'));
	it('rejects scheme-relative URLs', () => expect(safeRedirect('//evil.com')).toBe('/'));
	it('rejects backslash tricks', () => expect(safeRedirect('/\\evil.com')).toBe('/'));
	it('falls back on null', () => expect(safeRedirect(null)).toBe('/'));
});
~~~

   Lo stesso trattamento vale per `isValidRoomName` una volta copiato `src/lib/rooms.ts`.
2. **E2E (Playwright, già configurato)** — due test economici con un utente dedicato ai test:
   - da non autenticato, `page.goto('/account')` termina su `/login?redirectTo=%2Faccount`;
   - compila il form di login, invia, e verifica l'intestazione della pagina account e il cookie di sessione.
   Tieni le credenziali in `.env.test`/nei secret della CI e usa un utente seed, non il tuo account
   personale. La conferma email non è automatizzabile in un normale run E2E — crea l'utente di test già
   confermato dalla dashboard Supabase o tramite uno script di amministrazione.
3. `npm run check && npm run lint && npm run test`.

---

## 3. Checklist dei file

| File | Azione | Scopo |
|---|---|---|
| `temp/package.json` | modificare | aggiungere `@supabase/supabase-js`, `@supabase/ssr` |
| `temp/.env.local` | nuovo (ignorato) | URL Supabase locale + publishable key |
| `temp/.env.example` | esiste già | elenca già entrambe le variabili `PUBLIC_SUPABASE_*` |
| `temp/src/lib/supabase/env.ts` | nuovo | export delle variabili d'ambiente con fail-fast |
| `temp/src/lib/supabase/client.ts` | nuovo | client browser singleton |
| `temp/src/lib/supabase/redirect.ts` | nuovo | sanitizzatore per gli open redirect |
| `temp/src/lib/rooms.ts` | copiare da `webapp/` | validazione condivisa del nome stanza |
| `temp/src/hooks.server.ts` | nuovo | client server per richiesta, `safeGetSession`, passthrough degli header |
| `temp/src/app.d.ts` | modificare | tipi `App.Locals` / `App.PageData` |
| `temp/src/routes/+layout.server.ts` | nuovo | sessione/utente per ogni pagina |
| `temp/src/routes/+layout.ts` | nuovo | `depends('supabase:auth')` |
| `temp/src/routes/+layout.svelte` | modificare | listener di autenticazione + nav |
| `temp/src/routes/login/+page.server.ts` | nuovo | action di login |
| `temp/src/routes/login/+page.svelte` | nuovo | form di login |
| `temp/src/routes/register/+page.server.ts` + `.svelte` | nuovi | registrazione + stato "check your inbox" |
| `temp/src/routes/logout/+server.ts` | nuovo | sign-out via POST |
| `temp/src/routes/auth/confirm/+server.ts` | nuovo | `verifyOtp` per i link email |
| `temp/src/routes/auth/error/+page.svelte` | nuovo | pagina per link fallito |
| `temp/src/routes/(private)/+layout.server.ts` | nuovo | guard del gruppo di route |
| `temp/src/routes/(private)/account/+page.svelte` | nuovo | esempio di pagina protetta |
| `temp/src/routes/stanza/[nome]/+page.server.ts` | nuovo | guard auth + nome stanza, `displayName` |
| `temp/src/routes/stanza/[nome]/+page.svelte` | modificare | pre-join, legge `data.displayName` |
| `temp/src/routes/api/token/+server.ts` | nuovo/modificare | ricava l'identità da `locals.user` |
| `temp/src/lib/supabase/redirect.spec.ts` | nuovo | test unitario |
| `temp/e2e/auth.spec.ts` (o `*.e2e.ts` accanto alla route) | nuovo | test di login e guard |

---

## 4. Ordine di lavoro consigliato (ogni passo termina in uno stato verificabile)

1. Step 1 + Step 2 — dipendenze, variabili d'ambiente, client browser. L'app parte ancora.
2. Step 3 + Step 4 — hooks e tipi. `safeGetSession()` restituisce `null`; `npm run check` è pulito.
3. Step 5 — collegamento del layout. La nav mostra lo stato da non autenticato.
4. Step 6 + Step 8 — form di login e logout. Sai accedere e uscire. **Prima milestone utilizzabile.**
5. Step 7 + Step 9 — registrazione e conferma email. Il giro completo di iscrizione funziona.
6. Step 10 — `safeRedirect` + gruppo `(private)` + guard su `/stanza/[nome]`, più i test unitari.
7. Step 11 — l'endpoint del token LiveKit, ora che l'identità è affidabile.
8. Step 12 — copertura Playwright, poi `check` / `lint` / `test`.

Gli Step 6 e 9 si possono invertire se preferisci avere prima le registrazioni reali e poi la pagina di
login rifinita.

---

## 5. Errori tipici da evitare (riepilogo)

- **`getSession()` non è autorizzazione.** Chiunque può falsificare un cookie; solo `getUser()`/`getClaims()` validano.
- **Non istanziare mai il client server a livello di modulo** — deve essere creato per ogni richiesta.
- **Non chiamare `redirect()`/`fail()` dentro un `try` il cui `catch` li inghiotte** (usa `isRedirect`).
- **Non creare un secondo client browser** in un altro componente.
- **Non basare il controllo solo su `session.user` lato client** e dare per scontato che i dati dietro siano protetti.
- **Le Redirect URLs devono essere in allowlist** nella dashboard, altrimenti i link di conferma ricadono sulla Site URL.
- **L'API cookie di `@supabase/ssr` è cambiata** (ora `getAll`/`setAll`); se un tutorial passa `cookieOptions`, è vecchio.
- **Imposta cookie `secure` in produzione** — i default di Supabase vanno bene, ma se copi le opzioni dei cookie a mano non perdere `secure`/`sameSite`.
- **Fai il sign-out lato server**, così il cookie viene davvero cancellato nella risposta.
- **`$env/static/private`** (`LIVEKIT_API_SECRET`) si può importare solo da file server — mai da una `+page.svelte` o da un modulo `$lib` importato da un componente.
- **Non mettere il secret di LiveKit dietro una variabile `PUBLIC_`** mentre fai debug; è l'errore che fa trapelare le credenziali di produzione a ogni visitatore.

---

## 6. Estensioni opzionali (da valutare in seguito)

- **Reset password**: `resetPasswordForEmail` + un ramo `/auth/confirm?type=recovery` che porta l'utente a una pagina "imposta nuova password" che chiama `updateUser({ password })`.
- **OAuth (Google/GitHub)**: `/auth/callback/+server.ts` che esegue
  `supabase.auth.exchangeCodeForSession(url.searchParams.get('code'))`, e un pulsante
  `signInWithOAuth({ provider, options: { redirectTo: `${origin}/auth/callback` } })`.
- **Profilo / nome visualizzato**: una tabella `profiles` con chiave `auth.users.id`, scritta da un form in
  `(private)/account`; a quel punto l'endpoint del token legge il nome visualizzato da lì invece che da
  `user_metadata`.
- **Row Level Security**: quando inizierai a salvare dati applicativi (stanze, partecipanti), attiva la RLS
  su ogni tabella e scrivi le policy rispetto a `auth.uid()`. L'autenticazione senza RLS è solo metà della storia.
- **Azioni di amministrazione solo lato server**: un secondo client con la chiave `service_role`, creato
  *solo* dentro file in `$lib/server/` (SvelteKit blocca gli import da `$lib/server` nel codice client).
- **Rate limiting / captcha** su `/login` e `/register` prima di aprire al pubblico.

---

## 7. Fuori ambito, volutamente

- **La logica della stanza LiveKit** (connessione, tile, controlli, riconnessione): è coperta dalle Fasi 2–4
  di `piano.md`, non qui. Questo documento sostituisce soltanto il bullet "Autenticazione" della Fase 1 con
  qualcosa di operativo.
- **Schema del database e policy RLS**: non ci sono ancora dati applicativi.
- **Magic link / OTP / autenticazione via telefono**: viene descritto solo il flusso di conferma via link email.
- **Stile Tailwind delle pagine di autenticazione**: gli snippet sono volutamente senza stile, per non
  entrare in conflitto con il tuo `layout.css` / setup di `@tailwindcss/forms`.
- **Internazionalizzazione**: i messaggi di errore di autenticazione arrivano da Supabase in inglese;
  mapparli su stringhe italiane è un passaggio separato.

---

## 8. Domande aperte

1. **Piattaforma di deploy** — in `package.json` c'è `adapter-auto`. Su Vercel/Netlify la gestione dei cookie
   descritta sopra basta; su un server Node potresti volere `adapter-node` e ricontrollare i cookie `secure`
   dietro un proxy. Qual è la piattaforma?
2. **Registrazione aperta a tutti o solo su invito?** Se fosse solo su invito, `/register` non dovrebbe essere
   una route pubblica e ti servirebbe una tabella di allowlist invece del semplice `signUp`.
3. **Dove finiscono le pagine `(private)`?** Va bene il nome `/account`, o tutto il privato dovrebbe vivere
   solo sotto `/stanza/*`?
4. **Nome visualizzato in fase di registrazione?** Se lo raccogli, va in `options.data` di `signUp` (→
   `user_metadata`) oppure in una riga della tabella `profiles`, e l'endpoint del token dovrebbe usarlo (Step 11).
5. **Vuoi che l'attuale `temp/src/routes/+layout.svelte` mantenga la sua forma minimale** (senza nav), o
   preferisci che la nav faccia parte di questo lavoro? Al momento renderizza solo la favicon e la pagina.
