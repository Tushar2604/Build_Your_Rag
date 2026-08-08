import { api } from "./client";

export type ReportType = "bug" | "feature_request" | "question" | "billing" | "other";
export type Priority = "low" | "medium" | "high" | "critical";
export type IssueStatus = "open" | "in_progress" | "resolved" | "closed";

export interface IssueReport {
  id: string;
  name: string;
  email: string;
  phone: string;
  report_type: ReportType;
  priority: Priority;
  subject: string;
  description: string;
  status: IssueStatus;
  page_url: string;
  /** False = saved but not emailed (support email or Resend unconfigured). */
  email_sent: boolean;
  created_at: string;
}

export interface CreateIssueInput {
  name: string;
  email: string;
  phone?: string;
  report_type: ReportType;
  priority: Priority;
  subject: string;
  description: string;
  page_url?: string;
}

export interface IssueOptions {
  report_types: { value: string; label: string }[];
  priorities: { value: string; label: string }[];
  support_email_configured: boolean;
}

export function getIssueOptions(): Promise<IssueOptions> {
  return api.get<IssueOptions>("/issues/options");
}

export function createIssue(input: CreateIssueInput): Promise<IssueReport> {
  return api.post<IssueReport>("/issues", input);
}

export function listIssues(): Promise<IssueReport[]> {
  return api.get<IssueReport[]>("/issues");
}
