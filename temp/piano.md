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

## 0. Assumptions

| # | Assumption |
|---|---|
| A1 | You already have a Supabase project (org/ref) and can open the dashboard. |
| A2 | Auth method: **email + password**. Magic link / OTP / OAuth are covered later as optional blocks. |
| A3 | Email confirmation is **enabled** in the dashboard (Supabase default). |
| A4 | Only a subset of routes must be private (a "dashboard/account" area), not the whole site. |
| A5 | Session is stored in **cookies** via `@supabase/ssr` (not localStorage), so SSR can read it. |
| A6 | The app is deployed somewhere with HTTPS in production. |

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

