import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate, useOutletContext } from "react-router";

import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";

import { API_BASE_URL } from "../config";
import type { ToolLayoutContextValue } from "./_app.tools";

export default function ManageProjectView() {
  const { tool, revalidate } = useOutletContext<ToolLayoutContextValue>();
  const navigate = useNavigate();
  const [nameInput, setNameInput] = useState(tool.name);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    setNameInput(tool.name);
  }, [tool.name]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmed = nameInput.trim();
    if (!trimmed) {
      setError("Tool name cannot be empty.");
      return;
    }

    setIsSaving(true);
    setError(null);
    setFeedback(null);

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
        } catch (parseError) {
          console.error(parseError);
        }
        throw new Error(detail);
      }

      setFeedback("Tool renamed successfully.");
      revalidate();
    } catch (renameError) {
      setError(
        renameError instanceof Error ? renameError.message : "Rename failed"
      );
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDelete() {
    if (isDeleting) return;
    const confirmed = window.confirm(
      `Delete "${tool.name}"? This will remove all uploads and script history.`
    );
    if (!confirmed) {
      return;
    }

    setIsDeleting(true);
    setDeleteError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/tools/${tool.id}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        let detail = "Unable to delete tool";
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload?.detail) detail = payload.detail;
        } catch (parseError) {
          console.error(parseError);
        }
        throw new Error(detail);
      }

      window.dispatchEvent(new CustomEvent("tool-data-updated"));
      navigate("/");
    } catch (deleteErr) {
      setDeleteError(
        deleteErr instanceof Error ? deleteErr.message : "Delete failed"
      );
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Manage project</h1>
        <p className="text-sm text-muted-foreground">
          Update the name used for this tool in the workspace sidebar.
        </p>
      </header>

      <form className="space-y-3" onSubmit={handleSubmit}>
        <div className="space-y-2">
          <Label htmlFor="tool-name">Tool name</Label>
          <Input
            id="tool-name"
            value={nameInput}
            onChange={(event) => setNameInput(event.target.value)}
            disabled={isSaving}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <Button type="submit" disabled={isSaving}>
          {isSaving ? "Saving..." : "Save changes"}
        </Button>
      </form>

      {feedback && (
        <p className="text-sm text-muted-foreground">{feedback}</p>
      )}

      <p className="text-xs text-muted-foreground">
        Created {new Date(tool.created_at).toLocaleString()}
      </p>

      <div className="space-y-3 rounded-md border border-destructive/30 bg-destructive/5 p-4">
        <div>
          <h2 className="text-sm font-semibold text-destructive">Delete tool</h2>
          <p className="text-xs text-muted-foreground">
            Permanently remove this tool, its uploaded files, and all E2B history.
          </p>
        </div>
        {deleteError && <p className="text-sm text-destructive">{deleteError}</p>}
        <Button
          type="button"
          variant="destructive"
          onClick={handleDelete}
          disabled={isDeleting}
        >
          {isDeleting ? "Deleting..." : "Delete tool"}
        </Button>
      </div>
    </section>
  );
}
