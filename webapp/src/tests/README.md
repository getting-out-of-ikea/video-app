# Test infrastructure (shared helpers)

This folder contains the shared test helpers described in `test.md` §0
("Infrastruttura condivisa"). It intentionally contains **no product tests**:
just the utilities every other test file will reuse, so we don't reinvent the
same mocks in every spec.

## Files

- `mock-supabase.ts` — fake Supabase client (`createSupabaseMock`) and a helper
  for `safeGetSession` (`createSafeGetSessionMock`). Every method of `auth` is a
  `vi.fn()` that resolves to the `{ data, error }` shape used by the official
  client; tests override the resolved value with `mockResolvedValue(...)` when
  they need a specific outcome.
- `mock-livekit.ts` — fake `Participant`, `TrackPublication` and `Track`
  (`createFakeParticipant`, `createFakeTrackPublication`, `createFakeTrack`).
  The participant implements `on`/`off` (both chainable, like the real one) and
  additionally exposes `emit(event, ...args)` so tests can drive state updates.
- `mock-event.ts` — factory for a SvelteKit `RequestEvent`
  (`createMockEvent`) and an in-memory `Cookies` implementation
  (`createMockCookies`). Use it to invoke `load`, `actions`, `GET` and `POST`
  from `.server.ts` modules as plain functions, without a real HTTP server.
- `mock-app-modules.ts` — factories for the `$app/*` SvelteKit client modules
  used by browser tests: `$app/paths` (`createPathsMock`), `$app/forms`
  (`createFormsMock`), `$app/navigation` (`createNavigationMock`).

## Usage

### Server-side tests (§3)

```ts
import { describe, expect, it } from 'vitest';
import { actions } from './+page.server';
import { createMockEvent } from '../../tests/mock-event';
import { createSupabaseMock, createSafeGetSessionMock } from '../../tests/mock-supabase';

describe('login action', () => {
    it('redirects to / on success', async () => {
        const supabase = createSupabaseMock();
        supabase.auth.signInWithPassword.mockResolvedValueOnce({
            data: {
                user: { id: 'u1', email: 'a@b.c' } as never,
                session: { access_token: 't' } as never
            },
            error: null
        });

        const event = createMockEvent({
            url: 'http://localhost/login',
            form: { email: 'a@b.c', password: 'secret' },
            supabase,
            safeGetSession: createSafeGetSessionMock()
        });

        await expect(actions.login(event)).rejects.toMatchObject({
            status: 303,
            location: '/'
        });
    });
});
```

### Browser tests (§2)

`$app/*` modules are not available in Vitest. Register the mock factories with
`vi.mock` at the top of the spec:

```ts
vi.mock('$app/paths', async () =>
    (await import('../../tests/mock-app-modules')).createPathsMock()
);
vi.mock('$app/forms', async () =>
    (await import('../../tests/mock-app-modules')).createFormsMock()
);
vi.mock('$app/navigation', async () =>
    (await import('../../tests/mock-app-modules')).createNavigationMock()
);
```

The dynamic `import()` inside the factory is required because `vi.mock`
factories are hoisted above the file's imports and cannot reference top-level
bindings.

### LiveKit (browser tests, §2)

```ts
import { Track } from 'livekit-client';
import { createFakeParticipant, createFakeTrackPublication } from '../../tests/mock-livekit';

const participant = createFakeParticipant({
    identity: 'alice',
    name: 'Alice',
    publications: {
        [Track.Source.Camera]: createFakeTrackPublication({
            source: Track.Source.Camera,
            kind: Track.Kind.Video
        })
    }
});

// Later: drive a re-sync from the component, as if a LiveKit event fired.
participant.emit('trackMuted', createFakeTrackPublication({ source: Track.Source.Camera }));
```

## Conventions

- These helpers deliberately use loose typings: the fakes are structurally
  different from the real LiveKit / Supabase classes. Cast at the call site
  (e.g. `fakeParticipant as unknown as Participant`) when a prop type is strict.
- Keep the naming rules already enforced by `vite.config.ts`:
  - server tests: `*.spec.ts` / `*.test.ts`;
  - browser tests: `*.svelte.spec.ts`;
  - e2e: `*.e2e.ts`.
- Nothing here should import product code, to keep the helpers trivially
  reusable in every project (client, server, e2e).
