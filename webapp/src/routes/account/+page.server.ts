import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals: { safeGetSession } }) => {
	const { session, user } = await safeGetSession();

	if (!session) {
		redirect(303, '/login');
	}

	return { user };
};

export const actions: Actions = {
	updatePassword: async ({ request, locals: { supabase, safeGetSession } }) => {
		const { session } = await safeGetSession();
		if (!session) {
			redirect(303, '/login');
		}

		const formData = await request.formData();
		const password = formData.get('password') as string;
		const passwordConfirm = formData.get('password_confirm') as string;

		if (!password || password.length < 6) {
			return fail(400, { error: 'La password deve contenere almeno 6 caratteri.' });
		}

		if (password !== passwordConfirm) {
			return fail(400, { error: 'Le password non coincidono.' });
		}

		const { error } = await supabase.auth.updateUser({ password });

		if (error) {
			return fail(400, { error: error.message });
		}

		return { message: 'Password aggiornata con successo.' };
	}
};
