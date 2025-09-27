import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { useOutletContext } from "react-router";

import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";

import type { ToolLayoutContextValue } from "./_app.tools";

export default function ToolFilesView() {
  const { tool, handleUpload, uploadState } =
    useOutletContext<ToolLayoutContextValue>();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [localError, setLocalError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedFiles.length === 0) {
      setLocalError("Select at least one file to upload.");
      return;
    }
    setLocalError(null);
    await handleUpload(selectedFiles);
    setSelectedFiles([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Manage sample files</h1>
        <p className="text-sm text-muted-foreground">
          Upload CSV or spreadsheet files that belong to this project.
        </p>
      </header>

      <form className="space-y-4 rounded-md border border-border p-4" onSubmit={onSubmit}>
        <div className="space-y-2">
          <Label htmlFor="sample-files">Upload files</Label>
          <Input
            ref={fileInputRef}
            id="sample-files"
            type="file"
            multiple
            accept=".csv,.xls,.xlsx"
            onChange={(event) =>
              setSelectedFiles(
                event.target.files ? Array.from(event.target.files) : []
              )
            }
          />
          <p className="text-xs text-muted-foreground">
            {selectedFiles.length > 0
              ? `${selectedFiles.length} file${selectedFiles.length > 1 ? "s" : ""} selected`
              : "Select one or more files to upload."}
          </p>
          {localError && (
            <p className="text-xs text-destructive">{localError}</p>
          )}
        </div>

        {selectedFiles.length > 0 && (
          <ul className="space-y-2 text-sm text-muted-foreground">
            {selectedFiles.map((file) => (
              <li
                key={`${file.name}-${file.lastModified}`}
                className="flex items-center justify-between rounded-md border border-border px-3 py-2"
              >
                <span className="truncate pr-4" title={file.name}>
                  {file.name}
                </span>
                <span className="text-xs uppercase">
                  {Math.max(1, Math.round(file.size / 1024))} KB
                </span>
              </li>
            ))}
          </ul>
        )}

        <Button type="submit" className="w-full" disabled={selectedFiles.length === 0}>
          Upload
        </Button>
      </form>

      {uploadState.isUploading && (
        <p className="text-xs text-muted-foreground">Uploading files…</p>
      )}
      {uploadState.error && (
        <p className="text-xs text-destructive">{uploadState.error}</p>
      )}
      {uploadState.feedback && (
        <p className="text-xs text-muted-foreground">{uploadState.feedback}</p>
      )}

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Uploaded files</h2>
        {tool.files.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No files uploaded yet.
          </p>
        ) : (
          <ul className="space-y-2">
            {tool.files.map((file) => (
              <li
                key={file.id}
                className="rounded-md border border-border px-4 py-3"
              >
                <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
                  <div>
                    <p className="text-sm font-medium">{file.original_filename}</p>
                    <p className="text-xs text-muted-foreground">
                      Uploaded {new Date(file.uploaded_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    {file.content_type && <span>{file.content_type}</span>}
                    <span className="font-mono">{file.stored_filename}</span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
