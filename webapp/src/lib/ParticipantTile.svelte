<script lang="ts">
	import { ParticipantEvent, Track, type Participant } from 'livekit-client';
	import { onMount } from 'svelte';

	let {
		participant,
		speaking = false,
		isLocal = false
	}: {
		participant: Participant;
		speaking?: boolean;
		isLocal?: boolean;
	} = $props();

	let videoEl = $state<HTMLVideoElement>();
	let audioEl = $state<HTMLAudioElement>();

	let cameraTrack = $state<Track | null>(null);
	let micTrack = $state<Track | null>(null);
	let micMuted = $state(true);

	function syncTracks() {
		const camera = participant.getTrackPublication(Track.Source.Camera);
		cameraTrack = camera?.track && !camera.isMuted ? camera.track : null;

		const mic = participant.getTrackPublication(Track.Source.Microphone);
		micMuted = !mic || mic.isMuted;
		// Never render the local mic as audio, to avoid feedback
		micTrack = !isLocal && mic?.track && !mic.isMuted ? mic.track : null;
	}

	onMount(() => {
		syncTracks();

		participant
			.on(ParticipantEvent.TrackPublished, syncTracks)
			.on(ParticipantEvent.TrackUnpublished, syncTracks)
			.on(ParticipantEvent.TrackSubscribed, syncTracks)
			.on(ParticipantEvent.TrackUnsubscribed, syncTracks)
			.on(ParticipantEvent.TrackMuted, syncTracks)
			.on(ParticipantEvent.TrackUnmuted, syncTracks)
			.on(ParticipantEvent.LocalTrackPublished, syncTracks)
			.on(ParticipantEvent.LocalTrackUnpublished, syncTracks);

		return () => {
			participant
				.off(ParticipantEvent.TrackPublished, syncTracks)
				.off(ParticipantEvent.TrackUnpublished, syncTracks)
				.off(ParticipantEvent.TrackSubscribed, syncTracks)
				.off(ParticipantEvent.TrackUnsubscribed, syncTracks)
				.off(ParticipantEvent.TrackMuted, syncTracks)
				.off(ParticipantEvent.TrackUnmuted, syncTracks)
				.off(ParticipantEvent.LocalTrackPublished, syncTracks)
				.off(ParticipantEvent.LocalTrackUnpublished, syncTracks);
		};
	});

	$effect(() => {
		const el = videoEl;
		const track = cameraTrack;
		if (el && track) {
			track.attach(el);
			return () => {
				track.detach(el);
			};
		}
	});

	$effect(() => {
		const el = audioEl;
		const track = micTrack;
		if (el && track) {
			track.attach(el);
			return () => {
				track.detach(el);
			};
		}
	});
</script>

<div
	class="relative aspect-video overflow-hidden rounded-lg bg-gray-900 ring-2 {speaking
		? 'ring-green-500'
		: 'ring-transparent'}"
>
	<video
		bind:this={videoEl}
		autoplay
		playsinline
		muted
		class="h-full w-full object-cover {cameraTrack ? '' : 'invisible'}"
	></video>

	{#if !cameraTrack}
		<div class="absolute inset-0 flex items-center justify-center">
			<span
				class="flex h-16 w-16 items-center justify-center rounded-full bg-gray-700 text-2xl font-semibold text-white"
			>
				{(participant.name || participant.identity || '?').charAt(0).toUpperCase()}
			</span>
		</div>
	{/if}

	{#if !isLocal}
		<audio bind:this={audioEl} autoplay></audio>
	{/if}

	<div
		class="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/60 to-transparent px-3 py-2"
	>
		<span class="truncate text-sm font-medium text-white">
			{participant.name || participant.identity}{isLocal ? ' (tu)' : ''}
		</span>
		{#if micMuted}
			<span class="ml-2 shrink-0 rounded-full bg-red-600 px-2 py-0.5 text-xs font-medium text-white">
				Muto
			</span>
		{/if}
	</div>
</div>
