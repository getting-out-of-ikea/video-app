<script lang="ts">
	import ParticipantTile from '$lib/ParticipantTile.svelte';
	import {
		ConnectionState,
		Room,
		RoomEvent,
		type Participant,
		type RemoteParticipant
	} from 'livekit-client';
	import { onDestroy, onMount } from 'svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	// Pre-join state
	let previewVideo = $state<HTMLVideoElement>();
	let previewStream = $state<MediaStream | null>(null);
	let previewError = $state('');
	let audioInputs = $state<MediaDeviceInfo[]>([]);
	let videoInputs = $state<MediaDeviceInfo[]>([]);
	let selectedAudioDevice = $state('');
	let selectedVideoDevice = $state('');

	// Room state
	let room = $state<Room>();
	let joined = $state(false);
	let joining = $state(false);
	let joinError = $state('');
	let connectionState = $state<ConnectionState>(ConnectionState.Disconnected);
	let remoteParticipants = $state<RemoteParticipant[]>([]);
	let activeSpeakers = $state<Set<string>>(new Set());
	let micOn = $state(false);
	let camOn = $state(false);
	let screenOn = $state(false);

	onMount(() => {
		startPreview();
	});

	onDestroy(() => {
		stopPreview();
		room?.disconnect();
	});

	// Keep the preview <video> in sync with the current preview stream
	$effect(() => {
		if (previewVideo && previewStream) {
			previewVideo.srcObject = previewStream;
		}
	});

	async function startPreview() {
		stopPreview();
		previewError = '';
		try {
			previewStream = await navigator.mediaDevices.getUserMedia({
				audio: selectedAudioDevice ? { deviceId: { exact: selectedAudioDevice } } : true,
				video: selectedVideoDevice ? { deviceId: { exact: selectedVideoDevice } } : true
			});

			// Device labels are only available after a successful getUserMedia
			const devices = await navigator.mediaDevices.enumerateDevices();
			audioInputs = devices.filter((d) => d.kind === 'audioinput');
			videoInputs = devices.filter((d) => d.kind === 'videoinput');
			if (!selectedAudioDevice) selectedAudioDevice = audioInputs[0]?.deviceId ?? '';
			if (!selectedVideoDevice) selectedVideoDevice = videoInputs[0]?.deviceId ?? '';
		} catch {
			previewError =
				'Impossibile accedere a camera o microfono. Controlla i permessi del browser e riprova.';
		}
	}

	function stopPreview() {
		previewStream?.getTracks().forEach((track) => track.stop());
		previewStream = null;
	}

	async function join() {
		if (joining) return;
		joining = true;
		joinError = '';

		let newRoom: Room | undefined;
		try {
			const res = await fetch('/api/token', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ room: data.nome })
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

			stopPreview();

			try {
				await newRoom.localParticipant.setMicrophoneEnabled(true, {
					deviceId: selectedAudioDevice || undefined
				});
				await newRoom.localParticipant.setCameraEnabled(true, {
					deviceId: selectedVideoDevice || undefined
				});
			} catch {
				// Joined anyway, without camera/microphone (denied permissions or no devices)
			}

			syncParticipants();
			syncLocalState();
			joined = true;
		} catch {
			joinError = 'Connessione alla stanza fallita. Riprova.';
			newRoom?.disconnect();
			if (room === newRoom) room = undefined;
		} finally {
			joining = false;
		}
	}

	function registerRoomListeners(r: Room) {
		r.on(RoomEvent.ParticipantConnected, syncParticipants)
			.on(RoomEvent.ParticipantDisconnected, syncParticipants)
			.on(RoomEvent.ActiveSpeakersChanged, onActiveSpeakersChanged)
			.on(RoomEvent.ConnectionStateChanged, onConnectionStateChanged)
			.on(RoomEvent.TrackMuted, syncLocalState)
			.on(RoomEvent.TrackUnmuted, syncLocalState)
			.on(RoomEvent.LocalTrackPublished, syncLocalState)
			.on(RoomEvent.LocalTrackUnpublished, syncLocalState)
			.on(RoomEvent.Disconnected, onDisconnected);
	}

	function syncParticipants() {
		remoteParticipants = room ? [...room.remoteParticipants.values()] : [];
	}

	function syncLocalState() {
		if (!room) return;
		micOn = room.localParticipant.isMicrophoneEnabled;
		camOn = room.localParticipant.isCameraEnabled;
		screenOn = room.localParticipant.isScreenShareEnabled;
	}

	function onActiveSpeakersChanged(speakers: Participant[]) {
		activeSpeakers = new Set(speakers.map((s) => s.identity));
	}

	function onConnectionStateChanged(state: ConnectionState) {
		connectionState = state;
	}

	function onDisconnected() {
		room = undefined;
		joined = false;
		remoteParticipants = [];
		activeSpeakers = new Set();
		connectionState = ConnectionState.Disconnected;
		micOn = false;
		camOn = false;
		screenOn = false;
		startPreview();
	}

	async function toggleMic() {
		await room?.localParticipant.setMicrophoneEnabled(!micOn);
		syncLocalState();
	}

	async function toggleCamera() {
		await room?.localParticipant.setCameraEnabled(!camOn);
		syncLocalState();
	}

	async function toggleScreenShare() {
		try {
			await room?.localParticipant.setScreenShareEnabled(!screenOn);
		} catch {
			// The user cancelled the screen picker or denied the permission
		}
		syncLocalState();
	}

	async function leave() {
		await room?.disconnect();
	}
