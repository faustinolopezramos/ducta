import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { IconPackage, IconPlus, IconTrash, IconDotsVertical } from "@tabler/icons-react";
import { useCreateServerProject, useDeleteServerProject } from "../api/queries";
import { useTemplates, useGenerateFromTemplate } from "../api/templatesApi";
import { toastStore } from "../hooks/useModalStack";
import { Button, Modal, ConfirmDialog, PageContainer, PageHeader } from "./ui";
import { EmptyState } from "./ui/EmptyState";
import type { ProjectItem } from "../store/reducer";

interface ProjectsListProps {
  projects: ProjectItem[];
  onDeleteProject: (projectId: string) => void;
  workspacePath?: string;
}

function ProjectCard({ project, onNavigate, onDelete }: { project: ProjectItem; onNavigate: () => void; onDelete: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  // `GET /projects` already reports the count. Each card used to fire its own
  // `GET /projects/{id}/pipelines` to recount it — one request per card, on the
  // landing page, for a number the list response was already carrying.
  const pipelineCount = project.pipelineCount ?? project.pipelines.length;

  return (
    <div
      className="project-card"
      role="button"
      tabIndex={0}
      aria-label={`Open project ${project.name}`}
      onClick={onNavigate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onNavigate();
        }
      }}
    >
      <div className="project-card__body">
        <div className="project-card__info">
          <div className="project-card__icon">
            <IconPackage size={20} stroke={1.5} />
          </div>
          <div className="project-card__text">
            <h3 className="project-card__name">{project.name}</h3>
            <span className="project-card__id">{project.id}</span>
          </div>
        </div>

        <div className="project-card__menu">
          <button
            className="project-card__trigger"
            onClick={(e) => { e.stopPropagation(); setMenuOpen(prev => !prev); }}
            onBlur={() => setTimeout(() => setMenuOpen(false), 150)}
            aria-label="Project options"
          >
            <IconDotsVertical size={16} stroke={1.5} />
          </button>
          {menuOpen && (
            <div className="project-card__dropdown" role="presentation" onClick={(e) => e.stopPropagation()}>
              <button className="project-card__dropdown-item project-card__dropdown-item--danger" onClick={() => { onDelete(); setMenuOpen(false); }}>
                <IconTrash size={14} stroke={1.5} />
                Delete project
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="project-card__stats">
        <div className="project-card__stat">
          <span className="project-card__stat-value">{pipelineCount}</span>
          <span className="project-card__stat-label">
            {pipelineCount === 1 ? "Pipeline" : "Pipelines"}
          </span>
        </div>
        {project.createdAt && (
          <div className="project-card__stat">
            <span className="project-card__stat-value project-card__stat-value--date">
              {new Date(project.createdAt).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
            </span>
            <span className="project-card__stat-label">Created</span>
          </div>
        )}
      </div>
    </div>
  );
}

export function ProjectsList({
  projects,
  onDeleteProject,
  workspacePath
}: ProjectsListProps) {
  const navigate = useNavigate();
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [showTemplate, setShowTemplate] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [templateType, setTemplateType] = useState("medallion_basic");
  const [templateName, setTemplateName] = useState("");
  const [projectName, setProjectName] = useState("");
  const { data: templates } = useTemplates();
  const generate = useGenerateFromTemplate();
  const createProject = useCreateServerProject();
  const deleteProject = useDeleteServerProject();

  const projectToDelete = projects.find((project) => project.id === confirmDelete);

  const handleDelete = () => {
    if (!projectToDelete) return;
    deleteProject.mutate(
      { projectId: projectToDelete.id, force: true },
      {
        onSuccess: () => {
          onDeleteProject(projectToDelete.id);
          toastStore.getState().show(`Project "${projectToDelete.name}" deleted`, "success");
          setConfirmDelete(null);
        },
        onError: () => toastStore.getState().show("Unable to delete the project. Check its permissions and try again.", "error"),
      },
    );
  };

  const handleCreateEmpty = () => {
    const name = projectName.trim();
    if (!name) return;
    createProject.mutate(
      { name },
      {
        onSuccess: () => {
          toastStore.getState().show(`Project "${name}" created`, "success");
          setShowCreate(false);
          setProjectName("");
        },
        onError: () => toastStore.getState().show("Unable to create the project. Choose a unique name and try again.", "error"),
      },
    );
  };

  const handleGenerate = () => {
    if (!templateName.trim()) {
      toastStore.getState().show("Project name is required", "error");
      return;
    }
    generate.mutate(
      { template: templateType, project_name: templateName.trim() },
      {
        onSuccess: (r) => {
          toastStore.getState().show(`Project '${r.project_id}' created from ${r.template}`, "success");
          setShowTemplate(false);
          setTemplateName("");
        },
      }
    );
  };

  return (
    <PageContainer className="projects-page">
      <PageHeader
        title="Projects"
        description={
          workspacePath ? `Workspace: ${workspacePath}` : "Select a project to begin."
        }
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => setShowTemplate(true)}
              leftIcon={<IconPlus size={16} stroke={1.5} />}
            >
              New from template
            </Button>
            <Button
              variant="primary"
              onClick={() => setShowCreate(true)}
              leftIcon={<IconPlus size={16} stroke={1.5} />}
            >
              Create project
            </Button>
          </>
        }
      />

      {projects.length === 0 ? (
        <div className="projects-empty">
          <EmptyState
            icon={IconPackage}
            title="No projects yet"
            description="Create a new project to get started with pipelines and data workflows."
            action={<Button variant="primary" onClick={() => setShowCreate(true)}><IconPlus size={16} stroke={1.5} /> Create Project</Button>}
          />
        </div>
      ) : (
        <div className="projects-grid">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onNavigate={() => navigate(`/project/${project.id}`)}
              onDelete={() => setConfirmDelete(project.id)}
            />
          ))}
        </div>
      )}

      {showCreate && (
        <Modal title="Create project" onClose={() => setShowCreate(false)}>
          <div className="projects-modal__form">
            <label className="projects-modal__label" htmlFor="new-project-name">Project name</label>
            {/* eslint-disable-next-line jsx-a11y/no-autofocus -- focus belongs in the dialog the user just opened. */}
            <input id="new-project-name" className="projects-modal__input" value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="my_project" autoFocus />
            <div className="projects-modal__actions">
              <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
              <Button variant="primary" onClick={handleCreateEmpty} loading={createProject.isPending} disabled={!projectName.trim()}>Create project</Button>
            </div>
          </div>
        </Modal>
      )}

      {showTemplate && (
        <Modal title="New project from template" onClose={() => setShowTemplate(false)}>
          <div className="projects-modal__form">
            <label className="projects-modal__label" htmlFor="project-template">Template</label>
            <select
              id="project-template"
              className="projects-modal__select"
              value={templateType}
              onChange={(e) => setTemplateType(e.target.value)}
            >
              {(templates ?? [{ type: "medallion_basic", name: "Medallion Basic", description: "" }]).map((t) => (
                <option key={t.type} value={t.type}>{t.name}</option>
              ))}
            </select>
            {templates && (
              <p className="projects-modal__hint">
                {templates.find((t) => t.type === templateType)?.description}
              </p>
            )}

            <label className="projects-modal__label" htmlFor="template-project-name">Project name</label>
            <input
              id="template-project-name"
              className="projects-modal__input"
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
              placeholder="my_project"
            />

            <div className="projects-modal__actions">
              <Button variant="ghost" onClick={() => setShowTemplate(false)}>Cancel</Button>
              <Button variant="primary" onClick={handleGenerate} loading={generate.isPending} disabled={!templateName.trim()}>
                {generate.isPending ? "Creating…" : "Create"}
              </Button>
            </div>
          </div>
        </Modal>
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        title={`Delete ${projectToDelete?.name}?`}
        description="This permanently deletes the project and all its pipelines."
        tone="danger"
        requireTyping={projectToDelete?.name}
        confirmLabel="Delete project"
        pending={deleteProject.isPending}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </PageContainer>
  );
}
