import { useState } from "react";
import { NavLink, Outlet, useLoaderData, useRevalidator } from "react-router";

import { cn } from "~/lib/utils";

import { API_BASE_URL } from "../config";
import type { Route } from "./+types/_app.tools";

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

export type ToolLayoutContextValue = {
  tool: ToolDetail;
  revalidate: () => void;
  handleUpload: (files: File[]) => Promise<void>;
  deleteFile: (fileId: number) => Promise<void>;
  activityState: {
    isProcessing: boolean;
    error: string | null;
    message: string | null;
  };
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

export default function ToolLayout() {
  const { tool } = useLoaderData<typeof loader>();
  const revalidator = useRevalidator();
  const [isProcessing, setIsProcessing] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  async function handleUpload(files: File[]) {
    if (files.length === 0) {
      setStatusError("Select at least one file to upload.");
      setStatusMessage(null);
      return;
    }

    setIsProcessing(true);
    setStatusError(null);
    setStatusMessage(null);

    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));

      const response = await fetch(`${API_BASE_URL}/api/tools/${tool.id}/files`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        let detail = "Failed to upload files";
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload?.detail) detail = payload.detail;
        } catch (error) {
          console.error(error);
        }
        throw new Error(detail);
      }

      const uploaded = await response.json();
      const count = Array.isArray(uploaded) ? uploaded.length : 0;
      setStatusMessage(
        count === 1 ? "1 file uploaded successfully." : `${count} files uploaded successfully.`
      );
      revalidator.revalidate();
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setIsProcessing(false);
    }
  }

  async function deleteFile(fileId: number) {
    setIsProcessing(true);
    setStatusError(null);
    setStatusMessage(null);

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/tools/${tool.id}/files/${fileId}`,
        {
          method: "DELETE",
        }
      );

      if (!response.ok) {
        let detail = "Failed to delete file";
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload?.detail) detail = payload.detail;
        } catch (error) {
          console.error(error);
        }
        throw new Error(detail);
      }

      setStatusMessage("File removed successfully.");
      revalidator.revalidate();
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : "Delete failed");
    } finally {
      setIsProcessing(false);
    }
  }

  const context: ToolLayoutContextValue = {
    tool,
    revalidate: () => revalidator.revalidate(),
    handleUpload,
    deleteFile,
    activityState: {
      isProcessing,
      error: statusError,
      message: statusMessage,
    },
  };

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <aside className="w-full space-y-4 lg:w-56 lg:shrink-0">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Tool settings
          </h2>
          <nav className="mt-3 space-y-1">
            <NavLink
              end
              to="."
              className={({ isActive }) =>
                cn(
                  "block rounded-md px-3 py-2 text-sm transition",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/40"
                )
              }
            >
              Manage project
            </NavLink>
            <NavLink
              to="files"
              className={({ isActive }) =>
                cn(
                  "block rounded-md px-3 py-2 text-sm transition",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/40"
                )
              }
            >
              Manage sample files
            </NavLink>
            <NavLink
              to="script"
              className={({ isActive }) =>
                cn(
                  "block rounded-md px-3 py-2 text-sm transition",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/40"
                )
              }
            >
              Create script
            </NavLink>
            <NavLink
              to="generate-eval-files"
              className={({ isActive }) =>
                cn(
                  "block rounded-md px-3 py-2 text-sm transition",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/40"
                )
              }
            >
              Generate eval files
            </NavLink>
          </nav>
        </div>

      </aside>

      <div className="flex-1">
        <Outlet context={context} />
      </div>
    </div>
  );
}
