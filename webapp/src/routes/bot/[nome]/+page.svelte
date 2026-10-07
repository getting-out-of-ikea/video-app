<script lang="ts">
	import {
		ConnectionState,
		ParticipantEvent,
		Room,
		RoomEvent,
		type Participant,
		type RemoteParticipant
	} from 'livekit-client';
	import { onDestroy, onMount } from 'svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	// States published by LiveKit Agents in the `lk.agent.state` attribute.
	type AgentState = 'initializing' | 'idle' | 'listening' | 'thinking' | 'speaking';

	const KNOWN_AGENT_STATES: readonly AgentState[] = [
		'initializing',
		'idle',
		'listening',
		'thinking',
		'speaking'
	];

	const AGENT_STATE_LABEL: Record<AgentState, string> = {
		initializing: 'Connessione…',
		idle: 'In attesa',
		listening: 'In ascolto',
		thinking: 'Sta pensando…',
		speaking: 'Sta parlando'
	};

	// Pre-join state
	let micReady = $state(false);
	let micError = $state('');

	// Room state
	let room = $state<Room>();
	let joined = $state(false);
	let joining = $state(false);
	let joinError = $state('');
	let connectionState = $state<ConnectionState>(ConnectionState.Disconnected);
	let micOn = $state(false);
	let agentState = $state<AgentState>('initializing');
	let agentPresent = $state(false);

	// Transcript
	type TranscriptEntry = { id: string; who: 'user' | 'bot'; text: string; final: boolean };
	let transcript = $state<TranscriptEntry[]>([]);
	let transcriptEl = $state<HTMLDivElement>();

	onMount(() => {
		requestMic();
	});

	onDestroy(() => {
		room?.disconnect();
	});

	// Keep the transcript scrolled to the bottom on any change (including
	// interim-to-final text updates on existing entries).
	$effect(() => {
		transcript.forEach((entry) => entry.text);
		if (transcriptEl) {
			transcriptEl.scrollTop = transcriptEl.scrollHeight;
		}
	});

	/**
	 * Ask for microphone permission before joining. We stop the stream right
	 * away: LiveKit will re-acquire the device when `setMicrophoneEnabled` is
	 * called, and we don't want to hold the mic while the user is still on
	 * the pre-join screen.
	 */
	async function requestMic() {
		micError = '';
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			stream.getTracks().forEach((track) => track.stop());
			micReady = true;
		} catch {
			micError = 'Impossibile accedere al microfono. Controlla i permessi del browser e riprova.';
		}
	}

	async function join() {
		if (joining) return;
		joining = true;
		joinError = '';
		transcript = [];

		let newRoom: Room | undefined;
		try {
			const res = await fetch('/api/token', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ room: data.nome, mode: 'bot' })
			});

			if (!res.ok) {
				joinError =
					res.status === 401
						? 'Sessione scaduta. Effettua di nuovo il login.'
						: 'Impossibile ottenere il token di accesso.';
				return;
			}

			const { token } = (await res.json()) as { token: string };

			newRoom = new Room();
			registerRoomListeners(newRoom);
			await newRoom.connect(data.livekitUrl, token);
			room = newRoom;

			try {
				await newRoom.localParticipant.setMicrophoneEnabled(true);
			} catch {
				// Joined anyway, without a microphone (permission denied or no device)
			}

			syncLocalState();
			syncAgent();
			joined = true;
		} catch {
			joinError = 'Connessione alla conversazione fallita. Riprova.';
			newRoom?.disconnect();
			if (room === newRoom) room = undefined;
		} finally {
			joining = false;
		}
	}

	function registerRoomListeners(r: Room) {
		r.on(RoomEvent.ParticipantConnected, syncAgent)
			.on(RoomEvent.ParticipantDisconnected, syncAgent)
			.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
				connectionState = state;
			})
			.on(RoomEvent.TrackMuted, syncLocalState)
			.on(RoomEvent.TrackUnmuted, syncLocalState)
			.on(RoomEvent.LocalTrackPublished, syncLocalState)
			.on(RoomEvent.LocalTrackUnpublished, syncLocalState)
			.on(RoomEvent.TranscriptionReceived, onTranscription)
			.on(RoomEvent.Disconnected, onDisconnected);
	}

	// --- Agent discovery & state -------------------------------------------

	// Kept outside `$state`: the UI reads `agentState` / `agentPresent`, which
	// are updated as a side effect of the LiveKit events.
	let agentParticipant: RemoteParticipant | undefined;

	function onAgentAttributesChanged() {
		updateAgentState();
	}

	function syncAgent() {
		if (!room) return;

		// Heuristic: a LiveKit Agent publishes `lk.agent.state` on its own
		// attributes; some deployments also use an `agent-` identity prefix.
		const found = [...room.remoteParticipants.values()].find(
			(p) => p.attributes['lk.agent.state'] !== undefined || p.identity.startsWith('agent-')
		);

		if (found !== agentParticipant) {
			agentParticipant?.off(ParticipantEvent.AttributesChanged, onAgentAttributesChanged);
			agentParticipant = found;
			agentParticipant?.on(ParticipantEvent.AttributesChanged, onAgentAttributesChanged);
		}

		agentPresent = found !== undefined;
		updateAgentState();
	}

	function updateAgentState() {
		const raw = agentParticipant?.attributes['lk.agent.state'];
		if (raw && (KNOWN_AGENT_STATES as readonly string[]).includes(raw)) {
			agentState = raw as AgentState;
		} else {
			agentState = 'initializing';
		}
	}

	// --- Local mic ---------------------------------------------------------

	function syncLocalState() {
		if (!room) return;
		micOn = room.localParticipant.isMicrophoneEnabled;
	}

	async function toggleMic() {
		await room?.localParticipant.setMicrophoneEnabled(!micOn);
		syncLocalState();
	}

	// --- Transcript --------------------------------------------------------

	function onTranscription(
		segments: { id: string; text: string; final: boolean }[],
		participant?: Participant
	) {
		if (!participant) return;

		const who: 'user' | 'bot' =
			participant.identity === room?.localParticipant.identity ? 'user' : 'bot';

		for (const seg of segments) {
			const existing = transcript.find((e) => e.id === seg.id);
			if (existing) {
				existing.text = seg.text;
				existing.final = seg.final;
			} else {
				transcript.push({ id: seg.id, who, text: seg.text, final: seg.final });
			}
		}
	}

	// --- Teardown ----------------------------------------------------------

	function onDisconnected() {
		agentParticipant?.off(ParticipantEvent.AttributesChanged, onAgentAttributesChanged);
		agentParticipant = undefined;
		room = undefined;
		joined = false;
		micOn = false;
		agentPresent = false;
		agentState = 'initializing';
		connectionState = ConnectionState.Disconnected;
	}

	async function leave() {
		await room?.disconnect();
	}
