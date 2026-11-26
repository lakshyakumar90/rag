"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Brain,
  CheckCircle2,
  Cpu,
  Database,
  FileSearch,
  FlaskConical,
  GitBranch,
  Layers,
  Lock,
  MessageSquare,
  Moon,
  Network,
  Server,
  ShieldCheck,
  Sparkles,
  Sun,
  Zap,
} from "lucide-react";
import { useTheme } from "next-themes";
import { getAccessToken } from "../../lib/auth-client";

gsap.registerPlugin(ScrollTrigger);

type StageTab = "chat" | "evals" | "memory";

type CitationPreview = {
  id: number;
  filename: string;
  page: string;
  heading: string;
  excerpt: string;
  denseRank: number;
  lexicalRank: number;
  rrf: string;
  rerank: string;
  latencyMs: string;
};

const HERO_CITATIONS: CitationPreview[] = [
  {
    id: 1,
    filename: "architecture-v2.pdf",
    page: "Page 4",
    heading: "Retrieval Pipeline › Cross-Encoder Gate",
    excerpt:
      "Top-20 dense and top-20 lexical candidates are fused with RRF (k=60), then scored by BAAI/bge-reranker-v2-m3 into calibrated [0, 1] probabilities. Queries below 0.35 abstain cleanly.",
    denseRank: 1,
    lexicalRank: 2,
    rrf: "0.0325",
    rerank: "0.941",
    latencyMs: "38.4 ms",
  },
  {
    id: 2,
    filename: "memory-spec.md",
    page: "Section 3.1",
    heading: "Cognitive Memory › Conflict Resolution",
    excerpt:
      "Async ARQ turn consolidation extracts semantic facts and supersedes conflicting entries via superseded_by_id, while keeping <memory> strictly isolated from untrusted <context>.",
    denseRank: 2,
    lexicalRank: 1,
    rrf: "0.0320",
    rerank: "0.918",
    latencyMs: "41.2 ms",
  },
  {
    id: 3,
    filename: "graph-rbac.sql",
    page: "Lines 42–68",
    heading: "Light GraphRAG › 2-Hop Recursive CTE",
    excerpt:
      "WITH RECURSIVE graph_walk traverses entities and entity_edges up to 2 hops while joining DocumentGrant allow-lists so restricted files never leak across workspace roles.",
    denseRank: 3,
    lexicalRank: 3,
    rrf: "0.0317",
    rerank: "0.884",
    latencyMs: "44.0 ms",
  },
];

const PIPELINE_FRAMES = [
  {
    step: "01",
    badge: "Hybrid + 2-Hop Graph",
    title: "Fuse dense vectors, multilingual FTS & Postgres entity graphs",
    desc: "Every query fans out across Qdrant/pgvector, PostgreSQL 'simple' + pg_trgm full-text search, and a permission-aware 2-hop recursive SQL CTE over extracted entity triples.",
    accent: "from-sky-500 to-blue-600",
    ring: "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-300",
    nodes: [
      { label: "Qdrant / pgvector", meta: "Top-20 cosine" },
      { label: "Multilingual FTS + pg_trgm", meta: "Top-20 lexical" },
      { label: "2-Hop Entity CTE", meta: "RBAC-filtered" },
    ],
    metric: "Recall@5: 100%",
  },
  {
    step: "02",
    badge: "Cross-Encoder Gate",
    title: "Calibrated reranking eliminates hallucinations before generation",
    desc: "Self-hosted TEI running BAAI/bge-reranker-v2-m3 calibrates every fused candidate into [0, 1]. Off-topic queries abstain cleanly instead of guessing from weak rank-1 RRF scores.",
    accent: "from-violet-500 to-indigo-600",
    ring: "border-violet-500/30 bg-violet-500/10 text-violet-600 dark:text-violet-300",
    nodes: [
      { label: "RRF Fusion (k=60)", meta: "raw rrf_score" },
      { label: "BAAI/bge-reranker-v2-m3", meta: "sigmoid [0, 1]" },
      { label: "Abstention Gate", meta: "threshold ≥ 0.35" },
    ],
    metric: "False IDK: 0.0%",
  },
  {
    step: "03",
    badge: "Memory & Context",
    title: "Small-to-Big parent context meets 4-tier cognitive memory",
    desc: "Contextual child chunks retrieve their full ~1,000-token deduplicated parent windows inside <context>, while Semantic, Episodic, and Procedural memories live in a strictly quarantined <memory> block.",
    accent: "from-emerald-500 to-teal-600",
    ring: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
    nodes: [
      { label: "Parent Window Packing", meta: "2,000 tok budget" },
      { label: "4-Tier Memory Block", meta: "active / superseded" },
      { label: "Injection Isolation", meta: "<memory> ≠ <context>" },
    ],
    metric: "4 Memory Tiers",
  },
  {
    step: "04",
    badge: "Verify & Ship",
    title: "Split-screen citations, live confidence & CI regression gates",
    desc: "Streamed answers emit a multi-signal confidence badge, open exact PDF pages or highlighted passages in a resizable split viewer, and promote any bad answer into an eval regression case in one click.",
    accent: "from-amber-500 to-orange-600",
    ring: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-300",
    nodes: [
      { label: "Live Confidence SSE", meta: "High · Medium · Low" },
      { label: "Split Citation Viewer", meta: "PDF #page + excerpt" },
      { label: "LLM-as-a-Judge CI", meta: "Faithfulness gate" },
    ],
    metric: "Citation Acc: 92%",
  },
];

