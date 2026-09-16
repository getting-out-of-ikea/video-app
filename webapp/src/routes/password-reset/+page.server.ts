import { fail } from '@sveltejs/kit';
import type { Actions } from './$types';

export const actions: Actions = {
	default: async ({ request, url, locals: { supabase } }) => {
		const formData = await request.formData();
		const email = formData.get('email') as string;

		if (!email) {
			return fail(400, { error: "L'email è obbligatoria." });
		}

		await supabase.auth.resetPasswordForEmail(email, {
			redirectTo: `${url.origin}/auth/confirm?next=/account`
		});

		// Always return the same message, so we don't reveal whether the email exists
		return { message: "Se l'email è registrata, riceverai un link per reimpostare la password." };
	}
};
