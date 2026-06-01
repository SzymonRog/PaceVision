import { SiteHeader } from "@/components/site-header";
import { UploadForm } from "@/components/upload/upload-form";

export default function Home() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />

      <main className="mx-auto max-w-[1400px] px-6 md:px-10">
        {/* Hero: asymmetric split, generous whitespace, no icons */}
        <section className="grid items-start gap-x-16 gap-y-12 py-16 md:py-24 lg:grid-cols-[1fr_minmax(380px,460px)] lg:py-32">
          <div className="flex max-w-2xl flex-col gap-8">
            <p className="text-sm font-medium uppercase tracking-[0.18em] text-primary">
              Side-view footage only
            </p>

            <h1 className="text-balance font-display text-5xl font-semibold leading-[1.05] tracking-tight md:text-6xl lg:text-7xl">
              Running form,{" "}
              <span className="text-primary">measured</span>{" "}
              frame by frame.
            </h1>

            <p className="max-w-xl text-pretty text-lg leading-relaxed text-muted-foreground">
              Drop in a side-view clip. Eleven joint angles get tracked every
              frame, scored against biomechanics references, and turned into
              coaching you can act on.
            </p>

            <dl className="mt-2 grid max-w-lg grid-cols-3 gap-8 border-t border-border pt-8">
              <div>
                <dt className="tabular text-3xl font-semibold tracking-tight">11</dt>
                <dd className="mt-1 text-sm text-muted-foreground">joint angles</dd>
              </div>
              <div>
                <dt className="tabular text-3xl font-semibold tracking-tight">0–100</dt>
                <dd className="mt-1 text-sm text-muted-foreground">form score</dd>
              </div>
              <div>
                <dt className="tabular text-3xl font-semibold tracking-tight">8</dt>
                <dd className="mt-1 text-sm text-muted-foreground">problem detectors</dd>
              </div>
            </dl>
          </div>

          {/* Upload panel */}
          <div className="lg:sticky lg:top-24">
            <div className="rounded-lg border border-border bg-surface p-6">
              <h2 className="mb-1 font-display text-lg font-semibold tracking-tight">
                Analyze a clip
              </h2>
              <p className="mb-5 text-sm text-muted-foreground">
                MP4, MOV, AVI, MKV or WEBM. Up to 500 MB.
              </p>
              <UploadForm />
            </div>
          </div>
        </section>

        {/* How it works — vertical numbered steps, different layout family */}
        <section className="border-t border-border py-16 md:py-24">
          <h2 className="max-w-2xl font-display text-3xl font-semibold tracking-tight md:text-4xl">
            From clip to coaching in three passes.
          </h2>
          <div className="mt-12 grid gap-px overflow-hidden rounded-lg border border-border bg-border md:grid-cols-3">
            {[
              {
                k: "Track",
                d: "Pose estimation locks onto your body and follows every landmark through the whole clip, smoothing out the jitter.",
              },
              {
                k: "Measure",
                d: "Knee, hip, ankle, arm and trunk angles are computed at the gait phases that matter, then compared to reference ranges.",
              },
              {
                k: "Diagnose",
                d: "Stride-by-stride detectors flag overstriding, heel strike, trunk lean and more, each with a plain-language fix.",
              },
            ].map((step, i) => (
              <div key={step.k} className="bg-surface p-8">
                <span className="tabular text-sm font-medium text-primary">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h3 className="mt-4 font-display text-xl font-semibold tracking-tight">
                  {step.k}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {step.d}
                </p>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-[1400px] flex-col gap-1 px-6 py-10 text-sm text-muted-foreground md:px-10">
          <p>A running biomechanics analysis tool.</p>
          <p className="text-xs">Best results with a tripod-steady side-on view at a consistent distance.</p>
        </div>
      </footer>
    </div>
  );
}
