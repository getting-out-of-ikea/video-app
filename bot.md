# Bot conversazionale audio — Piano di realizzazione

## 1. Obiettivo

Estendere VideoApp con una modalità **conversazione vocale con un LLM**: l'utente
parla, il bot ascolta, elabora e risponde a voce. La UI deve mostrare:

- lo stato del bot (`in ascolto` / `sta pensando` / `sta parlando`);
- il transcript live della conversazione (utente + bot);
- i controlli locali (microfono, abbandona).

La pipeline conversazionale (STT → LLM → TTS) è la **Fase 2** e verrà sviluppata
in un secondo momento; qui definiamo anche il contratto tra UI e backend, così
che le due parti restino disaccoppiate.

## 2. Architettura

Si riusa l'infrastruttura esistente: SvelteKit (UI + auth Supabase) e LiveKit
(trasporto audio). Il bot è un **LiveKit Agent**: un worker lato server che entra
nella stanza come partecipante e gestisce STT → LLM → TTS.

```
Browser (SvelteKit)
  │  POST /api/token  { room, mode: "bot" }
  │  ← token con dispatch dell'agente
  ▼
LiveKit ── stanza ─┬─ utente  (audio, pubblica microfono)
                   └─ agente  (ascolta STT, pubblica TTS)
                        LiveKit Agent worker (Python)
                        STT  →  LLM  →  TTS
```

Perché LiveKit e non un WebSocket custom:

- riuso di trasporto, cancellazione eco, gestione device e riconnessione già presenti;
- il bot è un normale `Participant`, quindi la UI può riusare `ParticipantTile`;
- **agent state** e **transcription** sono funzionalità native di LiveKit.

## 3. Decisioni di progetto

1. **Trasporto = LiveKit** (non WebSocket custom). Coerente col resto dell'app,
   meno codice da mantenere, migliore qualità audio.
2. **L'agente è un worker LiveKit Agents (Python)** separato dalla webapp.
   Deploy indipendente; comunica solo via LiveKit Cloud. Richiede le stesse
   credenziali `LIVEKIT_URL / API_KEY / API_SECRET`.
3. **Nuova route `/bot/[nome]`**, simmetrica a `/stanza/[nome]`. Nome della
   conversazione validato con `isValidRoomName` (riuso di `$lib/rooms`).
4. **Bottone "Bot"** nell'header, dopo "Stanza", con lo stesso pattern a popover
   per scegliere il nome. Campo precompilato con un nome suggerito
   (`bot-<hash utente>`): di default si riprende la stessa conversazione.
5. **Stato del bot** letto dagli **attributi del partecipante agente**
   (`lk.agent.state`), non da segnali custom. LiveKit Agents pubblica già
   `initializing | idle | listening | thinking | speaking`.
6. **Transcript** via `RoomEvent.TranscriptionReceived` di LiveKit
   (`final: boolean`): nessun canale dati custom da inventare.
7. **Persistenza** (Fase 3) su Supabase per riprendere le conversazioni.
   In Fase 1 il transcript vive solo in memoria.

## 4. Fase 1 — UI (questo repo)

### 4.1 Bottone "Bot" (`webapp/src/routes/+layout.svelte`)

Aggiungere, dopo il bottone "Stanza", un bottone "Bot" con lo stesso pattern
popover. Stato locale aggiuntivo:

```ts
let showBotPrompt = $state(false);
let botName = $state(data.user ? `bot-${data.user.id.slice(0, 8)}` : 'bot');
let botError = $state('');

function toggleBotPrompt() {
	showBotPrompt = !showBotPrompt;
	botError = '';
}

function goToBot() {
	const name = botName.trim();
	if (!isValidRoomName(name)) {
		botError = 'Usa solo lettere minuscole, numeri e trattini (1-64 caratteri).';
		return;
	}
	showBotPrompt = false;
	goto(resolve('/bot/[nome]', { nome: name }));
}
```

### 4.2 Nuova route `/bot/[nome]`

