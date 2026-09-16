# Piano di lavoro — Webapp di videocomunicazione di gruppo

## Obiettivo
Realizzare una webapp per videoconferenze di gruppo utilizzando:
- **LiveKit Cloud** (piano gratuito) per audio/video in tempo reale
- **Supabase** (piano gratuito, ~10.000 utenti attivi/mese) per l'autenticazione
- **SvelteKit** come framework full-stack (frontend + endpoint API per i token LiveKit)

Alternative valutabili per l'autenticazione: Supabase Auth o Auth0 (entrambi con piano gratuito).

## Stack tecnologico
| Componente | Scelta |
|---|---|
| Framework | SvelteKit + TypeScript |
| Video/WebRTC | LiveKit Cloud + `livekit-client` + `livekit-server-sdk` |
| Autenticazione | Supabase |
| Stile | Tailwind CSS (opzionale) |
| Test | Vitest (unit) + Playwright (e2e) |
| Deploy | Vercel (piano gratuito) |

## Fase 0 — Setup account e progetto (~0,5 gg)
- [ ] Creare account LiveKit Cloud → nuovo progetto → recuperare API Key, API Secret e URL `wss://`
- [ ] Creare account Supabase → nuova applicazione → recuperare Publishable Key e Secret Key
- [ ] Inizializzare il progetto SvelteKit con TypeScript, ESLint, Prettier
- [ ] Creare `.env` con le chiavi (e aggiungerlo a `.gitignore`)
- [ ] Inizializzare il repository Git e CI di base

## Fase 1 — Autenticazione (~1 gg)
- [ ] Installare e configurare l'SDK Supabase per Svelte
- [ ] Pagine di login/registrazione
- [ ] Protezione delle route (es. `/stanza/[nome]` accessibile solo a utenti autenticati)
- [ ] Rendere la sessione disponibile lato server in `hooks.server.ts`

## Fase 2 — Backend: generazione token LiveKit (~1 gg)
- [ ] Installare `livekit-server-sdk`
- [ ] Endpoint `POST /api/token` che:
  - [ ] Verifica la sessione utente (401 se non autenticato)
  - [ ] Valida il nome della stanza richiesta
  - [ ] Genera un `AccessToken` JWT con identity utente, nome stanza e grant video, con scadenza breve
- [ ] Gestione errori e logging

## Fase 3 — Frontend: stanza video (~2-3 gg)
- [ ] Installare `livekit-client`
- [ ] Schermata pre-join: anteprima camera/microfono e selezione dispositivi
- [ ] Pagina stanza: connessione a LiveKit con il token dell'endpoint
- [ ] Griglia responsiva dei partecipanti (video + audio)
- [ ] Componenti: tile partecipante, indicatori "muted" e "speaking"
- [ ] Barra controlli: mute/unmute microfono, on/off camera, condivisione schermo, abbandona stanza
- [ ] Gestione riconnessione automatica e stati di errore

## Fase 4 — Funzionalità extra (opzionale, ~1-2 gg)
- [ ] Chat testuale in stanza via data channel LiveKit
- [ ] Reazioni / alzata di mano
- [ ] Registrazione delle sessioni (LiveKit Egress)

## Fase 5 — Test (~1 gg)
- [ ] Test unitari (Vitest) per l'endpoint `/api/token` e la logica di validazione
- [ ] Test e2e (Playwright): login, pre-join, ingresso in stanza
- [ ] Test manuale multi-browser e con connessione lenta

## Fase 6 — Deploy (~0,5 gg)
- [ ] Deploy su Vercel (adapter Vercel/auto)
- [ ] Configurare le variabili d'ambiente in produzione
- [ ] Verificare HTTPS (obbligatorio per `getUserMedia` e WebRTC)
- [ ] Smoke test in produzione con 2+ partecipanti

## Milestone
| # | Milestone | Durata stimata |
|---|---|---|
| M1 | Progetto inizializzato + autenticazione funzionante | 1,5 gg |
| M2 | Token LiveKit generati lato server | 1 gg |
| M3 | Videoconferenza di gruppo funzionante | 3 gg |
| M4 | Extra, test e deploy in produzione | 2-3 gg |

**Totale stimato: 7-9 giorni lavorativi**

## Note e rischi
- Verificare i limiti aggiornati dei piani gratuiti di LiveKit Cloud (minuti/banda) e Supabase (MAU) prima del rilascio
- Non esporre mai l'API Secret di LiveKit nel frontend: i token vanno generati solo lato server
- La condivisione schermo e l'audio richiedono browser moderni; prevedere messaggi di fallback
