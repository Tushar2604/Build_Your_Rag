import { api } from "./client";

export interface Document {
  id: string;
  filename: string;
  status: "pending" | "uploading" | "uploaded" | "parsing" | "chunking" | "embedding" | "ready" | "failed";
  chunk_count: number;
  error: string | null;
}

export interface CreateUploadResponse {
  document_id: string;
  upload_url: string;
  storage_key: string;
}

export function listDocuments(): Promise<Document[]> {
  return api.get<Document[]>("/documents");
}

export function getDocument(id: string): Promise<Document> {
  return api.get<Document>(`/documents/${id}`);
}

export function createUpload(
  filename: string,
  contentType: string,
  sizeBytes: number,
): Promise<CreateUploadResponse> {
  return api.post<CreateUploadResponse>("/documents", {
    filename,
    content_type: contentType,
    size_bytes: sizeBytes,
  });
}

export async function uploadFile(
  uploadUrl: string,
  file: File,
): Promise<void> {
  const res = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
}

export function completeUpload(documentId: string): Promise<{ status: string }> {
  return api.post<{ status: string }>(`/documents/${documentId}/complete`);
}

export function createTextDocument(filename: string, text: string): Promise<Document> {
  return api.post<Document>("/documents/from-text", { filename, text });
}

export function retryDocument(documentId: string): Promise<{ status: string }> {
  return api.post<{ status: string }>(`/documents/${documentId}/retry`);
}

export function deleteDocument(documentId: string): Promise<void> {
  return api.delete<void>(`/documents/${documentId}`);
}
