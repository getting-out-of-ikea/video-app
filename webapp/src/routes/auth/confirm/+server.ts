import { redirect } from '@sveltejs/kit';
import type { EmailOtpType } from '@supabase/supabase-js';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ url, locals: { supabase } }) => {
	const code = url.searchParams.get('code');
	const token_hash = url.searchParams.get('token_hash');
	const type = url.searchParams.get('type') as EmailOtpType | null;
	const next = url.searchParams.get('next') ?? '/';

	if (code) {
		// Default email template flow (PKCE)
		const { error } = await supabase.auth.exchangeCodeForSession(code);
		if (!error) redirect(303, next);
	} else if (token_hash && type) {
		// Custom email template flow using {{ .TokenHash }}
		const { error } = await supabase.auth.verifyOtp({ token_hash, type });
		if (!error) redirect(303, next);
	}

	redirect(303, '/login');
};
