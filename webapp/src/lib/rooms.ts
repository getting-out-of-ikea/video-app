/**
 * Room names: lowercase letters, digits and dashes, 1-64 characters.
 */
const ROOM_NAME_PATTERN = /^[a-z0-9-]{1,64}$/;

export function isValidRoomName(name: string): boolean {
	return ROOM_NAME_PATTERN.test(name);
}
