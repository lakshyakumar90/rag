import { readFile } from "node:fs/promises";
import path from "node:path";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowRight, ArrowUpRight, BookOpen } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { docHref, docs, headingId } from "../../catalog";
import { CopyPage } from "../../controls";

type Props = { params: Promise<{ slug?: string[] }> };
export const dynamicParams = false;

export function generateStaticParams() {
  return docs.map(({ slug }) => ({ slug: slug ? [slug] : [] }));
}

export async function generateMetadata({ params }: Props) {
  const { slug = [] } = await params;
  const doc = docs.find((entry) => entry.slug === slug.join("/"));
  return { title: doc ? `${doc.title} | RAG Documentation` : "RAG Documentation", description: doc?.description };
}

export default async function DocPage({ params }: Props) {
  const { slug = [] } = await params;
  const index = docs.findIndex((entry) => entry.slug === slug.join("/"));
  const doc = docs[index];
  if (!doc) notFound();

  const source = await readFile(path.join(process.cwd(), "content/docs", `${doc.slug || "introduction"}.md`), "utf8");
  const headings = [...source.replace(/^```[^\n]*\n[\s\S]*?^```.*$/gm, "").matchAll(/^(#{2,3}) (.+)$/gm)]
    .map(([, level = "", title = ""]) => ({ level: level.length, title, id: headingId(title) }));
  const groups = [...new Set(docs.map((entry) => entry.group))];
  const previous = docs[index - 1];
  const next = docs[index + 1];
  const navigation = (
    <nav aria-label="Documentation">
      {groups.map((group) => (
        <div className="doc-nav-group" key={group}>
          <h2>{group}</h2>
          {docs.filter((entry) => entry.group === group).map((entry) => (
            <Link key={entry.slug} href={docHref(entry.slug)} className={entry.slug === doc.slug ? "active" : undefined}
              aria-current={entry.slug === doc.slug ? "page" : undefined}>{entry.title}</Link>
          ))}
        </div>
      ))}
    </nav>
  );
  return (
    <div className="docs-shell">
      <aside className="docs-sidebar">
        <Link className="docs-home" href="/docs"><BookOpen size={17} aria-hidden="true" /> Documentation</Link>
        <Link className="floorplan-open docs-floorplan-link" href="/floorplan">Open floorplan <ArrowUpRight size={15} aria-hidden="true" /></Link>
        <div className="desktop-doc-nav">{navigation}</div>
        <details key={doc.slug} className="mobile-doc-nav"><summary>Browse documentation</summary>{navigation}</details>
        <div className="sidebar-note"><Link href="/docs/repository">Read the file guide <ArrowUpRight size={12} aria-hidden="true" /></Link></div>
      </aside>
      <main id="main" className="doc-main">
        <div className="doc-breadcrumb">Documentation<span>/</span>{doc.group}</div>
        <div className="doc-title-row"><h1>{doc.title}</h1><CopyPage key={doc.slug} source={source} /></div>
        <p className="doc-description">{doc.description}</p>
        <article className="prose">
          {doc.slug === "floorplan" && (
            <figure className="floorplan-viewer">
              <figcaption>
                <span>Explore services, source files, and guided workflows.</span>
                <Link className="floorplan-open" href="/floorplan">Full screen <ArrowUpRight size={15} /></Link>
                <a href="/floorplan/index.html" download="rag-floorplan.html">Download HTML</a>
              </figcaption>
              <iframe title="RAG architecture floorplan" src="/floorplan/index.html" loading="lazy" />
            </figure>
          )}
          <Markdown remarkPlugins={[remarkGfm]} components={{
            h2: ({ children }) => <h2 id={headingId(String(children))}>{children}</h2>,
            h3: ({ children }) => <h3 id={headingId(String(children))}>{children}</h3>,
            table: ({ children }) => <div className="table-scroll" role="region" aria-label="Scrollable table" tabIndex={0}><table>{children}</table></div>,
          }}>{source}</Markdown>
        </article>
        <nav className="doc-pagination" aria-label="Adjacent pages">
          {previous ? <Link href={docHref(previous.slug)}><span><ArrowLeft size={14} /> Previous</span><strong>{previous.title}</strong></Link> : <div />}
          {next && <Link href={docHref(next.slug)}><span>Next <ArrowRight size={14} /></span><strong>{next.title}</strong></Link>}
        </nav>
      </main>
      <aside className="doc-toc">
        <p>On this page</p>
        <nav aria-label="On this page">{headings.map((heading) => (
          <a key={heading.id} href={`#${heading.id}`} className={heading.level === 3 ? "nested" : undefined}>{heading.title}</a>
        ))}</nav>
        <div className="toc-help">Ready to try it?<Link href="/docs/setup">Install RAG <ArrowRight size={13} /></Link></div>
      </aside>
    </div>
  );
}
