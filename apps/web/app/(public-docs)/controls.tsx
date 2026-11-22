"use client";

import { Check, Clipboard, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { docHref, docs } from "./catalog";

export function CopyPage({ source }: { source: string }) {
  const [status, setStatus] = useState("Copy page");
  return (
    <button type="button" className="copy-button" aria-live="polite" onClick={async () => {
      try {
        await navigator.clipboard.writeText(source);
        setStatus("Copied");
      } catch {
        setStatus("Copy unavailable");
      }
    }}>
      {status === "Copied" ? <Check size={14} /> : <Clipboard size={14} />} {status}
    </button>
  );
}

export function DocsSearch() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  function open() {
    setQuery("");
    if (!dialog.current?.open) dialog.current?.showModal();
  }
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        open();
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  const terms = query.toLowerCase().trim().split(/\s+/);
  const matches = docs.filter((doc) => terms.every((term) =>
    `${doc.title} ${doc.group} ${doc.description}`.toLowerCase().includes(term),
  ));
  return (
    <>
      <button type="button" className="search-trigger" aria-label="Search documentation" onClick={open}>
        <Search size={15} /> <span>Search docs</span> <kbd>Ctrl K</kbd>
      </button>
      <dialog ref={dialog} className="docs-search" aria-label="Search documentation"
        onClick={(event) => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
        <div className="docs-search-body">
          <div className="docs-search-input">
            <Search size={18} />
            <input autoFocus aria-label="Search pages" placeholder="Search documentation…" value={query} onChange={(event) => setQuery(event.target.value)} />
            <button type="button" onClick={() => dialog.current?.close()}>Close</button>
          </div>
          <ul>
            {matches.map((doc) => (
              <li key={doc.slug}><Link href={docHref(doc.slug)} onClick={() => dialog.current?.close()}>
                <strong>{doc.title}</strong><span>{doc.description}</span>
              </Link></li>
            ))}
            {matches.length === 0 && <li className="docs-no-result" role="status">No matching pages.</li>}
          </ul>
        </div>
      </dialog>
    </>
  );
}
