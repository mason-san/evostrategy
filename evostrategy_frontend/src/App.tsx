import { useEffect, useState } from "react";

type IconName = "brain" | "folder" | "document" | "orders" | "payment" | "ledger" | "reports" | "clip" | "swap" | "arrow" | "upload" | "chevron" | "plus" | "check" | "terminal" | "shield" | "verified" | "hub" | "link" | "download";

const documentTags: Array<{ label: string; icon: IconName }> = [
  { label: "Invoices", icon: "document" },
  { label: "Purchase Orders", icon: "orders" },
  { label: "Payments", icon: "payment" },
  { label: "Ledgers", icon: "ledger" },
  { label: "Reports", icon: "reports" },
  { label: "Other business files", icon: "clip" },
];

const intelligenceTags = ["Verified data", "Business intelligence", "Insights", "Forecasts", "Strategic plans"];

function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (name) {
    case "brain":
      return <svg {...common}><path d="M9 4.5A3.5 3.5 0 0 0 5.5 8v.5A3.5 3.5 0 0 0 4 11.5 3.5 3.5 0 0 0 7.5 15H9v4l3-2 3 2v-4h1.5a3.5 3.5 0 0 0 3.5-3.5 3.5 3.5 0 0 0-1.5-3V8A3.5 3.5 0 0 0 15 4.5a3 3 0 0 0-6 0Z" /><path d="M9 8h.01M15 8h.01M9 12h.01M15 12h.01" /></svg>;
    case "folder":
      return <svg {...common}><path d="M3.5 6.5h6l2 2h9v9h-17z" /><path d="M3.5 6.5v-2h5l2 2" /></svg>;
    case "document":
      return <svg {...common}><path d="M6 3.5h8l4 4v13H6z" /><path d="M14 3.5v4h4M9 12h6M9 16h6" /></svg>;
    case "orders":
      return <svg {...common}><path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5" /></svg>;
    case "payment":
      return <svg {...common}><rect x="3.5" y="6" width="17" height="12" rx="1.5" /><path d="M3.5 10h17M7 14h3" /></svg>;
    case "ledger":
      return <svg {...common}><path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5" /></svg>;
    case "reports":
      return <svg {...common}><path d="M5 19V9M12 19V5M19 19v-7" /></svg>;
    case "clip":
      return <svg {...common}><path d="m9 8 6-3a3 3 0 1 1 2.5 5.5l-7 4A2.5 2.5 0 0 1 8 10l7-4" /></svg>;
    case "swap":
      return <svg {...common}><path d="M7 7h11l-3-3M17 17H6l3 3M18 7l-3 3M6 17l3-3" /></svg>;
    case "arrow":
      return <svg {...common}><path d="M5 12h13M13 6l6 6-6 6" /></svg>;
    case "upload":
      return <svg {...common}><path d="M12 16V4M8 8l4-4 4 4M5 15v4h14v-4" /></svg>;
    case "chevron":
      return <svg {...common}><path d="m7 10 5 5 5-5" /></svg>;
    case "plus":
      return <svg {...common}><path d="M12 5v14M5 12h14" /></svg>;
    case "check":
      return <svg {...common}><path d="m5 12 4 4L19 6" /></svg>;
    case "terminal":
      return <svg {...common}><rect x="3.5" y="5" width="17" height="14" rx="1.5" /><path d="m7 9 2.5 2L7 13M12 14h4" /></svg>;
    case "shield":
      return <svg {...common}><path d="M12 3 19 6v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z" /><path d="m9 12 2 2 4-4" /></svg>;
    case "verified":
      return <svg {...common}><path d="m12 3 2 1.2 2.4-.2 1.4 2 2.1 1.2-.2 2.4 1.2 2-1.2 2 .2 2.4-2.1 1.2-1.4 2-2.4-.2L12 21l-2-1.2-2.4.2-1.4-2-2.1-1.2.2-2.4-1.2-2 1.2-2-.2-2.4 2.1-1.2 1.4-2 2.4.2z" /><path d="m8.5 12 2.2 2.2 4.8-4.8" /></svg>;
    case "hub":
      return <svg {...common}><circle cx="12" cy="12" r="2.5" /><circle cx="5" cy="6" r="1.5" /><circle cx="19" cy="6" r="1.5" /><circle cx="5" cy="18" r="1.5" /><path d="m10.2 10.5-4-3M13.8 10.5l4-3M10.2 13.5l-4 3" /></svg>;
    case "link":
      return <svg {...common}><path d="M9 15 15 9M7 17H5a3 3 0 0 1 0-6h3M17 7h2a3 3 0 0 1 0 6h-3" /></svg>;
    case "download":
      return <svg {...common}><path d="M12 4v10M8 10l4 4 4-4M5 19h14" /></svg>;
  }
}

