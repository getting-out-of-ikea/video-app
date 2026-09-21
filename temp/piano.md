# Piano: aggiungere l'autenticazione con Supabase a `temp/` — *Authentication with Supabase: implementation plan*

> **Scope.** Everything below targets the app in `temp/` (SvelteKit 2, Svelte 5 runes, Tailwind 4,
> `adapter-auto`, Vitest + Playwright already configured). The sibling app in `webapp/` already
> implements the `@supabase/ssr` server pattern (`webapp/src/hooks.server.ts`, `webapp/src/app.d.ts`);
> this plan deliberately **mirrors those conventions** so the two apps stay consistent. No file in
> `webapp/` is touched.
>
> **Style of this document.** It is a guide, not a patch. Snippets are short and meant to be typed by
> you and adapted. Every snippet is followed by the *why*.

---

## Contents

0. [Assumptions](#0-assumptions)
1. [Mental model](#1-mental-model-read-this-before-writing-code)
2. [Step-by-step](#2-step-by-step)
3. [File checklist](#3-file-checklist)
4. [Order of work](#4-suggested-order-of-work-each-step-ends-in-a-verifiable-state)
5. [Pitfalls cheat-sheet](#5-pitfalls-cheat-sheet)
6. [Optional extensions](#6-optional-extensions-pick-later)
7. [Intentionally out of scope](#7-intentionally-out-of-scope)
8. [Open questions](#8-open-questions-for-you)

---

## 0. Assumptions

| # | Assumption |
|---|---|
| A1 | You already have a Supabase project (org/ref) and can open the dashboard. |
| A2 | Auth method: **email + password**. Magic link / OTP / OAuth are covered later as optional blocks. |
| A3 | Email confirmation is **enabled** in the dashboard (Supabase default). |
| A4 | Only a subset of routes must be private: the `(private)` group and `/stanza/[nome]` — see `piano.md`, Fase 1. |
| A5 | Session is stored in **cookies** via `@supabase/ssr` (not localStorage), so SSR can read it. |
| A6 | The app is deployed somewhere with HTTPS in production. |
| A7 | There is no database schema yet; only `auth.users` and its metadata are used at this stage. |

---

## 1. Mental model (read this before writing code)

Three ideas carry the whole design:

1. **One client per context.**
   - In the **browser**: a single, lazily-created `createBrowserClient`, so the auth state and the
     refresh timer are not duplicated.
   - On the **server**: a *new* `createServerClient` **per request**, wired to that request's cookies.
     A module-level server client would leak one user's session into another user's request.

2. **The session lives in cookies, the truth lives on the auth server.**
   `auth.getSession()` just reads and decodes the cookie — it is attacker-controllable. Only
   `auth.getUser()` (or `getClaims()`) asks the Supabase Auth server to validate the JWT. So:
   **use `getSession()` for cheap UX reads, use `getUser()` for every authorization decision.**

3. **Server-side guard = security boundary; client-side checks = UX only.**
   Hiding a link is not protection. The protection is a `redirect(303, …)` inside a `load` function
   or in `hooks.server.ts`.

Request flow once implemented:

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

## 2. Step-by-step

### Step 1 — Dependencies and environment variables

~~~bash
npm install @supabase/supabase-js @supabase/ssr
~~~

Both are **runtime** dependencies, not devDependencies (they end up in the browser bundle).

Create `temp/.env.local` (verify it is git-ignored; `.env.example` stays committed):

~~~ini
PUBLIC_SUPABASE_URL=https://<your-ref>.supabase.co
PUBLIC_SUPABASE_PUBLISHABLE_KEY=<your-publishable-key>
~~~

*Why:* the `PUBLIC_` prefix makes these readable from both server and client code via
`$env/static/public`. They are safe to ship to the browser **only** because they are the publishable
key. A `service_role` key must never appear in a `PUBLIC_` variable and must never be imported into
client code.

Optional but recommended — a fail-fast module so a missing variable is a loud error, not a mystery
`fetch` failure at runtime:

~~~ts
// src/lib/supabase/env.ts
import { PUBLIC_SUPABASE_URL, PUBLIC_SUPABASE_PUBLISHABLE_KEY } from '$env/static/public';

if (!PUBLIC_SUPABASE_URL || !PUBLIC_SUPABASE_PUBLISHABLE_KEY) {
	throw new Error('Missing PUBLIC_SUPABASE_URL / PUBLIC_SUPABASE_PUBLISHABLE_KEY');
}

export const SUPABASE_URL = PUBLIC_SUPABASE_URL;
export const SUPABASE_KEY = PUBLIC_SUPABASE_PUBLISHABLE_KEY;
~~~

> `$env/static/public` inlines the values at build time. If you want one build deployed to several
> environments, use `$env/dynamic/public` (which is *only* allowed on the server unless you pass it
> down through `load`). For now, static is simpler.

**Verify:** `npm run dev` still boots.

---

### Step 2 — Browser client (`src/lib/supabase/client.ts`)

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

*Why:* the `??=` singleton matters. Creating a second browser client spawns a second auth listener and
a second token-refresh timer, which produces random logouts and duplicate `onAuthStateChange` events.

---

### Step 3 — Server client + session helper (`src/hooks.server.ts`)

This is the keystone file.

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

*Why each piece:*
- `getAll`/`setAll` is the current `@supabase/ssr` cookie API (older tutorials use `get`/`set`/`remove`
  and also a `cookieOptions` argument — if you copy from an old post, that is the tell that it is outdated).
- `path: '/'` guarantees a refresh written from a deep route is visible everywhere.
- The `safeGetSession` name is the one already used in `webapp/`; keeping it means the same mental
  model and the same `app.d.ts` shape in both apps.
- The `filterSerializedResponseHeaders` block is needed for `count: 'exact'` queries and the
  Supabase API version header.
- If your Supabase helper ever writes a cookie during a *server component* render, it throws
  "Cookies can only be modified in a server action or endpoint"; the `setAll` body can be wrapped in
  `try/catch` to swallow that case, because the session will be persisted on the next real request.

**Verify:** add a temporary `console.log(await event.locals.safeGetSession())` — you should see
`{ session: null, user: null }` on a fresh browser.

---

### Step 4 — Type the locals (`src/app.d.ts`)

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

*Why:* `svelte-check` and your editor will now autocomplete `locals.user` and flag typos. The shape
matches `webapp/src/app.d.ts`.

**Verify:** `npm run check`.

---

### Step 5 — Expose the session to every page

**5a. Server layout data — `src/routes/+layout.server.ts`**

~~~ts
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals }) => {
	const { session, user } = await locals.safeGetSession();
	locals.session = session;
	locals.user = user;

	return { session, user };
};
~~~

*Why:* one place runs `safeGetSession` per navigation, every page and layout downstream can read
`data.user`, and `locals.user` is populated for guards.

**5b. Client-side re-validation — `src/routes/+layout.ts`**

~~~ts
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async ({ data, depends }) => {
	depends('supabase:auth');
	return { session: data.session, user: data.user };
};
~~~

*Why:* `depends('supabase:auth')` lets us re-run all `load` functions when the auth state changes
without a full page reload.

**5c. Layout + navigation — `src/routes/+layout.svelte`**

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

*Why:* `onAuthStateChange` is the only reliable way to notice a token refresh or a sign-out that
happened in another tab. Returning the unsubscribe function from `$effect` prevents listener leaks.
Never call Supabase methods *inside* the callback — set state and let `invalidate` re-run the loads.

> If you keep the existing `temp/src/routes/+layout.svelte` untouched and drop the `supabaseBrowserClient`
> import, everything in Steps 6–10 still works; you only lose the "another tab logged out" refresh.

**Verify:** browse around; with no session the nav shows "Log in".

---

### Step 6 — Login form backed by a server action

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

*Why a server action instead of `supabase.auth.signInWithPassword()` in the browser?*
- It works before/without JavaScript (progressive enhancement).
- The cookie is written by the server helper in `setAll`, so there is no "flash of unauthenticated
  content" while the client library boots.
- Validation errors come back as `form.message`, which is trivial to render.

*Two traps:*
1. `redirect()` and `fail()` **throw**. Never call them inside a `try/catch` that swallows errors —
   or if you must, re-throw with `isRedirect(e)` / `isHttpError(e)`.
2. `redirectTo` comes from the query string, so it must be validated (otherwise it is an open
   redirect). The tiny check above, or the reusable helper in Step 10a.

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

*Why:* `use:enhance` upgrades the plain HTML form to a fetch-based submit with loading state, while
the form still works with JS disabled. `autocomplete` attributes let browser password managers fill
and save credentials correctly. `role="alert"` announces errors to screen readers.

---

### Step 7 — Registration

Registration is the same shape as login, with `auth.signUp`:

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

*Why this differs from login:*
- **Do not redirect to a protected route here.** With email confirmation on, `data.session` is `null`
  and `data.user` exists but is unconfirmed; a redirect would immediately bounce the user back with
  `redirectTo`.
- **The same page must render three states**: untouched, error, and "check your inbox". A single
  `form.message` plus a conditional block is enough.
- A minimal password-length check server-side is worth having even though Supabase also enforces a
  minimum — it gives a readable message in your own UI language.

The matching `+page.svelte` only needs the extra fields and the conditional:

~~~svelte
{#if form?.message}
	<p role="alert" aria-live="polite">{form.message}</p>
{/if}
~~~

*Why `auth.signUp` and not the admin API:* the admin `createUser` endpoint requires the `service_role`
key, which must never be reachable from a public route. Self-service sign-up is the only option here.

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

*Why POST and not GET:* a GET logout can be triggered by any `<img src>` on any site (CSRF-ish
annoyance). The nav form in Step 5c already posts.

---

### Step 9 — Email confirmation (dashboard + `/auth/confirm`)

**9a. Supabase dashboard**
- *Auth → Providers → Email*: keep "Confirm email" on.
- *Auth → URL Configuration*: **Site URL** = your dev URL (`http://localhost:5173`), and add
  **Redirect URLs** for `http://localhost:5173/**` and your production origin `https://…/**`.
  Anything not allowlisted silently falls back to the Site URL.
- *Auth → Email Templates → Confirm sign up*: point the link at your own route:

~~~html
<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email&next=/account">
  Confirm your email
</a>
~~~

*Why `token_hash` and not the default `{{ .ConfirmationURL }}`:* the default link goes to Supabase,
which then bounces back with `?code=`; if the user opens it on a different device than the one that
signed up, the PKCE code verifier is missing and the exchange fails. The `token_hash` flow works on
any device.

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

*Note:* `verifyOtp` also supports `type: 'recovery'` (password reset) and `'magiclink'`. Add a
`/auth/error` page with a friendly message and a "resend" link:

~~~svelte
<!-- src/routes/auth/error/+page.svelte -->
<h1>Link non valido o scaduto</h1>
<p>Richiedi di nuovo l'email di conferma oppure <a href="/login">accedi</a>.</p>
~~~

**Verify:** sign up with a real inbox, click the link, land on `/account` logged in.

---

### Step 10 — Protecting routes

**10a. The shared open-redirect guard — `src/lib/supabase/redirect.ts`**

~~~ts
export function safeRedirect(target: string | null | undefined, fallback = '/'): string {
	if (!target) return fallback;
	if (!target.startsWith('/') || target.startsWith('//') || target.startsWith('/\\')) return fallback;
	return target;
}
~~~

*Why:* `redirectTo` / `next` arrive from the query string or a hidden field, so any of them can be
`//evil.com`. Centralizing the check means the rule cannot drift between the login action, the confirm
endpoint and the guards. It is also tiny and unit-testable with the Vitest setup you already have.

**10b. Option A — guard a route group (recommended for A4).**

Move the private pages into a group and guard once:

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

`src/routes/(private)/account/+page.svelte` then simply renders `data.user.email`; the parent layout
would not have rendered if there were no user. Group folders with parentheses do not appear in URLs.

**10c. Guarding the video room — `src/routes/stanza/[nome]/+page.server.ts`**

Fase 1 of `piano.md` requires `/stanza/[nome]` to be reachable only by authenticated users, and the
room name to be valid. That guard is *not* the token endpoint's job alone: a user who can load the
pre-join page with an invalid name gets a confusing failure later.

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

*Why 404 and not 400:* a malformed room name is indistinguishable from a non-existent one as far as
the visitor is concerned, and 404 keeps the information surface small. `src/lib/rooms.ts` already
exists in `webapp/`; copy it into `temp/src/lib/` rather than inlining the regex, so the token endpoint
and the page validate with the *same* rule.

**10d. Option B — centralized check in `hooks.server.ts`** (only if almost everything becomes private):

~~~ts
const PUBLIC_PATHS = ['/login', '/register', '/auth'];
const isPublic = (p: string) => PUBLIC_PATHS.some((x) => p === x || p.startsWith(x + '/'));

// inside handle(), after locals.safeGetSession is defined:
const { user } = await event.locals.safeGetSession();
if (!user && !isPublic(event.url.pathname) && !event.url.pathname.startsWith('/api/')) {
	redirect(303, `/login?redirectTo=${encodeURIComponent(event.url.pathname + event.url.search)}`);
}
~~~

*Why A is usually better:* the guard lives next to the pages it protects, and it does not need a
hand-maintained allowlist that can drift. Option B is also a sledgehammer for API routes — remember
that `redirect(303, '/login')` is the wrong answer for a JSON endpoint; there you want
`error(401, 'not authenticated')`.

---

### Step 11 — Teach the LiveKit token endpoint about the user

Your `temp/.env.example` already carries `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`, so
when `src/routes/api/token/+server.ts` is written (Fase 2 of `piano.md`), it must derive the identity
from the session:

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

*Why:* the LiveKit access token grants publish/subscribe rights. If `identity` came from the request
body, any logged-in user could impersonate another participant. `room` *does* legitimately come from
the client (the user picked it), but it must be validated and, once you have a database, checked
against a membership table. The `webapp/src/routes/api/token/+server.ts` endpoint is the reference
pattern. Keep the TTL short (minutes, not hours) and let the client re-request.

---

### Step 12 — Tests and checks

1. **Unit (Vitest, already configured in `temp/`)** — `src/lib/supabase/redirect.spec.ts`:

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

   Same treatment for `isValidRoomName` once `src/lib/rooms.ts` is copied over.
2. **E2E (Playwright, already configured)** — two cheap tests with a dedicated test user:
   - unauthenticated `page.goto('/account')` ends on `/login?redirectTo=%2Faccount`;
   - fill the login form, submit, expect the account heading and a session cookie.
   Keep the credentials in `.env.test`/CI secrets, and use a seeded user, not your personal account.
   Email confirmation cannot be scripted in a normal E2E run — seed the user as "already confirmed"
   through the Supabase dashboard or an admin script.
3. `npm run check && npm run lint && npm run test`.

---

## 3. File checklist

| File | Action | Purpose |
|---|---|---|
| `temp/package.json` | edit | add `@supabase/supabase-js`, `@supabase/ssr` |
| `temp/.env.local` | new (ignored) | local Supabase URL + publishable key |
| `temp/.env.example` | exists | already lists both `PUBLIC_SUPABASE_*` vars |
| `temp/src/lib/supabase/env.ts` | new | fail-fast env exports |
| `temp/src/lib/supabase/client.ts` | new | singleton browser client |
| `temp/src/lib/supabase/redirect.ts` | new | open-redirect sanitizer |
| `temp/src/lib/rooms.ts` | copy from `webapp/` | shared room-name validation |
| `temp/src/hooks.server.ts` | new | per-request server client, `safeGetSession`, header passthrough |
| `temp/src/app.d.ts` | edit | `App.Locals` / `App.PageData` types |
| `temp/src/routes/+layout.server.ts` | new | session/user for every page |
| `temp/src/routes/+layout.ts` | new | `depends('supabase:auth')` |
| `temp/src/routes/+layout.svelte` | edit | auth listener + nav |
| `temp/src/routes/login/+page.server.ts` | new | login action |
| `temp/src/routes/login/+page.svelte` | new | login form |
| `temp/src/routes/register/+page.server.ts` + `.svelte` | new | sign up + "check your inbox" state |
| `temp/src/routes/logout/+server.ts` | new | POST sign-out |
| `temp/src/routes/auth/confirm/+server.ts` | new | `verifyOtp` for email links |
| `temp/src/routes/auth/error/+page.svelte` | new | failed-link page |
| `temp/src/routes/(private)/+layout.server.ts` | new | route-group guard |
| `temp/src/routes/(private)/account/+page.svelte` | new | protected page example |
| `temp/src/routes/stanza/[nome]/+page.server.ts` | new | auth + room-name guard, `displayName` |
| `temp/src/routes/stanza/[nome]/+page.svelte` | edit | pre-join, reads `data.displayName` |
| `temp/src/routes/api/token/+server.ts` | new/edit | derive identity from `locals.user` |
| `temp/src/lib/supabase/redirect.spec.ts` | new | unit test |
| `temp/e2e/auth.spec.ts` (or `*.e2e.ts` beside the route) | new | login + guard tests |

---

## 4. Suggested order of work (each step ends in a verifiable state)

1. Step 1 + Step 2 — deps, env, browser client. App still boots.
2. Step 3 + Step 4 — hooks + types. `safeGetSession()` returns `null`s; `npm run check` is clean.
3. Step 5 — layout wiring. Nav renders the logged-out state.
4. Step 6 + Step 8 — login form and logout. You can log in and out. **First usable milestone.**
5. Step 7 + Step 9 — registration and email confirmation. Sign-up round trip works end to end.
6. Step 10 — `safeRedirect` + `(private)` group + `/stanza/[nome]` guard, plus the unit tests.
7. Step 11 — the LiveKit token endpoint, now that identity is trustworthy.
8. Step 12 — Playwright coverage, then `check` / `lint` / `test`.

Steps 6 and 9 can be swapped if you would rather have real sign-ups before a polished login page.

---

## 5. Pitfalls cheat-sheet

- **`getSession()` ≠ authorization.** Anyone can forge a cookie; only `getUser()`/`getClaims()` validate.
- **Never instantiate the server client at module scope** — it must be per-request.
- **Never call `redirect()`/`fail()` inside a `try` whose `catch` swallows them** (use `isRedirect`).
- **Don't create a second browser client** in another component.
- **Don't gate on `session.user` client-side only** and assume the data behind it is protected.
- **Redirect URLs must be allowlisted** in the dashboard, otherwise confirmation links fall back to Site URL.
- **`@supabase/ssr` cookie API changed** (`getAll`/`setAll` now); if a tutorial passes `cookieOptions`, it is old.
- **Set `secure` cookies in production** — the defaults from Supabase are fine, but if you copy cookie
  options manually, don't drop `secure`/`sameSite`.
- **Sign out server-side** so the cookie is actually cleared on the response.
- **`$env/static/private`** (`LIVEKIT_API_SECRET`) can only be imported from server files — never from
  a `+page.svelte` or a `$lib` module that a component imports.
- **Don't put the LiveKit secret behind a `PUBLIC_` variable** while debugging; that is the one mistake
  that leaks production credentials to every visitor.

---

## 6. Optional extensions (pick later)

- **Password reset**: `resetPasswordForEmail` + a `/auth/confirm?type=recovery` branch that sends the
  user to a "set new password" page calling `updateUser({ password })`.
- **OAuth (Google/GitHub)**: `/auth/callback/+server.ts` doing
  `supabase.auth.exchangeCodeForSession(url.searchParams.get('code'))`, and a
  `signInWithOAuth({ provider, options: { redirectTo: `${origin}/auth/callback` } })` button.
- **Profile / display name**: a `profiles` table keyed by `auth.users.id`, written from a
  `(private)/account` form; the token endpoint then reads the display name from there instead of
  `user_metadata`.
- **Row Level Security**: once you store app data (rooms, participants), enable RLS on each table and
  write policies against `auth.uid()`. Authentication without RLS is only half a story.
- **Server-only admin actions**: a second client using the `service_role` key, created *only* inside
  `$lib/server/` files (SvelteKit blocks `$lib/server` imports in client code).
- **Rate limiting / captcha** on `/login` and `/register` before going public.

---

## 7. Intentionally out of scope

- **LiveKit room logic** (connect, tiles, controls, reconnect): covered by Fase 2–4 of `piano.md`, not here.
  This document only replaces the "Autenticazione" bullet of Fase 1 with something actionable.
- **Database schema and RLS policies**: there is no app data yet.
- **Magic link / OTP / phone auth**: only the email-link confirmation flow is described.
- **Tailwind styling of the auth pages**: the snippets are unstyled on purpose, so they do not fight
  your `layout.css` / `@tailwindcss/forms` setup.
- **Internationalization**: the auth error messages come from Supabase in English; mapping them to
  Italian strings is a separate pass.

---

## 8. Open questions for you

1. **Deployment target** — `adapter-auto` is in `package.json`. On Vercel/Netlify the cookie handling
   above is enough; on a Node server you may want `adapter-node` and to double-check `secure` cookies
   behind a proxy. Which platform is it?
2. **Registration open to everyone or invite-only?** If invite-only, `/register` should not be a public
   route, and you will want an allowlist table rather than plain `signUp`.
3. **Where do `(private)` pages end up?** Is `/account` the right name, or should everything private
   live under `/stanza/*` only?
4. **Display name at sign-up?** If you collect one, it belongs in `options.data` on `signUp` (→
   `user_metadata`) or in a `profiles` row, and the token endpoint should use it (Step 11).
5. **Do you also want the current `temp/src/routes/+layout.svelte` to keep its minimal shape** (no nav),
   or should I plan the nav as part of this work? It currently renders only the favicon and the page.