**`webapp/src/routes/bot/[nome]/+page.server.ts`** — come quello di `/stanza`:
valida `params.nome` e restituisce `{ nome, livekitUrl }`.

**`webapp/src/routes/bot/[nome]/+page.svelte`** — versione semplificata della
stanza, senza selezione device/video. Flusso:

1. `onMount`: chiedi il permesso al microfono (niente video).
2. Bottone "Avvia conversazione": `POST /api/token` con
   `{ room: data.nome, mode: 'bot' }`.
3. `room.connect(...)` e abilita il microfono (`setMicrophoneEnabled(true)`).
4. Individua il partecipante agente, mostra stato e transcript.
5. Controlli: muta/attiva microfono, "Abbandona".

Pseudo-struttura:

```svelte
<script lang="ts">
	import { Room, RoomEvent, ParticipantEvent, ConnectionState } from 'livekit-client';
	// ...
	type AgentState = 'initializing' | 'idle' | 'listening' | 'thinking' | 'speaking';
	let agentState = $state<AgentState>('initializing');
	let transcript = $state<{ id: string; who: 'user' | 'bot'; text: string }[]>([]);
</script>
```

### 4.3 Stato del bot

- Trova il partecipante agente tra `room.remoteParticipants` (es. per attributo
  `lk.agent === '1'`, oppure per identity con prefisso noto).
- Leggi `attributes['lk.agent.state']` e reagisci a
  `ParticipantEvent.AttributesChanged`.
- Mappa gli stati a etichette UI:
  `initializing` → "Connessione…", `listening` → "In ascolto",
  `thinking` → "Sta pensando…", `speaking` → "Sta parlando".
- Fallback: se l'attributo non è presente, deriva lo stato dall'attività audio /
  dai transcript in arrivo.

### 4.4 Transcript

Ascoltare `RoomEvent.TranscriptionReceived`:

```ts
room.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
	for (const seg of segments) {
		if (seg.final) upsertFinal(seg);
		else updateInterim(seg);
	}
});
```

Ogni `seg` espone `id`, `text`, `final`; il `participant` distingue utente e bot.
Accumulare `{ id, who, text }` in `transcript` e mostrare la lista in fondo alla
pagina con auto-scroll.

> Nota: `ParticipantTile` può già visualizzare l'agente (audio-only, senza camera
> → fallback con iniziale). Per il bot probabilmente vogliamo una visualizzazione
> dedicata (avatar/pulsazione in base allo stato): in Fase 1 si può riusare
> `ParticipantTile` e rifinire in seguito.

### 4.5 Endpoint token (`webapp/src/routes/api/token/+server.ts`)

Estendere per accettare `mode: 'bot'` e, in quel caso, aggiungere al token il
**dispatch dell'agente**:

```ts
const body = (await request.json().catch(() => null)) as
	| { room?: unknown; mode?: unknown }
	| null;
const room = typeof body?.room === 'string' ? body.room : '';
const mode = body?.mode === 'bot' ? 'bot' : 'room';

const token = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, {
	identity: user.id,
	name: user.email ?? user.id,
	ttl: '1h',
	// solo per mode === 'bot': richiede l'ingresso del worker "llm-bot"
	...(mode === 'bot' ? { roomConfig: { agents: [{ agentName: 'llm-bot' }] } } : {})
});
token.addGrant({ roomJoin: true, room, canPublish: true, canSubscribe: true });
```

> Da verificare l'API esatta di `roomConfig` / `RoomAgentDispatch` rispetto alla
> versione di `livekit-server-sdk` in uso; il concetto è il "dispatched agent" di
> LiveKit. In alternativa si può usare l'Agent Dispatch API lato server.

### 4.6 Guardia di autenticazione (`webapp/src/hooks.server.ts`)

Aggiungere `/bot` alle route protette:

