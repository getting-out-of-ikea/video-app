import { LIVEKIT_API_KEY, LIVEKIT_API_SECRET } from '$env/static/private';
import { isValidRoomName } from '$lib/rooms';
import { error, json } from '@sveltejs/kit';
import { AccessToken } from 'livekit-server-sdk';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ request, locals: { safeGetSession } }) => {
	const { user } = await safeGetSession();
	if (!user) {
		error(401, 'Autenticazione richiesta.');
	}

	const body = (await request.json().catch(() => null)) as { room?: unknown } | null;
	const room = typeof body?.room === 'string' ? body.room : '';

	if (!isValidRoomName(room)) {
		error(400, 'Nome della stanza non valido.');
	}

	const token = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, {
		identity: user.id,
		name: user.email ?? user.id,
		ttl: '1h'
	});
	token.addGrant({
		roomJoin: true,
		room,
		canPublish: true,
		canSubscribe: true
	});

	return json({ token: await token.toJwt() });
};