function Brand({ setupStep }: { setupStep?: 2 | 3 }) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark"><Icon name="brain" size={22} /></div>
        <span className="brand-name">EvoStrategy</span>
        <span className="version">v2.4</span>
      </div>
      {setupStep ? (
        <div className="setup-header">
          <span className="setup-progress">
            {Array.from({ length: 4 }, (_, index) => (
              <span className={index < setupStep ? "progress-active" : ""} key={index} />
            ))}
          </span>
          <span>Setup Flow</span>
        </div>
      ) : <div className="step-indicator"><span className="step-dot" />Step 1 of 4</div>}
    </header>
  );
}

function DocumentPanel() {
  return (
    <section className="diagram-panel">
      <div className="panel-heading">
        <span>YOUR DOCUMENTS</span>
        <Icon name="folder" size={20} />
      </div>
      <div className="panel-rule" />
      <div className="tags document-tags">
        {documentTags.map((tag) => <span className="tag" key={tag.label}><Icon name={tag.icon} size={14} />{tag.label}</span>)}
      </div>
      <div className="panel-footnote"><span className="footnote-dot" />Raw structured &amp; unstructured<br />formats</div>
    </section>
  );
}

function EnginePanel() {
  return (
    <div className="engine-panel">
      <div className="engine-line"><span /></div>
      <div className="engine-card">
        <div className="engine-icon"><Icon name="swap" size={21} /></div>
        <div className="engine-title">EVOSTRATEGY</div>
        <div className="engine-subtitle">INTELLIGENCE ENGINE</div>
      </div>
      <div className="engine-arrow"><Icon name="arrow" size={18} /></div>
    </div>
  );
}

function IntelligencePanel() {
  return (
    <section className="diagram-panel intelligence-panel">
      <div className="panel-heading accent-heading">
        <span>YOUR COMPANY BRAIN</span>
        <Icon name="brain" size={20} />
      </div>
      <div className="panel-rule" />
      <div className="tags intelligence-tags">
        {intelligenceTags.map((label) => <span className="tag" key={label}><span className="tag-dot" />{label}</span>)}
      </div>
      <div className="panel-footnote accent-footnote"><span className="footnote-dot" />Continuous reconciliation<br />model</div>
    </section>
  );
}

type UploadFile = { file: File; name: string; size: string; type: string };
type PipelineStep = { key: string; label: string; detail: string; state: "pending" | "active" | "complete" | "failed" };
type IngestionJob = { job_id: string; status: "queued" | "running" | "completed" | "failed"; progress: number; files_received: number; files_processed: number; steps: PipelineStep[]; message: string; error?: string | null };
const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

