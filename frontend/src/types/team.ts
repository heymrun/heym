export interface Team {
  id: string;
  name: string;
  description: string | null;
  creator_id: string;
  creator_email: string;
  creator_name: string;
  member_count: number;
  created_at: string;
}

export interface TeamMember {
  id: string;
  user_id: string;
  email: string;
  name: string;
  added_by: string | null;
  joined_at: string;
}

export interface TeamDetail extends Team {
  members: TeamMember[];
}

export interface TeamShare {
  id: string;
  team_id: string;
  team_name: string;
  shared_at: string;
}

export interface TeamSharedEntityItem {
  id: string;
  name: string;
}

export interface TeamSharedEntities {
  workflows: TeamSharedEntityItem[];
  credentials: TeamSharedEntityItem[];
  global_variables: TeamSharedEntityItem[];
  vector_stores: TeamSharedEntityItem[];
  workflow_templates: TeamSharedEntityItem[];
  node_templates: TeamSharedEntityItem[];
}

export interface CreateTeamRequest {
  name: string;
  description?: string | null;
}

export interface UpdateTeamRequest {
  name?: string | null;
  description?: string | null;
}

export interface AddTeamMemberRequest {
  email: string;
}
