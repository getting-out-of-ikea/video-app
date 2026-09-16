
1. Creating the SvelteKit app

The current official CLI is sv (the old npm create svelte@latest you'll see in older tutorials is deprecated):

npx sv create videoconf-app

The interactive prompts will ask for:

 • Template: minimal (the demo one is just sample code)
 • TypeScript: Yes
 • Add-ons (select with spacebar): prettier, eslint, tailwindcss (optional per your plan), vitest, playwright
 • Package manager: npm

Then:

cd videoconf-app
npm install
git init# if the CLI didn't already do it
npm run dev -- --open


Notes:

 • The generated .gitignore already excludes .env, so your keys are safe — verify it anyway.
 • The template ships with adapter-auto, which auto-detects Vercel at deploy time, so Phase 6 needs no extra setup (you can still add adapter-vercel explicitly if you prefer).


2. Clerk + Svelte

Clerk has no official Svelte SDK — that's why Svelte is missing from the list. But the framework picker in the dashboard only customizes the quickstart guide it shows you; the API keys are framework-agnostic. Pick anything (or skip it) and grab your
keys from the "API Keys" page.

You then have three practical options:

 1 Community SDK — svelte-clerk (successor of the older clerk-sveltekit, compatible with Svelte 5). It's listed on Clerk's community SDKs page and gives you prebuilt components (<SignIn>, <UserButton>), route protection, and server-side session
   handling via hooks.server.ts — everything your Phase 1 checklist requires. Check its README for the current install/setup steps.
 2 Framework-agnostic packages: @clerk/clerk-js on the client + @clerk/backend to verify sessions server-side. More manual work, but fully supported by Clerk.
 3 Switch to Supabase Auth — your plan already lists it as an alternative, and it has an official SvelteKit integration guide via @supabase/ssr. Worth considering only if you're uncomfortable relying on a community SDK.

Whichever you choose, the env variables in .env will be:


PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...

# later, for Phase 2:
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
PUBLIC_LIVEKIT_URL=wss://your-project.livekit.cloud


Note the PUBLIC_ prefix: SvelteKit only exposes variables with that prefix to the browser — the secret keys stay server-only, which matches your "never expose secrets in the frontend" requirement.
