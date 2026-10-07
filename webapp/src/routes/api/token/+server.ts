import { LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL } from '$env/static/private';
import { isValidRoomName } from '$lib/rooms';
import { error, json } from '@sveltejs/kit';
import { AccessToken, AgentDispatchClient } from 'livekit-server-sdk';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ request, locals: { safeGetSession } }) => {
	const { user } = await safeGetSession();
	if (!user) {
		error(401, 'Autenticazione richiesta.');
	}

	const body = (await request.json().catch(() => null)) as
		| { room?: unknown; mode?: unknown }
		| null;
	const room = typeof body?.room === 'string' ? body.room : '';
	const mode = body?.mode === 'bot' ? 'bot' : 'room';

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

	// LiveKit only honors `roomConfig.agents` on the join that *creates* the
	// room, so joining an already-existing room (e.g. from a previous test)
	// silently never dispatches the agent. The explicit Agent Dispatch API
	// works regardless of the room's lifecycle, so we use that instead.
	if (mode === 'bot') {
		// AgentDispatchClient speaks HTTP(S); LIVEKIT_URL is a ws(s):// URL.
		const httpUrl = LIVEKIT_URL.replace(/^ws/, 'http');
		const dispatchClient = new AgentDispatchClient(httpUrl, LIVEKIT_API_KEY, LIVEKIT_API_SECRET);
		await dispatchClient.createDispatch(room, 'llm-bot');
	}

	return json({ token: await token.toJwt() });
};
