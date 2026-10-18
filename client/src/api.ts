export interface Target {
  id: string;
  name: string;
  sequence: string;
  offset: number;
  confidence: number | null;
  register_source: string;
  positions: string;
  warnings: string[];
  chain?: string;
  orientation?: string | null;
  register_fit?: number | null;
  input_id?: string | null;
}
export interface Library {
  id: string;
  name: string;
  members: {
    name: string;
    sequence: string;
    reference: string;
    recall: string;
  }[];
}
export interface Model {
  id: string;
  name: string;
  weights: Record<string, number>;
  tm_slope: number | null;
  tm_intercept: number | null;
  metrics?: { n: number; r2: number | null; rmse: number; evaluation: string };
}
export interface Run {
  id: string;
  kind: string;
  status: string;
  progress: number;
  message: string;
  created: number;
  request: {
    target_id?: string;
    seed?: number;
    parameters?: Record<string, unknown>;
  };
  snapshot: { target?: Target; model?: Model };
  parent_id: string | null;
  error: { message: string; code: string } | null;
}
export interface Candidate {
  name: string;
  sequence: string;
  offset?: number;
  hetero: number;
  candidate_self: number;
  target_self: number;
  specificity: number;
  specificity_both?: number;
  passed?: boolean;
  reference?: string;
  recall?: string;
}
export interface Result {
  candidates?: Candidate[];
  warnings?: string[];
  specificity_definition?: string;
  names?: string[];
  sequences?: string[];
  offset?: number;
  matrix?: number[][];
  shifts?: number[][];
  pairs?: {
    pair: number;
    names: string[];
    cognate: number;
    margin: number;
    worst_competitor: [number, string, string];
  }[];
  evaluation?: { passed: boolean; policy: string };
  model?: Model;
  orientation?: string;
  sequence?: string;
  register_fit?: number;
  [key: string]: unknown;
}
export interface Artifact {
  id: string;
  name: string;
  size: number;
  sha256: string;
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers:
        options.body instanceof FormData
          ? options.headers
          : { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new Error(
      "서버에 연결할 수 없습니다. 연결 상태를 확인하고 다시 시도해 주세요.",
    );
  }
  const payload = await response.json();
  if (!response.ok) {
    const detail = payload.error?.message;
    throw new Error(
      Array.isArray(detail)
        ? detail
            .map(
              (d: { field: string; message: string }) =>
                `${d.field}: ${d.message}`,
            )
            .join("\n")
        : String(detail || `요청 실패 (${response.status})`),
    );
  }
  return payload as T;
}
export const post = <T>(path: string, value: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(value) });
export async function upload(file: File): Promise<{ id: string }> {
  const form = new FormData();
  form.append("file", file);
  return api("/inputs", { method: "POST", body: form });
}
export const downloadURL = (id: string) =>
  `/api/v1/artifacts/${encodeURIComponent(id)}/download`;