```ts
if (
	!event.locals.session &&
	(event.url.pathname.startsWith('/stanza') ||
		event.url.pathname.startsWith('/bot') ||
		event.url.pathname.startsWith('/account'))
) {
	redirect(303, '/login');
}
```

### 4.7 File toccati in Fase 1

| File | Intervento |
|------|-----------|
| `webapp/src/routes/+layout.svelte` | bottone "Bot" + popover |
| `webapp/src/routes/bot/[nome]/+page.svelte` | nuova pagina |
| `webapp/src/routes/bot/[nome]/+page.server.ts` | nuovo load |
| `webapp/src/routes/api/token/+server.ts` | `mode: 'bot'` + agent dispatch |
| `webapp/src/hooks.server.ts` | protezione route `/bot` |

## 5. Fase 2 — Backend (LiveKit Agents)

Worker Python in una cartella/repository separata (es. `agent/`), deployato a
parte.

- **`agent.py`**: `AgentSession` con `STT` + `LLM` + `TTS`, VAD e turn detection;
  `agent_name = "llm-bot"` per il dispatch.
- **Provider** (configurabili via env):
  - STT: Deepgram (`DEEPGRAM_API_KEY`) o Whisper;
  - LLM: OpenAI (`OPENAI_API_KEY`) o compatibile;
  - TTS: ElevenLabs / OpenAI / ecc.
- **Env condivise**: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
- **Persona e tool**: istruzioni di sistema, eventuale function calling
  (ricerca, agenda, ecc.).
- **Deploy**: processo worker persistente collegato a LiveKit Cloud; scala in base
  alle stanze attive.
- **Transcription**: abilitare l'invio delle trascrizioni in output
  (`text_output`) così la UI le riceve via `RoomEvent.TranscriptionReceived`.

Esempio minimo (indicativo):

```python
from livekit.agents import AgentSession, Agent, JobContext, WorkerOptions, cli
from livekit.plugins import openai, deepgram, elevenlabs

class Bot(Agent):
    def __init__(self):
        super().__init__(instructions="Sei un assistente vocale conciso e cordiale.")

async def entrypoint(ctx: JobContext):
    await ctx.connect()
    session = AgentSession(
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=elevenlabs.TTS(),
    )
    await session.start(room=ctx.room, agent=Bot())
    await session.generate_reply(instructions="Saluta l'utente.")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="llm-bot"))
```

## 6. Fase 3 — Persistenza (Supabase)

- Tabelle: `bot_conversations` (id, user_id, nome, created_at, updated_at) e
  `bot_messages` (id, conversation_id, role, text, created_at).
- RLS: accesso consentito solo al proprietario.
- Salvataggio: preferibilmente dal worker (fonte autorevole del transcript) o, in
  alternativa, dalla UI a fine sessione.
- Ripristino: il `load` di `/bot/[nome]` carica la cronologia e la UI la mostra
  prima/durante la connessione.
- Policy di retention opzionale.

## 7. Test

- **UI / route** (`*.spec.ts`, `*.svelte.spec.ts`): `+page.server.ts` di
  `/bot/[nome]` (validazione del nome), rendering della pagina con
  `createMockEvent`, transizioni di stato del bot, accumulo del transcript.
- **Token endpoint**: `mode: 'bot'` → token con dispatch agente; `mode` assente →
  comportamento invariato.
- **E2E** (`*.e2e.ts`): il bottone "Bot" compare dopo "Stanza" e naviga alla route.
- **Backend**: test del worker separati (fuori da questo repo).

## 8. Domande aperte

1. Provider LLM / STT / TTS preferiti, e target di latenza.
2. Persona/istruzioni del bot e necessità di tool/function calling.
3. Una o più conversazioni per utente? (proposta: nome precompilato = una
   conversazione persistente, sovrascrivibile dall'utente).
4. Mostrare anche i segmenti di transcript parziali (`final: false`) o solo i
   definitivi?
5. Barge-in: l'agente deve fermare la risposta quando l'utente riprende a parlare
   (il turn detection di default dovrebbe coprirlo, da confermare).
