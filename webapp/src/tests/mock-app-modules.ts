import { vi } from 'vitest';

/**
 * Factories for the `$app/*` SvelteKit client modules.
 *
 * These modules are not available inside Vitest, so browser tests register the
 * factories with `vi.mock` at the top of the spec:
 *
 * ```ts
 * vi.mock('$app/paths', async () =>
 *     (await import('../../tests/mock-app-modules')).createPathsMock()
 * );
 * ```
 *
 * The dynamic `import()` is required because `vi.mock` factories are hoisted
 * above the file's imports and cannot reference top-level bindings.
 */

export function createPathsMock() {
	return {
		base: '',
		assets: '',
		resolve: vi.fn((route: string, params?: Record<string, string>) => {
			if (!params) return route;
			// Minimal `[param]` interpolation, enough for the routes this app uses.
			return Object.entries(params).reduce(
				(path, [key, value]) => path.replace(`[${key}]`, encodeURIComponent(value)),
				route
			);
		})
	};
}

export function createFormsMock() {
	return {
		enhance: vi.fn(() => ({
			destroy() {},
			update() {}
		})),
		applyAction: vi.fn(async () => undefined),
		deserialize: vi.fn((value: string) => value)
	};
}

export function createNavigationMock() {
	return {
		goto: vi.fn(async () => undefined),
		invalidate: vi.fn(async () => undefined),
		invalidateAll: vi.fn(async () => undefined),
		prefetch: vi.fn(async () => undefined),
		prefetchRoutes: vi.fn(async () => undefined),
		pushState: vi.fn(),
		replaceState: vi.fn(),
		beforeNavigate: vi.fn(),
		afterNavigate: vi.fn(),
		onNavigate: vi.fn()
	};
}
