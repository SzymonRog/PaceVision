import { ResultsView } from "@/components/results/results-view";

export default function ResultsPage({ params }: { params: { id: string } }) {
  return <ResultsView jobId={params.id} />;
}
