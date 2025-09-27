import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { useLoaderData, useRevalidator } from "react-router";

import { API_BASE_URL } from "../config";
import type { Route } from "./+types/_app.tools.$toolId";

type ToolFile = {
  id: number;
  tool_id: number;
  original_filename: string;
  stored_filename: string;
  content_type: string | null;
  size_bytes: number;
  uploaded_at: string;
};

type ToolDetail = {
  id: number;
  name: string;
  created_at: string;
  files: ToolFile[];
};

export async function loader({ params }: Route.LoaderArgs) {
  const { toolId } = params;
  if (!toolId) {
    throw new Response("Tool identifier is required", { status: 400 });
  }

  const response = await fetch(`${API_BASE_URL}/api/tools/${toolId}`, {
    headers: { Accept: "application/json" },
  });

  if (response.status === 404) {
    throw new Response("Tool not found", { status: 404 });
  }

  if (!response.ok) {
    throw new Response("Failed to load tool", { status: response.status });
  }

  const tool = (await response.json()) as ToolDetail;
  return { tool };
}

function formatBytes(bytes: number) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const result = bytes / Math.pow(1024, index);
  return `${result.toFixed(result >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

export default function ToolDetailRoute() {
  const { tool } = useLoaderData<typeof loader>();
  const revalidator = useRevalidator();
  const inputRef = useRef<HTMLInputElement | null>(null);

  const [filesToUpload, setFilesToUpload] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (filesToUpload.length === 0) {
      setError("Select at least one CSV or Excel file to upload.");
      return;
    }

    setError(null);
    setFeedback(null);
    setIsUploading(true);

    try {
      const formData = new FormData();
      filesToUpload.forEach((file) => formData.append("files", file));

      const response = await fetch(`${API_BASE_URL}/api/tools/${tool.id}/files`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        let detail = "Failed to upload files";
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload?.detail) {
            detail = payload.detail;
          }
        } catch (parseError) {
          console.error(parseError);
        }
        throw new Error(detail);
      }

      const uploaded = (await response.json()) as ToolFile[];
      setFeedback(
        uploaded.length === 1
          ? `${uploaded[0].original_filename} uploaded successfully.`
          : `${uploaded.length} files uploaded successfully.`
      );
      setFilesToUpload([]);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      revalidator.revalidate();
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : "Something went wrong while uploading the files"
      );
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <header className="rounded-2xl border border-slate-800 bg-slate-900/60 px-6 py-5 shadow-lg">
        <h3 className="text-xl font-semibold text-white">{tool.name}</h3>
        <p className="text-xs uppercase tracking-wide text-slate-500">
          Created {new Date(tool.created_at).toLocaleString()}
        </p>
      </header>

      <form
        className="rounded-2xl border border-dashed border-indigo-500/50 bg-indigo-500/10 px-6 py-8 shadow-lg"
        onSubmit={handleSubmit}
      >
        <label
          htmlFor="file-upload"
          className="block text-sm font-medium text-indigo-100"
        >
          Upload CSV or Excel files
        </label>
        <p className="mt-1 text-xs text-indigo-200/80">
          Supported formats: .csv, .xls, .xlsx. You can add multiple files at once.
        </p>

        <input
          ref={inputRef}
          id="file-upload"
          type="file"
          multiple
          accept=".csv,.xls,.xlsx"
          className="mt-4 block w-full rounded-lg border border-indigo-400/60 bg-slate-950 px-3 py-3 text-sm text-slate-100 file:mr-4 file:rounded-md file:border-0 file:bg-indigo-500 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-indigo-400 focus:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-500/70"
          onChange={(event) =>
            setFilesToUpload(event.target.files ? Array.from(event.target.files) : [])
          }
        />

        {filesToUpload.length > 0 && (
          <ul className="mt-4 space-y-2 text-sm text-indigo-100/90">
            {filesToUpload.map((file) => (
              <li
                key={`${file.name}-${file.lastModified}`}
                className="flex items-center justify-between rounded-md border border-indigo-400/40 bg-indigo-500/5 px-3 py-2"
              >
                <span className="truncate pr-4" title={file.name}>
                  {file.name}
                </span>
                <span className="text-xs uppercase tracking-wide text-indigo-200/80">
                  {formatBytes(file.size)}
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-6 flex items-center gap-3">
          <button
            type="submit"
            className="rounded-lg bg-indigo-500 px-5 py-2 text-sm font-semibold text-white transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isUploading}
          >
            {isUploading ? "Uploading..." : "Upload files"}
          </button>
          {feedback && (
            <span className="text-xs font-medium text-emerald-300">{feedback}</span>
          )}
          {error && (
            <span className="text-xs font-medium text-red-300">{error}</span>
          )}
        </div>
      </form>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 px-6 py-6 shadow-lg">
        <h4 className="text-lg font-semibold text-white">Uploaded files</h4>
        {tool.files.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">
            No files uploaded yet. Upload a CSV or Excel file to see it listed here.
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-slate-800 text-sm">
            {tool.files.map((file) => (
              <li key={file.id} className="flex items-center justify-between py-3">
                <div>
                  <p className="font-medium text-slate-100">{file.original_filename}</p>
                  <p className="text-xs text-slate-500">
                    Uploaded {new Date(file.uploaded_at).toLocaleString()} · {formatBytes(file.size_bytes)}
                  </p>
                </div>
                {file.content_type && (
                  <span className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-[10px] uppercase tracking-wide text-slate-400">
                    {file.content_type}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
