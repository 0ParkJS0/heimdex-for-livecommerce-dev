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
