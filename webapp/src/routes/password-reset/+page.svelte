<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import type { ActionData } from './$types';

	let { form }: { form: ActionData } = $props();
</script>

<svelte:head>
	<title>Password dimenticata · VideoApp</title>
</svelte:head>

<div class="mx-auto max-w-sm px-4 py-12">
	<h1 class="text-2xl font-semibold text-gray-900">Reimposta la password</h1>
	<p class="mt-2 text-sm text-gray-600">
		Inserisci la tua email: ti invieremo un link per scegliere una nuova password.
	</p>

	{#if form?.error}
		<p class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
			{form.error}
		</p>
	{/if}

	{#if form?.message}
		<p class="mt-4 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
			{form.message}
		</p>
	{/if}

	<form method="POST" use:enhance class="mt-6 space-y-4">
		<label class="block text-sm font-medium text-gray-700">
			Email
			<input
				name="email"
				type="email"
				required
				autocomplete="email"
				class="mt-1 block w-full rounded-md border-gray-300 shadow-sm"
			/>
		</label>

		<div class="flex items-center gap-3 pt-2">
			<button
				type="submit"
				class="flex-1 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700"
			>
				Invia il link
			</button>
			<a href={resolve('/login')} class="text-sm font-medium text-gray-600 hover:underline">
				Torna al login
			</a>
		</div>
	</form>
</div>
