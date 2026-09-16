import { LIVEKIT_URL } from '$env/static/private';
import { isValidRoomName } from '$lib/rooms';
import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

// Auth is enforced for /stanza/* in hooks.server.ts
export const load: PageServerLoad = async ({ params }) => {
	if (!isValidRoomName(params.nome)) {
		error(404, 'Stanza non trovata.');
	}

	return {
		nome: params.nome,
		livekitUrl: LIVEKIT_URL
	};
};
