import { vi, type Mock } from 'vitest';
import type { Session, User } from '@supabase/supabase-js';

/**
 * Shape of the mocked `supabase.auth` namespace.
 *
 * Each method is a `vi.fn()` that resolves to the `{ data, error }` shape used
 * by the official client. Tests override the resolved value with
 * `mockResolvedValue(...)` / `mockResolvedValueOnce(...)` when they need a
 * specific outcome.
 */
export interface SupabaseAuthMock {
	signInWithPassword: Mock;
	signUp: Mock;
	signOut: Mock;
	getSession: Mock;
	getUser: Mock;
	updateUser: Mock;
	resetPasswordForEmail: Mock;
	exchangeCodeForSession: Mock;
	verifyOtp: Mock;
}

export interface SupabaseMock {
	auth: SupabaseAuthMock;
}

/**
 * Fake Supabase client.
 *
 * Only the methods actually used by the app are implemented. The default
 * resolved values are "logged out / no error", so a test that does not override
 * anything behaves like an anonymous visitor.
 */
export function createSupabaseMock(): SupabaseMock {
	return {
		auth: {
			signInWithPassword: vi.fn(async () => ({
				data: { user: null, session: null },
				error: null
			})),
			signUp: vi.fn(async () => ({
				data: { user: null, session: null },
				error: null
			})),
			signOut: vi.fn(async () => ({ error: null })),
			getSession: vi.fn(async () => ({ data: { session: null }, error: null })),
			getUser: vi.fn(async () => ({ data: { user: null }, error: null })),
			updateUser: vi.fn(async () => ({ data: { user: null }, error: null })),
			resetPasswordForEmail: vi.fn(async () => ({ data: {}, error: null })),
			exchangeCodeForSession: vi.fn(async () => ({
				data: { session: null, user: null },
				error: null
			})),
			verifyOtp: vi.fn(async () => ({
				data: { session: null, user: null },
				error: null
			}))
		}
	};
}

export type SafeGetSession = () => Promise<{
	session: Session | null;
	user: User | null;
}>;

/**
 * `safeGetSession`-shaped mock returning whatever session/user you pass in.
 *
 * It is still a `vi.fn()`, so tests can assert on how many times the server
 * code looked up the session and with which arguments.
 */
export function createSafeGetSessionMock(
	session: Session | null = null,
	user: User | null = null
): SafeGetSession {
	return vi.fn(async () => ({ session, user }));
}
