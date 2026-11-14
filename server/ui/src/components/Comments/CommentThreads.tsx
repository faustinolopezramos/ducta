import { useState } from "react";
import { IconCheck, IconMessageCircle, IconRotate, IconTrash } from "@tabler/icons-react";
import { useCommentActions, useComments, type CommentFilter, type CommentThread } from "../../api/queries";
import { apiErrorMessage } from "../../api/mutations/errors";
import { formatRelative } from "../../utils/timeLabels";
import { PermittedButton } from "../ui/PermittedButton";

/**
 * The conversation about one node or file: open threads first, each with its
 * replies, a reply box and "resolve"; resolved ones folded below. A new
 * thread is anchored where the list is (`anchor`).
 */
export function CommentThreads({
  projectId,
  filter,
  anchor,
  label,
}: {
  projectId: string;
  filter: CommentFilter;
  /** Where a new thread goes: {pipeline, node} or {file, line}. */
  anchor: CommentThread["anchor"];
  label: string;
}) {
  const { data, isLoading } = useComments(projectId, filter);
  const actions = useCommentActions(projectId);
  const [draft, setDraft] = useState("");
  const [showResolved, setShowResolved] = useState(false);
  const threads = data?.threads ?? [];
  const open = threads.filter((t) => !t.resolved);
  const resolved = threads.filter((t) => t.resolved);

  const submit = () => {
    if (!draft.trim()) return;
    actions.add.mutate({ anchor, body: draft }, { onSuccess: () => setDraft("") });
  };

  return (
    <section className="comments" aria-label={label}>
      {isLoading ? null : open.length === 0 && resolved.length === 0 ? (
        <p className="focus-empty">No comments yet. Ask a question or leave a note for whoever works here next.</p>
      ) : (
        <ol className="comments__list">
          {open.map((t) => (
            <Thread key={t.id} thread={t} actions={actions} />
          ))}
        </ol>
      )}
      {resolved.length > 0 && (
        <button type="button" className="comments__toggle" onClick={() => setShowResolved((v) => !v)} aria-expanded={showResolved}>
          {showResolved ? "Hide" : "Show"} {resolved.length} resolved
        </button>
      )}
      {showResolved && (
        <ol className="comments__list is-resolved">
          {resolved.map((t) => (
            <Thread key={t.id} thread={t} actions={actions} />
          ))}
        </ol>
      )}
      <div className="comments__new">
        <textarea
          className="comments__input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          placeholder="Write a comment… (⌘⏎ to post)"
          aria-label={`New comment on ${label}`}
          rows={2}
        />
        <PermittedButton
          permission="pipeline.write"
          variant="secondary"
          size="sm"
          leftIcon={<IconMessageCircle size={13} />}
          disabled={!draft.trim()}
          loading={actions.add.isPending}
          onClick={submit}
        >
          Comment
        </PermittedButton>
      </div>
      {actions.add.error && <p className="comments__error" role="alert">{apiErrorMessage(actions.add.error)}</p>}
    </section>
  );
}

function Thread({ thread, actions }: { thread: CommentThread; actions: ReturnType<typeof useCommentActions> }) {
  const [reply, setReply] = useState("");
  const send = () => {
    if (!reply.trim()) return;
    actions.reply.mutate({ id: thread.id, body: reply }, { onSuccess: () => setReply("") });
  };
  return (
    <li className="comments__thread" data-resolved={thread.resolved}>
      <Message author={thread.author} at={thread.created_at} body={thread.body} />
      {thread.anchor.line != null && <span className="comments__where">line {thread.anchor.line}</span>}
      {thread.replies.map((r) => (
        <Message key={r.id} author={r.author} at={r.created_at} body={r.body} reply />
      ))}
      {!thread.resolved && (
        <input
          className="comments__reply"
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Reply…"
          aria-label={`Reply to ${thread.author}`}
        />
      )}
      <div className="comments__actions">
        <button
          type="button"
          className="comments__action"
          onClick={() => actions.resolve.mutate({ id: thread.id, resolved: !thread.resolved })}
        >
          {thread.resolved ? <IconRotate size={12} aria-hidden="true" /> : <IconCheck size={12} aria-hidden="true" />}
          {thread.resolved ? `Reopen (resolved by ${thread.resolved_by ?? "?"})` : "Resolve"}
        </button>
        <button type="button" className="comments__action" onClick={() => actions.remove.mutate(thread.id)} aria-label="Delete thread">
          <IconTrash size={12} aria-hidden="true" />
        </button>
      </div>
    </li>
  );
}

function Message({ author, at, body, reply }: { author: string; at: string; body: string; reply?: boolean }) {
  return (
    <div className={`comments__msg${reply ? " is-reply" : ""}`}>
      <span className="comments__author">{author}</span>{" "}
      <time className="comments__time" dateTime={at}>{formatRelative(at) ?? at}</time>
      <p className="comments__body">{body}</p>
    </div>
  );
}
