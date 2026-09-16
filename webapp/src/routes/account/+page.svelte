<script lang="ts">
	import { enhance } from '$app/forms';
	import type { ActionData, PageData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head>
	<title>Account · VideoApp</title>
</svelte:head>

<div class="mx-auto max-w-sm px-4 py-12">
	<h1 class="text-2xl font-semibold text-gray-900">Il tuo account</h1>
	<p class="mt-2 text-sm text-gray-600">{data.user?.email}</p>

	<h2 class="mt-8 text-lg font-medium text-gray-900">Cambia password</h2>

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

	<form method="POST" action="?/updatePassword" use:enhance class="mt-4 space-y-4">
		<label class="block text-sm font-medium text-gray-700">
			Nuova password
			<input
				name="password"
				type="password"
				required
				minlength="6"
				autocomplete="new-password"
				class="mt-1 block w-full rounded-md border-gray-300 shadow-sm"
			/>
		</label>

		<label class="block text-sm font-medium text-gray-700">
			Conferma nuova password
			<input
				name="password_confirm"
				type="password"
				required
				minlength="6"
				autocomplete="new-password"
				class="mt-1 block w-full rounded-md border-gray-300 shadow-sm"
			/>
		</label>

		<div class="pt-2">
			<button
				type="submit"
				class="w-full rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700"
			>
				Aggiorna password
			</button>
		</div>
	</form>
</div>
