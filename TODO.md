# TODO — Implementazione LiveKit

L'autenticazione (Fase 1 di `piano.md`) è completata. Seguono i passi per integrare LiveKit (Fasi 2 e 3).

## 1. Setup
- [ ] Installare le dipendenze: `npm install livekit-client livekit-server-sdk`
- [ ] Copiare `.env.example` in `.env` e compilare `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` con i valori del progetto LiveKit Cloud
- [ ] Verificare che `.env` sia in `.gitignore`

## 2. Backend — endpoint `POST /api/token`
- [ ] Creare `src/routes/api/token/+server.ts`
- [ ] Verificare la sessione con `locals.safeGetSession()`; rispondere `401` se non autenticato
- [ ] Validare il nome della stanza (es. solo lettere minuscole, numeri e `-`, lunghezza 1–64); rispondere `400` se invalido
- [ ] Generare un `AccessToken` (da `livekit-server-sdk`) con:
  - `identity` = `user.id` (Supabase)
  - `name` = `user.email` (mostrata nella stanza)
  - grant video: `roomJoin: true`, `room: <nome stanza>`, `canPublish`, `canSubscribe`
  - scadenza breve (es. `1h`)
- [ ] Restituire il token come JSON: `{ token }`
- [ ] Non esporre mai `LIVEKIT_API_SECRET` al client (importare solo da `$env/static/private`)

## 3. Frontend — pagina stanza `/stanza/[nome]`
- [ ] Creare `src/routes/stanza/[nome]/+page.svelte` (la route `/stanza` è già protetta in `hooks.server.ts`)
- [ ] Schermata pre-join: anteprima camera/microfono, selezione dispositivi, pulsante "Entra nella stanza"
- [ ] Al join: `fetch('/api/token', { method: 'POST', body })` con il nome stanza, poi connessione con `new Room()` e `room.connect(LIVEKIT_URL, token)`
- [ ] Pubblicare camera e microfono con `room.localParticipant.enableCameraAndMicrophone()`
- [ ] Griglia responsiva dei partecipanti: tile video/audio per ogni partecipante remoto, aggiornata sugli eventi `RoomEvent.ParticipantConnected/Disconnected` e `RoomEvent.TrackSubscribed/Unsubscribed`
- [ ] Indicatori "muted" e "speaking" (evento `RoomEvent.ActiveSpeakersChanged`)
- [ ] Barra controlli: mute/unmute microfono, on/off camera, condivisione schermo (`setScreenShareEnabled`), abbandona stanza (`room.disconnect()`)
- [ ] Gestione riconnessione automatica (`RoomEvent.Reconnecting/Reconnected`) e stati di errore

## 4. Test
- [ ] Test unitari (Vitest) per `/api/token`: 401 senza sessione, 400 nome stanza invalido, claims del token corretti
- [ ] Test e2e (Playwright): login → pre-join → ingresso in stanza
- [ ] Test manuale tra due utenti (vedi sotto)

## Come provare la videocomunicazione tra due utenti

1. Avviare il dev server: `npm run dev`
2. Registrare due account diversi dalla pagina `/login` (due email distinte)
3. Aprire **due browser diversi** (es. Chrome e Firefox), oppure una finestra normale e una in incognito: la sessione Supabase è salvata nei cookie, quindi servono due contesti di navigazione separati
4. In ciascun browser fare login con un account diverso
5. In entrambi visitare la stessa stanza, es. `http://localhost:5173/stanza/test`
6. Concedere i permessi per camera e microfono quando richiesti
7. Premere "Entra" in entrambe le finestre: ciascun utente deve vedere e sentire l'altro

Note:
- Su una singola macchina alcuni browser non condividono la stessa webcam tra due processi: se la camera non si apre nella seconda finestra, usare due browser diversi o un secondo dispositivo
- Per provare da un secondo dispositivo (es. smartphone) serve HTTPS, perché `getUserMedia` è bloccato su HTTP fuori da localhost: fare deploy su Vercel oppure usare un tunnel (es. `ngrok`)
- In alternativa si può entrare nella stessa stanza dall'app di esempio LiveKit Meet, generando un token dalla dashboard di LiveKit Cloud
