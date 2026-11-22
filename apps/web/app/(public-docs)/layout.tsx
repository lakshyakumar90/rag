import Link from "next/link";
import { Layers3 } from "lucide-react";
import { DocsSearch } from "./controls";
import "./docs.css";

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="rag-doc-site">
      <a className="docs-skip" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="header-inner">
          <Link className="brand" href="/docs"><Layers3 aria-hidden="true" /> RAG<span className="brand-dot">.</span></Link>
          <nav aria-label="Site navigation">
            <Link href="/docs">Docs</Link>
            <Link href="/floorplan">Floorplan</Link>
            <Link href="/login">Open workspace</Link>
          </nav>
          <div className="header-actions"><DocsSearch /></div>
        </div>
      </header>
      {children}
    </div>
  );
}
