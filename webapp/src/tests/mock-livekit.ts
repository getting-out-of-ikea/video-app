import { vi, type Mock } from 'vitest';
import { Track } from 'livekit-client';

/**
 * Fake `Track` — only the members used by `ParticipantTile.svelte`
 * (`attach`, `detach`, `source`, `kind`, `sid`).
 */
export interface FakeTrack {
	source: Track.Source;
	kind: Track.Kind;
	sid: string;
	attach: Mock;
	detach: Mock;
}

/**
 * Fake `TrackPublication` — only what the component reads:
 * `track`, `isMuted`, `source`, `kind`, `trackSid`.
 */
export interface FakeTrackPublication {
	source: Track.Source;
	kind: Track.Kind;
	trackSid: string;
	isMuted: boolean;
	track: FakeTrack | null;
}

/**
 * Fake `Participant`.
 *
 * `on` and `off` are chainable like the real EventEmitter (`participant.on(a).on(b)`),
 * and `emit(event, ...args)` lets tests trigger listeners pushed from the component.
 */
export interface FakeParticipant {
	identity: string;
	name: string;
	isLocal: boolean;
	getTrackPublication: Mock;
	on: Mock;
	off: Mock;
	emit(event: string, ...args: unknown[]): void;
	handlers: Map<string, Set<(...args: unknown[]) => void>>;
}

export function createFakeTrack(
	init: Partial<Pick<FakeTrack, 'source' | 'kind' | 'sid'>> = {}
): FakeTrack {
	return {
		source: init.source ?? Track.Source.Camera,
		kind: init.kind ?? Track.Kind.Video,
		sid: init.sid ?? 'TR_test',
		attach: vi.fn(),
		detach: vi.fn(() => [])
	};
}

export function createFakeTrackPublication(init: {
	source: Track.Source;
	kind?: Track.Kind;
	trackSid?: string;
	isMuted?: boolean;
	track?: FakeTrack | null;
}): FakeTrackPublication {
	const kind = init.kind ?? Track.Kind.Video;
	const track = 'track' in init ? (init.track ?? null) : createFakeTrack({ source: init.source, kind });

	return {
		source: init.source,
		kind,
		trackSid: init.trackSid ?? `TR_${init.source}`,
		isMuted: init.isMuted ?? false,
		track
	};
}

export function createFakeParticipant(
	init: {
		identity?: string;
		name?: string;
		isLocal?: boolean;
		publications?: Partial<Record<Track.Source, FakeTrackPublication | null>>;
	} = {}
): FakeParticipant {
	const handlers = new Map<string, Set<(...args: unknown[]) => void>>();
	// Kept as a live reference: mutating `publications` after creation is reflected
	// in `getTrackPublication`, so tests can simulate tracks coming and going.
	const publications = init.publications ?? {};

	const participant: FakeParticipant = {
		identity: init.identity ?? 'test-participant',
		name: init.name ?? 'Test Participant',
		isLocal: init.isLocal ?? false,
		getTrackPublication: vi.fn((source: Track.Source) => publications[source] ?? undefined),
		on: vi.fn((event: string, handler: (...args: unknown[]) => void) => {
			let set = handlers.get(event);
			if (!set) {
				set = new Set();
				handlers.set(event, set);
			}
			set.add(handler);
			return participant;
		}),
		off: vi.fn((event: string, handler: (...args: unknown[]) => void) => {
			handlers.get(event)?.delete(handler);
			return participant;
		}),
		emit: (event: string, ...args: unknown[]) => {
			handlers.get(event)?.forEach((handler) => handler(...args));
		},
		handlers
	};

	return participant;
}