</script>

<svelte:head>
	<title>Bot {data.nome} · VideoApp</title>
</svelte:head>

{#if !joined}
	<div class="mx-auto max-w-lg px-4 py-12">
		<h1 class="text-2xl font-semibold text-gray-900">Conversazione con {data.nome}</h1>
		<p class="mt-2 text-sm text-gray-600">
			Parla con il bot. Il microfono verrà attivato al momento della connessione.
		</p>

		{#if micError}
			<div class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
				<p>{micError}</p>
				<button onclick={requestMic} class="mt-1 font-medium underline">Riprova</button>
			</div>
		{:else if micReady}
			<p class="mt-4 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
				Microfono pronto.
			</p>
		{:else}
			<p class="mt-4 text-sm text-gray-500">Richiesta accesso al microfono…</p>
		{/if}

		{#if joinError}
			<p class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
				{joinError}
			</p>
		{/if}

		<button
			onclick={join}
			disabled={joining || !micReady}
			class="mt-6 w-full rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
		>
			{joining ? 'Connessione in corso…' : 'Avvia conversazione'}
		</button>
	</div>
{:else}
	<div class="mx-auto flex max-w-3xl flex-col px-4 pt-6 pb-32">
		<div class="mb-4 flex items-center gap-3">
			<span
				class="inline-block h-3 w-3 rounded-full {agentState === 'speaking'
					? 'animate-pulse bg-green-500'
					: agentState === 'thinking'
						? 'animate-pulse bg-yellow-500'
						: agentState === 'listening'
							? 'bg-blue-500'
							: 'bg-gray-400'}"
			></span>
			<span class="text-sm font-medium text-gray-700">
				{agentPresent ? AGENT_STATE_LABEL[agentState] : 'In attesa del bot…'}
			</span>
			{#if !agentPresent}
				<span class="text-xs text-gray-500">
					l'agente non è ancora entrato nella stanza
				</span>
			{/if}
		</div>

		{#if connectionState === ConnectionState.Reconnecting || connectionState === ConnectionState.SignalReconnecting}
			<p
				class="mb-4 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-center text-sm text-yellow-800"
			>
				Connessione instabile, riconnessione in corso…
			</p>
		{/if}

		<div bind:this={transcriptEl} class="max-h-[60vh] space-y-3 overflow-y-auto">
			{#if transcript.length === 0}
				<p class="text-sm text-gray-500">La conversazione apparirà qui.</p>
			{/if}
			{#each transcript as entry (entry.id)}
				<div class={entry.who === 'user' ? 'text-right' : 'text-left'}>
					<div
						class="inline-block max-w-[80%] rounded-lg px-3 py-2 text-sm {entry.who === 'user'
							? 'bg-gray-900 text-white'
							: 'bg-gray-100 text-gray-900'} {entry.final ? '' : 'opacity-60'}"
					>
						{entry.text}
					</div>
					<div class="mt-1 text-xs text-gray-400">
						{entry.who === 'user' ? 'Tu' : 'Bot'}
						{#if !entry.final}· <span class="italic">in corso…</span>{/if}
					</div>
				</div>
			{/each}
		</div>

		<div class="fixed inset-x-0 bottom-0 border-t border-gray-200 bg-white px-4 py-3">
			<div class="mx-auto flex max-w-xl flex-wrap items-center justify-center gap-3">
				<button
					onclick={toggleMic}
					class="rounded-md px-3 py-2 text-sm font-medium {micOn
						? 'bg-gray-200 text-gray-900 hover:bg-gray-300'
						: 'bg-red-100 text-red-700 hover:bg-red-200'}"
				>
					{micOn ? 'Microfono attivo' : 'Microfono muto'}
				</button>
				<button
					onclick={leave}
					class="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700"
				>
					Abbandona
				</button>
			</div>
		</div>
	</div>
{/if}
