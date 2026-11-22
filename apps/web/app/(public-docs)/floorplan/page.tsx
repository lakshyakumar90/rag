export const metadata = {
  title: "Floorplan | RAG Documentation",
  description: "Interactive architecture map and workflow tours for RAG Workspace.",
};

export default function Floorplan() {
  return (
    <main id="main" className="floorplan-page">
      <h1 className="floorplan-page-title">RAG Workspace floorplan</h1>
      <iframe className="floorplan-canvas" title="RAG architecture floorplan" src="/floorplan/index.html" />
    </main>
  );
}
