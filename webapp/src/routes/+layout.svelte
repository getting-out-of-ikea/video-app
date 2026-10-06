<script lang="ts">
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import { goto, invalidate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { PUBLIC_SUPABASE_PUBLISHABLE_KEY, PUBLIC_SUPABASE_URL } from '$env/static/public';
	import { createBrowserClient } from '@supabase/ssr';
	import { isValidRoomName } from '$lib/rooms';
	import { onMount } from 'svelte';

	let { data, children } = $props();

	// Small "room" prompt that lives next to the app name
	let showRoomPrompt = $state(false);
	let roomName = $state('');
	let roomError = $state('');

	onMount(() => {
		// Browser client used only to react to auth state changes
		// (sign in, sign out, token refresh) and refresh server data
		const supabase = createBrowserClient(PUBLIC_SUPABASE_URL, PUBLIC_SUPABASE_PUBLISHABLE_KEY);

		const {
			data: { subscription }
		} = supabase.auth.onAuthStateChange((event, newSession) => {
			if (event === 'SIGNED_OUT' || newSession?.expires_at !== data.session?.expires_at) {
				invalidate('supabase:auth');
			}
		});

		return () => subscription.unsubscribe();
	});

	function toggleRoomPrompt() {
		showRoomPrompt = !showRoomPrompt;
		roomError = '';
	}

	function goToRoom() {
		const name = roomName.trim();
		if (!isValidRoomName(name)) {
			roomError = 'Usa solo lettere minuscole, numeri e trattini (1-64 caratteri).';
			return;
		}
		showRoomPrompt = false;
		roomName = '';
		roomError = '';
		goto(resolve('/stanza/[nome]', { nome: name }));
	}
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>

<header class="flex items-center justify-between border-b border-gray-200 px-4 py-3">
	<div class="flex items-center gap-2">
		<a href={resolve('/')} class="text-lg font-semibold">VideoApp</a>
		<div class="relative">
			<button
				type="button"
				onclick={toggleRoomPrompt}
				class="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
			>
				Stanza
			</button>
			{#if showRoomPrompt}
				<div
					class="absolute top-full left-0 z-10 mt-2 w-56 rounded-md border border-gray-200 bg-white p-3 shadow-lg"
				>
					<label class="block text-xs font-medium text-gray-700">
						Nome stanza
						<input
							type="text"
							bind:value={roomName}
							onkeydown={(e) => {
								if (e.key === 'Enter') goToRoom();
							}}
							placeholder="es. stanza-1"
							class="mt-1 block w-full rounded-md border-gray-300 text-sm shadow-sm"
						/>
					</label>
					{#if roomError}
						<p class="mt-2 text-xs text-red-600">{roomError}</p>
					{/if}
					<div class="mt-2 flex justify-end">
						<button
							type="button"
							onclick={goToRoom}
							class="rounded-md bg-gray-900 px-3 py-1 text-xs font-medium text-white hover:bg-gray-700"
						>
							Ok
						</button>
					</div>
				</div>
			{/if}
		</div>
	</div>
	<nav class="flex items-center gap-4 text-sm">
		{#if data.user}
			<a href={resolve('/account')} class="hidden text-gray-600 hover:underline sm:inline">
				{data.user.email}
			</a>
			<form method="POST" action={resolve('/logout')}>
				<button
					type="submit"
					class="rounded-md bg-gray-900 px-3 py-1.5 font-medium text-white hover:bg-gray-700"
				>
					Esci
				</button>
			</form>
		{:else}
			<a
				href={resolve('/login')}
				class="rounded-md bg-gray-900 px-3 py-1.5 font-medium text-white hover:bg-gray-700"
			>
				Accedi
			</a>
		{/if}
	</nav>
</header>

<main>
	{@render children()}
</main>
