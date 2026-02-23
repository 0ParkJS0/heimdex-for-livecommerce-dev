export interface DriveStatusResponse {
  connected: boolean;
  connection_status: string | null;
  drive_name: string | null;
  last_sync_at: string | null;
  total_files: number;
  indexed: number;
  processing: number;
  pending: number;
  failed: number;
  last_indexed_at: string | null;
}

export interface DriveFolderInfo {
  folder_path: string;
  file_count: number;
  indexed_count: number;
  processing_count: number;
  failed_count: number;
  pending_count: number;
}

export interface DriveFolderListResponse {
  folders: DriveFolderInfo[];
  total_files: number;
}

export interface DriveConnectionResponse {
  id: string;
  org_id: string;
  library_id: string;
  drive_id: string | null;
  drive_name: string | null;
  scope_type: string;
  folder_id: string | null;
  folder_name: string | null;
  folder_path: string | null;
  status: string;
  last_sync_at: string | null;
  sync_requested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncTriggerResponse {
  status: string;
  sync_requested_at: string;
}

export interface DriveOAuthStatus {
  connected: boolean;
  google_email: string | null;
  connected_at: string | null;
}

export interface DriveFolderItem {
  id: string;
  name: string;
  parents?: string[];
}

export interface BrowseFoldersResponse {
  folders: DriveFolderItem[];
  parent_id: string;
}

export interface CurrentFileInfo {
  file_name: string;
  processing_status: string;
  file_size_bytes: number | null;
  started_at: string | null;
}

export interface RecentCompletedFile {
  file_name: string;
  scene_count: number;
  completed_at: string;
}

export interface FailedFileInfo {
  id: string;
  file_name: string;
  last_error: string | null;
  retry_count: number;
  failed_at: string | null;
}

export interface EnrichmentSummary {
  stt_done: number;
  stt_pending: number;
  stt_running: number;
  ocr_done: number;
  ocr_pending: number;
  ocr_running: number;
  caption_done: number;
  caption_pending: number;
  caption_running: number;
}

export interface DriveSyncProgress {
  total_files: number;
  indexed: number;
  processing: number;
  pending: number;
  failed: number;
  percent_complete: number;
  current_file: CurrentFileInfo | null;
  recent_completed: RecentCompletedFile[];
  failed_files: FailedFileInfo[];
  enrichment: EnrichmentSummary;
}
