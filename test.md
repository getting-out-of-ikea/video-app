# aider
voglio implementare dei test per questa webapp. Scrivi un file test.md in cui indichi in maniera discorsiva cosa bisogna fare per ogni categoria di test, in modo che successivamente io possa chiederti di implementare una sezione per volta.

# Piano dei test

Questo documento descrive, categoria per categoria, cosa va fatto per testare la webapp.
L'obiettivo è procedere **una sezione alla volta**: quando vuoi che una sezione venga
implementata davvero (file di test, helper, modifiche di configurazione), chiedilo
indicando il numero della sezione.

Stato attuale del progetto:

- **Vitest** è già configurato in `vite.config.ts` con due "projects":
  - `client`: gira nel browser (Playwright/Chromium), raccoglie `src/**/*.svelte.{test,spec}.{js,ts}`
    ed esclude `src/lib/server/**`. Serve per i test dei **componenti Svelte**.
  - `server`: gira in ambiente Node, raccoglie `src/**/*.{test,spec}.{js,ts}` ed esclude
    `src/**/*.svelte.{test,spec}.{js,ts}`. Serve per i test di **funzioni pure e logica server**.
- **Playwright** è configurato in `playwright.config.ts` (`testMatch: '**/*.e2e.{ts,js}'`, avvia
  `npm run build && npm run preview` sulla porta 4173). Serve per i test **end-to-end**.
  Come spiegato in §4, la webapp è già deployata su Vercel in un ambiente di sviluppo, quindi
  l'intenzione è **puntare Playwright a quell'ambiente** invece di servire una build in locale.
- Esistono già esempi "usa e getta" (`src/lib/vitest-examples/greet.spec.ts`,
  `Welcome.svelte.spec.ts`, `src/routes/demo/playwright/page.svelte.e2e.ts`) che si possono
  tenere come riferimento o rimuovere.

Convenzioni che adotteremo:

