import { api } from "./client";

export type BatchStatus = "collecting" | "sending" | "completed";
export type CandidateStatus = "ingesting" | "needs_review" | "excluded" | "scheduled" | "failed";

export interface BatchCandidate {
  id: string;
  resume_filename: string;
  candidate_name: string;
  candidate_email: string;
  status: CandidateStatus;
  error: string | null;
  interview_id: string | null;
}

export interface InterviewBatch {
  id: string;
  role_title: string;
  job_document_id: string;
  window_opens_at: string;
  window_closes_at: string | null;
  custom_questions: string[];
  status: BatchStatus;
  total_count: number;
  sent_count: number;
  failed_count: number;
  candidates: BatchCandidate[];
}

export interface CreateBatchInput {
  role_title: string;
  job_document_id: string;
  window_opens_at: string;
  window_closes_at?: string | null;
  custom_questions?: string[];
}

export function createInterviewBatch(input: CreateBatchInput): Promise<InterviewBatch> {
  return api.post<InterviewBatch>("/interview-batches", input);
}

export function listInterviewBatches(): Promise<InterviewBatch[]> {
  return api.get<InterviewBatch[]>("/interview-batches");
}

export function getInterviewBatch(id: string): Promise<InterviewBatch> {
  return api.get<InterviewBatch>(`/interview-batches/${id}`);
}

export function attachBatchResume(
  batchId: string,
  resumeDocumentId: string,
  resumeFilename: string,
): Promise<BatchCandidate> {
  return api.post<BatchCandidate>(`/interview-batches/${batchId}/resumes`, {
    resume_document_id: resumeDocumentId,
    resume_filename: resumeFilename,
  });
}

export function extractBatchCandidates(batchId: string): Promise<{ status: string }> {
  return api.post<{ status: string }>(`/interview-batches/${batchId}/extract`);
}

export function updateBatchCandidate(
  batchId: string,
  candidateId: string,
  patch: { candidate_name?: string; candidate_email?: string; excluded?: boolean },
): Promise<BatchCandidate> {
  return api.patch<BatchCandidate>(`/interview-batches/${batchId}/candidates/${candidateId}`, patch);
}

export function sendInterviewBatch(batchId: string): Promise<{ status: string }> {
  return api.post<{ status: string }>(`/interview-batches/${batchId}/send`);
}