</script>

<svelte:head>
	<title>Stanza {data.nome} · VideoApp</title>
</svelte:head>

{#if !joined}
	<div class="mx-auto max-w-lg px-4 py-12">
		<h1 class="text-2xl font-semibold text-gray-900">Stanza {data.nome}</h1>
		<p class="mt-2 text-sm text-gray-600">Controlla camera e microfono, poi entra nella stanza.</p>

		<div class="mt-6 overflow-hidden rounded-lg bg-black">
			{#if previewStream}
				<video
					bind:this={previewVideo}
					autoplay
					playsinline
					muted
					class="aspect-video w-full object-cover"
				></video>
			{:else}
				<div class="flex aspect-video items-center justify-center text-sm text-gray-400">
					Nessuna anteprima disponibile
				</div>
			{/if}
		</div>

		{#if previewError}
			<div class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
				<p>{previewError}</p>
				<button onclick={startPreview} class="mt-1 font-medium underline">Riprova</button>
			</div>
		{/if}

		{#if audioInputs.length > 0 || videoInputs.length > 0}
			<div class="mt-4 space-y-4">
				{#if audioInputs.length > 0}
					<label class="block text-sm font-medium text-gray-700">
						Microfono
						<select
							bind:value={selectedAudioDevice}
							onchange={startPreview}
							class="mt-1 block w-full rounded-md border-gray-300 shadow-sm"
						>
							{#each audioInputs as device (device.deviceId)}
								<option value={device.deviceId}>{device.label || 'Microfono'}</option>
							{/each}
						</select>
					</label>
				{/if}

				{#if videoInputs.length > 0}
					<label class="block text-sm font-medium text-gray-700">
						Fotocamera
						<select
							bind:value={selectedVideoDevice}
							onchange={startPreview}
							class="mt-1 block w-full rounded-md border-gray-300 shadow-sm"
						>
							{#each videoInputs as device (device.deviceId)}
								<option value={device.deviceId}>{device.label || 'Fotocamera'}</option>
							{/each}
						</select>
					</label>
				{/if}
			</div>
		{/if}

		{#if joinError}
			<p class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
				{joinError}
			</p>
		{/if}

		<button
			onclick={join}
			disabled={joining}
			class="mt-6 w-full rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
		>
			{joining ? 'Connessione in corso…' : 'Entra nella stanza'}
		</button>
	</div>
{:else if room}
	<div class="px-4 pt-6 pb-24">
		{#if connectionState === ConnectionState.Reconnecting || connectionState === ConnectionState.SignalReconnecting}
			<p
				class="mx-auto mb-4 max-w-xl rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-center text-sm text-yellow-800"
			>
				Connessione instabile, riconnessione in corso…
			</p>
		{/if}

		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
			<ParticipantTile
				participant={room.localParticipant}
				speaking={activeSpeakers.has(room.localParticipant.identity)}
				isLocal
			/>
			{#each remoteParticipants as participant (participant.identity)}
				<ParticipantTile {participant} speaking={activeSpeakers.has(participant.identity)} />
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
					onclick={toggleCamera}
					class="rounded-md px-3 py-2 text-sm font-medium {camOn
						? 'bg-gray-200 text-gray-900 hover:bg-gray-300'
						: 'bg-red-100 text-red-700 hover:bg-red-200'}"
				>
					{camOn ? 'Camera attiva' : 'Camera spenta'}
				</button>
				<button
					onclick={toggleScreenShare}
					class="rounded-md px-3 py-2 text-sm font-medium {screenOn
						? 'bg-blue-100 text-blue-700 hover:bg-blue-200'
						: 'bg-gray-200 text-gray-900 hover:bg-gray-300'}"
				>
					{screenOn ? 'Interrompi condivisione' : 'Condividi schermo'}
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