function UploadScreen({ onBack, onNext }: { onBack: () => void; onNext: (files: File[]) => Promise<void> }) {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [uploadError, setUploadError] = useState("");

  const addFiles = (selectedFiles: FileList | File[]) => {
    const nextFiles = Array.from(selectedFiles).map((file) => ({
      file,
      name: file.name,
      size: `${(file.size / 1024 / 1024).toFixed(1)} MB`,
      type: file.type || "Business document",
    }));
    setFiles((current) => [...current, ...nextFiles]);
  };

  const submitFiles = async () => {
    if (!files.length) {
      setUploadError("Add at least one document before continuing.");
      return;
    }
    setUploadError("");
    try {
      await onNext(files.map((entry) => entry.file));
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Documents could not be queued for ingestion.");
    }
  };

  return (
    <main className="app-shell upload-shell">
      <Brand setupStep={2} />
      <section className="upload-content">
        <div className="upload-eyebrow"><span className="step-dot" />Step 2 of 4 · Document Ingestion</div>
        <h1>Bring your company data together.</h1>
        <p>Upload the documents you already use to run your business. EvoStrategy will organize and<br className="desktop-break" /> reconcile them automatically.</p>

        <label
          className={`dropzone${isDragging ? " is-dragging" : ""}`}
          onDragEnter={(event) => { event.preventDefault(); setIsDragging(true); }}
          onDragOver={(event) => { event.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(event) => { event.preventDefault(); setIsDragging(false); addFiles(event.dataTransfer.files); }}
        >
          <input type="file" accept=".pdf,.csv,.xlsx,.docx" multiple onChange={(event) => event.target.files && addFiles(event.target.files)} />
          <span className="upload-icon"><Icon name="upload" size={25} /></span>
          <span className="drop-title">Drop your files here or <strong>browse your computer</strong></span>
          <span className="drop-help">PDF, CSV, XLSX, DOCX and common business documents (Source-faithful parsing)</span>
          <span className="drop-note">⌘ &nbsp; Automated classification · no manual tagging required</span>
        </label>

        <div className="classification-row">
          <span className="mono-heading">Autonomous Classification</span>
          <span className="active-chip">AI Cluster Engine Active</span>
          <span className="manual-note">No manual tagging required</span>
        </div>
        <div className="source-list">
          {files.length === 0 && <div className="empty-source-state">No documents added yet.</div>}
          {files.map((file) => (
            <div className="source-row uploaded-row" key={`${file.name}-${file.size}`}>
              <div className="source-icon"><Icon name="clip" size={18} /></div>
              <div className="source-copy">
                <div className="source-title">{file.name} <span>{file.type}</span></div>
                <div className="source-meta">{file.size} <b>•</b> Added from your computer</div>
              </div>
              <span className="ready-badge"><span />✓ Ready</span>
            </div>
          ))}
        </div>
        <button className="add-documents" onClick={() => document.querySelector<HTMLInputElement>(".dropzone input")?.click()}>
          <Icon name="plus" size={17} /> Add more documents
        </button>
        {uploadError && <p className="upload-error">{uploadError}</p>}
        <div className="onboarding-actions">
          <button className="back-button" onClick={onBack}>
            <span className="back-chevron">←</span> Back
          </button>
          <button className="next-button" onClick={submitFiles} disabled={!files.length}>
            Next <Icon name="arrow" size={18} />
          </button>
        </div>
      </section>
    </main>
  );
}

const processingSteps = [
  { label: "Documents received", detail: "Files available", state: "complete" },
  { label: "Extracting business information", detail: "Source-faithful fields", state: "complete" },
  { label: "Reconciling records", detail: "Reviewable comparisons", state: "complete" },
  { label: "Building company intelligence", detail: "Preparing your workspace", state: "active" },
  { label: "Preparing your workspace", detail: "Next", state: "pending" },
] as const;

function ProcessingScreen({ jobId, onBack, onNext }: { jobId: string; onBack: () => void; onNext: () => void }) {
  const [job, setJob] = useState<IngestionJob | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/ingestion/jobs/${jobId}`);
        if (!response.ok) throw new Error("Unable to read ingestion progress.");
        if (!cancelled) setJob(await response.json() as IngestionJob);
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : "Unable to read ingestion progress.";
          setJob({ job_id: jobId, status: "failed", progress: 0, files_received: 0, files_processed: 0, steps: [], message, error: message });
        }
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), 800);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [jobId]);

  const steps = job?.steps.length ? job.steps : processingSteps.map((step) => ({ key: step.label, ...step }));
  const currentProgress = job?.progress ?? 0;
  const isComplete = job?.status === "completed";
  const isFailed = job?.status === "failed";

  return (
    <main className="app-shell processing-shell">
      <Brand setupStep={3} />
      <section className="processing-content">
        <div className="processing-eyebrow"><Icon name="brain" size={15} /> STEP 3 OF 4 · KNOWLEDGE SYNTHESIS</div>
        <h1>Building your company brain...</h1>
        <p>We’re organizing your documents and creating a verified picture of your<br className="desktop-break" /> business.</p>

        <section className="processing-card">
          <div className="processing-summary">
            <span>Organizing your uploaded documents</span>
            <span className="summary-separator">•</span>
            <span>Preparing structured records</span>
            <span className="completion-pill">{currentProgress}% <small>{isFailed ? "failed" : "complete"}</small></span>
          </div>
          <div className="processing-track"><span style={{ width: `${currentProgress}%` }} /></div>
          <div className="processing-steps">
            {steps.map((step) => (
              <div className={`processing-step ${step.state}`} key={step.label}>
                <span className="processing-status">
                  {step.state === "complete" ? <Icon name="check" size={14} /> : step.state === "active" ? <span /> : "○"}
                </span>
                <strong>{step.label}</strong>
                <span className="processing-detail">{step.detail}</span>
              </div>
            ))}
          </div>
          <div className="synthesis-stream">
            <div className="stream-heading"><span><Icon name="terminal" size={15} /> LIVE SYNTHESIS<br />STREAM</span><span className="kernel-status">● Local processing state</span></div>
            <div className="stream-log"><span>{job ? `${job.files_processed}/${job.files_received}` : "—"}</span><b>{isFailed ? "!" : "✓"}</b> {job?.message ?? "Waiting for ingestion service"}{!isComplete && !isFailed && <span className="cursor-block" />}</div>
            <div className="stream-log"><span>STATUS</span><b>→</b> {isFailed ? job.error : isComplete ? "All documents processed" : "Processing uploaded documents"}{!isComplete && !isFailed && <span className="cursor-block" />}</div>
            <div className="stream-divider" />
            <div className="stream-note"><Icon name="shield" size={14} /> Source traceability remains available for review</div>
          </div>
        </section>

        <div className="processing-notes">
          <div><Icon name="document" size={16} /><strong>Source-faithful extraction</strong><span>Labels remain traceable to uploaded documents.</span></div>
          <div><Icon name="swap" size={16} /><strong>Deterministic comparison</strong><span>Reconciliation runs through the existing engine.</span></div>
          <div><Icon name="shield" size={16} /><strong>Reviewable evidence</strong><span>Records can be checked before analytics.</span></div>
        </div>
        <p className={`processing-disclaimer${isFailed ? " processing-error" : ""}`}>{isFailed ? job.error : isComplete ? "Ingestion complete. Review the source-backed workspace summary." : "Progress reflects the active ingestion service stages."}</p>
        <div className="processing-actions">
          <button className="processing-back" onClick={onBack}>← Back to documents</button>
          <button className="next-button processing-next" onClick={onNext} disabled={!isComplete}>Next <Icon name="arrow" size={18} /></button>
        </div>
      </section>
    </main>
  );
}

type ReadyMetric = { label: string; value: string; detail: string; tone?: "success" | "attention" };

const readySummary: ReadyMetric[] = [
  { label: "Sources analyzed", value: "30", detail: "documents processed" },
  { label: "Knowledge entities", value: "1,284", detail: "records understood" },
  { label: "Audit accuracy", value: "96%", detail: "successfully reconciled", tone: "success" },
  { label: "Discrepancies", value: "42", detail: "items need your attention", tone: "attention" },
] as const;

const readyCategories = [
  "Revenue streams",
  "Customers & accounts",
  "Vendors & supply",
  "Transactions",
  "Payments & aging",
  "Orders",
  "Business trends & seasonality",
];

function ReadyScreen({ onBack }: { onBack: () => void }) {
  return (
    <main className="app-shell ready-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><Icon name="brain" size={20} /></div>
          <div className="ready-brand-copy"><span className="brand-name">EvoStrategy</span><span>Enterprise Intelligence v2.4</span></div>
        </div>
        <div className="ready-status"><span />Synthesis complete</div>
      </header>

      <section className="ready-content">
        <div className="ready-intro">
          <div className="ready-step">Step 4 of 4 · Intelligence ready</div>
          <div className="success-ring"><div><Icon name="check" size={27} /></div></div>
          <h1>Your company brain is ready.</h1>
          <p>EvoStrategy has built a verified intelligence layer from your business data.</p>
        </div>

        <section className="ready-card">
          <div className="ready-card-heading">
            <span><Icon name="verified" size={16} /> Ingestion &amp; synthesis summary</span>
            <small>Validated 12s ago</small>
          </div>
          <div className="ready-metrics">
            {readySummary.map((metric) => (
              <div className={`ready-metric ${metric.tone ?? ""}`} key={metric.label}>
                <span className="metric-label">{metric.tone === "success" && <i />} {metric.label}</span>
                <strong>{metric.value}</strong>
                <small>{metric.detail}</small>
                {metric.tone === "attention" && <em>Review anytime</em>}
              </div>
            ))}
          </div>
        </section>

        <section className="ready-card understanding-card">
          <h2><Icon name="hub" size={17} /> EvoStrategy now understands:</h2>
          <p>Multi-layered ontology mapped across transactional databases, general ledgers, CRM objects, and supply pipelines.</p>
          <div className="category-list">
            {readyCategories.map((category) => <span key={category}><i />{category}</span>)}
          </div>
        </section>

        <div className="source-notice"><Icon name="link" size={17} /> All answers in your workspace link directly back to verified source records.</div>

        <div className="ready-actions">
          <button className="report-button"><Icon name="download" size={16} /> Download ingestion report</button>
          <button className="workspace-button" onClick={onBack}>Enter your workspace <Icon name="arrow" size={18} /></button>
        </div>
      </section>
    </main>
  );
}

export function App() {
  const [screen, setScreen] = useState<"welcome" | "upload" | "processing" | "ready">("welcome");
  const [jobId, setJobId] = useState("");

  if (screen === "ready") {
    return <ReadyScreen onBack={() => setScreen("processing")} />;
  }
  if (screen === "processing") {
    return <ProcessingScreen jobId={jobId} onBack={() => setScreen("upload")} onNext={() => setScreen("ready")} />;
  }
  if (screen === "upload") {
    return <UploadScreen
      onBack={() => setScreen("welcome")}
      onNext={async (files) => {
        const formData = new FormData();
        files.forEach((file) => formData.append("files", file));
        let response: Response;
        try {
          response = await fetch(`${API_BASE_URL}/api/ingestion/jobs`, { method: "POST", body: formData });
        } catch {
          throw new Error("The ingestion service is unavailable. Start the FastAPI backend on port 8000 and try again.");
        }
        if (!response.ok) throw new Error("Documents could not be queued for ingestion.");
        const job = await response.json() as IngestionJob;
        setJobId(job.job_id);
        setScreen("processing");
      }}
    />;
  }

  return (
    <main className="app-shell">
      <Brand />
      <section className="hero">
        <div className="eyebrow"><span className="shield">♢</span>Enterprise Intelligence OS</div>
        <h1>Let’s build your company brain.</h1>
        <p>Connect your business documents and EvoStrategy will organize, reconcile, and build a<br className="desktop-break" /> verified understanding of your company.</p>
      </section>

      <section className="diagram">
        <DocumentPanel />
        <EnginePanel />
        <IntelligencePanel />
      </section>

      <div className="actions">
        <button className="primary-button" onClick={() => setScreen("upload")}>
          Get started <Icon name="arrow" size={20} />
        </button>
        <button className="later-button" onClick={() => setScreen("welcome")}>I’ll do this later</button>
      </div>
    </main>
  );
}