const UPGRADE_DIFF = [
  {
    layer: "Retrieval & Gating",
    before: "Uncalibrated RRF threshold (0.15 vs max 0.0328)",
    after: "TEI BAAI/bge-reranker-v2-m3 + calibrated cosine/RRF fallback",
  },
  {
    layer: "Chunking & OCR",
    before: "Flat chunks, single worker queue, English-only FTS",
    after: "Small-to-Big contextual chunks, ingest-fast/ingest-ocr queues, vision fallback, 'simple' + pg_trgm",
  },
  {
    layer: "Quality & Evals",
    before: "Offline script only, no live answer confidence",
    after: "From-scratch Eval Studio, LLM-as-a-Judge, live Confidence SSE & + Eval flywheel",
  },
  {
    layer: "Memory & Graph",
    before: "Stateless per-conversation history, single-hop search",
    after: "4-tier Cognitive Memory with conflict superseding + RBAC-safe 2-hop Postgres GraphRAG",
  },
  {
    layer: "Scale & UI",
    before: "In-process cancel dict, Postgres cache, modal snippets",
    after: "Redis Pub/Sub cancel, RBAC-scoped TTL cache, resizable Split Citation Viewer & Inspector",
  },
];

export function RagLanding() {
  const rootRef = useRef<HTMLDivElement>(null);
  const pipelineRef = useRef<HTMLDivElement>(null);
  const [stageTab, setStageTab] = useState<StageTab>("chat");
  const [activeCitation, setActiveCitation] = useState<number>(1);
  const [activeFrame, setActiveFrame] = useState<number>(0);
  const [scrollProgress, setScrollProgress] = useState<number>(0);
  const [isAuthed, setIsAuthed] = useState(false);
  const [mounted, setMounted] = useState(false);
  const { resolvedTheme, setTheme } = useTheme();

  useEffect(() => {
    setMounted(true);
    setIsAuthed(Boolean(getAccessToken()));
  }, []);

  useEffect(() => {
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced || !rootRef.current) return;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".hero-reveal",
        { y: 24, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.8,
          stagger: 0.09,
          ease: "power3.out",
          clearProps: "transform",
        },
      );

      gsap.to(".ambient-orb", {
        y: -16,
        x: 10,
        duration: 6,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
        stagger: 1.4,
      });

      if (pipelineRef.current) {
        ScrollTrigger.create({
          trigger: pipelineRef.current,
          start: "top 68%",
          end: "bottom 42%",
          scrub: 0.5,
          onUpdate: (self) => {
            setScrollProgress(self.progress);
            const idx = Math.min(
              PIPELINE_FRAMES.length - 1,
              Math.floor(self.progress * PIPELINE_FRAMES.length),
            );
            setActiveFrame(idx);
          },
        });
      }

      gsap.fromTo(
        ".bento-card",
        { y: 30, opacity: 0, scale: 0.985 },
        {
          y: 0,
          opacity: 1,
          scale: 1,
          duration: 0.65,
          stagger: 0.07,
          ease: "power3.out",
          clearProps: "transform",
          scrollTrigger: {
            trigger: ".bento-grid",
            start: "top 82%",
            once: true,
          },
        },
      );

      gsap.fromTo(
        ".diff-row",
        { y: 18, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.55,
          stagger: 0.07,
          ease: "power2.out",
          clearProps: "transform",
          scrollTrigger: {
            trigger: ".diff-table",
            start: "top 82%",
            once: true,
          },
        },
      );

      gsap.fromTo(
        ".metric-tile",
        { y: 20, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.6,
          stagger: 0.08,
          ease: "power2.out",
          clearProps: "transform",
          scrollTrigger: {
            trigger: ".metrics-strip",
            start: "top 85%",
            once: true,
          },
        },
      );
    }, rootRef);

    return () => ctx.revert();
  }, []);

  const currentCitation =
    HERO_CITATIONS.find((c) => c.id === activeCitation) ?? HERO_CITATIONS[0]!;
  const currentFrame = PIPELINE_FRAMES[activeFrame] ?? PIPELINE_FRAMES[0]!;

  return (
    <div
      ref={rootRef}
      className="relative min-h-screen overflow-x-clip bg-background text-foreground selection:bg-accent/25"
    >
      {/* Subtle theme-consistent ambient backdrop */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
      >
        <div className="ambient-orb absolute -left-32 -top-24 h-[420px] w-[420px] rounded-full bg-blue-500/10 blur-[110px] dark:bg-blue-500/14" />
        <div className="ambient-orb absolute -right-24 top-36 h-[400px] w-[400px] rounded-full bg-violet-500/10 blur-[120px] dark:bg-violet-500/14" />
        <div className="ambient-orb absolute bottom-0 left-1/3 h-[340px] w-[340px] rounded-full bg-emerald-500/8 blur-[120px] dark:bg-emerald-500/10" />
      </div>

      {/* Floating Glass Navbar */}
      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/85 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent text-accent-foreground shadow-sm">
              <Sparkles size={16} />
            </span>
            <span className="text-sm font-semibold tracking-tight">
              RAG Workspace
            </span>
            <span className="hidden rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 font-mono text-[10px] font-medium text-accent sm:inline-block">
              v2.0
            </span>
          </Link>

          <nav
            aria-label="Primary"
            className="hidden items-center gap-6 text-xs font-medium text-muted-foreground md:flex"
          >
            <a href="#pipeline" className="transition-colors hover:text-foreground">
              Pipeline
            </a>
            <a href="#capabilities" className="transition-colors hover:text-foreground">
              Capabilities
            </a>
            <a href="#upgrade-diff" className="transition-colors hover:text-foreground">
              v2 Upgrades
            </a>
            <Link href="/docs/upgrade" className="transition-colors hover:text-foreground">
              Docs
            </Link>
            <Link href="/floorplan" className="transition-colors hover:text-foreground">
              Floorplan
            </Link>
          </nav>

          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Toggle theme"
              onClick={() =>
                setTheme(resolvedTheme === "dark" ? "light" : "dark")
              }
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-surface text-muted-foreground transition-colors hover:text-foreground"
            >
              {mounted && resolvedTheme === "dark" ? (
                <Sun size={14} />
              ) : (
                <Moon size={14} />
              )}
            </button>
            {isAuthed ? (
              <Link
                href="/dashboard"
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-foreground px-3.5 text-xs font-medium text-background transition-transform hover:scale-[1.02]"
              >
                Dashboard <ArrowRight size={13} />
              </Link>
            ) : (
              <>
                <Link
                  href="/login"
                  className="inline-flex h-8 items-center rounded-lg border border-border bg-surface px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                >
                  Sign in
                </Link>
                <Link
                  href="/register"
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-foreground px-3.5 text-xs font-medium text-background transition-transform hover:scale-[1.02]"
                >
                  Get Started <ArrowRight size={13} />
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main>
        {/* HERO SECTION + MULTI-TAB STAGE-SHOW PRODUCT MOCKUP */}
        <section className="mx-auto max-w-6xl px-4 pb-20 pt-12 sm:px-6 sm:pt-18 lg:pt-22">
          <div className="mx-auto max-w-3xl text-center">
            <div className="hero-reveal inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3.5 py-1 text-xs font-medium text-muted-foreground shadow-sm">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <span>
                Production RAG v2 · Cross-Encoder · 4-Tier Memory · Light GraphRAG
              </span>
              <Link
                href="/docs/upgrade"
                className="inline-flex items-center gap-0.5 font-semibold text-accent hover:underline"
              >
                Release Notes <ArrowUpRight size={12} />
              </Link>
            </div>

            <h1 className="hero-reveal mt-6 text-balance text-4xl font-semibold tracking-[-0.035em] text-foreground sm:text-6xl lg:text-[4.2rem] lg:leading-[1.05]">
              Enterprise RAG that{" "}
              <span className="bg-gradient-to-r from-blue-600 via-violet-600 to-emerald-500 bg-clip-text text-transparent dark:from-blue-400 dark:via-violet-400 dark:to-emerald-400">
                proves every claim.
              </span>
            </h1>

            <p className="hero-reveal mx-auto mt-5 max-w-2xl text-pretty text-base leading-relaxed text-muted-foreground sm:text-lg">
              Beyond basic vector search. Combine calibrated cross-encoder
              reranking, Small-to-Big contextual retrieval, 4-tier cognitive
              memory, 2-hop Postgres GraphRAG, and an integrated LLM-as-a-Judge
              eval studio in one multi-tenant workspace.
            </p>

            <div className="hero-reveal mt-8 flex flex-wrap items-center justify-center gap-3">
              <Link
                href={isAuthed ? "/dashboard" : "/register"}
                className="inline-flex h-11 items-center gap-2 rounded-xl bg-foreground px-6 text-sm font-medium text-background shadow-md transition-all hover:-translate-y-0.5"
              >
                {isAuthed ? "Open Dashboard" : "Get Started Free"}
                <ArrowRight size={15} />
              </Link>
              <Link
                href="/docs/upgrade"
                className="inline-flex h-11 items-center gap-2 rounded-xl border border-border bg-surface px-5 text-sm font-medium text-foreground transition-colors hover:bg-muted"
              >
                <BookOpen size={15} /> Read v2 Docs
              </Link>
              <Link
                href="/floorplan"
                className="inline-flex h-11 items-center gap-2 rounded-xl border border-border bg-surface/70 px-5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                Architecture Floorplan <ArrowUpRight size={15} />
              </Link>
            </div>
          </div>

          {/* Stage-Show Interactive Product Mockup Frame */}
          <div className="hero-reveal mt-12">
            {/* Stage Mode Switcher */}
            <div className="mb-3 flex flex-wrap items-center justify-center gap-2">
              {[
                { id: "chat" as const, label: "Split Citation Chat", icon: MessageSquare },
                { id: "evals" as const, label: "Eval Studio & Trends", icon: FlaskConical },
                { id: "memory" as const, label: "4-Tier Cognitive Memory", icon: Brain },
              ].map((tab) => {
                const Icon = tab.icon;
                const active = stageTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setStageTab(tab.id)}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-all ${
                      active
                        ? "border-accent/50 bg-accent text-accent-foreground shadow-sm"
                        : "border-border bg-surface text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <Icon size={13} />
                    {tab.label}
                  </button>
                );
              })}
            </div>

            <div className="overflow-hidden rounded-3xl border border-border bg-surface shadow-[var(--shadow-panel)]">
              {/* Browser Window Chrome */}
              <div className="flex items-center justify-between border-b border-border bg-muted/50 px-4 py-3 text-xs text-muted-foreground">
                <div className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-rose-500/75" />
                  <span className="h-2.5 w-2.5 rounded-full bg-amber-500/75" />
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/75" />
                  <span className="ml-2 font-mono text-[11px]">
                    rag-workspace / engineering / {stageTab}
                  </span>
                </div>
                <div className="hidden items-center gap-2 sm:flex">
                  <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 font-mono text-[10.5px] font-medium text-emerald-700 dark:text-emerald-300">
                    <ShieldCheck size={11} /> High · 94%
                  </span>
                  <span className="font-mono text-[11px]">
                    {currentCitation.latencyMs}
                  </span>
                </div>
              </div>

              {/* STAGE TAB 1: SPLIT CITATION CHAT */}
              {stageTab === "chat" ? (
                <div className="grid lg:grid-cols-12">
                  <div className="flex flex-col justify-between border-b border-border p-5 sm:p-6 lg:col-span-7 lg:border-b-0 lg:border-r">
                    <div className="space-y-4">
                      <div className="ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-foreground px-4 py-2.5 text-sm text-background">
                        How does RAG Workspace prevent hallucinations, isolate
                        memory, and handle multi-hop RBAC queries?
                      </div>

                      <div className="space-y-3 rounded-2xl border border-border bg-background p-4 text-sm leading-7">
                        <p>
                          Retrieval fuses top-20 dense and lexical candidates
                          with RRF and gates answerability using calibrated{" "}
                          <strong>BAAI/bge-reranker-v2-m3</strong> scores above{" "}
                          <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                            0.35
                          </code>{" "}
                          <button
                            type="button"
                            onClick={() => setActiveCitation(1)}
                            className={`mx-0.5 inline-flex h-5 items-center rounded-md px-1.5 font-mono text-[11px] font-semibold transition-all ${
                              activeCitation === 1
                                ? "bg-accent text-accent-foreground"
                                : "bg-accent/15 text-accent hover:bg-accent/25"
                            }`}
                          >
                            [1]
                          </button>
                          .
                        </p>
                        <p>
                          Durable workspace facts and procedural rules are
                          reconciled asynchronously with conflict superseding
                          and placed inside a dedicated{" "}
                          <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                            &lt;memory&gt;
                          </code>{" "}
                          block isolated from untrusted documents{" "}
                          <button
                            type="button"
                            onClick={() => setActiveCitation(2)}
                            className={`mx-0.5 inline-flex h-5 items-center rounded-md px-1.5 font-mono text-[11px] font-semibold transition-all ${
                              activeCitation === 2
                                ? "bg-accent text-accent-foreground"
                                : "bg-accent/15 text-accent hover:bg-accent/25"
                            }`}
                          >
                            [2]
                          </button>
                          .
                        </p>
                        <p>
                          Cross-document relationships expand via a 2-hop
                          recursive PostgreSQL CTE filtered by{" "}
                          <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                            DocumentGrant
                          </code>{" "}
                          permissions{" "}
                          <button
                            type="button"
                            onClick={() => setActiveCitation(3)}
                            className={`mx-0.5 inline-flex h-5 items-center rounded-md px-1.5 font-mono text-[11px] font-semibold transition-all ${
                              activeCitation === 3
                                ? "bg-accent text-accent-foreground"
                                : "bg-accent/15 text-accent hover:bg-accent/25"
                            }`}
                          >
                            [3]
                          </button>
                          .
                        </p>
                      </div>
                    </div>

                    <div className="mt-4 flex flex-wrap items-center justify-between gap-2 pt-2 text-xs text-muted-foreground">
                      <span>
                        Click [1] [2] [3] to jump to highlighted source passages →
                      </span>
                      <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-accent">
                        <Activity size={12} /> Retrieval Inspector · + Eval
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-col justify-between bg-muted/25 p-5 sm:p-6 lg:col-span-5">
                    <div className="space-y-4">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="rounded-md bg-accent px-2 py-0.5 font-mono text-xs font-semibold text-accent-foreground">
                            [{currentCitation.id}]
                          </span>
                          <span className="truncate text-sm font-semibold">
                            {currentCitation.filename}
                          </span>
                        </div>
                        <span className="shrink-0 rounded-md border border-border bg-surface px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                          {currentCitation.page}
                        </span>
                      </div>

                      <p className="text-xs text-muted-foreground">
                        {currentCitation.heading}
                      </p>

                      <blockquote className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4 text-[13px] leading-6 text-foreground">
                        {currentCitation.excerpt}
                      </blockquote>
                    </div>

                    <div className="mt-5 grid grid-cols-4 gap-2 border-t border-border pt-4 text-center font-mono text-[11px]">
                      <div className="rounded-lg border border-border bg-surface p-2">
                        <div className="text-[10px] text-muted-foreground">
                          Dense
                        </div>
                        <div className="font-semibold">
                          #{currentCitation.denseRank}
                        </div>
                      </div>
                      <div className="rounded-lg border border-border bg-surface p-2">
                        <div className="text-[10px] text-muted-foreground">
                          Lexical
                        </div>
                        <div className="font-semibold">
                          #{currentCitation.lexicalRank}
                        </div>
                      </div>
                      <div className="rounded-lg border border-border bg-surface p-2">
                        <div className="text-[10px] text-muted-foreground">
                          RRF
                        </div>
                        <div className="font-semibold">
                          {currentCitation.rrf}
                        </div>
                      </div>
                      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-2 text-emerald-700 dark:text-emerald-300">
                        <div className="text-[10px] opacity-80">Rerank</div>
                        <div className="font-semibold">
                          {currentCitation.rerank}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : stageTab === "evals" ? (
                /* STAGE TAB 2: EVAL STUDIO MOCKUP */
                <div className="space-y-5 p-5 sm:p-6">
                  <div className="grid gap-3 sm:grid-cols-4">
                    {[
                      { label: "Recall@5", value: "100%", color: "bg-sky-500", w: "100%" },
                      { label: "Faithfulness", value: "91%", color: "bg-emerald-500", w: "91%" },
                      { label: "Relevancy", value: "94%", color: "bg-violet-500", w: "94%" },
                      { label: "Citation Acc", value: "92%", color: "bg-amber-500", w: "92%" },
                    ].map((m) => (
                      <div
                        key={m.label}
                        className="rounded-2xl border border-border bg-background p-4"
                      >
                        <p className="text-xs text-muted-foreground">{m.label}</p>
                        <p className="mt-1 font-mono text-2xl font-semibold">
                          {m.value}
                        </p>
                        <div className="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                          <div
                            className={`h-full rounded-full ${m.color}`}
                            style={{ width: m.w }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="rounded-2xl border border-border bg-background p-4">
                    <div className="mb-2 flex items-center justify-between text-xs">
                      <span className="font-semibold">
                        CI Regression Gate · evals/evaluate.py --fast --markdown
                      </span>
                      <span className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 font-mono text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                        PASS (0 regressions)
                      </span>
                    </div>
                    <svg
                      viewBox="0 0 600 120"
                      className="h-28 w-full"
                      role="img"
                      aria-label="Evaluation accuracy sparkline"
                    >
                      <path
                        d="M 20 82 L 130 68 L 240 52 L 350 38 L 460 26 L 580 18"
                        fill="none"
                        stroke="#0ea5e9"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                      />
                      <path
                        d="M 20 90 L 130 78 L 240 64 L 350 48 L 460 36 L 580 28"
                        fill="none"
                        stroke="#10b981"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                      />
                      <path
                        d="M 20 96 L 130 84 L 240 72 L 350 54 L 460 40 L 580 32"
                        fill="none"
                        stroke="#f59e0b"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                      />
                    </svg>
                  </div>
                </div>
              ) : (
                /* STAGE TAB 3: 4-TIER COGNITIVE MEMORY MOCKUP */
                <div className="grid gap-4 p-5 sm:p-6 md:grid-cols-3">
                  <div className="rounded-2xl border border-sky-500/25 bg-background p-4 space-y-2.5">
                    <span className="font-mono text-[11px] font-semibold text-sky-600 dark:text-sky-300">
                      SEMANTIC FACTS
                    </span>
                    <div className="rounded-xl border border-border bg-surface p-3 text-xs">
                      <span className="font-mono text-[10px] text-emerald-600 dark:text-emerald-400">
                        ACTIVE · 96%
                      </span>
                      <p className="mt-1 font-medium">
                        Production cluster runs on AWS ap-south-1
                      </p>
                    </div>
                    <div className="rounded-xl border border-border bg-muted/40 p-3 text-xs opacity-65">
                      <span className="inline-flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
                        <GitBranch size={10} /> SUPERSEDED
                      </span>
                      <p className="mt-1 line-through">
                        We deploy on AWS ap-southeast-2
                      </p>
                    </div>
                  </div>
                  <div className="rounded-2xl border border-violet-500/25 bg-background p-4 space-y-2.5">
                    <span className="font-mono text-[11px] font-semibold text-violet-600 dark:text-violet-300">
                      EPISODIC SUMMARIES
                    </span>
                    <div className="rounded-xl border border-border bg-surface p-3 text-xs leading-relaxed text-muted-foreground">
                      Q2 Architecture Review: Agreed on isolated ingest-ocr
                      workers (2GB cap) and pg_trgm multilingual search.
                    </div>
                  </div>
                  <div className="rounded-2xl border border-emerald-500/25 bg-background p-4 space-y-2.5">
                    <span className="font-mono text-[11px] font-semibold text-emerald-600 dark:text-emerald-300">
                      PROCEDURAL RULES
                    </span>
                    <div className="rounded-xl border border-border bg-surface p-3 text-xs leading-relaxed">
                      Always cite RFC section numbers and abstain cleanly when
                      cross-encoder rerank score is below 0.35.
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* SCROLL-SCRUBBED 4-FRAME PIPELINE CHOREOGRAPHY */}
        <section
          id="pipeline"
          ref={pipelineRef}
          className="border-y border-border bg-surface/60 py-20 sm:py-28"
        >
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div className="max-w-2xl">
                <p className="font-mono text-xs font-semibold uppercase tracking-widest text-accent">
                  Scroll-Driven Pipeline
                </p>
                <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
                  Four stages from raw document to verified answer
                </h2>
              </div>
              <div className="flex items-center gap-3 font-mono text-xs text-muted-foreground">
                <span>
                  FRAME {currentFrame.step} / 0{PIPELINE_FRAMES.length}
                </span>
                <div className="h-1.5 w-28 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-accent transition-all duration-150"
                    style={{
                      width: `${Math.max(
                        15,
                        Math.round(
                          Math.max(
                            scrollProgress,
                            (activeFrame + 1) / PIPELINE_FRAMES.length,
                          ) * 100,
                        ),
                      )}%`,
                    }}
                  />
                </div>
              </div>
            </div>

            <div className="mt-10 grid gap-8 lg:grid-cols-12 lg:items-start">
              <div className="space-y-3 lg:col-span-5">
                {PIPELINE_FRAMES.map((frame, idx) => {
                  const isActive = idx === activeFrame;
                  return (
                    <button
                      key={frame.step}
                      type="button"
                      onClick={() => setActiveFrame(idx)}
                      className={`w-full rounded-2xl border p-4 text-left transition-all duration-300 ${
                        isActive
                          ? "border-accent/50 bg-background shadow-md ring-1 ring-accent/20"
                          : "border-border bg-surface/70 opacity-70 hover:opacity-100"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs font-semibold text-accent">
                          {frame.step} · {frame.badge}
                        </span>
                        <span className="font-mono text-[11px] text-muted-foreground">
                          {frame.metric}
                        </span>
                      </div>
                      <h3 className="mt-1.5 text-sm font-semibold text-foreground">
                        {frame.title}
                      </h3>
                      {isActive ? (
                        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                          {frame.desc}
                        </p>
                      ) : null}
                    </button>
                  );
                })}
              </div>

              <div className="lg:sticky lg:top-24 lg:col-span-7">
                <div className="relative overflow-hidden rounded-3xl border border-border bg-background p-6 shadow-xl sm:p-8">
                  <div
                    className={`pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-gradient-to-br ${currentFrame.accent} opacity-15 blur-3xl transition-all duration-500`}
                  />

                  <div className="flex items-center justify-between">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-xs font-medium ${currentFrame.ring}`}
                    >
                      <Zap size={12} /> Stage {currentFrame.step}:{" "}
                      {currentFrame.badge}
                    </span>
                    <span className="font-mono text-xs font-semibold text-foreground">
                      {currentFrame.metric}
                    </span>
                  </div>

                  <h3 className="mt-5 text-2xl font-semibold tracking-tight">
                    {currentFrame.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {currentFrame.desc}
                  </p>

                  <div className="mt-7 grid gap-3 sm:grid-cols-3">
                    {currentFrame.nodes.map((node, nIdx) => (
                      <div
                        key={node.label}
                        className="rounded-2xl border border-border bg-surface p-4 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:border-accent/40"
                      >
                        <div className="flex items-center justify-between font-mono text-[11px] text-muted-foreground">
                          <span>0{nIdx + 1}</span>
                          <span className="h-2 w-2 rounded-full bg-emerald-500" />
                        </div>
                        <p className="mt-2.5 text-xs font-semibold text-foreground">
                          {node.label}
                        </p>
                        <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                          {node.meta}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* VIBRANT BENTO CAPABILITIES GRID */}
        <section
          id="capabilities"
          className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28"
        >
          <div className="max-w-2xl">
            <p className="font-mono text-xs font-semibold uppercase tracking-widest text-accent">
              Not a Basic RAG Chatbot
            </p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
              Built end-to-end for verifiable knowledge work
            </h2>
          </div>

          <div className="bento-grid mt-10 grid gap-4 md:grid-cols-6">
            <div className="bento-card rounded-3xl border border-border bg-gradient-to-br from-sky-500/10 via-surface to-surface p-6 md:col-span-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-sky-500/30 bg-sky-500/15 text-sky-600 dark:text-sky-300">
                <FlaskConical size={19} />
              </div>
              <h3 className="mt-4 text-lg font-semibold">
                From-Scratch Eval Engine & CI Gate
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                Pure-Python Recall@K, MRR, and NDCG@K paired with strict-JSON
                LLM-as-a-Judge faithfulness, relevancy, and citation checks.
              </p>
              <div className="mt-4 flex flex-wrap gap-2 font-mono text-[11px]">
                <span className="rounded-full border border-border bg-background px-2.5 py-0.5">
                  Recall@5
                </span>
                <span className="rounded-full border border-border bg-background px-2.5 py-0.5">
                  Faithfulness
                </span>
                <span className="rounded-full border border-border bg-background px-2.5 py-0.5">
                  + Eval Flywheel
                </span>
              </div>
            </div>

            <div className="bento-card rounded-3xl border border-border bg-gradient-to-br from-violet-500/10 via-surface to-surface p-6 md:col-span-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-violet-500/30 bg-violet-500/15 text-violet-600 dark:text-violet-300">
                <Brain size={19} />
              </div>
              <h3 className="mt-4 text-lg font-semibold">
                4-Tier Cognitive Memory
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                Semantic facts, episodic summaries, and procedural rules
                reconciled asynchronously via ARQ with automatic conflict
                superseding.
              </p>
              <div className="mt-4 inline-flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-1.5 font-mono text-[11px]">
                <span className="line-through opacity-55">ap-southeast-2</span>
                <GitBranch size={12} className="text-violet-500" />
                <span className="font-semibold text-emerald-600 dark:text-emerald-400">
                  ap-south-1 (active)
                </span>
              </div>
            </div>

            <div className="bento-card rounded-3xl border border-border bg-surface p-6 md:col-span-2">
              <Network size={20} className="text-emerald-500" />
              <h3 className="mt-4 text-base font-semibold">
                Light GraphRAG in Postgres
              </h3>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                1–2 hop recursive SQL CTEs over extracted entity triples—no
                Neo4j cluster required, honoring DocumentGrant RBAC.
              </p>
            </div>

            <div className="bento-card rounded-3xl border border-border bg-surface p-6 md:col-span-2">
              <Database size={20} className="text-blue-500" />
              <h3 className="mt-4 text-base font-semibold">
                Multi-Replica Redis Scaling
              </h3>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                Redis Pub/Sub stream cancellation across replicas, RBAC-scoped
                TTL query cache, trusted proxy CIDRs, and Resend/SMTP invites.
              </p>
            </div>

            <div className="bento-card rounded-3xl border border-border bg-surface p-6 md:col-span-2">
              <Cpu size={20} className="text-amber-500" />
              <h3 className="mt-4 text-base font-semibold">
                Isolated OCR & Research Agent
              </h3>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                Dual ARQ queues (ingest-fast / ingest-ocr) with vision-LLM
                table fallback, 8-step query decomposition, and incremental
                GitHub sync.
              </p>
            </div>
          </div>
        </section>

        {/* BEFORE vs AFTER v2 UPGRADE COMPARISON */}
        <section
          id="upgrade-diff"
          className="border-y border-border bg-surface/50 py-20"
        >
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="font-mono text-xs font-semibold uppercase tracking-widest text-accent">
                  Architecture Evolution
                </p>
                <h2 className="mt-2 text-3xl font-semibold tracking-tight">
                  What changed in Production Upgrade v2
                </h2>
              </div>
              <Link
                href="/docs/upgrade"
                className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
              >
                Full technical changelog <ArrowUpRight size={13} />
              </Link>
            </div>

            <div className="diff-table mt-8 overflow-hidden rounded-2xl border border-border bg-background">
              <div className="grid grid-cols-12 border-b border-border bg-muted/40 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                <div className="col-span-3">Layer</div>
                <div className="col-span-4">Baseline v1</div>
                <div className="col-span-5 text-accent">RAG Workspace v2</div>
              </div>
              <div className="divide-y divide-border text-xs">
                {UPGRADE_DIFF.map((row) => (
                  <div
                    key={row.layer}
                    className="diff-row grid grid-cols-1 gap-2 px-4 py-3.5 sm:grid-cols-12 sm:gap-4"
                  >
                    <div className="font-semibold text-foreground sm:col-span-3">
                      {row.layer}
                    </div>
                    <div className="text-muted-foreground sm:col-span-4">
                      {row.before}
                    </div>
                    <div className="font-medium text-foreground sm:col-span-5">
                      {row.after}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* VERIFIED TELEMETRY STRIP */}
        <section className="metrics-strip py-16">
          <div className="mx-auto grid max-w-6xl gap-4 px-4 sm:grid-cols-2 sm:px-6 lg:grid-cols-4">
            {[
              { icon: CheckCircle2, value: "104/104", label: "Backend Pytest Suite Passing" },
              { icon: FileSearch, value: "100%", label: "Benchmark Recall@5" },
              { icon: Lock, value: "Zero-Leak", label: "RBAC-Scoped Cache & Graph" },
              { icon: Server, value: "9 Services", label: "Local-First Docker Compose Stack" },
            ].map((stat) => {
              const Icon = stat.icon;
              return (
                <div
                  key={stat.label}
                  className="metric-tile rounded-2xl border border-border bg-surface p-5"
                >
                  <Icon size={16} className="text-accent" />
                  <p className="mt-3 font-mono text-2xl font-semibold tracking-tight">
                    {stat.value}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {stat.label}
                  </p>
                </div>
              );
            })}
          </div>
        </section>

        {/* CLOSING CTA */}
        <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
          <div className="relative overflow-hidden rounded-3xl border border-border bg-gradient-to-br from-blue-600/12 via-violet-600/8 to-surface p-8 text-center sm:p-14">
            <Layers size={22} className="mx-auto text-accent" />
            <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight sm:text-4xl">
              Inspect every citation behind every answer.
            </h2>
            <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground sm:text-base">
              Create a workspace, run your first evaluation suite, or browse the
              live v2 architecture documentation and interactive floorplan.
            </p>
            <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
              <Link
                href={isAuthed ? "/dashboard" : "/register"}
                className="inline-flex h-11 items-center gap-2 rounded-xl bg-foreground px-6 text-sm font-medium text-background shadow-md transition-transform hover:-translate-y-0.5"
              >
                {isAuthed ? "Dashboard" : "Get Started"}{" "}
                <ArrowRight size={15} />
              </Link>
              <Link
                href="/docs/upgrade"
                className="inline-flex h-11 items-center gap-2 rounded-xl border border-border bg-background px-5 text-sm font-medium text-foreground transition-colors hover:bg-muted"
              >
                Upgrade Documentation <ArrowUpRight size={15} />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border py-8 text-xs text-muted-foreground">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 sm:px-6">
          <span>RAG Workspace v2 · Multi-tenant grounded knowledge engine</span>
          <div className="flex items-center gap-5">
            <Link href="/docs" className="hover:text-foreground">
              Docs
            </Link>
            <Link href="/docs/upgrade" className="hover:text-foreground">
              Upgrade Notes
            </Link>
            <Link href="/floorplan" className="hover:text-foreground">
              Floorplan
            </Link>
            <Link
              href={isAuthed ? "/dashboard" : "/login"}
              className="hover:text-foreground"
            >
              {isAuthed ? "Dashboard" : "Sign in"}
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
