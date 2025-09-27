import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Edit, Trash2, UploadCloud } from "lucide-react";
import { useLoaderData, useNavigate, useRevalidator } from "react-router";

import { Button } from "~/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
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
  const decimals = result >= 10 || index === 0 ? 0 : 1;
  return `${result.toFixed(decimals)} ${units[index]}`;
}

function broadcastToolChange() {
  window.dispatchEvent(new CustomEvent("tool-data-updated"));
}

export default function ToolDetailRoute() {
  const { tool } = useLoaderData<typeof loader>();
  const revalidator = useRevalidator();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [toolName, setToolName] = useState(tool.name);
  const [nameInput, setNameInput] = useState(tool.name);
  const [isRenaming, setIsRenaming] = useState(false);
  const [isSavingName, setIsSavingName] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);

  const [filesToUpload, setFilesToUpload] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const [showDeletePrompt, setShowDeletePrompt] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    setToolName(tool.name);
    setNameInput(tool.name);
  }, [tool.name]);

  const hasPendingFiles = filesToUpload.length > 0;

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!hasPendingFiles) {
      setUploadError("Select at least one file to upload.");
      return;
    }

    setUploadError(null);
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
          if (payload?.detail) detail = payload.detail;
        } catch (error) {
          console.error(error);
        }
        throw new Error(detail);
      }

      const uploaded = (await response.json()) as ToolFile[];
      const summary =
        uploaded.length === 1
          ? `${uploaded[0].original_filename} uploaded successfully.`
          : `${uploaded.length} files uploaded successfully.`;
      setFeedback(summary);
      setFilesToUpload([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      broadcastToolChange();
      revalidator.revalidate();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }

  async function handleRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = nameInput.trim();
    if (!trimmed) {
      setRenameError("Tool name cannot be empty.");
      return;
    }

    setRenameError(null);
    setIsSavingName(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/tools/${tool.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: trimmed }),
      });

      if (!response.ok) {
        let detail = "Unable to rename tool";
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload?.detail) detail = payload.detail;
        } catch (error) {
          console.error(error);
        }
        throw new Error(detail);
      }

      setToolName(trimmed);
      setFeedback("Tool renamed successfully.");
      setIsRenaming(false);
      broadcastToolChange();
      revalidator.revalidate();
    } catch (error) {
      setRenameError(error instanceof Error ? error.message : "Rename failed");
    } finally {
      setIsSavingName(false);
    }
  }

  async function handleDelete() {
    setDeleteError(null);
    setIsDeleting(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/tools/${tool.id}`, {
        method: "DELETE",
      });

      if (!response.ok && response.status !== 204) {
        let detail = "Failed to delete tool";
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload?.detail) detail = payload.detail;
        } catch (error) {
          console.error(error);
        }
        throw new Error(detail);
      }

      broadcastToolChange();
      setShowDeletePrompt(false);
      navigate("/", { replace: true });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "Delete failed");
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <Card>
        <CardHeader className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle>{toolName}</CardTitle>
            <CardDescription>
              Created {new Date(tool.created_at).toLocaleString()}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => {
                setIsRenaming((prev) => !prev);
                setRenameError(null);
                setNameInput(toolName);
                setFeedback(null);
              }}
              aria-label="Rename tool"
            >
              <Edit className="size-4" />
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="icon"
              onClick={() => {
                setShowDeletePrompt(true);
                setDeleteError(null);
              }}
              aria-label="Delete tool"
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        </CardHeader>
        {isRenaming && (
          <CardContent>
            <form className="flex flex-col gap-3" onSubmit={handleRename}>
              <div className="space-y-2">
                <Label htmlFor="tool-name">Tool name</Label>
                <Input
                  id="tool-name"
                  value={nameInput}
                  onChange={(event) => setNameInput(event.target.value)}
                  disabled={isSavingName}
                  autoFocus
                />
                {renameError && (
                  <p className="text-sm text-destructive">{renameError}</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={isSavingName}>
                  {isSavingName ? "Saving..." : "Save"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setIsRenaming(false);
                    setNameInput(toolName);
                    setRenameError(null);
                  }}
                  disabled={isSavingName}
                >
                  Cancel
                </Button>
              </div>
            </form>
          </CardContent>
        )}
        {feedback && !isRenaming && (
          <CardFooter>
            <p className="text-sm text-muted-foreground">{feedback}</p>
          </CardFooter>
        )}
      </Card>

      <Card>
        <CardHeader className="flex flex-col gap-2">
          <CardTitle>Upload data</CardTitle>
          <CardDescription>
            Attach CSV or Excel files to this tool. Upload multiple files at once.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-6" onSubmit={handleUpload}>
            <div className="space-y-3">
              <Label htmlFor="file-upload">Files</Label>
              <Input
                ref={fileInputRef}
                id="file-upload"
                type="file"
                accept=".csv,.xls,.xlsx"
                multiple
                onChange={(event) =>
                  setFilesToUpload(event.target.files ? Array.from(event.target.files) : [])
                }
                disabled={isUploading}
              />
              <p className="text-xs text-muted-foreground">
                {hasPendingFiles
                  ? `${filesToUpload.length} file${filesToUpload.length > 1 ? "s" : ""} selected`
                  : "Select one or more files to upload."}
              </p>
            </div>

            {hasPendingFiles && (
              <div className="rounded-md border border-border">
                <ul className="divide-y divide-border text-sm">
                  {filesToUpload.map((file) => (
                    <li
                      key={`${file.name}-${file.lastModified}`}
                      className="flex items-center justify-between px-4 py-2"
                    >
                      <span className="truncate pr-4" title={file.name}>
                        {file.name}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {formatBytes(file.size)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {uploadError && (
              <p className="text-sm text-destructive">{uploadError}</p>
            )}

            <div className="flex items-center gap-2">
              <Button type="submit" disabled={isUploading}>
                <UploadCloud className="size-4" />
                {isUploading ? "Uploading..." : "Upload files"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Uploaded files</CardTitle>
          <CardDescription>Review the file history for this tool.</CardDescription>
        </CardHeader>
        <CardContent>
          {tool.files.length === 0 ? (
            <p className="text-sm text-muted-foreground">No files uploaded yet.</p>
          ) : (
            <ul className="space-y-3">
              {tool.files.map((file) => (
                <li
                  key={file.id}
                  className="rounded-md border border-border px-4 py-3"
                >
                  <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="text-sm font-medium">{file.original_filename}</p>
                      <p className="text-xs text-muted-foreground">
                        Uploaded {new Date(file.uploaded_at).toLocaleString()} · {formatBytes(file.size_bytes)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      {file.content_type && <span>{file.content_type}</span>}
                      <span className="font-mono">{file.stored_filename}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {showDeletePrompt && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-background/80 backdrop-blur-sm">
          <Card className="w-full max-w-md">
            <CardHeader>
              <CardTitle>Delete tool</CardTitle>
              <CardDescription>
                This will remove the tool and all associated uploads. This action cannot be undone.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {deleteError && (
                <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {deleteError}
                </p>
              )}
              <p className="text-sm text-muted-foreground">
                Are you sure you want to delete "{toolName}"?
              </p>
            </CardContent>
            <CardFooter className="flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setShowDeletePrompt(false);
                  setDeleteError(null);
                }}
                disabled={isDeleting}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={handleDelete}
                disabled={isDeleting}
              >
                {isDeleting ? "Deleting..." : "Delete"}
              </Button>
            </CardFooter>
          </Card>
        </div>
      )}
    </div>
  );
}
