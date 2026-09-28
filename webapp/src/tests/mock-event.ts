import { vi } from 'vitest';
import type { Cookies, RequestEvent } from '@sveltejs/kit';
import type { Session, User } from '@supabase/supabase-js';
import { createSafeGetSessionMock, createSupabaseMock, type SupabaseMock } from './mock-supabase';

export interface MockCookies extends Cookies {
	/** Snapshot of the in-memory store, useful for assertions after the call. */
	snapshot(): Record<string, string>;
}

export function createMockCookies(initial: Record<string, string> = {}): MockCookies {
	const store = new Map<string, string>(Object.entries(initial));

	return {
		get: vi.fn((name: string) => store.get(name)),
		getAll: vi.fn(() => Array.from(store, ([name, value]) => ({ name, value }))),
		set: vi.fn((name: string, value: string) => {
			store.set(name, value);
		}),
		delete: vi.fn((name: string) => {
			store.delete(name);
		}),
		serialize: vi.fn((name: string, value: string) => `${name}=${value}`),
		snapshot: () => Object.fromEntries(store)
	};
}

function isMockCookies(value: unknown): value is MockCookies {
	return typeof value === 'object' && value !== null && 'snapshot' in value;
}

export interface MockEventOptions {
	/** Absolute URL of the request. Defaults to `http://localhost/`. */
	url?: string;
	/** HTTP method. Defaults to `POST` if `form`/`json` are given, otherwise `GET`. */
	method?: string;
	headers?: HeadersInit;
	/** Route parameters, e.g. `{ nome: 'stanza-1' }` for `/stanza/[nome]`. */
	params?: Record<string, string>;
	/** Route id, e.g. `/stanza/[nome]`. Defaults to `null`. */
	routeId?: string | null;
	/** Form fields: builds a multipart `FormData` body and implies `POST`. */
	form?: Record<string, string | File>;
	/** JSON body: stringified and given a `content-type: application/json` header. */
	json?: unknown;
	/** Raw body, used when `form` / `json` are not enough. */
	body?: BodyInit | null;
	/** Cookie store. Pass a `MockCookies` to keep a reference, or a plain map. */
	cookies?: MockCookies | Record<string, string>;
	/** Supabase client mock. Defaults to a fresh `createSupabaseMock()`. */
	supabase?: SupabaseMock;
	/** Override `locals.safeGetSession`. Defaults to one returning `{ session, user }`. */
	safeGetSession?: App.Locals['safeGetSession'];
	session?: Session | null;
	user?: User | null;
	/** Any additional `locals` overrides (merged last, so they win). */
	locals?: Partial<App.Locals>;
	fetch?: typeof fetch;
	getClientAddress?: () => string;
	setHeaders?: (headers: Record<string, string>) => void;
	platform?: App.Platform;
	isDataRequest?: boolean;
	isSubRequest?: boolean;
}

/**
 * Build a SvelteKit `RequestEvent` suitable for calling `load`, `actions`,
 * `GET` and `POST` from `.server.ts` modules as plain functions — no HTTP
 * server required.
 */
export function createMockEvent(options: MockEventOptions = {}): RequestEvent {
	const urlString = options.url ?? 'http://localhost/';
	const method = options.method ?? (options.form || options.json !== undefined ? 'POST' : 'GET');

	const headers = new Headers(options.headers);

	let body: BodyInit | null = options.body ?? null;
	if (options.form) {
		const formData = new FormData();
		for (const [key, value] of Object.entries(options.form)) {
			formData.append(key, value);
		}
		body = formData;
	} else if (options.json !== undefined) {
		body = JSON.stringify(options.json);
		if (!headers.has('content-type')) {
			headers.set('content-type', 'application/json');
		}
	}
	// `Request` forbids a body on GET/HEAD.
	if (method === 'GET' || method === 'HEAD') {
		body = null;
	}

	const request = new Request(urlString, { method, headers, body });

	const cookies = isMockCookies(options.cookies)
		? options.cookies
		: createMockCookies(options.cookies ?? {});

	const session = options.session ?? null;
	const user = options.user ?? null;
	const supabase = options.supabase ?? createSupabaseMock();
	const safeGetSession = options.safeGetSession ?? createSafeGetSessionMock(session, user);

	const locals: App.Locals = {
		supabase: supabase as unknown as App.Locals['supabase'],
		safeGetSession,
		session,
		user,
		...options.locals
	};

	const event = {
		cookies,
		fetch: options.fetch ?? fetch,
		getClientAddress: options.getClientAddress ?? (() => '127.0.0.1'),
		locals,
		params: options.params ?? {},
		platform: options.platform,
		request,
		route: { id: options.routeId ?? null },
		setHeaders: options.setHeaders ?? vi.fn(),
		url: new URL(urlString),
		isDataRequest: options.isDataRequest ?? false,
		isSubRequest: options.isSubRequest ?? false
	} as unknown as RequestEvent;

	return event;
}
