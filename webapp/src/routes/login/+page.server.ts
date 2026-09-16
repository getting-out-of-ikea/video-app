import { fail, redirect } from '@sveltejs/kit';
import type { Actions } from './$types';

export const actions: Actions = {
	login: async ({ request, locals: { supabase } }) => {
		const formData = await request.formData();
		const email = formData.get('email') as string;
		const password = formData.get('password') as string;

		if (!email || !password) {
			return fail(400, { error: 'Email e password sono obbligatorie.', email });
		}

		const { error } = await supabase.auth.signInWithPassword({ email, password });

		if (error) {
			return fail(400, { error: 'Credenziali non valide.', email });
		}

		redirect(303, '/');
	},

	signup: async ({ request, url, locals: { supabase } }) => {
		const formData = await request.formData();
		const email = formData.get('email') as string;
		const password = formData.get('password') as string;

		if (!email || !password) {
			return fail(400, { error: 'Email e password sono obbligatorie.', email });
		}

		const { data, error } = await supabase.auth.signUp({
			email,
			password,
			options: {
				emailRedirectTo: `${url.origin}/auth/confirm`
			}
		});

		if (error) {
			return fail(400, { error: error.message, email });
		}

		// If email confirmation is disabled the user is already signed in
		if (data.session) {
			redirect(303, '/');
		}

		return { message: 'Controlla la tua email per confermare la registrazione.' };
	}
};
