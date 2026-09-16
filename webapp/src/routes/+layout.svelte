<script lang="ts">
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import { invalidate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { PUBLIC_SUPABASE_PUBLISHABLE_KEY, PUBLIC_SUPABASE_URL } from '$env/static/public';
	import { createBrowserClient } from '@supabase/ssr';
	import { onMount } from 'svelte';

	let { data, children } = $props();

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
</script>

<svelte:head><link rel="icon" href={favicon} /></svelte:head>

<header class="flex items-center justify-between border-b border-gray-200 px-4 py-3">
	<a href={resolve('/')} class="text-lg font-semibold">VideoApp</a>
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
