export const docs = [
  { slug: "", group: "Getting started", title: "Introduction", description: "A local-first workspace for searching documents and answering questions with citations." },
  { slug: "setup", group: "Getting started", title: "Installation and setup", description: "Run the application locally or bring up the full Docker Compose stack." },
  { slug: "workspace", group: "Getting started", title: "Using a workspace", description: "Upload sources, follow indexing, choose a model, and inspect the evidence behind answers." },
  { slug: "architecture", group: "Architecture", title: "System architecture", description: "Follow requests, queued ingestion jobs, and streamed answers across the stack." },
  { slug: "floorplan", group: "Architecture", title: "Interactive floorplan", description: "Explore the repository and trace key workflows on the architecture map." },
  { slug: "repository", group: "Architecture", title: "Repository and file guide", description: "Find the entry points, ownership boundaries, and files behind each feature." },
  { slug: "stack", group: "Architecture", title: "Technology stack", description: "See what each dependency does and what it costs to operate." },
  { slug: "ingestion", group: "Internals", title: "Sources and indexing", description: "How source material becomes searchable chunks and how indexing progress is measured." },
  { slug: "retrieval", group: "Internals", title: "Retrieval and citations", description: "How Qdrant, PostgreSQL, ranking, caching, and citations fit together." },
  { slug: "providers", group: "Internals", title: "Models, providers, and agents", description: "Configure generation and embedding providers, test connectivity, and understand the agent loop." },
  { slug: "security", group: "Internals", title: "Authentication and permissions", description: "Understand the public documentation boundary, workspace roles, document grants, and credentials." },
  { slug: "decisions", group: "Reference", title: "Decisions and alternatives", description: "Compare the chosen architecture with viable alternatives and see when to reconsider." },
  { slug: "operations", group: "Reference", title: "Operations and recovery", description: "Operate the stack, diagnose common failures, and recover the databases and document objects." },
  { slug: "testing", group: "Reference", title: "Testing and evaluation", description: "Run the right test suite and interpret what the retrieval benchmarks measure." },
] as const;

export function docHref(slug: string) {
  return slug ? `/docs/${slug}` : "/docs";
}

export function headingId(title: string) {
  return title.toLowerCase().trim().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-");
}