- Test unitari/servizi (Node): `*.spec.ts` accanto al file, oppure in una cartella `__tests__`.
- Test di componenti (browser): `*.svelte.spec.ts`.
- Test end-to-end: `*.e2e.ts` sotto `src/routes/**` (come l'esempio) oppure in una cartella
  dedicata `e2e/` (in tal caso va aggiornato `playwright.config.ts`).
- Nomi dei test e delle `describe` in inglese (coerenti con il codice), helper riutilizzabili
  in `src/tests/` o `src/lib/testing/`.

---

## 0. Infrastruttura condivisa (da fare per prima)

Prima di scrivere i test veri e propri conviene creare un piccolo strato di utilità condivise,
altrimenti ogni file di test finirà per reinventare gli stessi mock. In questa sezione si
prepara il "terreno", senza testare ancora nulla di specifico:

- **Helper per il `RequestEvent` di SvelteKit.** I form action e gli endpoint (`+page.server.ts`,
  `+server.ts`, `hooks.server.ts`) ricevono un `RequestEvent`. Serve una factory
  `createMockEvent({ ... })` che costruisca un oggetto realistico con:
  - `request` (con un body `FormData` o JSON, a seconda del caso),
  - `cookies` (con `get`/`set`/`getAll`/`delete`),
  - `locals` (con `supabase` e `safeGetSession` mockati),
  - `url`, `params`, `route`, `platform` ecc. minimi ma sufficienti.
  L'obiettivo è poter scrivere `await actions.login(createMockEvent({ form: { email, password } }))`.

- **Fake del client Supabase.** Un oggetto che implementa solo i metodi usati dal codice
  (`auth.signInWithPassword`, `auth.signUp`, `auth.signOut`, `auth.getSession`,
  `auth.getUser`, `auth.updateUser`, `auth.resetPasswordForEmail`,
  `auth.exchangeCodeForSession`, `auth.verifyOtp`). Ogni metodo è una `vi.fn()` così nei test
  possiamo controllare il valore di ritorno (`{ data, error }`) e verificare le chiamate.
  Utile anche per `safeGetSession`, che possiamo mockare per restituire
  `{ session, user }` o `{ session: null, user: null }`.

- **Fake di LiveKit.** I test dei componenti e degli endpoint devono poter girare senza un
  server LiveKit. Serve un fake di `Participant` (con `identity`, `name`, `getTrackPublication`,
  `on`, `off`) e un fake di `Track`/`TrackPublication` (con `attach`, `detach`, `isMuted`,
  `track`, `source`). Possiamo costruirlo a mano oppure usare `vi.mock('livekit-client', ...)`.

- **Scelta su come costruire la richiesta nei test browser.** I componenti pagine usano
  moduli `$app/*` (`$app/paths` → `resolve`, `$app/forms` → `enhance`, `$app/navigation` per
  `invalidate`). In ambiente Vitest questi moduli non sono disponibili: vanno aliasati/mockati
  (es. `vi.mock('$app/paths', () => ({ resolve: (p) => p }))`). Questa decisione va presa una
  volta qui e riutilizzata.

- **`npm run test` oggi** lancia `test:unit` (che a sua volta lancia `vitest` per entrambi i
  project) più `test:e2e`. Va verificato che i comandi funzionino e, se serve, aggiunti script
  dedicati (`test:unit:client`, `test:unit:server`, `test:e2e:ui`).

Il risultato di questa sezione è una cartella di helper (proposta: `src/tests/`) e nessun test
di prodotto.

---

## 1. Funzioni pure (unit, project "server")

È la categoria più semplice e va fatta subito dopo l'infrastruttura. Copre la logica isolata,
senza I/O né browser.

- **`src/lib/rooms.ts` → `isValidRoomName`.**
  È l'unica funzione pura "di dominio" chiaramente testabile. I casi da coprire:
  - nomi validi: lettere minuscole, cifre, trattini (`"stanza-1"`, `"a"`, nome di 64 caratteri);
  - nomi non validi: stringa vuota, maiuscole (`"Stanza"`), underscore, spazi, punti,
    caratteri accentati/emoji, nomi più lunghi di 64 caratteri, solo trattini, `null`/`undefined`
    se mai li gestissimo.
  - Verifica del **boundary** della lunghezza: 64 valido, 65 non valido.
  Questi test sono in `src/lib/rooms.spec.ts` e girano nel project `server` (Node).

- **(Opzionale) funzioni di utilità future.** Se in futuro introduciamo altre funzioni pure
  (parsing nome stanza da URL, formattazione, ecc.), la logica resta qui.

Non ha senso, in questa categoria, toccare Supabase o LiveKit.

---

## 2. Componenti Svelte (component/browser, project "client")

Qui testiamo il rendering e il comportamento dei componenti Svelte in un browser vero
(Chromium headless via Playwright), usando `vitest-browser-svelte` e `page` di `vitest/browser`.
I test finiscono in `*.svelte.spec.ts`.

Il candidato principale è **`src/lib/ParticipantTile.svelte`**, perché è il componente con più
logica (gestione track camera/microfono, avatar di fallback, stato "muto", evidenziazione di
chi parla). Cosa coprire:

- **Fake `Participant`** (vedi §0) senza track: il componente deve mostrare l'iniziale del
  nome (o dell'identità) e l'etichetta "(tu)" se `isLocal` è `true`.
- **Con track camera attivo**: il `<video>` diventa visibile e viene chiamato `track.attach(el)`;
  quando il track viene rimosso/mutato, `detach` viene chiamato e si torna all'avatar.
- **Mic muto**: appare il badge "Muto" quando `micMuted` è vero e scompare quando è falso.
- **Mic locale**: per `isLocal === true` il nodo `<audio>` non deve essere renderizzato (evita
  il feedback). Verificare che per un participant remoto invece `audioEl` esista e che il track
  audio venga attachato.
- **Stato "speaking"**: la classe `ring-green-500` è applicata solo quando `speaking` è `true`.
- **Aggiornamenti da eventi LiveKit**: se il fake participant emette
  `ParticipantEvent.TrackMuted` / `LocalTrackPublished` ecc., il componente deve ri-sincronizzare
  (`syncTracks`); possiamo spingere gli eventi dal fake e verificare l'effetto sul DOM.
- **Cleanup**: al destroy del componente, gli handler `off(...)` vengono chiamati (importante per
  evitare memory leak).

Altri possibili test di componente, tutti più "di facciata" e da fare solo se utile:

- **`src/lib/vitest-examples/Welcome.svelte`**: già esiste come esempio, si può tenere o
  eliminare.
- **Pagine con form** (`login/+page.svelte`, `password-reset/+page.svelte`,
  `account/+page.svelte`): testare che gli errori/messaggi `form?.error` e `form?.message`
  vengano mostrati, che i campi abbiano gli attributi giusti (`required`, `minlength`,
  `autocomplete`), e che cliccando i pulsanti parta la `formaction` corretta. Questi test
  richiedono il mock di `$app/forms` (`enhance`) e `$app/paths` (`resolve`) deciso in §0.
- **`src/routes/+layout.svelte`** header: mostra "Accedi" se `data.user` è nullo, mostra email +
  "Esci" se c'è un utente. Richiede il mock di `$app/navigation` (`invalidate`),
  `$app/paths`, `$env/static/public` e `@supabase/ssr` (per `createBrowserClient`).

Nota: questo project Vitest esclude `src/lib/server/**`, quindi qui non mettiamo nulla di
server-only.

---

## 3. Server-side: hooks, endpoint e form action (unit, project "server", con mock)

Questa è la sezione più ricca e va fatta con calma. Sono test in Node che importano
direttamente i moduli server di SvelteKit (`+page.server.ts`, `+server.ts`, `hooks.server.ts`)
e li invocano con un `RequestEvent` costruito da noi (§0), verificando ritorni, redirect ed
errori. **Non** serve un vero server HTTP: invochiamo le funzioni `load`/`actions`/`GET`/`POST`
come normali funzioni.

Cosa coprire, file per file:

- **`src/hooks.server.ts` — `authGuard` (e la `sequence`).**
  È la logica di sicurezza più importante dell'app. Casi:
  - utente non autenticato su `/stanza/...` → `redirect(303, '/login')`;
  - utente non autenticato su `/account` → `redirect(303, '/login')`;
  - utente non autenticato su `/` o `/login` → passa oltre;
  - utente autenticato su `/login` → `redirect(303, '/')`;
  - utente autenticato su `/stanza/...` o `/account` → passa oltre;
  - `event.locals.session`/`event.locals.user` vengono popolati correttamente sia con sessione
    valida sia senza;
  - `safeGetSession` che ritorna `user: null` con `session` presente (caso token scaduto) →
    trattato come non autenticato.
  Va anche testato che `supabase` (il primo `Handle`) costruisca il client e che `setAll` dei
  cookie usi `path: '/'`.

- **`src/routes/api/token/+server.ts` — `POST`.**
  Endpoint che emette i JWT di LiveKit. Casi:
  - **nessun utente** (`safeGetSession` → `user: null`) → `error(401, ...)`;
  - **camera/room name non valido** (`isValidRoomName` falso) → `error(400, ...)`;
  - **body malformato** (JSON non parsabile, `room` non stringa, `room` mancante) → `error(400)`;
  - **happy path**: ritorna `{ token }` con status 200;
  - **contenuto del token**: decodificando il JWT (o con `AccessToken.fromString`/verifica)
    controllare che `identity` sia `user.id`, `name` sia `user.email`, che il grant contenga
    `roomJoin: true` sulla stanza richiesta, `canPublish`/`canSubscribe` a `true`, e che il TTL
    sia ~`1h`. La firma possiamo verificarla con la `LIVEKIT_API_SECRET` di test. In alternativa,
    mockare `livekit-server-sdk` (`AccessToken` con `addGrant`/`toJwt` come `vi.fn()`).
    Questa seconda opzione è più robusta e veloce, ma perde la verifica "reale" del contenuto:
    tipicamente si fa il test con mock e, se vuoi, uno più di integrazione.

- **`src/routes/logout/+server.ts` — `POST`.**
  - `supabase.auth.signOut` viene chiamato;
  - la risposta è `redirect(303, '/')` (per SvelteKit `redirect` lancia una `Redirect` con
    `status` e `location`: il test deve assertare sul `try/catch` della redirect).

- **`src/routes/login/+page.server.ts` — `actions.login` e `actions.signup`.**
  - `login`: mancano email o password → `fail(400, { error: 'Email e password sono obbligatorie.', email })`;
    Supabase ritorna `error` → `fail(400, { error: 'Credenziali non valide.', email })`;
    Supabase ok → `redirect(303, '/')`.
  - `signup`: campi mancanti → `fail(400, ...)`; errore Supabase → `fail(400, { error: error.message, email })`;
    `data.session` presente (conferma email disattivata) → `redirect(303, '/')`;
    `data.session` null → ritorna `{ message: 'Controlla la tua email ...' }`.
  - Verificare anche che `emailRedirectTo` passata a `signUp` includa `${url.origin}/auth/confirm`.

- **`src/routes/account/+page.server.ts` — `load` e `actions.updatePassword`.**
  - `load`: senza sessione → `redirect(303, '/login')`; con sessione → ritorna `{ user }`.
  - `updatePassword`: senza sessione → redirect; password < 6 → `fail(400, ...)`;
    due campi diversi → `fail(400, { error: 'Le password non coincidono.' })`;
    errore Supabase → `fail(400, { error })`; ok → `{ message: 'Password aggiornata con successo.' }`.

- **`src/routes/password-reset/+page.server.ts` — action di default.**
  - email mancante → `fail(400, { error: "L'email è obbligatoria." })`;
  - email presente → viene chiamato `resetPasswordForEmail` con `redirectTo` che punta a
    `${url.origin}/auth/confirm?next=/account`, e **ritorna sempre lo stesso messaggio**
    (non deve rivelare se l'email esiste).

- **`src/routes/auth/confirm/+server.ts` — `GET`.**
  - con `?code=...` valido → `exchangeCodeForSession` chiamato e redirect a `next` (o `/`);
  - con `token_hash` + `type` validi → `verifyOtp` chiamato e redirect a `next`;
  - errore in uno dei due rami → `redirect(303, '/login')`;
  - nessun parametro utile → `redirect(303, '/login')`;
  - `next` di default è `/` (verifica del fallback).

Per tutti questi test usiamo i fake Supabase (§0) e, dove serve, costruiamo `Request` con
`new FormData()` / `new Request(url, { body })`.

---

## 4. End-to-end (Playwright)

I test E2E verificano i flussi reali nel browser. **Decisione: i test girano contro la webapp
già deployata su Vercel nell'ambiente di sviluppo** (il progetto Vercel usato come "staging"),
non contro una build servita in locale.

Questo cambia diverse cose rispetto a un setup "classico":

- non serve più `webServer: { command: 'npm run build && npm run preview' }` in
  `playwright.config.ts`: il server esiste già;
- l'app è raggiunta via HTTPS (fornito da Vercel), quindi i permessi camera/microfono sono
  concedibili senza i workaround tipici di `localhost`;
- Supabase e LiveKit sono quelli **di sviluppo**: i test scrivono e leggono dati reali (utenti,
  sessioni), quindi la gestione dei dati di test diventa una preoccupazione concreta (§4.2);
- i test verificano **ciò che è già stato deployato**, non le modifiche non ancora committate:
  per testare una modifica bisogna prima pushare (o fare un deploy manuale), il che rende
  l'E2E un ciclo più lento del solito.

### 4.1 Configurazione del target

- Aggiungere una variabile d'ambiente (proposta: `E2E_BASE_URL`) con l'URL dell'ambiente di
  sviluppo e usarla come `baseURL`; se non è impostata, fallback su `localhost` per uno smoke
  test locale rapido.

  ```ts
  // playwright.config.ts
  import { defineConfig } from '@playwright/test';

  export default defineConfig({
      use: {
          baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:4173'
      },
      testMatch: '**/*.e2e.{ts,js}'
  });
  ```

- Due strategie per "quale URL":
  - **Alias stabile**: un branch dedicato (es. `develop` o `staging`) con alias Vercel fisso
    (es. `webapp-develop.vercel.app`). È l'URL da mettere in `E2E_BASE_URL` per i run manuali.
    Comodo, ma l'app può cambiare sotto i piedi se qualcuno pusha durante il run.
  - **Deployment specifico**: usare l'URL immutabile del singolo deploy per testare esattamente
    quel commit. Deterministico, ideale in CI (§5), scomodo per i run manuali.

### 4.2 Autenticazione e dati di test

L'ambiente Vercel di sviluppo usa lo stesso progetto Supabase di sviluppo: gli account creati
dai test restano lì. Opzioni, in ordine di preferenza:

- **Account di test pre-creati e fissi.** Creare a mano (una volta) uno o due utenti in Supabase
  dev e passarli via variabili (`E2E_USER_EMAIL`, `E2E_USER_PASSWORD`, salvate in `.env.test`,
  già previsto dal `.gitignore`). I test fanno login/logout ma non accumulano nuovi utenti.
- **Global setup con cleanup.** Uno script Playwright (`globalSetup`) che crea un utente via
  Supabase Admin API (service role key, **mai** esposta al client), lo usa nei test e lo elimina
  nel `globalTeardown`. Più isolato, ma richiede la service role key in CI e attenzione in caso
  di run concorrenti.
- **Signup "usa e getta" con email univoca** (`e2e+<timestamp>@...`): semplice, ma accumula
  utenti in dev nel tempo: va prevista una pulizia periodica.

Regole non negoziabili: **mai** puntare `E2E_BASE_URL` all'ambiente di produzione e **mai** usare
credenziali di produzione.

### 4.3 WebRTC e permessi

Anche contro un'app servita in HTTPS servono i device "finti" di Chromium, altrimenti i test non
hanno camera/microfono e i permessi restano da concedere:

```ts
// playwright.config.ts
use: {
    baseURL: process.env.E2E_BASE_URL,
    launchOptions: {
        args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']
    }
}
```

### 4.4 Flussi da coprire

- **Auth guard / redirect.**
  - visitando `/stanza/test-1` o `/account` da sloggati → si finisce su `/login`;
  - visitando `/login` da loggati → si finisce su `/`.
- **Registrazione + login + logout.**
  - signup con email test (eventualmente con conferma email disattivata nel progetto di test)
    → redirect a `/`;
  - l'header mostra l'email e il pulsante "Esci";
  - click su "Esci" → redirect a `/` e l'header torna a mostrare "Accedi";
  - login con credenziali errate → messaggio "Credenziali non valide.";
  - login corretto → `/`.
- **Ciclo "password dimenticata".**
  - submit di `/password-reset` → messaggio generico;
  - (opzionale, se abbiamo accesso alla casella di test / a un endpoint di mail) verifica che il
    link generato atterri su `/auth/confirm?next=/account`.
- **Stanza (`/stanza/[nome]`).**
  - nome valido `test-1` da utente loggato → si vede la schermata di pre-join con anteprima
    (grazie ai fake device);
  - nome non valido (es. `Test_1`) → 404;
  - click su "Entra nella stanza" con `/api/token` mockato → appare la card del "local
    participant" e i controlli in basso; toggle microfono/camera cambiano l'etichetta
    ("Microfono attivo" ↔ "Microfono muto"); "Abbandona" riporta alla pre-join;
  - se `/api/token` risponde 401 → messaggio "Sessione scaduta...".
- **Smoke test generale.** La home `/` risponde 200 e mostra "Welcome to SvelteKit" (o quello che
  sarà) e l'header è presente. È l'equivalente del test demo già esistente `page.svelte.e2e.ts`,
  che si può tenere, spostare o eliminare.

Nota sulla parte video: se l'ambiente di sviluppo ha un LiveKit funzionante, il flusso "Entra
nella stanza" può essere testato end-to-end con i device finti. Se invece preferiamo non
dipendere da un server LiveKit condiviso, si mocka `/api/token` con `page.route(...)` e ci si
limita a verificare l'ingresso nella stanza e i controlli UI (come sopra).

### 4.5 Precauzioni specifiche del target remoto

- **Flakiness**: latenza di rete, cold start delle function e stato condiviso possono rendere i
  test più instabili. Preferire attese esplicite (`expect(...).toBeVisible()`) a `waitForTimeout`,
  e usare `retries` (solo in CI) con parsimonia.
- **Parallelismo**: non lanciare più test E2E in parallelo sullo stesso ambiente con lo stesso
  utente: le sessioni si invalidano a vicenda (un "Esci" sloggia l'altro test). O usare utenti
  distinti per worker, o forzare `fullyParallel: false` / `workers: 1`.
- **App che cambia durante il run**: sull'alias stabile un push altrui può cambiare l'app a metà
  suite. In CI conviene puntare all'URL immutabile del deployment appena creato (§4.1).
- **Configurazione locale**: aggiungere `E2E_BASE_URL` (e le credenziali di test) a `.env.test`
  (già ignorato) e documentarle in `.env.example`, chiarendo che sono dati **di sviluppo**.

### 4.6 Alternativa ibrida (facoltativa)

Se l'E2E remoto dovesse rivelarsi lento o instabile, si può affiancare un secondo "project"
Playwright che gira in locale contro `npm run build && npm run preview` con `/api/token` mockato
via `page.route(...)`, per un feedback rapido prima del push. Il project remoto resta comunque
quello "di verità" per l'integrazione end-to-end.

---

## 5. Copertura, CI e manutenzione

Dopo che le sezioni precedenti esistono, questa sezione si occupa di renderle sostenibili:

- **Coverage.** Aggiungere/attivare `@vitest/coverage-v8` e `@vitest/coverage-istanbul` (o solo
  uno) con soglie minime ragionevoli sui file di logica (`src/lib/rooms.ts`,
  `src/hooks.server.ts`, `src/routes/**/+*.server.ts`). I file `.svelte` sono tipicamente esclusi
  dalla coverage istantanea; vanno valutati con attenzione.
- **Script npm.** Verificare/aggiungere:
  - `test:unit:client` → `vitest --project client`,
  - `test:unit:server` → `vitest --project server`,
  - `test:e2e:ui` → `playwright test --ui` (per debug locale),
  - `test:ci` → sequenza completa adatta alla pipeline.
- **CI.** Se si usa GitHub Actions (o simile), descrivere il workflow: `npm ci`,
  `npm run check` (svelte-check), `npm run lint`, `npm run test:unit`, poi `npm run test:e2e`
  eseguito **dopo** il deploy Vercel, puntando (`E2E_BASE_URL`) all'URL immutabile del deployment
  appena creato, con le credenziali di test passate come segreti (vedi §4.1 e §4.2).
- **Convenzioni di manutenzione.** Documentare qui la scelta fatta in §0 su come si mockano
  `$app/*`, Supabase e LiveKit, e in §4 su come si punta l'ambiente remoto e si gestiscono i dati
  di test, così chi aggiunge test in futuro riusa gli helper invece di ricrearli.

---

## Ordine di implementazione consigliato

1. §0 Infrastruttura e convenzioni (helper e mock condivisi).
2. §1 Funzioni pure (`isValidRoomName`).
3. §3 Server-side (`hooks.server.ts`, `/api/token`, `/logout`, action di login/account/
   password-reset/auth-confirm) — è la parte con più valore, ma va fatta dopo §0.
4. §2 Componenti Svelte (`ParticipantTile`, poi le pagine form/header).
5. §4 End-to-end (contro l'ambiente Vercel di sviluppo).
6. §5 Copertura, CI e manutenzione.

Quando vorrai procedere, dimmi ad esempio "implementa §0" oppure "implementa §0 e §1
insieme": mi occuperò solo delle parti richieste, senza toccare il resto.
