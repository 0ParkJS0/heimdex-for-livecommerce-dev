export interface PersonSummary {
  person_cluster_id: string;
  label: string | null;
  face_count: number;
  last_seen_scene_time: string | null;
}

export interface PeopleListResponse {
  people: PersonSummary[];
  total: number;
}

export interface RenamePersonResponse {
  person_cluster_id: string;
  label: string | null;
}
