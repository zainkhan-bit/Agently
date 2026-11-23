export type Role = "owner" | "member";

/** A workspace, with the signed-in person's own role in it. */
export type Workspace = { id: string; name: string; role: Role };

export type Member = { user_id: string; email: string; role: Role };
